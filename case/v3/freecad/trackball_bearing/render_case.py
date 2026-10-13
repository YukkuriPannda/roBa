"""Render assembly and actual mesh sections without a GUI."""
from pathlib import Path
import numpy as np
import FreeCAD as App
import Mesh
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import bearing_case as model
from mesh_checks import triangles
O=model.OUT
doc=App.openDocument(str(O/'trackball_bearing.FCStd'));p=doc.getObject('Dimensions')
case=Mesh.Mesh(str(O/'trackball_bearing.stl'))
# Make the enclosure translucent so the bearings and retainers remain visible
# in the assembled view instead of being hidden behind the case shell.
components=[(triangles(case),'#8aafcc',.22)]
for name,color in [('Bearings','#3fa36d'),('Screws','#d88a22'),('LooseSpacers','#b14c54')]:
 shape=doc.getObject(name).Shape
 components.append((triangles(Mesh.Mesh(shape.tessellate(.12))),color,1.))
components.append((triangles(Mesh.Mesh(doc.getObject('Ball34').Shape.tessellate(.8))),'#80b8e8',.12))
fig=plt.figure(figsize=(13,6))
for i,(elev,az) in enumerate(((25,-65),(88,0))):
 ax=fig.add_subplot(1,2,i+1,projection='3d')
 for component_index,(tri,color,alpha) in enumerate(components):
  if i==1 and component_index in (0,4):continue
  ax.add_collection3d(Poly3DCollection(tri,facecolor=color,edgecolor='none',alpha=alpha))
 ax.set_xlim(-23,33);ax.set_ylim(-25,25);ax.set_zlim(0,42)
 ax.set_box_aspect((56,50,42));ax.view_init(elev,az);ax.set_axis_off()
 ax.set_title('34mm ball / 3 bearings / M2 x 6mm'+(' / case and ball hidden' if i==1 else ''))
fig.tight_layout();fig.savefig(O/'assembly_preview.png',dpi=140);plt.close(fig)

fig,axs=plt.subplots(1,3,figsize=(15,5))
parts=[(case,'#253b4a','case')]
for name,color in [('Bearings','#3fa36d'),('Screws','#d88a22'),('LooseSpacers','#b14c54')]:
 parts.append((Mesh.Mesh(doc.getObject(name).Shape.tessellate(.04)),color,name))
for i,(c,axis,u) in enumerate(model.frames(p)):
 ax=axs[i];normal=axis.cross(u)
 for mesh,color,label in parts:
  polys=mesh.crossSections([(c,normal)],1e-5)[0]
  for j,poly in enumerate(polys):
   pts=np.array([[(q-c).dot(axis),(q-c).dot(u)] for q in poly])
   if len(pts)>1:ax.plot(pts[:,0],pts[:,1],color=color,lw=1.4,label=label if j==0 else None)
 radius=model.value(p,'BallDiameter')/2+model.value(p,'BearingOuterDiameter')/2
 ax.add_patch(Circle((0,-radius),model.value(p,'BallDiameter')/2,fill=False,color='#2793cf',lw=1.5))
 ax.set_xlim(-7,6);ax.set_ylim(-5,5);ax.set_aspect('equal');ax.grid(alpha=.25)
 ax.set_xlabel('Axial position (mm)');ax.set_ylabel('Radial offset (mm)');ax.set_title(f'Support {i+1}: actual mesh section')
 ax.legend(loc='lower right',fontsize=7)
fig.tight_layout();fig.savefig(O/'support_sections.png',dpi=140);plt.close(fig)
print('Rendered',O)

# The lower support is closest to the top. Show the actual body sections in
# its radial/shaft plane; the plot is visual evidence, numerical checks decide.
import json,math,Part
alignment=json.loads((model.HERE/'inspect/logs/alignment.json').read_text())
transform=App.Matrix();transform.rotateZ(math.radians(alignment['rotation_z_deg']));transform.move(App.Vector(*alignment['translation_xy'],alignment['translation_z_assuming_flange_contact']))
c,axis,u=model.frames(p)[1];normal=axis.cross(u)
fig,ax=plt.subplots(figsize=(10,6))
for mesh,color,label in parts:
 for j,poly in enumerate(mesh.crossSections([(c,normal)],1e-5)[0]):
  pts=np.array([[(q-c).dot(axis),(q-c).dot(u)] for q in poly])
  if len(pts)>1:ax.plot(pts[:,0],pts[:,1],color=color,label=label if j==0 else None)
for name,color in [('top_R','#865399'),('bottom_R','#777777')]:
 shape=Part.read(str(model.ROOT/f'case/v3/{name}.stp'));shape.transformShape(transform.inverse(),True)
 mesh=Mesh.Mesh(shape.tessellate(.1))
 for j,poly in enumerate(mesh.crossSections([(c,normal)],1e-5)[0]):
  pts=np.array([[(q-c).dot(axis),(q-c).dot(u)] for q in poly])
  if len(pts)>1:ax.plot(pts[:,0],pts[:,1],color=color,lw=2,label=name if j==0 else None)
ax.set_xlim(-15,10);ax.set_ylim(-10,12);ax.set_aspect('equal');ax.grid(alpha=.25);ax.legend();ax.set_xlabel('Axial position (mm)');ax.set_ylabel('Radial offset (mm)');ax.set_title('Lower support / assembled top and bottom sections')
fig.tight_layout();fig.savefig(O/'body_clearance_section.png',dpi=150);plt.close(fig)
