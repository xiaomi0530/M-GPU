import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import bpy
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    source = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
    source.data.calc_loop_triangles()
    triangles = len(source.data.loop_triangles)
    image = next(i for i in bpy.data.images if i.packed_file and i.size[0] > 1000)
    texture_path = output / 'source_basecolor.jpg'
    texture_path.write_bytes(image.packed_file.data)
    source_path = Path(bpy.data.filepath)
    info = dict(source=str(source_path), source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                source_vertices=len(source.data.vertices), source_triangles=triangles,
                source_texture=[image.name, *image.size], texture_sha256=hashlib.sha256(texture_path.read_bytes()).hexdigest(),
                method='Blender Decimate collapse modifier; independent reduction from the supplied source for every candidate; UVs retained.',
                variants={})
    for label, target in [('A', 4000), ('B', 8000), ('C', 16000), ('D', 32000), ('E', 64000)]:
        begin=time.monotonic(); folder=output/label;folder.mkdir(parents=True,exist_ok=True)
        bpy.ops.wm.open_mainfile(filepath=str(source_path))
        obj=next(o for o in bpy.context.scene.objects if o.type=='MESH');obj.name=f'Milkfrog_{label}_{target}'
        bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
        modifier=obj.modifiers.new('MGPU geometry reduction','DECIMATE');modifier.ratio=target/triangles;modifier.use_collapse_triangulate=True
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        mesh=obj.data;mesh.calc_loop_triangles()
        vertices=np.empty((len(mesh.vertices),3),np.float32);mesh.vertices.foreach_get('co',vertices.ravel())
        faces=np.empty((len(mesh.loop_triangles),3),np.int32);mesh.loop_triangles.foreach_get('vertices',faces.ravel())
        loops=np.empty((len(mesh.loop_triangles),3),np.int32);mesh.loop_triangles.foreach_get('loops',loops.ravel())
        uv=np.empty((len(mesh.loops),2),np.float32);mesh.uv_layers.active.data.foreach_get('uv',uv.ravel())
        normals=np.empty((len(mesh.vertices),3),np.float32);mesh.vertices.foreach_get('normal',normals.ravel())
        np.savez_compressed(folder/'mesh.npz',vertices=vertices,faces=faces,uv=uv[loops],normals=normals)
        scene=bpy.context.scene;scene.name=f'Milkfrog candidate {label}'
        obj['source_file']='milkfrog.blend';obj['target_triangles']=target
        obj['status']='Geometry fidelity candidate awaiting user selection; no animation or rig claimed.'
        scene['model_authority']='User supplied milkfrog.blend, original unchanged'
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/f'milkfrog_{label}.blend'),compress=True,copy=True)
        info['variants'][label]=dict(target_triangles=target,vertices=len(vertices),triangles=len(faces),seconds=time.monotonic()-begin)
        (output/'source_manifest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print(label,info['variants'][label],flush=True)


if __name__=='__main__':
    main()
