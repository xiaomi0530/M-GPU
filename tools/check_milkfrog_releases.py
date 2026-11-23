"""Validate both published variants using only repository files, without out/."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_path(value):
    path = (ROOT/value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f'Release path escaped repository: {value}')
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def check():
    catalog = json.loads((ROOT/'assets/milkfrog/versions.json').read_text(encoding='utf8'))
    assert set(catalog['versions']) == {'v1_fixed', 'v2_orbit'}
    shared = catalog['shared']
    baseline = json.loads(repository_path(shared['rtl_baseline']).read_text())
    current = {path.name: digest(path) for path in repository_path(shared['core_directory']).glob('*.sv')}
    assert current == baseline, 'GPU core differs from its validated baseline'
    top_hash = digest(repository_path(shared['scene_top']))
    source_hash = digest(repository_path(shared['source_model']))
    motion_hashes = {
        digest(repository_path(item['animation'])/'matrices.npy')
        for item in catalog['versions'].values()
    }
    assert len(motion_hashes) == 1, 'The two camera variants no longer share the verified laugh motion'
    for version, item in catalog['versions'].items():
        assert item['status'] == 'supported'
        animation, rom, delivery = (repository_path(item[key]) for key in ('animation', 'rom', 'delivery'))
        repository_path(item['workflow'])
        manifest = json.loads((delivery/'manifest.json').read_text())
        assert manifest['version'] == version and manifest['status'] == 'supported'
        assert manifest['hardware_depth_buffer'] is False
        listed = {entry['path'] for entry in manifest['files']}
        actual = {path.relative_to(delivery).as_posix() for path in delivery.rglob('*') if path.is_file()}
        assert actual == listed | {'manifest.json'}, f'{version}: unlisted or missing delivery files'
        for entry in manifest['files']:
            path = repository_path(item['delivery']+'/'+entry['path'])
            assert path.stat().st_size == entry['bytes'], f'{version}: size changed: {path.name}'
            assert digest(path) == entry['sha256'], f'{version}: delivery changed: {path.name}'
        for entry in manifest['inputs']:
            assert digest(repository_path(entry['path'])) == entry['sha256'], f'{version}: input changed: {entry["path"]}'
        assert {item['video'], item['preview'], 'milkfrog_nexys_a7.bit', 'README.md'} <= listed
        report = json.loads((delivery/'reports/final_validation.json').read_text())
        proof = json.loads((delivery/'reports/editable_blender_validation.json').read_text())
        rom_manifest = json.loads((rom/'manifest.json').read_text())
        assert report['existing_rtl_unchanged'] and report['source_model_unchanged']
        assert report['rtl_file_hashes'] == baseline and report['scene_top_sha256'] == top_hash
        assert report['all_frames_match_independent_software'] and report['frame_count'] == 541
        assert report['captured_frame_count'] == 542 and report['loop_frame_verified']
        assert all(report['controls'].values())
        assert all(row['mismatches'] == 0 for row in report['clock_crosscheck']['checks'])
        comparisons = report['reference_comparisons']
        assert [row['frame'] for row in comparisons] == list(range(541))
        assert sum(row['pixels'] for row in comparisons) == 41548800
        assert all(row['mismatches'] == 0 for row in comparisons)
        assert digest(delivery/'milkfrog_nexys_a7.bit') == report['bitstream']['sha256']
        assert digest(animation/'milkfrog_laugh.blend') == proof['blender_sha256']
        assert proof['original_source_blender_sha256'] == source_hash
        for filename, field in [('geometry.npz', 'source_geometry_sha256'), ('matrices.npy', 'source_matrices_sha256')]:
            assert digest(animation/filename) == rom_manifest[field]
        assert digest(rom/'manifest.json') == report['inputs']['manifest_sha256']
        for filename, expected in report['inputs']['rom_payload_sha256'].items():
            assert digest(rom/filename) == expected, f'{version}: ROM no longer matches RTL'
        if version == 'v2_orbit':
            assert digest(animation/'camera_matrices.npy') == rom_manifest['source_camera_matrices_sha256']
            assert proof['camera_integer_frame_equivalence']
        print(f'PASS {version}: {len(manifest["files"])} delivered files, {len(manifest["inputs"])} inputs, 541 exact frames, unchanged GPU and verified bitstream')
    print('PASS both supported versions; no generated out/ files required')


if __name__ == '__main__':
    check()
