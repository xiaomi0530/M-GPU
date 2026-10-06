from pathlib import Path
import argparse
import json
import math
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'out/mesh_libs'))
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from skimage.measure import marching_cubes
import fast_simplification
from build_milk_frog import ellipsoid,smooth
from build_vertex_lab import Q,rgb
from orbit_scene import matrix,project


BASE=dict(body=(.77,1.00,.62),belly=(.66,.78,.56),belly_z=-.24,
          neck=(.40,.72,.38),neck_y=.66,head=(.43,.45,.405),head_y=1.30,
          shoulder=(.63,.48,.02),elbow=(.91,-.10,-.04),hand=(.71,-.72,-.60),
          arm=.185,hand_r=(.145,.21,.145),hip=(.37,-.81,.13),ankle=(.47,-1.60,.02),
          thigh=.265,shin=.12,foot=(.49,-1.72,-.16),foot_r=(.24,.115,.34),
          patch=(.65,.73,-.035),eye_x=.225,eye_y=1.32,eye_r=(.15,.18),mouth_y=1.035)
VARIANTS=[
    ('A','设定还原','长颈 · 梨形肚腹 · 双手自然下垂',{}),
    ('B','抱肚站姿','更突出的肚腹 · 手臂内收 · 贴近第二张参考',
     dict(body=(.84,1.02,.66),belly=(.75,.82,.64),belly_z=-.25,
          elbow=(.94,-.02,-.21),hand=(.44,-.34,-1.00),arm=.195,hand_r=(.15,.22,.155),
          patch=(.69,.77,-.015),head=(.42,.44,.405),head_y=1.29,eye_y=1.31)),
    ('C','修长比例','更长的脖颈 · 窄肩长腿 · 放松站姿',
     dict(body=(.70,.91,.57),belly=(.59,.70,.51),neck=(.34,.76,.34),neck_y=.73,
          head=(.39,.43,.375),head_y=1.36,eye_x=.21,eye_y=1.37,eye_r=(.142,.17),mouth_y=1.095,
          shoulder=(.55,.40,.04),elbow=(.80,-.13,-.06),hand=(.64,-.76,-.49),
          arm=.163,hand_r=(.13,.20,.14),hip=(.33,-.73,.12),ankle=(.42,-1.61,.015),
          thigh=.24,shin=.115,foot=(.45,-1.72,-.16),foot_r=(.23,.115,.33),patch=(.58,.68,.01))),
    ('D','圆胖比例','宽肚短颈 · 粗短四肢 · 厚实圆润',
     dict(body=(.94,1.08,.70),belly=(.85,.87,.65),belly_z=-.26,
          neck=(.47,.62,.43),neck_y=.68,head=(.48,.43,.435),head_y=1.29,
          eye_x=.25,eye_y=1.31,eye_r=(.162,.186),mouth_y=1.035,
          shoulder=(.76,.42,.02),elbow=(1.06,-.11,-.13),hand=(.83,-.62,-.66),
          arm=.22,hand_r=(.16,.205,.155),hip=(.43,-.93,.12),ankle=(.52,-1.61,.04),
          thigh=.28,shin=.145,foot=(.55,-1.72,-.15),foot_r=(.265,.115,.35),patch=(.77,.79,-.05))),
    ('E','柔和圆头','饱满圆头 · 大绿眼 · 手臂略向前收',
     dict(body=(.78,.98,.62),belly=(.69,.77,.57),neck=(.44,.70,.41),neck_y=.66,
          head=(.49,.46,.445),head_y=1.29,eye_x=.255,eye_y=1.32,eye_r=(.17,.195),mouth_y=1.02,
          elbow=(.91,-.04,-.18),hand=(.65,-.58,-.80),arm=.185,hand_r=(.14,.205,.145),
          patch=(.65,.71,-.005)))
]


def tapered(p,a,b,ra,rb):
    a=np.array(a);b=np.array(b);v=b-a
    t=np.clip(np.sum((p-a)*v,axis=-1)/np.dot(v,v),0,1)
    return np.linalg.norm(p-a-t[...,None]*v,axis=-1)-(ra+(rb-ra)*t)


def mirrored(v,sign):
    return np.array([v[0]*sign,v[1],v[2]])


def torso(p,c):
    d=ellipsoid(p,(0,-.12,.14),c['body'])
    d=smooth(d,ellipsoid(p,(0,-.08,c['belly_z']),c['belly']),.24)
    d=smooth(d,ellipsoid(p,(0,c['neck_y'],.035),c['neck']),.32)
    d=smooth(d,ellipsoid(p,(0,c['head_y'],-.07),c['head']),.24)
    return smooth(d,ellipsoid(p,(0,c['mouth_y']+.02,-.34),(.255,.10,.12)),.065)


def field(p,c):
    d=torso(p,c)
    for sign in [-1,1]:
        d=smooth(d,tapered(p,mirrored(c['hip'],sign),mirrored(c['ankle'],sign),c['thigh'],c['shin']),.14)
        d=smooth(d,ellipsoid(p,mirrored(c['foot'],sign),c['foot_r']),.075)
        d=smooth(d,tapered(p,mirrored(c['shoulder'],sign),mirrored(c['elbow'],sign),c['arm']*1.10,c['arm']),.12)
        wrist=mirrored(c['hand'],sign)*.78+mirrored(c['elbow'],sign)*.22
        d=smooth(d,tapered(p,mirrored(c['elbow'],sign),wrist,c['arm'],c['arm']*.74),.095)
        d=smooth(d,ellipsoid(p,mirrored(c['hand'],sign),c['hand_r']),.065)
    return np.maximum(d,-1.83-p[...,1])


def normal(v,c):
    e=np.eye(3)*.001
    n=np.array([field(v+a,c)-field(v-a,c) for a in e])
    return n/max(np.linalg.norm(n),1e-9)


def split_polygon(poly,fn):
    values=[float(fn(p)) for p in poly];inside=[];outside=[]
    for j,a in enumerate(poly):
        b=poly[(j+1)%len(poly)];fa=values[j];fb=values[(j+1)%len(poly)]
        (inside if fa<=0 else outside).append(a)
        if (fa<0 and fb>0) or (fa>0 and fb<0):
            low=0.;high=1.
            for _ in range(28):
                t=(low+high)*.5
                if (fn(a+(b-a)*t)<=0)==(fa<=0):low=t
                else:high=t
            cut=a+(b-a)*((low+high)*.5)
            inside.append(cut);outside.append(cut)
    return inside,outside


def color_mesh(vertices,faces,c):
    result=[];light=np.array([-.45,.75,-.5]);light/=np.linalg.norm(light)
    rx,ry,cy=c['patch']
    def belly(p):return max((p[0]/rx)**2+((p[1]-cy)/ry)**2-1,(p[2]+.32)*4,(torso(p,c)-.07)*5)
    def hands(p):
        return min(ellipsoid(p,mirrored(c['hand'],s),np.array(c['hand_r'])*1.20) for s in [-1,1])
    def feet(p):return p[1]-(c['foot'][1]+.070)
    layers=[(feet,np.array([104.,104.,69.])),(hands,np.array([104.,104.,69.])),(belly,np.array([255.,235.,204.]))]
    def add(poly,color,gain):
        for j in range(1,len(poly)-1):
            p=np.array([poly[0],poly[j],poly[j+1]])
            if np.linalg.norm(np.cross(p[1]-p[0],p[2]-p[0]))<1e-9:continue
            result.append(dict(vertices=np.round(p,6).tolist(),colors=[np.clip(color*gain,0,255).round().astype(int).tolist()]*3))
    for f in faces:
        p=vertices[f];n=normal(p.mean(0),c)
        if np.dot(np.cross(p[1]-p[0],p[2]-p[0]),n)<0:p=p[[0,2,1]]
        pieces=[list(p)];gain=.89+.11*max(0,np.dot(n,light))
        for fn,color in layers:
            rest=[]
            for poly in pieces:
                inner,outer=split_polygon(poly,fn)
                if len(inner)>=3:add(inner,color,1 if fn==belly else .96+.04*max(0,np.dot(n,light)))
                if len(outer)>=3:rest.append(outer)
            pieces=rest
        green=round(223*gain*7/255)
        for poly in pieces:add(poly,np.array([(green+1)*255/7,green*255/7,85.]),1)
    return result


def add_face(result,points,color):
    p=np.array(points)
    if np.cross(p[1]-p[0],p[2]-p[0])[2]>0:p=p[[0,2,1]]
    result.append(dict(vertices=np.round(p,6).tolist(),colors=[list(color)]*3))


def add_features(result,vertices,faces,c):
    triangles=vertices[faces]
    def front(x,y):
        a=triangles[:,0];b=triangles[:,1];d=triangles[:,2]
        area=(b[:,0]-a[:,0])*(d[:,1]-a[:,1])-(b[:,1]-a[:,1])*(d[:,0]-a[:,0])
        safe=np.where(abs(area)>1e-10,area,1)
        u=((x-a[:,0])*(d[:,1]-a[:,1])-(y-a[:,1])*(d[:,0]-a[:,0]))/safe
        v=((b[:,0]-a[:,0])*(y-a[:,1])-(b[:,1]-a[:,1])*(x-a[:,0]))/safe
        mask=(abs(area)>1e-10)&(u>=-1e-7)&(v>=-1e-7)&(u+v<=1+1e-7)
        if np.any(mask):return float((a[:,2]+u*(b[:,2]-a[:,2])+v*(d[:,2]-a[:,2]))[mask].min())
        raise ValueError(('Face feature outside head',x,y))
    for sign in [-1,1]:
        cx=sign*c['eye_x'];cy=c['eye_y'];rx,ry=c['eye_r'];rings=[];count=10
        for r in [1.,.48]:
            ring=[]
            for t in np.arange(count)*2*math.pi/count:
                x=cx+rx*r*math.cos(t);y=cy+ry*r*math.sin(t)
                ring.append(np.array([x,y,front(x,y)-.055-.068*(1-r*r)]))
            rings.append(ring)
        center=np.array([cx,cy,front(cx,cy)-.140])
        for j in range(count):
            k=(j+1)%count;a,b=rings
            add_face(result,[a[j],a[k],b[k]],[113,183,66])
            add_face(result,[a[j],b[k],b[j]],[113,183,66])
            add_face(result,[b[j],b[k],center],[13,23,15])
        points=[[cx-.028,cy+.032,center[2]-.016],[cx-.009,cy+.053,center[2]-.017],[cx+.002,cy+.027,center[2]-.017]]
        add_face(result,points,[235,243,213])
    mouth=[]
    for x in np.linspace(-.205,.205,6):
        y=c['mouth_y']-.006*(x/.205)**2
        mouth.append([np.array([x,y+dy,front(x,y+dy)-.021]) for dy in [-.009,.009]])
    for a,b in zip(mouth,mouth[1:]):
        add_face(result,[a[0],b[0],b[1]],[83,78,43]);add_face(result,[a[0],b[1],a[1]],[83,78,43])


def build_mesh(c):
    low=np.array([-1.5,-1.95,-1.35]);high=np.array([1.5,1.95,1.15]);step=.035
    axes=[np.arange(a,b+step,step) for a,b in zip(low,high)]
    grid=np.stack(np.meshgrid(*axes,indexing='ij'),axis=-1)
    vertices,faces,_,_=marching_cubes(field(grid,c),0,spacing=(step,step,step),gradient_direction='ascent')
    vertices+=low
    stretched=vertices.copy();stretched[:,1]=np.where(vertices[:,1]>.73,.73+(vertices[:,1]-.73)*1.65,vertices[:,1])
    scale=1+.85*np.clip((vertices[:,1]-.65)/.4,0,1)
    stretched[:,0]*=scale;stretched[:,2]*=scale
    for target in range(340,219,-10):
        v,f=fast_simplification.simplify(stretched,faces,target_count=target,agg=5)
        v[:,1]=np.where(v[:,1]>.73,.73+(v[:,1]-.73)/1.65,v[:,1])
        scale=1+.85*np.clip((v[:,1]-.65)/.4,0,1)
        v[:,0]/=scale;v[:,2]/=scale
        result=color_mesh(v,f,c);add_features(result,v,f,c)
        if len(result)<=510:return result
    raise ValueError('Triangle budget exceeded')


def save_mesh(mesh,output):
    output.mkdir(parents=True,exist_ok=True)
    (output/'mesh.json').write_text(json.dumps(mesh,separators=(',',':')))
    obj=['mtllib milk_frog.mtl'];palette={};materials=[]
    for f in mesh:
        for v in f['vertices']:obj.append('v '+' '.join(map(str,v)))
    for i,f in enumerate(mesh):
        color=tuple(f['colors'][0])
        if color not in palette:
            name='color_'+str(len(palette));palette[color]=name
            value=rgb(*color);decoded=[(value>>5)*255/7,((value>>2)&7)*255/7,(value&3)*85]
            materials.extend(['newmtl '+name,'Kd '+' '.join(f'{v/255:.6f}' for v in decoded),'Ka 0 0 0','Ks 0 0 0','d 1','illum 1',''])
        obj.extend(['usemtl '+palette[color],'f '+' '.join(str(3*i+j+1) for j in range(3))])
    (output/'milk_frog.obj').write_text('\n'.join(obj)+'\n')
    (output/'milk_frog.mtl').write_text('\n'.join(materials))


def fixed_mesh(mesh):
    return [([tuple(round((c+(5.4 if j==2 else 0))*Q) for j,c in enumerate(v)) for v in f['vertices']],[],[rgb(*c) for c in f['colors']]) for f in mesh]


def render(mesh,frame,background=(243,245,243)):
    triangles=fixed_mesh(mesh);m=matrix(frame);angle=frame*math.tau/128
    camera=np.array([5.4*math.sin(angle),0,5.4*(1-math.cos(angle))])*Q
    image=np.full((480,640,3),background,dtype=np.uint8);depth=np.full((480,640),-np.inf)
    for vertices,_,colors in triangles:
        v=np.array(vertices)
        if np.dot(np.cross(v[1]-v[0],v[2]-v[0]),camera-v.mean(0))<=0:continue
        projected=[project(p,m) for p in vertices];points=np.array([p[0] for p in projected]);z=np.array([p[1] for p in projected])
        x0,y0=points.min(0);x1,y1=points.max(0)
        a,b,c=points;ab=b-a;ac=c-a;area=int(ab[0]*ac[1]-ab[1]*ac[0])
        if area==0:continue
        y,x=np.mgrid[y0:y1+1,x0:x1+1]
        u=((b[0]-x)*(c[1]-y)-(b[1]-y)*(c[0]-x))/area
        w=((c[0]-x)*(a[1]-y)-(c[1]-y)*(a[0]-x))/area;t=1-u-w
        zc=u*z[0]+w*z[1]+t*z[2]
        mask=(u>=-1e-8)&(w>=-1e-8)&(t>=-1e-8)&(zc>=depth[y0:y1+1,x0:x1+1])
        value=colors[0];color=[(value>>5)*255//7,((value>>2)&7)*255//7,(value&3)*85]
        image[y0:y1+1,x0:x1+1][mask]=color;depth[y0:y1+1,x0:x1+1][mask]=zc[mask]
    return Image.fromarray(image)


def font(size,bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/msyh'+('bd' if bold else '')+'.ttc',size)


def write_previews(entries,output):
    output.mkdir(parents=True,exist_ok=True)
    sheet=Image.new('RGB',(1800,1060),(243,245,243));draw=ImageDraw.Draw(sheet)
    draw.text((44,26),'奶蛙 / 五款三维模型',font=font(33,True),fill=(30,45,40))
    draw.text((46,77),'同一相机与比例 · RGB332 配色 · 上排正面 / 下排三分之四侧面',font=font(18),fill=(98,111,104))
    for index,(key,name,desc,mesh) in enumerate(entries):
        x=18+index*356
        for row,frame in enumerate([0,16]):
            view=render(mesh,frame).crop((170,45,470,455)).resize((326,445),Image.Resampling.NEAREST)
            sheet.paste(view,(x+15,135+row*452))
        draw.text((x+23,116),key+'  '+name,font=font(24,True),fill=(37,54,43))
        draw.text((x+23,1021),f'{len(mesh)} 个三角形',font=font(17),fill=(110,120,113))
        if index:draw.line((x-1,142,x-1,1005),fill=(217,224,216),width=1)
        card=Image.new('RGB',(1460,780),(243,245,243));d=ImageDraw.Draw(card)
        d.text((48,27),key+' / '+name,font=font(35,True),fill=(30,45,40))
        d.text((50,86),desc,font=font(21),fill=(97,111,101))
        for col,(frame,label) in enumerate([(0,'正面'),(16,'三分之四侧面'),(32,'侧面')]):
            view=render(mesh,frame).crop((155,40,485,460)).resize((440,560),Image.Resampling.NEAREST)
            card.paste(view,(30+col*480,144))
            d.text((67+col*480,703),label,font=font(20),fill=(69,86,73))
        d.text((50,747),f'真实三维网格 · {len(mesh)} 个三角形 · Q6.12 投影 / RGB332 · 软件造型预览，尚未进行 RTL 验证',font=font(16),fill=(115,125,117))
        card.save(output/f'{key}_views.png')
        render(mesh,0,(0,0,0)).save(output/f'{key}_640x480.png')
    sheet.save(output/'comparison.png')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--preview-only',action='store_true');args=parser.parse_args()
    output=ROOT/'assets/milk_frog_variants';entries=[];stats=[]
    for key,name,desc,changes in VARIANTS:
        path=output/key;c=BASE|changes
        mesh=json.loads((path/'mesh.json').read_text()) if args.preview_only else build_mesh(c)
        if not args.preview_only:save_mesh(mesh,path)
        triangles=fixed_mesh(mesh);counts=[];bounds=[]
        for frame in range(128):
            m=matrix(frame);a=frame*math.tau/128;camera=np.array([5.4*math.sin(a),0,5.4*(1-math.cos(a))])*Q;count=0
            for vertices,_,_ in triangles:
                points=np.array(vertices);pixels=[project(v,m)[0] for v in vertices];bounds.extend(pixels)
                if np.dot(np.cross(points[1]-points[0],points[2]-points[0]),camera-points.mean(0))>0:
                    p=np.array(pixels);ab=p[1]-p[0];ac=p[2]-p[0];count+=int(ab[0]*ac[1]-ab[1]*ac[0]!=0)
            counts.append(count)
        bounds=np.array(bounds)
        item=dict(version=key,name=name,description=desc,triangles=len(mesh),visible_min=min(counts),visible_max=max(counts),bounds_min=bounds.min(0).tolist(),bounds_max=bounds.max(0).tolist(),parameters=c)
        stats.append(item);entries.append((key,name,desc,mesh));print(key,len(mesh),min(counts),max(counts),flush=True)
    (output/'variants.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    write_previews(entries,ROOT/'docs/images/milk_frog_variants')
    print('Saved five meshes and comparison previews',flush=True)


if __name__=='__main__':main()
