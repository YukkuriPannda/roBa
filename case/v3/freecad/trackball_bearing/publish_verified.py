"""Publish only verified deliverables from a staged trackball-bearing run."""
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = Path(os.environ["ROBA_BEARING_OUTPUT"]).resolve()
PUBLISH_NAMES = (
    "trackball_bearing.FCStd",
    "trackball_bearing.step",
    "trackball_bearing.stl",
    "fit_coupon.step",
    "fit_coupon.stl",
    "inner_ring_spacer.stl",
    "assembly_preview.png",
    "body_clearance_section.png",
    "support_sections.png",
    "six_view.png",
    "six_view.pdf",
    "verification.json",
    "mesh_export_evidence.json",
    "repair.json",
    "repaired_source.bms",
    "source.brep",
    "source.sha256",
    "build.json",
)
DELIVERABLE_NAMES = (
    "trackball_bearing.FCStd",
    "trackball_bearing.step",
    "trackball_bearing.stl",
    "fit_coupon.step",
    "fit_coupon.stl",
    "inner_ring_spacer.stl",
)
EVIDENCE_NAMES = {"build.json", "verification.json", "mesh_export_evidence.json"}
LEGACY_DEBUG_NAMES = (
    "export_retry.log",
    "export_retry2.log",
    "probe_raw.stl",
    "render_final.log",
    "stuck_probe.log",
    "verify_final.log",
    "recompute_test.FCStd",
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


verification = json.loads((STAGE / "verification.json").read_text(encoding="utf-8"))
mesh = json.loads((STAGE / "mesh_export_evidence.json").read_text(encoding="utf-8"))
if verification.get("status") != "CAD_CHECKS_PASS_PHYSICAL_UNVERIFIED":
    raise RuntimeError("CAD verification did not pass; generated artifacts remain unpublished")
if mesh.get("status") != "PASS" or mesh["final_stl_round_trip"].get("self_intersections") != 0:
    raise RuntimeError("final STL mesh evidence did not pass")
missing = [name for name in PUBLISH_NAMES if not (STAGE / name).is_file()]
if missing:
    raise RuntimeError("verified publication is missing required files: " + ", ".join(missing))

record = json.loads((STAGE / "build.json").read_text(encoding="utf-8"))
record.update(
    status="CAD_CHECKS_PASS_PHYSICAL_UNVERIFIED",
    generated_at=datetime.now().astimezone().isoformat(),
    source_repair_sha256=digest(STAGE / "repair.json"),
    mesh_export_evidence_sha256=digest(STAGE / "mesh_export_evidence.json"),
    verification_evidence_sha256=digest(STAGE / "verification.json"),
)
code_names = (
    "bearing_case.py",
    "repair_source.py",
    "export_mesh.py",
    "export_case_mesh.py",
    "verify_case.py",
    "mesh_checks.py",
    "render_case.py",
    "render_six_view.py",
    "build_verify.py",
    "publish_verified.py",
)
record["code_hashes_sha256"] = {name: digest(HERE / name) for name in code_names}
input_names = ("sources.json", "alignment.json", "site_feasibility.json", "repair.json")
record["input_evidence_hashes_sha256"] = {
    name: digest(HERE / "inspect" / "logs" / name) for name in input_names
}
record["software"] = {
    "freecad": record["freecad"],
    "python": sys.version,
    "numpy": __import__("numpy").__version__,
    "scipy": __import__("scipy").__version__,
}
record["outputs_sha256"] = {
    name: digest(STAGE / name) for name in PUBLISH_NAMES if name not in EVIDENCE_NAMES
}
record["outputs"] = {
    name: record["outputs_sha256"][name] for name in DELIVERABLE_NAMES
}
(STAGE / "build.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

generated = HERE / "generated"
generated.mkdir(exist_ok=True)
for name in LEGACY_DEBUG_NAMES:
    stale = generated / name
    if stale.is_file():
        stale.unlink()
for name in PUBLISH_NAMES:
    shutil.copy2(STAGE / name, generated / name)

status = {"status": "CAD_CHECKS_PASS_PHYSICAL_UNVERIFIED", "run_directory": str(STAGE)}
(HERE / "latest_run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
print(json.dumps(status), flush=True)
