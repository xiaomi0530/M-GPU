import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time

import numpy as np

from run_naiwa_sim import ROOT, CORE_NAMES, RTL, SIM, command_environment, hardware_hashes, write_previews

ROM_NAMES = ('milkfrog_config.svh', 'milkfrog_vertex.mem', 'milkfrog_triangle.mem', 'milkfrog_order.mem',
             'milkfrog_order_meta.mem', 'milkfrog_matrix.mem', 'milkfrog_timeline.mem')
TOP = ROOT / 'MGPU.srcs/sources_1/demo/milkfrog_top.sv'
SOURCES = [SIM / 'milkfrog_board_sim.sv', TOP, *(RTL / name for name in CORE_NAMES), RTL / 'gpu_clock.sv']


def stage_rom(source, output):
    output.mkdir(parents=True, exist_ok=True)
    for name in ROM_NAMES:
        if not (source / name).is_file():
            raise FileNotFoundError(source / name)
        shutil.copyfile(source / name, output / name)
    return {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in ROM_NAMES}


def compilation_signature(rom, target_fps):
    cpp = ROOT / 'tools/milkfrog_board_sim.cpp'
    return hashlib.sha256(b''.join(p.read_bytes() for p in [*SOURCES, cpp, rom / 'milkfrog_config.svh']) + str(target_fps).encode()).hexdigest()


def build(output, rom, rebuild=False, target_fps=0):
    output.mkdir(parents=True, exist_ok=True)
    cpp = ROOT / 'tools/milkfrog_board_sim.cpp'
    signature = compilation_signature(rom, target_fps)
    stamp = output / 'signature.json'
    executable = output / ('Vmilkfrog_board_sim.exe' if os.name == 'nt' else 'Vmilkfrog_board_sim')
    env, msys = command_environment()
    if not rebuild and executable.is_file() and stamp.is_file() and json.loads(stamp.read_text()).get('signature') == signature:
        return executable, env
    for suffix in ('cpp', 'o', 'a'):
        (output / f'Vmilkfrog_board_sim__ALL.{suffix}').unlink(missing_ok=True)
    command = ['verilator', '--cc', '--exe', '--build', '-j', str(min(8, os.cpu_count() or 1)),
               '-Wno-fatal', '-Wno-WIDTHEXPAND', '-Wno-WIDTHTRUNC', '--top-module', 'milkfrog_board_sim',
               '--Mdir', output.as_posix(), '-I' + rom.as_posix(), '-CFLAGS', '-O3',
               f'-GTARGET_FPS={target_fps}',
               *[p.as_posix() for p in SOURCES], cpp.as_posix()]
    if msys:
        command = [str(msys / 'usr/bin/bash.exe'), '-lc', 'export PATH=/ucrt64/bin:/usr/bin:$PATH\n' + shlex.join(command)]
    with (output / 'build.log').open('w', encoding='utf8') as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode or not executable.is_file():
        raise RuntimeError(f'Board Verilator compilation failed; see {output / "build.log"}')
    stamp.write_text(json.dumps({'signature': signature}, indent=2) + '\n')
    return executable, env


def crosscheck(output, rom, capture_frames=1, init_proof=None):
    init_proof = init_proof or ROOT / 'out/milkfrog_board/build/register_init.rpt'
    required_init = "CELL=u_mgpu/u_rasterizer/frag_valid_reg REF_NAME=FDRE INIT=1'b0"
    if not init_proof.is_file() or required_init not in init_proof.read_text():
        raise RuntimeError('Board Icarus requires routed FPGA INIT evidence for rasterizer.frag_valid')
    work = output / 'icarus_40mhz'
    stage_rom(rom, work)
    shutil.copyfile(init_proof, work / 'register_init.rpt')
    binary = work / 'board.vvp'
    command = ['iverilog', '-g2012', '-s', 'milkfrog_board_tb', f'-Pmilkfrog_board_tb.CAPTURE_FRAMES={capture_frames}',
               '-I', str(work), '-o', str(binary),
               *map(str, SOURCES), str(SIM / 'milkfrog_board_tb.sv')]
    with (work / 'simulation.log').open('w', encoding='utf8') as log:
        subprocess.run(command, cwd=work, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['vvp', str(binary)], cwd=work, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
    checks = []
    for i in range(capture_frames):
        filename = 'board_icarus.hex' if i == 0 else f'board_icarus_{i:04d}.hex'
        words = (work / filename).read_text().split()
        if len(words) != 76800 or any('x' in value.lower() or 'z' in value.lower() for value in words):
            raise RuntimeError('Board Icarus framebuffer has missing/unknown pixels')
        actual = np.array([int(value, 16) for value in words], dtype=np.uint8)
        expected = np.fromfile(output / f'frame_{i:04d}.rgb332', dtype=np.uint8)
        checks.append(dict(capture=i, pixels=76800, mismatches=int(np.count_nonzero(actual != expected)),
                           framebuffer_sha256=hashlib.sha256(actual.tobytes()).hexdigest()))
    with (work / 'presentation_times.csv').open(newline='', encoding='utf8') as stream:
        rows = list(csv.DictReader(stream))
    times = [float(row['time_ns']) for row in rows]
    result = dict(top='milkfrog_top', gpu_mhz=40, vga_mhz=100, frames=capture_frames,
                  checks=checks, presentation_intervals_ns=[b-a for a,b in zip(times,times[1:])],
                  power_on_model=dict(signal='u_milkfrog_board_sim.u_milkfrog_top.u_mgpu.u_rasterizer.frag_valid',
                                      cell='u_mgpu/u_rasterizer/frag_valid_reg', primitive='FDRE', init="1'b0",
                                      applied='One assignment at time zero; subsequent resets do not force this signal',
                                      evidence='icarus_40mhz/register_init.rpt',
                                      evidence_sha256=hashlib.sha256(init_proof.read_bytes()).hexdigest()))
    (work / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    if any(check['mismatches'] for check in checks):
        raise RuntimeError('Board Icarus and Verilator framebuffer mismatch')
    print(f'PASS board Icarus 40 MHz: {capture_frames} frames, all pixels match accelerated Verilator', flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rom-dir', type=Path, default=ROOT / 'assets/milkfrog/v1_fixed/rom')
    parser.add_argument('--output', type=Path, default=ROOT / 'out/milkfrog_board/rtl')
    parser.add_argument('--frames', type=int, default=541)
    parser.add_argument('--rebuild', action='store_true')
    parser.add_argument('--video', action='store_true')
    parser.add_argument('--controls', action='store_true')
    parser.add_argument('--crosscheck', action='store_true')
    parser.add_argument('--target-fps', type=int, default=0)
    parser.add_argument('--icarus-frames', type=int, default=1)
    parser.add_argument('--reuse-capture', action='store_true')
    parser.add_argument('--fpga-init-proof', type=Path, default=ROOT / 'out/milkfrog_board/build/register_init.rpt')
    args = parser.parse_args()
    if args.frames < 1:
        parser.error('--frames must be positive')
    if args.icarus_frames < 1 or args.icarus_frames > args.frames:
        parser.error('--icarus-frames must be within the captured frame count')
    args.output = args.output.resolve(); args.rom_dir = args.rom_dir.resolve()
    before = hardware_hashes()
    rom_dir = args.output / 'rom'
    if args.reuse_capture:
        if any((args.rom_dir / name).read_bytes() != (rom_dir / name).read_bytes() for name in ROM_NAMES):
            raise RuntimeError('Cannot reuse captures after changing their staged ROMs')
        rom_hashes = {name: hashlib.sha256((rom_dir / name).read_bytes()).hexdigest() for name in ROM_NAMES}
    else:
        rom_hashes = stage_rom(args.rom_dir, rom_dir)
    inputs = dict(frames=args.frames, target_fps=args.target_fps, controls=args.controls,
                  scene_rom_sha256=rom_hashes, hardware_sha256=before,
                  top_sha256=hashlib.sha256(TOP.read_bytes()).hexdigest(),
                  compilation_signature=compilation_signature(rom_dir, args.target_fps))
    input_file = args.output / 'capture_inputs.json'
    started = time.monotonic()
    if args.reuse_capture:
        saved = json.loads(input_file.read_text())
        stamp = json.loads((args.output / 'verilated/signature.json').read_text())
        if any(saved.get(key) != value for key, value in inputs.items()) or stamp.get('signature') != inputs['compilation_signature']:
            raise RuntimeError('Cannot reuse captures with different RTL, executable signature, ROM, clocks or frame count')
        if len(list(args.output.glob('frame_*.rgb332'))) != args.frames:
            raise RuntimeError('Reused capture directory has an unexpected frame count')
        if any((args.output / f'frame_{i:04d}.rgb332').stat().st_size != 76800 for i in range(args.frames)):
            raise RuntimeError('Reused capture has an invalid framebuffer size')
        capture_seconds = saved['capture_seconds']
        print(f'Reusing {args.frames} complete captures after matching RTL/ROM/executable hashes...', flush=True)
    else:
        print('Compiling real milkfrog_top, ROMs and unchanged MGPU...', flush=True)
        exe, env = build(args.output / 'verilated', rom_dir, args.rebuild, args.target_fps)
        input_file.write_text(json.dumps(inputs, indent=2) + '\n')
        with (args.output / 'simulation.log').open('w', encoding='utf8') as log:
            command = [str(exe), str(args.output), str(args.frames)] + (['controls'] if args.controls else [])
            process = subprocess.Popen(command, cwd=rom_dir, env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                print(line.rstrip(), flush=True); log.write(line); log.flush()
            if process.wait():
                raise RuntimeError(f'Board simulation failed; see {args.output / "simulation.log"}')
        capture_seconds = time.monotonic()-started
        inputs['capture_seconds'] = capture_seconds
        input_file.write_text(json.dumps(inputs, indent=2) + '\n')
    write_previews(args.output, [(i, None) for i in range(args.frames)])
    with (args.output / 'frames.csv').open(newline='', encoding='utf8') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != args.frames:
        raise RuntimeError('Captured frame report has an unexpected row count')
    after = hardware_hashes()
    if before != after:
        raise RuntimeError('Core RTL changed during board simulation')
    config = (rom_dir / 'milkfrog_config.svh').read_text()
    count_match = re.search(r'\bFRAME_COUNT\s*=\s*(\d+)', config)
    if not count_match:
        raise RuntimeError('Cannot read FRAME_COUNT from config')
    frame_count = int(count_match.group(1))
    for i, row in enumerate(rows):
        if int(row['animation_frame']) != i % frame_count:
            raise RuntimeError(f'Animation frame sequence mismatch at capture {i}')
    loop_match = None
    if args.frames > frame_count:
        loop_match = (args.output / 'frame_0000.rgb332').read_bytes() == (args.output / f'frame_{frame_count:04d}.rgb332').read_bytes()
        if not loop_match:
            raise RuntimeError('Loop did not reproduce the initial framebuffer')
    result = dict(top='milkfrog_top', frames=args.frames, animation_frame_count=frame_count,
                  framebuffer=[320, 240], format='RGB332', input_clock_mhz=100, gpu_clock_mhz=50,
                  target_fps_parameter=args.target_fps, simulator='Verilator', seconds=capture_seconds,
                  reused_capture=args.reuse_capture,
                  hardware_unchanged=True, hardware_sha256=before, scene_rom_sha256=rom_hashes,
                  top_sha256=hashlib.sha256(TOP.read_bytes()).hexdigest(), loop_first_frame_equal=loop_match,
                  triangles_per_frame_min=min(int(r['triangles']) for r in rows),
                  triangles_per_frame_max=max(int(r['triangles']) for r in rows),
                  draw_cycles_max=max(int(r['draw_cycles']) for r in rows),
                  estimated_draw_ms_at_40mhz_max=max(int(r['draw_cycles']) for r in rows)/40000,
                  note='Only GPU clock divider and frame hold parameters differ from the bitstream; all ROM fetch/interpolation/draw/present logic is the same.')
    intervals = [int(rows[i]['root_cycles']) - int(rows[i-1]['root_cycles']) for i in range(1, len(rows))]
    result['presentation_intervals_100mhz_cycles'] = sorted(set(intervals))
    if args.controls:
        result['controls'] = json.loads((args.output / 'controls.json').read_text())
        if not all(result['controls'].get(key) is True for key in ('pause_at_frame_boundary', 'pause_stable', 'resume_next_frame', 'reset_frame_zero_equal')):
            raise RuntimeError('Board controls did not all pass')
    if args.crosscheck:
        print('Crosschecking real board top at 40 MHz with Icarus...', flush=True)
        result['icarus_40mhz'] = crosscheck(args.output, rom_dir, args.icarus_frames, args.fpga_init_proof)
    if args.video:
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-framerate', '30', '-i',
                        str(args.output / 'frame_%04d.png'), '-frames:v', str(min(args.frames, frame_count)),
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '16',
                        str(args.output / 'milkfrog_board_rtl.mp4')], check=True)
    (args.output / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS real board top: ' + str(args.output), flush=True)


if __name__ == '__main__':
    main()
