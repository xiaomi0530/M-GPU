import math
from functools import lru_cache
from pathlib import Path
import json
from mechanical_core import scene,groups,raw_matrix,Q,FRAME_COUNT,GROUP_COUNT
import numpy as np

KEY_STRIDE=8
KEY_COUNT=FRAME_COUNT//KEY_STRIDE

@lru_cache(maxsize=KEY_COUNT*GROUP_COUNT)
def key_matrix(key,group=0):return raw_matrix((key%KEY_COUNT)*KEY_STRIDE,group)

def matrix(frame,group=0):
    frame=frame%FRAME_COUNT;key=int(frame//KEY_STRIDE);fraction=frame%KEY_STRIDE
    return [a+math.floor((b-a)*fraction/KEY_STRIDE) for a,b in zip(key_matrix(key,group),key_matrix(key+1,group))]
def project(v,m):
    clip=[(sum(v[j]*m[j*4+i] for j in range(3))+m[12+i]*Q)>>12 for i in range(4)]
    assert clip[3]>0 and all(-131072<=c<=131071 for c in clip)
    ndc=[(abs(c)*Q//clip[3])*(-1 if c<0 else 1) for c in clip[:3]]
    p=((ndc[0]+Q)*320>>12,(Q-ndc[1])*240>>12)
    assert 0<=p[0]<640 and 0<=p[1]<480 and -Q<=ndc[2]<=Q
    return p,Q/clip[3]

def ordered(mesh,group_ids,matrices,idents=None,label=None):
    maps={};out={};ind={}
    for i in range(len(mesh)) if idents is None else idents:
        verts,_,colors=mesh[i];m=matrices[group_ids[i]]
        projections=[project(v,m) for v in verts];p=np.array([r[0] for r in projections]);z=np.array([r[1] for r in projections]);x0,y0=p.min(0);x1,y1=p.max(0)
        dx1,dy1=p[1]-p[0];dx2,dy2=p[2]-p[0];area=int(dx1*dy2-dy1*dx2);
        if area<=0:continue
        y,x=np.mgrid[y0:y1+1,x0:x1+1];a=((p[1,0]-x)*(p[2,1]-y)-(p[1,1]-y)*(p[2,0]-x))/area;b=((p[2,0]-x)*(p[0,1]-y)-(p[2,1]-y)*(p[0,0]-x))/area;c=1-a-b
        valid=(a>1e-6)&(b>1e-6)&(c>1e-6);depth=a*z[0]+b*z[1]+c*z[2]
        maps[i]=(x0,y0,x1,y1,depth,valid);out[i]=set();ind[i]=0
    for i in maps:
        for j in maps:
            if j<=i:continue
            a,b=maps[i],maps[j];x0=max(a[0],b[0]);y0=max(a[1],b[1]);x1=min(a[2],b[2]);y1=min(a[3],b[3])
            if x0>x1 or y0>y1:continue
            sa=np.s_[y0-a[1]:y1-a[1]+1,x0-a[0]:x1-a[0]+1];sb=np.s_[y0-b[1]:y1-b[1]+1,x0-b[0]:x1-b[0]+1]
            mask=a[5][sa]&b[5][sb];delta=(a[4][sa]-b[4][sb])[mask]
            pos=np.any(delta>1e-5);neg=np.any(delta< -1e-5)
            if pos and neg:
                if len(set(mesh[i][2]+mesh[j][2]))==1:continue
                raise ValueError(('Intersecting depth order',label,i,j))
            if pos or neg:
                far,near=(j,i) if pos else (i,j);out[far].add(near);ind[near]+=1
    ordered=[]
    while ind:
        ready=[i for i in ind if ind[i]==0]
        if not ready:raise RuntimeError(('cycle',label,ind))
        i=min(ready);ordered.append(i);del ind[i]
        for j in out[i]:ind[j]-=1
    return ordered


@lru_cache(maxsize=FRAME_COUNT)
def order(frame):return ordered(scene(),groups(),[matrix(frame,g) for g in range(GROUP_COUNT)],label=frame)


def generate():
    from verify_vertex_lab import render,to_image
    from PIL import Image
    root=Path(__file__).resolve().parents[1];output=root/'docs/images/mechanical_core';output.mkdir(parents=True,exist_ok=True)
    mesh=scene();group_ids=groups();images=[];counts=[]
    for frame in range(FRAME_COUNT):
        ids=order(frame);counts.append(len(ids));triangles=[]
        for i in ids:
            m=matrix(frame,group_ids[i])
            points=[(x//2,y//2) for x,y in (project(v,m)[0] for v in mesh[i][0])]
            triangles.append((mesh[i][0],points,mesh[i][2]))
        images.append(to_image(render(triangles,320,240)).resize((640,480),Image.Resampling.NEAREST))
    duration=[round((i+1)*1.6672)*10-round(i*1.6672)*10 for i in range(FRAME_COUNT)]
    images[0].save(output/'animation.gif',save_all=True,append_images=images[1:],duration=duration,loop=0,disposal=2)
    images[160].save(output/'preview.png')
    storyboard=Image.new('RGB',(1920,960))
    for k,frame in enumerate((0,80,160,256,384,480)):storyboard.paste(images[frame],((k%3)*640,(k//3)*480))
    storyboard.save(output/'storyboard.png')
    assets=root/'assets/mechanical_core';assets.mkdir(parents=True,exist_ok=True)
    data=dict(name='MECHANICAL CORE',triangles=len(mesh),groups=GROUP_COUNT,phases=FRAME_COUNT,key_stride=KEY_STRIDE,visible_min=min(counts),visible_max=max(counts),counts=counts)
    (assets/'metadata.json').write_text(json.dumps(data,indent=2)+'\n')
    (assets/'mesh.json').write_text(json.dumps([dict(vertices=v,colors=c,group=g) for (v,p,c),g in zip(mesh,group_ids)])+'\n')
    print(json.dumps({k:v for k,v in data.items() if k!='counts'}))


if __name__=='__main__':generate()
