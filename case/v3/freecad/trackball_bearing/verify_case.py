"""Fresh-process checks; success is numerical CAD evidence, never physical proof."""
import json, math, traceback, time
from pathlib import Path
import numpy as np
import FreeCAD as App
import Part, Mesh
import bearing_case as model
from mesh_checks import triangles,point_distance,contains

def ray_first_hit(origin,direction,tris):
 """Distance to the first triangle hit beyond 0.01 mm along a ray (Moller-Trumbore)."""
 e1=tris[:,1]-tris[:,0];e2=tris[:,2]-tris[:,0];h=np.cross(direction,e2)
 det=np.einsum('ij,ij->i',e1,h);valid=np.abs(det)>1e-12
 inv=1/np.where(valid,det,1);sv=origin-tris[:,0]
 bu=inv*np.einsum('ij,ij->i',sv,h);q=np.cross(sv,e1)
 bv=inv*(q@direction);bt=inv*np.einsum('ij,ij->i',e2,q)
 hits=bt[valid&(bu>=0)&(bv>=0)&(bu+bv<=1)&(bt>0.01)]
 return float(hits.min()) if len(hits) else float('inf')
H=Path(__file__).resolve().parent; O=model.OUT; R=H.parents[3]
report={'status':'FAIL','checks':{},'limitations':['physical bearing inner-ring face dimensions unavailable','PCB/wiring model unavailable','print, fit and strength untested','global wall thickness untested']}
def check(name,ok,evidence):
 report['checks'][name]={'pass':bool(ok),'evidence':evidence}
 print(name,bool(ok),evidence,flush=True)
def main():
 model.verify_source_hashes()
 doc=App.openDocument(str(O/'trackball_bearing.FCStd'));p=doc.getObject('Dimensions');s=doc.getObject('BearingCase').Shape
 v=model.validate_parameters(p);holders,cuts,bearings,screws,spacers=model.hardware(p)
 check('case_single_valid_solid',s.isValid() and len(s.Solids)==1,{'solids':len(s.Solids),'volume_mm3':s.Volume})
 ball=Part.makeSphere(v['BallDiameter']/2,model.CENTER)
 finalmesh=Mesh.Mesh(str(O/'trackball_bearing.stl'));tri=triangles(finalmesh)
 centre=np.array([model.CENTER.x,model.CENTER.y,model.CENTER.z]);gap=point_distance(centre,tri)-v['BallDiameter']/2
 check('ball_case_clearance',gap>=.3 and not contains(centre,tri),{'minimum_surface_gap_mm':gap,'centre_inside_material':contains(centre,tri),'method':'all-triangle plane/edge distance and ray parity'})
 original_centres=np.array([np.array(x['hole_bottom_centroid'])-np.array(x['u']) for x in json.loads((H/'inspect/logs/site_feasibility.json').read_text())['sites']])
 seat_distances=np.linalg.norm(original_centres-centre,axis=1)
 check('original_ball_seating_reference',np.max(np.abs(seat_distances-18))<.001,{'ceramic_centre_distances_mm':seat_distances.tolist(),'assumption':'2mm ceramic spheres against measured flat recess bottoms; not physical seating proof'})
 for i,b in enumerate(bearings):
  print('checking bearing',i,flush=True)
  overlap=b.common(s).Volume; contact=b.distToShape(ball)[0]
  check(f'bearing_{i}_contact_and_rotation',overlap<1e-5 and contact<1e-5,{'case_overlap_mm3':overlap,'ball_contact_gap_mm':contact})
  c,ax,u=model.frames(p)[i];half=v['BearingWidth']/2
  outer_sweep=model.cylinder(v['BearingOuterDiameter']/2+.1,-half+.05,half-.05,c,ax).cut(model.cylinder(v['InnerRingContactDiameter']/2+.1,-half,half,c,ax))
  check(f'bearing_{i}_outer_ring_sweep',outer_sweep.common(s).Volume<1e-5,outer_sweep.common(s).Volume)
  # Tool cylinder is measured from screw head away from the part. The 4mm
  # envelope is a minimum driver size, not every screwdriver.
  tool=model.cylinder(2.,-v['ToolAccessDepth'], -half-v['SpacerThickness']-v['ScrewHeadHeight']-.05,c,ax)
  check(f'bearing_{i}_driver_access',tool.common(s).Volume<1e-5,tool.common(s).Volume)
  screw_ball_gap=screws[i].distToShape(ball)[0]
  check(f'screw_{i}_vs_ball',screws[i].common(ball).Volume<1e-7 and screw_ball_gap>=.1,{'overlap_mm3':screws[i].common(ball).Volume,'gap_mm':screw_ball_gap})
 a=json.loads((H/'inspect/logs/alignment.json').read_text());m=App.Matrix();m.rotateZ(math.radians(a['rotation_z_deg']));m.move(App.Vector(*a['translation_xy'],a['translation_z_assuming_flange_contact']))
 check('assembly_alignment',a['max_residual_mm']<.1,a)
 global_c=m.multVec(model.CENTER);sensor=a['bottom_sensor_hole'][0]
 radial_sensor_offset=math.hypot(global_c.x-sensor[0],global_c.y-sensor[1])
 check('sensor_hole_relationship',radial_sensor_offset<.2,{'ball_center_global':[global_c.x,global_c.y,global_c.z],'sensor_hole_axis_global':sensor[:2],'radial_offset_mm':radial_sensor_offset,'ball_surface_z_at_sensor_axis':global_c.z-math.sqrt(17**2-radial_sensor_offset**2),'optical_axis_model_available':False})
 for part in ('top_R','bottom_R'):
  ref=Part.read(str(R/f'case/v3/{part}.stp'));ref.transformShape(m.inverse(),True)
  # Whole faceted BRep intersections can be prohibitively slow. Check the
  # complete case with tessellated surface Boolean, retaining the known
  # bottom flange contact separately; simple hardware uses exact CAD.
  refmesh=Mesh.Mesh(ref.tessellate(.1));intersection=finalmesh.intersect(refmesh)
  contact_only=(part=='bottom_R' and intersection.CountPoints>0 and all(abs(q.z-2.)<.001 for q in intersection.Points))
  empty=intersection.CountFacets==0
  check(f'case_vs_{part}',empty or contact_only,{'method':'mesh surface intersection; reference deflection 0.1mm','intersection_facets':intersection.CountFacets,'flange_contact_only':contact_only,'intersection_bbox':str(intersection.BoundBox),'reference_self_intersection_warning':refmesh.hasSelfIntersections()})
  # Keep additions away from the reference using exact BRep tests. This also
  # avoids relying on the bottom mesh's flagged coplanar flange triangles.
  for i,holder in enumerate(holders):
   overlap=holder.common(ref).Volume;gap=holder.distToShape(ref)[0]
   check(f'holder_{i}_vs_{part}',overlap<1e-7 and gap>=.25,{'overlap_mm3':overlap,'gap_mm':gap})
  for name,shape in [('ball34',ball),('bearings',Part.makeCompound(bearings)),('screws',Part.makeCompound(screws))]:
   print('checking assembly',name,part,flush=True)
   overlap=shape.common(ref).Volume;gap=shape.distToShape(ref)[0]
   check(f'{name}_vs_{part}',overlap<1e-7,{'overlap_mm3':overlap,'gap_mm':gap,'contact_allowed_for_original_mount':name=='case'})
  for i,(c,ax,u) in enumerate(model.frames(p)):
   underhead=-v['BearingWidth']/2-v['SpacerThickness']
   screw_path=model.cylinder(v['ScrewHeadDiameter']/2,-v['ToolAccessDepth'],underhead,c,ax)
   screw_body_overlap=screw_path.common(ref).Volume
   screw_detached_overlap=screw_path.common(s).Volume
   check(f'screw_{i}_installation_path_{part}',screw_detached_overlap<1e-5,{'detached_case_overlap_mm3':screw_detached_overlap,'assembled_body_overlap_mm3':screw_body_overlap,'in_place_replacement_available':screw_body_overlap<1e-5,'required_procedure':'remove trackball case from body before assembly/replacement' if screw_body_overlap>=1e-5 else 'checked screw-head insertion envelope clears body','screw_head_diameter_mm':v['ScrewHeadDiameter']})
   driver_path=model.cylinder(2.,-v['ToolAccessDepth'],-v['BearingWidth']/2-v['SpacerThickness']-v['ScrewHeadHeight']-.05,c,ax)
   driver_body_overlap=driver_path.common(ref).Volume
   driver_detached_overlap=driver_path.common(s).Volume
   check(f'driver_{i}_access_path_{part}',driver_detached_overlap<1e-5,{'detached_case_overlap_mm3':driver_detached_overlap,'assembled_body_overlap_mm3':driver_body_overlap,'in_place_access_available':driver_body_overlap<1e-5,'required_procedure':'remove trackball case from body before operating tool' if driver_body_overlap>=1e-5 else 'checked 4mm driver envelope clears body','driver_diameter_mm':4.0,'case_access_tunnel_diameter_mm':v['ScrewHeadDiameter']+.60})
 source=doc.getObject('SourceSolid').Shape
 # The construction is explicitly Source - declared cylinders + holders.
 # Record this contract; protected mounting/sensor geometry is checked by
 # exact localized solids below, rather than a huge coincident-face Boolean.
 check('source_retention_construction',doc.getObject('BearingCase').Source.Name=='SourceSolid',{'operations':'source cut by declared pocket/head/pilot cylinders, then holder union','cut_count':len(cuts),'holder_count':len(holders),'repair_record':'inspect/logs/repair.json','full_difference_volume_not_computed':True})
 dirs=np.array([[u.x,u.y,u.z] for c,ax,u in model.frames(p)])
 weights=np.linalg.solve(dirs.T,[0,0,-1])
 check('vertical_load_distribution',min(weights)>0 and max(weights)<10 and float(np.linalg.cond(dirs.T))<30,{'relative_reactions_per_unit_downward_load':weights.tolist(),'condition_number':float(np.linalg.cond(dirs.T)),'criteria':'all positive; peak coefficient <10; condition <30','not_strength_evidence':True})
 face=v['BearingWidth']/2+v['SpacerThickness']
 analytic=model.ball_side_web(p)
 # Radial rays from the pilot wall toward the ball, at the boss face (+0.01 mm),
 # over the ball-facing arc. The minimum is the mesh-measured ball-side web.
 measured=[]
 for c,ax,u in model.frames(p):
  e=-u;f=ax.cross(e);rp=v['PilotDiameter']/2
  for phi in np.radians(np.linspace(-60,60,13)):
   q=c+ax*(face+.01)+(e*math.cos(phi)+f*math.sin(phi))*rp
   measured.append(ray_first_hit(np.array([q.x,q.y,q.z]),np.array([e.x,e.y,e.z]),tri))
 measured_min=min(measured)
 check('ball_side_web_measured_mesh',abs(measured_min-analytic)<.05,{'analytic_mm':analytic,'mesh_min_mm':measured_min,'rays':len(measured),'method':'radial rays from pilot wall toward ball centre, first hit on final STL'})
 target=v['MinBallSideWeb'];floor=v['BallSideWebFloor']
 alt_r=v['BallDiameter']/2;alt_D=alt_r+v['BearingOuterDiameter']/2
 alt_web=(alt_D-2.05/2)-math.sqrt((alt_r+.2)**2-face**2)
 report['ball_side_web']={'analytic_mm':analytic,'mesh_min_mm':measured_min,'target_mm':target,'floor_mm':floor,
  'status':'MEETS_TARGET' if analytic>=target else ('MEETS_FLOOR_ONLY' if analytic>=floor else 'BELOW_FLOOR_HOLD'),
  'boss_face_offset_mm':face,
  'required_boss_face_offset_for_target_mm':model.boss_face_offset_for_web(p,target),
  'required_boss_face_offset_for_floor_mm':model.boss_face_offset_for_web(p,floor),
  'alternative_web_mm_ball_clearance_0.2_pilot_2.05':alt_web,
  'reason':'web = (ball radius + bearing OD/2 - pilot radius) - sqrt((ball radius + ball clearance)^2 - face offset^2); bearing centre distance, pilot, clearance and face offset are fixed by the frozen bearing stack (width 2 mm + 0.4 mm metal spacer)',
  'strength_status':'HOLD_THIN_LOCAL_SECTION_REQUIRES_COUPON_AND_LOAD_CONDITIONS','global_minimum_not_measured':True}
 report['limitations'].append(f"ball-side web {analytic:.3f} mm (mesh {measured_min:.3f} mm) is below the {target} mm target and the {floor} mm floor; face offset change or hardware-stack change needed; strength approval withheld")
 # Protected original screw flange and sensor opening zone at low Z.
 protected=Part.makeBox(35,30,4,App.Vector(-10,-15,1.9))
 original_zone=source.common(protected);current_zone=s.common(protected)
 loss=original_zone.cut(current_zone).Volume
 check('mounting_and_lower_sensor_zone_preserved',loss<.01,loss)
 for name in ('trackball_bearing','fit_coupon','inner_ring_spacer'):
  mesh=Mesh.Mesh(str(O/f'{name}.stl'))
  mt=triangles(mesh);areas=np.linalg.norm(np.cross(mt[:,1]-mt[:,0],mt[:,2]-mt[:,0]),axis=1)/2
  evidence={'components':mesh.countComponents(),'degenerate_facets':int(np.sum(areas<1e-12)),'minimum_triangle_area_mm2':float(areas.min()),'closed':mesh.isSolid(),'non_manifold':mesh.hasNonManifolds(),'self_intersections':mesh.hasSelfIntersections(),'facets':mesh.CountFacets,'volume_mm3':mesh.Volume}
  check(f'{name}_mesh',evidence['components']==1 and evidence['degenerate_facets']==0 and evidence['closed'] and not evidence['non_manifold'] and not evidence['self_intersections'],evidence)
 step=Part.read(str(O/'trackball_bearing.step'))
 check('step_round_trip',step.isValid() and len(step.Solids)==1 and abs(step.Volume-s.Volume)<.01,{'valid':step.isValid(),'solids':len(step.Solids),'volume_delta':step.Volume-s.Volume})
 before=s.Volume;old=model.value(p,'BearingWidth');hardware_before=doc.getObject('Bearings').Shape.Volume;p.BearingWidth=old+.05
 doc.recompute();after=doc.getObject('BearingCase').Shape.Volume
 check('named_dimension_recompute',abs(after-before)>.001 and doc.getObject('BearingCase').Shape.isValid(),{'volume_before':before,'volume_after':after,'changed_parameter':'BearingWidth','value_before':old,'value_after':old+.05})
 check('dependent_hardware_recompute',doc.getObject('Bearings').Shape.Volume>hardware_before+.01,{'volume_before':hardware_before,'volume_after':doc.getObject('Bearings').Shape.Volume})
 p.BearingWidth=old;doc.recompute()
 restored=doc.getObject('BearingCase').Shape.Volume
 check('dimension_restore',abs(restored-before)<.01,{'volume_delta':restored-before})
 tear_on=doc.getObject('BearingCase').Shape.Volume
 p.TeardropHoles=False;doc.recompute();tear_off=doc.getObject('BearingCase').Shape.Volume
 p.TeardropHoles=True;doc.recompute();tear_restored=doc.getObject('BearingCase').Shape.Volume
 check('teardrop_toggle_recompute',tear_off-tear_on>.01 and abs(tear_restored-tear_on)<.01,{'volume_teardrop_on':tear_on,'volume_teardrop_off':tear_off,'expected':'teardrop removes more material than round holes'})
 eb=json.loads(doc.getObject('BearingCase').EdgeBreakResult)
 check('edge_break_recorded',set(eb['groups'])=={'pilot_end','entrance','root'} and doc.getObject('BearingCase').Shape.isValid(),eb)
 if eb['applied_groups']<eb['total_groups']:
  report['limitations'].append(f"edge break applied to {eb['applied_groups']} of {eb['total_groups']} groups; unapplied groups recorded in verification.json")
 # Do not overwrite the reviewed FCStd during the mutation test.
 doc.saveAs(str(O/'recompute_test.FCStd'));App.closeDocument(doc.Name)
 doc=App.openDocument(str(O/'recompute_test.FCStd'))
 check('saved_document_reopen',doc.getObject('BearingCase').Shape.isValid() and abs(doc.getObject('BearingCase').Shape.Volume-before)<.01,{'volume':doc.getObject('BearingCase').Shape.Volume})
 # Guard a formerly permitted screw/bearing mismatch.
 p=doc.getObject('Dimensions');p.ScrewDiameter=2.6
 rejected=False
 try:model.validate_parameters(p)
 except ValueError:rejected=True
 check('oversize_screw_rejected',rejected,{'test_screw_diameter':2.6,'bearing_bore':2.5})
 report['status']='CAD_CHECKS_PASS_PHYSICAL_UNVERIFIED' if all(x['pass'] for x in report['checks'].values()) else 'FAIL_NOT_PRINT_READY'
 return report['status'].startswith('CAD_CHECKS_PASS')
if __name__=='__main__':
 try:ok=main()
 except Exception:
  report['exception']=traceback.format_exc();ok=False;print(report['exception'],flush=True)
 (O/'verification.json').write_text(json.dumps(report,indent=2))
 raise SystemExit(0 if ok else 1)



