"""Collapse short edges next to known self-intersections, preserving manifoldness.

Never changes upstream STL. Fails if repair needs an edge over 0.30mm or leaves
an open/non-manifold mesh. Every local edit is recorded for review.
"""
from pathlib import Path
import json
import numpy as np
from scipy.spatial import cKDTree
from mesh_checks import sampled_surface_distance
import FreeCAD,Mesh
H=Path(__file__).resolve().parent;R=H.parents[3];O=H/'inspect/logs'
source=Mesh.Mesh(str(R/'case/trackballcase.stl'));m=Mesh.Mesh(source);edits=[]
for step in range(30):
 pairs=m.getSelfIntersections()
 if not pairs:break
 points,faces=m.Topology;P=np.array([list(p) for p in points]);bad={int(x) for row in pairs for x in row[:2]}
 candidates=[]
 for i in bad:
  face=faces[i]
  for j in range(3):
   a,b=face[j],face[(j+1)%3];length=float(np.linalg.norm(P[a]-P[b]))
   adjacent=[k for k,f in enumerate(faces) if a in f and b in f]
   if len(adjacent)==2:candidates.append((length,adjacent,P[a].tolist(),P[b].tolist()))
 candidates.sort(key=lambda x:x[0]);accepted=False
 for length,adjacent,a,b in candidates:
  if length>.30:break
  test=Mesh.Mesh(m)
  try:test.collapseEdge(*adjacent)
  except Exception:continue
  # Validate native BMS save/reload before accepting the source repair.
  trial=O/'repair_trial.bms';test.write(str(trial));test=Mesh.Mesh(str(trial))
  if not test.isSolid() or test.hasNonManifolds():continue
  if len(test.getSelfIntersections())>=len(pairs):continue
  edits.append(dict(edge_length_mm=length,endpoints=[a,b],intersections_before=len(pairs),intersections_after=len(test.getSelfIntersections())))
  m=test;accepted=True;print(edits[-1],flush=True);break
 if not accepted:raise RuntimeError('No bounded, manifold-preserving local edge repair removes an intersection')
if m.hasSelfIntersections() or not m.isSolid() or m.hasNonManifolds():raise RuntimeError('source repair failed')
P=np.array([[p.x,p.y,p.z] for p in source.Points]);Q=np.array([[p.x,p.y,p.z] for p in m.Points])
deviation=max(cKDTree(Q).query(P)[0].max(),cKDTree(P).query(Q)[0].max())
record={'method':'short-edge collapse only on intersecting facet neighborhoods','edits':edits,'original_facets':source.CountFacets,'repaired_facets':m.CountFacets,'volume_delta_mm3':m.Volume-source.Volume,'vertex_sample_set_distance_mm':float(deviation),'closed':m.isSolid(),'self_intersections':m.hasSelfIntersections(),'non_manifold':m.hasNonManifolds()}
print(record,flush=True)
record['sampled_surface_distance_mm']=sampled_surface_distance(source,m)
print('surface_distance_mm',record['sampled_surface_distance_mm'],flush=True)
if record['sampled_surface_distance_mm']>.06 or abs(record['volume_delta_mm3'])>.05:raise RuntimeError('repair deviation exceeds declared limits')
m.write(str(O/'repaired_source.bms'))
reloaded=Mesh.Mesh(str(O/'repaired_source.bms'))
if not reloaded.isSolid() or reloaded.hasSelfIntersections() or reloaded.hasNonManifolds():raise RuntimeError('repaired BMS round-trip invalid')
(O/'repair.json').write_text(json.dumps(record,indent=2));print(record,flush=True)
(O/'repair_trial.bms').unlink(missing_ok=True)





