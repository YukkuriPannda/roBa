"""FreeCAD model: 34 mm trackball case with three screw-axle ball bearings.

The source ``case/trackballcase.stl`` has no parametric history.  It is kept as a
mesh reference and as a converted, history-free solid snapshot.  Only the bearing
housings, pockets, inner-ring shoulders and screw holes added here are regenerated
FeaturePython features driven by the named dimensions in ``BearingParameters``.

Coordinates are the source mesh frame (mm).  The assembly transform into the v3
top_R / bottom_R frame is measured from hole evidence at build time and recorded;
it is never assumed silently.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import FreeCAD as App
import Part


MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[3]
SOURCE_STL = REPO_ROOT / "case" / "trackballcase.stl"
JLC_STL = REPO_ROOT / "case" / "trackballcase_JLC3DP.stl"
V3_DIR = REPO_ROOT / "case" / "v3"
GENERATED_DIR = MODULE_DIR / "generated"
FAILED_DIR = MODULE_DIR / "failed_runs"
DOCUMENT_NAME = "trackball_bearing_34mm"
DOCUMENT_FILE = f"{DOCUMENT_NAME}.FCStd"
CONTRACT_VERSION = "1"

# Mesh -> BRep conversion tolerance used by Part.Shape.makeShapeFromMesh (mm).
MESH_SEW_TOLERANCE = 0.01

# Source measurements frozen from inspect/fit_cup.py and inspect/alignment_and_conversion.py.
# They are re-measured from the source mesh / bottom_R at every build and must agree.
SOURCE_INNER_SPHERE_RADIUS = 17.9915
SOURCE_OUTER_SPHERE_RADIUS = 19.4948
SOURCE_MEASUREMENT_TOLERANCE = 0.02
SOURCE_ORIGINAL_SUPPORT_DIRECTIONS = (
    (-0.54725, 0.82442, 0.14439),
    (-0.09429, -0.46633, -0.87957),
    (0.89232, -0.02968, 0.45043),
)
ASSEMBLY_ROTATION_Z_DEG = 0.1025
ASSEMBLY_TRANSLATION = (10.8954, -28.7258, -4.0)
ASSEMBLY_FIT_RESIDUAL_LIMIT = 0.10
ASSEMBLY_CONSTANT_TOLERANCE = 0.01

# Mounting / sensor features of the source (mesh frame) that must stay untouched.
EAR_HOLE_CENTERS = ((9.5916, -7.7166), (9.5916, 8.4832))
SENSOR_HOLE_CENTER = (-0.31, 0.0)
FLANGE_UNDERSIDE_Z = 2.0

STEP_ROUND_TRIP_RELATIVE_VOLUME_LIMIT = 0.0002
STEP_ROUND_TRIP_BBOX_LIMIT_MM = 0.02

# (name, type, default, group, description)
DEFAULTS = (
    ("BallDiameter", "App::PropertyLength", 34.0, "Ball", "Frozen requirement: trackball diameter."),
    ("BallCenterX", "App::PropertyDistance", -0.3179, "Ball", "Measured source cup centre X (reference; must not move)."),
    ("BallCenterY", "App::PropertyDistance", -0.0002, "Ball", "Measured source cup centre Y (reference; must not move)."),
    ("BallCenterZ", "App::PropertyDistance", 20.0010, "Ball", "Measured source cup centre Z (reference; must not move)."),
    ("BearingInnerDiameter", "App::PropertyLength", 2.5, "Bearing", "Frozen requirement: bearing bore."),
    ("BearingOuterDiameter", "App::PropertyLength", 4.0, "Bearing", "Frozen requirement: bearing outer diameter."),
    ("BearingWidth", "App::PropertyLength", 2.0, "Bearing", "Frozen requirement: bearing width."),
    ("ShieldInnerDiameterAssumed", "App::PropertyLength", 3.0, "Bearing", "ASSUMED inner edge of shields / outer-ring face; real part unmeasured."),
    ("InnerRingContactDiameter", "App::PropertyLength", 3.0, "Bearing", "Outer diameter of the printed inner-ring shoulders."),
    ("ScrewNominalDiameter", "App::PropertyLength", 2.5, "Screw", "Frozen requirement: M2.5."),
    ("ScrewLength", "App::PropertyLength", 5.0, "Screw", "Frozen requirement: length under head."),
    ("ScrewHeadDiameter", "App::PropertyLength", 4.0, "Screw", "ASSUMED maximum head envelope diameter (small-head M2.5)."),
    ("ScrewHeadHeight", "App::PropertyLength", 1.6, "Screw", "ASSUMED maximum head envelope height."),
    ("ScrewClearanceDiameter", "App::PropertyLength", 2.7, "Screw", "Head-side clearance hole."),
    ("ScrewPilotDiameter", "App::PropertyLength", 2.2, "Screw", "Thread-side self-tapping pilot hole."),
    ("PilotExtraDepth", "App::PropertyLength", 0.5, "Screw", "Pilot depth beyond the screw tip."),
    ("MinThreadEngagement", "App::PropertyLength", 1.0, "Screw", "Minimum thread length beyond the thread-side shoulder."),
    ("PocketRadialClearance", "App::PropertyLength", 0.4, "Pocket", "Radial gap around the outer ring."),
    ("ShoulderHeight", "App::PropertyLength", 0.3, "Pocket", "Inner-ring shoulder height = axial gap to the outer ring / shields."),
    ("HeadSideWebThickness", "App::PropertyLength", 1.0, "Pocket", "Printed web between head-side shoulder and screw head seat."),
    ("HeadCounterboreClearance", "App::PropertyLength", 0.3, "Pocket", "Radial clearance around the head envelope."),
    ("AccessChannelLength", "App::PropertyLength", 8.0, "Pocket", "Driver channel length beyond the head seat."),
    ("InsertionSlotDepth", "App::PropertyLength", 3.5, "Pocket", "Slot from bearing centre towards the ball for radial insertion."),
    ("HousingWall", "App::PropertyLength", 1.6, "Housing", "Wall around the pocket (4 x 0.4 mm lines review guide)."),
    ("ThreadSideCap", "App::PropertyLength", 1.0, "Housing", "Material beyond the pilot hole end."),
    ("MinBallClearance", "App::PropertyLength", 0.5, "Clearance", "Minimum case-to-ball clearance for added material."),
    ("MinHeadBallClearance", "App::PropertyLength", 0.1, "Clearance", "Minimum screw-head envelope to ball clearance."),
    ("Bearing1Polar", "App::PropertyAngle", 0.0, "Sites", "Contact direction polar angle from -Z (mesh frame)."),
    ("Bearing1Azimuth", "App::PropertyAngle", 0.0, "Sites", "Contact direction azimuth (mesh frame)."),
    ("Bearing1AxisAngle", "App::PropertyAngle", 0.0, "Sites", "Screw axis angle in the tangent plane."),
    ("Bearing2Polar", "App::PropertyAngle", 0.0, "Sites", "Contact direction polar angle from -Z (mesh frame)."),
    ("Bearing2Azimuth", "App::PropertyAngle", 0.0, "Sites", "Contact direction azimuth (mesh frame)."),
    ("Bearing2AxisAngle", "App::PropertyAngle", 0.0, "Sites", "Screw axis angle in the tangent plane."),
    ("Bearing3Polar", "App::PropertyAngle", 0.0, "Sites", "Contact direction polar angle from -Z (mesh frame)."),
    ("Bearing3Azimuth", "App::PropertyAngle", 0.0, "Sites", "Contact direction azimuth (mesh frame)."),
    ("Bearing3AxisAngle", "App::PropertyAngle", 0.0, "Sites", "Screw axis angle in the tangent plane."),
)
READ_ONLY = ("BallCenterX", "BallCenterY", "BallCenterZ")
SITE_COUNT = 3


def _number(value: Any) -> float:
    if hasattr(value, "Value"):
        return float(value.Value)
    return float(value)


def default_dimension_values() -> dict[str, float]:
    return {name: float(value) for name, _, value, _, _ in DEFAULTS}


def dimensions(parameters: Any) -> dict[str, float]:
    return {name: _number(getattr(parameters, name)) for name, _, _, _, _ in DEFAULTS}


def derived(d: dict[str, float]) -> dict[str, float]:
    """Axial stations along the screw axis t (bearing mid-plane t = 0, head side t > 0)."""

    half_w = d["BearingWidth"] / 2.0
    shoulder_end = half_w + d["ShoulderHeight"]
    head_seat = shoulder_end + d["HeadSideWebThickness"]
    screw_tip = head_seat - d["ScrewLength"]
    pilot_end = screw_tip - d["PilotExtraDepth"]
    ball_r = d["BallDiameter"] / 2.0
    bearing_center_radius = ball_r + d["BearingOuterDiameter"] / 2.0
    head_r = d["ScrewHeadDiameter"] / 2.0
    # Closest approach of the head envelope (cylinder radius head_r starting at t = head_seat)
    # to the ball centre: the axis passes at distance bearing_center_radius from the centre.
    head_min_dist = math.hypot(bearing_center_radius - head_r, head_seat)
    return {
        "half_width": half_w,
        "shoulder_end": shoulder_end,
        "head_seat": head_seat,
        "screw_tip": screw_tip,
        "pilot_end": pilot_end,
        "thread_engagement": -screw_tip - shoulder_end,
        "housing_t_min": pilot_end - d["ThreadSideCap"],
        "ball_radius": ball_r,
        "bearing_center_radius": bearing_center_radius,
        "pocket_radius": d["BearingOuterDiameter"] / 2.0 + d["PocketRadialClearance"],
        "housing_radius": d["BearingOuterDiameter"] / 2.0 + d["PocketRadialClearance"] + d["HousingWall"],
        "counterbore_radius": head_r + d["HeadCounterboreClearance"],
        "trim_radius": ball_r + d["MinBallClearance"],
        "head_ball_clearance": head_min_dist - ball_r,
    }


def validate_parameters(parameters: Any) -> dict[str, float]:
    """Reject dimension sets that cannot satisfy the frozen bearing/screw contract."""

    d = dimensions(parameters)
    positive = [n for n, kind, *_ in DEFAULTS if kind == "App::PropertyLength" and d[n] <= 0.0]
    if positive:
        raise ValueError("dimensions must be positive: " + ", ".join(positive))
    k = derived(d)
    checks = (
        (d["BearingInnerDiameter"] < d["InnerRingContactDiameter"] <= d["ShieldInnerDiameterAssumed"] < d["BearingOuterDiameter"],
         "require BearingInnerDiameter < InnerRingContactDiameter <= ShieldInnerDiameterAssumed < BearingOuterDiameter"),
        (d["ScrewNominalDiameter"] <= d["BearingInnerDiameter"], "screw must pass the bearing bore"),
        (d["ScrewPilotDiameter"] < d["ScrewNominalDiameter"] < d["ScrewClearanceDiameter"], "require pilot < nominal < clearance diameter"),
        (d["ScrewClearanceDiameter"] < d["InnerRingContactDiameter"], "head-side shoulder needs material outside the clearance hole"),
        (d["ScrewHeadDiameter"] > d["ScrewClearanceDiameter"], "screw head must bear on the web"),
        (k["thread_engagement"] >= d["MinThreadEngagement"], f"thread engagement {k['thread_engagement']:.3f} mm is below MinThreadEngagement"),
        (k["head_ball_clearance"] >= d["MinHeadBallClearance"], f"screw head envelope reaches within {k['head_ball_clearance']:.3f} mm of the ball"),
        (d["ShoulderHeight"] >= 0.1, "ShoulderHeight must leave a real axial gap to the outer ring"),
        (d["InsertionSlotDepth"] > k["bearing_center_radius"] - k["trim_radius"], "insertion slot must reach the ball-clearance sphere"),
    )
    failed = [message for ok, message in checks if not ok]
    if failed:
        raise ValueError("; ".join(failed))
    for i in range(1, SITE_COUNT + 1):
        if not 0.0 < d[f"Bearing{i}Polar"] < 180.0:
            raise ValueError(f"Bearing{i}Polar must be between 0 and 180 degrees")
    return d


def site_frame(d: dict[str, float], index: int) -> dict[str, Any]:
    """Contact direction u, screw axis a, b = a x u, bearing centre P (mesh frame)."""

    polar = math.radians(d[f"Bearing{index}Polar"])
    azimuth = math.radians(d[f"Bearing{index}Azimuth"])
    axis_angle = math.radians(d[f"Bearing{index}AxisAngle"])
    u = App.Vector(math.sin(polar) * math.cos(azimuth), math.sin(polar) * math.sin(azimuth), -math.cos(polar))
    ref = App.Vector(0, 0, 1) if abs(u.z) < 0.95 else App.Vector(1, 0, 0)
    e1 = ref.cross(u)
    e1.normalize()
    e2 = u.cross(e1)
    a = e1 * math.cos(axis_angle) + e2 * math.sin(axis_angle)
    a.normalize()
    b = a.cross(u)
    center = App.Vector(d["BallCenterX"], d["BallCenterY"], d["BallCenterZ"])
    k = derived(d)
    p = center + u * k["bearing_center_radius"]
    # Local frame columns [u, b, a]: local X radial outward, local Z screw axis (head side +).
    matrix = App.Matrix(u.x, b.x, a.x, p.x, u.y, b.y, a.y, p.y, u.z, b.z, a.z, p.z, 0, 0, 0, 1)
    return {"u": u, "a": a, "b": b, "p": p, "center": center, "placement": App.Placement(matrix)}


def _cyl_z(radius: float, z0: float, z1: float) -> Any:
    return Part.makeCylinder(radius, z1 - z0, App.Vector(0, 0, z0), App.Vector(0, 0, 1))


def _placed(shape: Any, placement: Any) -> Any:
    result = shape.copy()
    result.transformShape(placement.toMatrix(), True)
    return result


def local_housing(d: dict[str, float]) -> Any:
    k = derived(d)
    housing = _cyl_z(k["housing_radius"], k["housing_t_min"], k["head_seat"])
    trim = Part.makeSphere(k["trim_radius"], App.Vector(-k["bearing_center_radius"], 0, 0))
    return housing.cut(trim)


def local_shoulders(d: dict[str, float]) -> Any:
    k = derived(d)
    rc = d["InnerRingContactDiameter"] / 2.0
    head = _cyl_z(rc, k["half_width"], k["shoulder_end"]).cut(_cyl_z(d["ScrewClearanceDiameter"] / 2.0, k["half_width"] - 0.1, k["shoulder_end"] + 0.1))
    thread = _cyl_z(rc, -k["shoulder_end"], -k["half_width"]).cut(_cyl_z(d["ScrewPilotDiameter"] / 2.0, -k["shoulder_end"] - 0.1, -k["half_width"] + 0.1))
    return head.fuse(thread)


def local_cut_tool(d: dict[str, float]) -> Any:
    """Single cutting solid: pocket, insertion slot, driver channel, holes; shoulders kept."""

    k = derived(d)
    rp = k["pocket_radius"]
    pocket = _cyl_z(rp, -k["shoulder_end"], k["shoulder_end"])
    slot = Part.makeBox(d["InsertionSlotDepth"], 2.0 * rp, 2.0 * k["shoulder_end"], App.Vector(-d["InsertionSlotDepth"], -rp, -k["shoulder_end"]))
    channel = _cyl_z(k["counterbore_radius"], k["head_seat"], k["head_seat"] + d["AccessChannelLength"])
    clear = _cyl_z(d["ScrewClearanceDiameter"] / 2.0, 0.0, k["head_seat"] + 0.01)
    pilot = _cyl_z(d["ScrewPilotDiameter"] / 2.0, k["pilot_end"], 0.0)
    tool = pocket.fuse(slot).fuse(channel)
    tool = tool.cut(local_shoulders(d))
    tool = tool.fuse(clear).fuse(pilot)
    return tool.removeSplitter()


def local_hardware(d: dict[str, float]) -> dict[str, Any]:
    """Reference (non-printed) envelopes of the purchased parts in the site frame."""

    k = derived(d)
    ri, rc, ro = d["BearingInnerDiameter"] / 2.0, d["ShieldInnerDiameterAssumed"] / 2.0, d["BearingOuterDiameter"] / 2.0
    hw = k["half_width"]
    return {
        "inner_ring": _cyl_z(rc, -hw, hw).cut(_cyl_z(ri, -hw - 0.1, hw + 0.1)),
        "outer_zone": _cyl_z(ro, -hw, hw).cut(_cyl_z(rc, -hw - 0.1, hw + 0.1)),
        "screw_shank": _cyl_z(d["ScrewNominalDiameter"] / 2.0, k["screw_tip"], k["head_seat"]),
        "screw_head": _cyl_z(d["ScrewHeadDiameter"] / 2.0, k["head_seat"], k["head_seat"] + d["ScrewHeadHeight"]),
    }


def ball_shape(d: dict[str, float]) -> Any:
    return Part.makeSphere(d["BallDiameter"] / 2.0, App.Vector(d["BallCenterX"], d["BallCenterY"], d["BallCenterZ"]))


def assembly_matrix(rotation_deg: float = ASSEMBLY_ROTATION_Z_DEG, translation: tuple[float, float, float] = ASSEMBLY_TRANSLATION) -> Any:
    """Mesh frame -> v3 top_R/bottom_R frame (evidence-based, see build record)."""

    m = App.Matrix()
    m.rotateZ(math.radians(rotation_deg))
    m.move(App.Vector(*translation))
    return m


def keepout_zones() -> list[tuple[str, Any]]:
    """Mounting, sensor and hood regions that added/removed material must not touch."""

    zones = []
    for i, (x, y) in enumerate(EAR_HOLE_CENTERS):
        zones.append((f"ear_{i}", Part.makeCylinder(3.6, 6.0, App.Vector(x, y, FLANGE_UNDERSIDE_Z - 1.0))))
    zones.append(("sensor_aperture", Part.makeCylinder(7.5, 7.0, App.Vector(SENSOR_HOLE_CENTER[0], SENSOR_HOLE_CENTER[1], FLANGE_UNDERSIDE_Z - 1.0))))
    zones.append(("flange_plane", Part.makeBox(60.0, 60.0, 1.0, App.Vector(-25.0, -30.0, FLANGE_UNDERSIDE_Z - 1.0))))
    zones.append(("hood_cavity", Part.makeBox(9.9, 23.6, 30.0, App.Vector(17.69, -11.8, FLANGE_UNDERSIDE_Z))))
    return zones


# ---------------------------------------------------------------------------
# FeaturePython proxies
# ---------------------------------------------------------------------------


class ParametersProxy:
    def __init__(self, obj: Any):
        self._ready = False
        obj.Proxy = self
        obj.addProperty("App::PropertyString", "ContractVersion", "Contract", "Geometry contract revision")
        obj.ContractVersion = CONTRACT_VERSION
        for name, kind, value, group, text in DEFAULTS:
            obj.addProperty(kind, name, group, text)
            setattr(obj, name, value)
        for name in READ_ONLY:
            obj.setEditorMode(name, 1)
        self._ready = True

    def onChanged(self, obj: Any, prop: str) -> None:
        if not getattr(self, "_ready", False):
            return
        if prop in {name for name, *_ in DEFAULTS}:
            for dependent in obj.Document.Objects:
                if dependent is not obj and getattr(dependent, "Parameters", None) == obj:
                    dependent.touch()

    def execute(self, obj: Any) -> None:
        validate_parameters(obj)

    def __getstate__(self) -> None:
        return None

    def __setstate__(self, state: Any) -> None:
        del state
        self._ready = True


class SiteFeatureProxy:
    """One compound per kind ("housings", "cuts" or "hardware") for all three sites."""

    def __init__(self, obj: Any, parameters: Any, kind: str):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Parameters", "Inputs", "Shared editable dimensions")
        obj.addProperty("App::PropertyString", "Kind", "Inputs", "housings / cuts / hardware")
        obj.Parameters = parameters
        obj.Kind = kind
        obj.setEditorMode("Kind", 1)

    def execute(self, obj: Any) -> None:
        d = validate_parameters(obj.Parameters)
        shapes = []
        for i in range(1, SITE_COUNT + 1):
            placement = site_frame(d, i)["placement"]
            if obj.Kind == "housings":
                shapes.append(_placed(local_housing(d), placement))
            elif obj.Kind == "cuts":
                shapes.append(_placed(local_cut_tool(d), placement))
            elif obj.Kind == "hardware":
                for part in local_hardware(d).values():
                    shapes.append(_placed(part, placement))
            else:
                raise ValueError(f"unknown site feature kind: {obj.Kind}")
        if obj.Kind == "hardware":
            shapes.append(ball_shape(d))
        obj.Shape = Part.makeCompound(shapes)

    def __getstate__(self) -> None:
        return None

    def __setstate__(self, state: Any) -> None:
        del state


class BearingCaseProxy:
    """Final case = (source snapshot U housings) - cutting tools."""

    def __init__(self, obj: Any, parameters: Any, source: Any, housings: Any, cuts: Any):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Parameters", "Inputs", "Shared editable dimensions")
        obj.addProperty("App::PropertyLink", "Source", "Inputs", "History-free solid converted from the source STL")
        obj.addProperty("App::PropertyLink", "Housings", "Inputs", "Regenerated housing additions")
        obj.addProperty("App::PropertyLink", "Cuts", "Inputs", "Regenerated pocket / hole cutting tools")
        obj.Parameters, obj.Source, obj.Housings, obj.Cuts = parameters, source, housings, cuts

    def execute(self, obj: Any) -> None:
        validate_parameters(obj.Parameters)
        result = obj.Source.Shape.copy()
        for solid in obj.Housings.Shape.Solids:
            result = result.fuse(solid)
        for solid in obj.Cuts.Shape.Solids:
            result = result.cut(solid)
        if len(result.Solids) != 1 or not result.isValid():
            raise RuntimeError(f"bearing case boolean result is not one valid solid ({len(result.Solids)} solids)")
        obj.Shape = Part.Solid(result.Solids[0])

    def __getstate__(self) -> None:
        return None

    def __setstate__(self, state: Any) -> None:
        del state


class CouponProxy:
    """Printable fit coupon: one bearing site in a block, same cut tool and ball opening."""

    def __init__(self, obj: Any, parameters: Any):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Parameters", "Inputs", "Shared editable dimensions")
        obj.Parameters = parameters

    def execute(self, obj: Any) -> None:
        obj.Shape = build_coupon(validate_parameters(obj.Parameters))

    def __getstate__(self) -> None:
        return None

    def __setstate__(self, state: Any) -> None:
        del state


def build_coupon(d: dict[str, float]) -> Any:
    k = derived(d)
    rh = k["housing_radius"]
    x0 = -(k["bearing_center_radius"] - k["trim_radius"]) - 1.0
    block = Part.makeBox(rh + 1.5 - x0, 2.0 * (rh + 1.5), k["head_seat"] - k["housing_t_min"], App.Vector(x0, -(rh + 1.5), k["housing_t_min"]))
    block = block.cut(Part.makeSphere(k["trim_radius"], App.Vector(-k["bearing_center_radius"], 0, 0)))
    coupon = block.cut(local_cut_tool(d)).removeSplitter()
    if len(coupon.Solids) != 1 or not coupon.isValid():
        raise RuntimeError("coupon is not one valid solid")
    return Part.Solid(coupon.Solids[0])


# ---------------------------------------------------------------------------
# Source handling
# ---------------------------------------------------------------------------


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def convert_source_mesh() -> tuple[Any, dict[str, Any]]:
    import Mesh

    mesh = Mesh.Mesh(str(SOURCE_STL))
    shape = Part.Shape()
    shape.makeShapeFromMesh(mesh.Topology, MESH_SEW_TOLERANCE, False)
    shell = Part.Shell(shape.Faces)
    solid = Part.Solid(shell)
    info = {
        "source_file": _rel(SOURCE_STL),
        "sha256": sha256(SOURCE_STL),
        "mesh_facets": mesh.CountFacets,
        "mesh_is_solid": bool(mesh.isSolid()),
        "mesh_has_non_manifolds": bool(mesh.hasNonManifolds()),
        "mesh_self_intersection_pairs": len(mesh.getSelfIntersections()),
        "mesh_volume_mm3": float(mesh.Volume),
        "brep_faces": len(solid.Faces),
        "shell_closed": bool(shell.isClosed()),
        "brep_valid": bool(solid.isValid()),
        "brep_volume_mm3": float(solid.Volume),
        "sew_tolerance_mm": MESH_SEW_TOLERANCE,
    }
    if not (info["shell_closed"] and info["brep_valid"] and len(solid.Solids) == 1):
        raise RuntimeError(f"source mesh did not convert to one closed valid solid: {info}")
    if abs(info["brep_volume_mm3"] - info["mesh_volume_mm3"]) > 0.05:
        raise RuntimeError("converted solid volume differs from the mesh volume")
    return solid, info


def measure_source() -> dict[str, Any]:
    """Re-measure cup spheres and assembly evidence; compare to the frozen constants."""

    import Mesh
    import numpy as np

    mesh = Mesh.Mesh(str(SOURCE_STL))
    tris = np.array([[list(p) for p in f.Points] for f in mesh.Facets])
    cent = tris.mean(axis=1)
    nrm = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    area = 0.5 * np.linalg.norm(nrm, axis=1)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12

    def fit(sign: float, radius: float) -> tuple[Any, float, float]:
        c = np.array([0.0, 0.0, 20.0])
        r = radius
        for _ in range(8):
            rad = cent - c
            dist = np.linalg.norm(rad, axis=1)
            align = sign * np.einsum("ij,ij->i", nrm, rad / dist[:, None])
            sel = (align > 0.98) & (np.abs(dist - r) < 1.0)
            pts, w = cent[sel], area[sel]
            a = np.hstack([2 * pts, np.ones((len(pts), 1))])
            bvec = (pts ** 2).sum(axis=1)
            sw = np.sqrt(w)
            sol, *_ = np.linalg.lstsq(a * sw[:, None], bvec * sw, rcond=None)
            c = sol[:3]
            r = float(np.sqrt(sol[3] + c @ c))
        res = np.linalg.norm(pts - c, axis=1) - r
        return c, r, float(np.sqrt(np.average(res ** 2, weights=w)))

    c_in, r_in, rms_in = fit(-1.0, 18.0)
    c_out, r_out, rms_out = fit(1.0, 19.5)

    # Mounting evidence: ear holes and sensor hole sections vs bottom_R cylinders.
    def loops(z: float) -> list[tuple[float, float, float]]:
        out = []
        for poly in mesh.crossSections([(App.Vector(0, 0, z), App.Vector(0, 0, 1))], 1e-5)[0]:
            pts = np.array([[p.x, p.y] for p in poly])
            if len(pts) < 4:
                continue
            x, y = pts[:, 0], pts[:, 1]
            cross = x[:-1] * y[1:] - x[1:] * y[:-1]
            a2 = 0.5 * np.sum(cross)
            out.append((abs(a2), float(np.sum((x[:-1] + x[1:]) * cross) / (6 * a2)), float(np.sum((y[:-1] + y[1:]) * cross) / (6 * a2))))
        return out

    ears = sorted([l for l in loops(3.5) if l[0] < 6.0 and l[1] > 5], key=lambda l: l[2])
    sensor = [l for l in loops(2.2) if 120 < l[0] < 170]
    if len(ears) != 2 or len(sensor) != 1:
        raise RuntimeError("could not identify the two ear holes and the sensor hole in the source mesh")
    local = np.array([[ears[0][1], ears[0][2]], [ears[1][1], ears[1][2]], [sensor[0][1], sensor[0][2]]])
    bottom = Part.read(str(V3_DIR / "bottom_R.stp"))
    screw, sens, top_z = [], [], []
    for face in bottom.Faces:
        s = face.Surface
        if type(s).__name__ == "Cylinder" and abs(s.Axis.z) > 0.999:
            if abs(s.Radius - 1.2) < 0.01 and 15 < s.Center.x < 25 and -40 < s.Center.y < -15:
                screw.append((s.Center.x, s.Center.y))
                top_z.append(face.BoundBox.ZMax)
            if abs(s.Radius - 7.0) < 0.01 and 5 < s.Center.x < 15:
                sens.append((s.Center.x, s.Center.y))
                top_z.append(face.BoundBox.ZMax)
    if len(screw) != 2 or len(sens) != 1:
        raise RuntimeError("could not identify bottom_R trackball screw holes and sensor hole")
    glob = np.array(sorted(screw, key=lambda p: p[1]) + sens)
    lc, gc = local.mean(axis=0), glob.mean(axis=0)
    u_, _, vt = np.linalg.svd((local - lc).T @ (glob - gc))
    rot = vt.T @ u_.T
    theta = math.degrees(math.atan2(rot[1, 0], rot[0, 0]))
    trans = gc - rot @ lc
    resid = glob - (local @ rot.T + trans)
    flange_z = float(min(p.z for p in mesh.Points))
    tz = float(max(top_z)) - flange_z
    top = Part.read(str(V3_DIR / "top_R.stp"))
    spheres = [f.Surface for f in top.Faces if type(f.Surface).__name__ == "Sphere"]
    ball_global = np.array([*(rot @ c_in[:2] + trans), c_in[2] + tz])
    record = {
        "inner_sphere": {"center": c_in.round(4).tolist(), "radius": round(r_in, 4), "rms": round(rms_in, 4)},
        "outer_sphere": {"center": c_out.round(4).tolist(), "radius": round(r_out, 4), "rms": round(rms_out, 4)},
        "assembly": {
            "method": "2D rigid least-squares fit: two mesh ear-hole centroids + sensor-hole centroid -> bottom_R R1.2 screw-hole axes + R7 sensor-hole axis; Z from mesh flange underside to bottom_R hole top faces (contact ASSUMED, no PCB/spacer modelled)",
            "rotation_z_deg": round(theta, 4),
            "translation": [round(float(trans[0]), 4), round(float(trans[1]), 4), round(tz, 4)],
            "residuals_xy_mm": resid.round(4).tolist(),
            "max_residual_mm": round(float(np.linalg.norm(resid, axis=1).max()), 4),
            "bottom_R_hole_top_z": sorted(set(round(z, 4) for z in top_z)),
            "ball_center_v3_frame": ball_global.round(4).tolist(),
            "top_R_clearance_sphere": ({"center": [round(spheres[0].Center.x, 4), round(spheres[0].Center.y, 4), round(spheres[0].Center.z, 4)], "radius": spheres[0].Radius} if len(spheres) == 1 else None),
        },
    }
    if len(spheres) == 1:
        offset = np.array([spheres[0].Center.x, spheres[0].Center.y, spheres[0].Center.z]) - ball_global
        record["assembly"]["top_R_sphere_center_offset_mm"] = round(float(np.linalg.norm(offset)), 4)
    return record


def check_source_measurements(record: dict[str, Any], d: dict[str, float]) -> None:
    center = record["inner_sphere"]["center"]
    for axis, value in zip("XYZ", center):
        if abs(value - d[f"BallCenter{axis}"]) > SOURCE_MEASUREMENT_TOLERANCE:
            raise RuntimeError(f"measured cup centre {axis}={value} differs from BallCenter{axis}={d[f'BallCenter{axis}']}")
    if abs(record["inner_sphere"]["radius"] - SOURCE_INNER_SPHERE_RADIUS) > SOURCE_MEASUREMENT_TOLERANCE:
        raise RuntimeError("measured inner cup radius changed")
    if abs(record["outer_sphere"]["radius"] - SOURCE_OUTER_SPHERE_RADIUS) > SOURCE_MEASUREMENT_TOLERANCE:
        raise RuntimeError("measured outer cup radius changed")
    asm = record["assembly"]
    if asm["max_residual_mm"] > ASSEMBLY_FIT_RESIDUAL_LIMIT:
        raise RuntimeError(f"assembly hole fit residual {asm['max_residual_mm']} mm exceeds {ASSEMBLY_FIT_RESIDUAL_LIMIT}")
    if abs(asm["rotation_z_deg"] - ASSEMBLY_ROTATION_Z_DEG) > ASSEMBLY_CONSTANT_TOLERANCE * 10:
        raise RuntimeError("measured assembly rotation differs from the frozen constant")
    for got, want in zip(asm["translation"], ASSEMBLY_TRANSLATION):
        if abs(got - want) > ASSEMBLY_CONSTANT_TOLERANCE:
            raise RuntimeError("measured assembly translation differs from the frozen constant")
