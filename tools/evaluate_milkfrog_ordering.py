import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from build_milkfrog_rom import matrices_for_frames, projection, project_triangles
from compare_milkfrog_lods import rgb332
from painter_dependencies import coverage, subset_coverage, overlap_edges, dependency_order, combine_edges, painter_image
from verify_vertex_lab import to_image, render

ROOT = Path(__file__).resolve().parents[1]
DATA = None
OUTPUT = None
EPSILON = 0.5
VISIBLE_ONLY = False


def prepare(source, output):
    files = [source/'geometry.npz', source/'matrices.npy', source/'manifest.json', ROOT/'assets/naiwa/camera.json']
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    target = output/'projection.npz'
    stamp = output/'inputs.json'
    if target.exists() and stamp.exists() and json.loads(stamp.read_text()) == hashes:
        return target
    mesh = np.load(files[0]); transforms = np.load(files[1]).astype(float)
    manifest = json.loads(files[2].read_text())
    faces = mesh['faces']; points = np.rint(mesh['vertices'][faces]*4096).astype(np.int64)
    colors = rgb332(mesh['colors']); groups = mesh['groups'].astype(np.int32)
    camera = projection(json.loads(files[3].read_text()))
    full, _, _, _ = matrices_for_frames(transforms, camera)
    pixels, visible, vertex_depth, means = [], [], [], []
    for matrix in full:
        p, v, z, ndc = project_triangles(points, groups, matrix)
        pixels.append(p.astype(np.int16)); visible.append(v)
        vertex_depth.append(ndc[:, :, 2].astype(np.int16)); means.append(z.astype(np.float32))
    pixels = np.asarray(pixels); visible = np.asarray(visible); means = np.asarray(means)
    refs = np.asarray(manifest['order_reference_frames'], dtype=np.int32)
    assignment = np.asarray(manifest['order_assignment_per_frame'], dtype=np.int32)
    order, meta = [], []
    for number, reference in enumerate(refs):
        candidates = np.flatnonzero(visible[assignment == number].any(axis=0))
        candidates = candidates[np.argsort(-means[reference, candidates], kind='stable')]
        meta.append((len(order), len(candidates))); order.extend(candidates.tolist())
    np.savez_compressed(target, pixels=pixels, visible=visible, vertex_depth=np.asarray(vertex_depth),
                        means=means, colors=colors, groups=groups, assignment=assignment, refs=refs,
                        order=np.asarray(order, dtype=np.int32), meta=np.asarray(meta, dtype=np.int32))
    stamp.write_text(json.dumps(hashes, indent=2)+'\n')
    return target


def initialize(path, output, epsilon, visible_only=False):
    global DATA, OUTPUT, EPSILON, VISIBLE_ONLY
    with np.load(path) as packed:
        DATA = {name: packed[name] for name in packed.files}
    OUTPUT, EPSILON = Path(output), epsilon
    VISIBLE_ONLY = visible_only


def analyze(frame):
    start = time.monotonic()
    count = len(DATA['groups']); cache = int(DATA['assignment'][frame])
    offset, length = DATA['meta'][cache]
    old = DATA['order'][offset:offset+length]
    records = coverage(DATA['pixels'][frame], DATA['vertex_depth'][frame], old, DATA['colors'])
    front = np.flatnonzero(DATA['visible'][frame]); front_records = subset_coverage(records, front)
    front_edges = overlap_edges(front_records, count, EPSILON, VISIBLE_ONLY)
    union_edges = overlap_edges(records, count, EPSILON, VISIBLE_ONLY)
    front_order, front_graph = dependency_order(front, DATA['means'][frame], front_edges)
    union_order, union_graph = dependency_order(old, DATA['means'][frame], union_edges)
    centroid = front[np.argsort(-DATA['means'][frame, front], kind='stable')]
    orders = dict(old_cached=old, front_centroid=centroid, front_dependency=front_order, union_dependency=union_order)
    result = dict(frame=frame, cache=cache, front_triangles=len(front), cache_triangles=len(old),
                  front_graph=front_graph, union_graph=union_graph)
    images = {}
    for name, order in orders.items():
        image, quality, mask = painter_image(records, order, count, epsilon=EPSILON)
        images[name] = image; result[name] = quality
        to_image(image).save(OUTPUT/name/f'frame_{frame:04d}.png')
        if name.endswith('dependency'):
            preview = np.asarray(to_image(image)).copy(); preview[mask] = [255, 30, 30]
            from PIL import Image
            Image.fromarray(preview).save(OUTPUT/name/f'violations_{frame:04d}.png')
    if frame == 0:
        background = [(None, [(0, 0), (319, 0), (319, 239)], [0x9e]*3),
                      (None, [(0, 0), (319, 239), (0, 239)], [0x9e]*3)]
        independent = render(background+[(None, p, c) for p, c in zip(DATA['pixels'][frame, old], DATA['colors'][old])], 320, 240)
        assert np.array_equal(independent, images['old_cached']), 'Coverage-based painter differs from independent GPU rasterizer model'
    result['old_vs_union_dependency_pixels'] = int(np.count_nonzero(images['old_cached'] != images['union_dependency']))
    result['centroid_vs_front_dependency_pixels'] = int(np.count_nonzero(images['front_centroid'] != images['front_dependency']))
    result['seconds'] = time.monotonic()-start
    np.savez_compressed(OUTPUT/'edges'/f'frame_{frame:04d}.npz', edges=union_edges,
                        front_order=front_order, union_order=union_order)
    (OUTPUT/'frames'/f'frame_{frame:04d}.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def aggregate(path, output, epsilon):
    with np.load(path) as data:
        groups, assignment, refs, old, meta, means = [data[name] for name in ('groups', 'assignment', 'refs', 'order', 'meta', 'means')]
    all_order, reports = [], []
    for cache, reference in enumerate(refs):
        assigned = np.flatnonzero(assignment == cache)
        edge_sets = []
        for frame in assigned:
            with np.load(output/'edges'/f'frame_{frame:04d}.npz') as packed:
                edge_sets.append(packed['edges'])
        edges = combine_edges(edge_sets, len(groups))
        offset, length = meta[cache]; candidates = old[offset:offset+length]
        ordered, graph = dependency_order(candidates, means[reference], edges)
        all_order.extend(ordered.tolist())
        reports.append(dict(cache=cache, reference=int(reference), frames=assigned.tolist(), **graph))
    np.save(output/'cache_order.npy', np.asarray(all_order, dtype=np.int32))
    (output/'cache_graphs.json').write_text(json.dumps(reports, indent=2)+'\n')


def evaluate_cache(frame):
    offset, length = DATA['meta'][DATA['assignment'][frame]]
    old = DATA['order'][offset:offset+length]
    updated = DATA['updated'][offset:offset+length]
    records = coverage(DATA['pixels'][frame], DATA['vertex_depth'][frame], old, DATA['colors'])
    image, quality, _ = painter_image(records, updated, len(DATA['groups']), epsilon=EPSILON)
    old_image, old_quality, _ = painter_image(records, old, len(DATA['groups']), epsilon=EPSILON)
    to_image(image).save(OUTPUT/'new_cached'/f'frame_{frame:04d}.png')
    return dict(frame=frame, updated=quality, old=old_quality, changed_pixels=int(np.count_nonzero(image != old_image)))


def initialize_cached(path, output, epsilon):
    initialize(path, output, epsilon)
    DATA['updated'] = np.load(OUTPUT/'cache_order.npy')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT/'out/milkfrog_iteration2')
    parser.add_argument('--output', type=Path, default=ROOT/'out/milkfrog_iteration2/ordering')
    parser.add_argument('--frames', default='0,84,135,225,315,360,405,413,414,417,424,472,477,527,528,535,540')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--epsilon', type=float, default=0.5)
    parser.add_argument('--reuse-edges', action='store_true')
    parser.add_argument('--edge-mode', choices=['all', 'visible'], default='visible')
    args = parser.parse_args(); args.output = args.output.resolve(); args.source = args.source.resolve()
    for name in ('edges', 'frames', 'old_cached', 'front_centroid', 'front_dependency', 'union_dependency', 'new_cached'):
        (args.output/name).mkdir(parents=True, exist_ok=True)
    path = prepare(args.source, args.output)
    frames = list(range(541)) if args.frames == 'all' else [int(f) for f in args.frames.split(',')]
    if args.reuse_edges:
        results = [json.loads((args.output/'frames'/f'frame_{f:04d}.json').read_text()) for f in frames]
    else:
        results = []
        with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize,
                                 initargs=(str(path), str(args.output), args.epsilon, args.edge_mode == 'visible')) as pool:
            for i, result in enumerate(pool.map(analyze, frames), 1):
                results.append(result)
                if len(frames) < 30 or i%30 == 0 or i == len(frames):
                    print(f'Overlap order {i}/{len(frames)} frame={result["frame"]} RGB occlusion errors: centroid={result["front_centroid"]["visible_color_violations"]}, front-dependency={result["front_dependency"]["visible_color_violations"]}, cached={result["old_cached"]["visible_color_violations"]}, union-dependency={result["union_dependency"]["visible_color_violations"]}', flush=True)
    report = dict(method='Screen-overlap plane-depth dependencies produce an offline painter order. Images are rendered only by sequential overwrites. Strongly connected components use a deterministic greedy weighted feedback-edge heuristic; every remaining violated dependency is counted, without a global-optimality claim.',
                  epsilon_q12_depth=args.epsilon, edge_mode=args.edge_mode, frames=results)
    if frames == list(range(541)):
        aggregate(path, args.output, args.epsilon)
        with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize_cached,
                                 initargs=(str(path), str(args.output), args.epsilon)) as pool:
            report['updated_cache'] = list(pool.map(evaluate_cache, frames))
        print('Completed aggregated cache evaluation for all 541 frames', flush=True)
    (args.output/'ordering_report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
