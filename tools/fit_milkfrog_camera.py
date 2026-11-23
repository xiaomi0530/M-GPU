import json
from pathlib import Path
import time

import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt
from scipy.optimize import differential_evolution, minimize

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'out/naiwa/standard'


def basis(yaw,elevation):
    yaw,elevation=np.deg2rad([yaw,elevation])
    n=np.array([np.sin(yaw)*np.cos(elevation),-np.cos(yaw)*np.cos(elevation),np.sin(elevation)])
    right=np.array([-n[1],n[0],0]);right/=np.linalg.norm(right)
    up=np.cross(n,right)
    return np.stack([right,up,n])


def source_mask():
    image=cv2.cvtColor(cv2.imread(str(ROOT/'assets/references/naiwa_laugh/standing_user.png')),cv2.COLOR_BGR2RGB)
    background=np.median(image[:30].reshape(-1,3),axis=0)
    binary=(np.linalg.norm(image.astype(float)-background,axis=2)>55).astype(np.uint8)
    n,labels,stats,_=cv2.connectedComponentsWithStats(binary)
    binary=(labels==1+np.argmax(stats[1:,cv2.CC_STAT_AREA])).astype(np.uint8)
    contours,_=cv2.findContours(binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(binary,contours,-1,1,-1)
    return image,binary


def project(parameters,vertices):
    yaw,elevation,scale,tx,ty=parameters
    p=vertices@basis(yaw,elevation).T
    return np.column_stack((p[:,0]*scale+tx,-p[:,1]*scale+ty))


def silhouette(parameters,vertices,faces,shape):
    p=project(parameters,vertices)
    triangles=np.rint(p[faces]).astype(np.int32)
    m=np.zeros(shape,np.uint8)
    for triangle in triangles:
        cv2.fillConvexPoly(m,triangle,1)
    return m


def fit():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    image,target=source_mask();h,w=target.shape
    data=np.load(ROOT/'assets/naiwa/candidates/A/mesh.npz');vertices=data['vertices'];faces=data['faces']
    target_edge=cv2.morphologyEx(target,cv2.MORPH_GRADIENT,np.ones((3,3),np.uint8))
    distance=distance_transform_edt(target_edge==0)
    evaluations=0;start=time.monotonic()
    def score(parameters):
        nonlocal evaluations
        evaluations+=1
        actual=silhouette(parameters,vertices,faces,target.shape)
        union=np.count_nonzero(actual|target);intersection=np.count_nonzero(actual&target)
        edge=cv2.morphologyEx(actual,cv2.MORPH_GRADIENT,np.ones((3,3),np.uint8))
        chamfer=float(distance[edge>0].mean())
        return 1-intersection/union + chamfer/150
    result=differential_evolution(score,[(115,165),(-6,14),(350,405),(140,185),(225,260)],seed=412,popsize=9,maxiter=45,tol=.0003,polish=False,workers=1)
    local=minimize(score,result.x,method='Nelder-Mead',options={'maxiter':180,'xatol':.02,'fatol':1e-6})
    parameters=local.x if local.fun<result.fun else result.x
    actual=silhouette(parameters,vertices,faces,target.shape)
    intersection=np.count_nonzero(actual&target);union=np.count_nonzero(actual|target)
    overlay=image.copy();contours,_=cv2.findContours(actual,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);cv2.drawContours(overlay,contours,-1,(240,35,45),1)
    contours,_=cv2.findContours(target,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);cv2.drawContours(overlay,contours,-1,(35,65,235),1)
    cv2.imwrite(str(OUTPUT/'camera_fit_overlay.png'),cv2.cvtColor(overlay,cv2.COLOR_RGB2BGR))
    metadata=dict(method='orthographic silhouette fitting: bounded differential evolution then Nelder-Mead; no geometry deformation',
                  parameters=dict(zip(['yaw_degrees','elevation_degrees','pixels_per_unit','translation_x_px','translation_y_px'],map(float,parameters))),
                  source_image_size=[w,h],mask_threshold=55,camera_basis=basis(*parameters[:2]).tolist(),
                  silhouette_iou=float(intersection/union),evaluations=evaluations,seconds=time.monotonic()-start,
                  limitations=['Silhouette fit estimates a camera under an orthographic assumption; it is not a recovered physical camera calibration.',
                               'The user supplied model is kept unchanged in shape. Remaining photo/model shape differences are reported, not concealed by warping.'])
    (OUTPUT/'camera_fit.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(metadata,indent=2),flush=True)


if __name__=='__main__':fit()
