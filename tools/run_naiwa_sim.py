import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys
import time

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / 'MGPU.srcs/sources_1/new'
SIM = ROOT / 'MGPU.srcs/sim_1/new'
CORE_NAMES = ('mgpu.sv', 'vertex_shader.sv', 'rasterizer.sv', 'fifo.sv', 'shader.sv',
              'divider_signed.sv', 'divider_q16_16.sv', 'vga.sv')
SOURCES = [SIM / 'naiwa_sim.sv', *(RTL / name for name in CORE_NAMES)]
DEFAULT_BASELINE = ROOT / 'assets/naiwa/hardware_baseline.json'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hardware_hashes(baseline=DEFAULT_BASELINE):
    current = {path.name: sha256(path) for path in sorted(RTL.glob('*.sv'))}
    if baseline:
        before = json.loads(Path(baseline).read_text(encoding='utf8'))
        changed = sorted(name for name in set(before) | set(current) if before.get(name) != current.get(name))
        if changed:
            raise RuntimeError('Core RTL differs from the supplied baseline: ' + ', '.join(changed))
    return current


def load_scene(path):
    frames = []
    with Path(path).open('rb') as stream:
        header = stream.read(16)
        if len(header) != 16:
            raise ValueError('Scene header is truncated')
        magic, count, width, height = struct.unpack('<4I', header)
        if magic != 0x4e414957 or width != 320 or height != 240 or count < 1:
            raise ValueError('Scene requires NAIW header and native 320x240 framebuffer')
        matrix = np.frombuffer(stream.read(64), dtype='<i4').copy()
        if matrix.size != 16 or np.any(matrix < -131072) or np.any(matrix > 131071):
            raise ValueError('MVP matrix does not fit signed Q5.12 inputs')
        for _ in range(count):
            frame_header = stream.read(8)
            if len(frame_header) != 8:
                raise ValueError('Frame header is truncated')
            index, triangles = struct.unpack('<II', frame_header)
            data = np.frombuffer(stream.read(triangles * 48), dtype='<i4').copy()
            if data.size != triangles * 12:
                raise ValueError(f'Frame {index} vertex data is truncated')
            data = data.reshape(triangles, 3, 4)
            if np.any(data[:, :, :3] < -131072) or np.any(data[:, :, :3] > 131071):
                raise ValueError(f'Frame {index} vertex coordinates do not fit signed Q5.12')
            if np.any(data[:, :, 3] < 0) or np.any(data[:, :, 3] > 255):
                raise ValueError(f'Frame {index} vertex colors do not fit RGB332')
            frames.append((index, data))
        if stream.read(1):
            raise ValueError('Trailing bytes after final frame')
    if len({index for index, _ in frames}) != len(frames):
        raise ValueError('Frame indices must be unique')
    return matrix, frames


def command_environment():
    env = os.environ.copy()
    msys = Path(env.get('MSYS2_ROOT', 'C:/msys64'))
    if os.name == 'nt' and (msys / 'usr/bin/bash.exe').is_file():
        env['PATH'] = os.pathsep.join([str(msys / 'ucrt64/bin'), str(msys / 'usr/bin'), env.get('PATH', '')])
        return env, msys
    return env, None


def build_simulator(directory, rebuild=False):
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    signature = hashlib.sha256(b''.join(path.read_bytes() for path in [*SOURCES, ROOT / 'tools/naiwa_sim.cpp'])).hexdigest()
    exe = directory / ('Vnaiwa_sim.exe' if os.name == 'nt' else 'Vnaiwa_sim')
    stamp = directory / 'build_signature.json'
    env, msys = command_environment()
    if not rebuild and exe.is_file() and stamp.is_file() and json.loads(stamp.read_text()).get('signature') == signature:
        return exe, env
    for name in ('Vnaiwa_sim__ALL.cpp', 'Vnaiwa_sim__ALL.o', 'Vnaiwa_sim__ALL.a'):
        (directory / name).unlink(missing_ok=True)
    command = ['verilator', '--cc', '--exe', '--build', '-j', str(min(8, os.cpu_count() or 1)),
               '-Wno-fatal', '-Wno-WIDTHEXPAND', '-Wno-WIDTHTRUNC', '--top-module', 'naiwa_sim',
               '--Mdir', directory.as_posix(), '-CFLAGS', '-O3',
               *[p.as_posix() for p in SOURCES], (ROOT / 'tools/naiwa_sim.cpp').as_posix()]
    if msys:
        command = [str(msys / 'usr/bin/bash.exe'), '-lc', 'export PATH=/ucrt64/bin:/usr/bin:$PATH\n' + shlex.join(command)]
    elif not shutil.which('verilator', path=env.get('PATH')):
        raise RuntimeError('Install Verilator and a C++ compiler; on Windows set MSYS2_ROOT if MSYS2 is outside C:/msys64')
    print('Compiling unchanged MGPU RTL with Verilator...', flush=True)
    with (directory / 'build.log').open('w', encoding='utf8') as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode or not exe.is_file():
        raise RuntimeError(f'Verilator build failed; see {directory / "build.log"}')
    stamp.write_text(json.dumps({'signature': signature, 'sources': [str(p.relative_to(ROOT)) for p in SOURCES]}, indent=2) + '\n')
    return exe, env


def crosscheck_icarus(matrix, frame, output, clear_color, board_clock=False):
    index, commands = frame
    if len(commands) < 1:
        raise ValueError('Icarus crosscheck requires a frame with at least one triangle')
    compiler, runtime = shutil.which('iverilog'), shutil.which('vvp')
    if not compiler or not runtime:
        raise RuntimeError('Icarus crosscheck requires iverilog and vvp on PATH')
    work = output / ('icarus_board_clock' if board_clock else 'icarus')
    work.mkdir(parents=True, exist_ok=True)
    for name, words in [('matrix.mem', matrix), ('commands.mem', commands.ravel())]:
        (work / name).write_text(''.join(f'{int(value) & 0xffffffff:08x}\n' for value in words), encoding='ascii')
    binary = work / 'simulation.vvp'
    command = [compiler, '-g2012', '-s', 'naiwa_icarus_tb', f'-Pnaiwa_icarus_tb.TRIANGLE_COUNT={len(commands)}',
               f'-Pnaiwa_icarus_tb.GPU_HALF_PERIOD={12.5 if board_clock else 5.0}', '-o', str(binary),
               *map(str, SOURCES), str(SIM / 'naiwa_icarus_tb.sv')]
    print(f'Icarus crosscheck frame {index}, GPU clock {40 if board_clock else 100} MHz...', flush=True)
    started = time.monotonic()
    with (work / 'simulation.log').open('w', encoding='utf8') as log:
        subprocess.run(command, cwd=work, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run([runtime, str(binary), f'+CLEAR={clear_color:02x}'], cwd=work,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
    values = (work / 'icarus.hex').read_text().split()
    if len(values) != 76800 or any('x' in value.lower() or 'z' in value.lower() for value in values):
        raise RuntimeError('Icarus framebuffer is incomplete or contains unknown values')
    pixels = np.array([int(value, 16) for value in values], dtype=np.uint8)
    actual = np.fromfile(output / f'frame_{index:04d}.rgb332', dtype=np.uint8)
    if actual.size != pixels.size:
        raise RuntimeError('Verilator framebuffer size mismatch')
    mismatch = int(np.count_nonzero(actual != pixels))
    result = dict(frame=index, triangles=len(commands), pixels=int(pixels.size), mismatches=mismatch,
                  gpu_mhz=40 if board_clock else 100, vga_clock_mhz=100, seconds=time.monotonic()-started,
                  framebuffer_sha256=hashlib.sha256(pixels.tobytes()).hexdigest())
    (work / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    if mismatch:
        raise RuntimeError(f'Icarus differs from Verilator at {mismatch} pixels')
    print(f'PASS Icarus: all {pixels.size} framebuffer pixels exactly match Verilator', flush=True)
    return result


def write_previews(output, frames):
    for index, _ in frames:
        file = output / f'frame_{index:04d}.rgb332'
        pixels = np.fromfile(file, dtype=np.uint8)
        if pixels.size != 76800:
            raise RuntimeError(f'Invalid framebuffer size in {file}')
        values = pixels.reshape(240, 320).astype(np.uint16)
        rgb = np.stack(((values >> 5) * 255 // 7, ((values >> 2) & 7) * 255 // 7,
                        (values & 3) * 255 // 3), axis=-1).astype(np.uint8)
        Image.fromarray(rgb).save(output / f'frame_{index:04d}.png')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('scene', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clear-color', type=lambda value: int(value, 16), default=0x7e)
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'out/naiwa/verilated')
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE)
    parser.add_argument('--rebuild', action='store_true')
    parser.add_argument('--crosscheck', action='store_true')
    parser.add_argument('--board-clock-crosscheck', action='store_true')
    parser.add_argument('--video', action='store_true')
    parser.add_argument('--fps', type=int, default=30)
    args = parser.parse_args()
    if not 0 <= args.clear_color <= 255:
        parser.error('--clear-color must be a hexadecimal RGB332 byte')
    before = hardware_hashes(args.baseline)
    matrix, frames = load_scene(args.scene)
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    executable, env = build_simulator(args.build_dir, args.rebuild)
    print(f'Rendering {len(frames)} frame(s) through real MGPU RTL...', flush=True)
    started = time.monotonic()
    with (args.output / 'simulation.log').open('w', encoding='utf8') as log:
        process = subprocess.Popen([str(executable), str(args.scene.resolve()), str(args.output), f'{args.clear_color:02x}'],
                                   cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            log.write(line); log.flush(); print(line.rstrip(), flush=True)
        if process.wait():
            raise RuntimeError(f'RTL simulation failed; see {args.output / "simulation.log"}')
    write_previews(args.output, frames)
    with (args.output / 'frames.csv').open(newline='', encoding='utf8') as stream:
        cycle_rows = list(csv.DictReader(stream))
    draw_cycles = [int(row['draw_cycles']) for row in cycle_rows]
    report = dict(scene=str(args.scene.resolve()), scene_sha256=sha256(args.scene),
                  frames=len(frames), framebuffer=[320, 240], format='RGB332', clear_color=f'{args.clear_color:02x}',
                  engine='Verilator compiled original MGPU RTL', gpu_clock_mhz=100, vga_clock_mhz=100,
                  seconds=time.monotonic()-started, hardware_unchanged=True, hardware_sha256=before,
                  baseline_file=str(args.baseline.resolve()) if args.baseline.is_file() else None,
                  frame_indices=[index for index, _ in frames], total_triangles=sum(len(v) for _, v in frames),
                  draw_cycles_min=min(draw_cycles), draw_cycles_max=max(draw_cycles),
                  estimated_draw_ms_at_board_40mhz_max=max(draw_cycles)/40000,
                  performance_note='40 MHz estimate covers clear and draw only; board presentation additionally waits for VGA blanking.')
    if args.crosscheck:
        report['icarus'] = crosscheck_icarus(matrix, frames[0], args.output, args.clear_color)
    if args.board_clock_crosscheck:
        report['icarus_board_clock'] = crosscheck_icarus(matrix, frames[0], args.output, args.clear_color, True)
    after = hardware_hashes(args.baseline)
    if before != after:
        raise RuntimeError('Core RTL changed during simulation')
    if args.video:
        indices = [index for index, _ in frames]
        if indices != list(range(indices[0], indices[0] + len(indices))):
            raise ValueError('--video requires consecutive frame indices')
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-framerate', str(args.fps),
                        '-start_number', str(indices[0]), '-i', str(args.output / 'frame_%04d.png'),
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '16', str(args.output / 'rtl_animation.mp4')], check=True)
    (args.output / 'validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(f'PASS: original core RTL hashes unchanged; outputs: {args.output}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        raise SystemExit(1)
