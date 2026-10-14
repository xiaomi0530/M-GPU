from pathlib import Path
from functools import lru_cache
import json
import math
import numpy as np
from mechanical_core import GROUP_COUNT as MODEL_GROUP_COUNT

ROOT=Path(__file__).resolve().parents[1]
Q=4096
FRAME_COUNT=420
GROUP_COUNT=16+MODEL_GROUP_COUNT
MODEL_START=372
MODEL_OFFSET=558
MODEL_GROUP=16
INTRO_NEXT_FRAME=25


def rgb(r,g,b):
    return (round(max(0,min(255,r))*7/255)<<5)|(round(max(0,min(255,g))*7/255)<<2)|round(max(0,min(255,b))*3/255)


def signed_area(points):
    return sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1]))/2


def triangulate(points):
    points=list(points)
    if signed_area(points)<0:points.reverse()
    remaining=list(range(len(points)));triangles=[]
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    while len(remaining)>3:
        for k,b in enumerate(remaining):
            a=remaining[k-1];c=remaining[(k+1)%len(remaining)]
            if cross(points[a],points[b],points[c])<1e-9:continue
            if any(all(cross(points[u],points[v],points[i])>=-1e-9 for u,v in [(a,b),(b,c),(c,a)])
                   for i in remaining if points[i] not in (points[a],points[b],points[c])):continue
            triangles.append([points[a],points[b],points[c]]);remaining.pop(k);break
        else:raise ValueError(('Cannot triangulate',points,remaining))
    triangles.append([points[i] for i in remaining])
    return triangles


def glyphs():
    m=[(0,0),(.25,0),(.25,.93),(.60,.52),(.95,.93),(.95,0),(1.2,0),(1.2,1.4),(.94,1.4),(.60,.98),(.26,1.4),(0,1.4)]
    i=[(0,0),(.30,0),(.30,1.4),(0,1.4)]
    d=[(0,0),(.78,0),(1.1,.32),(1.1,1.08),(.78,1.4),(0,1.4)]
    dh=[(.28,.28),(.66,.28),(.82,.44),(.82,.96),(.66,1.12),(.28,1.12)]
    y=[(0,1.4),(.32,1.4),(.56,.93),(.80,1.4),(1.12,1.4),(.70,.66),(.70,0),(.42,0),(.42,.66)]
    a=[(0,0),(.28,0),(.43,.40),(.83,.40),(.98,0),(1.26,0),(.75,1.4),(.51,1.4)]
    ah=[(.52,.65),(.74,.65),(.63,1.0)]
    s=[(.19,0),(.86,0),(1.08,.22),(1.08,.64),(.86,.84),(.28,.84),(.28,1.10),(1.08,1.10),(1.08,1.4),(.20,1.4),(0,1.20),(0,.74),(.21,.54),(.80,.54),(.80,.30),(0,.30)]
    g=[(.22,0),(1.08,0),(1.08,.76),(.57,.76),(.57,.49),(.80,.49),(.80,.28),(.30,.28),(.28,.30),(.28,1.10),(.30,1.12),(1.08,1.12),(1.08,1.4),(.22,1.4),(0,1.18),(0,.22)]
    p=[(0,0),(.28,0),(.28,.53),(.84,.53),(1.08,.77),(1.08,1.16),(.84,1.4),(0,1.4)]
    ph=[(.28,.81),(.70,.81),(.80,.91),(.80,1.02),(.70,1.12),(.28,1.12)]
    u=[(.22,0),(.88,0),(1.1,.22),(1.1,1.4),(.82,1.4),(.82,.34),(.76,.28),(.34,.28),(.28,.34),(.28,1.4),(0,1.4),(0,.22)]
    return [(m,[],1.2),(i,[],.3),(d,[(dh,2)],1.1),(i,[],.3),(y,[],1.12),(a,[(ah,5)],1.26),(s,[],1.08)],[(g,[],1.08),(p,[(ph,4)],1.08),(u,[],1.1)]


@lru_cache(maxsize=1)
def geometry():
    faces=[];group_ids=[];centers=[(0.,0.,0.) for _ in range(GROUP_COUNT)]
    def face(points,colors,group):
        if isinstance(colors,int):colors=[colors]*3
        faces.append(([tuple(round(float(c)*Q) for c in p) for p in points],colors));group_ids.append(group)
    def extrude(outer,holes,group,scale=1.,offset=0.,depth=.18,palette=0):
        outer=list(outer)
        if signed_area(outer)<0:outer.reverse()
        contours=[outer];polygon=list(outer)
        for hole,bridge in holes:
            hole=list(hole)
            if signed_area(hole)>0:hole.reverse()
            h=max(range(len(hole)),key=lambda j:(hole[j][0],-hole[j][1]));o=polygon.index(outer[bridge])
            polygon=polygon[:o+1]+hole[h:]+hole[:h+1]+polygon[o:];contours.append(hole)
        def vertex(p,z):return ((p[0]+offset)*scale,p[1]*scale,z)
        def front(p):
            t=max(0,min(1,p[1]/1.4))
            if palette==0:return rgb(182+73*t,219+36*t,255)
            if palette==1:return rgb(0,146+109*t,255)
            return rgb(109+109*t,36+73*t,255)
        for tri in triangulate(polygon):
            face([vertex(p,-.08) for p in reversed(tri)],[front(p) for p in reversed(tri)],group)
            face([vertex(p,depth) for p in tri],rgb(36,0,85),group)
        for contour in contours:
            for a,b in zip(contour,contour[1:]+contour[:1]):
                points=[vertex(a,-.08),vertex(b,-.08),vertex(b,depth),vertex(a,depth)]
                color=rgb(73,36,170) if b[0]>a[0] else rgb(0,73,170) if b[1]>a[1] else rgb(36,0,85)
                for indices in [(0,1,2),(0,2,3)]:face([points[k] for k in indices],color,group)
    main,sub=glyphs();gap=.19;scale=5.35/(sum(g[2] for g in main)+gap*6)
    cursor=-5.35/2
    for group,(outer,holes,width) in enumerate(main):
        extrude(outer,holes,group,scale,-width/2,depth=.18)
        centers[group]=(cursor+width*scale/2,-.55-.70*scale,-.12)
        cursor+=(width+gap)*scale
    width=sum(g[2] for g in sub)+.26*2;scale=.36;cursor=-width/2
    for outer,holes,w in sub:
        extrude(outer,holes,7,scale,cursor,depth=.12,palette=1);cursor+=w+.26
    centers[7]=(0,-1.67,-.10)
    wing=[(-1.02,-.46),(-.68,-.46),(-.68,.27),(-.22,-.21),(0,.03),(-.76,.82),(-1.02,.66)]
    extrude(wing,[],8,depth=.26,palette=1)
    extrude([(-x,y) for x,y in wing],[],9,depth=.26,palette=2)
    centers[8]=centers[9]=(0,.72,-.18)
    equator=[(-.19,0,0),(0,.19,0),(.19,0,0),(0,-.19,0)]
    for j in range(4):
        face([equator[j],equator[(j+1)%4],(0,0,-.22)],rgb(255,219 if j%2 else 182,85),10)
        face([equator[(j+1)%4],equator[j],(0,0,.14)],rgb(182,73,0),10)
    centers[10]=(0,.49,-.78)
    for group,angles,palette in [(11,[(15,75),(135,195)],(0,219,255)),(12,[(75,135),(195,255),(315,375)],(182,73,255))]:
        centers[group]=(0,.87,1.65 if group==11 else 1.74)
        for start,end in angles:
            for j in range(3):
                a=math.radians(start+(end-start)*j/3+2);b=math.radians(start+(end-start)*(j+1)/3-2)
                for radius,width,gain in [(1.44,.14,.24),(1.42,.055,1.)]:
                    points=[(r*math.cos(t),r*.68*math.sin(t),-.02 if gain>.5 else 0) for r,t in [(radius,a),(radius,b),(radius-width,b),(radius-width,a)]]
                    color=rgb(*(v*gain for v in palette))
                    for indices in [(0,2,1),(0,3,2)]:face([points[k] for k in indices],color,group)
    centers[13]=(0,.2,1.95)
    for j in range(8):
        theta=2*math.pi*j/8+.28;x=2.5*math.cos(theta);y=1.45*math.sin(theta)
        dx=.20*math.cos(theta);dy=.20*math.sin(theta);nx=-.035*math.sin(theta);ny=.035*math.cos(theta)
        points=[(x-dx,y-dy,0),(x+nx,y+ny,0),(x+dx,y+dy,0),(x-nx,y-ny,0)]
        for indices in [(0,1,2),(0,2,3)]:face([points[k] for k in indices],rgb(0,182,255) if j%2 else rgb(182,73,255),13)
    centers[14]=(0,-1.42,.04)
    for sign in (-1,1):
        for x1,x2,y1,y2,color in [(1.00,1.75,-.045,.045,rgb(0,182,255)),(1.87,2.01,-.045,.045,rgb(255,182,0))]:
            points=[(sign*x1,y1,0),(sign*x2,y1,0),(sign*x2,y2,0),(sign*x1,y2,0)]
            if sign>0:points.reverse()
            for indices in [(0,1,2),(0,2,3)]:face([points[k] for k in indices],color,14)
    centers[15]=(0,.87,2.12)
    points=[(1.18*math.cos(t),.86*math.sin(t),0) for t in np.linspace(0,2*math.pi,7)[:-1]]
    for j in range(6):
        face([points[(j+1)%6],points[j],(0,0,-.12)],rgb(0,0,85) if j%2 else rgb(36,0,85),15)
    assert len(faces)==MODEL_OFFSET
    from orbit_scene import scene as model_scene,groups as model_groups
    for (vertices,_,colors),group in zip(model_scene(),model_groups()):
        faces.append((vertices,colors));group_ids.append(MODEL_GROUP+group)
    return faces,group_ids,centers


def mesh():return geometry()[0]


def groups():return geometry()[1]


def smooth(t):
    t=max(0,min(1,t));return t*t*(3-2*t)


def rotations(x,y,z):
    sx,cx=math.sin(x),math.cos(x);sy,cy=math.sin(y),math.cos(y);sz,cz=math.sin(z),math.cos(z)
    return np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])@np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])@np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])


def visible(frame,group):
    if group>=MODEL_GROUP:return frame>=MODEL_START
    if frame>=MODEL_START:return False
    seconds=frame*.016672
    if seconds>=6.10 and group!=10:return False
    t=seconds/1.4
    if group<7:return t>=.72+group*.065
    if group==7:return t>=1.38
    if group in (8,9):return t>=.28
    if group==13:return .06<=t<=1.85
    if group==14:return t>=1.48
    if group==15:return t>=.25
    return t>=.03


@lru_cache(maxsize=FRAME_COUNT*GROUP_COUNT)
def matrix(frame,group=0):
    frame=max(0,min(frame,FRAME_COUNT-1))
    if group>=MODEL_GROUP:
        from orbit_scene import matrix as orbit_matrix
        u=max(0,min(1,(frame-MODEL_START)/(FRAME_COUNT-MODEL_START-1)))
        values=np.array(orbit_matrix(24*u*u,group-MODEL_GROUP),dtype=float).reshape((4,4),order='F')
        scale=.055+.945*u*u*u*(10-15*u+6*u*u)
        values[:2]*=scale
        return [round(float(v)) for v in values.flatten(order='F')]
    if not visible(frame,group):return [6144,0,0,0,0,8192,0,0,0,0,5006,4096,0,0,21672,25000]
    seconds=frame*.016672;t=seconds/1.4
    release=smooth((seconds-4.6)/1.585)
    tail=1-smooth((t-3.35)/.65)
    x,y,z=geometry()[2][group];rx=ry=rz=0.;scale=1.
    if group<7:
        u=smooth((t-.72-group*.065)/.62);y-=.44*(1-u);z+=.40*(1-u)
        ry=math.radians(48)*(1-u);rz=math.radians((-1 if group%2 else 1)*8)*(1-u);scale=.58+.42*u
    elif group==7:
        u=smooth((t-1.38)/.55);y-=.18*(1-u);scale=.35+.65*u
    elif group in (8,9):
        sign=-1 if group==8 else 1;u=smooth((t-.28)/.9)
        x+=sign*.9*(1-u);y+=.32*(1-u);z+=.60*(1-u)
        rz=sign*math.radians(52)*(1-u);ry=-sign*math.radians(50)*(1-u)
        ry+=math.radians(9)*math.sin((t-1.2)*2)*smooth((t-1.1)/.5)*tail
    elif group==10:
        scale=.65+.35*smooth(t/.55)+.12*math.sin(t*6)*tail
        ry=t*1.5*tail;rz=t*2*tail
    elif group in (11,12):
        sign=-1 if group==11 else 1;u=smooth(t/.9)
        rz=sign*(1.5*(1-u)+.20*math.sin(t*2)*tail)
        scale=1.35-.35*u+.025*math.sin(t*5)*tail
    elif group==13:
        scale=.24+1.02*smooth(t/1.8);rz=-.12*t
    elif group==14:
        scale=.10+.90*smooth((t-1.48)/.65)
    elif group==15:
        scale=.3+.7*smooth((t-.25)/1.0);rz=.52*(1-smooth(t/1.4))
    if group==10:
        y*=1-release;scale*=1-.52*release
    model=np.eye(4);model[:3,:3]=rotations(rx,ry,rz)*scale;model[:3,3]=[x,y,z]
    yaw=math.radians(-16)*(1-smooth(t/1.9))+math.radians(3)*math.sin(t*1.7)*tail
    pitch=math.radians(7)*(1-smooth(t/2.2))
    view=np.eye(4);view[:3,:3]=rotations(pitch,yaw,0);view[:3,3]=[0,.08*(1-release),7.5-1.35*smooth(t/1.8)]
    projection=np.array([[1.5,0,0,0],[0,2,0,0],[0,0,11/9,-20/9],[0,0,1,0]])
    transform=projection@view@model
    if group!=10:transform[:2]*=1-release
    values=[round(float(v)*Q) for v in transform.flatten(order='F')]
    assert all(-131072<=v<=131071 for v in values)
    return values


def project(v,m):
    clip=[(sum(v[j]*m[j*4+i] for j in range(3))+m[12+i]*Q)>>12 for i in range(4)]
    assert clip[3]>0 and all(-131072<=c<=131071 for c in clip)
    ndc=[(abs(c)*Q//clip[3])*(-1 if c<0 else 1) for c in clip[:3]]
    p=((ndc[0]+Q)*320>>12,(Q-ndc[1])*240>>12)
    assert 0<=p[0]<640 and 0<=p[1]<480 and -Q<=ndc[2]<=Q,(p,ndc)
    return p,Q/clip[3]


@lru_cache(maxsize=1)
def scene():
    return [(verts,[project(v,matrix(0,group))[0] for v in verts],colors) for (verts,colors),group in zip(mesh(),groups())]


@lru_cache(maxsize=FRAME_COUNT)
def order(frame):
    from orbit_scene import ordered,order as model_order
    if frame==FRAME_COUNT-1:return [MODEL_OFFSET+i for i in model_order(INTRO_NEXT_FRAME-1)]
    ids=[i for i,group in enumerate(groups()) if visible(frame,group)]
    return ordered(scene(),groups(),[matrix(frame,g) for g in range(GROUP_COUNT)],ids,('intro',frame))


def generate():
    from verify_vertex_lab import render,to_image
    from PIL import Image
    output=ROOT/'docs/images/midiyas_logo';output.mkdir(parents=True,exist_ok=True)
    assets=ROOT/'assets/midiyas_logo';assets.mkdir(parents=True,exist_ok=True)
    triangles=scene();images=[];counts=[];points=[]
    for frame in range(FRAME_COUNT):
        ids=order(frame);counts.append(len(ids))
        projected=[(triangles[i][0],[project(v,matrix(frame,groups()[i]))[0] for v in triangles[i][0]],triangles[i][2]) for i in ids]
        points.extend(p for _,pixels,_ in projected for p in pixels)
        native=[(v,[(x//2,y//2) for x,y in p],c) for v,p,c in projected]
        images.append(to_image(render(native,320,240)).resize((640,480),Image.Resampling.NEAREST))
    images[240].save(output/'preview.png');images[110].save(output/'turned.png')
    duration=[round((i+1)*1.6672)*10-round(i*1.6672)*10 for i in range(FRAME_COUNT)]
    images[0].save(output/'animation.gif',save_all=True,append_images=images[1:],duration=duration,loop=0,disposal=2)
    storyboard=Image.new('RGB',(1280,960))
    for k,frame in enumerate((110,240,350,402)):storyboard.paste(images[frame],((k%2)*640,(k//2)*480))
    storyboard.save(output/'storyboard.png')
    from orbit_scene import scene as model_scene,matrix as orbit_matrix,project as orbit_project,order as orbit_order,groups as model_groups,FRAME_COUNT as MODEL_FRAMES
    model=model_scene();continuation=[]
    for frame in range(INTRO_NEXT_FRAME,INTRO_NEXT_FRAME+64):
        native=[(model[i][0],[(x//2,y//2) for x,y in [orbit_project(v,orbit_matrix(frame%MODEL_FRAMES,model_groups()[i]))[0] for v in model[i][0]]],model[i][2]) for i in orbit_order(frame%MODEL_FRAMES)]
        continuation.append(to_image(render(native,320,240)).resize((640,480),Image.Resampling.NEAREST))
    combined=images+continuation
    duration=[round((i+1)*1.6672)*10-round(i*1.6672)*10 for i in range(len(combined))]
    combined[0].save(output/'boot_preview.gif',save_all=True,append_images=combined[1:],duration=duration,loop=0,disposal=2)
    data=dict(name='MIDIYAS GPU / PRISM CORE',triangles=len(triangles),logo_triangles=MODEL_OFFSET,frames=FRAME_COUNT,groups=GROUP_COUNT,duration_ms=7000,model_start=MODEL_START,next_model_frame=INTRO_NEXT_FRAME,visible_min=min(counts),visible_max=max(counts),bounds=[np.min(points,axis=0).tolist(),np.max(points,axis=0).tolist()],counts=counts)
    (assets/'metadata.json').write_text(json.dumps(data,indent=2))
    (assets/'mesh.json').write_text(json.dumps([dict(vertices=verts,colors=colors,group=group) for (verts,_,colors),group in zip(triangles,groups())]))
    print(json.dumps({k:v for k,v in data.items() if k!='counts'}))


if __name__=='__main__':generate()
