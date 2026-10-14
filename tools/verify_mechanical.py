from pathlib import Path
import argparse
import json
import numbers
import numpy as np
import orbit_scene
from verify_intro import check_fixed,project,bounds,coverage
from verify_vertex_lab import render


ROOT=Path(__file__).resolve().parents[1]


def verify(output=None,gpu_hz=40000000):
    mesh=orbit_scene.scene();group_ids=orbit_scene.groups()
    frames=orbit_scene.FRAME_COUNT;groups=orbit_scene.GROUP_COUNT;stride=orbit_scene.KEY_STRIDE
    assert frames%stride==0 and stride==8,('Invalid key spacing',frames,stride)
    assert len(mesh)==len(group_ids) and gpu_hz>0
    vertices=[];coefficients=[];phases=[];previous=None;first=None;step_max=0
    for ident,(points,_,colors) in enumerate(mesh):
        assert len(points)==3 and len(colors)==3,('Invalid triangle',ident)
        assert isinstance(group_ids[ident],numbers.Integral) and 0<=group_ids[ident]<groups
        for vertex in points:
            assert len(vertex)==3
            check_fixed(vertex,('Vertex overflow',ident,vertex));vertices.extend(vertex)
        assert all(isinstance(c,numbers.Integral) and 0<=c<=255 for c in colors)
    for frame in range(frames):
        matrices=[]
        for group in range(groups):
            key,fraction=divmod(frame,stride)
            a=orbit_scene.key_matrix(key,group);b=orbit_scene.key_matrix((key+1)%(frames//stride),group)
            check_fixed(a,('Key matrix overflow',key,group));check_fixed(b,('Key matrix overflow',key+1,group))
            matrix=[int(x)+(int(y)-int(x))*fraction//stride for x,y in zip(a,b)]
            assert len(matrix)==16 and matrix==orbit_scene.matrix(frame,group),('Matrix interpolation',frame,group)
            check_fixed(matrix,('Matrix overflow',frame,group));coefficients.extend(matrix);matrices.append(matrix)
        projected=[]
        for ident,(points,_,_) in enumerate(mesh):
            matrix=matrices[group_ids[ident]]
            screen=[project(vertex,matrix) for vertex in points]
            assert screen==[tuple(orbit_scene.project(vertex,matrix)[0]) for vertex in points],('Projection disagreement',frame,ident)
            projected.append(screen)
        points=np.array(projected)
        if previous is not None:step_max=max(step_max,int(np.max(np.abs(points-previous))))
        else:first=points
        previous=points
        order=orbit_scene.order(frame)
        assert len(order)==len(set(order)) and all(isinstance(i,numbers.Integral) and 0<=i<len(mesh) for i in order)
        visible=[];pixels=0;bbox_samples=0;degenerate=[]
        for ident in order:
            p=projected[ident]
            a,b,c=p
            assert (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])>0,('Backface in order',frame,ident)
            native=[(x//2,y//2) for x,y in p]
            samples,covered,is_degenerate=coverage(native)
            bbox_samples+=samples;pixels+=covered;visible.extend(native)
            if is_degenerate:degenerate.append(int(ident))
        cycles=76800+512*len(order)+3*bbox_samples+10*pixels+1024
        phases.append(dict(phase=frame,triangles=len(order),pixels=pixels,bbox_samples=bbox_samples,
            conservative_cycles=cycles,conservative_ms=cycles*1000/gpu_hz,bounds=bounds(visible),
            native_degenerate=len(degenerate),degenerate_triangles=degenerate))
    wrap_step=int(np.max(np.abs(first-previous)))
    step_max=max(step_max,wrap_step)
    assert all(orbit_scene.matrix(frames,group)==orbit_scene.matrix(0,group) for group in range(groups))
    assert orbit_scene.order(frames)==orbit_scene.order(0)
    def image(frame):
        triangles=[]
        for i in orbit_scene.order(frame):
            matrix=orbit_scene.matrix(frame,group_ids[i])
            triangles.append((mesh[i][0],[(x//2,y//2) for x,y in (project(v,matrix) for v in mesh[i][0])],mesh[i][2]))
        return render(triangles,320,240)
    repeat_mismatch=int(np.count_nonzero(image(0)!=image(frames)))
    assert repeat_mismatch==0,('Loop repeat mismatch',repeat_mismatch)
    worst=max(phases,key=lambda p:p['conservative_cycles'])
    data=dict(gpu_hz=gpu_hz,render_size=[320,240],display_size=[640,480],refresh_hz=25_000_000/(800*521),
        frame_ms=800*521/25000,triangles=len(mesh),frames=frames,groups=groups,key_stride=stride,
        matrix_keys=frames//stride*groups,uncompressed_matrix_count=frames*groups,
        vertex_range=[int(min(vertices)),int(max(vertices))],matrix_range=[int(min(coefficients)),int(max(coefficients))],
        formula='76800 + 512*triangles + 3*bbox_samples + 10*covered_samples + 1024; conservative serialized work bound, not measured frame time',
        visible_min=min(p['triangles'] for p in phases),visible_max=max(p['triangles'] for p in phases),
        worst_phase=worst['phase'],worst_conservative_ms=worst['conservative_ms'],
        phases_over_refresh_budget=[p['phase'] for p in phases if p['conservative_ms']>800*521/25000],
        native_degenerate_total=sum(p['native_degenerate'] for p in phases),
        loop=dict(repeated_frame_pixel_mismatch=repeat_mismatch,max_vertex_step_display_pixels=step_max,
            wrap_vertex_step_display_pixels=wrap_step,period_ms=frames*800*521/25000),phases=phases)
    output=Path(output or ROOT/'out/mechanical_core_60fps/phase_budget.json')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(f'PASS {frames} phases: {len(mesh)} triangles, {groups} groups, signed Q6.12, independent interpolation and projection')
    print(f"Visible {data['visible_min']}..{data['visible_max']}; worst phase {worst['phase']}: conservative {worst['conservative_ms']:.4f} ms")
    print(f"Phases exceeding refresh budget: {len(data['phases_over_refresh_budget'])}; native degenerate instances: {data['native_degenerate_total']}")
    print(f'Loop identical at phases 0/{frames}; wrap maximum vertex step {wrap_step} display pixels; maximum step {step_max}')
    print(output)
    return data


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    parser.add_argument('--gpu-hz',type=int,default=40000000)
    args=parser.parse_args();verify(args.output,args.gpu_hz)
