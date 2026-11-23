import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import minimize
from scipy.spatial.transform import Rotation, RotationSpline

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'out/milkfrog_iteration2'
OUTPUT = SNAPSHOT / 'motion'
CONFIG = ROOT / 'assets/milkfrog/v1_fixed/animation/motion_refinement.json'
HEAD_GROUPS = [1, 10, 11, 12, 13, 14, 15]
UPPER_GROUPS = [0, 1, 2, 3, 4, 5, 10, 11, 12, 13, 14, 15]


def rotation(axis, degrees):
    axis = np.asarray(axis, float)
    norm = np.linalg.norm(axis)
    return np.eye(3) if norm < 1e-12 else Rotation.from_rotvec(axis / norm * np.deg2rad(degrees)).as_matrix()


def affine(rot=None, translation=None):
    result = np.eye(4)
    if rot is not None:
        result[:3, :3] = rot
    if translation is not None:
        result[:3, 3] = translation
    return result


def around(rot, pivot):
    return affine(rot, pivot - rot @ pivot)


def polar(matrix):
    u, _, vt = np.linalg.svd(matrix)
    r = u @ vt
    if np.linalg.det(r) < 0:
        u[:, -1] *= -1
        r = u @ vt
    return r


def align_segment(start, end, new_start, new_end):
    a = end - start
    b = new_end - new_start
    a /= np.linalg.norm(a)
    b /= np.linalg.norm(b)
    cross = np.cross(a, b)
    angle = np.arctan2(np.linalg.norm(cross), np.clip(a @ b, -1, 1))
    if np.linalg.norm(cross) < 1e-10:
        r = np.eye(3)
    else:
        r = rotation(cross, np.rad2deg(angle))
    return affine(r, new_start - r @ start)


def project(points, camera):
    basis = np.asarray(camera['basis_rows_right_up_toward_camera'])
    p = points @ basis.T
    return p[..., :2] * [camera['pixels_per_unit'], -camera['pixels_per_unit']] + [camera['translation_x_px'], camera['translation_y_px']]


def world_points(geometry, matrices):
    points = geometry['vertices'][geometry['faces']]
    m = matrices[geometry['groups']]
    return np.einsum('tij,tkj->tki', m[:, :3, :3], points) + m[:, None, :3, 3]


def anchors(geometry):
    points = geometry['vertices'][geometry['faces']]
    colors = geometry['colors'].mean(1)
    result = {}
    for group in [3, 5, 7, 9, 13]:
        actual_group = {7: 16, 9: 17}.get(group, group) if np.max(geometry['groups']) >= 17 else group
        mask = (geometry['groups'] == actual_group) & (colors[:, 0] < 145) & (colors[:, 1] < 135) & (colors[:, 2] < 130)
        tri = points[mask]
        area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        result[group] = np.average(tri.mean(1), axis=0, weights=area)
    return result


def parameters_at(config, frame):
    keys = config['pose_keys']
    x = np.array([k['frame'] for k in keys], float)
    values = np.array([k['parameters'] for k in keys], float)
    return PchipInterpolator(x, values, axis=0)(np.clip(frame, x[0], x[-1]))


def targets_at(config, frame):
    result = {}
    for group, keys in config['limb_target_keys'].items():
        x = np.array([k[0] for k in keys], float)
        if x[0] <= frame <= x[-1]:
            result[int(group)] = PchipInterpolator(x, np.asarray(keys)[:, 1:3], axis=0)(frame)
    return result


def anchors_at(config, defaults, frame):
    result = dict(defaults)
    for group, keys in config.get('surface_anchor_keys', {}).items():
        data = np.asarray(keys, float)
        result[int(group)] = PchipInterpolator(data[:, 0], data[:, 1:], axis=0)(np.clip(frame, data[0, 0], data[-1, 0]))
    return result


def foot_rotations_at(config, frame):
    result = {}
    for group, keys in config.get('foot_rotation_keys', {}).items():
        data = np.asarray(keys, float)
        result[int(group)] = RotationSpline(data[:, 0], Rotation.from_quat(data[:, 1:]))(np.clip(frame, data[0, 0], data[-1, 0])).as_matrix()
    return result


def solve_limb(matrices, upper, lower, shoulder, elbow, endpoint, target_xy, camera, twist=0, front_depth=None, planted=False, floor_orientation=None, floor_weight=0, target_world=None, previous=None, normal_target=None, tuck_amount=0):
    m = matrices.copy()
    basis = np.asarray(camera['basis_rows_right_up_toward_camera'])
    start = m[upper, :3, :3] @ shoulder + m[upper, :3, 3]
    middle = m[upper, :3, :3] @ elbow + m[upper, :3, 3]
    lower_start = m[lower, :3, :3] @ elbow + m[lower, :3, 3]
    end = m[lower, :3, :3] @ endpoint + m[lower, :3, 3]
    l1, l2 = np.linalg.norm(middle - start), np.linalg.norm(end - lower_start)
    cp = end @ basis.T
    cp[:2] = [(target_xy[0] - camera['translation_x_px']) / camera['pixels_per_unit'], -(target_xy[1] - camera['translation_y_px']) / camera['pixels_per_unit']]
    if target_world is not None:
        cp = target_world @ basis.T
    if front_depth is not None:
        cp[2] = max(cp[2], front_depth)
    cs = start @ basis.T
    planar = np.linalg.norm(cp[:2] - cs[:2])
    if planar < l1 + l2 - .001:
        max_depth = np.sqrt((l1 + l2 - .001) ** 2 - planar ** 2)
        cp[2] = np.clip(cp[2], cs[2] - max_depth, cs[2] + max_depth)
    target = cp @ basis
    direction = target - start
    length = np.linalg.norm(direction)
    direction /= length
    length = np.clip(length, abs(l1 - l2) + .001, l1 + l2 - .001)
    target = start + direction * length
    along = (l1 * l1 - l2 * l2 + length * length) / (2 * length)
    if lower in [7, 9]:
        desired = (endpoint - elbow) if planted else (end - lower_start)
        pole = -desired + direction * (desired @ direction)
    else:
        pole = middle - start
        pole -= direction * (pole @ direction)
    if previous is not None:
        old_start = previous[upper, :3, :3] @ shoulder + previous[upper, :3, 3]
        old_middle = previous[upper, :3, :3] @ elbow + previous[upper, :3, 3]
        old_end = previous[lower, :3, :3] @ endpoint + previous[lower, :3, 3]
        old_direction = old_end - old_start
        old_direction /= max(1e-10, np.linalg.norm(old_direction))
        temporal_pole = old_middle - old_start
        temporal_pole -= old_direction * (temporal_pole @ old_direction)
        temporal_pole = polar(m[0, :3, :3]) @ polar(previous[0, :3, :3]).T @ temporal_pole
        temporal_pole -= direction * (temporal_pole @ direction)
        if np.linalg.norm(temporal_pole) > .0001:
            pole = temporal_pole
    if tuck_amount > 0:
        body_center = m[0, :3, 3]
        tucked = body_center-(start+target)*.5
        tucked -= direction*(tucked@direction)
        if np.linalg.norm(tucked) > 1e-8 and np.linalg.norm(pole) > 1e-8:
            pole = (1-tuck_amount)*pole/np.linalg.norm(pole)+tuck_amount*tucked/np.linalg.norm(tucked)
    if np.linalg.norm(pole) < 1e-8:
        pole = np.cross(direction, basis[2])
    pole /= np.linalg.norm(pole)
    new_middle = start + direction * along + pole * np.sqrt(max(1e-10, l1 * l1 - along * along))
    if previous is None:
        m[upper] = align_segment(start, middle, start, new_middle) @ m[upper]
        m[lower] = align_segment(lower_start, end, new_middle, target) @ m[lower]
    else:
        for group, local_a, local_b, world_a, world_b in [(upper, shoulder, elbow, start, new_middle), (lower, elbow, endpoint, new_middle, target)]:
            stretch = polar(m[group, :3, :3]).T @ m[group, :3, :3]
            linear = polar(previous[group, :3, :3]) @ stretch
            m[group] = align_segment(linear @ local_a, linear @ local_b, world_a, world_b) @ affine(linear)
    if lower in [7, 9]:
        source_normal = np.array([0., 0., 1.])
        desired_normal = source_normal if planted else np.linalg.inv(matrices[lower, :3, :3]).T @ source_normal
    else:
        source_normal = np.array([1., 0., 0.])
        desired_normal = basis[2]
    if normal_target is not None:
        desired_normal = normal_target.copy()
    if previous is not None:
        previous_normal = np.linalg.inv(previous[lower, :3, :3]).T @ source_normal
        previous_normal /= np.linalg.norm(previous_normal)
        desired_normal /= np.linalg.norm(desired_normal)
        desired_normal = .9 * previous_normal + .1 * desired_normal
    normal = np.linalg.inv(m[lower, :3, :3]).T @ source_normal
    axis = target - new_middle
    axis /= np.linalg.norm(axis)
    normal -= axis * (normal @ axis)
    desired_normal -= axis * (desired_normal @ axis)
    if np.linalg.norm(normal) > .15 and np.linalg.norm(desired_normal) > .15:
        normal /= np.linalg.norm(normal)
        desired_normal /= np.linalg.norm(desired_normal)
        angle = np.arctan2(axis @ np.cross(normal, desired_normal), normal @ desired_normal)
        if previous is not None:
            angle = np.clip(angle, np.deg2rad(-8), np.deg2rad(8))
        m[lower] = around(rotation(axis, np.rad2deg(angle)), new_middle) @ m[lower]
    if twist:
        m[lower] = around(rotation(target - new_middle, twist), new_middle) @ m[lower]
    if floor_orientation is not None and floor_weight > 0:
        current_r = polar(m[lower, :3, :3])
        delta = polar(floor_orientation) @ current_r.T
        blend = Rotation.from_rotvec(Rotation.from_matrix(delta).as_rotvec() * floor_weight).as_matrix()
        m[lower] = around(blend, target) @ m[lower]
        connected_knee = m[lower, :3, :3] @ elbow + m[lower, :3, 3]
        m[upper] = align_segment(start, new_middle, start, connected_knee) @ m[upper]
        direction = connected_knee - start
        ratio = np.linalg.norm(direction) / l1
        direction /= np.linalg.norm(direction)
        m[upper] = around(np.eye(3) + (ratio - 1) * np.outer(direction, direction), start) @ m[upper]
    return m


def apply_pose(matrix, geometry, camera, joints, anchor_points, parameters, targets, frame=405, foot_rotations=None, previous=None):
    p = np.asarray(parameters)
    m = matrix.astype(float).copy()
    if 406 <= frame <= 410 and 9 in targets:
        targets = dict(targets)
        targets[7] = np.asarray(targets[9]) + [5., -12.]
    basis = np.asarray(camera['basis_rows_right_up_toward_camera'])
    pelvis_local = np.array([-.018, 0, -.22])
    pelvis = m[0, :3, :3] @ pelvis_local + m[0, :3, 3]
    axis = polar(m[0, :3, :3])[:, 1]
    waist = around(rotation(axis, p[5]), pelvis)
    m[UPPER_GROUPS] = waist @ m[UPPER_GROUPS]
    neck_local = np.array([.008, 0, .255])
    neck = m[1, :3, :3] @ neck_local + m[1, :3, 3]
    head_r = polar(m[1, :3, :3])
    local = Rotation.from_euler('ZY', p[6:8], degrees=True).as_matrix()
    head = around(head_r @ local @ head_r.T, neck)
    m[HEAD_GROUPS] = head @ m[HEAD_GROUPS]
    camera_r = Rotation.from_euler('xyz', p[:3], degrees=True).as_matrix()
    m = around(basis.T @ camera_r @ basis, pelvis) @ m
    m[:, :3, 3] += basis[0] * p[3] / camera['pixels_per_unit'] - basis[1] * p[4] / camera['pixels_per_unit']
    points = world_points(geometry, m)
    occluders = points[np.isin(geometry['groups'], [0, 1, 10, 11, 12, 13, 14, 15])] @ basis.T
    a = occluders[:, 0, :2]
    u, v = occluders[:, 1, :2] - a, occluders[:, 2, :2] - a
    determinant = u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]
    def surface_depth(cp):
        q = cp[:2] - a
        valid = np.abs(determinant) > 1e-10
        bu, bv = np.zeros(len(a)), np.zeros(len(a))
        bu[valid] = (q[valid, 0] * v[valid, 1] - q[valid, 1] * v[valid, 0]) / determinant[valid]
        bv[valid] = (u[valid, 0] * q[valid, 1] - u[valid, 1] * q[valid, 0]) / determinant[valid]
        hit = valid & (bu >= 0) & (bv >= 0) & (bu + bv <= 1)
        if not hit.any():
            return None
        depth = occluders[:, 0, 2] + bu * (occluders[:, 1, 2] - occluders[:, 0, 2]) + bv * (occluders[:, 2, 2] - occluders[:, 0, 2])
        return depth[hit].max()
    for side, upper, lower in [(-1, 6, 7), (1, 8, 9), (-1, 2, 3), (1, 4, 5)]:
        if lower in [3, 5] and 417 <= frame < 425 and lower not in targets:
            targets = dict(targets)
            targets[lower] = project(m[lower, :3, :3] @ anchor_points[lower] + m[lower, :3, 3], camera)
        if lower not in targets:
            continue
        joint = joints[str(side)]
        if lower in [7, 9] and len(m) >= 18:
            foot = 16 if lower == 7 else 17
            anchor = anchor_points[lower]
            point = m[foot, :3, :3] @ anchor + m[foot, :3, 3]
            if foot_rotations and foot in foot_rotations:
                stretch = polar(m[foot, :3, :3]).T @ m[foot, :3, :3]
                m[foot, :3, :3] = foot_rotations[foot] @ stretch
            cp = point @ basis.T
            cp[:2] = [(targets[lower][0] - camera['translation_x_px']) / camera['pixels_per_unit'], -(targets[lower][1] - camera['translation_y_px']) / camera['pixels_per_unit']]
            if foot == 17 and 402 <= frame <= 411:
                front = surface_depth(cp)
                if front is not None:
                    cp[2] = max(cp[2], front + .018)
            if foot == 16 and 406 <= frame <= 410:
                front = surface_depth(cp)
                if front is not None:
                    cp[2] = min(cp[2], front - .14)
            m[foot, :3, 3] = cp @ basis - m[foot, :3, :3] @ anchor
            ankle = np.asarray(joint['ankle'])
            target = m[foot, :3, :3] @ ankle + m[foot, :3, 3]
            tuck = np.clip((frame-416)/9, 0, 1)
            tuck = tuck*tuck*(3-2*tuck)
            m = solve_limb(m, upper, lower, np.asarray(joint['hip']), np.asarray(joint['knee']), ankle, project(target, camera), camera, target_world=target, previous=previous, tuck_amount=tuck)
            reached = m[lower, :3, :3] @ ankle + m[lower, :3, 3]
            m[foot, :3, 3] += reached - target
            continue
        origin, hinge = ('hip', 'knee') if lower in [7, 9] else ('shoulder', 'elbow')
        twist = p[8] if lower == 7 else p[9] if lower == 9 else 0
        front_depth = None
        if lower in [3, 5]:
            target = np.asarray(targets[lower])
            cp = np.array([(target[0] - camera['translation_x_px']) / camera['pixels_per_unit'], -(target[1] - camera['translation_y_px']) / camera['pixels_per_unit']])
            q = cp - a
            valid = np.abs(determinant) > 1e-10
            bu, bv = np.zeros(len(a)), np.zeros(len(a))
            bu[valid] = (q[valid, 0] * v[valid, 1] - q[valid, 1] * v[valid, 0]) / determinant[valid]
            bv[valid] = (u[valid, 0] * q[valid, 1] - u[valid, 1] * q[valid, 0]) / determinant[valid]
            hit = valid & (bu >= 0) & (bv >= 0) & (bu + bv <= 1)
            if hit.any():
                depth = occluders[:, 0, 2] + bu * (occluders[:, 1, 2] - occluders[:, 0, 2]) + bv * (occluders[:, 2, 2] - occluders[:, 0, 2])
                front_depth = depth[hit].max() + .025
        amount = np.clip((405 - frame) / 5, 0, 1)
        amount = amount * amount * (3 - 2 * amount)
        floor_orientation = matrix[lower, :3, :3] if lower in [7, 9] else None
        normal_target = np.linalg.inv(matrix[lower, :3, :3]).T @ np.array([1., 0., 0.]) if lower in [3, 5] and frame >= 417 else None
        m = solve_limb(m, upper, lower, np.asarray(joint[origin]), np.asarray(joint[hinge]), anchor_points[lower], targets[lower], camera, twist=twist, front_depth=front_depth, planted=frame<=400, floor_orientation=floor_orientation, floor_weight=amount, previous=previous, normal_target=normal_target)
        if lower in [3, 5] and 417 <= frame < 425:
            blend = (frame - 416) / 9
            blend = blend * blend * (3 - 2 * blend)
            for group in [upper, lower]:
                before_r, after_r = polar(m[group, :3, :3]), polar(matrix[group, :3, :3])
                delta = Rotation.from_matrix(after_r @ before_r.T).as_rotvec()
                stretch = (1-blend) * (before_r.T @ m[group, :3, :3]) + blend * (after_r.T @ matrix[group, :3, :3])
                m[group, :3, :3] = Rotation.from_rotvec(delta * blend).as_matrix() @ before_r @ stretch
                m[group, :3, 3] = (1-blend) * m[group, :3, 3] + blend * matrix[group, :3, 3]
            hinge = np.asarray(joint['elbow'])
            m[lower, :3, 3] += m[upper, :3, :3] @ hinge + m[upper, :3, 3] - m[lower, :3, :3] @ hinge - m[lower, :3, 3]
    return m


def refine_motion(matrices, geometry, camera, reference, config):
    output = np.asarray(matrices, dtype=float).copy()
    joint_data = config['joints']
    anchor_points = anchors(geometry)
    first, last = config['frame_range']
    previous_foot = {}
    for frame in range(first, last + 1):
        rotations = foot_rotations_at(config, frame)
        for group, r in rotations.items():
            if group in previous_foot:
                delta = Rotation.from_matrix(r @ previous_foot[group].T).as_rotvec()
                limit = np.deg2rad(25 if frame <= 417 else 15)
                delta *= min(1., limit / max(1e-10, np.linalg.norm(delta)))
                rotations[group] = Rotation.from_rotvec(delta).as_matrix() @ previous_foot[group]
        previous_foot = rotations
        output[frame] = apply_pose(output[frame], geometry, camera, joint_data, anchors_at(config, anchor_points, frame), parameters_at(config, frame), targets_at(config, frame), frame, rotations, output[frame-1] if frame > first else None)
    for frame in range(first, last + 1):
        corrections = {}
        for group, keys in config.get('orientation_corrections', {}).items():
            data = np.asarray(keys, float)
            corrections[int(group)] = PchipInterpolator(data[:, 0], data[:, 1:], axis=0)(np.clip(frame, data[0, 0], data[-1, 0]))
        output[frame] = correct_orientations(output[frame], geometry, camera, config, frame, corrections, output[frame-1] if frame > first else None)
    landing = config.get('landing_foot_track')
    if landing and output.shape[1] >= 18:
        basis = np.asarray(camera['basis_rows_right_up_toward_camera'])
        canonical = Rotation.from_quat(landing['canonical_world_quaternion']).as_matrix()
        anchor = np.asarray(landing['canonical_source_anchor'])
        keys = np.asarray(landing['axis_keys'])
        axis_curve = PchipInterpolator(keys[:, 0], keys[:, 1])
        joint = config['joints']['-1']
        ankle = np.asarray(joint['ankle'])
        for frame in range(412, min(len(output), 541)):
            m = output[frame].copy()
            angle = float(axis_curve(frame))
            desired = rotation(basis[2], -(angle-landing['canonical_reference_axis_degrees'])) @ canonical
            previous_rotation = polar(output[frame-1, 16, :3, :3])
            delta = Rotation.from_matrix(desired@previous_rotation.T).as_rotvec()
            limit = np.deg2rad(50 if frame <= 420 else 15)
            delta *= min(1., limit/max(1e-10, np.linalg.norm(delta)))
            desired = Rotation.from_rotvec(delta).as_matrix()@previous_rotation
            stretch = polar(m[16, :3, :3]).T @ m[16, :3, :3]
            m[16, :3, :3] = desired @ stretch
            target_xy = targets_at(config, frame)[7]
            depth = m[0, :3, 3]@basis[2]+landing['depth_relative_to_torso_origin']
            point = np.array([(target_xy[0]-camera['translation_x_px'])/camera['pixels_per_unit'], -(target_xy[1]-camera['translation_y_px'])/camera['pixels_per_unit'], depth])@basis
            m[16, :3, 3] = point-m[16, :3, :3]@anchor
            target = m[16, :3, :3]@ankle+m[16, :3, 3]
            m = solve_limb(m, 6, 7, np.asarray(joint['hip']), np.asarray(joint['knee']), ankle, project(target, camera), camera, target_world=target, previous=output[frame-1])
            m[16, :3, 3] += m[7, :3, :3]@ankle+m[7, :3, 3]-target
            output[frame] = m
    hand_prior = config.get('landing_hand_pose_prior')
    if hand_prior:
        prior_keys = {int(row[0]): np.asarray(row[1:]).reshape(2, 3, 4) for row in hand_prior['frames']}
        joint = joint_data['1']
        for frame in range(415, min(len(output), 541)):
            m = output[frame].copy()
            prior = m.copy()
            amount = np.clip((frame-414)/3, 0, 1)
            amount = amount*amount*(3-2*amount)
            data = prior_keys[max(417, frame)]
            for index, group in enumerate([4, 5]):
                old_r = polar(data[index, :3, :3])
                current_r = polar(m[group, :3, :3])
                delta = Rotation.from_matrix(old_r@current_r.T).as_rotvec()
                prior[group, :3, :3] = Rotation.from_rotvec(delta*amount).as_matrix()@current_r@(current_r.T@m[group, :3, :3])
                prior[group, :3, 3] = (1-amount)*m[group, :3, 3]+amount*data[index, :3, 3]
            anchor = anchors_at(config, anchor_points, frame)[5]
            contact = m[5, :3, :3]@anchor+m[5, :3, 3]
            normal = np.linalg.inv(prior[5, :3, :3]).T@np.array([1., 0., 0.])
            output[frame] = solve_limb(m, 4, 5, np.asarray(joint['shoulder']), np.asarray(joint['elbow']), anchor, project(contact, camera), camera, target_world=contact, previous=prior, normal_target=normal)
            roll = hand_prior.get('additional_contact_axis_roll_degrees', 0)*amount
            if roll:
                elbow = np.asarray(joint['elbow'])
                first = output[frame, 5, :3, :3]@elbow+output[frame, 5, :3, 3]
                end = output[frame, 5, :3, :3]@anchor+output[frame, 5, :3, 3]
                output[frame, 5] = around(rotation(end-first, roll), first)@output[frame, 5]
    return output.astype(np.float32)


def correct_orientations(matrix, geometry, camera, config, frame, corrections, previous=None):
    m = matrix.copy()
    basis = np.asarray(camera['basis_rows_right_up_toward_camera'])
    anchor_points = anchors_at(config, anchors(geometry), frame)
    for group, values in corrections.items():
        if np.max(np.abs(values)) < 1e-7:
            continue
        if group in [3, 5]:
            side = '-1' if group == 3 else '1'
            elbow = np.asarray(config['joints'][side]['elbow'])
            first = m[group, :3, :3] @ elbow + m[group, :3, 3]
            end = m[group, :3, :3] @ anchor_points[group] + m[group, :3, 3]
            if len(values) > 1 and abs(values[1]) > 1e-7:
                upper = group-1
                shoulder = np.asarray(config['joints'][side]['shoulder'])
                start = m[upper, :3, :3] @ shoulder + m[upper, :3, 3]
                swivel = around(rotation(end-start, float(values[1])), start)
                m[upper] = swivel @ m[upper]
                m[group] = swivel @ m[group]
                first = m[group, :3, :3] @ elbow + m[group, :3, 3]
            m[group] = around(rotation(end-first, float(values[0])), first) @ m[group]
        elif group in [16, 17]:
            side, upper, lower = ('-1', 6, 7) if group == 16 else ('1', 8, 9)
            joint = config['joints'][side]
            point = m[group, :3, :3] @ anchor_points[lower] + m[group, :3, 3]
            rot = basis.T @ Rotation.from_euler('xyz', values[:3], degrees=True).as_matrix() @ basis
            m[group] = around(rot, point) @ m[group]
            if len(values) > 3:
                m[group, :3, 3] += basis[2]*values[3]
            ankle = np.asarray(joint['ankle'])
            target = m[group, :3, :3] @ ankle + m[group, :3, 3]
            tuck = np.clip((frame-416)/9, 0, 1)
            tuck = tuck*tuck*(3-2*tuck)
            m = solve_limb(m, upper, lower, np.asarray(joint['hip']), np.asarray(joint['knee']), ankle, project(target, camera), camera, target_world=target, previous=previous, tuck_amount=tuck)
            actual = m[lower, :3, :3] @ ankle + m[lower, :3, 3]
            m[group, :3, 3] += actual-target
    return m


def painter_dark_mask(geometry, matrix, camera, wanted_groups, return_anchor=False):
    from build_milkfrog_rom import project_triangles, projection
    from compare_milkfrog_lods import rgb332
    points = np.rint(geometry['vertices'][geometry['faces']] * 4096).astype(np.int64)
    xy, visible, depth, _ = project_triangles(points, geometry['groups'], np.rint(projection(camera) @ matrix * 4096).astype(np.int64))
    ids = np.flatnonzero(visible)
    ids = ids[np.argsort(-depth[ids], kind='stable')]
    winning = np.full((240, 320), -1, np.int32)
    for tid in ids:
        cv2.fillConvexPoly(winning, xy[tid].astype(np.int32), int(tid))
    yy, xx = np.where(winning >= 0)
    tid = winning[yy, xx]
    chosen = np.isin(geometry['groups'][tid], wanted_groups)
    xx, yy, tid = xx[chosen], yy[chosen], tid[chosen]
    tri = xy[tid].astype(float)
    a, b = tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]
    p = np.column_stack([xx, yy])-tri[:, 0]
    det = a[:, 0]*b[:, 1]-a[:, 1]*b[:, 0]
    u = (p[:, 0]*b[:, 1]-p[:, 1]*b[:, 0])/det
    v = (a[:, 0]*p[:, 1]-a[:, 1]*p[:, 0])/det
    packed = rgb332(geometry['colors'][tid]).astype(int)
    levels = np.array([7, 7, 3])
    color = np.stack([packed>>5, (packed>>2)&7, packed&3], axis=-1)*4096//levels
    area = det.astype(np.int64)
    num_x = (color[:, 1]-color[:, 0])*b[:, 1, None].astype(np.int64)-(color[:, 2]-color[:, 0])*a[:, 1, None].astype(np.int64)
    num_y = (color[:, 2]-color[:, 0])*a[:, 0, None].astype(np.int64)-(color[:, 1]-color[:, 0])*b[:, 0, None].astype(np.int64)
    grad_x = np.sign(num_x)*np.sign(area[:, None])*(np.abs(num_x)//np.abs(area[:, None]))
    grad_y = np.sign(num_y)*np.sign(area[:, None])*(np.abs(num_y)//np.abs(area[:, None]))
    grad_x = (grad_x+16384)%32768-16384
    grad_y = (grad_y+16384)%32768-16384
    values = color[:, 0]+p[:, 0, None].astype(np.int64)*grad_x+p[:, 1, None].astype(np.int64)*grad_y
    shaded = (np.clip(values, 0, 4096)*levels+2048)>>12
    rgb = shaded*255//levels
    dark = np.all(rgb < [145, 135, 130], axis=1)
    mask = np.zeros((240, 320), np.uint8)
    mask[yy[dark], xx[dark]] = 1
    if return_anchor:
        source = geometry['vertices'][geometry['faces'][tid[dark]]]
        point = np.mean(source[:, 0]+u[dark, None]*(source[:, 1]-source[:, 0])+v[dark, None]*(source[:, 2]-source[:, 0]), axis=0)
        return mask, point
    return mask


def fit_orientation_corrections(config, geometry, matrices, camera, reference):
    frames = [406, 414, 425, 430, 450, 480, 510, 540]
    images, _ = reference_frames(reference, frames)
    observations = {v['frame']: v['observed_points'] for v in json.loads((ROOT/'assets/milkfrog/v1_fixed/animation/landing_landmarks.json').read_text(encoding='utf8'))['frames']}
    jobs = [(406, 5, [3, 5], 'hands_merged'), (414, 5, [5], 'hand_upper'), (414, 16, [16], 'foot_upper')]+[(frame, 16, [16], 'far_foot_visible_dark_part') for frame in frames if frame>=425]
    extra_path = ROOT/'assets/milkfrog/v1_fixed/animation/lying_upper_foot_reference.json'
    if extra_path.exists():
        extra = json.loads(extra_path.read_text(encoding='utf8'))
        for row in extra['frames']:
            frame = row['frame']
            if frame not in observations:
                observations[frame] = {'far_foot_visible_dark_part': {'center_xy': row['upper_foot_dark_region']['center_xy'], 'manual_roi_xyxy': [80, 105, 140, 178]}}
    fits = {}
    def measures(mask):
        y, x = np.where(mask)
        if len(x) < 6:
            return np.array([160., 120.]), 0., max(1, len(x))
        points = np.column_stack([x, y])
        _, vector = np.linalg.eigh(np.cov(points.T))
        angle = np.arctan2(vector[1, -1], vector[0, -1])
        return points.mean(0), angle, len(x)
    for frame, group, wanted, name in jobs:
        ob = observations[frame][name]
        center = np.asarray(ob['center_xy'])
        x0, y0, x1, y1 = ob.get('bbox_xyxy', ob.get('manual_roi_xyxy', [75, 100, 137, 176]))
        dark = np.all(images[frame][y0:y1, x0:x1] < [145, 135, 130], axis=2).astype(np.uint8)
        n, labels, stats, centers = cv2.connectedComponentsWithStats(dark, 8)
        valid = [i for i in range(1, n) if stats[i, 4] >= 8]
        chosen = min(valid, key=lambda i: np.linalg.norm(centers[i]+[x0, y0]-center))
        target = np.zeros((240, 320), np.uint8)
        target[y0:y1, x0:x1] = labels == chosen
        target_center, target_axis, target_area = measures(target)
        def loss(values):
            m = correct_orientations(matrices[frame], geometry, camera, config, frame, {group: values})
            mask = painter_dark_mask(geometry, m, camera, wanted)
            yy, xx = np.indices(mask.shape)
            mask[(xx-center[0])**2+(yy-center[1])**2 > 45**2] = 0
            actual_center, axis, area = measures(mask)
            result = 1-iou(mask, target)
            result += .004*np.sum((actual_center-target_center)**2)
            result += .4*np.sin(axis-target_axis)**2 + .2*np.log(area/target_area)**2
            result += .000008*np.sum(np.asarray(values)**2)
            return float(result)
        if group in [3, 5]:
            values = [np.array([angle, 0.]) for angle in range(-180, 181, 15)]
            best = min(values, key=loss)
            fit = minimize(loss, best, method='Powell', bounds=[(-180, 180), (-100, 100)], options={'maxiter': 6, 'xtol': 1., 'ftol': .002})
        else:
            initial = np.zeros(3)
            _, axis, _ = measures(painter_dark_mask(geometry, matrices[frame], camera, wanted))
            initial[2] = -np.rad2deg((target_axis-axis+np.pi/2)%np.pi-np.pi/2)
            fit = minimize(loss, initial, method='Powell', bounds=[(-70, 70), (-70, 70), (-90, 90)], options={'maxiter': 6, 'xtol': 1., 'ftol': .002})
        fits[(frame, group)] = fit.x.tolist()
        print('ORIENTATION_FIT', frame, group, round(float(fit.fun), 4), np.round(fit.x, 2).tolist(), flush=True)
    hand_a = fits[(406, 5)]
    hand_b = fits[(414, 5)]
    foot_a = fits[(414, 16)]
    foot_b = fits[(425, 16)]
    config['orientation_corrections'] = {
        '5': [[400, 0., 0.], [403, *np.multiply(hand_a, .5).tolist()], [406, *hand_a], [408, *hand_a], [411, 0., 0.], [414, *hand_b], [416, *np.multiply(hand_b, .5).tolist()], [420, 0., 0.], [540, 0., 0.]],
        '16': [[400, 0., 0., 0.], [410, 0., 0., 0.], [414, *foot_a], [417, 0., 0., 0.], [421, *np.multiply(foot_b, .5).tolist()]]+[[frame, *fits[(frame, 16)]] for frame in frames if frame>=425]
    }
    config['orientation_correction_method'] = 'Measured reference dark-mask area, center and principal axis fitted against integer projected, backface-selected, no-Z triangle painter with RGB332 corner channels. Forearm correction is a free twist keeping elbow and hand anchor fixed; foot correction preserves foot/calf shared ankle through two-bone IK.'
    return config


def silhouette(geometry, matrix, camera, hull=False):
    mask = np.zeros((240, 320), np.uint8)
    if hull:
        for group in np.unique(geometry['groups']):
            ids = np.unique(geometry['faces'][geometry['groups'] == group])
            p = geometry['vertices'][ids] @ matrix[group, :3, :3].T + matrix[group, :3, 3]
            xy = np.rint(project(p, camera)).astype(np.int32)
            if len(xy) >= 3:
                cv2.fillConvexPoly(mask, cv2.convexHull(xy), 1)
    else:
        points = world_points(geometry, matrix)
        basis = np.asarray(camera['basis_rows_right_up_toward_camera'])
        normal = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
        xy = np.rint(project(points[normal @ basis[2] > 0], camera)).astype(np.int32)
        for triangle in xy:
            cv2.fillConvexPoly(mask, triangle, 1)
    return mask


def reference_frames(reference, frames):
    cap = cv2.VideoCapture(str(ROOT / reference['source_video']))
    mapping = reference['display_mapping']
    s = mapping['uniform_scale']
    tx, ty = mapping['translation_xy']
    warp = np.array([[s, 0, tx], [0, s, ty]], float)
    images, masks = {}, {}
    for frame in frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, source = cap.read()
        if not ok:
            raise RuntimeError(f'Missing source video frame {frame}')
        rgb = cv2.cvtColor(cv2.warpAffine(source, warp, (320, 240), borderValue=(157, 255, 130)), cv2.COLOR_BGR2RGB)
        r, g, b = np.moveaxis(rgb.astype(np.int16), -1, 0)
        mask = (~((g > r + 24) & (g > b + 24) & (g > 170))).astype(np.uint8)
        images[frame], masks[frame] = rgb, mask
    cap.release()
    return images, masks


def iou(a, b):
    return float(np.count_nonzero(a & b) / max(1, np.count_nonzero(a | b)))


def calibrate_visible_anchors(config, geometry, matrices, camera, frames):
    from build_milkfrog_rom import project_triangles, projection
    points = np.rint(geometry['vertices'][geometry['faces']] * 4096).astype(np.int64)
    source = geometry['vertices'][geometry['faces']]
    colors = geometry['colors'].mean(1)
    defaults = anchors(geometry)
    keys = {str(group): [[386, *defaults[group].tolist()]] for group in [3, 5, 7, 9]}
    diagnostics = []
    for frame in frames:
        qmatrix = np.rint(projection(camera) @ matrices[frame] * 4096).astype(np.int64)
        pixels, visible, depth, _ = project_triangles(points, geometry['groups'], qmatrix)
        order = np.flatnonzero(visible)
        order = order[np.argsort(-depth[order], kind='stable')]
        triangle_ids = np.full((240, 320), -1, np.int32)
        for tid in order:
            cv2.fillConvexPoly(triangle_ids, pixels[tid].astype(np.int32), int(tid))
        valid = triangle_ids >= 0
        yy, xx = np.where(valid)
        tids = triangle_ids[valid]
        for group in [3, 5, 7, 9]:
            actual_group = {7: 16, 9: 17}.get(group, group) if np.max(geometry['groups']) >= 17 else group
            use = (geometry['groups'][tids] == actual_group) & np.all(colors[tids] < [145, 135, 130], axis=1)
            if group == 9 and frame >= 415:
                use &= (xx < 110) & (yy >= 180)
            x, y, ids = xx[use], yy[use], tids[use]
            if len(ids) < 10:
                continue
            xy = np.column_stack([x, y]).astype(float)
            tri = pixels[ids].astype(float)
            a, b, q = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0], xy - tri[:, 0]
            det = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
            nonzero = np.abs(det) > 1e-8
            u = (q[nonzero, 0] * b[nonzero, 1] - q[nonzero, 1] * b[nonzero, 0]) / det[nonzero]
            v = (a[nonzero, 0] * q[nonzero, 1] - a[nonzero, 1] * q[nonzero, 0]) / det[nonzero]
            s = source[ids[nonzero]]
            point = np.mean(s[:, 0] + u[:, None] * (s[:, 1] - s[:, 0]) + v[:, None] * (s[:, 2] - s[:, 0]), axis=0)
            keys[str(group)].append([frame, *point.tolist()])
            diagnostics.append({'frame': frame, 'group': group, 'visible_pixels': len(ids), 'center_xy': xy.mean(0).tolist(), 'source_anchor': point.tolist()})
    config['surface_anchor_keys'] = keys
    config['surface_anchor_method'] = 'Source-space barycentric mean of visible dark pixels in the fixed-point no-Z painter. Near-foot pixels after415 use the same x<110,y>=180 toe ROI as the reference; not anatomical joint centers.'
    (OUTPUT / 'visible_anchor_calibration.json').write_text(json.dumps(diagnostics, indent=2) + '\n')
    return config


def optimize(config, geometry, matrices, camera, reference, frames):
    _, masks = reference_frames(reference, frames)
    anchor_points = anchors(geometry)
    for frame in frames:
        frame_anchors = anchors_at(config, anchor_points, frame)
        current = parameters_at(config, frame)
        targets = targets_at(config, frame)
        target_mask = masks[frame]
        target_distance = cv2.distanceTransform(1 - target_mask, cv2.DIST_L2, 3)
        def cost(delta):
            p = current.copy()
            p[[0, 1, 2, 3, 4, 5, 7]] += delta
            m = apply_pose(matrices[frame], geometry, camera, config['joints'], frame_anchors, p, targets, frame, foot_rotations_at(config, frame))
            mask = silhouette(geometry, m, camera, hull=True)
            outside = float(target_distance[mask.astype(bool)].mean()) if mask.any() else 100
            loss = 1 - iou(mask, target_mask) + .025 * outside
            loss += .00006 * np.sum(delta[:3] ** 2) + .0001 * delta[5] ** 2
            for group, target in targets.items():
                actual_group = {7: 16, 9: 17}.get(group, group) if len(m) >= 18 else group
                actual = project(m[actual_group, :3, :3] @ frame_anchors[group] + m[actual_group, :3, 3], camera)
                loss += .001 * np.sum((actual - target) ** 2)
            return loss
        fit = minimize(cost, np.zeros(7), method='Powell', bounds=[(-20, 20), (-25, 25), (-30, 30), (-22, 22), (-25, 25), (-18, 18), (-18, 18)], options={'maxiter': 12, 'xtol': .35, 'ftol': .0005})
        fitted = current.copy()
        fitted[[0, 1, 2, 3, 4, 5, 7]] += fit.x
        for key in config['pose_keys']:
            if key['frame'] == frame:
                key['parameters'] = fitted.tolist()
                break
        else:
            config['pose_keys'].append({'frame': frame, 'parameters': fitted.tolist()})
            config['pose_keys'].sort(key=lambda k: k['frame'])
        print('FIT', frame, round(float(fit.fun), 4), np.round(fitted, 2).tolist(), flush=True)
    return config


def optimize_feet(config, geometry, matrices, camera, reference, frames):
    images, _ = reference_frames(reference, frames)
    observations = json.loads((ROOT / 'assets/milkfrog/v1_fixed/animation/landing_landmarks.json').read_text(encoding='utf8'))
    observations = {item['frame']: item['observed_points'] for item in observations['frames']}
    basis = np.asarray(camera['basis_rows_right_up_toward_camera'])
    defaults = anchors(geometry)
    config.setdefault('foot_rotation_keys', {})
    for foot in [16, 17]:
        keys = config['foot_rotation_keys'].setdefault(str(foot), [])
        if not keys:
            for frame in [386, 400, 405, 408, 411, 414, 417, 430, 450, 480, 510, 540]:
                keys.append([frame, *Rotation.from_matrix(polar(matrices[frame, foot, :3, :3])).as_quat().tolist()])
    for frame in frames:
        target_points = targets_at(config, frame)
        a = anchors_at(config, defaults, frame)
        current_rotations = foot_rotations_at(config, frame)
        for foot, lower in [(16, 7), (17, 9)]:
            if lower not in target_points:
                continue
            points = observations.get(frame, {})
            name = ('foot_screen_left' if foot == 16 else 'foot_screen_right') if frame <= 405 else ('far_foot_visible_dark_part' if foot == 16 else 'near_foot_visible_dark_part')
            if 406 <= frame <= 410:
                if foot == 16:
                    continue
                name = 'single_visible_foot'
            if name not in points and 411 <= frame <= 414:
                name = 'foot_upper' if foot == 16 else 'foot_lower'
            if name in points:
                observed = points[name]
                if 'bbox_xyxy' in observed:
                    x0, y0, x1, y1 = observed['bbox_xyxy']
                else:
                    x, y = observed['center_xy']
                    x0, y0, x1, y1 = int(x-14), int(y-16), int(x+14), int(y+16)
                x0, y0, x1, y1 = max(0, x0-3), max(0, y0-3), min(320, x1+4), min(240, y1+4)
            elif frame > 430:
                x0, y0, x1, y1 = (75, 100, 137, 176) if foot == 16 else (75, 180, 110, 221)
            else:
                continue
            rgb = images[frame]
            target = np.zeros((240, 320), np.uint8)
            target[y0:y1, x0:x1] = np.all(rgb[y0:y1, x0:x1] < [145, 135, 130], axis=2)
            target_count = int(target.sum())
            if target_count < 15:
                continue
            ids = np.unique(geometry['faces'][geometry['groups'] == foot])
            vertices = geometry['vertices'][ids]
            prior = current_rotations[foot]
            p = parameters_at(config, frame)
            def cost(delta):
                orientations = dict(current_rotations)
                orientations[foot] = basis.T @ Rotation.from_euler('xyz', delta, degrees=True).as_matrix() @ basis @ prior
                m = apply_pose(matrices[frame], geometry, camera, config['joints'], a, p, target_points, frame, orientations)
                xy = np.rint(project(vertices @ m[foot, :3, :3].T + m[foot, :3, 3], camera)).astype(np.int32)
                mask = np.zeros((240, 320), np.uint8)
                cv2.fillConvexPoly(mask, cv2.convexHull(xy), 1)
                if foot == 17 and frame >= 415:
                    mask[:, 110:] = 0
                    mask[:180] = 0
                score = 1 - iou(mask, target)
                score += .00001 * np.sum(delta ** 2)
                up = orientations[foot][:, 2] @ basis[2]
                score += .08 * max(0., -up)
                actual = project(m[foot, :3, :3] @ a[lower] + m[foot, :3, 3], camera)
                score += .002 * np.sum((actual - target_points[lower]) ** 2)
                return score
            bound = 35 if frame <= 400 else 75
            fit = minimize(cost, np.zeros(3), method='Powell', bounds=[(-bound, bound)] * 3, options={'maxiter': 8, 'xtol': .5, 'ftol': .001})
            orientation = basis.T @ Rotation.from_euler('xyz', fit.x, degrees=True).as_matrix() @ basis @ prior
            current_rotations[foot] = orientation
            value = [frame, *Rotation.from_matrix(orientation).as_quat().tolist()]
            keys = [key for key in config['foot_rotation_keys'][str(foot)] if key[0] != frame] + [value]
            config['foot_rotation_keys'][str(foot)] = sorted(keys)
            print('FOOT_FIT', frame, foot, round(float(fit.fun), 4), np.round(fit.x, 1).tolist(), flush=True)
    return config


def write_review(geometry, baseline, candidate, camera, reference, config, input_geometry_path=None, input_matrices_path=None):
    from PIL import Image, ImageDraw
    from build_milkfrog_rom import project_triangles, projection
    from compare_milkfrog_lods import rgb332
    from verify_vertex_lab import render, to_image
    frames = list(range(390, 426)) + [430, 450, 480, 510, 540]
    images, masks = reference_frames(reference, frames)
    colors = rgb332(geometry['colors'])
    points = np.rint(geometry['vertices'][geometry['faces']] * 4096).astype(np.int64)
    clear = 0x9e
    report = []
    for frame in frames:
        before = silhouette(geometry, baseline[frame], camera)
        after = silhouette(geometry, candidate[frame], camera)
        qmatrix = np.rint(projection(camera) @ candidate[frame] * 4096).astype(np.int64)
        pixels, visible, depth, _ = project_triangles(points, geometry['groups'], qmatrix)
        valid = visible & np.all((pixels >= 0) & (pixels < [320, 240]), axis=(1, 2))
        order = np.flatnonzero(valid)
        order = order[np.argsort(-depth[order], kind='stable')]
        background = [(None, [(0, 0), (319, 0), (319, 239)], [clear] * 3), (None, [(0, 0), (319, 239), (0, 239)], [clear] * 3)]
        painter = render(background + [(None, p, c) for p, c in zip(pixels[order], colors[order])], 320, 240)
        to_image(painter).save(OUTPUT / f'candidate_{frame:04d}.png')
        Image.fromarray(images[frame]).save(OUTPUT / f'reference_{frame:04d}.png')
        report.append({'frame': frame, 'baseline_silhouette_iou': iou(before, masks[frame]), 'candidate_silhouette_iou': iou(after, masks[frame]), 'out_of_frame_triangles': int(np.count_nonzero(visible & ~valid))})
    for first in [390, 402, 414]:
        sheet = Image.new('RGB', (1920, 600), 'white')
        draw = ImageDraw.Draw(sheet)
        for i, frame in enumerate(range(first, first + 12)):
            x, y = i % 4 * 480, i // 4 * 200
            sheet.paste(Image.fromarray(images[frame]).resize((240, 180)), (x, y + 20))
            sheet.paste(Image.open(OUTPUT / f'candidate_{frame:04d}.png').resize((240, 180)), (x + 240, y + 20))
            draw.text((x + 5, y + 3), f'f{frame} REF / CANDIDATE NO-Z', fill=(0, 0, 0))
        sheet.save(OUTPUT / f'candidate_dense_{first}_{first+11}.jpg')
    sheet = Image.new('RGB', (1920, 520), 'white')
    draw = ImageDraw.Draw(sheet)
    for i, frame in enumerate([425, 430, 450, 480, 510, 540]):
        x, y = i%3*640, i//3*260
        sheet.paste(Image.fromarray(images[frame]), (x, y+20))
        sheet.paste(Image.open(OUTPUT/f'candidate_{frame:04d}.png'), (x+320, y+20))
        draw.text((x+5, y+3), f'f{frame} REF / CANDIDATE NO-Z', fill=(0, 0, 0))
    sheet.save(OUTPUT/'candidate_late_landing.jpg')
    provenance = {'method': 'Fixed camera/scale, exact projected-triangle silhouette and independent fixed-point per-frame centroid painter; no depth buffer, not RTL.', 'geometry_triangles': len(geometry['faces']), 'groups': candidate.shape[1], 'frames': report}
    for label, path in [('geometry', input_geometry_path), ('base_matrices', input_matrices_path), ('motion_config', CONFIG)]:
        if path is not None:
            provenance[label] = {'path': str(Path(path).resolve().relative_to(ROOT)), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    provenance['candidate_matrices_sha256'] = hashlib.sha256((OUTPUT / 'matrices.npy').read_bytes()).hexdigest()
    provenance['joint_connection_error'] = {}
    if candidate.shape[1] >= 18:
        for side, calf, foot in [('-1', 7, 16), ('1', 9, 17)]:
            ankle = np.asarray(config['joints'][side]['ankle'])
            first_point = np.einsum('fij,j->fi', candidate[:, calf, :3, :3], ankle) + candidate[:, calf, :3, 3]
            second_point = np.einsum('fij,j->fi', candidate[:, foot, :3, :3], ankle) + candidate[:, foot, :3, 3]
            provenance['joint_connection_error'][str(foot)] = float(np.linalg.norm(first_point-second_point, axis=1).max())
    provenance['whole_sequence'] = {'finite': bool(np.isfinite(candidate).all()), 'minimum_affine_determinant': float(np.linalg.det(candidate[:, :, :3, :3]).min())}
    provenance['rotation_step_degrees'] = {}
    for group in [1, 2, 3, 4, 5, 6, 7, 8, 9, 16, 17]:
        if group >= candidate.shape[1]:
            continue
        rotations = np.stack([polar(value[:3, :3]) for value in candidate[:, group]])
        differences = np.rad2deg(Rotation.from_matrix(rotations[1:] @ rotations[:-1].transpose(0, 2, 1)).magnitude())
        provenance['rotation_step_degrees'][str(group)] = {'max_after386': float(differences[386:].max()), 'frame': int(np.argmax(differences[386:])+387), 'max_after425': float(differences[425:].max())}
    (OUTPUT / 'motion_validation.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print('DENSE_REVIEW', np.mean([x['baseline_silhouette_iou'] for x in report]), np.mean([x['candidate_silhouette_iou'] for x in report]), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--optimize', type=int, nargs='*')
    parser.add_argument('--review', action='store_true')
    parser.add_argument('--calibrate-anchors', action='store_true')
    parser.add_argument('--geometry', type=Path, default=SNAPSHOT / 'geometry.npz')
    parser.add_argument('--matrices', type=Path, default=SNAPSHOT / 'matrices.npy')
    parser.add_argument('--optimize-feet', type=int, nargs='*')
    parser.add_argument('--fit-orientations', action='store_true')
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    geometry = dict(np.load(args.geometry))
    matrices = np.load(args.matrices)
    camera = json.loads((ROOT / 'assets/naiwa/camera.json').read_text(encoding='utf8'))
    reference = json.loads((ROOT / 'assets/naiwa/reference_motion.json').read_text(encoding='utf8'))
    config = json.loads(CONFIG.read_text(encoding='utf8'))
    if args.calibrate_anchors:
        candidate = refine_motion(matrices, geometry, camera, reference, config)
        config = calibrate_visible_anchors(config, geometry, candidate, camera, [*range(390, 431), 450, 480, 510, 540])
        CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    if args.optimize:
        config = optimize(config, geometry, matrices, camera, reference, args.optimize)
        CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    if args.optimize_feet:
        config = optimize_feet(config, geometry, matrices, camera, reference, args.optimize_feet)
        CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    if args.fit_orientations:
        config.pop('orientation_corrections', None)
    candidate = refine_motion(matrices, geometry, camera, reference, config)
    if args.fit_orientations:
        config = fit_orientation_corrections(config, geometry, candidate, camera, reference)
        CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
        candidate = refine_motion(matrices, geometry, camera, reference, config)
    np.save(OUTPUT / 'matrices.npy', candidate)
    if args.review:
        write_review(geometry, matrices, candidate, camera, reference, config, args.geometry, args.matrices)
    print('MOTION_CANDIDATE', OUTPUT / 'matrices.npy', flush=True)


if __name__ == '__main__':
    main()
