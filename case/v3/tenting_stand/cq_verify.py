"""Independent design-intent verification for CadQuery parts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


Point = tuple[float, float, float]
ExpectedBBox = tuple[float | None, float | None, float | None]


@dataclass(frozen=True)
class VerificationSpec:
    """Frozen expectations derived independently from the generated shape."""

    expected_solids: int = 1
    volume_range: tuple[float, float] | None = None
    bbox: ExpectedBBox | None = None
    bbox_tolerance: float = 0.05
    material_points: tuple[Point, ...] = ()
    void_points: tuple[Point, ...] = ()
    point_tolerance: float = 1e-6

    def __post_init__(self) -> None:
        if self.expected_solids < 1:
            raise ValueError("expected_solids must be at least 1")
        if self.volume_range is not None:
            low, high = self.volume_range
            if low < 0 or high <= low:
                raise ValueError("volume_range must satisfy 0 <= low < high")
        if self.bbox is not None and len(self.bbox) != 3:
            raise ValueError("bbox must contain expected X, Y, Z lengths")
        if self.bbox_tolerance < 0 or self.point_tolerance < 0:
            raise ValueError("tolerances cannot be negative")
        has_bbox_check = self.bbox is not None and any(
            value is not None for value in self.bbox
        )
        if not (
            self.volume_range is not None
            or has_bbox_check
            or self.material_points
            or self.void_points
        ):
            raise ValueError("provide an independent intent check")


@dataclass(frozen=True)
class VerificationResult:
    is_valid: bool
    solid_count: int
    volume: float
    bbox: tuple[float, float, float]
    material_points_checked: int
    void_points_checked: int


class VerificationError(RuntimeError):
    def __init__(self, failures: Sequence[str], result: VerificationResult):
        self.failures = tuple(failures)
        self.result = result
        details = "\n".join(f"- {failure}" for failure in self.failures)
        super().__init__(f"CadQuery verification failed:\n{details}")


def _shape(part):
    import cadquery as cq

    if isinstance(part, cq.Workplane):
        return part.val()
    if isinstance(part, cq.Shape):
        return part
    raise TypeError("part must be a cadquery.Workplane or cadquery.Shape")


def _classify_point(solid, point: Point, tolerance: float) -> str:
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_OUT
    from OCP.gp import gp_Pnt

    classifier = BRepClass3d_SolidClassifier(solid.wrapped)
    classifier.Perform(gp_Pnt(*map(float, point)), tolerance)
    state = classifier.State()
    if state == TopAbs_IN:
        return "material"
    if state == TopAbs_OUT:
        return "void"
    return "boundary"


def verify_shape(part, spec: VerificationSpec, *, verbose: bool = True) -> VerificationResult:
    from OCP.BRepCheck import BRepCheck_Analyzer

    shape = _shape(part)
    solids = tuple(shape.Solids())
    is_valid = bool(BRepCheck_Analyzer(shape.wrapped).IsValid())
    volume = float(sum(solid.Volume() for solid in solids))
    bounds = shape.BoundingBox()
    bbox = (float(bounds.xlen), float(bounds.ylen), float(bounds.zlen))
    result = VerificationResult(
        is_valid=is_valid,
        solid_count=len(solids),
        volume=volume,
        bbox=bbox,
        material_points_checked=len(spec.material_points),
        void_points_checked=len(spec.void_points),
    )

    failures: list[str] = []
    if not is_valid:
        failures.append("BRepCheck reports invalid topology")
    if len(solids) != spec.expected_solids:
        failures.append(f"solid count is {len(solids)}, expected {spec.expected_solids}")
    if spec.volume_range is not None:
        low, high = spec.volume_range
        if not low <= volume <= high:
            failures.append(f"volume is {volume:.3f} mm^3, expected {low:.3f}..{high:.3f}")
    if spec.bbox is not None:
        for axis, measured, expected in zip("XYZ", bbox, spec.bbox):
            if expected is not None and abs(measured - expected) > spec.bbox_tolerance:
                failures.append(
                    f"bbox {axis} is {measured:.3f} mm, expected {expected:.3f} "
                    f"+/- {spec.bbox_tolerance:.3f}"
                )

    if spec.material_points or spec.void_points:
        if len(solids) != 1:
            failures.append("point checks require exactly one solid")
        else:
            solid = solids[0]
            for point in spec.material_points:
                state = _classify_point(solid, point, spec.point_tolerance)
                if state != "material":
                    failures.append(f"point {tuple(point)} should be material, got {state}")
            for point in spec.void_points:
                state = _classify_point(solid, point, spec.point_tolerance)
                if state != "void":
                    failures.append(f"point {tuple(point)} should be void, got {state}")

    if verbose:
        status = "PASS" if not failures else "FAIL"
        print(f"[verify] {status}: valid={is_valid}, solids={len(solids)}")
        print(f"[verify] volume={volume:.3f} mm^3")
        print(f"[verify] bbox={bbox[0]:.3f} x {bbox[1]:.3f} x {bbox[2]:.3f} mm")
        print(
            "[verify] points="
            f"{len(spec.material_points)} material, {len(spec.void_points)} void"
        )
    if failures:
        raise VerificationError(failures, result)
    return result


def export_verified(
    part,
    output_dir: str | Path,
    name: str,
    spec: VerificationSpec,
    *,
    formats: Iterable[str] = ("step", "stl"),
    verbose: bool = True,
) -> VerificationResult:
    import cadquery as cq

    if not name or Path(name).name != name:
        raise ValueError("name must be a plain file stem without path components")
    requested_formats = tuple(str(fmt).lower().lstrip(".") for fmt in formats)
    unsupported = set(requested_formats) - {"step", "stp", "stl"}
    if not requested_formats or unsupported:
        raise ValueError(f"formats must be step/stp/stl, got {requested_formats}")

    result = verify_shape(part, spec, verbose=verbose)
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for fmt in requested_formats:
        target = destination / f"{name}.{fmt}"
        cq.exporters.export(part, str(target))
        written.append(str(target.relative_to(destination.parent)))

    record = {
        "part": name,
        "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "spec": asdict(spec),
        "result": asdict(result),
        "files": written,
    }
    record_path = destination / f"{name}.verified.json"
    record_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if verbose:
        print(f"[verify] exported: {', '.join(written)}")
        print(f"[verify] record: {record_path}")
    return result
