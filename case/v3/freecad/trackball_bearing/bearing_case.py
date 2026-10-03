"""FreeCAD FeaturePython bearing conversion of the original triangulated case.

All lengths are mm. The original mesh is retained as a separate reference;
only the added holder and pocket operations are parametric.
"""
from pathlib import Path
import hashlib, json, math, time, os
import FreeCAD as App
import Part, Mesh

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUT = Path(os.environ.get('ROBA_BEARING_OUTPUT',str(HERE/'generated')))
# Reconstructed 34mm ball centre from three 2mm ceramic spheres seated
# against measured flat recess bottoms. Physical seating is still unverified.
CENTER = App.Vector(-0.28458016, 0.09661005, 19.89032338)
DEFAULTS = {
 'BallDiameter':34., 'BearingOuterDiameter':4., 'BearingInnerDiameter':2.5,
 'BearingWidth':2., 'ScrewLength':5., 'ScrewDiameter':2.5,
 # NBK SNSS-M2.5-5-SD manufacturer dimensional envelope.
 'ScrewHeadDiameter':3.8, 'ScrewHeadHeight':2.5,
 'PilotDiameter':2.15, 'PocketClearance':0.30,
 'InnerRingContactDiameter':2.90, 'SpacerThickness':0.40,
 'BossRadius':3.20, 'BossLength':2.50, 'BallClearance':0.40, 'ToolAccessDepth':12.,
 # COROPIT photo-derived topology: two upper flank sites and one lower site.
 # Use the original v3 ceramic-seat normals as the nearest preserved case
 # locations; COROPIT's exact coordinates and shaft angles are unpublished.
 'Support1Polar':98.30, 'Support1Azimuth':123.58, 'Support1AxisTilt':0.,
 # Raise the lower support from the original ceramic-seat angle (28.41 deg)
 # to clear the v3 body while preserving the lower COROPIT-style support role.
 'Support2Polar':60.00, 'Support2Azimuth':258.57, 'Support2AxisTilt':0.,
 'Support3Polar':116.77, 'Support3Azimuth':358.09, 'Support3AxisTilt':0.,
}
ANGLE_NAMES = {name for name in DEFAULTS if name.endswith(('Polar', 'Azimuth', 'AxisTilt'))}

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def verify_source_hashes():
 evidence=json.loads((HERE/'inspect/logs/sources.json').read_text())
 for entry in list(evidence['meshes'].values())+list(evidence['steps'].values()):
  if sha(ROOT/entry['file'])!=entry['sha256']:raise ValueError('source changed; remeasure geometry: '+entry['file'])
def value(obj,name):
 v=getattr(obj,name); return float(v.Value if hasattr(v,'Value') else v)
def unit(v):
 v=App.Vector(v); v.normalize(); return v
def radial(polar,azimuth):
 p,a=map(math.radians,(polar,azimuth))
 return App.Vector(math.sin(p)*math.cos(a),math.sin(p)*math.sin(a),-math.cos(p))
def cylinder(radius,t0,t1,c,axis): return Part.makeCylinder(radius,t1-t0,c+axis*t0,axis)
def directions(p):
 return [
  radial(value(p,f'Support{i}Polar'),value(p,f'Support{i}Azimuth'))
  for i in range(1,4)
 ]
def frames(p):
 dirs=directions(p); radius=value(p,'BallDiameter')/2+value(p,'BearingOuterDiameter')/2
 result=[]
 for i,u in enumerate(dirs):
  axis=unit(App.Vector(0,0,1).cross(u))
  tilt=math.radians(value(p,f'Support{i+1}AxisTilt'))
  axis=unit(axis*math.cos(tilt)+u.cross(axis)*math.sin(tilt))
  result.append((CENTER+u*radius,axis,u))
 return result

def validate_parameters(p):
 vals={k:value(p,k) for k in DEFAULTS}
 if not all(math.isfinite(v) for v in vals.values()):raise ValueError('dimensions must be finite values')
 if not all(v>0 for k,v in vals.items() if k not in ANGLE_NAMES):raise ValueError('length dimensions must be positive')
 if vals['BearingInnerDiameter']>=vals['BearingOuterDiameter']:raise ValueError('bearing ID must be below OD')
 if not vals['BearingInnerDiameter']<vals['InnerRingContactDiameter']<vals['BearingOuterDiameter']:raise ValueError('inner-ring contact diameter out of range')
 if vals['PilotDiameter']>=vals['ScrewDiameter']:raise ValueError('pilot must be smaller than screw')
 if vals['ScrewDiameter']>vals['BearingInnerDiameter']:raise ValueError('screw cannot exceed bearing bore')
 if vals['ScrewHeadDiameter']<=vals['InnerRingContactDiameter']:raise ValueError('head must retain inner-ring spacer')
 if vals['ScrewLength']<vals['BearingWidth']+2*vals['SpacerThickness']+1.5:raise ValueError('insufficient screw engagement')
 if vals['ToolAccessDepth']<8:raise ValueError('insufficient fastener access depth')
 for i in range(1,4):
  if not 0<vals[f'Support{i}Polar']<180:raise ValueError(f'Support{i}Polar must be between 0 and 180 degrees')
  if not -20<=vals[f'Support{i}AxisTilt']<=20:raise ValueError(f'Support{i}AxisTilt outside examined design range')
 return vals

def hardware(p):
 v=validate_parameters(p); half=v['BearingWidth']/2; spacer=v['SpacerThickness']; r=v['BearingOuterDiameter']/2
 bearings=[];screws=[];spacers=[];holders=[];cuts=[]
 ballvoid=Part.makeSphere(v['BallDiameter']/2+v['BallClearance'],CENTER)
 # Sensor enclosure inner face measured at X=18.69 mm. Additions stop
 # 0.30 mm before it; this does not prove PCB or wiring clearance.
 sensorvoid=Part.makeBox(20,23.6,26.5,App.Vector(18.39,-11.8,5.5))
 for i,(c,ax,u) in enumerate(frames(p)):
  bear=cylinder(r,-half,half,c,ax).cut(cylinder(v['BearingInnerDiameter']/2,-half-.01,half+.01,c,ax))
  bearings.append(bear)
  body=cylinder(v['BossRadius'],half+spacer,half+spacer+v['BossLength'],c,ax).cut(ballvoid)
  # Both sides use precision metal spacers. A 0.15mm radial printed collar
  # would be thinner than the nozzle line width and is intentionally omitted.
  holder=body.cut(sensorvoid)
  pilot=cylinder(v['PilotDiameter']/2,half-.01,half+spacer+v['BossLength']+.01,c,ax)
  holder=holder.cut(pilot)
  holder=holder.cut(cylinder(1.325,half-.01,half+spacer+.01,c,ax))
  holders.append(holder)
  pocket=cylinder(r+v['PocketClearance'],-half-v['PocketClearance'],half+spacer-.002,c,ax)
  # Screw is inserted along the negative axis. Open the shell for its head
  # and driver as well as the bearing; the assembly sweep is checked separately.
  headspace=cylinder(v['ScrewHeadDiameter']/2+.30,-v['ToolAccessDepth'],-half-.01,c,ax)
  cuts.extend([pocket,headspace,pilot,cylinder(1.325,half-.01,half+spacer+.01,c,ax)])
  underhead=-half-spacer
  shank=cylinder(v['ScrewDiameter']/2,underhead,underhead+v['ScrewLength'],c,ax)
  head=cylinder(v['ScrewHeadDiameter']/2,underhead-v['ScrewHeadHeight'],underhead,c,ax)
  screws.append(shank.fuse(head))
  spacers.append(cylinder(v['InnerRingContactDiameter']/2,underhead,-half,c,ax).cut(cylinder(1.30,underhead-.01,-half+.01,c,ax)))
  spacers.append(cylinder(v['InnerRingContactDiameter']/2,half,half+spacer,c,ax).cut(cylinder(1.30,half-.01,half+spacer+.01,c,ax)))
 return holders,cuts,bearings,screws,spacers

class CaseProxy:
 def __init__(self,obj):obj.Proxy=self
 def execute(self,obj):
  holders,cuts,_,_,_=hardware(obj.Dimensions)
  shape=obj.Source.Shape.copy()
  for i,cut in enumerate(cuts):
   print('cut',i,flush=True);shape=shape.cut(cut)
  for i,holder in enumerate(holders):
   print('holder',i,flush=True);shape=shape.fuse(holder)
  shape=shape.removeSplitter()
  if not shape.isValid() or len(shape.Solids)!=1:raise ValueError('case must be a valid single solid')
  obj.Shape=shape
 def dumps(self):return None
 def loads(self,state):pass

def coupon_shape(p):
 holder=hardware(p)[0][0];c,ax,u=frames(p)[0]
 # Map the broad boss end to a planar print base; shoulder faces upwards.
 z=-ax;x=u;y=z.cross(x);origin=c+ax*(value(p,'BearingWidth')/2+value(p,'SpacerThickness')+value(p,'BossLength'))
 m=App.Matrix()
 for row,vec in enumerate((x,y,z),1):
  setattr(m,f'A{row}1',vec.x);setattr(m,f'A{row}2',vec.y);setattr(m,f'A{row}3',vec.z);setattr(m,f'A{row}4',-vec.dot(origin))
 holder.transformShape(m,True)
 base=Part.makeBox(8,8,1.6,App.Vector(-4,-4,-1.6))
 return holder.fuse(base).cut(Part.makeCylinder(value(p,'PilotDiameter')/2,6,App.Vector(0,0,-1.61)))

class HardwareProxy:
 def __init__(self,obj,kind):obj.Proxy=self;self.kind=kind
 def execute(self,obj):
  if self.kind=='Ball':obj.Shape=Part.makeSphere(value(obj.Dimensions,'BallDiameter')/2,CENTER)
  elif self.kind=='Coupon':obj.Shape=coupon_shape(obj.Dimensions)
  else:obj.Shape=Part.makeCompound(hardware(obj.Dimensions)[{'Bearings':2,'Screws':3,'LooseSpacers':4}[self.kind]])
 def dumps(self):return self.kind
 def loads(self,state):self.kind=state

def build():
 verify_source_hashes()
 OUT.mkdir(parents=True,exist_ok=True)
 doc=App.newDocument('TrackballBearing')
 p=doc.addObject('App::FeaturePython','Dimensions');p.Label='Bearing case dimensions (mm / degrees)'
 for name,val in DEFAULTS.items():
  typ='App::PropertyAngle' if name in ANGLE_NAMES else 'App::PropertyLength'
  p.addProperty(typ,name,'Bearing design');setattr(p,name,val)
 mesh=Mesh.Mesh(str(ROOT/'case/trackballcase.stl'))
 ref=doc.addObject('Mesh::Feature','OriginalMesh');ref.Mesh=mesh;ref.Label='Original STL reference (unchanged)'
 cached=OUT/'source.brep'
 repaired=HERE/'inspect/logs/repaired_source.bms'
 if not repaired.exists():raise ValueError('run repair_source.py first')
 repair_mesh=Mesh.Mesh(str(repaired))
 if not repair_mesh.isSolid() or repair_mesh.hasSelfIntersections() or repair_mesh.hasNonManifolds():raise ValueError('repaired source mesh invalid')
 if cached.exists() and (OUT/'source.sha256').exists() and (OUT/'source.sha256').read_text()==sha(repaired):
  base=Part.read(str(cached))
 else:
  raw=Part.Shape();raw.makeShapeFromMesh(repair_mesh.Topology,.00001)
  base=Part.makeSolid(raw.Shells[0]);base.exportBrep(str(cached));(OUT/'source.sha256').write_text(sha(repaired))
 if not base.isValid() or len(base.Solids)!=1:raise ValueError('source conversion invalid')
 source=doc.addObject('Part::Feature','SourceSolid');source.Shape=base;source.Label='Faceted source snapshot; no recovered CAD history'
 result=doc.addObject('Part::FeaturePython','BearingCase');result.addProperty('App::PropertyLink','Source');result.Source=source
 result.addProperty('App::PropertyLink','Dimensions');result.Dimensions=p;CaseProxy(result)
 doc.recompute()
 if result.Shape.isNull():raise ValueError('recompute failed')
 holders,cuts,bearings,screws,spacers=hardware(p)
 for name,shapes in [('Bearings',bearings),('Screws',screws),('LooseSpacers',spacers)]:
  obj=doc.addObject('Part::FeaturePython',name);obj.addProperty('App::PropertyLink','Dimensions');obj.Dimensions=p;HardwareProxy(obj,name)
 ball=doc.addObject('Part::FeaturePython','Ball34');ball.addProperty('App::PropertyLink','Dimensions');ball.Dimensions=p;HardwareProxy(ball,'Ball')
 # Coupon duplicates one holder and its inner-ring contact shoulder, plus
 # loose spacer. It is a fast fit check, not a structural proof.
 coupon=doc.addObject('Part::FeaturePython','FitCoupon');coupon.addProperty('App::PropertyLink','Dimensions');coupon.Dimensions=p;HardwareProxy(coupon,'Coupon')
 doc.recompute();doc.saveAs(str(OUT/'trackball_bearing.FCStd'))
 result.Shape.exportStep(str(OUT/'trackball_bearing.step'))
 Mesh.Mesh(result.Shape.tessellate(.08)).write(str(OUT/'trackball_bearing.stl'))
 coupon.Shape.exportStep(str(OUT/'fit_coupon.step'))
 Mesh.Mesh(coupon.Shape.tessellate(.05)).write(str(OUT/'fit_coupon.stl'))
 Mesh.Mesh(spacers[0].tessellate(.03)).write(str(OUT/'inner_ring_spacer.stl'))
 manifest={'status':'CANDIDATE_REQUIRES_VALIDATION','source_sha256':sha(ROOT/'case/trackballcase.stl'),'code_sha256':sha(__file__),'freecad':App.Version(),'units':'mm','parameters':validate_parameters(p),'ball_center_local':[CENTER.x,CENTER.y,CENTER.z],'case_volume':result.Shape.Volume,'valid':result.Shape.isValid(),'solids':len(result.Shape.Solids),'outputs':{x.name:sha(x) for x in OUT.iterdir() if x.suffix.lower() in ('.fcstd','.step','.stl')},'unverified':['inner race face diameter and screw fit','assembly/tool access','PCB and wiring','strength and printability','source self-intersections','complete wall thickness']}
 (OUT/'build.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest),flush=True)
 return doc

if __name__=='__main__':
 import bearing_case
 bearing_case.build()





