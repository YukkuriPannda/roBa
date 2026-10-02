"""Small independent verification helper for the tenting CAD exports."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


Point = tuple[float, float, float]


@dataclass(frozen=True)
class VerificationSpec:
    """Frozen expectations derived from the design contract."""

    volume_range: tuple[float, float]
    bbox: tuple[float | None, float | None, float | None]
    bbox_tolerance: float = 0.2
    material_points: tuple[Point, ...] = ()
    void_points: tuple[Point, ...] = ()
    expected_solids: int = 1


def _shape(part):
    import cadquery as cq

    return part.val() if isinstance(part, cq.Workplane) else part


def _classify(solid, point: Point) -> str:
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_OUT
    from OCP.gp import gp_Pnt

    classifier = BRepClass3d_SolidClassifier(solid.wrapped)
    classifier.Perform(gp_Pnt(*point), 1e-6)
    state = classifier.State()
    if state == TopAbs_IN:
        return "material"
    if state == TopAbs_OUT:
        return "void"
    return "boundary"


def verify_shape(part, spec: VerificationSpec) -> dict:
    """Raise when topology or a frozen design-intent check fails."""

    from OCP.BRepCheck import BRepCheck_Analyzer

    shape = _shape(part)
    solids = tuple(shape.Solids())
    bounds = shape.BoundingBox()
    measured_bbox = (bounds.xlen, bounds.ylen, bounds.zlen)
    measured_volume = sum(solid.Volume() for solid in solids)
    failures: list[str] = []

    if not BRepCheck_Analyzer(shape.wrapped).IsValid():
        failures.append("BRep is invalid")
    if len(solids) != spec.expected_solids:
        failures.append(f"solid count {len(solids)} != {spec.expected_solids}")
    if not spec.volume_range[0] <= measured_volume <= spec.volume_range[1]:
        failures.append(
            f"volume {measured_volume:.3f} not in {spec.volume_range[0]:.3f}..{spec.volume_range[1]:.3f}"
        )
    for axis, actual, expected in zip("XYZ", measured_bbox, spec.bbox):
        if expected is not None and abs(actual - expected) > spec.bbox_tolerance:
            failures.append(
                f"bbox {axis} {actual:.3f} != {expected:.3f} +/- {spec.bbox_tolerance:.3f}"
            )

    if len(solids) == 1:
        for point in spec.material_points:
            state = _classify(solids[0], point)
            if state != "material":
                failures.append(f"material point {point} classified as {state}")
        for point in spec.void_points:
            state = _classify(solids[0], point)
            if state != "void":
                failures.append(f"void point {point} classified as {state}")
    elif spec.material_points or spec.void_points:
        failures.append("point checks require exactly one solid")

    result = {
        "is_valid": not any(failure == "BRep is invalid" for failure in failures),
        "solid_count": len(solids),
        "volume": measured_volume,
        "bbox": measured_bbox,
        "material_points_checked": len(spec.material_points),
        "void_points_checked": len(spec.void_points),
    }
    status = "PASS" if not failures else "FAIL"
    print(
        f"[verify] {status}: solids={len(solids)}, volume={measured_volume:.3f} mm^3, "
        f"bbox={measured_bbox[0]:.3f} x {measured_bbox[1]:.3f} x {measured_bbox[2]:.3f} mm"
    )
    if failures:
        raise RuntimeError("verification failed:\n- " + "\n- ".join(failures))
    return result


def export_verified(part, output_dir: Path, name: str, spec: VerificationSpec) -> dict:
    """Verify, then export STEP/STL plus a durable JSON record."""

    import cadquery as cq

    result = verify_shape(part, spec)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for extension in ("stp", "stl"):
        target = output_dir / f"{name}.{extension}"
        export_type = "STEP" if extension == "stp" else "STL"
        cq.exporters.export(part, str(target), exportType=export_type)
        files.append(str(target.resolve()))
    record = {
        "part": name,
        "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "spec": asdict(spec),
        "result": result,
        "files": files,
    }
    record_path = output_dir / f"{name}.verified.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"[verify] exported {name}: {', '.join(files)}")
    return result
