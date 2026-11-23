import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from preview_milkfrog_rom import (
    DEFAULT_ANIMATION,
    DEFAULT_ROM,
    assert_inputs_unchanged,
    validate_projection,
)

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(
    output,
    bitstream,
    reference=None,
    editable_proof=None,
    *,
    animation_dir=None,
    rom_dir=None,
    projection=None,
):
    output = Path(output).resolve()
    animation = Path(animation_dir or DEFAULT_ANIMATION).resolve()
    rom = Path(rom_dir or DEFAULT_ROM).resolve()
    projection = Path(projection).resolve() if projection is not None else None
    assert not (
        output / "INVALIDATED.txt"
    ).exists(), "Simulation candidate is marked invalidated"
    source = ROOT / "milkfrog.blend"
    manifest = json.loads(
        (ROOT / "assets/naiwa/candidates/source_manifest.json").read_text(
            encoding="utf8"
        )
    )
    assert digest(source) == manifest["source_sha256"], "Original model changed"
    baseline = json.loads((ROOT / "assets/naiwa/hardware_baseline.json").read_text())
    current = {
        p.name: digest(p) for p in (ROOT / "MGPU.srcs/sources_1/new").glob("*.sv")
    }
    assert baseline == current, "Existing RTL changed"
    top = ROOT / "MGPU.srcs/sources_1/demo/milkfrog_top.sv"
    simulation = json.loads((output / "validation.json").read_text())
    assert simulation["top_sha256"] == digest(top), "Simulation used a stale scene top"
    assert (
        simulation["hardware_sha256"] == baseline
    ), "Simulation core hashes differ from baseline"
    assert (
        simulation["hardware_unchanged"] and simulation["loop_first_frame_equal"]
    ), "Simulation integrity checks failed"
    assert all(
        simulation["controls"].values()
    ), "Pause, resume or reset verification failed"
    crosscheck = simulation["icarus_40mhz"]
    checks = crosscheck.get("checks", [crosscheck])
    assert checks and all(
        check["mismatches"] == 0 for check in checks
    ), "40 MHz clock crosscheck failed"
    rom_info = json.loads((rom / "manifest.json").read_text())
    assert (
        rom_info["configuration"]["FRAME_COUNT"] == 541
    ), "This animation must preserve all 541 action frames"
    locked = {rom / "manifest.json": digest(rom / "manifest.json")}
    for name in ["geometry.npz", "matrices.npy"]:
        locked[animation / name] = digest(animation / name)
    assert (
        digest(animation / "geometry.npz") == rom_info["source_geometry_sha256"]
    ), "ROM geometry is stale"
    assert (
        digest(animation / "matrices.npy") == rom_info["source_matrices_sha256"]
    ), "ROM motion is stale"
    has_camera = (
        animation / "camera_matrices.npy"
    ).exists() or bool(rom_info.get("source_camera_matrices_sha256"))
    if has_camera:
        camera_path = animation / "camera_matrices.npy"
        locked[camera_path] = digest(camera_path)
        assert locked[camera_path] == rom_info.get(
            "source_camera_matrices_sha256"
        ), "ROM orbit camera is stale"
        assert (
            projection is not None
        ), "Orbit verification requires --projection to bind the moving-camera reference"
    if projection is not None:
        projection_info, projection_inputs = validate_projection(
            animation, rom, projection
        )
        assert (
            projection_info == rom_info
        ), "Manifest changed during projection validation"
        locked.update(projection_inputs)
    editable_report = None
    if editable_proof is not None:
        editable_report = json.loads(editable_proof.read_text(encoding="utf8"))
        assert (
            editable_report["geometry_sha256"] == rom_info["source_geometry_sha256"]
        ), "Editable model geometry proof is stale"
        assert (
            editable_report["matrices_sha256"] == rom_info["source_matrices_sha256"]
        ), "Editable model motion proof is stale"
        assert editable_report["blender_sha256"] == digest(
            animation / "milkfrog_laugh.blend"
        ), "Editable Blender file differs from proof"
        assert editable_report["original_source_blender_sha256"] == digest(
            source
        ), "Editable model used a different source"
        assert (
            editable_report["integer_frame_equivalence"]
            and editable_report["frames"] == 541
        )
        assert editable_report["groups"] == rom_info["configuration"]["GROUP_COUNT"]
        assert all(
            row["triangle_connectivity_equal"]
            and row["source_corner_color_max_error"] < 1e-6
            for row in editable_report["topology"]
        )
        if has_camera:
            assert (
                editable_report["camera_matrices_sha256"]
                == rom_info["source_camera_matrices_sha256"]
            ), "Editable camera projection proof is stale"
            locked[animation / "camera_world.npy"] = digest(
                animation / "camera_world.npy"
            )
            assert (
                editable_report["camera_world_sha256"]
                == locked[animation / "camera_world.npy"]
            ), "Editable camera world-pose proof is stale"
            assert editable_report[
                "camera_integer_frame_equivalence"
            ], "Editable camera does not reproduce the orbit"
            for field in [
                "camera_max_abs_world_matrix_error",
                "camera_max_abs_projection_matrix_error",
            ]:
                assert np.isfinite(
                    editable_report[field]
                ), f"Invalid editable camera error: {field}"
    complete_reference = reference is not None
    reference = (
        Path(reference)
        if reference is not None
        else (
            projection.parent
            if projection is not None
            else ROOT / "out/naiwa/board_reference"
        )
    )
    if complete_reference:
        provenance = json.loads((reference / "provenance.json").read_text())
        assert (
            provenance["geometry_sha256"] == rom_info["source_geometry_sha256"]
        ), "Software reference geometry is stale"
        assert (
            provenance["matrices_sha256"] == rom_info["source_matrices_sha256"]
        ), "Software reference motion is stale"
        assert (
            provenance.get("clear_color_rgb332", 0xBE) == rom_info["clear_color_rgb332"]
        ), "Software reference background is stale"
        if "manifest_sha256" in provenance or has_camera:
            assert (
                provenance.get("manifest_sha256") == locked[rom / "manifest.json"]
            ), "Software reference ROM manifest is stale"
        if projection is not None:
            assert (
                provenance["projection_sha256"] == locked[projection]
            ), "Software reference projection is stale"
        if has_camera:
            assert (
                provenance.get("camera_matrices_sha256")
                == rom_info["source_camera_matrices_sha256"]
            ), "Software reference used a different orbit camera"
    frames = []
    for index in range(541):
        path = output / f"frame_{index:04d}.rgb332"
        assert path.stat().st_size == 76800, f"Incomplete frame {index}"
        frames.append(dict(frame=index, sha256=digest(path)))
    comparisons = []
    for path in sorted(reference.glob("frame_*.rgb332")):
        actual = output / path.name
        if not actual.exists():
            continue
        expected = np.fromfile(path, np.uint8)
        observed = np.fromfile(actual, np.uint8)
        differences = int(np.count_nonzero(expected != observed))
        assert differences == 0, f"{path.name}: {differences} pixel differences"
        comparisons.append(
            dict(
                frame=int(path.stem.split("_")[-1]),
                pixels=76800,
                mismatches=differences,
            )
        )
    assert len(comparisons) >= 9, "Keyframe checks incomplete"
    if complete_reference:
        assert [c["frame"] for c in comparisons] == list(
            range(541)
        ), "Full software reference is incomplete"
    with (output / "frames.csv").open(newline="", encoding="utf8") as stream:
        timing = list(csv.DictReader(stream))
    assert len(timing) in (541, 542), "Frame timing log incomplete"
    assert [int(row["animation_frame"]) for row in timing] == [
        i % 541 for i in range(len(timing))
    ], "Animation skipped or repeated a phase"
    loop_verified = False
    if len(timing) == 542:
        assert digest(output / "frame_0541.rgb332") == digest(
            output / "frame_0000.rgb332"
        ), "Loop frame differs from first frame"
        loop_verified = True
    draw_cycles = np.array([int(row["draw_cycles"]) for row in timing[:541]])
    staged = output / "rom"
    rom_payloads = {}
    for path in rom.glob("milkfrog_*"):
        if path.suffix in {".mem", ".svh"}:
            locked[path] = digest(path)
            rom_payloads[path.name] = locked[path]
            assert locked[path] == digest(
                staged / path.name
            ), f"Simulation used stale {path.name}"
            assert (
                simulation["scene_rom_sha256"].get(path.name) == locked[path]
            ), f"Simulation provenance used stale {path.name}"
    if complete_reference and ("rom_payload_sha256" in provenance or has_camera):
        assert (
            provenance.get("rom_payload_sha256") == rom_payloads
        ), "Software reference used a different ROM payload"
    build_report = None
    if bitstream:
        assert (
            bitstream.is_file() and bitstream.stat().st_size > 1000000
        ), "No usable bitstream"
        build = bitstream.parent
        assert not (
            build / "INVALIDATED.txt"
        ).exists(), "Bitstream candidate is marked invalidated"
        report = (build / "build_validation.txt").read_text()
        assert (
            "PASS:" in report and "DRC errors: 0" in report
        ), "Build checks not complete"
        assert digest(build / top.name) == digest(
            top
        ), "Bitstream used a stale scene top"
        for path in rom.glob("milkfrog_*"):
            if path.suffix in {".mem", ".svh"}:
                assert digest(path) == digest(
                    build / path.name
                ), f"Bitstream used stale {path.name}"
        try:
            bitstream_name = str(bitstream.relative_to(ROOT))
        except ValueError:
            bitstream_name = str(bitstream)
        build_report = dict(
            path=bitstream_name,
            bytes=bitstream.stat().st_size,
            sha256=digest(bitstream),
            validation=report,
        )
    result = dict(
        source_model_unchanged=True,
        existing_rtl_unchanged=True,
        rtl_baseline_path="assets/naiwa/hardware_baseline.json",
        rtl_baseline_scope="Matches the reviewed SystemVerilog source snapshot; historical source-style changes are recorded in assets/validation/systemverilog_migration.json.",
        rtl_file_hashes=current,
        scene_top_sha256=digest(top),
        frame_count=541,
        captured_frame_count=len(timing),
        loop_frame_verified=loop_verified,
        fps=30,
        duration_seconds=541 / 30,
        resolution=[320, 240],
        format="RGB332",
        reference_comparisons=comparisons,
        all_frames_match_independent_software=complete_reference,
        frames=frames,
        bitstream=build_report,
        controls=simulation["controls"],
        clock_crosscheck=crosscheck,
        draw_timing_at_40mhz=dict(
            min_ms=float(draw_cycles.min() / 40000),
            max_ms=float(draw_cycles.max() / 40000),
            mean_ms=float(draw_cycles.mean() / 40000),
            all_draws_below_30fps_period=bool(np.all(draw_cycles <= 40000000 / 30)),
            scope="GPU clear and draw cycles; VGA present wait and frame pacing are separate.",
        ),
        editable_model=editable_report,
        inputs=dict(
            animation_dir=str(animation),
            rom_dir=str(rom),
            projection=str(projection) if projection is not None else None,
            manifest_sha256=locked[rom / "manifest.json"],
            source_geometry_sha256=rom_info["source_geometry_sha256"],
            source_matrices_sha256=rom_info["source_matrices_sha256"],
            source_camera_matrices_sha256=rom_info.get("source_camera_matrices_sha256"),
            rom_payload_sha256=rom_payloads,
        ),
        scope="All 541 output images are read from real milkfrog_top/MGPU RTL front buffers; listed comparisons match independent fixed-point painter rasterization without a depth buffer.",
        limits="Video is encoded at the reference 30 fps; board throughput is assessed separately from draw/present clocks. No physical board download or monitor observation is claimed.",
    )
    assert_inputs_unchanged(locked)
    (output / "final_validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        f"PASS: original model and {len(current)} RTL files unchanged; 541 complete frames; {len(comparisons)} exact reference frames; bitstream={bool(bitstream)}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--bitstream", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--editable-proof", type=Path)
    parser.add_argument("--animation-dir", type=Path, default=DEFAULT_ANIMATION)
    parser.add_argument("--rom-dir", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--projection", type=Path)
    args = parser.parse_args()
    custom_sources = (
        args.animation_dir.resolve() != DEFAULT_ANIMATION
        or args.rom_dir.resolve() != DEFAULT_ROM
    )
    if custom_sources and args.output is None:
        parser.error(
            "--output is required for non-default sources so the V1 validation is not overwritten"
        )
    output = (args.output or ROOT / "out/milkfrog_board/rtl").resolve()
    verify(
        output,
        args.bitstream.resolve() if args.bitstream else None,
        args.reference.resolve() if args.reference else None,
        args.editable_proof.resolve() if args.editable_proof else None,
        animation_dir=args.animation_dir,
        rom_dir=args.rom_dir,
        projection=args.projection,
    )
