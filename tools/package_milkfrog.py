import argparse
import hashlib
import json
from pathlib import Path
import shutil

from verify_milkfrog import verify

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    'milkfrog_nexys_a7.bit': 'out/milkfrog_board/build/milkfrog_nexys_a7.bit',
    'milkfrog_board_rtl.mp4': 'out/milkfrog_board/rtl/milkfrog_board_rtl.mp4',
    'reference_vs_rtl.mp4': 'out/milkfrog_board/rtl/reference_vs_rtl.mp4',
    'rtl_preview.gif': 'out/milkfrog_board/rtl/rtl_preview.gif',
    'keyframes.png': 'out/milkfrog_board/rtl/review/visual_review_compact.png',
    'reports/final_validation.json': 'out/milkfrog_board/rtl/final_validation.json',
    'reports/visual_review.json': 'out/milkfrog_board/rtl/review/visual_review.json',
    'reports/regions.json': 'out/milkfrog_board/rtl/review/regions.json',
    'reports/temporal.json': 'out/milkfrog_board/rtl/review/temporal.json',
    'reports/editable_blender_validation.json': 'out/naiwa/validation/editable_blender_validation.json',
    'reports/build_validation.txt': 'out/milkfrog_board/build/build_validation.txt',
    'reports/timing.rpt': 'out/milkfrog_board/build/timing.rpt',
    'reports/utilization.rpt': 'out/milkfrog_board/build/utilization.rpt',
    'reports/drc.rpt': 'out/milkfrog_board/build/drc.rpt',
    'reports/register_init.rpt': 'out/milkfrog_board/build/register_init.rpt',
    'reports/icarus_comparison.json': 'out/milkfrog_board/rtl/icarus_40mhz/comparison.json',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'deliverables/milkfrog/v1_fixed')
    args = parser.parse_args()
    output = args.output.resolve()
    bitstream = ROOT/FILES['milkfrog_nexys_a7.bit']
    verify(ROOT/'out/milkfrog_board/rtl', bitstream, ROOT/'out/naiwa/painter_verified',
           ROOT/'out/naiwa/validation/editable_blender_validation.json')
    entries = []
    for name, original in FILES.items():
        source, destination = ROOT/original, output/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == digest
        entries.append(dict(path=name, source=original, bytes=source.stat().st_size, sha256=digest))
    inputs = [ROOT/'milkfrog.blend', *sorted((ROOT/'assets/milkfrog/v1_fixed/animation').glob('*')),
              *sorted((ROOT/'assets/milkfrog/v1_fixed/rom').glob('*')),
              *sorted((ROOT/'MGPU.srcs/sources_1/new').glob('*.sv')),
              ROOT/'MGPU.srcs/sources_1/demo/milkfrog_top.sv']
    readme = output/'README.md'
    if readme.is_file():
        entries.append(dict(path='README.md', bytes=readme.stat().st_size,
                            sha256=hashlib.sha256(readme.read_bytes()).hexdigest()))
    manifest = dict(version='v1_fixed', status='supported', target='Nexys A7-100T / xc7a100tcsg324-1', frames=541, fps=30,
                    resolution=[320, 240], format='RGB332', hardware_depth_buffer=False,
                    physical_board_tested=False, files=entries,
                    inputs=[dict(path=p.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                            for p in inputs if p.is_file()],
                    report_paths='Reports preserve original run paths as provenance. Regenerate full frames under out/ using docs/milkfrog_workflow.md.')
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf8', newline='\n')
    print(f'PACKAGED {len(entries)} verified files in {output}')


if __name__ == '__main__':
    main()
