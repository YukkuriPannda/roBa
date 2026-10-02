"""Add a pinless folding tenting stand to the roBa v3 bottom cases.

The imported v3 STEP files remain the source for all existing case geometry.
This script only adds two snap sockets and two closed-position detents to each
bottom.  One universal stand fits either side; its axle and stop cams are part
of the print, so no screw, pin, or magnet is required.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq

from cq_verify import VerificationSpec, export_verified


ROOT = Path(__file__).resolve().parents[3]
SOURCE_DIR = ROOT / "case" / "v3"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# Frozen mechanism contract, millimetres and degrees.
BASE_TENT_ANGLE = 4.0
DEPLOY_ANGLE = 65.0
NOMINAL_TOTAL_TENT_ANGLE = 15.0
HINGE_X = 50.0
HINGE_AXIS_OFFSET = 3.0
HINGE_CLIP_Y = 22.0
HINGE_CLIP_LENGTH = 8.0
PIN_RADIUS = 1.50
BORE_RADIUS = 1.70
SOCKET_RADIUS = 3.20
SOCKET_THROAT = 2.65
STAND_LENGTH = 20.0
STAND_SPAN = 60.0
STAND_THICKNESS = 2.70
DETENT_X = 16.0
DETENT_Y = 14.0
DETENT_HOLE_RADIUS = 1.40


@dataclass(frozen=True)
class SideSpec:
    name: str
    source: str
    side: int
    underside_z_at_origin: float
    original_volume: float
    original_bbox: tuple[float, float, float]

    @property
    def hinge_origin(self) -> tuple[float, float, float]:
        x = self.side * HINGE_X
        slope = -self.side * math.tan(math.radians(BASE_TENT_ANGLE))
        return (x, 0.0, self.underside_z_at_origin + slope * x)


SIDES = (
    SideSpec(
        name="bottom_L_tenting",
        source="bottom_L.stp",
        side=1,
        underside_z_at_origin=-7.729,
        original_volume=16973.65,
        original_bbox=(126.569, 96.986, 11.738),
    ),
    SideSpec(
        name="bottom_R_tenting",
        source="bottom_R.stp",
        side=-1,
        underside_z_at_origin=-7.719,
        original_volume=20008.61,
        original_bbox=(125.940, 96.885, 11.726),
    ),
)


def stand() -> cq.Shape:
    """Build the universal stand in its folded local coordinate system."""

    axis_z = HINGE_AXIS_OFFSET
    pin = (
        cq.Workplane(cq.Plane(origin=(0, 0, axis_z), xDir=(1, 0, 0), normal=(0, 1, 0)))
        .circle(PIN_RADIUS)
        .extrude(STAND_SPAN / 2, both=True)
        .val()
    )
    plate_z0 = axis_z - STAND_THICKNESS / 2
    plate = (
        cq.Workplane("XY", origin=(STAND_LENGTH / 2, 0, plate_z0))
        .box(STAND_LENGTH, STAND_SPAN, STAND_THICKNESS, centered=(True, True, False))
        .val()
    )

    # The notches let the plate rotate past the two case-side C-clips.
    for y in (-HINGE_CLIP_Y, HINGE_CLIP_Y):
        notch = (
            cq.Workplane("XY", origin=(2.4, y, plate_z0 - 0.5))
            .box(4.8, HINGE_CLIP_LENGTH + 0.8, STAND_THICKNESS + 1.0, centered=(True, True, False))
            .val()
        )
        plate = plate.cut(notch)

    shape = pin.fuse(plate)

    # Two integral cams touch the inspected v3 underside at 65 degrees and
    # provide a hard deployed stop on both mirrored case halves.
    for y in (-8.0, 8.0):
        cam = (
            cq.Workplane("XY", origin=(-1.25, y, 1.98))
            .box(3.5, 5.0, 2.22, centered=(True, True, False))
            .val()
        )
        shape = shape.fuse(cam)

    # A rounded foot avoids balancing on a sharp printed edge.
    foot = (
        cq.Workplane(
            cq.Plane(
                origin=(STAND_LENGTH, 0, axis_z),
                xDir=(1, 0, 0),
                normal=(0, 1, 0),
            )
        )
        .circle(STAND_THICKNESS / 2)
        .extrude((STAND_SPAN - 2.0) / 2, both=True)
        .val()
    )
    shape = shape.fuse(foot)

    for y in (-DETENT_Y, DETENT_Y):
        hole = (
            cq.Workplane("XY", origin=(DETENT_X, y, plate_z0 - 0.5))
            .circle(DETENT_HOLE_RADIUS)
            .extrude(STAND_THICKNESS + 1.0)
            .val()
        )
        shape = shape.cut(hole)
    return shape.clean()


def local_plane(spec: SideSpec) -> cq.Plane:
    """Map universal local X/Y/Z to outward/length/down on one case side."""

    angle = math.radians(BASE_TENT_ANGLE)
    x_dir = (-spec.side * math.cos(angle), 0.0, math.sin(angle))
    down_normal = (-spec.side * math.sin(angle), 0.0, -math.cos(angle))
    return cq.Plane(origin=spec.hinge_origin, xDir=x_dir, normal=down_normal)


def case_hardware_local() -> cq.Shape:
    """Build sockets and detents in the universal local coordinate system."""

    hardware: cq.Shape | None = None
    axis_z = HINGE_AXIS_OFFSET
    for y in (-HINGE_CLIP_Y, HINGE_CLIP_Y):
        axis_plane = cq.Plane(origin=(0, y, axis_z), xDir=(1, 0, 0), normal=(0, 1, 0))
        outer = (
            cq.Workplane(axis_plane)
            .circle(SOCKET_RADIUS)
            .extrude(HINGE_CLIP_LENGTH / 2, both=True)
            .val()
        )
        bore = (
            cq.Workplane(axis_plane)
            .circle(BORE_RADIUS)
            .extrude((HINGE_CLIP_LENGTH + 1.0) / 2, both=True)
            .val()
        )
        throat = (
            cq.Workplane("XY", origin=(0, y, axis_z))
            .box(
                SOCKET_THROAT,
                HINGE_CLIP_LENGTH + 1.0,
                SOCKET_RADIUS + 1.0,
                centered=(True, True, False),
            )
            .val()
        )
        web = (
            cq.Workplane("XY", origin=(0, y, -1.0))
            .box(8.0, HINGE_CLIP_LENGTH, 3.5, centered=(True, True, False))
            .val()
        )
        # Cut the bore and insertion throat after adding the web; otherwise the
        # reinforcing web would refill the upper half of the bearing clearance.
        socket = outer.fuse(web).cut(bore).cut(throat)
        hardware = socket if hardware is None else hardware.fuse(socket)

    # Ball detents enter the stand holes in the folded position.  The 0.1 mm
    # radial interference is intentional and is taken by flex in the stand.
    for y in (-DETENT_Y, DETENT_Y):
        detent = (
            cq.Workplane("XY", origin=(DETENT_X, y, -0.8))
            .circle(0.75)
            .workplane(offset=1.6)
            .circle(0.75)
            .workplane(offset=0.7)
            .circle(1.50)
            .workplane(offset=1.1)
            .circle(0.20)
            .loft(combine=True)
            .val()
        )
        hardware = hardware.fuse(detent) if hardware is not None else detent
    assert hardware is not None
    return hardware.clean()


def local_to_global(point: tuple[float, float, float], plane: cq.Plane) -> tuple[float, float, float]:
    location = cq.Vector(*point).transform(plane.rG)
    return (location.x, location.y, location.z)


def modified_case(spec: SideSpec) -> tuple[cq.Shape, cq.Plane]:
    source = cq.importers.importStep(str(SOURCE_DIR / spec.source)).val()
    plane = local_plane(spec)
    hardware = case_hardware_local().moved(plane.location)
    result = source
    # Fuse each disconnected hardware solid independently.  Passing the whole
    # compound to OCC can preserve otherwise-intersecting detents as separate
    # solids even though each one overlaps the imported case floor.
    for hardware_solid in hardware.Solids():
        result = result.fuse(hardware_solid)
    result = result.clean()
    return result, plane


def verify_and_export() -> None:
    universal_stand = stand()
    stand_spec = VerificationSpec(
        volume_range=(3200.0, 4300.0),
        bbox=(24.5, STAND_SPAN, 3.0),
        bbox_tolerance=0.15,
        material_points=((0.0, 0.0, HINGE_AXIS_OFFSET), (10.0, 0.0, HINGE_AXIS_OFFSET)),
        void_points=((DETENT_X, -DETENT_Y, HINGE_AXIS_OFFSET), (DETENT_X, DETENT_Y, HINGE_AXIS_OFFSET)),
    )
    export_verified(universal_stand, OUTPUT_DIR, "folding_tenting_stand", stand_spec)

    for side in SIDES:
        case, plane = modified_case(side)
        # The socket bottom is the new Z minimum.  It extends 6.2 mm along the
        # local down normal from the inspected v3 underside at the hinge.
        expected_z = abs(
            side.hinge_origin[2]
            - (HINGE_AXIS_OFFSET + SOCKET_RADIUS) * math.cos(math.radians(BASE_TENT_ANGLE))
        )
        case_spec = VerificationSpec(
            volume_range=(side.original_volume + 350.0, side.original_volume + 950.0),
            bbox=(side.original_bbox[0], side.original_bbox[1], expected_z),
            bbox_tolerance=0.30,
            material_points=(
                local_to_global((2.5, -HINGE_CLIP_Y, HINGE_AXIS_OFFSET), plane),
                local_to_global((2.5, HINGE_CLIP_Y, HINGE_AXIS_OFFSET), plane),
            ),
            void_points=(
                local_to_global((0.0, -HINGE_CLIP_Y, HINGE_AXIS_OFFSET), plane),
                local_to_global((0.0, HINGE_CLIP_Y, HINGE_AXIS_OFFSET), plane),
            ),
        )
        export_verified(case, OUTPUT_DIR, side.name, case_spec)

        folded = universal_stand.moved(plane.location)
        folded_overlap = case.intersect(folded).Volume()
        deployed_local = universal_stand.rotate(
            (0, 0, HINGE_AXIS_OFFSET),
            (0, 1, HINGE_AXIS_OFFSET),
            -DEPLOY_ANGLE,
        )
        deployed = deployed_local.moved(plane.location)
        deployed_overlap = case.intersect(deployed).Volume()
        if folded_overlap > 2.0:
            raise RuntimeError(f"{side.name}: folded interference {folded_overlap:.3f} mm^3")
        if deployed_overlap > 2.0:
            raise RuntimeError(f"{side.name}: deployed interference {deployed_overlap:.3f} mm^3")
        print(
            f"[assembly] {side.name}: folded overlap={folded_overlap:.3f} mm^3, "
            f"deployed overlap={deployed_overlap:.3f} mm^3"
        )

    extra_angle = math.degrees(
        math.atan2(
            HINGE_AXIS_OFFSET
            + STAND_LENGTH * math.sin(math.radians(DEPLOY_ANGLE))
            + STAND_THICKNESS / 2 * math.cos(math.radians(DEPLOY_ANGLE)),
            110.0,
        )
    )
    print(
        f"[design] nominal tent angle={BASE_TENT_ANGLE + extra_angle:.2f} deg "
        f"(target {NOMINAL_TOTAL_TENT_ANGLE:.1f} deg over a 110 mm support span)"
    )


if __name__ == "__main__":
    verify_and_export()
