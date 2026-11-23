import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from verify_vertex_lab import render, to_image


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets/naiwa/candidates'
STANDARD = ROOT / 'out/naiwa/standard'
DEFAULT_OUTPUT = STANDARD / 'lod_comparison'
WIDTH, HEIGHT, Q = 320, 240, 4096
CLEAR = 0xbe
REGIONS = {
    'eyes': [138, 24, 167, 45],
    'hands': [103, 99, 165, 139],
    'feet': [112, 193, 204, 225],
}


def rgb332(rgb):
    value = np.clip(np.floor(np.asarray(rgb, dtype=float) * np.array([7, 7, 3]) / 255 + .5), 0, [7, 7, 3]).astype(np.uint8)
    return (value[..., 0] << 5) | (value[..., 1] << 2) | value[..., 2]


def expanded_rgb(pixels):
    value = np.asarray(pixels).astype(np.uint16)
    return np.stack(((value >> 5)*255//7, ((value >> 2)&7)*255//7, (value&3)*255//3), axis=-1).astype(np.uint8)


def sample_texture(texture, uv):
    h, w = texture.shape[:2]
    u = np.mod(uv[..., 0], 1.0)
    v = np.mod(uv[..., 1], 1.0)
    x, y = u*w-.5, (1-v)*h-.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x-x0, y-y0
    return (texture[y0 % h, x0 % w] * ((1-fx)*(1-fy))[..., None]
            + texture[y0 % h, (x0+1) % w] * (fx*(1-fy))[..., None]
            + texture[(y0+1) % h, x0 % w] * ((1-fx)*fy)[..., None]
            + texture[(y0+1) % h, (x0+1) % w] * (fx*fy)[..., None])


def project_fixed(vertices, matrix):
    coordinates = np.rint(vertices*Q).astype(np.int64)
    clip = (coordinates @ matrix[:, :3].T + matrix[:, 3]*Q) >> 12
    if np.any(clip[:, 3] <= 0):
        raise ValueError('Nonpositive clip w')
    ndc = np.sign(clip[:, :3]) * (np.abs(clip[:, :3])*Q // clip[:, 3:4])
    pixels = np.stack(((ndc[:, 0]+Q)*WIDTH//(2*Q), (Q-ndc[:, 1])*HEIGHT//(2*Q)), axis=1)
    if np.any(ndc[:, 2] < -Q) or np.any(ndc[:, 2] > Q):
        raise ValueError('Vertex depth outside existing GPU clip range')
    return coordinates, pixels


def make_scene(label, output, camera, texture):
    mesh_path = ASSETS/label/'mesh.npz'
    mesh = np.load(mesh_path)
    vertices = mesh['vertices'].astype(float)
    faces = mesh['faces'].astype(int)
    uv = mesh['uv'].astype(float)
    basis = np.asarray(camera['basis_rows_right_up_toward_camera'])
    matrix_words = np.asarray(camera['mvp_q5_12_column_major'], dtype=np.int32)
    matrix = matrix_words.reshape(4, 4, order='F').astype(np.int64)
    coordinates, pixels = project_fixed(vertices, matrix)
    cross = np.cross(vertices[faces[:, 1]]-vertices[faces[:, 0]], vertices[faces[:, 2]]-vertices[faces[:, 0]])
    visible = cross @ basis[2] > 0
    d1 = pixels[faces[:, 1]]-pixels[faces[:, 0]]
    d2 = pixels[faces[:, 2]]-pixels[faces[:, 0]]
    area = d1[:, 0]*d2[:, 1]-d1[:, 1]*d2[:, 0]
    inside = np.all((pixels[faces] >= [0, 0]) & (pixels[faces] < [WIDTH, HEIGHT]), axis=(1, 2))
    selected = np.flatnonzero(visible & (area != 0) & inside)
    depth = (vertices[faces[selected]] @ basis[2]).mean(axis=1)
    selected = selected[np.argsort(depth, kind='stable')]
    ordered = faces[selected]
    colors = rgb332(sample_texture(texture, uv[selected]))
    commands = np.zeros((len(ordered), 3, 4), dtype='<i4')
    commands[:, :, :3] = coordinates[ordered]
    commands[:, :, 3] = colors
    folder = output/label; folder.mkdir(parents=True, exist_ok=True)
    with (folder/'scene.bin').open('wb') as stream:
        stream.write(struct.pack('<4I', 0x4e414957, 1, WIDTH, HEIGHT))
        stream.write(matrix_words.astype('<i4').tobytes())
        stream.write(struct.pack('<2I', 0, len(commands)))
        stream.write(commands.tobytes())
    background = [(None, [(0,0),(319,0),(319,239)], [CLEAR]*3),
                  (None, [(0,0),(319,239),(0,239)], [CLEAR]*3)]
    expected = render(background+[(None, p, c) for p,c in zip(pixels[ordered],colors)], WIDTH, HEIGHT)
    expected.tofile(folder/'expected.rgb332')
    to_image(expected).save(folder/'expected.png')
    metadata = dict(label=label, vertices=len(vertices), original_triangles=len(faces),
                    front_faces=int(visible.sum()), quantized_nondegenerate=int(np.count_nonzero(area)),
                    submitted_triangles=len(commands), culled_outside=int(np.count_nonzero(~inside)),
                    shader_input='Original XYZ, signed Q5.12, real MGPU MVP; not preprojected pixel vertices.',
                    colors='Per-corner UV bilinear sampling, JPEG sRGB to RGB332 nearest levels; original texture is not sent to GPU.',
                    order='Back-to-front by mean camera-space depth; no depth-buffer hardware added.',
                    mesh_sha256=hashlib.sha256(mesh_path.read_bytes()).hexdigest(),
                    scene_sha256=hashlib.sha256((folder/'scene.bin').read_bytes()).hexdigest())
    (folder/'scene_metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    return metadata


def ssim_map(a, b):
    a, b = a.astype(float), b.astype(float)
    mean_a = cv2.GaussianBlur(a, (11,11), 1.5)
    mean_b = cv2.GaussianBlur(b, (11,11), 1.5)
    var_a = cv2.GaussianBlur(a*a, (11,11), 1.5)-mean_a*mean_a
    var_b = cv2.GaussianBlur(b*b, (11,11), 1.5)-mean_b*mean_b
    cov = cv2.GaussianBlur(a*b, (11,11), 1.5)-mean_a*mean_b
    c1, c2 = (0.01*255)**2, (0.03*255)**2
    return (((2*mean_a*mean_b+c1)*(2*cov+c2))/((mean_a*mean_a+mean_b*mean_b+c1)*(var_a+var_b+c2))).mean(axis=2)


def errors(a, b, mask=None):
    delta = a.astype(float)-b.astype(float)
    if mask is not None:
        delta = delta[mask]
    mae=float(np.abs(delta).mean()); mse=float((delta*delta).mean())
    return dict(mae_rgb_255=mae, psnr_db=float(10*np.log10(255**2/mse)) if mse else None)


def evaluate(label, output, source_rgb, source_packed, source_mask):
    folder=output/label
    actual=np.fromfile(folder/'frame_0000.rgb332',dtype=np.uint8).reshape(HEIGHT,WIDTH)
    expected=np.fromfile(folder/'expected.rgb332',dtype=np.uint8).reshape(HEIGHT,WIDTH)
    mismatch=int(np.count_nonzero(actual!=expected))
    if mismatch:
        raise RuntimeError(f'{label}: RTL vs independent fixed-point reference differs at {mismatch} pixels')
    rgb=expanded_rgb(actual); mask=actual!=CLEAR
    union=mask|source_mask; intersection=mask&source_mask
    report=dict(rtl_reference_pixel_mismatches=mismatch, foreground_iou=float(intersection.sum()/union.sum()),
                full_frame=errors(rgb,source_rgb), foreground_union=errors(rgb,source_rgb,union),
                foreground_ssim=float(ssim_map(rgb,source_rgb)[union].mean()),
                exact_rgb332_match_fraction_foreground=float((actual[union]==source_packed[union]).mean()),
                regions={})
    for name,(x0,y0,x1,y1) in REGIONS.items():
        a,b=rgb[y0:y1,x0:x1],source_rgb[y0:y1,x0:x1]
        report['regions'][name]={'bbox_xyxy':[x0,y0,x1,y1],**errors(a,b),'ssim':float(ssim_map(rgb,source_rgb)[y0:y1,x0:x1].mean())}
    validation=json.loads((folder/'validation.json').read_text())
    report['draw_cycles']=validation['draw_cycles_max']
    report['estimated_draw_ms_at_40mhz']=validation['estimated_draw_ms_at_board_40mhz_max']
    report['hardware_unchanged']=validation['hardware_unchanged']
    report['source_note']='Blender original high-poly render quantized to RGB332; antialiasing, exact visibility, integer coverage and per-corner texture approximation differ from current GPU.'
    (folder/'comparison_metrics.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def review_sheet(output, reports, source_rgb):
    labels=['SOURCE','A','B','C','D','E']
    width=384; sheet=Image.new('RGB',(width*6,760),'#20252b');d=ImageDraw.Draw(sheet)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',18)
    title=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
    for i,label in enumerate(labels):
        x=i*width
        if label=='SOURCE':
            image=Image.fromarray(source_rgb);sub='High-poly RGB332 baseline'
        else:
            image=Image.open(output/label/'frame_0000.png').convert('RGB')
            r=reports[label];sub=f"IoU {r['foreground_iou']:.4f}  MAE {r['foreground_union']['mae_rgb_255']:.2f}"
        d.text((x+16,10),label,font=title,fill='white')
        d.text((x+16,43),sub,font=font,fill='#c9d1d9')
        sheet.paste(image.resize((384,288),Image.Resampling.NEAREST),(x,76))
        d.text((x+16,380),'EYES  (nearest-neighbor)',font=font,fill='white')
        eye=image.crop(REGIONS['eyes']).resize((348,252),Image.Resampling.NEAREST)
        sheet.paste(eye,(x+18,410))
        d.text((x+16,678),'HANDS',font=font,fill='white')
        hand=image.crop(REGIONS['hands']).resize((248,160),Image.Resampling.NEAREST)
        if sheet.height<870:
            enlarged=Image.new('RGB',(sheet.width,880),'#20252b');enlarged.paste(sheet,(0,0));sheet=enlarged;d=ImageDraw.Draw(sheet)
        sheet.paste(hand,(x+66,706))
    sheet.save(output/'comparison.png')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--labels',default='ABCDE');parser.add_argument('--skip-simulation',action='store_true')
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    camera=json.loads((ROOT/'assets/naiwa/camera.json').read_text(encoding='utf8'))
    texture=np.asarray(Image.open(ASSETS/'source_basecolor.jpg').convert('RGB'),dtype=float)
    source=np.asarray(Image.open(STANDARD/'source_native.png').convert('RGB'))
    source_packed=rgb332(source);source_rgb=expanded_rgb(source_packed)
    source_mask=np.asarray(Image.open(STANDARD/'source_native_rgba.png'))[:,:,3]>127
    Image.fromarray(source_rgb).save(output/'source_quantized_rgb332.png')
    reports={};metadata={}
    for label in args.labels:
        print(f'Preparing LOD {label}',flush=True)
        metadata[label]=make_scene(label,output,camera,texture)
        if not args.skip_simulation:
            subprocess.run([sys.executable,str(ROOT/'tools/run_naiwa_sim.py'),str(output/label/'scene.bin'),
                            '--output',str(output/label),'--clear-color','be'],check=True)
        reports[label]=evaluate(label,output,source_rgb,source_packed,source_mask)
        print(label,json.dumps(reports[label]),flush=True)
    report={'camera':'assets/naiwa/camera.json','source':'../source_native.png','background_rgb332':'be',
            'metrics_exclude_background_for_primary_comparison':True,
            'roi_selection':'Manual semantic rectangles at fixed native coordinates, identical for every LOD.',
            'source_geometry_unchanged':True,'scene_metadata':metadata,'results':reports}
    if 'B' in reports and 'C' in reports:
        report['recommendation'] = {
            'label': 'B', 'source_triangles': metadata['B']['original_triangles'],
            'basis': '8k board-storage candidate; retains visible pupil/iris and finger silhouettes at the native 320x240 display. C improves static texture approximation modestly but increases command storage and draw time.',
            'B_to_C_foreground_mae_reduction': reports['B']['foreground_union']['mae_rgb_255']-reports['C']['foreground_union']['mae_rgb_255'],
            'B_to_C_draw_time_increase_ms_40mhz': reports['C']['estimated_draw_ms_at_40mhz']-reports['B']['estimated_draw_ms_at_40mhz'],
            'limits': 'This is a static reference-pose comparison. Animation poses may expose different triangles, change ordering, and have higher draw cost. Board memory mapping and timing still need separate verification.',
        }
    (output/'comparison_report.json').write_text(json.dumps(report,indent=2)+'\n')
    if set(reports)==set('ABCDE'):
        review_sheet(output,reports,source_rgb)


if __name__=='__main__':
    main()
