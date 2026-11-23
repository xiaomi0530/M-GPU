"""Construct bounded offline painter caches without modifying the GPU pipeline."""
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from optimize_milkfrog_caches import fit, fit_budget, costs, reassign
from painter_dependencies import coverage, subset_coverage, overlap_edges, dependency_order, painter_image

_DATA = None
_LISTS = None
_ASSIGNMENT = None


def _initialize(data, lists, assignment):
    global _DATA, _LISTS, _ASSIGNMENT
    _DATA, _LISTS, _ASSIGNMENT = data, lists, assignment


def _constraints(frame):
    count = len(_DATA['groups'])
    order = _LISTS[_ASSIGNMENT[frame]]
    records = coverage(_DATA['pixels'][frame], _DATA['vertex_depth'][frame], order, _DATA['colors'])
    front = np.flatnonzero(_DATA['visible'][frame])
    front_records = subset_coverage(records, front)
    front_edges = overlap_edges(front_records, count, visible_only=True)
    reference, graph = dependency_order(front, _DATA['means'][frame], front_edges)
    union_edges = overlap_edges(records, count, visible_only=True)
    visible = _DATA['visible'][frame]
    fitted_edges = union_edges[visible[union_edges[:, 0].astype(int)] & visible[union_edges[:, 1].astype(int)]]
    _, initial_quality, _ = painter_image(records, order, count, groups=_DATA['groups'])
    _, reference_quality, _ = painter_image(front_records, reference, count, groups=_DATA['groups'])
    return fitted_edges, reference, dict(frame=frame, initial=initial_quality, per_frame_reference=reference_quality,
                                        per_frame_graph=graph)


def _quality(frame):
    order = _LISTS[_ASSIGNMENT[frame]]
    records = coverage(_DATA['pixels'][frame], _DATA['vertex_depth'][frame], order, _DATA['colors'])
    _, quality, _ = painter_image(records, order, len(_DATA['groups']), groups=_DATA['groups'])
    return quality


def construct_caches(pixels, visibility, vertex_depth, means, colors, groups, assignment, references,
                     entry_budget=131072, max_caches=26, iterations=3, workers=4, dedicated_frames=()):
    references = np.asarray(references, dtype=np.int32)
    assignment = np.asarray(assignment, dtype=np.int32)
    initial_lists = []
    for cache, reference in enumerate(references):
        active = np.flatnonzero(visibility[assignment == cache].any(axis=0))
        initial_lists.append(active[np.argsort(-means[reference, active], kind='stable')])
    data = dict(pixels=pixels, visible=visibility, vertex_depth=vertex_depth, means=means,
                colors=colors, groups=groups, refs=references, order=np.concatenate(initial_lists),
                dedicated_frames=np.asarray(dedicated_frames, dtype=np.int32))
    edge_sets, frame_orders, frame_reports = [], [], []
    with ProcessPoolExecutor(max_workers=workers, initializer=_initialize,
                             initargs=(data, initial_lists, assignment)) as pool:
        for frame, (edges, ordered, report) in enumerate(pool.map(_constraints, range(len(assignment)))):
            edge_sets.append(edges); frame_orders.append(ordered); frame_reports.append(report)
            if frame%60 == 0 or frame == len(assignment)-1:
                print(f'Offline overlap constraints: {frame+1}/{len(assignment)}', flush=True)
    assignment, merges = fit_budget(data, edge_sets, assignment, entry_budget, max_caches)
    weights = np.ones(len(assignment)); history = []; best = None
    for iteration in range(iterations+1):
        ranks, order, meta, graphs = fit(data, edge_sets, assignment, weights)
        scores = costs(edge_sets, ranks)
        current = scores[np.arange(len(assignment)), assignment]
        statistics = dict(iteration=iteration, mean=float(current.mean()), maximum=float(current.max()),
                          percentile95=float(np.percentile(current, 95)), order_entries=len(order))
        objective = statistics['percentile95']+0.15*statistics['mean']+0.05*statistics['maximum']
        if best is None or objective < best[0]:
            best = (objective, order.copy(), meta.copy(), assignment.copy(), graphs)
        if iteration < iterations:
            weights = np.clip(1+(current/max(1, np.median(current)))**2, 1, 8)
            assignment, change = reassign(data, assignment, scores, entry_budget, weights)
            statistics.update(change)
        history.append(statistics)
        print(f'Offline cache iteration {iteration}: weighted violations p95={statistics["percentile95"]:.1f}, max={statistics["maximum"]:.1f}', flush=True)
    _, order, meta, assignment, graphs = best
    if len(order) > entry_budget or len(meta) > max_caches:
        raise RuntimeError('Offline painter caches exceeded their declared ROM budget')
    lists = [order[offset:offset+length] for offset, length in meta]
    for cache, candidates in enumerate(lists):
        if int(data['refs'][cache]) in dedicated_frames:
            if not np.array_equal(np.flatnonzero(assignment == cache), [data['refs'][cache]]):
                raise RuntimeError('A dedicated transition cache was shared or lost its frame')
        required = np.flatnonzero(visibility[assignment == cache].any(axis=0))
        if not np.array_equal(np.sort(candidates), required):
            raise RuntimeError('A painter cache lost or duplicated a potentially visible triangle')
    with ProcessPoolExecutor(max_workers=workers, initializer=_initialize,
                             initargs=(data, lists, assignment)) as pool:
        for frame, quality in enumerate(pool.map(_quality, range(len(assignment)))):
            frame_reports[frame]['cached'] = quality
            if frame%90 == 0 or frame == len(assignment)-1:
                print(f'Offline cached-order assessment: {frame+1}/{len(assignment)}', flush=True)
    report = dict(
        method='Offline projected-pixel overlap establishes far-to-near dependencies against the frontmost surface. Final images are painter overwrites; the GPU has no depth buffer.',
        cycle_handling='Strongly connected components use a deterministic greedy weighted feedback-edge heuristic, without a global-optimality claim. Remaining violated constraints are recorded; intersecting surfaces cannot always be represented by one triangle order.',
        cache_assignment='Iterative dependency-rank fitting with hard union-of-visible-triangles entry budget; least-conflicting dependency sets are merged when the cache count or entry budget requires it.',
        metric='Model-internal geometric coverage diagnosis using Q5.12 vertex depths on GPU integer screen triangles; not a source-video pixel-match score.',
        epsilon_q12_depth=0.5, entry_budget=entry_budget, cache_count=len(meta), order_entries=len(order),
        dedicated_transition_frames=list(map(int, dedicated_frames)),
        merges=merges, iterations=history, cache_graphs=graphs, frames=frame_reports)
    for key in ('initial', 'cached', 'per_frame_reference'):
        values = np.asarray([r[key]['visible_color_violations'] for r in frame_reports])
        report[key+'_summary'] = dict(mean=float(values.mean()), percentile95=float(np.percentile(values, 95)),
                                      maximum=int(values.max()), worst_frame=int(values.argmax()), total=int(values.sum()))
    return order, meta, assignment, data['refs'], frame_orders, report
