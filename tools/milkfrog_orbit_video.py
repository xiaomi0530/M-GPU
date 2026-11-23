import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import cv2
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def main(output, animation, version1):
    camera = json.loads((animation/'camera.json').read_text(encoding='utf8'))
    clip = cv2.VideoCapture(str(version1))
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 22)
    small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 16)
    encoder = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo',
                                '-pixel_format', 'rgb24', '-video_size', '1280x540', '-framerate', '30', '-i', '-',
                                '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                                str(output/'version1_vs_orbit_v2.mp4')], stdin=subprocess.PIPE)
    frames = []
    selected = [round(index*540/11) for index in range(12)]
    try:
        for frame in range(541):
            ok, pixels = clip.read()
            if not ok:
                raise RuntimeError(f'Version 1 video ended at frame {frame}')
            fixed = Image.fromarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB))
            orbit = Image.open(output/f'frame_{frame:04d}.png').convert('RGB')
            canvas = Image.new('RGB', (1280, 540), '#20252b')
            draw = ImageDraw.Draw(canvas)
            angle = camera['frame_camera'][frame]['orbit_degrees']
            draw.text((20, 14), 'V1: fixed camera / MGPU RTL', font=font, fill='white')
            draw.text((660, 14), f'V2: orbit camera {angle:05.1f} deg / MGPU RTL', font=font, fill='white')
            draw.text((20, 39), f'Frame {frame:03d} / {frame/30:05.2f} s - same laugh animation', font=small, fill='#bac8d5')
            canvas.paste(fixed.resize((640, 480), Image.Resampling.NEAREST), (0, 60))
            canvas.paste(orbit.resize((640, 480), Image.Resampling.NEAREST), (640, 60))
            encoder.stdin.write(canvas.tobytes())
            if frame in selected:
                tile = Image.new('RGB', (320, 265), '#20252b')
                ImageDraw.Draw(tile).text((8, 4), f'f{frame:03d} / {frame/30:.2f}s / orbit {angle:.0f} deg', font=small, fill='white')
                tile.paste(orbit, (0, 25))
                frames.append(tile)
    finally:
        clip.release()
        encoder.stdin.close()
    if encoder.wait():
        raise RuntimeError('Orbit comparison video encoding failed')
    sheet = Image.new('RGB', (1280, 265*3), '#20252b')
    for index, tile in enumerate(frames):
        sheet.paste(tile, ((index%4)*320, (index//4)*265))
    sheet.save(output/'orbit_keyframes.jpg', quality=94)
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-framerate', '30',
                    '-i', str(output/'frame_%04d.png'), '-vf',
                    'trim=end_frame=541,fps=12,scale=480:360:flags=neighbor,split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=none',
                    '-loop', '0', str(output/'orbit_preview.gif')], check=True)
    (output/'media_provenance.json').write_text(json.dumps(dict(
        version1_video=version1.relative_to(ROOT).as_posix() if version1.is_relative_to(ROOT) else str(version1),
        version1_video_sha256=hashlib.sha256(version1.read_bytes()).hexdigest(),
        camera_config_sha256=hashlib.sha256((animation/'camera.json').read_bytes()).hexdigest(),
        frames=541, fps=30, comparison='Decoded delivered V1 RTL video alongside native V2 RTL frame images. This is not a fixed-view source-reconstruction score.'), indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'out/milkfrog_orbit_v2/rtl')
    parser.add_argument('--animation-dir', type=Path, default=ROOT/'assets/milkfrog/v2_orbit/animation')
    parser.add_argument('--version1', type=Path, default=ROOT/'deliverables/milkfrog/v1_fixed/milkfrog_board_rtl.mp4')
    args = parser.parse_args()
    main(args.output.resolve(), args.animation_dir.resolve(), args.version1.resolve())
