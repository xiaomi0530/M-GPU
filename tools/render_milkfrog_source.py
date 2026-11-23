import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT / 'milkfrog.blend')
    parser.add_argument('--camera', type=Path, default=ROOT / 'out/naiwa/standard/camera_fit.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'out/naiwa/standard')
    parser.add_argument('--blender', type=Path, default=Path('C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'))
    parser.add_argument('--blender-stage', action='store_true')
    parser.add_argument('--measure-only', action='store_true')
    return parser.parse_args(args)


def blender_stage(args):
    import bpy
    import numpy as np
    from mathutils import Matrix, Vector

    source = args.source.resolve()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    fit = json.loads(args.camera.read_text(encoding='utf8'))
    basis = np.array(fit['camera_basis'], dtype=float)
    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH' and not obj.hide_render]
    points = []
    for obj in objects:
        vertices = np.empty((len(obj.data.vertices), 3), dtype=np.float64)
        obj.data.vertices.foreach_get('co', vertices.ravel())
        world = np.array(obj.matrix_world, dtype=float)
        points.append(vertices @ world[:3, :3].T + world[:3, 3])
    world_points = np.concatenate(points)
    projected = world_points @ basis.T
    low, high = projected.min(axis=0), projected.max(axis=0)
    center = (low + high) * .5
    scale = 204.0 / (high[1] - low[1])
    tx = 160.0 - scale * center[0]
    ty = 222.0 + scale * low[1]
    z_scale = 1.6 / (high[2] - low[2])
    matrix = np.eye(4)
    matrix[0, :3] = basis[0] * (2 * scale / 320)
    matrix[0, 3] = 2 * tx / 320 - 1
    matrix[1, :3] = basis[1] * (2 * scale / 240)
    matrix[1, 3] = 1 - 2 * ty / 240
    matrix[2, :3] = -basis[2] * z_scale
    matrix[2, 3] = center[2] * z_scale
    native = dict(
        source=source.name, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        authority='User supplied source mesh; geometry and object transforms unchanged.',
        basis_rows_right_up_toward_camera=basis.tolist(),
        projected_bounds_xyz=[low.tolist(), high.tolist()],
        projected_center_xyz=center.tolist(),
        native_resolution=[320, 240], pixels_per_unit=float(scale),
        translation_x_px=float(tx), translation_y_px=float(ty),
        model_height_px=204.0, model_screen_height_fraction=.85,
        model_bottom_px=222.0, model_center_x_px=160.0,
        model_bbox_native_xyxy=[float(scale*low[0]+tx),18.0,float(scale*high[0]+tx),222.0],
        projection='sx = dot(right, world_vertex)*pixels_per_unit + translation_x_px; sy = -dot(up, world_vertex)*pixels_per_unit + translation_y_px',
        mvp_rows=matrix.tolist(),
        mvp_q5_12_column_major=np.rint(matrix*4096).astype(int).flatten(order='F').tolist(),
        blender_ortho_scale=float(320 / scale),
        camera_world_target=(center @ basis).tolist(),
        depth_ndc_range=[-.8,.8],
        pixel_convention='Continuous raster coordinates. Blender antialiases pixel centers; MGPU floors viewport coordinates and uses its own inclusive integer coverage rules.',
        reference_camera_fit='camera_fit.json',
        limitation='The view is fitted under an orthographic assumption; it is not recovered physical camera calibration.',
    )
    (output/'native_camera.json').write_text(json.dumps(native,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('NATIVE_CAMERA', json.dumps({k:native[k] for k in ('pixels_per_unit','translation_x_px','translation_y_px','model_bbox_native_xyxy','mvp_q5_12_column_major')}), flush=True)
    if args.measure_only:
        return
    for obj in objects:
        for slot in obj.material_slots:
            material = slot.material
            if material is None or material.node_tree is None:
                continue
            nodes = material.node_tree.nodes
            texture = next((node for node in nodes if node.type == 'TEX_IMAGE' and node.image), None)
            if texture is None:
                raise RuntimeError(f'No base color texture in {material.name}')
            output_node = next((node for node in nodes if node.type == 'OUTPUT_MATERIAL'), None)
            if output_node is None:
                output_node = nodes.new('ShaderNodeOutputMaterial')
            emission = nodes.new('ShaderNodeEmission')
            emission.inputs['Strength'].default_value = 1.0
            material.node_tree.links.new(texture.outputs['Color'], emission.inputs['Color'])
            material.node_tree.links.new(emission.outputs['Emission'], output_node.inputs['Surface'])
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'; scene.cycles.samples = 16
    scene.cycles.use_denoising = False
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.render.film_transparent = True
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    scene.render.dither_intensity = 0
    data = bpy.data.cameras.new('Source reference camera')
    camera = bpy.data.objects.new('Source reference camera', data)
    scene.collection.objects.link(camera); scene.camera = camera
    camera.data.type = 'ORTHO'; camera.data.ortho_scale = 320 / scale
    camera.data.clip_start = .001; camera.data.clip_end = 100
    target = center @ basis

    def set_camera(rotation_basis, target_point):
        camera.matrix_world = Matrix(rotation_basis.T.tolist()).to_4x4()
        camera.location = Vector(target_point + rotation_basis[2] * 3)

    set_camera(basis, target)
    for label, width, height in [('native',320,240),('large',960,720)]:
        scene.render.resolution_x=width; scene.render.resolution_y=height
        scene.render.filepath=str(output/f'source_{label}_rgba.png')
        bpy.ops.render.render(write_still=True)
    scene.render.resolution_x=480; scene.render.resolution_y=480
    camera.data.ortho_scale = float(1.16*(world_points[:,2].max()-world_points[:,2].min()))
    for label, rotation_angle in [('front',0),('side_left',90),('back',180),('side_right',270)]:
        angle = math.radians(rotation_angle)
        toward = np.array([math.cos(angle),math.sin(angle),.08]); toward /= np.linalg.norm(toward)
        right = np.cross(np.array([0.,0.,1.]),toward); right /= np.linalg.norm(right)
        up = np.cross(toward,right)
        orbit_basis=np.stack((right,up,toward))
        set_camera(orbit_basis,np.array([0.,0.,0.]))
        scene.render.filepath=str(output/f'source_{label}_rgba.png')
        bpy.ops.render.render(write_still=True)
    print('SOURCE_RENDER_COMPLETE', flush=True)


def composite(args):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    output=args.output.resolve()
    reference=Image.open(ROOT/'assets/references/naiwa_laugh/standing_user.png').convert('RGB')
    rgb=np.asarray(reference)
    background=tuple(int(v) for v in np.median(rgb[:30].reshape(-1,3),axis=0))
    for name in ['native','large','front','side_left','back','side_right']:
        path=output/f'source_{name}_rgba.png'
        foreground=Image.open(path).convert('RGBA')
        canvas=Image.new('RGBA',foreground.size,(*background,255))
        canvas.alpha_composite(foreground)
        canvas.convert('RGB').save(output/f'source_{name}.png')
    sheet=Image.new('RGB',(1920,528),'#20252b')
    draw=ImageDraw.Draw(sheet)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',23)
    for i,(name,label) in enumerate([('front','FRONT (+X)'),('side_left','SIDE (+Y)'),('back','BACK (-X)'),('side_right','SIDE (-Y)')]):
        sheet.paste(Image.open(output/f'source_{name}.png'),(i*480,48))
        draw.text((i*480+18,12),label,fill='white',font=font)
    sheet.save(output/'source_views.jpg',quality=95)
    meta=json.loads((output/'native_camera.json').read_text(encoding='utf8'))
    meta['composite_background_rgb']=list(background)
    meta['render_origin']='Blender Cycles emission basecolor baseline; not MGPU RTL output.'
    meta['source_mesh_preserved']=True
    meta['source_sha256_after']=hashlib.sha256(args.source.read_bytes()).hexdigest()
    assert meta['source_sha256']==meta['source_sha256_after']
    (output/'native_camera.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def main():
    args=parse_args()
    if args.blender_stage:
        blender_stage(args)
        return
    args.output.mkdir(parents=True,exist_ok=True)
    command=[str(args.blender),'--background','--factory-startup','--disable-autoexec',str(args.source.resolve()),
             '--threads','8','--python',str(Path(__file__).resolve()),'--','--blender-stage','--source',str(args.source.resolve()),
             '--camera',str(args.camera.resolve()),'--output',str(args.output.resolve())]
    if args.measure_only:
        command.append('--measure-only')
    subprocess.run(command,check=True)
    if not args.measure_only:
        composite(args)
    # Keep the reproducible camera outside disposable render output.
    from PIL import Image
    import numpy as np
    camera = json.loads((args.output/'native_camera.json').read_text(encoding='utf8'))
    if 'composite_background_rgb' not in camera:
        reference = np.asarray(Image.open(ROOT/'assets/references/naiwa_laugh/standing_user.png').convert('RGB'))
        camera['composite_background_rgb'] = np.median(reference[:30].reshape(-1,3),axis=0).astype(int).tolist()
    asset = ROOT/'assets/naiwa/camera.json'
    asset.parent.mkdir(parents=True,exist_ok=True)
    asset.write_text(json.dumps(camera,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


if __name__=='__main__':
    main()
