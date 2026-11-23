import argparse
from pathlib import Path
import subprocess
import sys

from scene_rom import stage_rom

ROOT = Path(__file__).resolve().parents[1]


def run(command, output, log):
    result = subprocess.run(command, cwd=output, capture_output=True, text=True, timeout=300)
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode or 'ERROR:' in result.stdout or 'FATAL:' in result.stdout:
        print(result.stdout + result.stderr)
        raise RuntimeError(f'Failed: {log}')
    print(result.stdout.strip())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'out/tests')
    args = parser.parse_args()
    output = args.output.resolve()
    stage_rom(ROOT, output)
    rtl = sorted((ROOT / 'MGPU.srcs/sources_1/new').glob('*.sv'))
    tbdir = ROOT / 'MGPU.srcs/sim_1/new'
    for name in ('vga_tb', 'top_clear_tb', 'space_sequence_tb', 'midiyas_boot_tb', 'double_buffer_tb', 'top_tb'):
        sources = rtl
        extra = []
        if name in ('space_sequence_tb', 'midiyas_boot_tb'):
            extra = ['-DSPACE_SCENE_STUB']
            sources = [file for file in rtl if file.stem in ('top', 'gpu_clock')]
            if name == 'midiyas_boot_tb':
                sources += [tbdir / 'space_sequence_tb.sv']
        if name == 'top_tb':
            extra = ['-DSTUDIO_SIMULATION', '-Ptop_tb.GPU_CLK_DIV_LOG2=1',
                     '-Ptop_tb.STAGE_HOLD_MS=0', '-Ptop_tb.TARGET_FPS=0']
        binary = output / f'{name}.vvp'
        print(f'Running {name}', flush=True)
        run(['iverilog', '-g2012', *extra, '-s', name, '-o', str(binary),
             *map(str, sources), str(tbdir / f'{name}.sv')], output, output / f'{name}_compile.log')
        run(['vvp', str(binary)], output, output / f'{name}.log')
    run([sys.executable, str(ROOT / 'tools/verify_vertex_lab.py'), '--output', str(output)],
        output, output / 'pixels.log')
    if args.python:
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tools', '-p', 'test_*.py', '-v'], cwd=ROOT)
        result.check_returncode()
    print(f'PASS: regression results in {output}')


if __name__ == '__main__':
    main()
