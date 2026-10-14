from functools import lru_cache
import math
import numpy as np

Q=4096
FRAME_COUNT=512
GROUP_COUNT=9
NAME='MECHANICAL CORE'


def rgb(r,g,b):
    return (round(max(0,min(255,r))*7/255)<<5)|(round(max(0,min(255,g))*7/255)<<2)|round(max(0,min(255,b))*3/255)


def smooth(t):
    t=max(0,min(1,t));return t*t*t*(10-15*t+6*t*t)


def rotations(x,y,z):
    sx,cx=math.sin(x),math.cos(x);sy,cy=math.sin(y),math.cos(y);sz,cz=math.sin(z),math.cos(z)
    return np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])@np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])@np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])


@lru_cache(maxsize=1)
def geometry():
    faces=[];group_ids=[]
    def face(points,colors,group,direction=None):
        points=[np.array(p,dtype=float) for p in points]
        if isinstance(colors,int):colors=[colors]*3
        if direction is not None and np.dot(np.cross(points[1]-points[0],points[2]-points[0]),direction)<0:
            points.reverse();colors=list(reversed(colors))
        faces.append(([tuple(round(float(c)*Q) for c in p) for p in points],list(colors)));group_ids.append(group)
    def quad(points,colors,group,direction):
        if isinstance(colors,int):colors=[colors]*4
        for ids in [(0,1,2),(0,2,3)]:face([points[j] for j in ids],[colors[j] for j in ids],group,direction)
    for group in range(6):
        theta=group*math.pi/3
        levels=[(-1.12,.34,.24),(0.,1.15,.98),(1.12,.34,.24)]
        shell=[]
        for y,r,inner in levels:
            shell.append([[(radius*math.cos(a),y,radius*math.sin(a)) for a in (theta-.46,theta+.46)] for radius in (r,inner)])
        for j in range(2):
            points=[shell[j][0][0],shell[j][0][1],shell[j+1][0][1],shell[j+1][0][0]]
            palette=[rgb(0,109,182),rgb(0,182,219),rgb(219,255,255),rgb(146,219,255)] if j else [rgb(0,73,146),rgb(0,109,182),rgb(36,182,255),rgb(146,219,255)]
            quad(points,palette,group,np.mean(points,axis=0))
            points=[shell[j][1][0],shell[j][1][1],shell[j+1][1][1],shell[j+1][1][0]]
            quad(points,rgb(0,36,85),group,-np.mean(points,axis=0))
            for side,sign in [(0,-1),(1,1)]:
                a=theta+sign*.46
                points=[shell[j][0][side],shell[j][1][side],shell[j+1][1][side],shell[j+1][0][side]]
                quad(points,rgb(36,182,219) if side else rgb(0,73,146),group,[sign*-math.sin(a),0,sign*math.cos(a)])
        for j,sign in [(0,-1),(2,1)]:
            points=[shell[j][0][0],shell[j][0][1],shell[j][1][1],shell[j][1][0]]
            quad(points,rgb(182,219,255) if sign>0 else rgb(0,73,146),group,[0,sign,0])
    upper=[];lower=[]
    for j in range(6):
        a=j*math.pi/3
        upper.append((.54*math.cos(a),.20,.54*math.sin(a)))
        lower.append((.48*math.cos(a),-.20,.48*math.sin(a)))
    for j in range(6):
        k=(j+1)%6
        for points,colors in [
            ([(0,.79,0),upper[j],upper[k]],[rgb(255,255,170),rgb(255,219,85),rgb(255,146,0)]),
            ([upper[j],lower[j],lower[k]],[rgb(255,219,85),rgb(219,109,0),rgb(255,146,0)]),
            ([upper[j],lower[k],upper[k]],[rgb(255,219,85),rgb(255,146,0),rgb(255,182,0)]),
            ([(0,-.79,0),lower[k],lower[j]],[rgb(146,73,0),rgb(255,146,0),rgb(255,219,85)])]:
            face(points,colors,6,np.mean(points,axis=0))
    for group,radius,width,palette in [(7,2.62,.18,(0,219,255)),(8,2.98,.14,(146,109,255))]:
        for j in range(24):
            if j in (5,11,17,23):continue
            a=j*2*math.pi/24;b=(j+1)*2*math.pi/24
            points=[(r*math.cos(t),r*math.sin(t),0.) for r,t in [(radius-width/2,a),(radius+width/2,a),(radius+width/2,b),(radius-width/2,b)]]
            colors=[rgb(*(c*g for c in palette)) for g in (.42,1.,1.,.42)]
            quad(points,colors,group,[0,0,-1]);quad(points,colors,group,[0,0,1])
    return faces,group_ids


def mesh():return geometry()[0]


def groups():return geometry()[1]


def visible(frame,group):return True


def raw_matrix(frame,group=0):
    u=(frame%FRAME_COUNT)/FRAME_COUNT;phase=2*math.pi*u
    opening=smooth((u-.07)/.24)*(1-smooth((u-.72)/.23))
    model=np.eye(4)
    if group<6:
        theta=group*math.pi/3;spread=.98*opening
        spin=.16*math.sin(phase)
        rotation=rotations(0,spin,0)
        model[:3,:3]=rotation
        model[:3,3]=rotation@np.array([spread*math.cos(theta),0.,spread*math.sin(theta)])
    elif group==6:
        model[:3,:3]=rotations(.14*math.sin(phase),phase*2,-phase)*(.88+.12*opening)
    elif group==7:
        model[:3,:3]=rotations(.84+.10*math.sin(phase),.25,phase)
    elif group==8:
        model[:3,:3]=rotations(-.68,.55+.12*math.sin(phase),-phase)
    view=np.eye(4)
    view[:3,:3]=rotations(.22+.10*math.sin(phase),phase+.34,.04*math.sin(phase))
    view[:3,3]=[0,0,8.3-.4*opening]
    projection=np.array([[1.5,0,0,0],[0,2.,0,0],[0,0,21/19,-40/19],[0,0,1,0]])
    values=[round(float(v)*Q) for v in (projection@view@model).flatten(order='F')]
    assert all(-131072<=v<=131071 for v in values)
    return values


def matrix(frame,group=0):return raw_matrix(frame,group)


def project(v,m):
    clip=[(sum(v[j]*m[j*4+i] for j in range(3))+m[12+i]*Q)>>12 for i in range(4)]
    assert clip[3]>0 and all(-131072<=c<=131071 for c in clip)
    ndc=[(abs(c)*Q//clip[3])*(-1 if c<0 else 1) for c in clip[:3]]
    p=((ndc[0]+Q)*320>>12,(Q-ndc[1])*240>>12)
    assert 0<=p[0]<640 and 0<=p[1]<480 and -Q<=ndc[2]<=Q,(p,ndc)
    return p,Q/clip[3]


@lru_cache(maxsize=1)
def scene():
    return [(verts,[project(v,raw_matrix(0,group))[0] for v in verts],colors) for (verts,colors),group in zip(mesh(),groups())]

