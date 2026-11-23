import argparse
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from compare_milkfrog_lods import rgb332
from milkfrog_order_cache import construct_caches
from verify_vertex_lab import render, to_image

ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/'assets/milkfrog/v1_fixed/animation'
OUTPUT=ROOT/'assets/milkfrog/v1_fixed/rom'
Q=4096
CLEAR=0x9e
ORDER_FRAMES=np.array([0,80,135,175,210,235,270,310,385,399,405,411,417,490,26,166,65,379,414,478,449,402,518,436,421,500,540])
MOTION_CONTROL_FIELDS=('pose_keys','foot_rotation_keys','orientation_corrections','surface_anchor_keys')


def width(count):
    return max(1,(int(count)-1).bit_length())


def write_mem(path, values, bits):
    digits=(bits+3)//4
    path.write_text(''.join(f'{int(v):0{digits}x}\n' for v in values),encoding='ascii')


def projection(camera):
    m=np.array(camera['mvp_rows'],dtype=float)
    m[2,:3]=-.3*np.array(camera['basis_rows_right_up_toward_camera'])[2]
    m[2,3]=0
    return m


def load_camera(input_dir):
    """Local camera matrices are complete world-to-clip transforms, without remapping."""
    input_dir=Path(input_dir)
    snapshots=[]
    camera_path=input_dir/'camera.json'
    camera_bytes=camera_path.read_bytes() if camera_path.is_file() else None
    camera_info=json.loads(camera_bytes) if camera_bytes is not None else {}
    if camera_bytes is not None:
        snapshots.append((camera_path,camera_bytes))
    sequence_path=input_dir/'camera_matrices.npy'
    sequence_bytes=sequence_path.read_bytes() if sequence_path.is_file() else None
    if sequence_bytes is not None:
        camera=np.load(io.BytesIO(sequence_bytes),allow_pickle=False).astype(float)
        if camera.shape!=(541,4,4):
            raise ValueError('camera_matrices.npy must contain 541 world-to-clip 4x4 matrices')
        snapshots.append((sequence_path,sequence_bytes))
        mode='per_frame_world_to_clip'
    elif camera_bytes is not None:
        values=camera_info.get('mvp_rows',camera_info.get('mvp'))
        if values is None:
            raise ValueError('A static local camera.json needs mvp_rows or mvp')
        camera=np.asarray(values,dtype=float)
        if camera.shape!=(4,4):
            raise ValueError('A static camera MVP must have shape (4,4)')
        mode='static_local_world_to_clip'
    else:
        if input_dir.resolve()!=INPUT.resolve():
            raise ValueError('An independent animation input needs camera.json or camera_matrices.npy')
        camera_path=ROOT/'assets/naiwa/camera.json'
        camera_bytes=camera_path.read_bytes()
        snapshots.append((camera_path,camera_bytes))
        camera=projection(json.loads(camera_bytes))
        mode='legacy_v1_fixed_projection'
    if not np.isfinite(camera).all():
        raise ValueError('Camera matrices contain non-finite coefficients')
    metadata=dict(mode=mode,composition='C[frame] @ world_transform[frame,group]',
                  source_camera_matrices_sha256=hashlib.sha256(sequence_bytes).hexdigest() if sequence_bytes is not None else None,
                  source_camera_json_sha256=hashlib.sha256(camera_bytes).hexdigest() if camera_bytes is not None else None)
    return camera,metadata,snapshots


def motion_control_frames(refinement):
    """Keep authored motion knots; dense limb target measurements are not knots."""
    controls={}
    for name in MOTION_CONTROL_FIELDS:
        value=refinement.get(name,[])
        rows=[row for group in value.values() for row in group] if isinstance(value,dict) else value
        frames=[row['frame'] if isinstance(row,dict) else row[0] for row in rows]
        if any(int(frame)!=frame or not 0<=frame<541 for frame in frames):
            raise ValueError(f'{name} control keys must be integer frames within 0..540')
        controls[name]=sorted(set(map(int,frames)))
    return controls


def compose_matrices(transforms,camera):
    transforms=np.asarray(transforms,dtype=float)
    camera=np.asarray(camera,dtype=float)
    if transforms.ndim!=4 or transforms.shape[0]!=541 or transforms.shape[-2:]!=(4,4):
        raise ValueError('World matrices must have shape (541,groups,4,4)')
    if camera.shape==(4,4):
        result=np.einsum('ij,fGjk->fGik',camera,transforms)
    elif camera.shape==(541,4,4):
        result=np.einsum('fij,fGjk->fGik',camera,transforms)
    else:
        raise ValueError('Camera must be a static 4x4 matrix or 541 world-to-clip matrices')
    if not np.isfinite(result).all():
        raise ValueError('Composed camera/world matrices contain non-finite coefficients')
    quantized=np.rint(result*Q).astype(np.int64)
    if not np.all((-131072<=quantized)&(quantized<=131071)):
        raise ValueError('Composed MVP coefficients exceed signed 18-bit Q5.12')
    return quantized


def interpolate_matrices(direct,keys):
    key_mvp=direct[keys]
    full=[];timeline=[]
    for frame in range(541):
        k0=max(0,int(np.searchsorted(keys,frame,side='right'))-1);k1=min(k0+1,len(keys)-1)
        alpha=0 if k0==k1 else (frame-keys[k0])*256//(keys[k1]-keys[k0])
        full.append((key_mvp[k0]*(256-alpha)+key_mvp[k1]*alpha)>>8)
        timeline.append((k0,k1,alpha))
    return np.asarray(full),key_mvp,np.asarray(keys),timeline


def group_sampling_corners(points,groups,group_count):
    corners=[]
    for group in range(group_count):
        positions=points[groups==group].reshape(-1,3).astype(float)/Q
        if not len(positions):
            positions=np.zeros((1,3))
        low=positions.min(axis=0);high=positions.max(axis=0)
        corners.append([[high[0] if a else low[0],high[1] if b else low[1],high[2] if c else low[2],1]
                        for a in (0,1) for b in (0,1) for c in (0,1)])
    return np.asarray(corners)


def sampling_errors(direct,interpolated,sample_points=None):
    if sample_points is None:
        return np.max(np.abs(direct-interpolated),axis=(1,2,3)).astype(float)
    a=np.einsum('fgij,gpj->fgpi',direct,sample_points)
    b=np.einsum('fgij,gpj->fgpi',interpolated,sample_points)
    if np.any(np.abs(a[...,3])<1e-9) or np.any(np.abs(b[...,3])<1e-9):
        raise ValueError('A matrix sampling corner reaches a zero projection denominator')
    delta=(a[...,:2]/a[...,3:4]-b[...,:2]/b[...,3:4])*[160,120]
    return np.max(np.linalg.norm(delta,axis=-1),axis=(1,2))


def adaptive_key_frames(direct,mandatory,budget,sample_points,target_error):
    """Minimize the worst sampled projection error without crossing mandatory knots."""
    mandatory=sorted(mandatory)
    count=len(direct)
    interval_error=np.full((count,count),np.inf)
    interval_error[np.arange(count-1),np.arange(1,count)]=0
    direct_screen=None
    if sample_points is not None:
        clip=np.einsum('fgij,gpj->fgpi',direct,sample_points)
        if np.any(np.abs(clip[...,3])<1e-9):
            raise ValueError('A direct matrix sampling corner has a zero projection denominator')
        direct_screen=clip[...,:2]/clip[...,3:4]*[160,120]
    for low,high in zip(mandatory[:-1],mandatory[1:]):
        for start in range(low,high-1):
            for end in range(start+2,high+1):
                alpha=(np.arange(1,end-start)*256//(end-start))[:,None,None,None]
                interpolated=(direct[start]*(256-alpha)+direct[end]*alpha)>>8
                if sample_points is None:
                    error=float(np.max(np.abs(direct[start+1:end]-interpolated)))
                else:
                    clip=np.einsum('fgij,gpj->fgpi',interpolated,sample_points)
                    if np.any(np.abs(clip[...,3])<1e-9):
                        continue
                    screen=clip[...,:2]/clip[...,3:4]*[160,120]
                    error=float(np.max(np.linalg.norm(screen-direct_screen[start+1:end],axis=-1)))
                interval_error[start,end]=error
    previous=np.full(count,np.inf);previous[0]=0
    parents=[]
    for pieces in range(1,budget):
        candidates=np.maximum(previous[:,None],interval_error)
        parents.append(candidates.argmin(axis=0))
        previous=candidates.min(axis=0)
        if previous[-1]<=target_error:
            break
    if not np.isfinite(previous[-1]):
        raise ValueError('The matrix key budget cannot preserve all mandatory control nodes')
    frame=count-1;keys=[frame]
    for parent in reversed(parents):
        frame=int(parent[frame]);keys.append(frame)
    keys=list(reversed(keys))
    if keys[0]!=0 or not set(mandatory)<=set(keys) or len(set(keys))!=len(keys):
        raise RuntimeError('Adaptive matrix sampling did not preserve the required key sequence')
    return keys


def matrices_for_frames(transforms,camera,control_keys=(),sampling='legacy',key_budget=None,
                        sample_points=None,target_error=0.25):
    if len(transforms)!=541:
        raise ValueError('The scene timeline must contain exactly 541 frames')
    if any(int(frame)!=frame or not 0<=frame<541 for frame in control_keys):
        raise ValueError('Animation control keys must be integer frames within 0..540')
    mandatory={0,20,24,26,28,30,32,62,63,69,123,139,207,219,258,267,299,319,373,389,540}|set(range(390,424))|set(map(int,control_keys))
    keys=sorted(mandatory|set(range(63,541,3))) if sampling=='legacy' else sorted(mandatory)
    direct=compose_matrices(transforms,camera)
    if sampling not in ('legacy','adaptive'):
        raise ValueError('Matrix sampling must be legacy or adaptive')
    if sampling=='adaptive':
        maximum=4096//transforms.shape[1]
        budget=maximum if key_budget is None else min(maximum,key_budget)
        if len(keys)>budget:
            raise ValueError(f'{len(keys)} required motion/expression keys exceed the {budget}-key budget')
        keys=adaptive_key_frames(direct,keys,budget,sample_points,target_error)
    return interpolate_matrices(direct,keys)


def project_triangles(points,groups,matrices):
    chosen=matrices[groups]
    clip=(np.einsum('tij,tkj->tki',chosen[:,:,:3],points)+chosen[:,None,:,3]*Q)>>12
    assert np.all(clip[:,:,3]>0)
    ndc=np.sign(clip[:,:,:3])*(np.abs(clip[:,:,:3])*Q//clip[:,:,3:4])
    pixels=np.stack(((ndc[:,:,0]+Q)*320//(2*Q),(Q-ndc[:,:,1])*240//(2*Q)),axis=-1)
    a=ndc[:,1,:2]-ndc[:,0,:2];b=ndc[:,2,:2]-ndc[:,0,:2]
    front=a[:,0]*b[:,1]-a[:,1]*b[:,0]>0
    d1=pixels[:,1]-pixels[:,0];d2=pixels[:,2]-pixels[:,0]
    area=d1[:,0]*d2[:,1]-d1[:,1]*d2[:,0]
    return pixels,front&(area!=0),ndc[:,:,2].mean(axis=1),ndc


def make(preview_frames,input_dir=INPUT,output_dir=OUTPUT,review_dir=None,order_caches=26,order_entry_budget=131072,
         order_workers=4,order_iterations=3,dedicated_order_frames=None,matrix_sampling='auto',matrix_key_budget=None,
         matrix_target_error=0.25,order_seeding='auto',order_seed_count=27,order_reference_frames=None):
    input_dir=Path(input_dir).resolve();output_dir=Path(output_dir).resolve()
    legacy_input=input_dir==INPUT.resolve()
    legacy_review=ROOT/'out/naiwa/board_reference'
    review=Path(review_dir).resolve() if review_dir is not None else (legacy_review if legacy_input and output_dir==OUTPUT.resolve() else ROOT/'out'/output_dir.name/'board_reference')
    if not legacy_input and (output_dir==OUTPUT.resolve() or review==legacy_review.resolve()):
        raise ValueError('Independent animation inputs must not overwrite the V1 ROM or reference directories')
    output_dir.mkdir(parents=True,exist_ok=True)
    review.mkdir(parents=True,exist_ok=True)
    geometry_bytes=(input_dir/'geometry.npz').read_bytes();matrix_bytes=(input_dir/'matrices.npy').read_bytes()
    geometry_hash=hashlib.sha256(geometry_bytes).hexdigest();matrix_hash=hashlib.sha256(matrix_bytes).hexdigest()
    mesh=np.load(io.BytesIO(geometry_bytes));transforms=np.load(io.BytesIO(matrix_bytes)).astype(float)
    vertices=mesh['vertices'].astype(float);faces=mesh['faces'];groups=mesh['groups'].astype(int)
    colors=rgb332(mesh['colors'])
    points=np.rint(vertices[faces]*Q).astype(np.int64)
    camera,camera_metadata,camera_snapshots=load_camera(input_dir)
    eye_curve_path=input_dir/'eye_closure_curve.json'
    eye_curve_bytes=eye_curve_path.read_bytes() if eye_curve_path.is_file() else None
    eye_curve=json.loads(eye_curve_bytes) if eye_curve_bytes is not None else {}
    eye_control_keys=[item[0] for item in eye_curve.get('keyframes',[])]
    motion_path=input_dir/'motion_refinement.json'
    motion_bytes=motion_path.read_bytes() if motion_path.is_file() else None
    motion_controls=motion_control_frames(json.loads(motion_bytes) if motion_bytes is not None else {})
    control_keys=sorted(set(eye_control_keys).union(*(set(frames) for frames in motion_controls.values())))
    if matrix_sampling=='auto':
        matrix_sampling='adaptive' if camera.ndim==3 else 'legacy'
    samples=group_sampling_corners(points,groups,transforms.shape[1])
    full,key_mvp,keys,timeline=matrices_for_frames(transforms,camera,control_keys,matrix_sampling,matrix_key_budget,
                                                samples,matrix_target_error)
    if len(keys)*transforms.shape[1]>4096:
        raise ValueError(f'{len(keys)} matrix keys across {transforms.shape[1]} groups exceed the reviewed 4096-word budget; review sampling before generating ROMs')
    direct=compose_matrices(transforms,camera)
    interpolation_error=sampling_errors(direct,full,samples)
    sampling_quality=dict(mode=matrix_sampling,key_budget=4096//transforms.shape[1] if matrix_key_budget is None else matrix_key_budget,
                          allocation='Minimax dynamic programming over integer frame intervals, preserving all authored controls and dense transition frames' if matrix_sampling=='adaptive' else 'Original V1 fixed key sequence',
                          target_corner_error_px=matrix_target_error,
                          target_met=bool(interpolation_error.max()<=matrix_target_error),
                          max_group_corner_error_px=float(interpolation_error.max()),
                          p95_group_corner_error_px=float(np.percentile(interpolation_error,95)),
                          worst_frame=int(interpolation_error.argmax()),
                          per_frame_group_corner_error_px=interpolation_error.tolist(),
                          metric='Screen-space L2 error of group object-space bounding-box corners under quantized direct MVP versus RTL coefficient interpolation; conservative sample geometry, not a source-video score.')
    print(f'Matrix sampling: {len(keys)} keys, {len(keys)*transforms.shape[1]} words; maximum group-corner interpolation error {interpolation_error.max():.4f} pixels',flush=True)
    pixels=[];visibility=[];depths=[];vertex_depths=[];bounds=[]
    for f,mat in enumerate(full):
        pixel,visible,depth,ndc=project_triangles(points,groups,mat)
        minimum=pixel.min(axis=(0,1));maximum=pixel.max(axis=(0,1))
        if np.any(minimum<[0,0]) or np.any(maximum>=[320,240]) or np.any(np.abs(ndc[:,:,2])>Q):
            raise ValueError(f'Frame {f} leaves GPU clipping volume: pixel bounds {minimum}..{maximum}, depth {ndc[:,:,2].min()}..{ndc[:,:,2].max()}')
        pixels.append(pixel.astype(np.int16));visibility.append(visible);depths.append(depth)
        vertex_depths.append(ndc[:,:,2].astype(np.int16))
        bounds.append([*minimum.tolist(),*maximum.tolist()])
    pixels=np.asarray(pixels);visibility=np.asarray(visibility);depths=np.asarray(depths)
    features=full[:,:,:3,:].astype(float)/Q
    features[:,:,:,3]-=features[:,0:1,:,3]
    features[:,:,2,:]*=5
    features=features.reshape(541,-1)
    if order_seeding=='auto':
        order_seeding='uniform' if camera.ndim==3 else 'legacy'
    if order_seeding not in ('legacy','uniform'):
        raise ValueError('Order seeding must be legacy or uniform')
    if dedicated_order_frames is None:
        dedicated_order_frames=(412,413,414,415) if order_seeding=='legacy' else ()
    dedicated_order_frames=tuple(sorted(set(map(int,dedicated_order_frames))))
    if any(frame<0 or frame>=len(full) for frame in dedicated_order_frames):
        raise ValueError('Dedicated painter frames must be within the animation timeline')
    seed_frames=list(ORDER_FRAMES) if order_seeding=='legacy' else np.rint(np.linspace(0,540,order_seed_count)).astype(int).tolist()
    if order_reference_frames is not None:
        seed_frames=list(dict.fromkeys(map(int,order_reference_frames)))
        order_seeding='explicit'
    if not seed_frames or any(frame<0 or frame>=len(full) for frame in seed_frames):
        raise ValueError('Painter seed frames must be within the animation timeline')
    order_frames=np.asarray(seed_frames+[frame for frame in dedicated_order_frames if frame not in seed_frames])
    pose_distance=((features[:,None,:]-features[order_frames][None,:,:])**2).mean(axis=2)
    for frame in dedicated_order_frames:
        cache=int(np.flatnonzero(order_frames==frame)[0])
        pose_distance[:,cache]=np.inf
        pose_distance[frame,cache]=0
        pose_distance[frame,order_frames!=frame]=np.inf
    assignment=pose_distance.argmin(axis=1)
    order,meta,assignment,order_references,frame_orders,ordering_report=construct_caches(
        pixels,visibility,np.asarray(vertex_depths),depths,colors,groups,assignment,order_frames,
        entry_budget=order_entry_budget,max_caches=order_caches,iterations=order_iterations,workers=order_workers,
        dedicated_frames=dedicated_order_frames)
    lists=[order[offset:offset+count] for offset,count in meta]
    per_frame_order=[];per_frame_meta=[]
    for indices in frame_orders:
        per_frame_meta.append((len(per_frame_order),len(indices)));per_frame_order.extend(indices.tolist())
    used_faces=np.unique(order)
    face_map=np.full(len(faces),-1,dtype=np.int64);face_map[used_faces]=np.arange(len(used_faces))
    board_order=face_map[np.asarray(order)]
    attributes=np.concatenate([points[used_faces],colors[used_faces,:,None]],axis=2).reshape(-1,4)
    unique,inverse=np.unique(attributes,axis=0,return_inverse=True)
    indices=inverse.reshape(-1,3)
    original_commands=np.concatenate([points[np.asarray(order)],colors[np.asarray(order),:,None]],axis=2)
    assert np.array_equal(unique[indices[board_order]],original_commands),'ROM remapping changed a vertex attribute'
    assert np.array_equal(groups[used_faces][board_order],groups[np.asarray(order)]),'ROM remapping changed a transform group'
    vertex_words=[]
    for x,y,z,c in unique:
        vertex_words.append((((int(x)&0x3ffff)<<18 | (int(y)&0x3ffff))<<18 | (int(z)&0x3ffff))<<8 | int(c))
    vw,tw,gw,kw,ow=width(len(unique)),width(len(used_faces)),width(transforms.shape[1]),width(len(keys)),width(len(order))
    lw=width(len(order_references));cw=width(len(used_faces)+1)
    triangle_words=[((((int(a)<<vw)|int(b))<<vw)|int(c))<<gw|int(g) for (a,b,c),g in zip(indices,groups[used_faces])]
    matrix_words=[]
    for key in key_mvp:
        for matrix in key:
            word=0
            for n,coefficient in enumerate(matrix.flatten(order='F')):
                word|=(int(coefficient)&0x3ffff)<<(n*18)
            matrix_words.append(word)
    timeline_words=[((((k0<<kw)|k1)<<8|alpha)<<lw)|int(assignment[f]) for f,(k0,k1,alpha) in enumerate(timeline)]
    write_mem(output_dir/'milkfrog_vertex.mem',vertex_words,62)
    write_mem(output_dir/'milkfrog_triangle.mem',triangle_words,3*vw+gw)
    write_mem(output_dir/'milkfrog_order.mem',board_order,tw)
    write_mem(output_dir/'milkfrog_order_meta.mem',[(int(offset)<<cw)|int(count) for offset,count in meta],ow+cw)
    write_mem(output_dir/'milkfrog_matrix.mem',matrix_words,288)
    write_mem(output_dir/'milkfrog_timeline.mem',timeline_words,2*kw+8+lw)
    config=dict(VERTEX_COUNT=len(unique),TRIANGLE_COUNT=len(used_faces),GROUP_COUNT=transforms.shape[1],KEY_COUNT=len(keys),ORDER_LIST_COUNT=len(order_references),ORDER_ENTRY_COUNT=len(order),FRAME_COUNT=541)
    (output_dir/'milkfrog_config.svh').write_text(''.join(f'localparam int {k} = {v};\n' for k,v in config.items())+f"localparam logic [7:0] CLEAR_COLOR = 8'h{CLEAR:02x};\n",encoding='ascii')
    camera_provenance={key:value for key,value in camera_metadata.items() if key.startswith('source_') and value is not None}
    np.savez_compressed(review/'projection.npz',pixels=pixels,colors=colors,visibility=visibility,depths=depths,assignment=assignment,order=np.asarray(order),order_meta=np.asarray(meta),matrices=full,keys=keys,source_geometry_sha256=geometry_hash,source_matrices_sha256=matrix_hash,board_triangle_source_indices=used_faces,
                        per_frame_order=np.asarray(per_frame_order,dtype=np.int32),per_frame_order_meta=np.asarray(per_frame_meta,dtype=np.int32),**camera_provenance)
    (output_dir/'ordering_report.json').write_text(json.dumps(ordering_report,indent=2)+'\n')
    changes=[]
    for frame in preview_frames:
        ordered=lists[assignment[frame]]
        background=[(None,[(0,0),(319,0),(319,239)],[CLEAR]*3),(None,[(0,0),(319,239),(0,239)],[CLEAR]*3)]
        expected=render(background+[(None,p,c) for p,c in zip(pixels[frame,ordered],colors[ordered])],320,240)
        expected.tofile(review/f'frame_{frame:04d}.rgb332');to_image(expected).save(review/f'frame_{frame:04d}.png')
        ideal=frame_orders[frame]
        target=render(background+[(None,p,c) for p,c in zip(pixels[frame,ideal],colors[ideal])],320,240)
        differences=int(np.count_nonzero(target!=expected));changes.append(dict(frame=frame,pixels_different_from_per_frame_sort=differences,reference_order='Projected-overlap dependency order with explicit weighted cycle handling'))
        print(f'Reference frame {frame}: {len(ordered)} commands, order cache differs from per-frame dependencies by {differences} pixels',flush=True)
    bits=dict(vertex=len(unique)*62,triangle=len(used_faces)*(3*vw+gw),order=len(order)*tw,order_meta=len(meta)*(ow+cw),matrix=len(matrix_words)*288,timeline=541*(2*kw+8+lw))
    manifest=dict(configuration=config,clear_color_rgb332=CLEAR,source_video_background_rgb=[130,255,157],bit_counts=bits,total_rom_bits=sum(bits.values()),key_frames=keys.tolist(),order_reference_frames=order_references.tolist(),order_assignment_per_frame=assignment.tolist(),order_lists=[dict(reference=int(ref),offset=int(offset),count=int(count)) for ref,(offset,count) in zip(order_references,meta)],
                  screen_bounds_per_frame=bounds,sort_checks=changes,source_geometry_sha256=geometry_hash,source_matrices_sha256=matrix_hash,
                  camera=camera_metadata,source_camera_matrices_sha256=camera_metadata['source_camera_matrices_sha256'],
                  asset_compaction=dict(source_triangles=len(faces),board_triangles=len(used_faces),board_vertices=len(unique),all_ordered_vertex_attributes_and_groups_exactly_preserved=True,method='Only records never referenced by any of the 541 frames are omitted from board ROMs. Original geometry and editable Blender model remain complete.'),
                  matrix_interpolation='signed floor((A*(256-alpha)+B*alpha)/256), keyframe coefficient Q5.12',
                  matrix_sampling=dict(normal_active_step=3 if matrix_sampling=='legacy' else None,dense_every_frame_interval=[390,423],expression_control_frames=eye_control_keys,
                                       motion_control_frames=motion_controls,combined_control_frames=control_keys,matrix_words=len(matrix_words),matrix_word_budget=4096,
                                       eye_curve_sha256=hashlib.sha256(eye_curve_bytes).hexdigest() if eye_curve_bytes is not None else None,
                                       motion_refinement_sha256=hashlib.sha256(motion_bytes).hexdigest() if motion_bytes is not None else None,
                                       interpolation_quality=sampling_quality,
                                       excluded_motion_field='limb_target_keys: dense measurement targets, evaluated by the source motion fitter before matrix sampling'),
                  rendering='Existing MGPU receives three-dimensional object coordinates and a group-specific MVP; pixel rasterization and framebuffer writes are RTL.',
                  order_limit=f'{len(order_references)} painter caches are fitted to projected-overlap dependencies, with at most {order_entry_budget} entries. Every potentially visible face is retained. Remaining cyclic constraints and per-frame geometric coverage errors are recorded in ordering_report.json.',
                  ordering_algorithm='offline_overlap_dependencies_v2',order_seeding=dict(mode=order_seeding,seed_frames=list(map(int,order_frames))),dedicated_order_frames=list(dedicated_order_frames),ordering_quality={name:ordering_report[name] for name in ('initial_summary','cached_summary','per_frame_reference_summary')})
    if geometry_hash!=hashlib.sha256((input_dir/'geometry.npz').read_bytes()).hexdigest() or matrix_hash!=hashlib.sha256((input_dir/'matrices.npy').read_bytes()).hexdigest():
        raise RuntimeError('Animation input changed during ROM construction; rerun on stable inputs')
    if eye_curve_bytes is not None and eye_curve_bytes!=eye_curve_path.read_bytes():
        raise RuntimeError('Expression control keys changed during ROM construction')
    if motion_bytes is not None and motion_bytes!=motion_path.read_bytes():
        raise RuntimeError('Motion control keys changed during ROM construction')
    if any(path.read_bytes()!=content for path,content in camera_snapshots):
        raise RuntimeError('Camera input changed during ROM construction')
    (output_dir/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'configuration':config,'total_rom_bits':sum(bits.values()),'order_counts':[int(m[1]) for m in meta]},indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--preview-frames',default='0,84,135,225,315,360,405,417,540')
    parser.add_argument('--input-dir',type=Path,default=INPUT)
    parser.add_argument('--output-dir',type=Path,default=OUTPUT)
    parser.add_argument('--review-dir',type=Path)
    parser.add_argument('--order-caches',type=int,default=26)
    parser.add_argument('--order-entry-budget',type=int,default=131072)
    parser.add_argument('--order-workers',type=int,default=4)
    parser.add_argument('--order-iterations',type=int,default=3)
    parser.add_argument('--dedicated-order-frames',help='Comma-separated singleton caches; default is the V1 transition set for legacy seeds, or none for moving cameras')
    parser.add_argument('--matrix-sampling',choices=('auto','legacy','adaptive'),default='auto')
    parser.add_argument('--matrix-key-budget',type=int)
    parser.add_argument('--matrix-target-error',type=float,default=0.25)
    parser.add_argument('--order-seeding',choices=('auto','legacy','uniform'),default='auto')
    parser.add_argument('--order-seed-count',type=int,default=27)
    parser.add_argument('--order-reference-frames',help='Optional comma-separated explicit seed frames')
    args=parser.parse_args()
    if not 1<=args.order_caches<=541 or not 1<=args.order_entry_budget<=131072 or args.order_workers<1 or args.order_iterations<0 or not 1<=args.order_seed_count<=541 or args.matrix_target_error<0 or (args.matrix_key_budget is not None and args.matrix_key_budget<1):
        parser.error('Invalid painter cache count, address budget, worker count, or iteration count')
    make([int(x) for x in args.preview_frames.split(',') if x],args.input_dir,args.output_dir,args.review_dir,
         args.order_caches,args.order_entry_budget,args.order_workers,args.order_iterations,
         None if args.dedicated_order_frames is None else [int(x) for x in args.dedicated_order_frames.split(',') if x],
         args.matrix_sampling,args.matrix_key_budget,args.matrix_target_error,args.order_seeding,args.order_seed_count,
         None if args.order_reference_frames is None else [int(x) for x in args.order_reference_frames.split(',') if x])
