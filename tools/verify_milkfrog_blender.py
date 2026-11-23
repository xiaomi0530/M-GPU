import argparse
import hashlib
import sys
import json
from pathlib import Path

import bpy
import numpy as np

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=root/'out/naiwa/validation')
parser.add_argument('--animation-dir', type=Path, default=root/'assets/milkfrog/v1_fixed/animation')
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
assets = args.animation_dir.resolve()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
locked = {name: hashlib.sha256((assets/name).read_bytes()).hexdigest() for name in ['geometry.npz', 'matrices.npy']}
source_sha = hashlib.sha256((root/'milkfrog.blend').read_bytes()).hexdigest()
geometry = dict(np.load(assets/'geometry.npz'))
matrices = np.load(assets/'matrices.npy')
metadata = json.loads((assets/'metadata.json').read_text(encoding='utf8'))
assert source_sha == metadata['source_sha256']
bpy.ops.wm.open_mainfile(filepath=str(assets/'milkfrog_laugh.blend'))
maximum = 0.
worst = None
per_group = np.zeros(matrices.shape[1])
camera_poses = np.load(assets/'camera_world.npy') if (assets/'camera_world.npy').is_file() else None
camera_mvp = np.load(assets/'camera_matrices.npy') if camera_poses is not None else None
camera_error = 0.
camera_projection_error = 0.
for frame in range(len(matrices)):
    bpy.context.scene.frame_set(frame+1)
    if camera_poses is not None:
        camera = bpy.context.scene.camera
        actual_camera = np.asarray(camera.matrix_world, dtype=float)
        camera_error = max(camera_error, float(np.abs(actual_camera-camera_poses[frame]).max()))
        inverse = np.linalg.inv(actual_camera)
        actual_mvp = np.eye(4)
        actual_mvp[0] = inverse[0]*2/camera.data.ortho_scale
        actual_mvp[1] = inverse[1]*2*(320/240)/camera.data.ortho_scale
        actual_mvp[2] = inverse[2]*(-2/(camera.data.clip_end-camera.data.clip_start))
        actual_mvp[2, 3] -= (camera.data.clip_end+camera.data.clip_start)/(camera.data.clip_end-camera.data.clip_start)
        camera_projection_error = max(camera_projection_error, float(np.abs(actual_mvp-camera_mvp[frame]).max()))
    for group, name in enumerate(metadata['group_names']):
        actual = np.asarray(bpy.data.objects[name].matrix_world, dtype=float)
        error = float(np.abs(actual-matrices[frame, group]).max())
        per_group[group] = max(per_group[group], error)
        if error > maximum:
            maximum, worst = error, [frame, group, name]
topology = []
for group, name in enumerate(metadata['group_names']):
    mesh = bpy.data.objects[name].data
    faces = geometry['faces'][geometry['groups']==group]
    used = np.unique(faces)
    source = geometry['vertices'][used]
    actual = np.asarray([vertex.co[:] for vertex in mesh.vertices])
    local_error = float(np.abs(source-actual).max())
    expected_indices = np.searchsorted(used, faces)
    actual_indices = np.asarray([polygon.vertices[:] for polygon in mesh.polygons])
    assert np.array_equal(actual_indices, expected_indices), f'{name}: triangle connectivity differs'
    rgb = geometry['colors'][geometry['groups']==group].reshape(-1, 3).astype(float)/255
    expected_color = np.where(rgb<=.04045, rgb/12.92, ((rgb+.055)/1.055)**2.4)
    actual_color = np.asarray([corner.color[:] for corner in mesh.color_attributes['source_color'].data])
    color_error = float(np.abs(actual_color[:, :3]-expected_color).max())
    assert color_error<1e-6 and np.all(actual_color[:, 3]==1), f'{name}: source corner colors differ'
    local_triangles = geometry['vertices'][faces]
    points, inverse = np.unique(np.rint(local_triangles.reshape(-1, 3)*1e6).astype(np.int64), axis=0, return_inverse=True)
    welded = inverse.reshape(-1, 3)
    edges = np.sort(np.concatenate([welded[:, [0, 1]], welded[:, [1, 2]], welded[:, [2, 0]]]), axis=1)
    unique, count = np.unique(edges, axis=0, return_counts=True)
    boundary = unique[count==1]
    cut_edges = 0
    if len(boundary):
        endpoints = points[boundary].astype(float)/1e6
        cut_edges = int(np.count_nonzero(np.all(np.abs(endpoints[:, :, 2]+.430)<2e-6, axis=1)))
    topology.append({'group': group, 'name': name, 'vertices': len(mesh.vertices), 'triangles': len(mesh.polygons), 'expected_triangles': len(faces), 'source_local_vertex_max_error': local_error, 'weld_tolerance': 1e-6, 'boundary_edges': len(boundary), 'nonmanifold_edges_more_than_two_faces': int(np.count_nonzero(count>2)), 'unclosed_ankle_plane_edges': cut_edges, 'corner_color_loops': len(mesh.color_attributes['source_color'].data)})
    topology[-1]['triangle_connectivity_equal'] = True
    topology[-1]['source_corner_color_max_error'] = color_error
    assert len(mesh.polygons)==len(faces) and local_error<1e-6
report = {'frames': len(matrices), 'groups': matrices.shape[1], 'matrix_comparisons': len(matrices)*matrices.shape[1], 'max_abs_world_matrix_error': maximum, 'worst_frame_group': worst, 'per_group_max_error': per_group.tolist(), 'integer_frame_equivalence': maximum<2e-5, 'geometry_sha256': locked['geometry.npz'], 'matrices_sha256': locked['matrices.npy'], 'blender_sha256': hashlib.sha256((assets/'milkfrog_laugh.blend').read_bytes()).hexdigest(), 'original_source_blender_sha256': source_sha, 'representation': 'Shared vertices per mesh group; CORNER source colors; two-object SVD affine hierarchy per group, preserving nonuniform compression and shear at each integer frame.', 'topology': topology, 'topology_scope': 'Welded edge incidence diagnoses boundary and nonmanifold edges in each static group. Open facial surfaces are intentional; this does not prove absence of all animated intersections or painter cycles.'}
for name, digest in locked.items():
    assert hashlib.sha256((assets/name).read_bytes()).hexdigest()==digest
assert hashlib.sha256((root/'milkfrog.blend').read_bytes()).hexdigest()==source_sha
assert report['integer_frame_equivalence']
if camera_poses is not None:
    report.update(camera_matrices_sha256=hashlib.sha256((assets/'camera_matrices.npy').read_bytes()).hexdigest(),
                  camera_world_sha256=hashlib.sha256((assets/'camera_world.npy').read_bytes()).hexdigest(),
                  camera_max_abs_world_matrix_error=camera_error,
                  camera_max_abs_projection_matrix_error=camera_projection_error,
                  camera_integer_frame_equivalence=camera_error<2e-5 and camera_projection_error<2e-5)
    assert report['camera_integer_frame_equivalence'], 'Blender camera differs from GPU world-to-clip trajectory'
(output/'editable_blender_validation.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
print('EDITABLE_BLENDER_VERIFIED', json.dumps({key: report[key] for key in ['matrix_comparisons', 'max_abs_world_matrix_error', 'worst_frame_group', 'geometry_sha256', 'matrices_sha256', 'blender_sha256']}), flush=True)
