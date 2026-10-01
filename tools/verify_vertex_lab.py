from pathlib import Path
import numpy as np
from PIL import Image
from build_vertex_lab import ROOT, scene


def verify():
    output=ROOT/'out/vertex_lab'
    expected=np.zeros((480,640),dtype=np.uint8)
    triangles=scene()
    for vertices,pixels,color in triangles:
        points=np.array(pixels)
        x0,y0=points.min(axis=0);x1,y1=points.max(axis=0)
        y,x=np.mgrid[y0:y1+1,x0:x1+1]
        edges=[]
        for a,b in zip(points,np.roll(points,-1,axis=0)):
            edges.append((x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0]))
        edges=np.array(edges)
        inside=np.all(edges>=0,axis=0)|np.all(edges<=0,axis=0)
        expected[y0:y1+1,x0:x1+1][inside]=color
    actual=np.array([int(v,16) for v in (output/'framebuffer.hex').read_text().split()],dtype=np.uint8).reshape(480,640)
    pixels=actual.astype(np.uint16)
    image=np.stack(((pixels>>5)*255//7,((pixels>>2)&7)*255//7,(pixels&3)*255//3),axis=-1).astype(np.uint8)
    Image.fromarray(image).save(output/'framebuffer.png')
    mismatch=np.count_nonzero(actual!=expected)
    assert mismatch==0,f'{mismatch} framebuffer pixels differ'
    print(f'PASS: {len(triangles)} triangles, all 307200 framebuffer pixels match the independent edge-function renderer')


if __name__=='__main__':verify()
