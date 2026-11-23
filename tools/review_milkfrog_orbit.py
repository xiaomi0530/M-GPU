"""Measure the moving camera and inspect all captured frames without a depth buffer."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from build_milkfrog_rom import compose_matrices, project_triangles, Q
from preview_milkfrog_rom import validate_projection
from verify_vertex_lab import to_image

ROOT = Path(__file__).resolve().parents[1]
ANIMATION = ROOT/'assets/milkfrog/v2_orbit/animation'
ROM = ROOT/'assets/milkfrog/v2_orbit/rom'
RUN = ROOT/'out/milkfrog_orbit_v2'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def components(mask):
    count, _, statistics, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return sorted((dict(x=int(x), y=int(y), width=int(w), height=int(h), area=int(area))
                   for x, y, w, h, area in statistics[1:count]), key=lambda item: -item['area'])


def review(captures, output, engine):
    output.mkdir(parents=True, exist_ok=True)
    camera = json.loads((ANIMATION/'camera.json').read_text(encoding='utf8'))
    manifest = json.loads((ROM/'manifest.json').read_text())
    geometry = dict(np.load(ANIMATION/'geometry.npz'))
    old = dict(np.load(ROOT/'assets/milkfrog/v1_fixed/animation/geometry.npz'))
    unchanged = {}
    for name, expected in camera['source_animation_sha256'].items():
        assert digest(ROOT/'assets/milkfrog/v1_fixed/animation'/name) == expected, f'V1 changed: {name}'
        if name != 'geometry.npz':
            unchanged[name] = digest(ANIMATION/name) == expected
    assert all(unchanged.values()), 'The V2 source motion or expression controls changed'
    for name in ('vertices', 'faces', 'groups', 'colors'):
        assert np.array_equal(geometry[name][:len(old[name])], old[name]), f'V1 surfaces changed: {name}'
    projection_path = RUN/'board_reference/projection.npz'
    data = dict(np.load(projection_path))
    validate_projection(ANIMATION, ROM, projection_path)
    camera_world = np.load(ANIMATION/'camera_world.npy')
    actual_angles = np.unwrap(np.arctan2(camera_world[:, 1, 2], camera_world[:, 0, 2]))
    actual_angles = np.rad2deg(actual_angles-actual_angles[0])
    angle_errors = actual_angles-np.linspace(0, 360, 541)
    assert np.max(np.abs(angle_errors)) < 1e-8, 'Camera did not complete the expected orbit'
    camera_clip = np.load(ANIMATION/'camera_matrices.npy')
    scales = np.linalg.norm(camera_clip[:, :2, :3], axis=2)*[160, 120]
    assert np.max(np.abs(scales-camera['pixels_per_unit'])) < 1e-8, 'Camera scale pumps'
    transforms = np.load(ANIMATION/'matrices.npy')
    direct = compose_matrices(transforms, camera_clip)
    points = np.rint(geometry['vertices'][geometry['faces']]*Q).astype(np.int64)
    groups = geometry['groups'].astype(int)
    interpolation = []
    for frame in range(541):
        expected, _, _, _ = project_triangles(points, groups, direct[frame])
        delta = data['pixels'][frame]-expected
        interpolation.append(dict(frame=frame, maximum_coordinate_error=int(np.abs(delta).max()),
                                  maximum_euclidean_error=float(np.linalg.norm(delta, axis=-1).max())))
    all_pixels = data['pixels']
    bounds = [all_pixels.min(axis=(0, 1, 2)).tolist(), all_pixels.max(axis=(0, 1, 2)).tolist()]
    assert bounds[0][0] >= 0 and bounds[0][1] >= 0 and bounds[1][0] < 320 and bounds[1][1] < 240, 'Geometry clips the frame'
    frames, images, transitions = [], [], []
    previous = None
    clear = manifest['clear_color_rgb332']
    assignment = data['assignment']
    for frame in range(541):
        path = captures/f'frame_{frame:04d}.rgb332'
        raw = np.fromfile(path, np.uint8)
        assert raw.size == 76800, f'Incomplete frame {frame}'
        raw = raw.reshape(240, 320)
        images.append(raw)
        foreground = raw != clear
        yy, xx = np.nonzero(foreground)
        assert len(xx), f'Empty frame {frame}'
        islands = components(foreground)
        holes = [item for item in components(~foreground)
                 if item['x'] > 0 and item['y'] > 0
                 and item['x']+item['width'] < 320 and item['y']+item['height'] < 240]
        record = dict(frame=frame, sha256=digest(path), orbit_degrees=float(actual_angles[frame]),
                      foreground_pixels=int(foreground.sum()), bbox=[int(xx.min()), int(yy.min()), int(xx.max()), int(yy.max())],
                      detached_components=islands[1:], enclosed_background=holes)
        frames.append(record)
        if previous is not None:
            transitions.append(dict(frame=frame, cache_changed=bool(assignment[frame] != assignment[frame-1]),
                                    changed_pixels=int(np.count_nonzero(raw != previous)),
                                    foreground_symmetric_difference=int(np.count_nonzero(foreground != (previous != clear)))))
        previous = raw
    order = json.loads((ROM/'ordering_report.json').read_text())
    worst_color = sorted(order['frames'], key=lambda item: -item['cached']['visible_color_violations'])[:8]
    cache_changes = [item for item in transitions if item['cache_changed']]
    ranked = sorted(cache_changes, key=lambda item: -item['changed_pixels'])[:8]
    holes_ranked = sorted(frames, key=lambda item: -sum(hole['area'] for hole in item['enclosed_background']))[:8]
    selected = sorted(set([round(i*540/11) for i in range(12)] + [135, 225, 315, 360, 405, 411, 412, 413, 414, 415, 417]
                          + [item['frame'] for item in worst_color+ranked+holes_ranked]))
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 15)
    def sheet(frame_numbers, path):
        canvas = Image.new('RGB', (1280, ((len(frame_numbers)+3)//4)*268), '#20252b')
        draw = ImageDraw.Draw(canvas)
        for index, frame in enumerate(frame_numbers):
            x, y = (index%4)*320, (index//4)*268
            draw.text((x+6, y+5), f'f{frame:03d} / orbit {actual_angles[frame]:.1f} deg / cache {assignment[frame]}', font=font, fill='white')
            canvas.paste(to_image(images[frame]), (x, y+28))
        canvas.save(path, quality=95)
    sheet(selected, output/'orbit_review.jpg')
    transition_frames = list(range(389, 397))+list(range(404, 420))
    sheet(transition_frames, output/'orbit_transitions.jpg')
    result = dict(engine=engine, frame_count=541, model_motion_unchanged=unchanged,
                  original_surfaces_preserved=True, geometry_sha256=digest(ANIMATION/'geometry.npz'),
                  camera_matrices_sha256=digest(ANIMATION/'camera_matrices.npy'),
                  manifest_sha256=digest(ROM/'manifest.json'), projection_sha256=digest(projection_path),
                  camera=dict(total_measured_orbit_degrees=float(actual_angles[-1]),
                              maximum_angle_error_degrees=float(np.abs(angle_errors).max()),
                              fixed_pixels_per_unit=camera['pixels_per_unit'], all_geometry_pixel_bounds=bounds,
                              no_frame_clipping=True),
                  matrix_interpolation=dict(maximum_coordinate_error=max(item['maximum_coordinate_error'] for item in interpolation),
                                            maximum_euclidean_error=max(item['maximum_euclidean_error'] for item in interpolation),
                                            frames=interpolation),
                  ordering_summary=order['cached_summary'], worst_ordering_frames=[item['frame'] for item in worst_color],
                  cache_switch_count=len(cache_changes), largest_cache_switch_changes=ranked,
                  largest_enclosed_background_frames=[item['frame'] for item in holes_ranked],
                  selected_review_frames=selected, transition_sheet_frames=transition_frames,
                  transitions=transitions, frames=frames,
                  scope='Full-orbit geometry, camera and image diagnostics. Enclosed background includes valid gaps between limbs; components and temporal peaks require visual interpretation. Offline geometric order scores are not reference-video similarity scores. No runtime depth buffer is used.')
    (output/'orbit_review.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    print(json.dumps({key: result[key] for key in ('engine', 'frame_count', 'camera', 'ordering_summary', 'worst_ordering_frames')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--captures', type=Path, default=RUN/'rtl')
    parser.add_argument('--output', type=Path, default=RUN/'rtl/review')
    parser.add_argument('--engine', default='Actual MGPU RTL framebuffer')
    args = parser.parse_args()
    review(args.captures.resolve(), args.output.resolve(), args.engine)
