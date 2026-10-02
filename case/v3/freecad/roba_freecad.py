"""Native FreeCAD Part API model for the roBa v3 folding tenting stand.

The feature proxies in this module are imported by both the build runner and
the GUI macro so saved FCStd documents can recompute their geometry.
"""

from __future__ import annotations

import json
import hashlib
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
REPO_ROOT = MODULE_DIR.parents[2]
SOURCE_DIR = REPO_ROOT / "case" / "v3"
LEGACY_DIR = SOURCE_DIR / "tenting" / "output"
GENERATED_DIR = MODULE_DIR / "generated"
DETENT_SEED_PATH = MODULE_DIR / "reference" / "legacy_detent.brep"
DOCUMENT_NAME = "roba_v3_folding_tenting"
DOCUMENT_FILE = f"{DOCUMENT_NAME}.FCStd"
CONTRACT_VERSION = "1"
STEP_ROUND_TRIP_RELATIVE_VOLUME_LIMIT = 0.0002  # 0.02%; calibrated against FreeCAD 1.1 on the untouched source STEP.
STEP_ROUND_TRIP_BBOX_LIMIT_MM = 0.02
STEP_ROUND_TRIP_SAMPLE_DEFLECTION_MM = 0.10
STEP_ROUND_TRIP_SAMPLE_LIMIT = 80
STEP_ROUND_TRIP_SURFACE_DISTANCE_LIMIT_MM = 0.005

# Frozen mechanism contract, millimetres and degrees.  This is copied from
# case/v3/tenting/build_tenting.py without changing its coordinate transforms.
DEFAULTS = (
    ("BaseTentAngle", "App::PropertyAngle", 4.0),
    ("DeployAngle", "App::PropertyAngle", 65.0),
    ("NominalTotalTentAngle", "App::PropertyAngle", 15.0),
    ("HingeX", "App::PropertyLength", 50.0),
    ("HingeAxisOffset", "App::PropertyLength", 3.0),
    ("HingeClipY", "App::PropertyLength", 22.0),
    ("HingeClipLength", "App::PropertyLength", 8.0),
    ("PinRadius", "App::PropertyLength", 1.50),
    ("BoreRadius", "App::PropertyLength", 1.70),
    ("SocketRadius", "App::PropertyLength", 3.20),
    ("SocketThroat", "App::PropertyLength", 2.65),
    ("StandLength", "App::PropertyLength", 20.0),
    ("StandSpan", "App::PropertyLength", 60.0),
    ("StandThickness", "App::PropertyLength", 2.70),
    ("DetentX", "App::PropertyLength", 16.0),
    ("DetentY", "App::PropertyLength", 14.0),
    ("DetentHoleRadius", "App::PropertyLength", 1.40),
    ("LeftUndersideZAtOrigin", "App::PropertyDistance", -7.729),
    ("RightUndersideZAtOrigin", "App::PropertyDistance", -7.719),
)

SIDE_DATA = {
    "L": {
        "name": "bottom_L_tenting",
        "source": "bottom_L.stp",
        "side": 1,
        "underside_property": "LeftUndersideZAtOrigin",
    },
    "R": {
        "name": "bottom_R_tenting",
        "source": "bottom_R.stp",
        "side": -1,
        "underside_property": "RightUndersideZAtOrigin",
    },
}

REFERENCE_SOURCES = {
    "BottomLSource": "bottom_L.stp",
    "BottomRSource": "bottom_R.stp",
    "TopLReference": "top_L.stp",
    "TopRReference": "top_R.stp",
}

_LENGTH_PROPERTIES = tuple(
    name for name, kind, _ in DEFAULTS if kind in ("App::PropertyLength", "App::PropertyDistance")
)
_ANGLE_PROPERTIES = tuple(name for name, kind, _ in DEFAULTS if kind == "App::PropertyAngle")


def _number(value: Any) -> float:
    """Return a FreeCAD Quantity's display-unit value or a regular float."""

    if hasattr(value, "Value"):
        return float(value.Value)
    return float(value)


def _dimension(parameters: Any, name: str) -> float:
    return _number(getattr(parameters, name))


def default_dimension_values() -> dict[str, float]:
    return {name: float(value) for name, _, value in DEFAULTS}


def validate_parameters(parameters: Any) -> dict[str, float]:
    """Reject invalid hinge relationships before a feature can be exported."""

    values = {name: _dimension(parameters, name) for name, _, _ in DEFAULTS}
    positive_names = tuple(name for name in _LENGTH_PROPERTIES if name not in ("LeftUndersideZAtOrigin", "RightUndersideZAtOrigin"))
    invalid = [name for name in positive_names if values[name] <= 0.0]
    if invalid:
        raise ValueError("dimensions must be positive: " + ", ".join(invalid))

    # Explicit axle / bore / throat contract: the bore clears the axle while
    # the narrower throat retains it. Socket wall must remain positive.
    pin = values["PinRadius"]
    bore = values["BoreRadius"]
    socket = values["SocketRadius"]
    throat = values["SocketThroat"]
    if not (pin < bore < socket):
        raise ValueError("require PinRadius < BoreRadius < SocketRadius")
    if not (throat < 2.0 * pin and throat < 2.0 * socket):
        raise ValueError("SocketThroat must be narrower than the pin diameter and socket diameter")
    if throat <= 0.0:
        raise ValueError("SocketThroat must be positive")
    if values["HingeClipLength"] <= 1.0:
        raise ValueError("HingeClipLength must exceed the one millimetre bore allowance")
    if values["StandSpan"] <= 2.0:
        raise ValueError("StandSpan must leave positive length for the rounded foot")
    if values["DetentHoleRadius"] <= 0.0:
        raise ValueError("DetentHoleRadius must be positive")
    if not 0.0 < values["DeployAngle"] < 90.0:
        raise ValueError("DeployAngle must be between 0 and 90 degrees")
    if not 0.0 <= values["BaseTentAngle"] < 90.0:
        raise ValueError("BaseTentAngle must be between 0 and 90 degrees")
    return values


class ParametersProxy:
    """Single named dimension table; edits touch every linked feature."""

    def __init__(self, obj: Any):
        self._ready = False
        obj.Proxy = self
        obj.addProperty("App::PropertyString", "ContractVersion", "Contract", "Geometry contract revision")
        obj.ContractVersion = CONTRACT_VERSION
        descriptions = {
            "BaseTentAngle": "Frozen source case-base transform angle; changing it remaps hardware relative to unchanged STEP geometry.",
            "DeployAngle": "End pose used for clearance checks only; it does not move or redesign the physical stop cams.",
            "NominalTotalTentAngle": "Design target for reporting only; it does not drive any feature geometry.",
            "LeftUndersideZAtOrigin": "Source-derived left underside reference used by the frozen local transform.",
            "RightUndersideZAtOrigin": "Source-derived right underside reference used by the frozen local transform.",
        }
        for name, type_id, value in DEFAULTS:
            obj.addProperty(
                type_id,
                name,
                "Dimensions",
                descriptions.get(name, "Named folding-stand design dimension in mm or degrees."),
            )
            setattr(obj, name, value)
        # These describe the imported shell frame or a reporting target; expose
        # them as named properties without implying that STEP history is edited.
        for name in descriptions:
            obj.setEditorMode(name, 1)
        self._ready = True

    def onChanged(self, obj: Any, prop: str) -> None:
        if not self._ready or prop not in _LENGTH_PROPERTIES + _ANGLE_PROPERTIES:
            return
        for dependent in obj.Document.Objects:
            if dependent is obj:
                continue
            if hasattr(dependent, "Parameters") and dependent.Parameters == obj:
                dependent.touch()

    def execute(self, obj: Any) -> None:
        validate_parameters(obj)

    def __getstate__(self) -> None:
        return None

    def __setstate__(self, state: Any) -> None:
        del state
        self._ready = True


def hinge_placement(parameters: Any, side_key: str) -> Any:
    """FreeCAD Placement equivalent of the legacy CadQuery local_plane()."""

    side_info = SIDE_DATA[side_key]
    side = int(side_info["side"])
    angle = math.radians(_dimension(parameters, "BaseTentAngle"))
    x_dir = App.Vector(-side * math.cos(angle), 0.0, math.sin(angle))
    normal = App.Vector(-side * math.sin(angle), 0.0, -math.cos(angle))
    y_dir = normal.cross(x_dir)
    origin_x = side * _dimension(parameters, "HingeX")
    underside = _dimension(parameters, str(side_info["underside_property"]))
    origin_z = underside - side * math.tan(angle) * origin_x
    rotation = App.Rotation(x_dir, y_dir, normal, "ZXY")
    return App.Placement(App.Vector(origin_x, 0.0, origin_z), rotation)


def _box(length: float, width: float, height: float, corner: Any) -> Any:
    return Part.makeBox(length, width, height, corner)


def build_stand_shape(parameters: Any) -> Any:
    """Build the universal stand in its folded local coordinate system."""

    d = validate_parameters(parameters)
    axis_z = d["HingeAxisOffset"]
    span = d["StandSpan"]
    clip_len = d["HingeClipLength"]
    thickness = d["StandThickness"]
    plate_z0 = axis_z - thickness / 2.0

    pin = Part.makeCylinder(
        d["PinRadius"], span, App.Vector(0.0, -span / 2.0, axis_z), App.Vector(0, 1, 0)
    )
    plate = _box(
        d["StandLength"], span, thickness, App.Vector(0.0, -span / 2.0, plate_z0)
    )
    # Preserve the legacy clip notches, including their through-depth margin.
    for y in (-d["HingeClipY"], d["HingeClipY"]):
        notch = _box(
            4.8,
            clip_len + 0.8,
            thickness + 1.0,
            App.Vector(0.0, y - (clip_len + 0.8) / 2.0, plate_z0 - 0.5),
        )
        plate = plate.cut(notch)

    shape = pin.fuse(plate)
    for y in (-8.0, 8.0):
        cam = _box(3.5, 5.0, 2.22, App.Vector(-3.0, y - 2.5, 1.98))
        shape = shape.fuse(cam)

    foot = Part.makeCylinder(
        thickness / 2.0,
        span - 2.0,
        App.Vector(d["StandLength"], -(span - 2.0) / 2.0, axis_z),
        App.Vector(0, 1, 0),
    )
    shape = shape.fuse(foot)

    for y in (-d["DetentY"], d["DetentY"]):
        hole = Part.makeCylinder(
            d["DetentHoleRadius"],
            thickness + 1.0,
            App.Vector(d["DetentX"], y, plate_z0 - 0.5),
            App.Vector(0, 0, 1),
        )
        shape = shape.cut(hole)
    return shape.removeSplitter()


def _circle_wire(radius: float, x: float, y: float, z: float) -> Any:
    edge = Part.makeCircle(radius, App.Vector(x, y, z), App.Vector(0, 0, 1))
    return Part.Wire(edge.Edges)


def build_hardware_local(parameters: Any, detent_seed: Any) -> Any:
    """Build sockets and place the preserved legacy detent BRep seed."""

    d = validate_parameters(parameters)
    axis_z = d["HingeAxisOffset"]
    clip_len = d["HingeClipLength"]
    shapes = []
    for y in (-d["HingeClipY"], d["HingeClipY"]):
        outer = Part.makeCylinder(
            d["SocketRadius"],
            clip_len,
            App.Vector(0, y - clip_len / 2.0, axis_z),
            App.Vector(0, 1, 0),
        )
        web = _box(8.0, clip_len, 3.5, App.Vector(-4.0, y - clip_len / 2.0, -1.0))
        socket = outer.fuse(web)
        bore = Part.makeCylinder(
            d["BoreRadius"],
            clip_len + 1.0,
            App.Vector(0, y - (clip_len + 1.0) / 2.0, axis_z),
            App.Vector(0, 1, 0),
        )
        throat = _box(
            d["SocketThroat"],
            clip_len + 1.0,
            d["SocketRadius"] + 1.0,
            App.Vector(
                -d["SocketThroat"] / 2.0,
                y - (clip_len + 1.0) / 2.0,
                axis_z,
            ),
        )
        shapes.append(socket.cut(bore).cut(throat).removeSplitter())

    if detent_seed is None or detent_seed.isNull() or len(detent_seed.Solids) != 1:
        raise ValueError("a valid one-solid legacy detent BRep seed is required")
    for y in (-d["DetentY"], d["DetentY"]):
        detent = detent_seed.copy()
        detent.translate(App.Vector(d["DetentX"], y, 0.0))
        shapes.append(detent)
    return Part.makeCompound(shapes)


def _fuse_hardware(source_shape: Any, hardware_shape: Any) -> Any:
    """Fuse each disconnected feature independently as in the legacy builder."""

    result = source_shape.copy()
    for hardware_solid in hardware_shape.Solids:
        result = result.fuse(hardware_solid)
    return result.removeSplitter()


class StandProxy:
    def __init__(self, obj: Any, parameters: Any):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Parameters", "Inputs", "Shared editable dimensions")
        obj.Parameters = parameters
        self.execute(obj)

    def execute(self, obj: Any) -> None:
        obj.Shape = build_stand_shape(obj.Parameters)

    def __getstate__(self) -> None:
        return None

    def __setstate__(self, state: Any) -> None:
        del state


class CaseHardwareProxy:
    def __init__(self, obj: Any, parameters: Any, side_key: str, detent_seed: Any):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Parameters", "Inputs", "Shared editable dimensions")
        obj.addProperty("App::PropertyLink", "DetentSeed", "Inputs", "Fixed legacy loft BRep seed")
        obj.addProperty("App::PropertyEnumeration", "CaseSide", "Inputs", "Case side local transform")
        obj.CaseSide = ["L", "R"]
        obj.CaseSide = side_key
        obj.Parameters = parameters
        obj.DetentSeed = detent_seed
        self.execute(obj)

    def execute(self, obj: Any) -> None:
        validate_parameters(obj.Parameters)
        placement = hinge_placement(obj.Parameters, str(obj.CaseSide))
        local_shape = build_hardware_local(obj.Parameters, obj.DetentSeed.Shape)
        shape = local_shape.copy()
        shape.transformShape(placement.toMatrix(), True)
        obj.Shape = shape

    def __getstate__(self) -> None:
        return None

    def __setstate__(self, state: Any) -> None:
        del state


class ModifiedCaseProxy:
    def __init__(self, obj: Any, parameters: Any, source: Any, hardware: Any, side_key: str):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Parameters", "Inputs", "Shared editable dimensions")
        obj.addProperty("App::PropertyLink", "Source", "Inputs", "Imported original STEP shape")
        obj.addProperty("App::PropertyLink", "Hardware", "Inputs", "Recomputed attached features")
        obj.addProperty("App::PropertyEnumeration", "CaseSide", "Inputs", "Case side local transform")
        obj.CaseSide = ["L", "R"]
        obj.CaseSide = side_key
        obj.Parameters = parameters
        obj.Source = source
        obj.Hardware = hardware
        self.execute(obj)

    def execute(self, obj: Any) -> None:
        validate_parameters(obj.Parameters)
        if obj.Source is None or obj.Hardware is None:
            raise ValueError("modified case requires both source STEP and hardware features")
        obj.Shape = _fuse_hardware(obj.Source.Shape, obj.Hardware.Shape)

    def __getstate__(self) -> None:
        return None

    def __setstate__(self, state: Any) -> None:
        del state


def _set_color(obj: Any, color: tuple[float, float, float]) -> None:
    if getattr(obj, "ViewObject", None):
        obj.ViewObject.ShapeColor = color
        obj.ViewObject.LineColor = (0.15, 0.15, 0.15)


def _annotate_source(obj: Any, filename: str) -> None:
    source_path = SOURCE_DIR / filename
    obj.addProperty("App::PropertyString", "SourceFile", "Reference", "Relative source STEP path")
    obj.addProperty("App::PropertyString", "SourceSHA256", "Reference", "Imported source file SHA-256")
    obj.SourceFile = f"case/v3/{filename}"
    obj.SourceSHA256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    obj.setEditorMode("SourceFile", 1)
    obj.setEditorMode("SourceSHA256", 1)


def build_document(doc: Any = None) -> Any:
    """Create the editable native model while retaining original STEP shapes."""

    if doc is None:
        doc = App.newDocument("RoBaV3FoldingTenting")
    model_group = doc.addObject("App::DocumentObjectGroup", "FoldingTentingModel")
    model_group.Label = "roBa v3 folding tenting stand"
    reference_group = doc.addObject("App::DocumentObjectGroup", "BaseCaseReferences")
    reference_group.Label = "Original v3 case STEP snapshots (reference only)"
    params = doc.addObject("App::FeaturePython", "TentingParameters")
    params.Label = "Tenting dimensions (mm / degrees)"
    ParametersProxy(params)

    if not DETENT_SEED_PATH.exists():
        raise FileNotFoundError("the preserved legacy detent BRep seed is missing")
    detent_seed_shape = Part.read(str(DETENT_SEED_PATH))
    if detent_seed_shape.isNull() or not detent_seed_shape.isValid() or len(detent_seed_shape.Solids) != 1:
        raise RuntimeError("the preserved legacy detent BRep seed is not a valid one-solid shape")
    detent_seed_shape.translate(App.Vector(-16.0, -14.0, 0.0))
    detent_seed_obj = doc.addObject("Part::Feature", "LegacyDetentSeed")
    detent_seed_obj.Label = "Legacy detent loft BRep seed (fixed profile)"
    detent_seed_obj.Shape = detent_seed_shape
    detent_seed_obj.addProperty(
        "App::PropertyString", "SourceFile", "Reference", "Legacy modified-bottom STEP used to recover the loft"
    )
    detent_seed_obj.addProperty(
        "App::PropertyString", "SourceFaces", "Reference", "Recovered loft surface and tip cap face indices"
    )
    detent_seed_obj.addProperty(
        "App::PropertyString", "SourceSHA256", "Reference", "Legacy modified-bottom STEP SHA-256"
    )
    detent_seed_obj.addProperty(
        "App::PropertyString", "SeedFile", "Reference", "Relative normalized native BRep seed path"
    )
    detent_seed_obj.addProperty(
        "App::PropertyString", "SeedSHA256", "Reference", "Normalized seed file SHA-256"
    )
    detent_seed_obj.SourceFile = "case/v3/tenting/output/bottom_L_tenting.stp"
    detent_seed_obj.SourceFaces = "Face 22 loft surface, Face 23 tip cap; lower cap reconstructed at z=-0.8 mm"
    detent_seed_obj.SourceSHA256 = hashlib.sha256((LEGACY_DIR / "bottom_L_tenting.stp").read_bytes()).hexdigest()
    detent_seed_obj.SeedFile = "case/v3/freecad/reference/legacy_detent.brep"
    detent_seed_obj.SeedSHA256 = hashlib.sha256(DETENT_SEED_PATH.read_bytes()).hexdigest()
    for prop in ("SourceFile", "SourceFaces", "SourceSHA256", "SeedFile", "SeedSHA256"):
        detent_seed_obj.setEditorMode(prop, 1)
    if getattr(detent_seed_obj, "ViewObject", None):
        detent_seed_obj.ViewObject.Visibility = False

    stand = doc.addObject("PartDesign::FeaturePython", "FoldingStand")
    stand.Label = "Universal folding stand"
    StandProxy(stand, params)
    _set_color(stand, (0.82, 0.61, 0.35))
    model_group.addObject(params)
    model_group.addObject(detent_seed_obj)
    model_group.addObject(stand)

    for side_key, side_info in SIDE_DATA.items():
        source_path = SOURCE_DIR / str(side_info["source"])
        if not source_path.exists():
            raise FileNotFoundError(f"source STEP is missing: {source_path}")
        prefix = "Bottom" + side_key
        source_shape = Part.read(str(source_path))
        if source_shape.isNull() or not source_shape.isValid() or len(source_shape.Solids) != 1:
            raise RuntimeError(f"invalid source STEP geometry: {source_path.name}")
        source_obj = doc.addObject("Part::Feature", prefix + "Source")
        source_obj.Label = f"{side_info['source']} (imported STEP snapshot)"
        source_obj.Shape = source_shape
        _annotate_source(source_obj, str(side_info["source"]))
        if getattr(source_obj, "ViewObject", None):
            source_obj.ViewObject.Visibility = False

        hardware_obj = doc.addObject("PartDesign::FeaturePython", prefix + "Hardware")
        hardware_obj.Label = f"{side_info['name']} added sockets and detents"
        CaseHardwareProxy(hardware_obj, params, side_key, detent_seed_obj)
        if getattr(hardware_obj, "ViewObject", None):
            hardware_obj.ViewObject.Visibility = False

        final_obj = doc.addObject("PartDesign::FeaturePython", prefix + "Tenting")
        final_obj.Label = str(side_info["name"])
        ModifiedCaseProxy(final_obj, params, source_obj, hardware_obj, side_key)
        _set_color(final_obj, (0.72, 0.74, 0.78))

        model_group.addObject(source_obj)
        model_group.addObject(hardware_obj)
        model_group.addObject(final_obj)

    for side_key in ("L", "R"):
        filename = f"top_{side_key}.stp"
        source_path = SOURCE_DIR / filename
        if not source_path.exists():
            raise FileNotFoundError(f"reference STEP is missing: {filename}")
        source_shape = Part.read(str(source_path))
        if source_shape.isNull() or not source_shape.isValid() or not source_shape.Solids:
            raise RuntimeError(f"invalid reference STEP geometry: {filename}")
        reference = doc.addObject("Part::Feature", f"Top{side_key}Reference")
        reference.Label = f"{filename} (imported reference snapshot; no recovered sketch history)"
        reference.Shape = source_shape
        _annotate_source(reference, filename)
        if getattr(reference, "ViewObject", None):
            reference.ViewObject.Visibility = False
        reference_group.addObject(reference)

    doc.recompute()
    return doc


def _bounds(shape: Any) -> tuple[float, float, float]:
    # BoundBox is the B-spline control hull and can be materially larger than
    # the actual trimmed solid. Use the exact OCC optimal box, explicitly
    # disabling triangulation and shape tolerance so cached display meshes do
    # not affect dimensional regression or STEP round-trip checks.
    optimal_box = getattr(shape, "optimalBoundingBox", None)
    if not callable(optimal_box):
        raise RuntimeError("FreeCAD Shape.optimalBoundingBox() is required for legacy bbox regression")
    box = optimal_box(False, False)
    return (float(box.XLength), float(box.YLength), float(box.ZLength))


def _shape_summary(shape: Any) -> dict[str, Any]:
    return {
        "is_valid": bool(shape.isValid()),
        "solid_count": len(shape.Solids),
        "volume_mm3": float(shape.Volume),
        "bbox_mm": _bounds(shape),
    }


def _assert_close(actual: float, expected: float, tolerance: float, label: str) -> None:
    if abs(actual - expected) > tolerance:
        raise RuntimeError(f"{label}: {actual:.6f} differs from {expected:.6f} by more than {tolerance:g}")


def _assert_single_solid(shape: Any, label: str) -> None:
    if shape.isNull() or not shape.isValid():
        raise RuntimeError(f"{label}: null or invalid BRep")
    if len(shape.Solids) != 1:
        raise RuntimeError(f"{label}: expected one solid, found {len(shape.Solids)}")


def _global_point(local: tuple[float, float, float], placement: Any) -> Any:
    return placement.multVec(App.Vector(*local))


def _inside(shape: Any, point: Any) -> bool:
    return bool(shape.isInside(point, 1e-6, True))


def _transformed_shape(shape: Any, placement: Any) -> Any:
    result = shape.copy()
    result.transformShape(placement.toMatrix(), True)
    return result


def _overlap_volume(shape_a: Any, shape_b: Any) -> float:
    return float(shape_a.common(shape_b).Volume)


def verify_model(doc: Any) -> dict[str, Any]:
    """Check native geometry against source solids and legacy exports."""

    doc.recompute()
    params = doc.getObject("TentingParameters")
    dims = validate_parameters(params)
    defaults = default_dimension_values()
    legacy_regression_applied = all(abs(dims[name] - defaults[name]) <= 1e-9 for name in defaults)
    source_reference_checks: dict[str, Any] = {}
    for name, filename in REFERENCE_SOURCES.items():
        source_obj = doc.getObject(name)
        source_path = SOURCE_DIR / filename
        if source_obj is None or source_obj.Shape.isNull() or not source_obj.Shape.isValid():
            raise RuntimeError(f"missing or invalid imported case reference: {filename}")
        actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if source_obj.SourceFile != f"case/v3/{filename}" or source_obj.SourceSHA256 != actual_hash:
            raise RuntimeError(f"source reference path/hash mismatch: {filename}")
        source_reference_checks[name] = {
            "source_file": str(source_obj.SourceFile),
            "sha256": str(source_obj.SourceSHA256),
            "solid_count": len(source_obj.Shape.Solids),
            "is_valid": bool(source_obj.Shape.isValid()),
            "snapshot_only": True,
        }
    seed_obj = doc.getObject("LegacyDetentSeed")
    legacy_seed_source = LEGACY_DIR / "bottom_L_tenting.stp"
    if seed_obj is None or not seed_obj.Shape.isValid() or len(seed_obj.Shape.Solids) != 1:
        raise RuntimeError("missing or invalid native detent-loft seed BRep")
    _assert_close(float(seed_obj.Shape.Volume), 8.97045823077259, 0.001, "preserved detent seed volume")
    if (
        seed_obj.SeedFile != "case/v3/freecad/reference/legacy_detent.brep"
        or seed_obj.SeedSHA256 != hashlib.sha256(DETENT_SEED_PATH.read_bytes()).hexdigest()
        or seed_obj.SourceSHA256 != hashlib.sha256(legacy_seed_source.read_bytes()).hexdigest()
    ):
        raise RuntimeError("legacy detent seed provenance/hash check failed")
    source_reference_checks["LegacyDetentSeed"] = {
        "source_file": str(seed_obj.SourceFile),
        "source_faces": str(seed_obj.SourceFaces),
        "source_sha256": str(seed_obj.SourceSHA256),
        "seed_file": str(seed_obj.SeedFile),
        "seed_sha256": str(seed_obj.SeedSHA256),
        "shape": _shape_summary(seed_obj.Shape),
        "snapshot_only": True,
    }
    stand_obj = doc.getObject("FoldingStand")
    _assert_single_solid(stand_obj.Shape, "folding stand")
    if legacy_regression_applied:
        stand_legacy = _load_legacy("folding_tenting_stand")
        stand_expected = stand_legacy["result"]
        _assert_close(float(stand_obj.Shape.Volume), float(stand_expected["volume"]), 1.0, "stand legacy volume")
        for axis, actual, expected in zip("XYZ", _bounds(stand_obj.Shape), stand_expected["bbox"]):
            _assert_close(actual, float(expected), 0.16, f"stand legacy bbox {axis}")

    stand_z = dims["HingeAxisOffset"]
    for point in ((0.0, 0.0, stand_z), (10.0, 0.0, stand_z)):
        if not _inside(stand_obj.Shape, App.Vector(*point)):
            raise RuntimeError(f"stand material-point check failed: {point}")
    for point in (
        (dims["DetentX"], -dims["DetentY"], stand_z),
        (dims["DetentX"], dims["DetentY"], stand_z),
    ):
        if _inside(stand_obj.Shape, App.Vector(*point)):
            raise RuntimeError(f"stand detent-hole void check failed: {point}")

    cases: dict[str, Any] = {}
    assemblies: dict[str, Any] = {}
    stand_shape = stand_obj.Shape
    deploy_angle = dims["DeployAngle"]
    for side_key, side_info in SIDE_DATA.items():
        prefix = "Bottom" + side_key
        source_obj = doc.getObject(prefix + "Source")
        hardware_obj = doc.getObject(prefix + "Hardware")
        final_obj = doc.getObject(prefix + "Tenting")
        source_shape = source_obj.Shape
        shape = final_obj.Shape
        _assert_single_solid(source_shape, f"{side_key} original bottom")
        _assert_single_solid(shape, f"{side_key} modified bottom")
        if legacy_regression_applied:
            legacy = _load_legacy(str(side_info["name"]))
            expected = legacy["result"]
            _assert_close(float(shape.Volume), float(expected["volume"]), 1.25, f"{side_key} legacy volume")
            for axis, actual, wanted in zip("XYZ", _bounds(shape), expected["bbox"]):
                _assert_close(actual, float(wanted), 0.30, f"{side_key} legacy bbox {axis}")

        original_volume = float(source_shape.Volume)
        source_legacy = {"L": 16973.65, "R": 20008.61}[side_key]
        _assert_close(original_volume, source_legacy, 0.10, f"{side_key} immutable source STEP volume")
        removed_original_volume = float(source_shape.cut(shape).Volume)
        if removed_original_volume > 0.02:
            raise RuntimeError(f"{side_key} modified bottom removes {removed_original_volume:.6f} mm^3 of original geometry")

        placement = hinge_placement(params, side_key)
        material_points = (
            _global_point((2.5, -dims["HingeClipY"], dims["HingeAxisOffset"]), placement),
            _global_point((2.5, dims["HingeClipY"], dims["HingeAxisOffset"]), placement),
        )
        void_points = (
            _global_point((0.0, -dims["HingeClipY"], dims["HingeAxisOffset"]), placement),
            _global_point((0.0, dims["HingeClipY"], dims["HingeAxisOffset"]), placement),
        )
        if not all(_inside(shape, point) for point in material_points):
            raise RuntimeError(f"{side_key} socket material-point check failed")
        if any(_inside(shape, point) for point in void_points):
            raise RuntimeError(f"{side_key} axle bore void-point check failed")

        folded = _transformed_shape(stand_shape, placement)
        deployed_local = stand_shape.copy()
        deployed_local.rotate(
            App.Vector(0, 0, dims["HingeAxisOffset"]),
            App.Vector(0, 1, 0),
            -deploy_angle,
        )
        deployed = _transformed_shape(deployed_local, placement)
        folded_overlap = _overlap_volume(shape, folded)
        deployed_overlap = _overlap_volume(shape, deployed)
        if folded_overlap > 2.0 or deployed_overlap > 2.0:
            raise RuntimeError(
                f"{side_key} assembly overlap exceeds 2 mm^3: folded={folded_overlap:.6f}, deployed={deployed_overlap:.6f}"
            )

        cases[side_key] = {
            "source": _shape_summary(source_shape),
            "added_hardware": {
                "is_valid": bool(hardware_obj.Shape.isValid()),
                "solid_count": len(hardware_obj.Shape.Solids),
                "volume_mm3": float(hardware_obj.Shape.Volume),
            },
            "modified": _shape_summary(shape),
            "legacy_comparison": {
                "applied": legacy_regression_applied,
                "volume_tolerance_mm3": 1.25,
                "bbox_tolerance_mm": 0.30,
            },
            "original_material_removed_mm3": removed_original_volume,
            "material_points_checked": len(material_points),
            "bore_void_points_checked": len(void_points),
        }
        assemblies[side_key] = {
            "folded_overlap_mm3": folded_overlap,
            "deployed_overlap_mm3": deployed_overlap,
            "deployment_angle_deg": deploy_angle,
            "limit_mm3": 2.0,
        }

    pin = dims["PinRadius"]
    bore = dims["BoreRadius"]
    throat = dims["SocketThroat"]
    dimensions_check = {
        "pin_radius_mm": pin,
        "bore_radius_mm": bore,
        "socket_throat_width_mm": throat,
        "diametral_bore_clearance_mm": 2.0 * (bore - pin),
        "diametral_throat_retention_mm": 2.0 * pin - throat,
        "socket_radial_wall_mm": dims["SocketRadius"] - bore,
    }
    if min(
        dimensions_check["diametral_bore_clearance_mm"],
        dimensions_check["diametral_throat_retention_mm"],
        dimensions_check["socket_radial_wall_mm"],
    ) <= 0.0:
        raise RuntimeError("pin/bore/throat/socket wall regression check failed")

    angle_extra = math.degrees(
        math.atan2(
            dims["HingeAxisOffset"]
            + dims["StandLength"] * math.sin(math.radians(deploy_angle))
            + dims["StandThickness"] / 2.0 * math.cos(math.radians(deploy_angle)),
            110.0,
        )
    )
    return {
        "status": "PASS",
        "contract_version": CONTRACT_VERSION,
        "units": {"length": "mm", "angle": "degrees"},
        "legacy_default_regression_applied": legacy_regression_applied,
        "imported_source_references": source_reference_checks,
        "dimensions": dims,
        "pin_bore_throat_regression": dimensions_check,
        "stand": _shape_summary(stand_shape),
        "cases": cases,
        "assembly_end_pose_overlaps": assemblies,
        "derived_nominal_tent_angle_deg": dims["BaseTentAngle"] + angle_extra,
        "physical_strength_or_print_validation": "not performed",
    }


def _load_legacy(name: str) -> dict[str, Any]:
    path = LEGACY_DIR / f"{name}.verified.json"
    if not path.exists():
        raise FileNotFoundError(f"legacy verification record is required: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _stl_edge_report(path: Path) -> dict[str, Any]:
    """Check binary STL edge incidence, orientation, and degenerate facets."""

    raw = path.read_bytes()
    if len(raw) < 84:
        raise RuntimeError(f"invalid STL: {path.name} is shorter than its header")
    triangle_count = struct.unpack_from("<I", raw, 80)[0]
    if len(raw) != 84 + 50 * triangle_count:
        raise RuntimeError(f"invalid binary STL length in {path.name}")
    edge_counts: dict[tuple[Any, Any], int] = {}
    edge_directions: dict[tuple[Any, Any], int] = {}
    degenerate = 0
    for index in range(triangle_count):
        offset = 84 + 50 * index + 12
        vertices = [struct.unpack_from("<fff", raw, offset + 12 * i) for i in range(3)]
        a, b, c = vertices
        ab = tuple(b[i] - a[i] for i in range(3))
        ac = tuple(c[i] - a[i] for i in range(3))
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        if sum(component * component for component in cross) <= 1e-18:
            degenerate += 1
        keys = [tuple(round(float(value), 5) for value in vertex) for vertex in vertices]
        for start, end in ((keys[0], keys[1]), (keys[1], keys[2]), (keys[2], keys[0])):
            edge = (start, end) if start < end else (end, start)
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
            edge_directions[edge] = edge_directions.get(edge, 0) + (1 if (start, end) == edge else -1)
    boundary = sum(1 for count in edge_counts.values() if count == 1)
    nonmanifold = sum(1 for count in edge_counts.values() if count > 2)
    misoriented = sum(1 for edge, count in edge_counts.items() if count == 2 and edge_directions[edge] != 0)
    report = {
        "triangles": triangle_count,
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "misoriented_edges": misoriented,
        "degenerate_triangles": degenerate,
        "closed_oriented_mesh": boundary == 0 and nonmanifold == 0 and misoriented == 0 and degenerate == 0,
    }
    if not report["closed_oriented_mesh"]:
        raise RuntimeError(f"STL mesh check failed for {path.name}: {report}")
    return report


def _export_one(shape: Any, stage: Path, name: str) -> dict[str, Any]:
    _assert_single_solid(shape, name)
    step_path = stage / f"{name}.stp"
    stl_path = stage / f"{name}.stl"
    shape.exportStep(str(step_path))
    import MeshPart

    mesh = MeshPart.meshFromShape(
        Shape=shape,
        LinearDeflection=0.10,
        AngularDeflection=0.30,
        Relative=False,
    )
    mesh.write(str(stl_path))

    imported = Part.read(str(step_path))
    _assert_single_solid(imported, f"reimported STEP {name}")
    volume_delta = abs(float(imported.Volume) - float(shape.Volume))
    relative_volume_delta = volume_delta / max(abs(float(shape.Volume)), 1e-12)
    if relative_volume_delta > STEP_ROUND_TRIP_RELATIVE_VOLUME_LIMIT:
        raise RuntimeError(
            f"STEP round trip {name} relative volume delta {relative_volume_delta:.6%} exceeds "
            f"{STEP_ROUND_TRIP_RELATIVE_VOLUME_LIMIT:.6%}"
        )
    bbox_before = _bounds(shape)
    bbox_after = _bounds(imported)
    bbox_deltas = tuple(abs(before - after) for before, after in zip(bbox_before, bbox_after))
    if max(bbox_deltas, default=0.0) > STEP_ROUND_TRIP_BBOX_LIMIT_MM:
        raise RuntimeError(
            f"STEP round trip {name} optimal bounding-box delta exceeds "
            f"{STEP_ROUND_TRIP_BBOX_LIMIT_MM:g} mm: {bbox_deltas}"
        )
    distance_report = _sampled_round_trip_surface_distance(shape, imported)
    if distance_report["max_sampled_surface_distance_mm"] > STEP_ROUND_TRIP_SURFACE_DISTANCE_LIMIT_MM:
        raise RuntimeError(
            f"STEP round trip {name} sampled boundary distance exceeds "
            f"{STEP_ROUND_TRIP_SURFACE_DISTANCE_LIMIT_MM:g} mm: {distance_report}"
        )
    mesh_report = _stl_edge_report(stl_path)
    return {
        "step_file": step_path.name,
        "stl_file": stl_path.name,
        "step_round_trip": _shape_summary(imported),
        "step_round_trip_comparison": {
            "absolute_volume_delta_mm3": volume_delta,
            "relative_volume_delta": relative_volume_delta,
            "relative_volume_limit": STEP_ROUND_TRIP_RELATIVE_VOLUME_LIMIT,
            "optimal_bbox_before_mm": bbox_before,
            "optimal_bbox_after_mm": bbox_after,
            "optimal_bbox_axis_length_delta_mm": bbox_deltas,
            "optimal_bbox_axis_length_limit_mm": STEP_ROUND_TRIP_BBOX_LIMIT_MM,
            "sampled_boundary_distance": distance_report,
        },
        "stl": mesh_report,
        "stl_tessellation": {"linear_deflection_mm": 0.10, "angular_deflection_rad": 0.30},
    }


def _sampled_round_trip_surface_distance(shape: Any, imported: Any) -> dict[str, Any]:
    """Compare deterministic BRep and tessellation vertices in both directions."""

    def sample(source: Any, target: Any) -> tuple[int, float]:
        nodes, facets = source.tessellate(STEP_ROUND_TRIP_SAMPLE_DEFLECTION_MM)
        if not nodes or not facets:
            raise RuntimeError("could not tessellate a STEP round-trip shape for boundary sampling")
        brep_vertices = list(source.Vertexes)
        if not brep_vertices:
            raise RuntimeError("could not sample BRep vertices for STEP round-trip comparison")
        brep_count = min(STEP_ROUND_TRIP_SAMPLE_LIMIT, len(brep_vertices))
        mesh_count = min(STEP_ROUND_TRIP_SAMPLE_LIMIT, len(nodes))
        max_distance = 0.0
        for index in range(brep_count):
            brep_vertex = brep_vertices[(index * (len(brep_vertices) - 1)) // max(brep_count - 1, 1)]
            distance = float(brep_vertex.distToShape(target)[0])
            max_distance = max(max_distance, distance)
        for index in range(mesh_count):
            node = nodes[(index * (len(nodes) - 1)) // max(mesh_count - 1, 1)]
            distance = float(Part.Vertex(node).distToShape(target)[0])
            max_distance = max(max_distance, distance)
        return brep_count + mesh_count, max_distance

    forward_count, forward_max = sample(shape, imported)
    reverse_count, reverse_max = sample(imported, shape)
    return {
        "sampling_deflection_mm": STEP_ROUND_TRIP_SAMPLE_DEFLECTION_MM,
        "samples_per_direction": min(forward_count, reverse_count),
        "native_to_step_max_mm": forward_max,
        "step_to_native_max_mm": reverse_max,
        "max_sampled_surface_distance_mm": max(forward_max, reverse_max),
        "limit_mm": STEP_ROUND_TRIP_SURFACE_DISTANCE_LIMIT_MM,
        "method": "evenly spaced exact BRep and tessellation vertices; bidirectional point-to-solid distance",
    }


def verify_reloaded_document(doc: Any) -> dict[str, Any]:
    """Verify proxy restoration and prove linked features recompute after edits."""

    params = doc.getObject("TentingParameters")
    stand = doc.getObject("FoldingStand")
    left = doc.getObject("BottomLTenting")
    if params is None or stand is None or left is None:
        raise RuntimeError("FCStd is missing expected native model objects")
    for obj in (params, stand, doc.getObject("BottomLHardware"), left):
        proxy = getattr(obj, "Proxy", None)
        if proxy is None or proxy.__class__.__module__ != "roba_freecad":
            raise RuntimeError(f"FeaturePython proxy did not restore from roba_freecad: {obj.Name}")

    doc.recompute()
    baseline_stand_volume = float(stand.Shape.Volume)
    baseline_left_volume = float(left.Shape.Volume)
    old_thickness = _dimension(params, "StandThickness")
    old_socket_radius = _dimension(params, "SocketRadius")

    params.StandThickness = old_thickness + 0.10
    doc.recompute()
    changed_stand_volume = float(stand.Shape.Volume)
    if abs(changed_stand_volume - baseline_stand_volume) < 1.0:
        raise RuntimeError("StandThickness edit did not change the dependent stand shape")
    if _dimension(params, "StandThickness") <= old_thickness:
        raise RuntimeError("StandThickness edit did not persist in the dimension object")

    params.SocketRadius = old_socket_radius + 0.10
    doc.recompute()
    changed_left_volume = float(left.Shape.Volume)
    if abs(changed_left_volume - baseline_left_volume) < 1.0:
        raise RuntimeError("SocketRadius edit did not change the dependent case hardware and final case")

    params.StandThickness = old_thickness
    params.SocketRadius = old_socket_radius
    doc.recompute()
    _assert_close(float(stand.Shape.Volume), baseline_stand_volume, 1e-6, "restored stand volume")
    _assert_close(float(left.Shape.Volume), baseline_left_volume, 1e-5, "restored left case volume")
    return {
        "status": "PASS",
        "proxies_restored_from_module": True,
        "stand_thickness_edit": {
            "from_mm": old_thickness,
            "to_mm": old_thickness + 0.10,
            "volume_before_mm3": baseline_stand_volume,
            "volume_changed_mm3": changed_stand_volume,
            "restored_volume_mm3": float(stand.Shape.Volume),
        },
        "socket_radius_edit": {
            "from_mm": old_socket_radius,
            "to_mm": old_socket_radius + 0.10,
            "left_case_volume_before_mm3": baseline_left_volume,
            "left_case_volume_changed_mm3": changed_left_volume,
            "restored_volume_mm3": float(left.Shape.Volume),
        },
        "restored_defaults": validate_parameters(params),
    }


def _phase_build(fcstd_path: Path) -> None:
    doc = build_document()
    verify_model(doc)
    doc.recompute()
    doc.saveAs(str(fcstd_path))
    App.closeDocument(doc.Name)
    print(f"[build] saved native document: {fcstd_path.name}")


def _phase_mutate(fcstd_path: Path, evidence_path: Path) -> None:
    doc = App.openDocument(str(fcstd_path))
    evidence = verify_reloaded_document(doc)
    doc.recompute()
    doc.save()
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    App.closeDocument(doc.Name)
    print("[reopen] proxies restored, edits recomputed, defaults restored, FCStd saved")


def _phase_finalize(fcstd_path: Path, stage: Path, evidence_path: Path) -> None:
    doc = App.openDocument(str(fcstd_path))
    doc.recompute()
    geometry = verify_model(doc)
    with evidence_path.open("r", encoding="utf-8") as handle:
        mutation = json.load(handle)
    if mutation.get("status") != "PASS":
        raise RuntimeError("fresh-process parameter-edit evidence is missing or failed")

    exports: dict[str, Any] = {}
    exports["folding_tenting_stand"] = _export_one(doc.getObject("FoldingStand").Shape, stage, "folding_tenting_stand")
    for side_key, side_info in SIDE_DATA.items():
        obj = doc.getObject("Bottom" + side_key + "Tenting")
        exports[str(side_info["name"])] = _export_one(obj.Shape, stage, str(side_info["name"]))

    for part_name, export_info in exports.items():
        if part_name == "folding_tenting_stand":
            geometry_summary = geometry["stand"]
        else:
            side_key = "L" if part_name == "bottom_L_tenting" else "R"
            geometry_summary = geometry["cases"][side_key]["modified"]
        part_record = {
            "status": "PASS",
            "part": part_name,
            "geometry": geometry_summary,
            "export": export_info,
            "units": {"length": "mm", "angle": "degrees"},
        }
        (stage / f"{part_name}.verified.json").write_text(
            json.dumps(part_record, indent=2) + "\n", encoding="utf-8"
        )

    source_files = {
        name: str(doc.getObject(name).SourceFile) for name in REFERENCE_SOURCES
    }
    source_hashes = {
        **{name: str(doc.getObject(name).SourceSHA256) for name in REFERENCE_SOURCES},
        "LegacyDetentSeed": str(doc.getObject("LegacyDetentSeed").SeedSHA256),
        "LegacyDetentSeedSource": str(doc.getObject("LegacyDetentSeed").SourceSHA256),
    }
    App.closeDocument(doc.Name)
    artifact_names = [DOCUMENT_FILE]
    for part_name in exports:
        artifact_names.extend(
            (f"{part_name}.stp", f"{part_name}.stl", f"{part_name}.verified.json")
        )
    artifact_hashes = {
        name: hashlib.sha256((stage / name).read_bytes()).hexdigest() for name in artifact_names
    }

    record = {
        "status": "PASS",
        "generated_by": "FreeCAD Part API",
        "freecad_version": App.Version()[0:4],
        "source_files": source_files,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "native_document": DOCUMENT_FILE,
        "source_hashes": source_hashes,
        "native_reopen_and_parameter_edit": mutation,
        "geometry": geometry,
        "exports": exports,
        "artifact_sha256": artifact_hashes,
    }
    # This is the success manifest, written only after every export has passed.
    (stage / "freecad_build.verified.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print("[verify] native shapes, STEP round trips, and closed STL meshes passed")


def export_current_document(doc: Any) -> dict[str, Any]:
    """Validate and export the active, already-saved native document values."""

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    status_path = GENERATED_DIR / "latest_run_status.json"
    status: dict[str, Any] = {
        "status": "RUNNING",
        "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "export-current-document",
    }
    status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    stage = Path(tempfile.mkdtemp(prefix=".freecad-export-", dir=str(GENERATED_DIR)))
    try:
        if not getattr(doc, "FileName", ""):
            raise RuntimeError("save the native FCStd document before exporting edited dimensions")
        doc.recompute()
        geometry = verify_model(doc)
        # Bind the exported live geometry to the FCStd that the manifest hashes.
        doc.save()
        native_path = Path(doc.FileName)
        native_hash = hashlib.sha256(native_path.read_bytes()).hexdigest()
        exports: dict[str, Any] = {
            "folding_tenting_stand": _export_one(doc.getObject("FoldingStand").Shape, stage, "folding_tenting_stand")
        }
        for side_key, side_info in SIDE_DATA.items():
            name = str(side_info["name"])
            exports[name] = _export_one(doc.getObject("Bottom" + side_key + "Tenting").Shape, stage, name)

        for name, export_info in exports.items():
            if name == "folding_tenting_stand":
                part_geometry = geometry["stand"]
            else:
                side = "L" if name == "bottom_L_tenting" else "R"
                part_geometry = geometry["cases"][side]["modified"]
            (stage / f"{name}.verified.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "part": name,
                        "geometry": part_geometry,
                        "export": export_info,
                        "units": {"length": "mm", "angle": "degrees"},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        artifact_names: list[str] = []
        for name in exports:
            artifact_names.extend((f"{name}.stp", f"{name}.stl", f"{name}.verified.json"))
        record = {
            "status": "PASS",
            "generated_by": "FreeCAD Part API",
            "freecad_version": App.Version()[0:4],
            "native_document": native_path.name,
            "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "native_document_sha256": native_hash,
            "units": {"length": "mm", "angle": "degrees"},
            "source_hashes": {
                **{name: str(doc.getObject(name).SourceSHA256) for name in REFERENCE_SOURCES},
                "LegacyDetentSeed": str(doc.getObject("LegacyDetentSeed").SeedSHA256),
                "LegacyDetentSeedSource": str(doc.getObject("LegacyDetentSeed").SourceSHA256),
            },
            "geometry": geometry,
            "exports": exports,
            "artifact_sha256": {
                name: hashlib.sha256((stage / name).read_bytes()).hexdigest()
                for name in artifact_names
            },
        }
        (stage / "freecad_build.verified.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
        for name in artifact_names:
            os.replace(str(stage / name), str(GENERATED_DIR / name))
        os.replace(
            str(stage / "freecad_build.verified.json"),
            str(GENERATED_DIR / "freecad_build.verified.json"),
        )
        shutil.rmtree(str(stage), ignore_errors=True)
        status["status"] = "PASS"
        status["finished_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        status["manifest"] = "freecad_build.verified.json"
        status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        return record
    except Exception as exc:
        shutil.rmtree(str(stage), ignore_errors=True)
        status["status"] = "FAIL"
        status["finished_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        status["error_type"] = type(exc).__name__
        status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        raise


def _run_phase(phase: str, fcstd_path: Path, stage: Path, evidence_path: Path) -> None:
    if phase == "build":
        _phase_build(fcstd_path)
    elif phase == "mutate":
        _phase_mutate(fcstd_path, evidence_path)
    elif phase == "finalize":
        _phase_finalize(fcstd_path, stage, evidence_path)
    else:
        raise ValueError(f"unknown build phase: {phase}")


def build_verify_command() -> None:
    """Run build, save, edit/restore, and reopen checks in fresh processes."""

    import subprocess
    import sys

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    status_path = GENERATED_DIR / "latest_run_status.json"
    run_record: dict[str, Any] = {
        "status": "RUNNING",
        "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "phases": [],
    }
    status_path.write_text(json.dumps(run_record, indent=2) + "\n", encoding="utf-8")
    stage = Path(tempfile.mkdtemp(prefix=".freecad-build-", dir=str(GENERATED_DIR)))
    fcstd_path = stage / DOCUMENT_FILE
    evidence_path = stage / "parameter_edit.verified.json"
    try:
        for phase in ("build", "mutate", "finalize"):
            run_record["phases"].append({"name": phase, "status": "RUNNING"})
            command = [
                sys.executable,
                str(MODULE_DIR / "build_verify.py"),
                "--phase",
                phase,
                "--fcstd",
                str(fcstd_path),
                "--stage",
                str(stage),
                "--evidence",
                str(evidence_path),
            ]
            completed = subprocess.run(command, cwd=str(REPO_ROOT), text=True, check=False)
            if completed.returncode != 0:
                raise RuntimeError(f"FreeCAD {phase} subprocess exited with {completed.returncode}")
            run_record["phases"][-1]["status"] = "PASS"

        publish_names = [DOCUMENT_FILE]
        for side_info in SIDE_DATA.values():
            prefix = str(side_info["name"])
            publish_names.extend((f"{prefix}.stp", f"{prefix}.stl", f"{prefix}.verified.json"))
        publish_names.extend(
            (
                "folding_tenting_stand.stp",
                "folding_tenting_stand.stl",
                "folding_tenting_stand.verified.json",
            )
        )
        for name in publish_names:
            source = stage / name
            if not source.exists():
                raise RuntimeError(f"verified build did not produce {name}")
        for name in publish_names:
            os.replace(str(stage / name), str(GENERATED_DIR / name))
        if not (stage / "freecad_build.verified.json").exists():
            raise RuntimeError("verified build did not produce the success manifest")
        os.replace(
            str(stage / "freecad_build.verified.json"),
            str(GENERATED_DIR / "freecad_build.verified.json"),
        )
        run_record["status"] = "PASS"
        run_record["finished_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        run_record["manifest"] = "freecad_build.verified.json"
        status_path.write_text(json.dumps(run_record, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(str(stage), ignore_errors=True)
        print(f"[done] verified FreeCAD artifacts published in {GENERATED_DIR}")
    except Exception as exc:
        run_record["status"] = "FAIL"
        run_record["finished_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        run_record["error_type"] = type(exc).__name__
        run_record["error"] = str(exc)
        if run_record["phases"] and run_record["phases"][-1]["status"] == "RUNNING":
            run_record["phases"][-1]["status"] = "FAIL"
        status_path.write_text(json.dumps(run_record, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(str(stage), ignore_errors=True)
        raise
