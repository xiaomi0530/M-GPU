import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'assets/milkfrog/v1_fixed/animation'
PREVIEW = ROOT / 'out/naiwa/animation'
GROUP_NAMES = ['torso', 'head', 'upper_arm_negative_y', 'forearm_hand_negative_y',
               'upper_arm_positive_y', 'forearm_hand_positive_y', 'thigh_negative_y',
               'calf_foot_negative_y', 'thigh_positive_y', 'calf_foot_positive_y',
               'lower_jaw', 'eye_negative_y', 'eye_positive_y', 'mouth_interior',
               'eyelid_arcs', 'neck_connector', 'foot_negative_y', 'foot_positive_y']


def smooth(x):
    x = np.clip(x, 0, 1)
    return x*x*(3-2*x)


def track(frame, points):
    keys = np.asarray(points, dtype=float)
    i = int(np.clip(np.searchsorted(keys[:, 0], frame)-1, 0, len(keys)-2))
    u = smooth((frame-keys[i, 0])/(keys[i+1, 0]-keys[i, 0]))
    return keys[i, 1:]*(1-u)+keys[i+1, 1:]*u


def rotation(axis, degrees):
    axis = np.asarray(axis, dtype=float); axis /= np.linalg.norm(axis)
    x,y,z = axis; a = math.radians(float(degrees)); c,s = math.cos(a),math.sin(a)
    skew = np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
    return c*np.eye(3)+(1-c)*np.outer(axis,axis)+s*skew


def affine(rot=None, translation=None):
    m=np.eye(4)
    if rot is not None:m[:3,:3]=rot
    if translation is not None:m[:3,3]=translation
    return m


def pivot_rotation(pivot, axis, degrees):
    p=np.asarray(pivot);r=rotation(axis,degrees)
    return affine(r,p-r@p)


def align_vectors(a,b):
    a=np.asarray(a,float);b=np.asarray(b,float);a/=np.linalg.norm(a);b/=np.linalg.norm(b)
    cross=np.cross(a,b);c=float(np.clip(a@b,-1,1))
    if np.linalg.norm(cross)<1e-8:return np.eye(3) if c>0 else rotation([0,0,1],180)
    return rotation(cross,math.degrees(math.acos(c)))


def segment_transform(rest_start,rest_end,new_start,new_end):
    a,b,c,d=map(lambda x:np.asarray(x,float),(rest_start,rest_end,new_start,new_end))
    r=align_vectors(b-a,d-c)
    return affine(r,c-r@a)


def point_segment_distance(p,a,b):
    d=b-a;t=np.clip(((p-a)@d)/(d@d),0,1)
    return np.linalg.norm(p-a-t[:,None]*d,axis=1)


def texture_colors(uv):
    from PIL import Image
    image=np.asarray(Image.open(ROOT/'assets/naiwa/candidates/source_basecolor.jpg').convert('RGB'),dtype=float)
    h,w=image.shape[:2];u=np.mod(uv[...,0],1)*(w-1);v=(1-np.mod(uv[...,1],1))*(h-1)
    x=np.floor(u).astype(int);y=np.floor(v).astype(int);dx=u-x;dy=v-y
    x1=np.minimum(x+1,w-1);y1=np.minimum(y+1,h-1)
    return np.clip(np.rint(image[y,x]*(1-dx)[...,None]*(1-dy)[...,None]+image[y,x1]*dx[...,None]*(1-dy)[...,None]+image[y1,x]*(1-dx)[...,None]*dy[...,None]+image[y1,x1]*dx[...,None]*dy[...,None]),0,255).astype(np.uint8)


class Mesh:
    def __init__(self,vertices,faces,colors,groups):
        self.vertices=vertices.tolist();self.faces=faces.tolist();self.colors=colors.tolist();self.groups=groups.tolist()

    def add(self,vertices,faces,color,group):
        offset=len(self.vertices);self.vertices.extend(np.asarray(vertices).tolist())
        self.faces.extend((np.asarray(faces)+offset).tolist())
        color=np.asarray(color,float)
        if color.ndim==1:color=np.tile(color,(len(faces),3,1))
        self.colors.extend(np.clip(color,0,255).astype(np.uint8).tolist());self.groups.extend([group]*len(faces))

    def sphere(self,center,scale,color,group,sides=8,rings=4):
        vertices=[];faces=[]
        for k in range(rings+1):
            phi=np.pi*k/rings
            for j in range(sides):
                a=2*np.pi*j/sides
                vertices.append(np.asarray(center)+np.asarray(scale)*[np.cos(phi),np.sin(phi)*np.cos(a),np.sin(phi)*np.sin(a)])
        for k in range(rings):
            for j in range(sides):
                a=k*sides+j;b=k*sides+(j+1)%sides
                if k>0:faces.append([a,b,a+sides])
                if k<rings-1:faces.append([b,b+sides,a+sides])
        vertices=np.asarray(vertices);faces=np.asarray(faces)
        n=np.cross(vertices[faces[:,1]]-vertices[faces[:,0]],vertices[faces[:,2]]-vertices[faces[:,0]])
        flip=(n*(vertices[faces].mean(1)-center)).sum(1)<0;faces[flip]=faces[flip,::-1]
        self.add(vertices,faces,color,group)

    def box(self,center,size,color,group):
        vertices=np.array([[x,y,z] for x in [-1,1] for y in [-1,1] for z in [-1,1]])*np.asarray(size)*.5+center
        faces=np.array([[0,1,3],[0,3,2],[4,6,7],[4,7,5],[0,4,5],[0,5,1],[2,3,7],[2,7,6],[0,2,6],[0,6,4],[1,5,7],[1,7,3]])
        self.add(vertices,faces,color,group)


def close_group_boundaries(mesh,vertices,faces,colors,groups):
    vertex_color=np.zeros((len(vertices),3));counts=np.zeros(len(vertices))
    for j in range(3):
        np.add.at(vertex_color,faces[:,j],colors[:,j]);np.add.at(counts,faces[:,j],1)
    vertex_color/=np.maximum(counts,1)[:,None]
    for group in range(1,13):
        tri=faces[groups==group]
        if not len(tri):continue
        edges=np.concatenate([tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]])
        _,inverse,count=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
        boundary=edges[count[inverse]==1]
        remaining=set(map(tuple,boundary.tolist()));adj={}
        for a,b in remaining:adj.setdefault(a,[]).append(b)
        while remaining:
            a,b=next(iter(remaining));remaining.remove((a,b));loop=[a,b]
            while loop[-1]!=loop[0]:
                options=[n for n in adj.get(loop[-1],[]) if (loop[-1],n) in remaining]
                if not options:break
                n=options[0];remaining.remove((loop[-1],n));loop.append(n)
            if loop[-1]!=loop[0] or len(loop)<4:continue
            loop=loop[:-1];points=vertices[loop];center=points.mean(axis=0)
            colors_at_edge=vertex_color[loop].copy()
            center_color=colors_at_edge.mean(axis=0)
            out=np.vstack([points,center]);new_faces=[];new_colors=[]
            for i in range(len(loop)):
                j=(i+1)%len(loop);new_faces.append([j,i,len(loop)])
                new_colors.append([colors_at_edge[j],colors_at_edge[i],center_color])
            mesh.add(out,new_faces,new_colors,group)


def underlying_torso(mesh,vertices,faces,colors,groups):
    from scipy.spatial import cKDTree
    samples=vertices[faces[groups==0]].reshape(-1,3)
    rgb=colors[groups==0].reshape(-1,3).astype(float)
    contact=(samples[:,0]>.10)&(np.abs(samples[:,1])>.065)&(samples[:,2]>-.095)&(samples[:,2]<.145)
    valid=(rgb[:,0]>165)&(rgb[:,1]>120)&(~contact)
    tree=cKDTree(samples[valid]);source_rgb=rgb[valid]
    source_faces=np.load(ROOT/'assets/naiwa/candidates/B/mesh.npz')['faces']
    tri=vertices[source_faces];vertices_new=[];colors_new=[];new_faces=[];sides=40
    zs=np.linspace(-.239,.255,30)
    for z in zs:
        crossing=tri[(tri[:,:,2].min(1)<z)&(tri[:,:,2].max(1)>z)]
        segments=[]
        for t in crossing:
            pts=[]
            for i,j in [(0,1),(1,2),(2,0)]:
                if (t[i,2]-z)*(t[j,2]-z)<0:
                    u=(z-t[i,2])/(t[j,2]-t[i,2]);pts.append(t[i,:2]+u*(t[j,:2]-t[i,:2]))
            if len(pts)==2:segments.append(pts)
        segments=np.asarray(segments);a=segments[:,0];e=segments[:,1]-a
        hit=(a[:,1]*(a[:,1]+e[:,1])<=0)&(np.abs(e[:,1])>1e-10)
        xx=a[hit,0]-a[hit,1]*e[hit,0]/e[hit,1]
        center=np.array([(xx.min()+xx.max())*.5,0.])
        radius_x=(xx.max()-xx.min())*.5
        back_slice=segments.reshape(-1,2)
        back_slice=back_slice[back_slice[:,0]<center[0]]
        radius_y=np.max(np.abs(back_slice[:,1]))
        for j in range(sides):
            theta=2*np.pi*j/sides;d=np.array([np.cos(theta),np.sin(theta)])
            den=d[0]*e[:,1]-d[1]*e[:,0];q=a-center
            good=np.abs(den)>1e-10
            ray=np.full(len(a),np.inf);along=np.full(len(a),-1.)
            ray[good]=(q[good,0]*e[good,1]-q[good,1]*e[good,0])/den[good]
            along[good]=(q[good,0]*d[1]-q[good,1]*d[0])/den[good]
            ok=good&(ray>0)&(along>=0)&(along<=1)
            if not np.any(ok):raise RuntimeError(f'No source radial surface at z={z}, angle={theta}')
            radius=ray[ok].min()*.995
            ellipse_radius=1/np.sqrt((d[0]/radius_x)**2+(d[1]/radius_y)**2)
            radius=min(radius,ellipse_radius*.995)
            xy=center+radius*d
            back_points=crossing[crossing[:,:,0]<-.03]
            if len(back_points)>10 and -.07<z<.225:
                y_limit=np.max(np.abs(back_points[:,1]))*.985
                if abs(xy[1])>y_limit:
                    xy=center+(xy-center)*(y_limit/abs(xy[1]))
            p=np.array([xy[0],xy[1],z]);vertices_new.append(p)
            distances,ids=tree.query(p,k=36);weight=1/np.maximum(distances,.015)**2;col=(source_rgb[ids]*weight[:,None]).sum(0)/weight.sum()
            colors_new.append(col)
    for k in range(len(zs)-1):
        for j in range(sides):
            a=k*sides+j;b=k*sides+(j+1)%sides;new_faces.extend([[a,b,b+sides],[a,b+sides,a+sides]])
    vertices_new=np.asarray(vertices_new);new_faces=np.asarray(new_faces);colors_new=np.asarray(colors_new)
    mesh.add(vertices_new,new_faces,colors_new[new_faces],0)
    for k in [0,len(zs)-1]:
        ring=vertices_new[k*sides:(k+1)*sides];center=ring.mean(0)
        cap_faces=np.array([[j,(j+1)%sides,sides] for j in range(sides)])
        if k==0:cap_faces=cap_faces[:,::-1]
        cap_colors=np.vstack((colors_new[k*sides:(k+1)*sides],colors_new[k*sides:(k+1)*sides].mean(0)))
        mesh.add(np.vstack((ring,center)),cap_faces,cap_colors[cap_faces],0)


def limb_tube(mesh,start,end,radii,group,source_vertices,source_faces,source_colors):
    from scipy.spatial import cKDTree
    start=np.asarray(start);end=np.asarray(end);axis=end-start;axis/=np.linalg.norm(axis)
    u=np.cross(axis,[1.,0.,0.])
    if np.linalg.norm(u)<.1:u=np.cross(axis,[0.,1.,0.])
    u/=np.linalg.norm(u);v=np.cross(axis,u)
    vertices=[];colors=[];faces=[];sides=12;rings=7
    triangles=source_vertices[source_faces];p0=triangles[:,0];e1=triangles[:,1]-p0;e2=triangles[:,2]-p0
    sample_points=triangles.reshape(-1,3);sample_colors=source_colors.reshape(-1,3).astype(float)
    clean=(sample_colors[:,0]>165)&(sample_colors[:,1]>115)
    color_tree=cKDTree(sample_points[clean]);sample_colors=sample_colors[clean]
    for k,t in enumerate(np.linspace(0,1,rings)):
        radius=np.interp(t,np.linspace(0,1,len(radii)),radii)
        center=start*(1-t)+end*t
        if group in [3,5]:center[2]+=.020*np.sin(np.pi*t)
        for j in range(sides):
            a=2*np.pi*j/sides;n=np.cos(a)*u+np.sin(a)*v
            h=np.cross(np.tile(n,(len(p0),1)),e2);det=(e1*h).sum(1);valid=np.abs(det)>1e-10
            inverse=np.zeros(len(p0));inverse[valid]=1/det[valid];q=center-p0
            b=inverse*(q*h).sum(1);cross=np.cross(q,e1);c=inverse*(cross*n).sum(1);ray=inverse*(e2*cross).sum(1)
            hit=valid&(b>=0)&(c>=0)&(b+c<=1)&(ray>1e-4)
            measured=min(radius,ray[hit].min()*.995) if hit.any() else radius
            p=center+max(.012,measured)*n;vertices.append(p)
            dist,ids=color_tree.query(p,k=16);weight=1/np.maximum(dist,.012)**2
            colors.append((sample_colors[ids]*weight[:,None]).sum(0)/weight.sum())
        angles=np.arange(sides)*2*np.pi/sides
        features=np.column_stack([np.ones(sides),np.cos(angles),np.sin(angles),np.cos(2*angles),np.sin(2*angles)])
        measured=np.linalg.norm(np.asarray(vertices[-sides:])-center,axis=1)
        fitted=np.clip(features@np.linalg.lstsq(features,measured,rcond=None)[0],.012,radius)
        for j,a in enumerate(angles):
            n=np.cos(a)*u+np.sin(a)*v;p=center+fitted[j]*n;vertices[-sides+j]=p
            dist,ids=color_tree.query(p,k=16);weight=1/np.maximum(dist,.012)**2
            colors[-sides+j]=(sample_colors[ids]*weight[:,None]).sum(0)/weight.sum()
    for k in range(rings-1):
        for j in range(sides):
            a=k*sides+j;b=k*sides+(j+1)%sides;faces.extend([[a,b,b+sides],[a,b+sides,a+sides]])
    for k,center in [(0,start),(rings-1,end)]:
        index=len(vertices);vertices.append(center);colors.append([225,176,39])
        for j in range(sides):
            a=k*sides+j;b=k*sides+(j+1)%sides;faces.append([index,b,a] if k==0 else [index,a,b])
    vertices=np.asarray(vertices);faces=np.asarray(faces);colors=np.asarray(colors)
    mesh.add(vertices,faces,colors[faces],group)


def clipped_source_hands(mesh,vertices,faces,colors):
    points=[];out_faces=[];out_colors=[];out_groups=[];lookup={}
    for face,face_colors in zip(faces,colors):
        p=vertices[face];center=p.mean(0)
        if not (center[0]>.13 and -.075<center[2]<.115 and abs(center[1])>.025):continue
        scalar=np.minimum(170-face_colors[:,0].astype(float),130-face_colors[:,1].astype(float))
        if scalar.max()<0:continue
        poly=[(p[i],face_colors[i].astype(float),scalar[i]) for i in range(3)]
        clipped=[]
        for i in range(3):
            a=poly[i];b=poly[(i+1)%3]
            if a[2]>=0:clipped.append(a)
            if (a[2]>=0)!=(b[2]>=0):
                t=a[2]/(a[2]-b[2]);clipped.append((a[0]*(1-t)+b[0]*t,a[1]*(1-t)+b[1]*t,0.))
        if len(clipped)<3:continue
        indices=[]
        for pos,col,_ in clipped:
            key=tuple(np.round(pos,7))
            if key not in lookup:lookup[key]=len(points);points.append(pos)
            indices.append(lookup[key])
        for j in range(1,len(indices)-1):
            out_faces.append([indices[0],indices[j],indices[j+1]])
            out_colors.append([clipped[0][1],clipped[j][1],clipped[j+1][1]])
            out_groups.append(3 if center[1]<0 else 5)
    points=np.asarray(points);out_faces=np.asarray(out_faces);out_colors=np.asarray(out_colors);out_groups=np.asarray(out_groups)
    for group in [3,5]:
        mask=out_groups==group;mesh.add(points,out_faces[mask],out_colors[mask],group)
    close_group_boundaries(mesh,points,out_faces,out_colors,out_groups)


def eye_skin_patch(mesh,vertices,faces,colors,side):
    from scipy.spatial import cKDTree
    p=vertices[faces].reshape(-1,3);rgb=colors.reshape(-1,3)
    cy=side*.059;cz=.425
    dist=((p[:,1]-cy)/.022)**2+((p[:,2]-cz)/.025)**2
    valid=(p[:,0]>.02)&(dist>2.0)&(dist<5.5)&(rgb[:,0]>190)&(rgb[:,1]>140)&(rgb[:,0]>rgb[:,1]*1.1)
    sampled=p[valid];sample_rgb=rgb[valid]
    def features(y,z):
        y=(np.asarray(y)-cy)*30;z=(np.asarray(z)-cz)*30
        return np.column_stack((np.ones_like(y),y,z,y*y,y*z,z*z))
    fit=np.linalg.lstsq(features(sampled[:,1],sampled[:,2]),sampled[:,0],rcond=None)[0]
    tree=cKDTree(sampled)
    verts=[];cs=[];fs=[];count=12;rings=4
    for k in range(rings):
        r=max(.001,k/(rings-1))
        for j in range(count):
            a=2*np.pi*j/count;y=cy+.039*r*np.cos(a);z=cz+.043*r*np.sin(a)
            x=float(np.clip(features([y],[z])[0]@fit,.035,.105))
            v=np.array([x,y,z]);verts.append(v)
            _,ids=tree.query(v,k=8);cs.append(sample_rgb[ids].mean(0))
    for k in range(rings-1):
        for j in range(count):
            a=k*count+j;b=k*count+(j+1)%count;fs.extend([[a,a+count,b+count],[a,b+count,b]])
    verts=np.asarray(verts);fs=np.asarray(fs);cs=np.asarray(cs)
    cross=np.cross(verts[fs[:,1]]-verts[fs[:,0]],verts[fs[:,2]]-verts[fs[:,0]]);fs[cross[:,0]<0]=fs[cross[:,0]<0,::-1]
    mesh.add(verts,fs,cs[fs],1)
    pts=[];fs=[]
    for k in range(7):
        u=-1+k/3;y=cy+u*.027;z=cz+.009*(1-u*u);x=float(np.clip(features([y],[z])[0]@fit,.035,.105))+.015
        pts.extend([[x,y,z-.0022],[x,y,z+.0022]])
        if k<6:fs.extend([[2*k,2*k+2,2*k+3],[2*k,2*k+3,2*k+1]])
    mesh.add(pts,fs,[58,46,20],14)


def split_ankle_geometry(geometry, cut_z=-.430):
    """Split the source surface at each ankle without moving its vertices."""
    mesh=Mesh(np.empty((0,3)),np.empty((0,3),int),np.empty((0,3,3)),np.empty(0,int))
    boundary={7:[],9:[]}
    for face,color,group in zip(geometry['faces'],geometry['colors'],geometry['groups']):
        points=geometry['vertices'][face].astype(float);color=color.astype(float)
        if group not in (7,9):
            mesh.add(points,[[0,1,2]],color[None],int(group));continue
        for below in (False,True):
            clipped=[]
            for i in range(3):
                j=(i+1)%3;p,c=points[i],color[i];q,d=points[j],color[j]
                pin=p[2]<=cut_z if below else p[2]>=cut_z
                qin=q[2]<=cut_z if below else q[2]>=cut_z
                if pin:clipped.append((p,c))
                if pin!=qin:
                    t=(cut_z-p[2])/(q[2]-p[2]);v=p+t*(q-p);rgb=c+t*(d-c)
                    clipped.append((v,rgb));boundary[int(group)].append((v,rgb))
            if len(clipped)<3:continue
            p=np.array([x[0] for x in clipped]);c=np.array([x[1] for x in clipped])
            faces=np.array([[0,k,k+1] for k in range(1,len(p)-1)])
            mesh.add(p,faces,c[faces],16 if group==7 and below else 17 if below else int(group))
    for calf,items in boundary.items():
        unique={tuple(np.round(p,8)):(p,c) for p,c in items};p=np.array([v[0] for v in unique.values()]);c=np.array([v[1] for v in unique.values()])
        center=p.mean(0);order=np.argsort(np.arctan2(p[:,1]-center[1],p[:,0]-center[0]));p=p[order];c=c[order]
        vertices=np.vstack([p,center]);colors=np.vstack([c,c.mean(0)])
        faces=np.array([[k,(k+1)%len(p),len(p)] for k in range(len(p))])
        mesh.add(vertices,faces,colors[faces],16 if calf==7 else 17)
        mesh.add(vertices,faces[:,::-1],colors[faces[:,::-1]],calf)
    result=dict(vertices=np.asarray(mesh.vertices,np.float32),faces=np.asarray(mesh.faces,np.int32),colors=np.asarray(mesh.colors,np.uint8),groups=np.asarray(mesh.groups,np.uint8))
    _,first,inverse=np.unique(np.round(result['vertices'],7),axis=0,return_index=True,return_inverse=True)
    result['vertices']=result['vertices'][first];result['faces']=inverse[result['faces']].astype(np.int32)
    p=result['vertices'][result['faces']];valid=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)>1e-10
    for name in ['faces','colors','groups']:result[name]=result[name][valid]
    return result


def build_geometry():
    data=np.load(ROOT/'assets/naiwa/candidates/B/mesh.npz')
    vertices=data['vertices'].astype(float);faces=data['faces'];colors=texture_colors(data['uv'])
    centroids=vertices[faces].mean(axis=1);rgb=colors.mean(1)
    x,y,z=centroids.T;groups=np.zeros(len(faces),np.uint8)
    groups[z>.255]=1
    joints={}
    for side,upper,lower,thigh,calf in [(-1,2,3,6,7),(1,4,5,8,9)]:
        shoulder=np.array([-.016,side*.160,.178]);elbow=np.array([.112,side*.242,.026]);wrist=np.array([.222,side*.142,.009])
        hip=np.array([-.018,side*.136,-.225]);knee=np.array([-.025,side*.157,-.347]);ankle=np.array([-.0567979,-.11905167,-.430]) if side<0 else np.array([-.05808536,.1229324,-.430])
        joints[str(side)]=dict(shoulder=shoulder.tolist(),elbow=elbow.tolist(),wrist=wrist.tolist(),hip=hip.tolist(),knee=knee.tolist(),ankle=ankle.tolist())
        region=(side*y>.026)&(z>-.075)&(z<.235)&(x>.00)
        da=point_segment_distance(centroids,shoulder,elbow);db=point_segment_distance(centroids,elbow,wrist)
        upper_mask=region&(da<.075)&(da<=db)&(np.abs(y)>.12)
        dark=(rgb[:,0]<165)&(rgb[:,1]<130)&(rgb[:,2]<90)&(z>-.06)&(z<.105)&(x>.13)&(side*y>.025)
        lower_mask=region&(((db<.071)&(x>.095)&(np.abs(y)>.09))|dark)
        groups[upper_mask]=upper;groups[lower_mask]=lower
        leg=(side*y>.055)&(z<-.235)
        groups[leg&(z>=-.352)]=thigh;groups[leg&(z<-.352)]=calf
    jaw=(x>.060)&(np.abs(y)<.090)&(z>.255)&(z<.3815)
    groups[jaw]=10
    for side,group in [(-1,11),(1,12)]:
        eye=(x>.040)&(((y-side*.059)/.037)**2+((z-.425)/.041)**2<1.0)
        groups[eye]=group
    minimum_color=colors.min(axis=1)
    hands=(x>.14)&(z>-.06)&(z<.105)&(np.abs(y)>.025)&(minimum_color[:,0]<150)&(minimum_color[:,1]<120)&(rgb[:,0]<185)&(rgb[:,1]<150)
    arm_zone=((np.abs(y)>.13)&(z>-.07)&(z<.225)&(x>-.06))|np.isin(groups,[2,3,4,5])
    groups[hands&(y<0)]=3;groups[hands&(y>=0)]=5
    keep=(~arm_zone)&(~hands)
    residue=(groups==0)&(x>.12)&(z>-.085)&(z<.11)&(minimum_color[:,0]<175)&(minimum_color[:,1]<140)
    colors[residue]=np.array([224,205,150],np.uint8)
    faces=faces[keep];colors=colors[keep];groups=groups[keep]
    mesh=Mesh(vertices,faces,colors,groups)
    original_count=len(faces)
    close_group_boundaries(mesh,vertices,faces,colors,groups)
    underlying_torso(mesh,vertices,faces,colors,groups)
    keep_surface=np.ones(len(mesh.faces),dtype=bool)
    keep_surface[:original_count]=groups!=0
    mesh.faces=np.asarray(mesh.faces)[keep_surface].tolist()
    mesh.colors=np.asarray(mesh.colors)[keep_surface].tolist()
    mesh.groups=np.asarray(mesh.groups)[keep_surface].tolist()
    original_colors=texture_colors(data['uv'])
    clipped_source_hands(mesh,vertices,data['faces'],original_colors)
    for side,upper,lower in [(-1,2,3),(1,4,5)]:
        p=joints[str(side)]
        limb_tube(mesh,p['shoulder'],p['elbow'],[.069,.082,.078,.068],upper,vertices,data['faces'],original_colors)
        limb_tube(mesh,p['elbow'],p['wrist'],[.074,.068,.057,.040],lower,vertices,data['faces'],original_colors)
        mesh.sphere(p['elbow'],[.060,.060,.060],[232,181,43],upper,sides=8,rings=3)
    from milkfrog_expression import mouth_geometry, neck_geometry
    neck_geometry(mesh, vertices, data['faces'], original_colors)
    mouth_geometry(mesh, vertices, data['faces'])
    for side in [-1,1]:
        eye_skin_patch(mesh,vertices,faces,colors,side)
    result=dict(vertices=np.asarray(mesh.vertices,np.float32),faces=np.asarray(mesh.faces,np.int32),colors=np.asarray(mesh.colors,np.uint8),groups=np.asarray(mesh.groups,np.uint8))
    _,first,inverse=np.unique(np.round(result['vertices'],7),axis=0,return_index=True,return_inverse=True)
    result['vertices']=result['vertices'][first];result['faces']=inverse[result['faces']].astype(np.int32)
    p=result['vertices'][result['faces']]
    valid=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)>1e-10
    for key in ['faces','colors','groups']:result[key]=result[key][valid]
    used,inverse=np.unique(result['faces'],return_inverse=True)
    result['vertices']=result['vertices'][used];result['faces']=inverse.reshape(-1,3).astype(np.int32)
    result=split_ankle_geometry(result)
    assert len(result['faces'])<=10000,len(result['faces'])
    return result,joints


def arm_matrices(joints,side,raise_hands,reach,wobble,clasp=0):
    p=joints[str(side)];s,e,w=[np.asarray(p[k]) for k in ['shoulder','elbow','wrist']]
    if raise_hands<1e-6 and reach<1e-6 and abs(wobble)<1e-6 and clasp<1e-6:return np.eye(4),np.eye(4)
    target=w*(1-raise_hands)+np.array([.125,side*.085-.025,.472-(.025 if side<0 else 0)])*raise_hands
    target+=np.array([reach*.12,side*reach*.025,wobble])
    target+=np.array([.015,-side*.075,-.015])*clasp
    l1=np.linalg.norm(e-s);l2=np.linalg.norm(w-e);d=target-s;length=np.linalg.norm(d);d/=length
    length=np.clip(length,abs(l1-l2)+.001,l1+l2-.002);target=s+d*length
    along=(l1*l1-l2*l2+length*length)/(2*length)
    rest_axis=w-s;rest_axis/=np.linalg.norm(rest_axis)
    rest_pole=e-s-rest_axis*((e-s)@rest_axis);rest_pole/=np.linalg.norm(rest_pole)
    raised_pole=np.array([.3,side*1.,.12]);raised_pole/=np.linalg.norm(raised_pole)
    outward=rest_pole*(1-raise_hands)+raised_pole*raise_hands
    outward-=d*(outward@d);outward/=np.linalg.norm(outward)
    middle=s+along*d+math.sqrt(max(1e-9,l1*l1-along*along))*outward
    return segment_transform(s,e,s,middle),segment_transform(e,w,middle,target)


def fitted_fall_rotation(matrices,geometry,joints,basis,parameters,amount):
    m=matrices.copy();p=parameters
    local_head=rotation([0,0,1],p['head_local_z_deg']*amount)@rotation([0,1,0],p['head_local_y_deg']*amount)
    head_rotation=m[1,:3,:3]@local_head@m[1,:3,:3].T
    neck=m[1,:3,:3]@np.array([.008,0,.255])+m[1,:3,3]
    head_delta=affine(head_rotation,neck-head_rotation@neck)
    head_groups=[1,10,11,12,13,14];m[head_groups]=head_delta@m[head_groups]
    angle=math.acos(float(np.clip((np.trace(head_rotation)-1)/2,-1,1)))
    axis=np.array([head_rotation[2,1]-head_rotation[1,2],head_rotation[0,2]-head_rotation[2,0],head_rotation[1,0]-head_rotation[0,1]])
    if np.linalg.norm(axis)>1e-9:
        half=rotation(axis,math.degrees(angle)*.5);m[15]=affine(half,neck-half@neck)@m[15]
    for side,thigh,calf,name in [(-1,6,7,'negative_y'),(1,8,9,'positive_y')]:
        joint=joints[str(side)]
        knee=m[calf,:3,:3]@joint['knee']+m[calf,:3,3]
        hip=m[thigh,:3,:3]@joint['hip']+m[thigh,:3,3];axis=m[thigh,:3,1]
        kr=rotation(axis,p[name+'_knee_delta_deg']*amount);hr=rotation(axis,p[name+'_hip_delta_deg']*amount)
        m[calf]=affine(kr,knee-kr@knee)@m[calf]
        m[[thigh,calf]]=affine(hr,hip-hr@hip)@m[[thigh,calf]]
        m[16 if calf==7 else 17]=m[calf]
    camera_rotation=rotation([0,0,1],p['body_camera_z_deg']*amount)@rotation([0,1,0],p['body_camera_y_deg']*amount)@rotation([1,0,0],p['body_camera_x_deg']*amount)
    r=basis.T@camera_rotation@basis
    points=geometry['vertices'][geometry['faces']];world=np.einsum('tij,tkj->tki',m[geometry['groups'],:3,:3],points)+m[geometry['groups'],None,:3,3]
    pivot=(world.min((0,1))+world.max((0,1)))*.5
    return affine(r,pivot-r@pivot)@m


def constrain_fall_hands(matrices,geometry,joints,basis,camera,reference,frame,amount,positive_y_roll=0):
    m=matrices.copy();points=geometry['vertices'][geometry['faces']];groups=geometry['groups'];color=geometry['colors'].mean(1)
    scale=camera['pixels_per_unit'];translation=np.array([camera['translation_x_px'],camera['translation_y_px']])
    mapping=reference['display_mapping'];body=points[groups==0]@m[0,:3,:3].T+m[0,:3,3];body_camera=body@basis.T
    a=body_camera[:,0,:2];u=body_camera[:,1,:2]-a;v=body_camera[:,2,:2]-a;det=u[:,0]*v[:,1]-u[:,1]*v[:,0]
    for side,upper,lower,name in [(-1,2,3,'hand_lower'),(1,4,5,'hand_upper')]:
        samples=[]
        for key in reference['landmark_keyframes']:
            if key['frame']>=417 and name in key['landmarks']:
                xy=np.asarray(key['landmarks'][name]['xy'])*mapping['uniform_scale']+mapping['translation_xy'];samples.append([key['frame'],*xy])
        if not samples:continue
        target_xy=track(max(417,frame),samples)
        dark=(groups==lower)&(color[:,0]<145)&(color[:,1]<135)&(color[:,2]<130);tri=points[dark]
        normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);areas=np.linalg.norm(normal,axis=1)
        anchor=np.average(tri.mean(1),axis=0,weights=areas);joint=joints[str(side)]
        shoulder=m[upper,:3,:3]@joint['shoulder']+m[upper,:3,3];elbow=m[upper,:3,:3]@joint['elbow']+m[upper,:3,3]
        lower_elbow=m[lower,:3,:3]@joint['elbow']+m[lower,:3,3];hand=m[lower,:3,:3]@anchor+m[lower,:3,3]
        l1=np.linalg.norm(elbow-shoulder);l2=np.linalg.norm(hand-lower_elbow);camera_hand=hand@basis.T
        target=np.array([(target_xy[0]-translation[0])/scale,-(target_xy[1]-translation[1])/scale,camera_hand[2]])
        q=target[:2]-a;good=np.abs(det)>1e-10;b=np.zeros(len(a));c=np.zeros(len(a))
        b[good]=(q[good,0]*v[good,1]-q[good,1]*v[good,0])/det[good];c[good]=(u[good,0]*q[good,1]-u[good,1]*q[good,0])/det[good]
        hit=good&(b>=0)&(c>=0)&(b+c<=1)
        if np.any(hit):
            depth=body_camera[:,0,2]+b*(body_camera[:,1,2]-body_camera[:,0,2])+c*(body_camera[:,2,2]-body_camera[:,0,2]);target[2]=depth[hit].max()+.018
        target=camera_hand*(1-amount)+target*amount;camera_shoulder=shoulder@basis.T
        xy_distance=np.linalg.norm(target[:2]-camera_shoulder[:2]);reach=l1+l2-.002
        if xy_distance<reach:
            dz=np.sqrt(reach*reach-xy_distance*xy_distance);target[2]=np.clip(target[2],camera_shoulder[2]-dz,camera_shoulder[2]+dz)
        target=target@basis;direction=target-shoulder;length=np.linalg.norm(direction);direction/=length
        length=np.clip(length,abs(l1-l2)+.002,l1+l2-.002);target=shoulder+direction*length;along=(l1*l1-l2*l2+length*length)/(2*length)
        pole=elbow-shoulder;pole-=direction*(pole@direction)
        if np.linalg.norm(pole)<1e-8:pole=np.cross(direction,basis[2])
        pole/=np.linalg.norm(pole);middle=shoulder+along*direction+np.sqrt(max(1e-9,l1*l1-along*along))*pole
        m[upper]=segment_transform(shoulder,elbow,shoulder,middle)@m[upper];m[lower]=segment_transform(lower_elbow,hand,middle,target)@m[lower]
        n=np.linalg.inv(m[lower,:3,:3]).T@normal.sum(0);axis=target-middle;axis/=np.linalg.norm(axis)
        n-=axis*(n@axis);toward=basis[2]-axis*(basis[2]@axis)
        if np.linalg.norm(n)>1e-10 and np.linalg.norm(toward)>1e-10:
            n/=np.linalg.norm(n);toward/=np.linalg.norm(toward);angle=math.atan2(axis@np.cross(n,toward),n@toward)
            twist=rotation(axis,math.degrees(angle)*amount);m[lower]=affine(twist,middle-twist@middle)@m[lower]
        if side>0 and positive_y_roll:
            twist=rotation(axis,positive_y_roll*amount);m[lower]=affine(twist,middle-twist@middle)@m[lower]
    return m


def build_matrices(geometry,joints):
    camera=json.loads((ROOT/'assets/naiwa/camera.json').read_text(encoding='utf8'))
    basis=np.array(camera['basis_rows_right_up_toward_camera'])
    reference=json.loads((ROOT/'assets/naiwa/reference_motion.json').read_text(encoding='utf8'))
    fall_parameters=json.loads((OUTPUT/'fall_pose_constraints.json').read_text(encoding='utf8'))['parameters']
    boxes=np.asarray([x['bbox_xyxy'] for x in reference['silhouette_frames']],float)
    centers=(boxes[:,:2]+boxes[:,2:])*.5;offsets=(centers-centers[0])*reference['display_mapping']['uniform_scale']
    verts=geometry['vertices'][geometry['faces']].reshape(-1,3);groups=np.repeat(geometry['groups'],3)
    scale=camera['pixels_per_unit'];tx=camera['translation_x_px'];ty=camera['translation_y_px']
    eye_curve=json.loads((OUTPUT/'eye_closure_curve.json').read_text(encoding='utf8'))['eye_closed']
    all_m=[];keys=[];initial_center=None
    for frame in range(541):
        lean,head,jaw,raise_hands,reach,yaw,fall,jump,crouch=track(frame,[
            [0,0,0,0,0,0,0,0,0,0],[62,0,0,0,0,0,0,0,0,0],
            [66,10,8,13,0,0,18,0,0,0],[72,-10,-36,39,0,0,24,0,0,0],[120,-11,-37,41,0,0,24,0,0,0],
            [135,25,8,34,0,0,24,0,0,.018],[150,5,-5,32,0,0,26,0,0,0],
            [206,0,-6,34,0,0,26,0,0,0],[219,8,-8,34,1,0,26,0,0,0],
            [258,6,-5,32,1,0,26,0,0,0],[268,8,0,34,0,0,24,0,0,0],
            [295,0,-4,34,0,0,24,0,0,0],[307,23,6,34,0,0,24,0,0,.025],
            [319,21,4,33,0,0,24,0,0,.02],[330,-12,-38,41,0,0,24,0,0,0],
            [370,-11,-37,41,0,0,24,0,0,0],[380,0,0,8,0,0,24,0,0,0],
            [390,4,0,30,0,0,24,0,0,0],[397,30,8,35,0,0,20,0,0,.065],
            [402,-2,-4,36,0,.6,-4,0,.05,0],[406,0,-4,39,0,.8,-8,.28,.14,0],
            [411,0,-3,31,0,.2,-2,.80,.10,0],[417,0,-3,25,0,0,0,1,0,0],
            [540,0,-3,25,0,0,0,1,0,0],
        ])
        laughing=float(smooth((frame-63)/7));wave=math.sin(frame/30*2*math.pi*3.1)
        if frame<417:lean+=1.1*wave*laughing
        jaw=max(0,jaw+(3-2.4*fall)*wave*laughing)
        closed=float(eye_curve[frame])
        root=pivot_rotation([0,0,-.14],[0,0,1],yaw)
        if fall>0:
            root=pivot_rotation([0,0,-.14],basis[2],-91*fall)@root
            root=pivot_rotation([0,0,-.14],basis[1],-43*fall)@root
            root=affine(translation=np.array([0,0,-.13*fall+jump])-basis[0]*.10*fall)@root
        else:root=affine(translation=[0,0,jump-crouch])@root
        torso=root@pivot_rotation([-.018,0,-.22],[0,1,0],lean)
        matrices=np.repeat(np.eye(4)[None],len(GROUP_NAMES),axis=0);matrices[0]=torso
        matrices[1]=torso@pivot_rotation([.008,0,.255],[0,1,0],head)
        for side,upper,lower,thigh,calf in [(-1,2,3,6,7),(1,4,5,8,9)]:
            arm_wobble=.0035*wave*laughing*(1-raise_hands)*(1-fall)
            clasp=float(smooth((lean-5)/20))*(1-raise_hands)*(1-fall)
            a,b=arm_matrices(joints,side,raise_hands,reach,arm_wobble,clasp)
            matrices[upper]=torso@a;matrices[lower]=torso@b
            p=joints[str(side)]
            kick=(24+10*math.sin(frame*.23+side)) *fall
            leg_angle=kick+crouch*180
            matrices[thigh]=root@pivot_rotation(p['hip'],[0,1,0],-leg_angle)
            matrices[calf]=matrices[thigh]@pivot_rotation(p['knee'],[0,1,0],leg_angle*1.65)
            matrices[16 if side<0 else 17]=matrices[calf]
        opening=float(smooth(jaw/45))
        jaw_scale=np.diag([1,1,1-.70*opening])
        matrices[10]=matrices[1]@affine(jaw_scale,[-.090*opening,0,.350*(1-jaw_scale[2,2])])
        eye_scale=np.diag([1-.97*closed,1,1-.97*closed]);eye_shift=np.array([.060*(1-eye_scale[0,0])-.030*closed,0,.425*(1-eye_scale[2,2])])
        matrices[11]=matrices[1]@affine(eye_scale,eye_shift)
        matrices[12]=matrices[1]@affine(eye_scale,eye_shift)
        mouth_scale=np.diag([1-.65*laughing*(1-opening),1,max(.025,opening)])
        matrices[13]=matrices[1]@affine(mouth_scale,[.140*(1-mouth_scale[0,0])+(-.060+.052*laughing)*(1-opening),0,.382*(1-mouth_scale[2,2])])
        matrices[14]=matrices[1]@affine(translation=[-.080*(1-closed),0,0])
        matrices[15]=torso@pivot_rotation([.008,0,.255],[0,1,0],head*.5)
        fit_amount=float(smooth((frame-406)/11))
        if fit_amount>0:matrices=fitted_fall_rotation(matrices,geometry,joints,basis,fall_parameters,fit_amount)
        landing_z_scale=1-.20*float(smooth((frame-412)/5))
        matrices=affine(np.diag([1.,1.,landing_z_scale]))@matrices
        if frame>=417:
            world=np.einsum('nij,nj->ni',matrices[groups,:3,:3],verts)+matrices[groups,:3,3]
            dz=-.48965-world[:,2].min();matrices[:,:3,3]+=np.array([0,0,dz])
        world=np.einsum('nij,nj->ni',matrices[groups,:3,:3],verts)+matrices[groups,:3,3]
        projected=world@basis.T;xy=np.column_stack((projected[:,0]*scale+tx,-projected[:,1]*scale+ty))
        low=xy.min(0);high=xy.max(0);center=(low+high)*.5
        if initial_center is None:initial_center=center.copy()
        delta=initial_center+offsets[frame]-center
        delta+=np.array([fall_parameters['translation_x_px'],fall_parameters['translation_y_px']])*fit_amount
        shifted_low=low+delta;shifted_high=high+delta
        delta+=np.maximum([2.,2.]-shifted_low,0)-np.maximum(shifted_high-[317.,237.],0)
        matrices[:,:3,3]+=basis[0]*delta[0]/scale-basis[1]*delta[1]/scale
        if fit_amount>0:
            matrices=constrain_fall_hands(matrices,geometry,joints,basis,camera,reference,frame,fit_amount,fall_parameters.get('positive_y_hand_roll_deg',0))
            world=np.einsum('nij,nj->ni',matrices[groups,:3,:3],verts)+matrices[groups,:3,3]
            projected=world@basis.T;xy=np.column_stack((projected[:,0]*scale+tx,-projected[:,1]*scale+ty))
            delta=np.maximum([2.,2.]-xy.min(0),0)-np.maximum(xy.max(0)-[317.,237.],0)
            matrices[:,:3,3]+=basis[0]*delta[0]/scale-basis[1]*delta[1]/scale
        all_m.append(matrices)
        keys.append(dict(frame=frame,lean_deg=float(lean),head_deg=float(head),jaw_deg=float(jaw),mouth_opening=float(opening),hands_to_head=float(raise_hands),fall=float(fall),fall_fit_weight=fit_amount,landing_world_z_scale=landing_z_scale,jump=float(jump),eye_closed=float(closed)))
    return np.asarray(all_m,np.float32),keys


def blender_stage():
    import bpy
    from mathutils import Matrix,Vector
    data=np.load(OUTPUT/'geometry.npz');all_m=np.load(OUTPUT/'matrices.npy')
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    for group,name in enumerate(GROUP_NAMES):
        faces=data['faces'][data['groups']==group];rgb=data['colors'][data['groups']==group]
        used,inverse=np.unique(faces,return_inverse=True)
        vertices=data['vertices'][used];indices=inverse.reshape(-1,3)
        mesh=bpy.data.meshes.new(name);mesh.from_pydata(vertices.tolist(),[],indices.tolist());mesh.update()
        obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj)
        colors=mesh.color_attributes.new(name='source_color',type='FLOAT_COLOR',domain='CORNER')
        color=rgb.reshape(-1,3).astype(float)/255;linear=np.where(color<=.04045,color/12.92,((color+.055)/1.055)**2.4)
        colors.data.foreach_set('color',np.column_stack([linear,np.ones(len(linear))]).astype(np.float32).ravel())
        material=bpy.data.materials.new(name+'_source_color');material.use_nodes=True;n=material.node_tree.nodes;n.clear()
        out=n.new('ShaderNodeOutputMaterial');emission=n.new('ShaderNodeEmission');attribute=n.new('ShaderNodeVertexColor');attribute.layer_name='source_color'
        material.node_tree.links.new(attribute.outputs['Color'],emission.inputs['Color']);material.node_tree.links.new(emission.outputs[0],out.inputs['Surface']);obj.data.materials.append(material)
        parent=bpy.data.objects.new(name+'_affine',None);bpy.context.collection.objects.link(parent);obj.parent=parent
        parent.rotation_mode='QUATERNION';obj.rotation_mode='QUATERNION';last_parent=None;last_child=None
        for frame,matrix in enumerate(all_m[:,group]):
            u,scale,vt=np.linalg.svd(matrix[:3,:3].astype(float))
            if np.linalg.det(u)<0:u[:,-1]*=-1;scale[-1]*=-1
            if np.linalg.det(vt)<0:vt[-1]*=-1;scale[-1]*=-1
            qp=Matrix(u.tolist()).to_quaternion();qc=Matrix(vt.tolist()).to_quaternion()
            if last_parent is not None and qp.dot(last_parent)<0:qp.negate()
            if last_child is not None and qc.dot(last_child)<0:qc.negate()
            parent.location=Vector(matrix[:3,3].tolist());parent.rotation_quaternion=qp;parent.scale=Vector(scale.tolist());obj.rotation_quaternion=qc
            parent.keyframe_insert(data_path='location',frame=frame+1);parent.keyframe_insert(data_path='rotation_quaternion',frame=frame+1);parent.keyframe_insert(data_path='scale',frame=frame+1);obj.keyframe_insert(data_path='rotation_quaternion',frame=frame+1)
            last_parent=qp.copy();last_child=qc.copy()
    scene=bpy.context.scene;scene.frame_start=1;scene.frame_end=541;scene.render.fps=30
    camera=json.loads((ROOT/'assets/naiwa/camera.json').read_text());basis=np.asarray(camera['basis_rows_right_up_toward_camera']);target=np.asarray(camera['camera_world_target'])
    cd=bpy.data.cameras.new('MGPU fixed camera');cam=bpy.data.objects.new('MGPU fixed camera',cd);scene.collection.objects.link(cam);cam.matrix_world=Matrix(basis.T.tolist()).to_4x4();cam.location=Vector(target+basis[2]*3);cd.type='ORTHO';cd.ortho_scale=camera['blender_ortho_scale'];scene.camera=cam
    scene.render.engine='CYCLES';scene.cycles.samples=4;scene.render.resolution_x=640;scene.render.resolution_y=480;scene.render.resolution_percentage=100;scene.render.film_transparent=True;scene.view_settings.view_transform='Standard';scene.view_settings.look='None';scene.render.image_settings.color_mode='RGBA'
    scene.frame_set(1);scene['source']='milkfrog.blend';scene['adaptation']=f'{len(GROUP_NAMES)} affine groups, fixed source-derived mesh and per-group 4x4 animation for unmodified MGPU'
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT/'milkfrog_laugh.blend'),compress=True)
    for frame in [0,84,135,225,315,360,405,417,540]:
        scene.frame_set(frame+1);scene.render.filepath=str(PREVIEW/f'blender_{frame:04d}.png');bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender-stage',action='store_true');parser.add_argument('--no-blender',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)
    if args.blender_stage:blender_stage();return
    OUTPUT.mkdir(parents=True,exist_ok=True);PREVIEW.mkdir(parents=True,exist_ok=True)
    refinement_names=['eye_closure_curve.json','motion_refinement.json','mouth_reference_masks.npz','landing_landmarks.json','fall_pose_constraints.json']
    locked_inputs={name:(OUTPUT/name).read_bytes() for name in refinement_names}
    geometry,joints=build_geometry();matrices,tracks=build_matrices(geometry,joints)
    from refine_milkfrog_motion import refine_motion
    from milkfrog_expression import fit_expression
    camera=json.loads((ROOT/'assets/naiwa/camera.json').read_text(encoding='utf8'))
    reference=json.loads((ROOT/'assets/naiwa/reference_motion.json').read_text(encoding='utf8'))
    motion=json.loads(locked_inputs['motion_refinement.json'])
    matrices=refine_motion(matrices,geometry,camera,reference,motion)
    observed=np.load(OUTPUT/'mouth_reference_masks.npz')
    matrices,expression,expression_report=fit_expression(matrices,geometry,camera,observed['masks'],observed['confidence'],observed['occluded'])
    matrices=matrices.astype(np.float32)
    assert np.isfinite(matrices).all() and np.all(np.linalg.det(matrices[:,:,:3,:3])>0)
    if any((OUTPUT/name).read_bytes()!=data for name,data in locked_inputs.items()):
        raise RuntimeError('Refinement inputs changed while generating animation; rerun on frozen inputs')
    for row,parameters in zip(tracks,expression):
        row['mouth_width_scale'],row['mouth_height_scale'],row['head_offset_x_px'],row['head_offset_y_px']=map(float,parameters)
    (OUTPUT/'expression_fit.json').write_text(json.dumps(dict(method='Native observed mouth-mask width/height fitting in anatomical mouth Y/Z; bounded whole-head offset, deforming source-derived neck sleeve; smoothed over time. No camera or GPU core changes.',frames=expression_report),indent=2)+'\n')
    np.savez_compressed(OUTPUT/'geometry.npz',**geometry);np.save(OUTPUT/'matrices.npy',matrices)
    metadata=dict(source='milkfrog.blend',source_sha256=hashlib.sha256((ROOT/'milkfrog.blend').read_bytes()).hexdigest(),source_lod='B:8000 triangles',group_names=GROUP_NAMES,frames=541,fps=30,vertices=len(geometry['vertices']),triangles=len(geometry['faces']),joints=joints,matrix_convention='column vector; 4x4 object-to-world includes root; downstream left-multiplies fixed camera MVP',reference='assets/naiwa/reference_motion.json',limitations=['Rigid/affine-piece adaptation; not an exact recovered rig or pixel-for-pixel match.','Torso and upper/lower arms are reconstructed source-constrained surfaces to separate the fused hands/belly; hidden contact anatomy is an authored approximation.','Head, eye, hand, leg and foot surfaces are retained from the source LOD with local cutting and joint closure.','Mouth cavity, lips, teeth, tongue, eyelid skin and neck connector are newly constructed animation geometry in the working copy.','Source material sampled into per-corner sRGB colors; reconstructed regions use source-derived color interpolation; original .blend unchanged.','The B simplification RMS does not measure the additional animation retopology error.'])
    metadata['adaptation_measurements']={
        'torso':'30 horizontal cross sections and 40 angles; positive original-surface ray distance is a hard bound; front/back central diameters and unobstructed back-half width constrain a smooth ellipse beneath fused arms/hands.',
        'arms':'7 transverse rings with 12 angles per segment; original-surface ray samples, radius limits and second-harmonic smoothing; measured exposed upper-arm radii approximately 0.069 to 0.084 source units.',
        'hands':'Original triangles clipped internally at min(170-R,130-G)>=0 in sampled source color; boundary closures retain dark fingers without carrying unrelated belly corners.',
        'neck_source_front_x_at_z':[[.21,.133713],[.23,.124261],[.255,.116771],[.28,.113397],[.30,.114933]],
        'pose':'Reference timing and fixed-scale projected bbox-center offsets are measurements; 3D joint angles and hidden motion remain authored estimates.',
        'camera':'assets/naiwa/camera.json; fixed camera and fixed scale for all 541 frames; only root translation is fitted to the reference center trajectory.',
        'fall':'Selected visible-feet pose parameters are stored in fall_pose_constraints.json; corrections blend over frames 406..417; hand targets interpolate measured reference landmarks and contact the transformed torso front surface.',
        'landing_deformation':'World-Z compression blends from 1.0 to 0.8 over frames 412..417 and remains 0.8 afterward. This is an empirical nonrigid cartoon-pose fit, not measured physical depth or a recovered source rig. It is applied before final hand contact IK and does not alter the fixed camera or source file.',
        'blender_affine':'Each GPU group is represented by a two-object SVD transform hierarchy to preserve shear at all 541 integer frames. GPU storage remains one full 4x4 affine transform per triangle group.'}
    metadata['adaptation_measurements'].update({
        'mouth':'Asymmetric smile cavity, three-dimensional curved tooth rows, and 541-frame observed mouth-mask constraints. Occluded frames 411..415 are excluded from expression fitting rather than forced visible.',
        'eyes':'Original source eye surfaces retained; closed-eye arc geometry and eye_closure_curve.json follow inspected reference intervals, including the closed eyes at frame 186.',
        'neck':'Seven source-surface ray-sampled neck cross sections with 24 angular samples form the continuous affine neck sleeve.',
        'ankles':'Source triangles are clipped at local Z=-0.430, retaining interpolated source colors and closed ankle cut surfaces. Groups 16/17 articulate feet independently from calf groups 7/9. Both sides use measured cut-ring centers as the shared calf/foot joint.',
        'motion_refinement':'motion_refinement.json separates planted crouch, upright jump, backward fall, head self-occlusion and arm/leg contact targets. Single-view depth and joint rotations remain authored fits.'})
    metadata['refinement_input_sha256']={name:hashlib.sha256(data).hexdigest() for name,data in locked_inputs.items()}
    (OUTPUT/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf8');(OUTPUT/'pose_tracks.json').write_text(json.dumps(tracks,indent=2)+'\n')
    print('ANIMATION_DATA_READY',json.dumps({k:metadata[k] for k in ['frames','vertices','triangles','group_names']}),flush=True)
    if not args.no_blender:
        subprocess.run(['C:/Program Files/Blender Foundation/Blender 5.2/blender.exe','--background','--factory-startup','--disable-autoexec','--threads','8','--python',str(Path(__file__).resolve()),'--','--blender-stage'],check=True)


if __name__=='__main__':main()
