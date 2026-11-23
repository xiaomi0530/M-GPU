"""Fit fixed painter caches to measured visibility dependencies within a ROM budget."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import numpy as np

from painter_dependencies import combine_edges, dependency_order, coverage, painter_image
from verify_vertex_lab import to_image

DATA = None
DESTINATION = None


def fit(data, edge_sets, assignment, frame_weights):
    count = len(data['groups']); global_faces = np.unique(data['order'])
    ranks = np.full((len(data['refs']), count), count, dtype=np.int32)
    order, meta, graphs = [], [], []
    for cache, reference in enumerate(data['refs']):
        frames = np.flatnonzero(assignment == cache)
        candidates = np.flatnonzero(data['visible'][frames].any(axis=0))
        edge_data = [np.column_stack((edge_sets[f][:, :2], edge_sets[f][:, 2]*frame_weights[f])) for f in frames]
        edges = combine_edges(edge_data, count)
        if len(edges):
            edges = edges[np.isin(edges[:, 0], candidates) & np.isin(edges[:, 1], candidates)]
        full_order, graph = dependency_order(global_faces, data['means'][reference], edges)
        ranks[cache, full_order] = np.arange(len(full_order))
        submitted = full_order[np.isin(full_order, candidates)]
        meta.append((len(order), len(submitted))); order.extend(submitted.tolist())
        graphs.append(dict(cache=cache, frames=len(frames), **graph))
    return ranks, np.asarray(order, dtype=np.int32), np.asarray(meta, dtype=np.int32), graphs


def costs(edge_sets, ranks):
    result = np.zeros((len(edge_sets), len(ranks)), dtype=np.float64)
    for frame, edges in enumerate(edge_sets):
        if len(edges):
            source, target = edges[:, 0].astype(np.int32), edges[:, 1].astype(np.int32)
            result[frame] = (ranks[:, source] > ranks[:, target]) @ edges[:, 2]
    return result


def reassign(data, assignment, score, budget, weights):
    assignment = assignment.copy()
    count = len(data['groups']); caches = len(data['refs'])
    references = np.zeros((caches, count), dtype=np.int16)
    active = [np.flatnonzero(v) for v in data['visible']]
    for frame, cache in enumerate(assignment):
        references[cache, active[frame]] += 1
    entries = int(np.count_nonzero(references))
    current = score[np.arange(len(assignment)), assignment]
    gain = (current-score.min(axis=1))*weights
    moves = 0
    dedicated = set(map(int, data.get('dedicated_frames', ())))
    for frame in np.argsort(-gain, kind='stable'):
        if int(frame) in dedicated:
            continue
        previous = assignment[frame]; faces = active[frame]
        removal = int(np.count_nonzero(references[previous, faces] == 1))
        for cache in np.argsort(score[frame], kind='stable'):
            if int(data['refs'][cache]) in dedicated:
                continue
            if score[frame, cache] >= score[frame, previous]-1e-9:
                break
            additional = int(np.count_nonzero(references[cache, faces] == 0))
            if entries+additional-removal <= budget:
                references[previous, faces] -= 1; references[cache, faces] += 1
                assignment[frame] = cache; entries += additional-removal; moves += 1
                break
    return assignment, dict(moved_frames=moves, order_entries=entries)


def fit_budget(data, edge_sets, assignment, budget, max_caches=None):
    """Merge compatible dependency sets; retain every face visible in any frame."""
    assignment = assignment.copy(); records = []
    triangle_count = len(data['groups'])
    dedicated = set(map(int, data.get('dedicated_frames', ())))
    while True:
        faces = [np.flatnonzero(data['visible'][assignment == c].any(axis=0)) for c in range(len(data['refs']))]
        entries = sum(map(len, faces))
        if entries <= budget and (max_caches is None or len(faces) <= max_caches):
            return assignment, records
        if len(faces) == 1:
            raise ValueError('One complete cache exceeds the supplied ROM budget')
        signed_edges = []
        for cache in range(len(faces)):
            edges = combine_edges([edge_sets[f] for f in np.flatnonzero(assignment == cache)], triangle_count)
            a, b = edges[:, 0].astype(np.int64), edges[:, 1].astype(np.int64)
            codes = np.minimum(a, b)*triangle_count+np.maximum(a, b)
            unique, inverse = np.unique(codes, return_inverse=True)
            net = np.bincount(inverse, weights=edges[:, 2]*np.where(a < b, 1, -1))
            signed_edges.append((unique, net))
        choices = []
        for a in range(len(faces)):
            for b in range(a+1, len(faces)):
                if int(data['refs'][a]) in dedicated or int(data['refs'][b]) in dedicated:
                    continue
                _, ia, ib = np.intersect1d(signed_edges[a][0], signed_edges[b][0], return_indices=True)
                wa, wb = signed_edges[a][1][ia], signed_edges[b][1][ib]
                conflict = float(((np.abs(wa)+np.abs(wb)-np.abs(wa+wb))/2).sum())
                saved = len(np.intersect1d(faces[a], faces[b]))
                similarity = saved/max(1, len(faces[a])+len(faces[b])-saved)
                choices.append((conflict/max(1, saved), conflict, a, b, saved, similarity))
        if not choices:
            raise ValueError('Dedicated painter caches cannot fit the supplied ROM budget')
        sufficient = [choice for choice in choices if choice[4] >= entries-budget]
        single_merge = entries > budget and bool(sufficient)
        if single_merge:
            choices = sufficient
        nearby = [choice for choice in choices if choice[5] >= 0.8]
        if nearby:
            choices = nearby
        _, conflict, a, b, saved, similarity = min(choices)
        record = dict(merged_reference_frames=[int(data['refs'][a]), int(data['refs'][b])],
                      extra_opposed_dependency_weight=conflict, saved_entries=saved,
                      visible_face_jaccard=similarity, single_merge_meets_entry_budget=single_merge,
                      entries_before=entries, entries_after=entries-saved)
        print('Budget merge '+json.dumps(record), flush=True); records.append(record)
        assignment[assignment == b] = a
        assignment[assignment > b] -= 1
        data['refs'] = np.delete(data['refs'], b)


def initialize(projection, candidate, destination):
    global DATA, DESTINATION
    with np.load(projection) as packed:
        DATA = {name: packed[name] for name in packed.files}
    with np.load(candidate) as packed:
        DATA.update({name: packed[name] for name in ('updated_order', 'updated_meta', 'updated_assignment')})
    DESTINATION = Path(destination)


def evaluate(frame):
    cache = DATA['updated_assignment'][frame]
    offset, count = DATA['updated_meta'][cache]
    order = DATA['updated_order'][offset:offset+count]
    records = coverage(DATA['pixels'][frame], DATA['vertex_depth'][frame], order, DATA['colors'])
    image, metrics, _ = painter_image(records, order, len(DATA['groups']))
    to_image(image).save(DESTINATION/'images'/f'frame_{frame:04d}.png')
    return dict(frame=frame, cache=int(cache), **metrics)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ordering', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget', type=int, default=131072)
    parser.add_argument('--iterations', type=int, default=3)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-caches', type=int)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True); (args.output/'images').mkdir(exist_ok=True)
    projection = args.ordering/'projection.npz'
    with np.load(projection) as packed:
        data = {name: packed[name] for name in packed.files}
    edge_sets = []
    for frame in range(len(data['assignment'])):
        with np.load(args.ordering/'edges'/f'frame_{frame:04d}.npz') as packed:
            edges = packed['edges']
        visible = data['visible'][frame]
        edge_sets.append(edges[visible[edges[:, 0].astype(int)] & visible[edges[:, 1].astype(int)]])
    assignment, merges = fit_budget(data, edge_sets, data['assignment'], args.budget, args.max_caches)
    weights = np.ones(len(assignment)); history = []
    best = None
    for iteration in range(args.iterations+1):
        ranks, order, meta, graphs = fit(data, edge_sets, assignment, weights)
        score = costs(edge_sets, ranks); current = score[np.arange(len(assignment)), assignment]
        statistics = dict(iteration=iteration, mean=float(current.mean()), maximum=float(current.max()),
                          percentile95=float(np.percentile(current, 95)), order_entries=len(order))
        print(json.dumps(statistics), flush=True)
        objective = statistics['percentile95']+0.15*statistics['mean']+0.05*statistics['maximum']
        if best is None or objective < best[0]:
            best = (objective, order.copy(), meta.copy(), assignment.copy(), graphs)
        if iteration < args.iterations:
            weights = np.clip(1+(current/max(1, np.median(current)))**2, 1, 8)
            assignment, change = reassign(data, assignment, score, args.budget, weights)
            statistics.update(change)
        history.append(statistics)
    _, order, meta, assignment, graphs = best
    candidate = args.output/'candidate.npz'
    np.savez_compressed(candidate, updated_order=order, updated_meta=meta, updated_assignment=assignment,
                        updated_references=data['refs'])
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize,
                             initargs=(str(projection.resolve()), str(candidate.resolve()), str(args.output.resolve()))) as pool:
        results = list(pool.map(evaluate, range(len(assignment))))
    (args.output/'optimization.json').write_text(json.dumps(dict(
        method='Weighted overlap-dependency rank fitting with frame reassignment; every move preserves the hard union-of-visible-triangles ROM-entry budget.',
        order_entries=len(order), budget=args.budget, cache_count=len(meta), merges=merges,
        history=history, cache_graphs=graphs, frames=results), indent=2)+'\n')
    print('Finished candidate painter rendering for all frames', flush=True)


if __name__ == '__main__':
    main()
