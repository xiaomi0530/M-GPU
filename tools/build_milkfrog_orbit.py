import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'assets/milkfrog/v1_fixed/animation'
OUTPUT = ROOT/'assets/milkfrog/v2_orbit/animation'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blender_stage():
    import bpy
    from mathutils import Matrix
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE/'milkfrog_laugh.blend'))
    scene = bpy.context.scene
    geometry = dict(np.load(OUTPUT/'geometry.npz'))
    metadata = json.loads((OUTPUT/'metadata.json').read_text(encoding='utf8'))
    for group, name in enumerate(metadata['group_names']):
        obj = bpy.data.objects[name]
        original_mesh = obj.data
        material = original_mesh.materials[0]
        selected = geometry['groups'] == group
        faces = geometry['faces'][selected]
        used, inverse = np.unique(faces, return_inverse=True)
        mesh = bpy.data.meshes.new(name+'_orbit_v2')
        mesh.from_pydata(geometry['vertices'][used].tolist(), [], inverse.reshape(-1, 3).tolist())
        mesh.update()
        colors = mesh.color_attributes.new(name='source_color', type='FLOAT_COLOR', domain='CORNER')
        srgb = geometry['colors'][selected].reshape(-1, 3).astype(float)/255
        linear = np.where(srgb<=.04045, srgb/12.92, ((srgb+.055)/1.055)**2.4)
        colors.data.foreach_set('color', np.column_stack((linear, np.ones(len(linear)))).astype(np.float32).ravel())
        mesh.materials.append(material)
        obj.data = mesh
        if original_mesh.users == 0:
            bpy.data.meshes.remove(original_mesh)
    camera = scene.camera
    camera.animation_data_clear()
    camera.rotation_mode = 'QUATERNION'
    camera.data.type = 'ORTHO'
    settings = json.loads((OUTPUT/'camera.json').read_text(encoding='utf8'))
    camera.data.ortho_scale = settings['blender_ortho_scale']
    camera.data.clip_start = 3-1/settings['depth_scale']
    camera.data.clip_end = 3+1/settings['depth_scale']
    previous = None
    for frame, pose in enumerate(np.load(OUTPUT/'camera_world.npy')):
        matrix = Matrix(pose.tolist())
        quaternion = matrix.to_quaternion()
        if previous is not None and quaternion.dot(previous) < 0:
            quaternion.negate()
        camera.location = matrix.to_translation()
        camera.rotation_quaternion = quaternion
        camera.keyframe_insert(data_path='location', frame=frame+1)
        camera.keyframe_insert(data_path='rotation_quaternion', frame=frame+1)
        previous = quaternion.copy()
    scene.frame_start = 1
    scene.frame_end = 541
    scene.render.fps = 30
    scene['camera_motion'] = 'V2: one complete world-Z camera orbit with smoothed torso tracking and fixed orthographic scale.'
    scene.frame_set(1)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT/'milkfrog_laugh.blend'), compress=True)


def generate(elevation=None):
    from scipy.ndimage import gaussian_filter1d
    from milkfrog_orbit_geometry import adapt_orbit_geometry
    OUTPUT.mkdir(parents=True, exist_ok=True)
    reference = json.loads((ROOT/'assets/naiwa/camera.json').read_text(encoding='utf8'))
    geometry, adaptation = adapt_orbit_geometry(dict(np.load(SOURCE/'geometry.npz')))
    transforms = np.load(SOURCE/'matrices.npy').astype(float)
    assert transforms.shape == (541, 18, 4, 4)
    basis = np.asarray(reference['basis_rows_right_up_toward_camera'])
    first_target = np.asarray(reference['camera_world_target'])
    local_anchor = np.linalg.solve(transforms[0, 0], np.r_[first_target, 1.])[:3]
    targets = np.einsum('fij,j->fi', transforms[:, 0, :3, :3], local_anchor)+transforms[:, 0, :3, 3]
    targets = gaussian_filter1d(targets, 4.0, axis=0, mode='nearest')
    initial_azimuth = np.arctan2(basis[2, 1], basis[2, 0])
    elevation = np.arcsin(basis[2, 2]) if elevation is None else np.deg2rad(elevation)
    angles = np.linspace(0., 2*np.pi, 541)
    azimuth = initial_azimuth+angles
    toward = np.column_stack((np.cos(elevation)*np.cos(azimuth),
                              np.cos(elevation)*np.sin(azimuth), np.full(541, np.sin(elevation))))
    right = np.column_stack((-np.sin(azimuth), np.cos(azimuth), np.zeros(541)))
    up = np.cross(toward, right)
    bases = np.stack((right, up, toward), axis=1)
    triangles = geometry['vertices'][geometry['faces']]
    groups = geometry['groups'].astype(int)
    bounds = []
    for frame, matrix in enumerate(transforms):
        world = np.einsum('tij,tkj->tki', matrix[groups, :3, :3], triangles)+matrix[groups, None, :3, 3]
        view = (world-targets[frame])@bases[frame].T
        bounds.append(np.stack((view.min(axis=(0, 1)), view.max(axis=(0, 1)))))
    bounds = np.asarray(bounds)
    extent = np.abs(bounds).max(axis=(0, 1))
    scale = min(reference['pixels_per_unit'], 148/extent[0], 108/extent[1])
    depth_scale = .70/extent[2]
    clip = np.repeat(np.eye(4)[None], 541, axis=0)
    clip[:, :3, :3] = bases*np.array([scale/160, scale/120, -depth_scale])[None, :, None]
    clip[:, :3, 3] = -np.einsum('fij,fj->fi', clip[:, :3, :3], targets)
    camera_world = np.repeat(np.eye(4)[None], 541, axis=0)
    camera_world[:, :3, :3] = bases.transpose(0, 2, 1)
    camera_world[:, :3, 3] = targets+3*toward
    assert np.allclose(np.linalg.det(bases), 1.)
    assert np.allclose(bases@bases.transpose(0, 2, 1), np.eye(3))
    projected = bounds[:, :, :2]*np.array([scale, -scale])+np.array([160, 120])
    source_hashes = {}
    for name in ('geometry.npz', 'matrices.npy', 'eye_closure_curve.json', 'motion_refinement.json'):
        source_hashes[name] = digest(SOURCE/name)
        if name != 'geometry.npz':
            shutil.copyfile(SOURCE/name, OUTPUT/name)
            assert digest(OUTPUT/name) == source_hashes[name]
    np.savez_compressed(OUTPUT/'geometry.npz', **geometry)
    adaptation['source_geometry_sha256'] = source_hashes['geometry.npz']
    adaptation['geometry_sha256'] = digest(OUTPUT/'geometry.npz')
    (OUTPUT/'geometry_adaptation.json').write_text(json.dumps(adaptation, indent=2)+'\n', encoding='utf8')
    np.save(OUTPUT/'camera_matrices.npy', clip)
    np.save(OUTPUT/'camera_world.npy', camera_world)
    camera = dict(version='milkfrog_orbit_v2', projection='orthographic', frames=541, fps=30,
                  orbit_axis_world=[0, 0, 1], orbit_degrees=360., angle_step_degrees=360/540,
                  initial_azimuth_degrees=float(np.rad2deg(initial_azimuth)),
                  elevation_degrees=float(np.rad2deg(elevation)), pixels_per_unit=float(scale),
                  blender_ortho_scale=float(320/scale), depth_scale=float(depth_scale),
                  native_resolution=[320, 240], screen_center_xy=[160, 120],
                  target_method='Fixed source-space torso anchor transformed by unchanged pose; Gaussian sigma 4 frames; global fixed scale fitted once over the entire orbit.',
                  torso_anchor_local_xyz=local_anchor.tolist(), tracking_sigma_frames=4.,
                  camera_matrices_file='camera_matrices.npy', camera_world_file='camera_world.npy',
                  source_animation_directory=SOURCE.relative_to(ROOT).as_posix(),
                  source_animation_sha256=source_hashes,
                  camera_matrices_sha256=digest(OUTPUT/'camera_matrices.npy'),
                  camera_world_sha256=digest(OUTPUT/'camera_world.npy'),
                  model_animation_unchanged=True, geometry_adaptation=adaptation,
                  projected_extents_over_all_frames=[projected.min(axis=(0, 1)).tolist(), projected.max(axis=(0, 1)).tolist()],
                  frame_camera=[dict(frame=f, orbit_degrees=float(np.rad2deg(angles[f])), target_xyz=targets[f].tolist()) for f in range(541)])
    (OUTPUT/'camera.json').write_text(json.dumps(camera, indent=2)+'\n', encoding='utf8')
    metadata = json.loads((SOURCE/'metadata.json').read_text(encoding='utf8'))
    metadata.update(version='milkfrog_orbit_v2', camera='camera.json',
                    vertices=len(geometry['vertices']), triangles=len(geometry['faces']), geometry_adaptation=adaptation,
                    matrix_convention='Unchanged object-to-world animation matrices; downstream left-multiplies per-frame world-to-clip camera_matrices.npy.',
                    camera_motion='One 360 degree world-Z orbit over the full original 541-frame laugh animation.',
                    source_animation_sha256=source_hashes)
    (OUTPUT/'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(json.dumps({key: camera[key] for key in ('version', 'orbit_degrees', 'elevation_degrees', 'pixels_per_unit', 'projected_extents_over_all_frames', 'source_animation_sha256')}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--elevation', type=float)
    parser.add_argument('--blender-stage', action='store_true')
    parser.add_argument('--no-blender', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)
    if args.blender_stage:
        blender_stage()
    else:
        generate(args.elevation)
        if not args.no_blender:
            subprocess.run(['C:/Program Files/Blender Foundation/Blender 5.2/blender.exe', '--background',
                            '--factory-startup', '--disable-autoexec', '--threads', '4', '--python-exit-code', '1', '--python', str(Path(__file__).resolve()),
                            '--', '--blender-stage'], check=True)
