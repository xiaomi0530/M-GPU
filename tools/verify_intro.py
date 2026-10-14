from pathlib import Path
import argparse
import json
import numbers
import numpy as np
import midiyas_logo


ROOT=Path(__file__).resolve().parents[1]
Q=4096


def check_fixed(values,label):
    assert all(isinstance(v,numbers.Integral) and -131072<=int(v)<=131071 for v in values),label


def project(vertex,matrix):
    clip=[(sum(int(vertex[j])*int(matrix[j*4+i]) for j in range(3))+int(matrix[12+i])*Q)>>12 for i in range(4)]
    check_fixed(clip,('Clip overflow',vertex,matrix,clip))
    assert clip[3]>0,('Nonpositive clip W',vertex,clip)
    ndc=[(abs(v)*Q//clip[3])*(-1 if v<0 else 1) for v in clip[:3]]
    assert all(-Q<=v<=Q for v in ndc),('Outside clip volume',vertex,clip,ndc)
    point=((ndc[0]+Q)*320>>12,(Q-ndc[1])*240>>12)
    assert 0<=point[0]<640 and 0<=point[1]<480,('Outside viewport',point)
    return point


def bounds(points):
    if not points:return None
    values=np.array(points)
    return [values.min(0).tolist(),values.max(0).tolist()]


def coverage(points):
    p=np.array(points,dtype=np.int64)
    low=p.min(0);high=p.max(0)
    samples=int(np.prod(high-low+1))
    a,b,c=p
    if (b[0]-a[0])*(c[1]-a[1])==(b[1]-a[1])*(c[0]-a[0]):
        return samples,0,True
    y,x=np.mgrid[low[1]:high[1]+1,low[0]:high[0]+1]
    edges=np.array([(x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0])
        for a,b in zip(p,np.roll(p,-1,axis=0))])
    inside=np.all(edges>=0,axis=0)|np.all(edges<=0,axis=0)
    return samples,int(np.count_nonzero(inside)),False


def verify(output=None,complete_from=0,complete_to=None,text_groups=None,gpu_hz=40000000):
    mesh=midiyas_logo.scene();group_ids=midiyas_logo.groups()
    frames=midiyas_logo.FRAME_COUNT;group_count=midiyas_logo.GROUP_COUNT
    if complete_to is None:complete_to=frames-1
    assert len(mesh)==len(group_ids),('Group count mismatch',len(mesh),len(group_ids))
    assert 0<=complete_from<=complete_to<frames,('Invalid complete interval',complete_from,complete_to)
    assert gpu_hz>0,('Invalid GPU frequency',gpu_hz)
    if text_groups is None:text_groups=list(range(group_count))
    text_groups=sorted(set(text_groups))
    assert text_groups and all(0<=g<group_count for g in text_groups),('Invalid text groups',text_groups)
    coordinates=[];coefficients=[];phases=[];complete_points=[];complete_frames=[]
    for i,(vertices,_,colors) in enumerate(mesh):
        assert len(vertices)==3 and len(colors)==3,('Invalid triangle',i)
        assert isinstance(group_ids[i],numbers.Integral) and 0<=group_ids[i]<group_count,('Invalid group',i,group_ids[i])
        for vertex in vertices:
            assert len(vertex)==3,('Invalid vertex',i,vertex)
            check_fixed(vertex,('Vertex overflow',i,vertex));coordinates.extend(vertex)
        assert all(isinstance(c,numbers.Integral) and 0<=c<=255 for c in colors),('Invalid RGB332',i,colors)
    for frame in range(frames):
        matrices=[midiyas_logo.matrix(frame,group) for group in range(group_count)]
        for group,matrix in enumerate(matrices):
            assert len(matrix)==16,('Invalid matrix',frame,group)
            check_fixed(matrix,('Matrix overflow',frame,group,matrix));coefficients.extend(matrix)
        ordering=midiyas_logo.order(frame)
        assert len(set(ordering))==len(ordering),('Duplicate triangle',frame)
        points=[];text_points=[];visible_groups=set();degenerate=[];pixels=0;bbox_samples=0
        for ident in ordering:
            assert isinstance(ident,numbers.Integral) and 0<=ident<len(mesh),('Invalid triangle index',frame,ident)
            vertices=mesh[ident][0];group=group_ids[ident];matrix=matrices[group]
            projected=[project(vertex,matrix) for vertex in vertices]
            reference=[tuple(midiyas_logo.project(vertex,matrix)[0]) for vertex in vertices]
            assert projected==reference,('Projection disagreement',frame,ident,projected,reference)
            native=[(x//2,y//2) for x,y in projected]
            samples,covered,is_degenerate=coverage(native)
            bbox_samples+=samples;pixels+=covered;points.extend(native)
            if is_degenerate:degenerate.append(int(ident))
            if group in text_groups:text_points.extend(native);visible_groups.add(int(group))
        cycles=76800+512*len(ordering)+3*bbox_samples+10*pixels+1024
        phase=dict(phase=frame,triangles=len(ordering),pixels=pixels,bbox_samples=bbox_samples,
            conservative_cycles=cycles,conservative_ms=cycles*1000/gpu_hz,
            bounds=bounds(points),text_bounds=bounds(text_points),text_groups=sorted(visible_groups),
            native_degenerate=len(degenerate),degenerate_triangles=degenerate)
        if phase['text_bounds'] is not None:
            lo,hi=phase['text_bounds'];phase['text_center']=[(a+b)/2 for a,b in zip(lo,hi)]
        phases.append(phase)
        if complete_from<=frame<=complete_to:
            complete_points.extend(text_points);complete_frames.append(phase)
    worst=max(phases,key=lambda p:p['conservative_cycles'])
    degenerate_phases=[p['phase'] for p in phases if p['native_degenerate']]
    missing_groups=[dict(phase=p['phase'],missing=sorted(set(text_groups)-set(p['text_groups'])))
        for p in complete_frames if set(text_groups)-set(p['text_groups'])]
    centers=[p['text_center'] for p in complete_frames if 'text_center' in p]
    from orbit_scene import scene as model_scene,matrix as model_matrix,order as model_order,groups as model_groups,FRAME_COUNT as model_frames,GROUP_COUNT as model_group_count
    from verify_vertex_lab import render
    model_mesh=model_scene();model_group=midiyas_logo.MODEL_GROUP;model_offset=midiyas_logo.MODEL_OFFSET;model_ids=model_groups()
    final_orbit=(midiyas_logo.INTRO_NEXT_FRAME-1)%model_frames
    assert len(mesh)-model_offset==len(model_mesh),('Transition model size',len(mesh),model_offset,len(model_mesh))
    assert all(mesh[model_offset+i][0]==face[0] and mesh[model_offset+i][2]==face[2]
        for i,face in enumerate(model_mesh)),('Transition model changed',model_offset)
    assert all(group_ids[model_offset+i]==model_group+model_ids[i] for i in range(len(model_mesh))),('Transition group mapping',model_group)
    final_matrices=[midiyas_logo.matrix(frames-1,model_group+group) for group in range(model_group_count)]
    assert all(final_matrices[group]==model_matrix(final_orbit,group) for group in range(model_group_count)),('Transition matrix discontinuity',frames-1,final_orbit)
    final_order=midiyas_logo.order(frames-1)
    assert all(group_ids[i]>=model_group for i in final_order),('Logo remains at transition',final_order)
    assert final_order==[model_offset+i for i in model_order(final_orbit)],('Transition order discontinuity',final_orbit)
    final_triangles=[(mesh[i][0],[(x//2,y//2) for x,y in (project(v,final_matrices[group_ids[i]-model_group]) for v in mesh[i][0])],mesh[i][2]) for i in final_order]
    model_triangles=[(model_mesh[i][0],[(x//2,y//2) for x,y in (project(v,final_matrices[model_ids[i]]) for v in model_mesh[i][0])],model_mesh[i][2]) for i in model_order(final_orbit)]
    seam_mismatch=int(np.count_nonzero(render(final_triangles,320,240)!=render(model_triangles,320,240)))
    assert seam_mismatch==0,('Transition pixel discontinuity',seam_mismatch)
    data=dict(gpu_hz=gpu_hz,render_size=[320,240],display_size=[640,480],refresh_hz=25_000_000/(800*521),
        frame_ms=800*521/25000,triangles=len(mesh),frames=frames,groups=group_count,
        vertex_range=[int(min(coordinates)),int(max(coordinates))],
        matrix_range=[int(min(coefficients)),int(max(coefficients))],
        formula='76800 + 512*triangles + 3*bbox_samples + 10*covered_samples + 1024; conservative serialized work bound, not measured frame time',
        worst_phase=worst['phase'],worst_conservative_ms=worst['conservative_ms'],
        phases_over_refresh_budget=[p['phase'] for p in phases if p['conservative_ms']>800*521/25000],
        native_degenerate_total=sum(p['native_degenerate'] for p in phases),native_degenerate_phases=degenerate_phases,
        transition=dict(first_model_phase=midiyas_logo.MODEL_START,final_intro_phase=frames-1,final_orbit_phase=final_orbit,
            next_orbit_phase=midiyas_logo.INTRO_NEXT_FRAME,identical_model=True,identical_matrix=True,pixel_mismatch=seam_mismatch),
        complete_text=dict(first=complete_from,last=complete_to,groups=text_groups,bounds=bounds(complete_points),
            center_range=bounds(centers),missing_groups=missing_groups),phases=phases)
    output=Path(output or ROOT/'out/intro_validation/phase_budget.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(f'PASS {frames} phases: {len(mesh)} triangles, {group_count} groups, signed Q6.12 and independent projection checks')
    print(f"Worst phase {worst['phase']}: conservative {worst['conservative_ms']:.4f} ms, {worst['triangles']} triangles, {worst['pixels']} covered samples")
    print(f"Native degenerate triangles: {data['native_degenerate_total']} instances in {len(degenerate_phases)} phases")
    print(f"Selected complete-period text bounds: {data['complete_text']['bounds']}; centers: {data['complete_text']['center_range']}")
    print(f"Phases exceeding conservative refresh budget: {len(data['phases_over_refresh_budget'])}; complete-period phases missing requested groups: {len(missing_groups)}")
    print(f'Transition: intro {frames-1} matches orbit {final_orbit} at every pixel; next orbit {midiyas_logo.INTRO_NEXT_FRAME}')
    print(output)
    return data


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    parser.add_argument('--complete-from',type=int,default=0)
    parser.add_argument('--complete-to',type=int)
    parser.add_argument('--text-groups',type=int,nargs='+')
    parser.add_argument('--gpu-hz',type=int,default=40000000)
    args=parser.parse_args()
    verify(args.output,args.complete_from,args.complete_to,args.text_groups,args.gpu_hz)
