"""Offline triangle ordering from projected overlap; no runtime depth buffer."""
import heapq

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


def coverage(points, depths, indices, colors, width=320, height=240):
    pixel_parts, triangle_parts, depth_parts, color_parts = [], [], [], []
    for index in indices:
        p = points[index].astype(np.int64)
        dx1, dy1 = p[1]-p[0]
        dx2, dy2 = p[2]-p[0]
        area = int(dx1*dy2-dy1*dx2)
        if area == 0:
            continue
        lo = np.maximum(p.min(axis=0), 0)
        hi = np.minimum(p.max(axis=0), [width-1, height-1])
        if np.any(hi < lo):
            continue
        y, x = np.mgrid[lo[1]:hi[1]+1, lo[0]:hi[0]+1]
        edges = np.array([(x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0])
                          for a, b in zip(p, np.roll(p, -1, axis=0))])
        inside = np.all(edges >= 0, axis=0) | np.all(edges <= 0, axis=0)
        x, y = x[inside], y[inside]
        if not x.size:
            continue
        z = depths[index].astype(float)
        zx = ((z[1]-z[0])*dy2-(z[2]-z[0])*dy1)/area
        zy = ((z[2]-z[0])*dx1-(z[1]-z[0])*dx2)/area
        interpolated = z[0] + zx*(x-p[0, 0]) + zy*(y-p[0, 1])
        c = np.array([[(v >> 5) & 7, (v >> 2) & 7, v & 3] for v in colors[index]], dtype=np.int64)
        c = c*4096//np.array([7, 7, 3])
        nx = (c[1]-c[0])*dy2-(c[2]-c[0])*dy1
        ny = (c[2]-c[0])*dx1-(c[1]-c[0])*dx2
        gx = np.sign(nx)*np.sign(area)*(np.abs(nx)//abs(area))
        gy = np.sign(ny)*np.sign(area)*(np.abs(ny)//abs(area))
        gx, gy = (gx+16384)%32768-16384, (gy+16384)%32768-16384
        values = c[0] + (x-p[0, 0])[:, None]*gx + (y-p[0, 1])[:, None]*gy
        values = (np.clip(values, 0, 4096)*np.array([7, 7, 3])+2048) >> 12
        shaded = ((values[:, 0] << 5) | (values[:, 1] << 2) | values[:, 2]).astype(np.uint8)
        pixel_parts.append((y*width+x).astype(np.int32))
        triangle_parts.append(np.full(x.size, index, dtype=np.int32))
        depth_parts.append(interpolated.astype(np.float32))
        color_parts.append(shaded)
    if not pixel_parts:
        return dict(pixel=np.empty(0, np.int32), triangle=np.empty(0, np.int32),
                    depth=np.empty(0, np.float32), color=np.empty(0, np.uint8))
    result = dict(pixel=np.concatenate(pixel_parts), triangle=np.concatenate(triangle_parts),
                  depth=np.concatenate(depth_parts), color=np.concatenate(color_parts))
    order = np.lexsort((result['triangle'], result['depth'], result['pixel']))
    return {name: values[order] for name, values in result.items()}


def subset_coverage(records, active):
    mask = np.isin(records['triangle'], active)
    return {name: values[mask] for name, values in records.items()}


def overlap_edges(records, triangle_count, epsilon=0.5, visible_only=False):
    pixels, ids, depth = records['pixel'], records['triangle'], records['depth']
    if not len(pixels):
        return np.empty((0, 3), dtype=np.float64)
    _, counts = np.unique(pixels, return_counts=True)
    encoded_parts = []
    if visible_only:
        first = np.flatnonzero(np.r_[True, pixels[:-1] != pixels[1:]])
        nearest = np.repeat(first, counts)
        shared = depth-depth[nearest] > epsilon
        codes, weights = np.unique(ids[shared].astype(np.int64)*triangle_count+ids[nearest[shared]], return_counts=True)
        return np.column_stack((codes//triangle_count, codes%triangle_count, weights)).astype(np.float64)
    for offset in range(1, int(counts.max())):
        shared = (pixels[:-offset] == pixels[offset:]) & (depth[offset:]-depth[:-offset] > epsilon)
        if np.any(shared):
            near, far = ids[:-offset][shared], ids[offset:][shared]
            encoded_parts.append(far.astype(np.int64)*triangle_count+near)
    if not encoded_parts:
        return np.empty((0, 3), dtype=np.float64)
    codes, weights = np.unique(np.concatenate(encoded_parts), return_counts=True)
    return np.column_stack((codes//triangle_count, codes%triangle_count, weights)).astype(np.float64)


def combine_edges(edge_sets, triangle_count):
    nonempty = [e for e in edge_sets if len(e)]
    if not nonempty:
        return np.empty((0, 3), dtype=np.float64)
    edges = np.concatenate(nonempty)
    codes = edges[:, 0].astype(np.int64)*triangle_count+edges[:, 1].astype(np.int64)
    unique, inverse = np.unique(codes, return_inverse=True)
    weight = np.bincount(inverse, weights=edges[:, 2])
    return np.column_stack((unique//triangle_count, unique%triangle_count, weight))


def _cycle_order(nodes, edges, fallback_rank):
    lookup = {int(node): i for i, node in enumerate(nodes)}
    outgoing = [[] for _ in nodes]
    incoming = [[] for _ in nodes]
    inside = np.isin(edges[:, 0], nodes) & np.isin(edges[:, 1], nodes)
    weight_in, weight_out = np.zeros(len(nodes)), np.zeros(len(nodes))
    for source, target, weight in edges[inside]:
        a, b = lookup[int(source)], lookup[int(target)]
        outgoing[a].append((b, weight)); incoming[b].append((a, weight))
        weight_out[a] += weight; weight_in[b] += weight
    active = np.ones(len(nodes), dtype=bool)
    left, right = [], []
    ranks = fallback_rank[nodes]
    for _ in nodes:
        candidates = np.flatnonzero(active & (weight_in < 1e-9))
        place_right = False
        if len(candidates):
            chosen = candidates[np.argmin(ranks[candidates])]
        else:
            candidates = np.flatnonzero(active & (weight_out < 1e-9))
            if len(candidates):
                chosen = candidates[np.argmax(ranks[candidates])]
                place_right = True
            else:
                candidates = np.flatnonzero(active)
                score = weight_out[candidates]-weight_in[candidates]
                candidates = candidates[score == score.max()]
                chosen = candidates[np.argmin(ranks[candidates])]
        (right if place_right else left).append(int(nodes[chosen]))
        active[chosen] = False
        for target, weight in outgoing[chosen]:
            weight_in[target] -= weight
        for source, weight in incoming[chosen]:
            weight_out[source] -= weight
    return left+right[::-1]


def dependency_order(indices, mean_depth, edges):
    indices = np.asarray(indices, dtype=np.int32)
    triangle_count = len(mean_depth)
    fallback = indices[np.argsort(-mean_depth[indices], kind='stable')]
    fallback_rank = np.full(triangle_count, triangle_count, dtype=np.int32)
    fallback_rank[fallback] = np.arange(len(fallback))
    if not len(edges):
        return fallback, dict(edges=0, cyclic_components=0, largest_cycle=0, violated_edges=0, violated_weight=0.0)
    lookup = np.full(triangle_count, -1, dtype=np.int32)
    lookup[indices] = np.arange(len(indices))
    source, target = edges[:, 0].astype(np.int32), edges[:, 1].astype(np.int32)
    if np.any(lookup[source] < 0) or np.any(lookup[target] < 0):
        raise ValueError('Dependency endpoints must belong to the candidate list')
    graph = coo_matrix((np.ones(len(edges)), (lookup[source], lookup[target])), shape=(len(indices), len(indices))).tocsr()
    count, labels = connected_components(graph, directed=True, connection='strong')
    components = [indices[labels == component] for component in range(count)]
    rank = np.array([fallback_rank[nodes].min() for nodes in components])
    cs, ct = labels[lookup[source]], labels[lookup[target]]
    links = np.unique(np.column_stack((cs[cs != ct], ct[cs != ct])), axis=0)
    outgoing = [[] for _ in range(count)]
    indegree = np.zeros(count, dtype=np.int32)
    for a, b in links:
        outgoing[a].append(b); indegree[b] += 1
    heap = [(int(rank[i]), i) for i in range(count) if not indegree[i]]
    heapq.heapify(heap)
    ordered = []
    while heap:
        _, component = heapq.heappop(heap)
        nodes = components[component]
        ordered.extend(nodes.tolist() if len(nodes) == 1 else _cycle_order(nodes, edges, fallback_rank))
        for target_component in outgoing[component]:
            indegree[target_component] -= 1
            if not indegree[target_component]:
                heapq.heappush(heap, (int(rank[target_component]), int(target_component)))
    if len(ordered) != len(indices):
        raise RuntimeError('Component graph did not produce a complete order')
    positions = np.full(triangle_count, -1, dtype=np.int32)
    positions[ordered] = np.arange(len(ordered))
    violated = positions[source] > positions[target]
    sizes = np.bincount(labels)
    codes = source.astype(np.int64)*triangle_count+target
    reverse = target.astype(np.int64)*triangle_count+source
    crossing_pairs = int(np.count_nonzero(np.isin(codes, reverse))//2)
    report = dict(edges=len(edges), total_weight=float(edges[:, 2].sum()),
                  cyclic_components=int(np.count_nonzero(sizes > 1)), largest_cycle=int(sizes.max()),
                  pairwise_depth_crossings=crossing_pairs, violated_edges=int(violated.sum()),
                  violated_weight=float(edges[violated, 2].sum()))
    return np.asarray(ordered, dtype=np.int32), report


def painter_image(records, order, triangle_count, clear=0x9e, width=320, height=240, epsilon=0.5, groups=None):
    """Render solely by command order; depth is used only for error measurements."""
    positions = np.full(triangle_count, -1, dtype=np.int32)
    positions[order] = np.arange(len(order))
    kept = positions[records['triangle']] >= 0
    r = {key: value[kept] for key, value in records.items()}
    image = np.full(width*height, clear, dtype=np.uint8)
    error_mask = np.zeros(width*height, dtype=bool)
    if not len(r['pixel']):
        return image.reshape(height, width), dict(covered_pixels=0, depth_violations=0, visible_color_violations=0), error_mask.reshape(height, width)
    draw = np.lexsort((positions[r['triangle']], r['pixel']))
    ends = np.r_[r['pixel'][draw][:-1] != r['pixel'][draw][1:], True]
    winner = draw[ends]
    pixels = r['pixel'][winner]
    image[pixels] = r['color'][winner]
    first = np.r_[True, r['pixel'][:-1] != r['pixel'][1:]]
    nearest = np.flatnonzero(first)
    if not np.array_equal(pixels, r['pixel'][nearest]):
        raise RuntimeError('Coverage groups do not align')
    wrong_depth = r['depth'][winner] > r['depth'][nearest]+epsilon
    wrong_color = wrong_depth & (r['color'][winner] != r['color'][nearest])
    error_mask[pixels[wrong_color]] = True
    quality = dict(covered_pixels=len(pixels), depth_violations=int(wrong_depth.sum()),
                   visible_color_violations=int(wrong_color.sum()))
    if groups is not None:
        near_group = groups[r['triangle'][nearest]]
        drawn_group = groups[r['triangle'][winner]]
        pairs, counts = np.unique(np.column_stack((near_group[wrong_color], drawn_group[wrong_color])), axis=0, return_counts=True)
        quality['cross_group_color_violations'] = int(np.count_nonzero(wrong_color & (near_group != drawn_group)))
        quality['occlusion_group_pairs'] = [dict(near_group=int(pairs[i, 0]), drawn_group=int(pairs[i, 1]), pixels=int(counts[i]))
                                             for i in np.argsort(-counts, kind='stable')]
    return image.reshape(height, width), quality, error_mask.reshape(height, width)
