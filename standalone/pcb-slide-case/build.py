from pathlib import Path
import json, hashlib
import FreeCAD as A
import Part, MeshPart

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'generated'
OUT.mkdir(exist_ok=True)
d = A.newDocument('PCBSlideCase')
p = d.addObject('App::FeaturePython','Dimensions')
for name,value in [('InnerWidth',100),('InnerLength',100),('InnerHeight',50),('Wall',3),('Clearance',0.3)]:
    p.addProperty('App::PropertyLength',name,'Design'); setattr(p,name,value)

def box(name, dims, pos):
    o=d.addObject('Part::Box',name)
    for key, expr in zip(['Length','Width','Height'],dims): o.setExpression(key,expr)
    for axis,expr in zip('xyz',pos): o.setExpression('Placement.Base.'+axis,expr)
    return o
def cut(name,a,b):
    o=d.addObject('Part::Cut',name); o.Base=a; o.Tool=b; return o
def fuse(name,parts):
    o=d.addObject('Part::MultiFuse',name); o.Shapes=parts; return o
W='Dimensions.Wall'; X='Dimensions.InnerWidth'; Y='Dimensions.InnerLength'; Z='Dimensions.InnerHeight'; C='Dimensions.Clearance'
outer=box('LowerOuter',[X+'+2*'+W,Y+'+2*'+W,Z+'+'+W],['0','0','0'])
void=box('StorageVoid',[X,Y,Z+'+1'],[W,W,W])
lower=cut('LowerShell',outer,void)
rails=[]
for side in ['Left','Right']:
    x='0' if side=='Left' else X
    rail=box(side+'RailBlank',['2*'+W,Y+'+2*'+W,'3*'+W+'+2*'+C],[x,'0',Z+'+'+W])
    groove_x=W if side=='Left' else X
    groove=box(side+'Groove',[W,Y+'+2*'+W+'+2',W+'+2*'+C],[groove_x,'-1',Z+'+2*'+W])
    rails.append(cut(side+'Rail',rail,groove))
rear=box('RearStop',[X+'+2*'+W,W,'3*'+W+'+2*'+C],['0',Y+'+'+W,Z+'+'+W])
body=fuse('CaseBody',[lower,*rails,rear])
lid=box('SlidingLid',[X+'-2*'+C,Y+'+'+W+'-'+C,W],[W+'+'+C,'0',Z+'+2*'+W+'+'+C])
d.recompute()
for o in d.Objects:
    if o.ViewObject: o.ViewObject.Visibility=False
if body.ViewObject:
    body.ViewObject.Visibility=True; lid.ViewObject.Visibility=True
    body.ViewObject.ShapeColor=(0.2,0.55,0.7); lid.ViewObject.ShapeColor=(0.95,0.65,0.2)
checks={}
for o in [body,lid]:
    assert o.Shape.isValid() and len(o.Shape.Solids)==1
    b=o.Shape.BoundBox
    checks[o.Name]={'bbox_mm':[b.XLength,b.YLength,b.ZLength],'volume_mm3':o.Shape.Volume}
storage=Part.makeBox(100,100,50,A.Vector(3,3,3))
assert body.Shape.common(storage).Volume<1e-7
checks['storage_envelope_intersection_mm3']=body.Shape.common(storage).Volume
collisions=[]
for i in range(121):
    s=lid.Shape.copy(); s.translate(A.Vector(0,-i,0)); collisions.append(body.Shape.common(s).Volume)
assert max(collisions)<1e-7
checks['slide_samples']=len(collisions); checks['max_slide_intersection_mm3']=max(collisions)
old=body.Shape.Volume
p.InnerWidth=110; d.recompute()
assert abs(body.Shape.BoundBox.XLength-116)<1e-7
p.InnerWidth=100; d.recompute(); assert abs(body.Shape.Volume-old)<1e-7
checks['width_edit_restore']='passed'
for o in [body,lid]:
    o.Shape.exportStep(str(OUT/(o.Name+'.step')))
    mesh=MeshPart.meshFromShape(Shape=o.Shape,LinearDeflection=0.1,AngularDeflection=0.2,Relative=False)
    assert mesh.isSolid()
    mesh.write(str(OUT/(o.Name+'.stl')))
    checks[o.Name]['mesh_closed']=mesh.isSolid()
    checks[o.Name]['triangles']=mesh.CountFacets
    assert Part.Shape().isNull()
    reload=Part.Shape(); reload.read(str(OUT/(o.Name+'.step')))
    assert reload.isValid() and abs(reload.Volume-o.Shape.Volume)<1e-5
d.saveAs(str(OUT/'PCBSlideCase.FCStd'))
A.closeDocument(d.Name)
r=A.openDocument(str(OUT/'PCBSlideCase.FCStd')); r.recompute()
assert r.CaseBody.Shape.isValid()
r.Dimensions.InnerHeight=55; r.recompute(); assert abs(r.CaseBody.Shape.BoundBox.ZLength-67.6)<1e-7
r.Dimensions.InnerHeight=50; r.recompute()
checks['save_reopen_edit_restore']='passed'
checks['FreeCAD']=A.Version(); checks['units']='mm'; checks['source_step']='none; new design'
checks['generator_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
checks['unverified']=['full thickness analysis','slicer','actual PLA slide fit','PCB fit','strength/heat/durability']
(OUT/'verification.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(checks,ensure_ascii=False))
