"""Generate dovetail-equipped roBa v3 bottoms and a removable 7 degree stand."""

from __future__ import annotations

import math
import os
from pathlib import Path
import sys

import cadquery as cq

sys.dont_write_bytecode = True

from cq_verify import VerificationSpec, export_verified


# Frozen design parameters (millimetres / degrees).
TENT_ANGLE_DEG = 7.0
STAND_X_MIN = -38.0
STAND_X_MAX = 38.0
STAND_Y_MIN = -33.0
STAND_Y_MAX = 39.0
MIN_HEIGHT = 3.0

CONNECTOR_X_CENTERS = (-30.0, 30.0)
SUPPORT_RAIL_WIDTH = 16.0
SUPPORT_RAIL_Y_MIN = -33.0
SUPPORT_RAIL_Y_MAX = 33.0
STOP_BAR_Y_MIN = 27.0
STOP_BAR_Y_MAX = 39.0

DOVETAIL_BASE_WIDTH = 7.0
DOVETAIL_HEAD_WIDTH = 10.0
DOVETAIL_HEIGHT = 2.4
DOVETAIL_EMBED = 0.2
DOVETAIL_LENGTH = 48.0
DOVETAIL_CENTER_Y = 3.0
DOVETAIL_CLEARANCE = 0.25  # Clearance on each side.
GROOVE_DEPTH_CLEARANCE = 0.25
GROOVE_Y_MIN = -34.0  # Extends past the stand for an open insertion end.
GROOVE_Y_MAX = 27.0   # The crossbar forms the positive stop.

HERE = Path(__file__).resolve().parent
CASE_DIR = HERE.parent
OUTPUT_DIR = HERE / "generated"

ORIGINAL_VOLUME = {
    "L": 16973.651477338793,
    "R": 20008.610499244704,
}


def stand_height(x: float) -> float:
    return MIN_HEIGHT + (x - STAND_X_MIN) * math.tan(math.radians(TENT_ANGLE_DEG))


def _outer_face(shape: cq.Shape) -> cq.Face:
    candidates = [
        face
        for face in shape.Faces()
        if face.geomType() == "PLANE" and face.normalAt().z < -0.9
    ]
    if not candidates:
        raise RuntimeError("no downward planar exterior face found")
    return max(candidates, key=lambda face: face.Area())


def _connector_plane(shape: cq.Shape, side: str) -> cq.Plane:
    """Return a bottom-surface plane whose +X direction points inward."""

    face = _outer_face(shape)
    normal = face.normalAt().normalized()
    center = face.Center()
    z_at_origin = center.z - (
        normal.x * (0.0 - center.x) + normal.y * (0.0 - center.y)
    ) / normal.z

    inward = cq.Vector(1.0 if side == "L" else -1.0, 0.0, 0.0)
    x_direction = (inward - normal.multiply(inward.dot(normal))).normalized()
    return cq.Plane(
        origin=(0.0, 0.0, z_at_origin),
        xDir=x_direction,
        normal=normal,
    )


def _male_dovetail_local(x_center: float) -> cq.Shape:
    half_base = DOVETAIL_BASE_WIDTH / 2
    half_head = DOVETAIL_HEAD_WIDTH / 2
    return (
        cq.Workplane("XZ")
        .moveTo(x_center - half_base, -DOVETAIL_EMBED)
        .lineTo(x_center + half_base, -DOVETAIL_EMBED)
        .lineTo(x_center + half_head, DOVETAIL_HEIGHT)
        .lineTo(x_center - half_head, DOVETAIL_HEIGHT)
        .close()
        .extrude(DOVETAIL_LENGTH / 2, both=True)
        .translate((0.0, DOVETAIL_CENTER_Y, 0.0))
        .val()
    )


def verify_connector_footprint(shape: cq.Shape, plane: cq.Plane) -> None:
    """Require every 1 mm grid point under both rail roots to lie on the outer face."""

    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_OUT
    from OCP.gp import gp_Pnt

    face = _outer_face(shape)
    half_surface_width = (
        DOVETAIL_BASE_WIDTH
        + (DOVETAIL_HEAD_WIDTH - DOVETAIL_BASE_WIDTH)
        * DOVETAIL_EMBED
        / (DOVETAIL_HEIGHT + DOVETAIL_EMBED)
    ) / 2
    y_min = DOVETAIL_CENTER_Y - DOVETAIL_LENGTH / 2
    y_max = DOVETAIL_CENTER_Y + DOVETAIL_LENGTH / 2
    outside: list[tuple[float, float]] = []

    for x_center in CONNECTOR_X_CENTERS:
        x = x_center - half_surface_width
        while x <= x_center + half_surface_width + 1e-9:
            y = y_min
            while y <= y_max + 1e-9:
                point = plane.toWorldCoords((x, y, 0.0))
                classifier = BRepClass_FaceClassifier(
                    face.wrapped,
                    gp_Pnt(*point.toTuple()),
                    1e-6,
                )
                if classifier.State() == TopAbs_OUT:
                    outside.append((x, y))
                y += 1.0
            x += 1.0
    if outside:
        raise RuntimeError(
            f"connector footprint leaves the exterior face at {len(outside)} grid points; "
            f"first={outside[:5]}"
        )
    print("[verify] connector footprint PASS: 1 mm grid entirely on exterior face")


def build_connector_bottom(side: str) -> tuple[cq.Shape, cq.Plane]:
    if side not in {"L", "R"}:
        raise ValueError("side must be 'L' or 'R'")
    original = cq.importers.importStep(str(CASE_DIR / f"bottom_{side}.stp")).val()
    plane = _connector_plane(original, side)
    verify_connector_footprint(original, plane)
    connectors = [
        _male_dovetail_local(x_center).moved(plane.location)
        for x_center in CONNECTOR_X_CENTERS
    ]
    return original.fuse(*connectors), plane


def _groove_cutter(x_center: float) -> cq.Workplane:
    half_throat = DOVETAIL_BASE_WIDTH / 2 + DOVETAIL_CLEARANCE
    half_head = DOVETAIL_HEAD_WIDTH / 2 + DOVETAIL_CLEARANCE
    top_offset = 0.2
    depth = DOVETAIL_HEIGHT + GROOVE_DEPTH_CLEARANCE

    profile = (
        cq.Workplane("XZ")
        .moveTo(
            x_center - half_throat,
            stand_height(x_center - half_throat) + top_offset,
        )
        .lineTo(
            x_center + half_throat,
            stand_height(x_center + half_throat) + top_offset,
        )
        .lineTo(
            x_center + half_head,
            stand_height(x_center + half_head) - depth,
        )
        .lineTo(
            x_center - half_head,
            stand_height(x_center - half_head) - depth,
        )
        .close()
    )
    groove_length = GROOVE_Y_MAX - GROOVE_Y_MIN
    groove_center = (GROOVE_Y_MIN + GROOVE_Y_MAX) / 2
    return profile.extrude(groove_length / 2, both=True).translate(
        (0.0, groove_center, 0.0)
    )


def build_stand() -> cq.Workplane:
    maximum_height = stand_height(STAND_X_MAX)
    wedge = (
        cq.Workplane("XZ")
        .moveTo(STAND_X_MIN, 0.0)
        .lineTo(STAND_X_MAX, 0.0)
        .lineTo(STAND_X_MAX, maximum_height)
        .lineTo(STAND_X_MIN, MIN_HEIGHT)
        .close()
        .extrude((STAND_Y_MAX - STAND_Y_MIN) / 2, both=True)
        .translate((0.0, (STAND_Y_MIN + STAND_Y_MAX) / 2, 0.0))
    )

    rail_length = SUPPORT_RAIL_Y_MAX - SUPPORT_RAIL_Y_MIN
    rail_center_y = (SUPPORT_RAIL_Y_MIN + SUPPORT_RAIL_Y_MAX) / 2
    rails = [
        cq.Workplane("XY")
        .box(
            SUPPORT_RAIL_WIDTH,
            rail_length,
            maximum_height,
            centered=(True, True, False),
        )
        .translate((x_center, rail_center_y, 0.0))
        for x_center in CONNECTOR_X_CENTERS
    ]
    stop_bar = (
        cq.Workplane("XY")
        .box(
            STAND_X_MAX - STAND_X_MIN,
            STOP_BAR_Y_MAX - STOP_BAR_Y_MIN,
            maximum_height,
            centered=(True, True, False),
        )
        .translate((0.0, (STOP_BAR_Y_MIN + STOP_BAR_Y_MAX) / 2, 0.0))
    )
    support_mask = rails[0].union(rails[1]).union(stop_bar)
    stand = wedge.intersect(support_mask)
    for x_center in CONNECTOR_X_CENTERS:
        stand = stand.cut(_groove_cutter(x_center))
    return stand.clean()


def _assembled_male(x_center: float, y_offset: float = 0.0) -> cq.Workplane:
    """Male rail in stand coordinates at its fully inserted position."""

    half_base = DOVETAIL_BASE_WIDTH / 2
    half_head = DOVETAIL_HEAD_WIDTH / 2
    profile = (
        cq.Workplane("XZ")
        .moveTo(
            x_center - half_base,
            stand_height(x_center - half_base) + DOVETAIL_EMBED,
        )
        .lineTo(
            x_center + half_base,
            stand_height(x_center + half_base) + DOVETAIL_EMBED,
        )
        .lineTo(
            x_center + half_head,
            stand_height(x_center + half_head) - DOVETAIL_HEIGHT,
        )
        .lineTo(
            x_center - half_head,
            stand_height(x_center - half_head) - DOVETAIL_HEIGHT,
        )
        .close()
    )
    return profile.extrude(DOVETAIL_LENGTH / 2, both=True).translate(
        (0.0, DOVETAIL_CENTER_Y + y_offset, 0.0)
    )


def verify_mating(stand: cq.Workplane) -> None:
    """Check running clearance and the positive end stop geometrically."""

    running_overlap = sum(
        stand.intersect(_assembled_male(x_center)).val().Volume()
        for x_center in CONNECTOR_X_CENTERS
    )
    if running_overlap > 1e-4:
        raise RuntimeError(f"dovetail running fit overlaps by {running_overlap:.6f} mm^3")

    stop_overlap = sum(
        stand.intersect(_assembled_male(x_center, y_offset=0.2)).val().Volume()
        for x_center in CONNECTOR_X_CENTERS
    )
    if stop_overlap < 1.0:
        raise RuntimeError("dovetail positive stop does not engage")
    if DOVETAIL_HEAD_WIDTH <= DOVETAIL_BASE_WIDTH + 2 * DOVETAIL_CLEARANCE:
        raise RuntimeError("dovetail head is too narrow to remain captured")
    print(
        "[verify] mating PASS: "
        f"running_overlap={running_overlap:.6f} mm^3, "
        f"stop_overlap_at_0.2mm={stop_overlap:.3f} mm^3"
    )


def bottom_verification_spec(side: str, plane: cq.Plane) -> VerificationSpec:
    width_at_surface = DOVETAIL_BASE_WIDTH + (
        (DOVETAIL_HEAD_WIDTH - DOVETAIL_BASE_WIDTH)
        * DOVETAIL_EMBED
        / (DOVETAIL_HEIGHT + DOVETAIL_EMBED)
    )
    added_cross_section = (
        (width_at_surface + DOVETAIL_HEAD_WIDTH) / 2 * DOVETAIL_HEIGHT
    )
    nominal_volume = ORIGINAL_VOLUME[side] + 2 * added_cross_section * DOVETAIL_LENGTH

    material_points = tuple(
        plane.toWorldCoords(
            (x_center, DOVETAIL_CENTER_Y, DOVETAIL_HEIGHT / 2)
        ).toTuple()
        for x_center in CONNECTOR_X_CENTERS
    )
    void_point = plane.toWorldCoords(
        (0.0, DOVETAIL_CENTER_Y, DOVETAIL_HEIGHT / 2)
    ).toTuple()
    return VerificationSpec(
        volume_range=(nominal_volume * 0.99, nominal_volume * 1.01),
        material_points=material_points,
        void_points=(void_point,),
    )


def stand_verification_spec() -> VerificationSpec:
    maximum_height = stand_height(STAND_X_MAX)
    return VerificationSpec(
        volume_range=(17000.0, 20500.0),
        bbox=(
            STAND_X_MAX - STAND_X_MIN,
            STAND_Y_MAX - STAND_Y_MIN,
            maximum_height,
        ),
        bbox_tolerance=0.02,
        material_points=(
            (-36.5, 0.0, stand_height(-36.5) / 2),
            (36.5, 0.0, stand_height(36.5) / 2),
            (0.0, 34.0, stand_height(0.0) / 2),
        ),
        void_points=(
            (0.0, 0.0, 1.0),
            (-30.0, 0.0, stand_height(-30.0) - 1.0),
            (30.0, 0.0, stand_height(30.0) - 1.0),
            (0.0, 0.0, maximum_height + 1.0),
        ),
    )


def main() -> None:
    for side in ("L", "R"):
        bottom, plane = build_connector_bottom(side)
        export_verified(
            bottom,
            OUTPUT_DIR,
            f"roBa_v3_bottom_{side}_dovetail",
            bottom_verification_spec(side, plane),
        )

    stand = build_stand()
    verify_mating(stand)
    export_verified(
        stand,
        OUTPUT_DIR,
        "roBa_v3_tenting_stand_7deg",
        stand_verification_spec(),
    )


if __name__ == "__main__":
    main()
    # CadQuery 2.8 can leave a VTK helper thread alive on this Windows runtime.
    # All exports are closed above, so flush the report and terminate cleanly.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
