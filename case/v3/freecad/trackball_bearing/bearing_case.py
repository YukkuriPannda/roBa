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
 'BallDiameter':34., 'BearingOuterDiameter':4., 'BearingInnerDiameter':2.,
 # MR42 ball bearing: ID 2.0, OD 4.0, width 1.5 mm. Strength is knowingly
 # secondary for this variant; the ball-side web is reported, not enforced.
 'BearingWidth':1.5, 'ScrewLength':6., 'ScrewDiameter':2.,
 # M2 Mini 4WD screw. Pan head 3.8 x 1.3 mm is an ASSUMPTION (not a datasheet
 # value); confirm against the purchased screw before printing.
 'ScrewHeadDiameter':3.8, 'ScrewHeadHeight':1.3,
 # Self-tapping pilot for M2 into PLA; the coupon pilots bracket this value.
 'PilotDiameter':1.65,
 # Bearing-seat radial clearance. 0.30 -> 0.20 (2026-10-24 print feedback) to
 # reduce ball play; matches CouponClearance1.
 'PocketClearance':0.20,
 # Inner-ring spacer (metal, Mini 4WD). OD must stay below the outer-ring bore so
 # it touches only the inner ring. SpacerBore is the screw clearance through it.
 # MR42 inner-ring OD is not published; 2.60 is an ASSUMPTION to check on the part.
 'InnerRingContactDiameter':2.60, 'SpacerThickness':0.50,
 'SpacerBoreDiameter':2.10, 'ShellReliefDiameter':2.15,
 # Minimum screw length inside the boss (tip to boss face, capped at boss end).
 'MinThreadEngagement':2.00,
 'BossRadius':3.00, 'BossLength':2.50,
 # BallClearance trims only the boss tips. 0.40 -> 0.81 (2026-10-24 print feedback)
 # halves the ball-side web (0.82 -> 0.41 mm) so the bearings protrude further.
 'BallClearance':0.81, 'ToolAccessDepth':12.,
 # Print-oriented options (FDM, 0.4 mm nozzle, 0.2 mm layers).
 # TeardropHoles: horizontal bearing-seat and head-tunnel holes get a 45 degree
 # roof so they print without support. The screw pilot stays round because its
 # roof would thin the ball-side web.
 'TeardropHoles':True,
 # EdgeBreak: 0.5 mm fillet at boss roots and hole entrances; chamfer fallback.
 'EdgeBreak':0.50,
 # Ball-side web between the pilot bore and the ball void, measured at the boss
 # face. MinBallSideWeb is the review target; BallSideWebFloor is the lowest
 # value accepted before the design must be revised.
 'MinBallSideWeb':1.60, 'BallSideWebFloor':0.40,
 # Multi-level fit coupon: three bearing-seat / pilot pairs, ordered left to
 # right at x = -pitch, 0, +pitch (see README).
 'CouponBaseThickness':2.40, 'CouponElephantChamfer':0.30, 'CouponPitch':12.,
 'CouponClearance1':0.20, 'CouponPilot1':1.55,
 'CouponClearance2':0.30, 'CouponPilot2':1.65,
 'CouponClearance3':0.40, 'CouponPilot3':1.75,
 # INTERIM layout (pending review). Polar is measured from the bottom pole
 # (z = -cos(polar), see radial()), so polar < 90 deg is below the ball equator
 # and polar > 90 deg is above it. The previous 91/60/100 set had two supports
 # at or above the equator. Three equal supports at polar p give load shares of
 # 1/(3 cos p) per unit downward load: 0.581 at 55 deg, 0.667 at 60 deg.
 # Polar 55 deg was rejected: the upper case part (top_R) occupies every azimuth
 # except a ~80 deg arc, so no 120 deg triad fits (90/210/330 overlapped top_R,
 # 9.5 mm3 at 90 deg). At 60 deg the clear arcs are about 322-30 and 128-266 deg
 # (2 deg scan of the bearing+boss against top_R). The screw head/shank at 137 deg
 # grazes top_R (0.0085 mm3) at polar 60, so polar is raised to 61 deg (load share
 # 0.688). 142/262/22 was rejected: its STL export was not one closed component.
 # The set stays off the +X sensor cutout (sensor void starts at X=18.39 mm, 0 deg).
 # 2026-10-24 print feedback: support 1 raised 61 -> 76 deg (clear of top_R after the boss-tip trim),
 # support 2 bearing axis rotated 30 deg (tilt -90 -> -60).
 'Support1Polar':76.00, 'Support1Azimuth':139.00, 'Support1AxisTilt':0.,
 'Support2Polar':61.00, 'Support2Azimuth':257.00, 'Support2AxisTilt':-60.,
 'Support3Polar':61.00, 'Support3Azimuth':19.00, 'Support3AxisTilt':0.,
 # Driver hole through the far wall on the screw-head side. Support 3's head
 # side crosses the sensor box and its outer wall 16.2-19.5 mm from the
 # bearing centre, so a straight driver could not reach the screw. The hole
 # continues the head tunnel from ToolAccessDepth to DriverHoleLength. The
 # 4.0 mm diameter matches the 4 mm driver envelope used by verify_case.py.
 'DriverHoleDiameter':4.00, 'DriverHoleLength':30.,
 'Support1DriverHole':False, 'Support2DriverHole':False, 'Support3DriverHole':True,
 # Fill the three recesses that held the original 2 mm ceramic balls (radius
 # about 0.68-0.88 mm, flat bottom about 19.05 mm from the ball centre). The
 # plug runs from CeramicRecessFillInnerRadius to CeramicRecessFillOuterRadius,
 # inside the 19.49 mm outer shell. It starts 0.17 mm below the faceted pad
 # surface (17.535 mm): a plug flush with the 17.4 mm ball void grazed the pad
 # and left STL self-intersections, so a shallow dimple is kept instead.
 # Recess axes come from inspect/logs/site_feasibility.json.
 'FillCeramicRecesses':True, 'CeramicRecessFillDiameter':2.20,
 'CeramicRecessFillInnerRadius':17.85, 'CeramicRecessFillOuterRadius':19.25,
 # Remove the raised pads around those recesses. Each pad rises from the
 # 17.99 mm cup surface to about 17.53 mm (radius from the fitted cup centre)
 # over a circle of about 4.8 mm diameter. Cut inside CeramicPadCutRadius,
 # 0.16 mm beyond the cup surface so no sliver of the faceted cup remains,
 # within CeramicPadCutDiameter around each recess axis. Features 4 mm and more
 # off the site-3 axis (sensor side bumps) stay outside the cut.
 'RemoveCeramicPads':True, 'CeramicPadCutDiameter':5.40, 'CeramicPadCutRadius':18.15,
}
ANGLE_NAMES = {name for name in DEFAULTS if name.endswith(('Polar', 'Azimuth', 'AxisTilt'))}
BOOL_NAMES = {'TeardropHoles','FillCeramicRecesses','RemoveCeramicPads','Support1DriverHole','Support2DriverHole','Support3DriverHole'}
COUPON_LEVELS = (1, 2, 3)

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def verify_source_hashes():
 evidence=json.loads((HERE/'inspect/logs/sources.json').read_text())
 for entry in list(evidence['meshes'].values())+list(evidence['steps'].values()):
  if sha(ROOT/entry['file'])!=entry['sha256']:raise ValueError('source changed; remeasure geometry: '+entry['file'])
def value(obj,name):
 v=getattr(obj,name)
 if isinstance(v,bool):return float(v)
 return float(v.Value if hasattr(v,'Value') else v)
def unit(v):
 v=App.Vector(v); v.normalize(); return v
def radial(polar,azimuth):
 p,a=map(math.radians,(polar,azimuth))
 return App.Vector(math.sin(p)*math.cos(a),math.sin(p)*math.sin(a),-math.cos(p))
def cylinder(radius,t0,t1,c,axis): return Part.makeCylinder(radius,t1-t0,c+axis*t0,axis)
def teardrop(radius,t0,t1,c,axis,enabled):
 """Cylinder with a 45 degree pointed roof toward +Z when enabled.

 The roof apex is at radius*sqrt(2) above the axis, so the hole's upper
 surface makes 45 degrees with the build direction and needs no support.
 The axis must be horizontal for the roof to be printable; the caller uses
 the frame axes, which are horizontal for all tilt values in use (0 deg).
 """
 cyl=cylinder(radius,t0,t1,c,axis)
 if not enabled:return cyl
 ax=unit(axis); up=App.Vector(0,0,1); up=unit(up-ax*up.dot(ax)); side=ax.cross(up)
 s=math.sqrt(.5); base=c+ax*t0
 tr=base+side*(radius*s)+up*(radius*s); tl=base-side*(radius*s)+up*(radius*s)
 apex=base+up*(radius*math.sqrt(2.))
 prism=Part.Face(Part.makePolygon([base,tr,apex,tl,base])).extrude(ax*(t1-t0))
 return cyl.fuse(prism)
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

def ball_side_web(p):
 """Analytic radial web between the pilot bore and the ball void at the boss face.

 The boss face sits at axial distance BearingWidth/2 + SpacerThickness from the
 bearing centre. The pilot is at the bearing centre, so the thinnest point is
 where the pilot wall meets the boss face on the ball side.
 """
 R=value(p,'BallDiameter')/2; Rv=R+value(p,'BallClearance')
 D=R+value(p,'BearingOuterDiameter')/2
 a=value(p,'BearingWidth')/2+value(p,'SpacerThickness')
 return (D-value(p,'PilotDiameter')/2)-math.sqrt(Rv*Rv-a*a)
def boss_face_offset_for_web(p,target):
 """Axial distance from bearing centre to the boss face that gives `target` web."""
 lo,hi=0.,40.
 for _ in range(200):
  mid=(lo+hi)/2
  R=value(p,'BallDiameter')/2; Rv=R+value(p,'BallClearance'); D=R+value(p,'BearingOuterDiameter')/2
  web=(D-value(p,'PilotDiameter')/2)-math.sqrt(max(Rv*Rv-mid*mid,0.))
  if web>=target:hi=mid
  else:lo=mid
 return hi

def ceramic_recess_sites():
 """Measured recess axes of the original 2 mm ceramic-ball seats."""
 return json.loads((HERE/'inspect/logs/site_feasibility.json').read_text())['sites']
def recess_fills(p):
 """Plugs that close the original ceramic-ball recesses, trimmed to the ball void."""
 v=validate_parameters(p)
 if not v['FillCeramicRecesses']:return []
 inner=Part.makeSphere(v['CeramicRecessFillInnerRadius'],CENTER)
 r=v['CeramicRecessFillDiameter']/2
 return [cylinder(r,v['CeramicRecessFillInnerRadius']-.5,v['CeramicRecessFillOuterRadius'],CENTER,unit(App.Vector(*s['u']))).cut(inner)
  for s in ceramic_recess_sites()]

def cup_centre():
 c=json.loads((HERE/'inspect/logs/cup_fit_trackballcase.json').read_text())['inner']['center']
 return App.Vector(*c)
def ceramic_pad_cuts(p):
 """Cutters that remove the raised ceramic-ball pads down to just below the cup surface."""
 v=validate_parameters(p)
 if not v['RemoveCeramicPads']:return []
 c=cup_centre();sphere=Part.makeSphere(v['CeramicPadCutRadius'],c)
 r=v['CeramicPadCutDiameter']/2
 return [cylinder(r,v['CeramicPadCutRadius']-4,v['CeramicPadCutRadius']+.5,c,unit(App.Vector(*st['u']))).common(sphere)
  for st in ceramic_recess_sites()]

def validate_parameters(p):
 vals={k:value(p,k) for k in DEFAULTS}
 if not all(math.isfinite(v) for v in vals.values()):raise ValueError('dimensions must be finite values')
 if not all(v>0 for k,v in vals.items() if k not in ANGLE_NAMES|BOOL_NAMES):raise ValueError('length dimensions must be positive')
 for k in BOOL_NAMES:
  if vals[k] not in (0.,1.):raise ValueError(f'{k} must be True or False')
 if vals['DriverHoleLength']<=vals['ToolAccessDepth']:raise ValueError('driver hole must extend beyond the head tunnel')
 if vals['DriverHoleDiameter']>vals['ScrewHeadDiameter']+.6:raise ValueError('driver hole wider than the head tunnel')
 bottoms=[s['hole_bottom_radius_from_center'] for s in ceramic_recess_sites()]
 if not vals['BallDiameter']/2+vals['BallClearance']<=vals['CeramicRecessFillInnerRadius']<min(bottoms)-.5:raise ValueError('recess fill must start outside the ball void and well before the recess bottom')
 if not max(bottoms)<vals['CeramicRecessFillOuterRadius']<19.45:raise ValueError('recess fill must pass the recess bottom and stay inside the 19.49 mm shell')
 if not 18.0<vals['CeramicPadCutRadius']<min(bottoms)-.5:raise ValueError('pad cut must pass the 17.99 mm cup surface and leave the recess plug')
 if not 4.8<=vals['CeramicPadCutDiameter']<=7.0:raise ValueError('pad cut diameter outside the measured 4.8 mm pad and the 8 mm clear zone')
 if vals['CeramicRecessFillDiameter']<1.9:raise ValueError('recess fill narrower than the 1.75 mm recess')
 if vals['BearingInnerDiameter']>=vals['BearingOuterDiameter']:raise ValueError('bearing ID must be below OD')
 if not vals['BearingInnerDiameter']<vals['InnerRingContactDiameter']<vals['BearingOuterDiameter']:raise ValueError('inner-ring contact diameter out of range')
 if vals['PilotDiameter']>=vals['ScrewDiameter']:raise ValueError('pilot must be smaller than screw')
 if vals['ScrewDiameter']>vals['BearingInnerDiameter']:raise ValueError('screw cannot exceed bearing bore')
 if vals['ScrewHeadDiameter']<=vals['InnerRingContactDiameter']:raise ValueError('head must retain inner-ring spacer')
 if not vals['ScrewDiameter']<vals['SpacerBoreDiameter']<vals['InnerRingContactDiameter']:raise ValueError('spacer bore must clear the screw and stay inside the spacer OD')
 if vals['ShellReliefDiameter']<=vals['ScrewDiameter']:raise ValueError('shell relief must clear the screw')
 if vals['ScrewLength']<vals['BearingWidth']+2*vals['SpacerThickness']+1.5:raise ValueError('insufficient screw engagement')
 _face=vals['BearingWidth']/2+vals['SpacerThickness']
 _tip=-_face+vals['ScrewLength']; _boss_end=_face+vals['BossLength']
 if min(_tip,_boss_end)-_face<vals['MinThreadEngagement']:raise ValueError('insufficient thread engagement in boss')
 if vals['ToolAccessDepth']<8:raise ValueError('insufficient fastener access depth')
 if vals['BallSideWebFloor']>vals['MinBallSideWeb']:raise ValueError('web floor above web target')
 if vals['EdgeBreak']>0.8:raise ValueError('EdgeBreak above the 0.8 mm review limit')
 if vals['CouponBaseThickness']<2.0:raise ValueError('coupon base must be at least 2.0 mm')
 if vals['CouponPitch']<11:raise ValueError('coupon pitch too small for 10 mm units')
 for k in COUPON_LEVELS:
  if not 0<vals[f'CouponClearance{k}']<=0.5:raise ValueError(f'CouponClearance{k} outside 0-0.5 mm')
  if not vals[f'CouponPilot{k}']<vals['ScrewDiameter']:raise ValueError(f'CouponPilot{k} must be below screw diameter')
 for i in range(1,4):
  if not 0<vals[f'Support{i}Polar']<180:raise ValueError(f'Support{i}Polar must be between 0 and 180 degrees')
  if not -90<=vals[f'Support{i}AxisTilt']<=90:raise ValueError(f'Support{i}AxisTilt outside -90..90 degrees')
 return vals

def hardware(p):
 v=validate_parameters(p); half=v['BearingWidth']/2; spacer=v['SpacerThickness']; r=v['BearingOuterDiameter']/2
 tear=bool(v['TeardropHoles'])
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
  # Keep the holder face flat against the inner-ring spacer. The matching
  # relief is cut from the source shell below, not from the boss face.
  holders.append(holder)
  # Extend the pocket slightly into the boss union to avoid a 0.002 mm
  # residual source sliver at the shell/boss join.
  pocket=teardrop(r+v['PocketClearance'],-half-v['PocketClearance'],half+spacer+.05,c,ax,tear)
  # Screw is inserted along the negative axis. Open the shell for its head
  # and driver as well as the bearing; the assembly sweep is checked separately.
  headspace=teardrop(v['ScrewHeadDiameter']/2+.30,-v['ToolAccessDepth'],-half-.01,c,ax,tear)
  cuts.extend([pocket,headspace,pilot,cylinder(v['ShellReliefDiameter']/2,half-.01,half+spacer+.01,c,ax)])
  if v[f'Support{i+1}DriverHole']:
   cuts.append(teardrop(v['DriverHoleDiameter']/2,-v['DriverHoleLength'],-v['ToolAccessDepth']+.01,c,ax,tear))
  underhead=-half-spacer
  shank=cylinder(v['ScrewDiameter']/2,underhead,underhead+v['ScrewLength'],c,ax)
  head=cylinder(v['ScrewHeadDiameter']/2,underhead-v['ScrewHeadHeight'],underhead,c,ax)
  screws.append(shank.fuse(head))
  bore=v['SpacerBoreDiameter']/2
  spacers.append(cylinder(v['InnerRingContactDiameter']/2,underhead,-half,c,ax).cut(cylinder(bore,underhead-.01,-half+.01,c,ax)))
  spacers.append(cylinder(v['InnerRingContactDiameter']/2,half,half+spacer,c,ax).cut(cylinder(bore,half-.01,half+spacer+.01,c,ax)))
 return holders,cuts,bearings,screws,spacers

def _edge_points(edge):
 return edge.discretize(Number=6)

def _edge_break_groups(shape,p):
 """Group boss-root, hole-entrance and pilot-end edges by their distance from each axis."""
 v=validate_parameters(p); half=v['BearingWidth']/2; spacer=v['SpacerThickness']
 t_end=half+spacer+v['BossLength']
 specs=[]
 for c,ax,u in frames(p):
  specs.append((c,ax,v['BossRadius'],'root'))
  specs.append((c,ax,v['PocketClearance']+v['BearingOuterDiameter']/2,'entrance'))
  specs.append((c,ax,v['ScrewHeadDiameter']/2+.30,'entrance'))
  specs.append((c,ax,v['PilotDiameter']/2,'pilot_end'))
 groups={'root':{},'entrance':{},'pilot_end':{}}
 reach=v['BossRadius']+1.0
 centres=[c for c,_,_ in frames(p)]
 for edge in shape.Edges:
  bb=edge.BoundBox;mid=App.Vector(bb.Center);half_diag=bb.DiagonalLength/2
  if not any((mid-c).Length<=reach+half_diag for c in centres):continue
  pts=_edge_points(edge)
  for c,ax,radius,kind in specs:
   d=[];t=[]
   for q in pts:
    w=q-c; tt=w.dot(ax); t.append(tt); d.append((w-ax*tt).Length)
   if max(abs(x-radius) for x in d)>0.02:continue
   spread=max(t)-min(t)
   if kind=='pilot_end':
    if abs(max(t)-t_end)<0.02 and abs(min(t)-t_end)<0.02:groups[kind][edge.hashCode()]=edge
   elif spread>0.05:
    if kind=='root' and min(t)<half+spacer-0.05:continue
    groups[kind][edge.hashCode()]=edge
   break
 return {k:list(g.values()) for k,g in groups.items()}

def edge_break(shape,p):
 """Apply the requested edge break per edge group; chamfer is the fallback."""
 radius=value(p,'EdgeBreak')
 report={'requested_mm':radius,'groups':{}}
 for name in ('pilot_end','entrance','root'):
  # Edge identities change after each applied group, so re-select them here.
  edges=_edge_break_groups(shape,p)[name]
  entry={'edges':len(edges),'mode':'none','reason':''}
  report['groups'][name]=entry
  if not edges:
   entry['reason']='no matching edges';continue
  for mode,op in (('fillet',lambda s:s.makeFillet(radius,edges)),('chamfer',lambda s:s.makeChamfer(radius,edges))):
   try:
    out=op(shape).removeSplitter()
    if out.isValid() and len(out.Solids)==1 and abs(out.Volume-shape.Volume)<0.5*radius*radius*len(edges):
     entry['mode']=mode;entry['volume_delta_mm3']=out.Volume-shape.Volume
     shape=out
     break
    entry['reason']+=f'{mode} produced invalid or out-of-range solid; '
   except Exception as exc:
    entry['reason']+=f'{mode} failed ({exc}); '
 modes=[g['mode'] for g in report['groups'].values()]
 report['applied_groups']=sum(m!='none' for m in modes)
 report['total_groups']=len(modes)
 return shape,report

class CaseProxy:
 def __init__(self,obj):obj.Proxy=self
 def execute(self,obj):
  holders,cuts,_,_,_=hardware(obj.Dimensions)
  shape=obj.Source.Shape.copy()
  # Fill the old ceramic-ball recesses first so the bearing cuts still win.
  for i,fill in enumerate(recess_fills(obj.Dimensions)):
   print('recess_fill',i,flush=True);shape=shape.fuse(fill)
  for i,pad in enumerate(ceramic_pad_cuts(obj.Dimensions)):
   print('pad_cut',i,flush=True);shape=shape.cut(pad)
  for i,cut in enumerate(cuts):
   print('cut',i,flush=True);shape=shape.cut(cut)
  for i,holder in enumerate(holders):
   print('holder',i,flush=True);shape=shape.fuse(holder)
  shape=shape.removeSplitter()
  if not shape.isValid() or len(shape.Solids)!=1:raise ValueError('case must be a valid single solid')
  shape,report=edge_break(shape,obj.Dimensions)
  print('edge_break',json.dumps(report),flush=True)
  obj.EdgeBreakResult=json.dumps(report)
  if not shape.isValid() or len(shape.Solids)!=1:raise ValueError('case must be a valid single solid')
  obj.Shape=shape
 def dumps(self):return None
 def loads(self,state):pass

def _coupon_base(p):
 T=value(p,'CouponBaseThickness'); pitch=value(p,'CouponPitch'); tear=bool(value(p,'TeardropHoles'))
 y_axis=App.Vector(0,1,0)
 plate=Part.makeBox(2*(pitch+7),8,T,App.Vector(-(pitch+7),-4,0))
 body=plate;pockets=[];pilots=[]
 # Seat radius follows the bearing OD. The seat centre keeps a 0.6 mm floor under
 # the largest seat, and the block top clears the teardrop roof apex (r*sqrt2)
 # by 0.6 mm, so no roof breaks through the block.
 seat=value(p,'BearingOuterDiameter')/2
 r_max=seat+max(value(p,f'CouponClearance{k}') for k in COUPON_LEVELS)
 zc=T+r_max+.6; top=zc+r_max*math.sqrt(2.)+.6
 for k,x in zip(COUPON_LEVELS,(-pitch,0.,pitch)):
  body=body.fuse(Part.makeBox(10,8,top-T,App.Vector(x-5,-4,T)))
  c=App.Vector(x,-4,zc)
  pockets.append(teardrop(seat+value(p,f'CouponClearance{k}'),-.01,2.01,c,y_axis,tear))
  pilots.append(Part.makeCylinder(value(p,f'CouponPilot{k}')/2,8.02,App.Vector(x,-4.01,zc),y_axis))
 for cutter in pockets+pilots:body=body.cut(cutter)
 return body.removeSplitter()

def coupon_shape(p):
 """Three-level fit coupon; levels 1-3 are left to right (see README)."""
 body=_coupon_base(p)
 bottom=[e for e in body.Edges if all(abs(q.z)<1e-6 for q in _edge_points(e))]
 chamfer=value(p,'CouponElephantChamfer')
 try:
  out=body.makeChamfer(chamfer,bottom).removeSplitter()
  if out.isValid() and len(out.Solids)==1:body=out
 except Exception:
  pass
 if not body.isValid() or len(body.Solids)!=1:raise ValueError('coupon must be one valid solid')
 return body

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
  if name in BOOL_NAMES:typ='App::PropertyBool'
  elif name in ANGLE_NAMES:typ='App::PropertyAngle'
  else:typ='App::PropertyLength'
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
 result.addProperty('App::PropertyLink','Dimensions');result.Dimensions=p
 result.addProperty('App::PropertyString','EdgeBreakResult','Output');CaseProxy(result)
 doc.recompute()
 if result.Shape.isNull():raise ValueError('recompute failed')
 holders,cuts,bearings,screws,spacers=hardware(p)
 for name,shapes in [('Bearings',bearings),('Screws',screws),('LooseSpacers',spacers)]:
  obj=doc.addObject('Part::FeaturePython',name);obj.addProperty('App::PropertyLink','Dimensions');obj.Dimensions=p;HardwareProxy(obj,name)
 ball=doc.addObject('Part::FeaturePython','Ball34');ball.addProperty('App::PropertyLink','Dimensions');ball.Dimensions=p;HardwareProxy(ball,'Ball')
 # Coupon: three bearing-seat / pilot pairs with 0.2/0.3/0.4 mm pocket clearance
 # and 1.55/1.65/1.75 mm pilots (M2 self-tap bracket). It is a fast fit check, not a structural proof.
 coupon=doc.addObject('Part::FeaturePython','FitCoupon');coupon.addProperty('App::PropertyLink','Dimensions');coupon.Dimensions=p;HardwareProxy(coupon,'Coupon')
 doc.recompute();doc.saveAs(str(OUT/'trackball_bearing.FCStd'))
 result.Shape.exportStep(str(OUT/'trackball_bearing.step'))
 Mesh.Mesh(result.Shape.tessellate(.08)).write(str(OUT/'trackball_bearing.stl'))
 coupon.Shape.exportStep(str(OUT/'fit_coupon.step'))
 Mesh.Mesh(coupon.Shape.tessellate(.05)).write(str(OUT/'fit_coupon.stl'))
 Mesh.Mesh(spacers[0].tessellate(.03)).write(str(OUT/'inner_ring_spacer.stl'))
 v=validate_parameters(p)
 manifest={'status':'CANDIDATE_REQUIRES_VALIDATION','source_sha256':sha(ROOT/'case/trackballcase.stl'),'code_sha256':sha(__file__),'freecad':App.Version(),'units':'mm','parameters':v,'ball_center_local':[CENTER.x,CENTER.y,CENTER.z],'case_volume':result.Shape.Volume,'valid':result.Shape.isValid(),'solids':len(result.Shape.Solids),'ball_side_web_mm':ball_side_web(p),'edge_break':json.loads(result.EdgeBreakResult),'outputs':{x.name:sha(x) for x in OUT.iterdir() if x.suffix.lower() in ('.fcstd','.step','.stl')},'unverified':['inner race face diameter and screw fit','assembly/tool access','PCB and wiring','strength and printability','source self-intersections','complete wall thickness','ball-side web target (see verification.json)']}
 (OUT/'build.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest),flush=True)
 return doc

if __name__=='__main__':
 import bearing_case
 bearing_case.build()
