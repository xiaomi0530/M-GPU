from pathlib import Path
import numpy as np
from PIL import Image
from build_vertex_lab import ROOT, scene


def render(triangles,width=640,height=480):
    expected=np.zeros((height,width),dtype=np.uint8)
    for vertices,pixels,color in triangles:
        points=np.array(pixels)
        a,b,c=points
        if (b[0]-a[0])*(c[1]-a[1])==(b[1]-a[1])*(c[0]-a[0]):
            continue
        x0,y0=points.min(axis=0);x1,y1=points.max(axis=0)
        y,x=np.mgrid[y0:y1+1,x0:x1+1]
        edges=[]
        for a,b in zip(points,np.roll(points,-1,axis=0)):
            edges.append((x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0]))
        edges=np.array(edges)
        inside=np.all(edges>=0,axis=0)|np.all(edges<=0,axis=0)
        colors=np.array([[(c>>5)&7,(c>>2)&7,c&3] for c in color],dtype=np.int64)
        colors=colors*4096//np.array([7,7,3])
        dx1,dy1=points[1]-points[0];dx2,dy2=points[2]-points[0]
        area=int(dx1*dy2-dy1*dx2)
        num_x=(colors[1]-colors[0])*dy2-(colors[2]-colors[0])*dy1
        num_y=(colors[2]-colors[0])*dx1-(colors[1]-colors[0])*dx2
        grad_x=np.sign(num_x)*np.sign(area)*(np.abs(num_x)//abs(area))
        grad_y=np.sign(num_y)*np.sign(area)*(np.abs(num_y)//abs(area))
        grad_x=(grad_x+16384)%32768-16384
        grad_y=(grad_y+16384)%32768-16384
        values=colors[0]+(x-points[0,0])[...,None]*grad_x+(y-points[0,1])[...,None]*grad_y
        values=(np.clip(values,0,4096)*np.array([7,7,3])+2048)>>12
        shaded=(values[...,0]<<5)|(values[...,1]<<2)|values[...,2]
        expected[y0:y1+1,x0:x1+1][inside]=shaded[inside]
    return expected


def to_image(actual):
    pixels=actual.astype(np.uint16)
    image=np.stack(((pixels>>5)*255//7,((pixels>>2)&7)*255//7,(pixels&3)*255//3),axis=-1).astype(np.uint8)
    return Image.fromarray(image)


def verify(output=None,frames=1,orbit=False,start=0,logo=False):
    from orbit_scene import matrix,project,order,FRAME_COUNT
    from view_framebuffer import framebuffer_size
    output=Path(output or ROOT/'out/vertex_lab')
    mesh=scene();images=[]
    if logo:
        from midiyas_logo import scene as logo_scene,matrix,project,order,groups,FRAME_COUNT
        mesh=logo_scene();group_ids=groups()
    for frame in range(frames):
        angle=min(frame+start,FRAME_COUNT-1) if logo else (frame+start)%FRAME_COUNT
        filename=f'framebuffer.hex.{frame:02d}.hex' if orbit else 'framebuffer.hex'
        actual=np.array([int(v,16) for v in (output/filename).read_text().split()],dtype=np.uint8)
        width,height=framebuffer_size(actual.size)
        actual=actual.reshape(height,width)
        triangles=[]
        for i in order(angle):
            m=matrix(angle,group_ids[i]) if logo else matrix(angle)
            triangles.append((mesh[i][0],[(p[0]*width//640,p[1]*height//480)
                for p in (project(v,m)[0] for v in mesh[i][0])],mesh[i][2]))
        expected=render(triangles,width,height)
        mismatch=np.count_nonzero(actual!=expected)
        assert mismatch==0,f'Frame {frame}: {mismatch} framebuffer pixels differ'
        images.append(to_image(actual).resize((640,480),Image.Resampling.NEAREST))
        print(f'PASS frame {frame}: {len(triangles)} triangles, all {width*height} pixels match')
    images[-1].save(output/'framebuffer.png')
    if orbit:
        duration=[round((i+1)*1.6672)*10-round(i*1.6672)*10 for i in range(len(images))]
        images[0].save(output/'orbit.gif',save_all=True,append_images=images[1:FRAME_COUNT],duration=duration[:FRAME_COUNT],loop=0,disposal=2)
        if frames>FRAME_COUNT and not logo:assert np.array_equal(np.asarray(images[0]),np.asarray(images[FRAME_COUNT]))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    parser.add_argument('--frames',type=int,default=1)
    parser.add_argument('--orbit',action='store_true')
    parser.add_argument('--start',type=int,default=0)
    parser.add_argument('--logo',action='store_true')
    args=parser.parse_args()
    verify(args.output,args.frames,args.orbit,args.start,args.logo)
