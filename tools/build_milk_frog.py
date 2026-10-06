from pathlib import Path
import sys
import json
import math

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'out/mesh_libs'))
import numpy as np
from skimage.measure import marching_cubes
import fast_simplification


def ellipsoid(p,c,r):
    q=(p-np.array(c))/np.array(r)
    return (np.linalg.norm(q,axis=-1)-1)*min(r)


def capsule(p,a,b,r):
    a=np.array(a);b=np.array(b);v=b-a
    t=np.clip(np.sum((p-a)*v,axis=-1)/np.dot(v,v),0,1)
    return np.linalg.norm(p-a-t[...,None]*v,axis=-1)-r


def smooth(a,b,k):
    h=np.maximum(k-np.abs(a-b),0)/k
    return np.minimum(a,b)-h*h*k*.25


def field(p):
    d=ellipsoid(p,(0,-.10,.12),(.84,1.03,.62))
    d=smooth(d,ellipsoid(p,(0,-.12,-.26),(.70,.79,.53)),.30)
    d=smooth(d,ellipsoid(p,(0,.66,.04),(.49,.72,.43)),.30)
    d=smooth(d,ellipsoid(p,(0,1.20,-.05),(.46,.54,.44)),.22)
    for sign in [-1,1]:
        d=smooth(d,ellipsoid(p,(sign*.39,-1.22,.10),(.28,.57,.29)),.20)
        d=smooth(d,ellipsoid(p,(sign*.48,-1.69,-.13),(.32,.14,.43)),.11)
        d=smooth(d,capsule(p,(sign*.67,.45,.06),(sign*.98,-.13,-.06),.22),.12)
        d=smooth(d,capsule(p,(sign*.98,-.13,-.06),(sign*.65,-.56,-.58),.20),.10)
        d=smooth(d,ellipsoid(p,(sign*.59,-.58,-.66),(.19,.23,.18)),.09)
    return d


def front(x,y):
    lo=-1.5;hi=.1
    for _ in range(32):
        mid=(lo+hi)/2
        if field(np.array([x,y,mid]))>0:lo=mid
        else:hi=mid
    return (lo+hi)/2


def normal(v):
    e=np.eye(3)*.002
    n=np.array([field(v+a)-field(v-a) for a in e])
    return n/max(np.linalg.norm(n),1e-9)


def build():
    low=np.array([-1.35,-1.92,-1.05]);high=np.array([1.35,1.90,1.02]);step=.035
    axes=[np.arange(a,b+step,step) for a,b in zip(low,high)]
    grid=np.stack(np.meshgrid(*axes,indexing='ij'),axis=-1)
    vertices,faces,_,_=marching_cubes(field(grid),0,spacing=(step,step,step),gradient_direction='ascent')
    vertices+=low
    vertices,faces=fast_simplification.simplify(vertices,faces,target_count=400,agg=5)
    result=[]
    light=np.array([-.45,.75,-.50]);light/=np.linalg.norm(light)
    def add(points,colors):
        result.append(dict(vertices=np.round(np.array(points),6).tolist(),colors=np.clip(colors,0,255).astype(int).tolist()))
    for f in faces:
        p=vertices[f];center=p.mean(0);n=np.cross(p[1]-p[0],p[2]-p[0])
        if np.dot(n,normal(center))<0:p=p[[0,2,1]]
        v=center;n=normal(v);color=np.array([255.,218.,72.])
        belly=(v[0]/.73)**2+((v[1]+.04)/.77)**2
        if v[2]<-.34 and belly<1.05:color=np.array([255.,248.,205.])
        if v[1]<-1.55:color=np.array([74.,82.,41.])
        hand=min(ellipsoid(v,(side*.59,-.58,-.66),(.205,.245,.195)) for side in [-1,1])
        if hand<.025 and v[2]<-.55 and abs(v[0])>.43:color=np.array([77.,85.,43.])
        gain=.90+.10*max(0,np.dot(n,light))
        if v[2]<-.34 and belly<1.05:color=np.array([255.,235.,200.]);gain=1.0
        add(p,[color*gain]*3)
    for sign in [-1,1]:
        cx=sign*.245;cy=1.25;n=12
        rings=[]
        for r in [1.,.48]:
            rings.append([np.array([cx+.157*r*math.cos(t),cy+.184*r*math.sin(t),0.]) for t in np.arange(n)*2*math.pi/n])
            for v in rings[-1]:v[2]=front(v[0],v[1])-.045-.075*(1-r*r)
        center=np.array([cx,cy,front(cx,cy)-.125])
        for j in range(n):
            k=(j+1)%n;a,b=rings
            for p in [[a[j],a[k],b[k]],[a[j],b[k],b[j]]]:add(p,[[117,191,67]]*3)
            add([b[j],b[k],center],[[14,25,14]]*3)
        for p in [np.array([[cx-.027,cy+.045,center[2]-.007],[cx-.008,cy+.060,center[2]-.009],[cx+.002,cy+.031,center[2]-.009]])]:add(p,[[236,245,201]]*3)
    mouth=[]
    for x in np.linspace(-.22,.22,7):
        y=.91+.035*(x/.22)**2
        mouth.append([np.array([x,y+dy,front(x,y+dy)-.038]) for dy in [-.012,.012]])
    for a,b in zip(mouth,mouth[1:]):
        add([a[0],b[0],b[1]],[[83,77,31]]*3);add([a[0],b[1],a[1]],[[83,77,31]]*3)
    for f in result[len(faces):]:
        p=np.array(f['vertices']);n=np.cross(p[1]-p[0],p[2]-p[0]);center=p.mean(0)
        if n[2]>0 and center[1]>.8 and center[2]<-.4:
            f['vertices']=[f['vertices'][i] for i in [0,2,1]];f['colors']=[f['colors'][i] for i in [0,2,1]]
    output=ROOT/'assets/milk_frog';output.mkdir(exist_ok=True)
    (output/'mesh.json').write_text(json.dumps(result,separators=(',',':')))
    text=['mtllib milk_frog.mtl'];palette={};materials=[]
    for f in result:
        for v in f['vertices']:text.append('v '+' '.join(map(str,v)))
    for i,f in enumerate(result):
        color=tuple(np.mean(f['colors'],axis=0).round().astype(int))
        if color not in palette:
            name='color_'+str(len(palette));palette[color]=name
            materials.extend(['newmtl '+name,'Kd '+' '.join(f'{c/255:.6f}' for c in color),'Ka 0 0 0','Ks 0 0 0','d 1','illum 1',''])
        text.append('usemtl '+palette[color])
        text.append('f '+' '.join(str(3*i+j+1) for j in range(3)))
    (output/'milk_frog.obj').write_text('\n'.join(text)+'\n')
    (output/'milk_frog.mtl').write_text('\n'.join(materials))
    print(len(result),'triangles')


if __name__=='__main__':build()
