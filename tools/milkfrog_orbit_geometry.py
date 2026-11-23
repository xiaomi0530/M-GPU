import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


def adapt_orbit_geometry(source):
    geometry = {name: np.asarray(value).copy() for name, value in source.items()}
    vertices = geometry['vertices'].astype(float)
    faces = geometry['faces']
    groups = geometry['groups']
    colors = geometry['colors']
    mean = colors.mean(axis=1)
    lip = faces[(groups == 13) & (mean[:, 0] > 180) & (mean[:, 1] > 120) & (mean[:, 2] < 100)]
    edges = np.sort(np.concatenate((lip[:, [0, 1]], lip[:, [1, 2]], lip[:, [2, 0]])), axis=1)
    edges, counts = np.unique(edges, axis=0, return_counts=True)
    boundary = edges[counts == 1]
    adjacency = {}
    for a, b in boundary:
        adjacency.setdefault(int(a), []).append(int(b))
        adjacency.setdefault(int(b), []).append(int(a))
    if any(len(neighbors) != 2 for neighbors in adjacency.values()):
        raise ValueError('Expected closed source lip boundary loops')
    loops = []
    remaining = set(adjacency)
    while remaining:
        first = min(remaining)
        loop, previous, current = [], None, first
        while current not in loop:
            loop.append(current)
            remaining.discard(current)
            neighbors = adjacency[current]
            following = neighbors[0] if neighbors[0] != previous else neighbors[1]
            previous, current = current, following
        if current != first:
            raise ValueError('Lip boundary is not a simple closed loop')
        loops.append(np.asarray(loop, dtype=int))
    def area(loop):
        yz = vertices[loop, 1:]
        following = np.roll(yz, -1, axis=0)
        return abs(float((yz[:, 0]*following[:, 1]-yz[:, 1]*following[:, 0]).sum()))
    outer = max(loops, key=area)
    ring = vertices[outer]
    center = np.array([.025, 0., .305])
    rear = ring.copy()
    rear[:, 0] = .035
    rear[:, 1:] = center[1:] + .82 * (rear[:, 1:] - center[1:])
    count = len(ring)
    local_vertices = np.vstack((ring, rear, center))
    local_faces = []
    for j in range(count):
        k = (j + 1) % count
        local_faces.extend([[j, k, count + k], [j, count + k, count + j],
                            [count + j, count + k, 2 * count]])
    local_faces = np.asarray(local_faces, dtype=np.int32)
    points = local_vertices[local_faces]
    normals = np.cross(points[:, 1]-points[:, 0], points[:, 2]-points[:, 0])
    internal = np.array([.090, 0., .305])
    reverse = np.einsum('ij,ij->i', normals, points.mean(axis=1)-internal) < 0
    local_faces[reverse] = local_faces[reverse, ::-1]
    skin = np.isin(groups, [1, 10, 15]) & (mean[:, 0] > 140) & (mean[:, 1] > 100) & (mean[:, 2] < 130)
    source_points = vertices[faces[skin]].reshape(-1, 3)
    source_colors = colors[skin].reshape(-1, 3).astype(float)
    distance, indices = cKDTree(source_points).query(local_vertices, k=8)
    weights = 1 / np.maximum(distance, .003)**2
    skin_color = (source_colors[indices]*weights[:, :, None]).sum(axis=1)/weights.sum(axis=1)[:, None]
    skin_color[:count] = [235, 181, 44]
    skin_color = np.clip(np.rint(skin_color), 0, 255).astype(np.uint8)
    offset = len(vertices)
    geometry['vertices'] = np.vstack((vertices, local_vertices)).astype(source['vertices'].dtype)
    geometry['faces'] = np.vstack((faces, local_faces+offset)).astype(faces.dtype)
    geometry['colors'] = np.concatenate((colors, skin_color[local_faces])).astype(colors.dtype)
    geometry['groups'] = np.concatenate((groups, np.full(len(local_faces), 13, dtype=groups.dtype)))
    metadata = dict(method='Closed three-dimensional posterior oral shell attached to the existing outer lip contour, in mouth group 13. Original front cavity, teeth, source surfaces, group count and all pose matrices are unchanged.',
                    source_vertices=len(vertices), source_triangles=len(faces),
                    added_vertices=len(local_vertices), added_triangles=len(local_faces),
                    group=13, boundary_vertices=count, rear_ring_x=.035, rear_radial_scale=.82,
                    exterior_color='Existing lip color at its seam; inverse-distance samples of source-derived head/jaw/neck skin colors on the posterior shell.',
                    limitations='A V2 authored closure for side and rear viewing, not newly recovered source anatomy. Requires no-Z whole-orbit validation after cache construction.')
    return geometry, metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, default=Path('assets/milkfrog/v1_fixed/animation/geometry.npz'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    original = args.input.read_bytes()
    geometry, metadata = adapt_orbit_geometry(dict(np.load(args.input)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, **geometry)
    metadata['source_geometry_sha256'] = hashlib.sha256(original).hexdigest()
    metadata['geometry_sha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix('.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf8')
    if args.input.read_bytes() != original:
        raise RuntimeError('Source geometry changed during adaptation')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
