"""Source-space mouth geometry and measured expression refinement.

All surfaces remain three-dimensional and use the existing affine group format.
The painter order, never a runtime depth buffer, determines visibility on MGPU.
"""
import numpy as np


def apply_expression_fit(matrices, camera, parameters):
    """Apply anatomical mouth scales and small, smooth whole-head offsets."""
    result = matrices.copy()
    basis = np.asarray(camera['basis_rows_right_up_toward_camera'])
    scale = camera['pixels_per_unit']
    for f, (width, height, dx, dy) in enumerate(parameters):
        local = np.eye(4)
        local[1, 1], local[2, 2] = width, height
        local[2, 3] = .382 * (1 - height)
        result[f, 13] = result[f, 13] @ local
        shift = basis[0] * dx / scale - basis[1] * dy / scale
        result[f, [1, 10, 11, 12, 13, 14], :3, 3] += shift
        neck = result[f, 15]
        lower = neck[:3, :3] @ np.array([-.012, 0., .165]) + neck[:3, 3]
        upper = neck[:3, :3] @ np.array([-.012, 0., .345]) + neck[:3, 3]
        axis = upper - lower
        bridge = np.eye(4)
        bridge[:3, :3] += np.outer(shift, axis) / (axis @ axis)
        bridge[:3, 3] = lower - bridge[:3, :3] @ lower
        result[f, 15] = bridge @ neck
    return result


def neck_geometry(mesh, source_vertices, source_faces, source_colors):
    """A source-surface neck sleeve keeps shifted expressions joined to the torso."""
    tri = source_vertices[source_faces]
    edge1, edge2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    points, colors, faces = [], [], []
    sides, rings = 24, 7
    for z in np.linspace(.195, .325, rings):
        origin = np.array([0., 0., z])
        for angle in np.arange(sides) * (2 * np.pi / sides):
            direction = np.array([np.cos(angle), np.sin(angle), 0.])
            pvec = np.cross(direction, edge2)
            det = np.einsum('ij,ij->i', edge1, pvec)
            safe = np.where(np.abs(det) > 1e-12, det, 1.)
            delta = origin - tri[:, 0]
            u = np.einsum('ij,ij->i', delta, pvec) / safe
            qvec = np.cross(delta, edge1)
            v = qvec @ direction / safe
            distance = np.einsum('ij,ij->i', edge2, qvec) / safe
            hit = (np.abs(det) > 1e-12) & (u >= 0) & (v >= 0) & (u + v <= 1) & (distance > 0)
            candidates = np.flatnonzero(hit)
            if not len(candidates):
                raise ValueError('Source neck cross-section has no surface intersection')
            i = candidates[np.argmin(distance[candidates])]
            point = origin + direction * distance[i] * .995
            # The upper anterior sleeve is hidden inside the chin. Keep it behind
            # the recessed oral cavity when the head leans forward and opens wide.
            inset = np.clip((z - .275) / .050, 0., 1.)
            inset = inset * inset * (3 - 2 * inset)
            point[0] -= .018 * inset * max(0., np.cos(angle))**6
            points.append(point)
            colors.append(source_colors[i, 0] * (1 - u[i] - v[i]) +
                          source_colors[i, 1] * u[i] + source_colors[i, 2] * v[i])
    for ring in range(rings - 1):
        for j in range(sides):
            a, b = ring * sides + j, ring * sides + (j + 1) % sides
            faces.extend([[a, b, b + sides], [a, b + sides, a + sides]])
    points, faces, colors = np.asarray(points), np.asarray(faces), np.asarray(colors)
    mesh.add(points, faces, colors[faces], 15)


def fit_expression(matrices, geometry, camera, reference_masks, confidence, occluded):
    """Fit observed mouth width/height; diagnostic raster is a painter, not Z."""
    import cv2
    from scipy.ndimage import gaussian_filter1d
    ids = np.flatnonzero(geometry['groups'] == 13)
    triangles = geometry['vertices'][geometry['faces'][ids]].astype(float)
    mean = geometry['colors'][ids].mean(axis=1)
    dark = ((mean[:, 0] < 135) & (mean[:, 1] < 125) & (mean[:, 2] < 120)).astype(np.uint8)
    basis = np.asarray(camera['basis_rows_right_up_toward_camera'])
    scale = camera['pixels_per_unit']
    translation = [camera['translation_x_px'], camera['translation_y_px']]

    def measure(matrix, parameters):
        width, height = parameters
        p = triangles.copy()
        p[:, :, 1] *= width
        p[:, :, 2] = .382 + (p[:, :, 2] - .382) * height
        world = p @ matrix[:3, :3].T + matrix[:3, 3]
        local = world @ basis.T
        xy = local[:, :, :2] * [scale, -scale] + translation
        normal = np.cross(world[:, 1] - world[:, 0], world[:, 2] - world[:, 0])
        visible = np.flatnonzero(normal @ basis[2] > 0)
        order = visible[np.argsort(local[visible, :, 2].mean(1), kind='stable')]
        origin = np.floor(xy.min(axis=(0, 1))) - 1
        high = np.ceil(xy.max(axis=(0, 1))) + 1
        size = np.maximum(np.ceil((high - origin) * 4).astype(int), 1)
        image = np.zeros((size[1], size[0]), np.uint8)
        for i in order:
            cv2.fillConvexPoly(image, np.rint((xy[i] - origin) * 4).astype(np.int32), int(dark[i]))
        y, x = np.where(image)
        if len(x) < 4:
            return None
        extent = np.array([(x.max() - x.min() + 1) / 4, (y.max() - y.min() + 1) / 4])
        center = np.array([x.mean(), y.mean()]) / 4 + origin
        return extent, center

    parameters = np.tile([1., 1., 0., 0.], (len(matrices), 1))
    diagnostics = []
    for frame in range(64, len(matrices)):
        if occluded[frame] or confidence[frame] < .5:
            continue
        y, x = np.where(reference_masks[frame])
        if len(x) < 15:
            continue
        target_extent = np.array([x.max() - x.min() + 1., y.max() - y.min() + 1.])
        target_center = np.array([x.mean(), y.mean()])
        guess = np.ones(2)
        for iteration in range(5):
            measured = measure(matrices[frame, 13], guess)
            if measured is None:
                break
            extent, center = measured
            jacobian = np.zeros((2, 2))
            for j in range(2):
                offset = guess.copy()
                offset[j] += .04
                trial = measure(matrices[frame, 13], offset)
                if trial is not None:
                    jacobian[:, j] = (trial[0] - extent) / .04
            # Small prior prevents a nearly edge-on mouth from being stretched.
            lhs = np.vstack([jacobian, np.eye(2) * 2])
            rhs = np.r_[target_extent - extent, (1 - guess) * 2]
            step = np.linalg.lstsq(lhs, rhs, rcond=None)[0]
            guess = np.clip(guess + np.clip(step, -.20, .20), [.62, .30], [1.30, 1.25])
        measured = measure(matrices[frame, 13], guess)
        if measured is None:
            continue
        extent, center = measured
        shift = np.clip(target_center - center, [-7., -6.], [7., 6.])
        # The landing rotation is fitted independently; never reveal an occluded face.
        if 409 <= frame <= 416:
            shift *= 0
        parameters[frame] = [*guess, *shift]
        diagnostics.append(dict(frame=frame, target_extent=target_extent.tolist(),
                                target_center=target_center.tolist(), fitted_extent=extent.tolist(),
                                parameters=parameters[frame].tolist()))
    parameters = gaussian_filter1d(parameters, .85, axis=0, mode='nearest')
    parameters[:63] = [1, 1, 0, 0]
    parameters[411:416, 2:] = 0
    return apply_expression_fit(matrices, camera, parameters), parameters, diagnostics


def mouth_geometry(mesh, source_vertices, source_faces):
    """A recessed cavity, continuous lip rim and curved upper/lower tooth rows."""
    count = 32
    angles = np.arange(count) * (2 * np.pi / count)
    source_tri = source_vertices[source_faces]

    def contour(angle, radius=1.0):
        # The bottom narrows towards the chin; the upper arch is a broad smile.
        y = .067 * radius * np.cos(angle) * (.88 + .12 * np.sin(angle))
        height = .060 + (.020 if np.sin(angle) >= 0 else .140) * np.sin(angle)
        z = .305 + radius * height
        return y, z

    def add_front(points, faces, colors):
        points = np.asarray(points, float)
        faces = np.asarray(faces, int)
        cross = np.cross(points[faces[:, 1]] - points[faces[:, 0]],
                         points[faces[:, 2]] - points[faces[:, 0]])
        faces[cross[:, 0] < 0] = faces[cross[:, 0] < 0, ::-1]
        mesh.add(points, faces, colors, 13)

    points, faces = [], []
    for radius in (1.0, .67, .34, .015):
        for angle in angles:
            y, z = contour(angle, radius)
            arch = .020 * max(0., np.sin(angle)) + .023 * max(0., -np.sin(angle))
            x = .136 + arch * radius - .025 * (1 - radius)
            points.append([x, y, z])
    for ring in range(3):
        for j in range(count):
            a, b = ring * count + j, ring * count + (j + 1) % count
            faces.extend([[a, b, b + count], [a, b + count, a + count]])
    points.append([.111, 0, .305])
    for j in range(count):
        faces.append([3 * count + j, 3 * count + (j + 1) % count, len(points) - 1])
    add_front(points, faces, [29, 10, 10])

    points, faces, colors = [], [], []
    for ring in range(3):
        for angle in angles:
            y, z = contour(angle, 1 + .11 * ring)
            yz = source_tri[:, :, 1:]
            a, u, v = yz[:, 0], yz[:, 1] - yz[:, 0], yz[:, 2] - yz[:, 0]
            q = np.array([y, z]) - a
            det = u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]
            good = np.abs(det) > 1e-10
            b, c = np.zeros(len(det)), np.zeros(len(det))
            b[good] = (q[good, 0] * v[good, 1] - q[good, 1] * v[good, 0]) / det[good]
            c[good] = (u[good, 0] * q[good, 1] - u[good, 1] * q[good, 0]) / det[good]
            hit = good & (b >= 0) & (c >= 0) & (b + c <= 1)
            xx = source_tri[:, 0, 0] + b * (source_tri[:, 1, 0] - source_tri[:, 0, 0]) + c * (source_tri[:, 2, 0] - source_tri[:, 0, 0])
            surface = xx[hit].max() if hit.any() else .075
            front = .137 + .020 * max(0., np.sin(angle)) + .023 * max(0., -np.sin(angle))
            t = ring / 2
            points.append([front * (1 - t) + (surface + .002) * t, y, z])
            colors.append(([224, 169, 47] if ring == 0 else [235, 181, 44]))
    for ring in range(2):
        for j in range(count):
            a, b = ring * count + j, ring * count + (j + 1) % count
            faces.extend([[a, b, b + count], [a, b + count, a + count]])
    add_front(points, faces, np.asarray(colors)[faces])

    # Small separated teeth follow the curved cavity edge instead of a flat bar.
    for low, high, teeth, inner in ((.22, np.pi - .22, 9, .77),
                                   (np.pi + .40, 2 * np.pi - .40, 7, .89)):
        edges = np.linspace(low, high, teeth + 1)
        for a, b in zip(edges[:-1], edges[1:]):
            gap = .014
            points = []
            for radius, angle in ((.96, a + gap), (.96, b - gap),
                                  (inner, b - gap), (inner, a + gap)):
                y, z = contour(angle, radius)
                points.append([.141 + .026 * max(0., np.sin(angle)) +
                               .023 * max(0., -np.sin(angle)), y, z])
            add_front(points, [[0, 1, 2], [0, 2, 3]], [244, 235, 204])
    mesh.sphere([.147, 0, .249], [.006, .025, .009], [115, 32, 39], 13,
                sides=8, rings=3)
