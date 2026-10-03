"""Apply bounded, measured mesh cleanup to the current FreeCAD case BRep."""
from pathlib import Path
import json
import FreeCAD as App
import bearing_case as model
from export_mesh import export_verified_stl

out = model.OUT
doc = App.openDocument(str(out / "trackball_bearing.FCStd"))
shape = doc.getObject("BearingCase").Shape
result = export_verified_stl(shape, out / "trackball_bearing.stl", max_surface_deviation=0.08)
(out / "mesh_export_evidence.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({"status": result["status"], "self_intersections": result["final_stl_round_trip"]["self_intersections"], "repairs": len(result["repair_policy"]["operations"]), "deviation_mm": result["geometry_deviation"]["raw_to_final_bidirectional_sampled_distance"]["max_distance_upper_bound_mm"]}, indent=2), flush=True)
App.closeDocument(doc.Name)
