import math
from build_vertex_lab import scene,Q
import numpy as np

def matrix(frame):
    angle=frame*2*math.pi/32;s,c=math.sin(angle),math.cos(angle);a=11/9;b=-20/9;r=5.4
    return [round(v*Q) for v in [1.5*c,0,-a*s,-s,0,2,0,0,1.5*s,0,a*c,c,-1.5*s*r,0,a*r*(1-c)+b,r*(1-c)]]
def project(v,m):
    clip=[(sum(v[j]*m[j*4+i] for j in range(3))+m[12+i]*Q)>>12 for i in range(4)]
    assert clip[3]>0 and all(-131072<=c<=131071 for c in clip)
    ndc=[(abs(c)*Q//clip[3])*(-1 if c<0 else 1) for c in clip[:3]]
    p=((ndc[0]+Q)*320>>12,(Q-ndc[1])*240>>12)
    assert 0<=p[0]<640 and 0<=p[1]<480 and -Q<=ndc[2]<=Q
    return p,Q/clip[3]

def order(frame):
    m=matrix(frame);mesh=scene();maps={};keys={};out={};ind={}
    for i,(verts,_,colors) in enumerate(mesh):
        projections=[project(v,m) for v in verts];p=np.array([r[0] for r in projections]);z=np.array([r[1] for r in projections]);x0,y0=p.min(0);x1,y1=p.max(0)
        dx1,dy1=p[1]-p[0];dx2,dy2=p[2]-p[0];area=int(dx1*dy2-dy1*dx2);
        if area==0:continue
        y,x=np.mgrid[y0:y1+1,x0:x1+1];a=((p[1,0]-x)*(p[2,1]-y)-(p[1,1]-y)*(p[2,0]-x))/area;b=((p[2,0]-x)*(p[0,1]-y)-(p[2,1]-y)*(p[0,0]-x))/area;c=1-a-b
        valid=(a>1e-6)&(b>1e-6)&(c>1e-6);depth=a*z[0]+b*z[1]+c*z[2]
        maps[i]=(x0,y0,x1,y1,depth,valid);out[i]=set();ind[i]=0;keys[i]=float(z.mean())
    for i in maps:
        for j in maps:
            if j<=i:continue
            a,b=maps[i],maps[j];x0=max(a[0],b[0]);y0=max(a[1],b[1]);x1=min(a[2],b[2]);y1=min(a[3],b[3])
            if x0>x1 or y0>y1:continue
            sa=np.s_[y0-a[1]:y1-a[1]+1,x0-a[0]:x1-a[0]+1];sb=np.s_[y0-b[1]:y1-b[1]+1,x0-b[0]:x1-b[0]+1]
            mask=a[5][sa]&b[5][sb];delta=(a[4][sa]-b[4][sb])[mask]
            pos=np.any(delta>1e-5);neg=np.any(delta< -1e-5)
            if pos and neg:raise ValueError(('Intersecting depth order',frame,i,j))
            if pos or neg:
                far,near=(j,i) if pos else (i,j);out[far].add(near);ind[near]+=1
    ordered=[]
    while ind:
        ready=[i for i in ind if ind[i]==0]
        if not ready:raise RuntimeError(('cycle',frame,ind))
        i=min(ready,key=lambda k:(keys[k],k));ordered.append(i);del ind[i]
        for j in out[i]:ind[j]-=1
    return ordered
