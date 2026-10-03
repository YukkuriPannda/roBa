"""Vectorized triangle geometry checks; no slow per-point CAD classification."""
import numpy as np
from scipy.spatial import cKDTree

def triangles(mesh):
 points,faces=mesh.Topology
 return np.asarray([[p.x,p.y,p.z] for p in points])[np.asarray(faces)]

def paired_distances(points,tris):
 a,b,c=tris[:,0],tris[:,1],tris[:,2];ab=b-a;ac=c-a;ap=points-a
 d00=np.einsum('ij,ij->i',ab,ab);d11=np.einsum('ij,ij->i',ac,ac);d01=np.einsum('ij,ij->i',ab,ac)
 d20=np.einsum('ij,ij->i',ap,ab);d21=np.einsum('ij,ij->i',ap,ac);den=d00*d11-d01*d01
 good=den>1e-24; safe=np.where(good,den,1)
 u=(d11*d20-d01*d21)/safe;v=(d00*d21-d01*d20)/safe
 projection=a+u[:,None]*ab+v[:,None]*ac
 plane=np.linalg.norm(points-projection,axis=1)
 edge=[]
 for x,y in ((a,b),(b,c),(c,a)):
  d=y-x;l=np.einsum('ij,ij->i',d,d)
  t=np.clip(np.einsum('ij,ij->i',points-x,d)/np.where(l>0,l,1),0,1)
  edge.append(np.linalg.norm(points-x-t[:,None]*d,axis=1))
 boundary=np.minimum.reduce(edge)
 return np.where(good & (u>=-1e-10) & (v>=-1e-10) & (u+v<=1+1e-10),plane,boundary)

def point_distance(point,tris):
 return float(paired_distances(np.broadcast_to(point,(len(tris),3)),tris).min())

def sampled_surface_distance(a,b):
 ta,tb=triangles(a),triangles(b)
 maxima=[]
 for source,target in ((ta,tb),(tb,ta)):
  points=np.concatenate((source.reshape(-1,3),source.mean(axis=1)))
  points=np.unique(points,axis=0)
  target_samples=np.concatenate((target.reshape(-1,3),target.mean(axis=1)))
  already_shared=cKDTree(target_samples).query(points)[0]<1e-8
  # Most triangles are identical. For the locally changed samples, scan every
  # target triangle; centroid-nearest candidates can miss long narrow facets.
  distances=[point_distance(p,target) for p in points[~already_shared]]
  maxima.append(max(distances,default=0.))
 return max(maxima)

def contains(point,tris):
 ray=np.array([1.,.371,.113]);ray/=np.linalg.norm(ray)
 e1=tris[:,1]-tris[:,0];e2=tris[:,2]-tris[:,0];h=np.cross(ray,e2)
 det=np.einsum('ij,ij->i',e1,h);valid=np.abs(det)>1e-12
 inv=1/np.where(valid,det,1);s=point-tris[:,0]
 u=inv*np.einsum('ij,ij->i',s,h);q=np.cross(s,e1)
 v=inv*(q@ray);t=inv*np.einsum('ij,ij->i',e2,q)
 hits=np.sort(t[valid & (u>=0) & (v>=0) & (u+v<=1) & (t>1e-7)])
 if not len(hits):return False
 return bool((1+np.count_nonzero(np.diff(hits)>1e-6))%2)
