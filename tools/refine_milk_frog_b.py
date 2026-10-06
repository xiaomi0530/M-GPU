from pathlib import Path
import argparse
import json
import math
import zipfile
import build_milk_frog_variants as base
from build_milk_frog_variants import np,Image,ImageDraw,font,ROOT,Q,ellipsoid,smooth,tapered,mirrored
from skimage.measure import marching_cubes
import fast_simplification
import orbit_scene


CONFIG=base.BASE|base.VARIANTS[1][3]|dict(
    body=(.84,1.02,.65),belly=(.75,.82,.64),neck=(.405,.73,.39),
    head=(.44,.45,.42),head_y=1.295,eye_x=.237,eye_y=1.33,eye_r=(.155,.176),
    shoulder=(.665,.445,.015),elbow=(.94,-.035,-.23),
    hand=(.415,-.345,-1.005),hand_r=(.175,.205,.14),arm=.19,
    thigh=.265,shin=.14,foot=(.48,-1.72,-.175),foot_r=(.255,.115,.35),
    patch=(.685,.745,-.005),mouth_y=1.035)


def hand_field(p,c,sign,inflate=1.):
    h=mirrored(c['hand'],sign)
    d=ellipsoid(p,h,np.array(c['hand_r'])*inflate)
    thumb=h+np.array([sign*.065,.145,-.035])
    d=smooth(d,ellipsoid(p,thumb,np.array([.09,.115,.105])*inflate),.055)
    for dy in [-.105,.005,.11]:
        finger=h+np.array([-sign*.115,dy,-.025])
        d=smooth(d,ellipsoid(p,finger,np.array([.10,.072,.13])*inflate),.035)
    return d


def field(p,c):
    d=base.torso(p,c)
    for sign in [-1,1]:
        d=smooth(d,tapered(p,mirrored(c['hip'],sign),mirrored(c['ankle'],sign),c['thigh'],c['shin']),.17)
        foot=mirrored(c['foot'],sign)
        d=smooth(d,ellipsoid(p,foot,c['foot_r']),.08)
        for dx in [-.12,0,.12]:
            toe=foot+np.array([dx,-.01,-.21])
            d=smooth(d,ellipsoid(p,toe,(.12,.105,.185)),.06)
        shoulder=mirrored(c['shoulder'],sign);elbow=mirrored(c['elbow'],sign);hand=mirrored(c['hand'],sign)
        d=smooth(d,tapered(p,shoulder,elbow,c['arm']*1.13,c['arm']*1.03),.17)
        d=smooth(d,ellipsoid(p,shoulder,(.22,.24,.21)),.105)
        middle=elbow*.53+hand*.47+np.array([sign*.025,-.025,-.035])
        wrist=hand*.79+elbow*.21
        d=smooth(d,tapered(p,elbow,middle,c['arm']*1.03,c['arm']*.95),.105)
        d=smooth(d,tapered(p,middle,wrist,c['arm']*.95,c['arm']*.77),.08)
        d=smooth(d,hand_field(p,c,sign),.06)
    return np.maximum(d,-1.83-p[...,1])


def normal(p):
    e=np.eye(3)*.001
    g=np.array([field(p+a,CONFIG)-field(p-a,CONFIG) for a in e])
    return g/max(np.linalg.norm(g),1e-10)


def symmetric_mesh(vertices,faces):
    points=[];triangles=[];lookup={}
    def index(p):
        key=tuple(np.round(p,7))
        if key not in lookup:lookup[key]=len(points);points.append(key)
        return lookup[key]
    for f in faces:
        p=vertices[f];poly,_=base.split_polygon(list(p),lambda q:-q[0])
        for j in range(1,len(poly)-1):
            tri=np.array([poly[0],poly[j],poly[j+1]])
            if np.linalg.norm(np.cross(tri[1]-tri[0],tri[2]-tri[0]))<1e-9:continue
            triangles.append([index(v) for v in tri])
            mirror=tri[[0,2,1]]*np.array([-1,1,1])
            triangles.append([index(v) for v in mirror])
    return np.array(points),np.array(triangles)


def color_mesh(vertices,faces):
    c=CONFIG;rx,ry,cy=c['patch'];result=[]
    light=np.array([-.35,.75,-.55]);light/=np.linalg.norm(light)
    def front(p):return max((p[2]+.32)*4,(base.torso(p,c)-.065)*5)
    def hands(p):return min(hand_field(p,c,s,1.20) for s in [-1,1])
    def feet(p):return p[1]-(c['foot'][1]+.080)
    def add(poly,color):
        for j in range(1,len(poly)-1):
            p=np.array([poly[0],poly[j],poly[j+1]])
            if np.linalg.norm(np.cross(p[1]-p[0],p[2]-p[0]))<1e-9:continue
            result.append(dict(vertices=np.round(p,6).tolist(),colors=[list(color)]*3))
    for f in faces:
        p=vertices[f];n=normal(p.mean(0))
        pieces=[list(p)]
        for fn,color in [(feet,[104,104,69]),(hands,[104,104,69])]:
            rest=[]
            for poly in pieces:
                inside,outside=base.split_polygon(poly,fn)
                if len(inside)>=3:add(inside,color)
                if len(outside)>=3:rest.append(outside)
            pieces=rest
        green=round(223*(.89+.11*max(0,np.dot(n,light)))*7/255)
        if p.mean(0)[1]>.92 and n[2]<-.3:green=6
        color=[round((green+1)*255/7),round(green*255/7),85]
        for poly in pieces:
            inside,outside=base.split_polygon(poly,front)
            if len(outside)>=3:add(outside,color)
            for angle in np.arange(16)*math.tau/16:
                if len(inside)<3:break
                a,b=math.cos(angle),math.sin(angle)
                inside,outside=base.split_polygon(inside,lambda q:a*q[0]/rx+b*(q[1]-cy)/ry-math.cos(math.pi/16))
                if len(outside)>=3:add(outside,color)
            if len(inside)>=3:add(inside,[255,235,204])
    return result


def conform_edges(mesh):
    vertices=np.unique(np.array([v for f in mesh for v in f['vertices']]),axis=0);result=[]
    for face in mesh:
        p=np.array(face['vertices']);boundary=[]
        for a,b in zip(p,np.roll(p,-1,axis=0)):
            edge=b-a;length=np.dot(edge,edge)
            t=(vertices-a)@edge/length
            distance=np.linalg.norm(vertices-a-t[:,None]*edge,axis=1)
            ids=np.flatnonzero((t>1e-5)&(t<1-1e-5)&(distance<2e-6))
            boundary.append(a)
            boundary.extend(vertices[i] for i in ids[np.argsort(t[ids])])
        if len(boundary)==3:result.append(face);continue
        polygon=np.array(boundary);n=np.cross(p[1]-p[0],p[2]-p[0]);axes=[i for i in range(3) if i!=np.argmax(abs(n))]
        points=polygon[:,axes];ids=list(range(len(polygon)))
        def cross(a,b):return a[0]*b[1]-a[1]*b[0]
        orientation=np.sign(cross(p[1,axes]-p[0,axes],p[2,axes]-p[0,axes]))
        while len(ids)>3:
            for k,i in enumerate(ids):
                tri=[ids[k-1],i,ids[(k+1)%len(ids)]];a,b,c=points[tri]
                if cross(b-a,c-a)*orientation<=1e-12:continue
                blocked=False
                for other in ids:
                    if other in tri:continue
                    q=points[other]
                    if min(cross(b-a,q-a)*orientation,cross(c-b,q-b)*orientation,cross(a-c,q-c)*orientation)>=-1e-12:
                        blocked=True;break
                if blocked:continue
                result.append(dict(vertices=polygon[tri].tolist(),colors=face['colors']))
                ids.pop(k);break
            else:raise ValueError('Could not triangulate shared boundary')
        if np.linalg.norm(np.cross(polygon[ids[1]]-polygon[ids[0]],polygon[ids[2]]-polygon[ids[0]]))>1e-10:
            result.append(dict(vertices=polygon[ids].tolist(),colors=face['colors']))
    return result


def build():
    c=CONFIG;low=np.array([-1.5,-1.95,-1.4]);high=np.array([1.5,1.95,1.1]);step=.03
    axes=[np.arange(a,b+step,step) for a,b in zip(low,high)]
    grid=np.stack(np.meshgrid(*axes,indexing='ij'),axis=-1)
    vertices,faces,_,_=marching_cubes(field(grid,c),0,spacing=(step,step,step),gradient_direction='ascent')
    vertices+=low
    stretched=vertices.copy();stretched[:,1]=np.where(vertices[:,1]>.73,.73+(vertices[:,1]-.73)*1.4,vertices[:,1])
    scale=1+.55*np.clip((vertices[:,1]-.65)/.4,0,1)
    stretched[:,0]*=scale;stretched[:,2]*=scale
    for target in range(540,399,-20):
        v,f=fast_simplification.simplify(stretched,faces,target_count=target,agg=5)
        v[:,1]=np.where(v[:,1]>.73,.73+(v[:,1]-.73)/1.4,v[:,1])
        scale=1+.55*np.clip((v[:,1]-.65)/.4,0,1);v[:,0]/=scale;v[:,2]/=scale
        for _ in range(3):
            e=np.eye(3)*.001;g=np.stack([(field(v+a,c)-field(v-a,c))/.002 for a in e],axis=-1)
            stepv=field(v,c)[:,None]*g/np.maximum(np.sum(g*g,axis=-1,keepdims=True),1e-8)
            v-=np.clip(stepv,-.025,.025)
        v,f=symmetric_mesh(v,f)
        if np.sum(np.einsum('ij,ij->i',v[f[:,0]],np.cross(v[f[:,1]],v[f[:,2]])))<0:f=f[:,[0,2,1]]
        result=conform_edges(color_mesh(v,f));base.add_features(result,v,f,c)
        print('Geometry',len(f),'total',len(result),flush=True)
        if len(result)<=1023:return result,len(f)
    raise ValueError('Refined mesh budget exceeded')


def previews(mesh,old,output):
    background=(243,245,243);output.mkdir(parents=True,exist_ok=True)
    card=Image.new('RGB',(1460,790),background);d=ImageDraw.Draw(card)
    d.text((48,28),'B / 抱肚站姿 · 细化版',font=font(35,True),fill=(30,45,40))
    d.text((50,86),'圆顺头肩 · 贴腹手掌与拇指 · 更宽的脚掌 · 平直嘴线',font=font(20),fill=(97,111,101))
    for col,(frame,label) in enumerate([(0,'正面'),(16,'三分之四侧面'),(32,'侧面')]):
        view=base.render(mesh,frame).crop((155,40,485,460)).resize((440,560),Image.Resampling.NEAREST)
        card.paste(view,(30+col*480,144));d.text((67+col*480,707),label,font=font(20),fill=(69,86,73))
    d.text((50,756),f'{len(mesh)} 个三角形 · RGB332 / Q6.12 · 软件造型预览，实际 RTL 仿真截图另附',font=font(16),fill=(115,125,117))
    card.save(output/'views.png')
    comparison=Image.new('RGB',(1540,1080),background);d=ImageDraw.Draw(comparison)
    d.text((42,24),'B / 细化前后',font=font(33,True),fill=(30,45,40))
    d.text((44,77),'相同相机、比例与配色 · 上排正面 / 下排侧前方',font=font(19),fill=(97,111,101))
    for col,(label,model) in enumerate([('原版 B',old),('B 细化版',mesh)]):
        x=col*770
        d.text((x+88,126),label+f' / {len(model)} 面',font=font(25,True),fill=(30,45,40))
        for row,frame in enumerate([0,16]):
            view=base.render(model,frame).crop((155,45,485,455)).resize((350,435),Image.Resampling.NEAREST)
            comparison.paste(view,(x+190,174+row*441))
    d.line((770,150,770,1034),fill=(217,224,216),width=1)
    comparison.save(output/'before_after.png')
    frames=[base.render(mesh,i) for i in range(0,128,2)]
    durations=[(round((i+1)*200/15)-round(i*200/15))*10 for i in range(64)]
    frames[0].save(output/'orbit.gif',save_all=True,append_images=frames[1:],duration=durations,loop=0,disposal=2)
    base.render(mesh,0,(0,0,0)).save(output/'front_640x480.png')


def audit(mesh):
    fixed=base.fixed_mesh(mesh);bounds=[];counts=[];failures=[];orders=[]
    saved=orbit_scene.scene;orbit_scene.scene=lambda:fixed
    try:
        for frame in range(128):
            m=base.matrix(frame)
            for vertices,_,_ in fixed:
                bounds.extend(base.project(v,m)[0] for v in vertices)
            try:order=orbit_scene.order(frame);counts.append(len(order));orders.append(order)
            except (ValueError,RuntimeError) as exc:failures.append(dict(frame=frame,error=str(exc)));orders.append(None)
            if frame%32==31:print('Checked orbit',frame+1,'/ 128',flush=True)
    finally:orbit_scene.scene=saved
    bounds=np.array(bounds)
    return dict(triangles=len(mesh),visible_min=min(counts),visible_max=max(counts),bounds_min=bounds.min(0).tolist(),bounds_max=bounds.max(0).tolist(),order_failures=failures,orders=orders)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--preview-only',action='store_true');parser.add_argument('--install',action='store_true');args=parser.parse_args()
    output=ROOT/'assets/milk_frog_variants/B_refined';images=ROOT/'docs/images/milk_frog_variants/B_refined'
    if args.preview_only:mesh=json.loads((output/'mesh.json').read_text())
    else:
        mesh,body_count=build();base.save_mesh(mesh,output)
        result=audit(mesh);result.update(parameters=CONFIG,body_triangles=body_count,rtl_verified=False,rom_index_bits=len(mesh).bit_length())
        (output/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Order failures',len(result['order_failures']),flush=True)
    old=json.loads((ROOT/'assets/milk_frog_variants/B/mesh.json').read_text());previews(mesh,old,images)
    with zipfile.ZipFile(output/'milk_frog_b_refined.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for name in ['mesh.json','milk_frog.obj','milk_frog.mtl','validation.json']:
            archive.write(output/name,name)
    if args.install:
        validation=json.loads((output/'validation.json').read_text(encoding='utf-8'))
        if validation['order_failures']:raise ValueError('Orbit order validation failed')
        active=ROOT/'assets/milk_frog';base.save_mesh(mesh,active)
        with zipfile.ZipFile(active/'milk_frog_model.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for name in ['mesh.json','milk_frog.obj','milk_frog.mtl']:archive.write(active/name,name)
    print('Saved refined B',len(mesh),'triangles',flush=True)


if __name__=='__main__':main()
