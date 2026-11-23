import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

from verify_vertex_lab import render, to_image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANIMATION = ROOT / "assets/milkfrog/v1_fixed/animation"
DEFAULT_ROM = ROOT / "assets/milkfrog/v1_fixed/rom"
DEFAULT_PROJECTION = ROOT / "out/naiwa/board_reference/projection.npz"
DATA = None
OUTPUT = None
COMPARE_SORT = False
CLEAR = 0xBE


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_projection(animation, rom, projection):
    """Bind source animation, optional orbit camera, cached order and projection."""
    animation, rom, projection = map(Path, (animation, rom, projection))
    manifest_path = rom / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    locked = {manifest_path: digest(manifest_path), projection: digest(projection)}
    sources = {
        "geometry.npz": "source_geometry_sha256",
        "matrices.npy": "source_matrices_sha256",
    }
    camera = animation / "camera_matrices.npy"
    if camera.exists() or bool(manifest.get("source_camera_matrices_sha256")):
        sources["camera_matrices.npy"] = "source_camera_matrices_sha256"
    for filename, field in sources.items():
        path = animation / filename
        locked[path] = digest(path)
        if locked[path] != manifest.get(field):
            raise RuntimeError(
                f"ROM projection is stale or missing provenance: {filename}"
            )
    with np.load(projection) as packed:
        for field in sources.values():
            if field not in packed:
                if field == "source_camera_matrices_sha256":
                    raise RuntimeError(f"Orbit projection is missing {field}")
            elif str(packed[field].item()) != manifest[field]:
                raise RuntimeError(
                    f"Projection provenance differs from ROM manifest: {field}"
                )
        expected_frames = manifest["configuration"]["FRAME_COUNT"]
        if len(packed["assignment"]) != expected_frames:
            raise RuntimeError("Projection frame count differs from ROM manifest")
        if not np.array_equal(
            packed["assignment"], manifest["order_assignment_per_frame"]
        ):
            raise RuntimeError("Projection cache assignment differs from ROM manifest")
        meta = [[row["offset"], row["count"]] for row in manifest["order_lists"]]
        if not np.array_equal(packed["order_meta"], meta):
            raise RuntimeError("Projection cache offsets differ from ROM manifest")
        if "board_triangle_source_indices" in packed:
            order_path = rom / "milkfrog_order.mem"
            locked[order_path] = digest(order_path)
            dense = np.asarray(
                [
                    int(line.strip(), 16)
                    for line in order_path.read_text().splitlines()
                    if line.strip()
                ],
                np.int64,
            )
            source_indices = packed["board_triangle_source_indices"]
            if len(dense) != manifest["configuration"]["ORDER_ENTRY_COUNT"] or np.any(
                dense >= len(source_indices)
            ):
                raise RuntimeError("ROM order indices are incomplete or out of range")
            if not np.array_equal(source_indices[dense], packed["order"]):
                raise RuntimeError("Projection triangle order differs from ROM payload")
    for path in rom.glob("milkfrog_*"):
        if path.suffix in {".mem", ".svh"}:
            locked[path] = digest(path)
    return manifest, locked


def assert_inputs_unchanged(locked):
    for path, expected in locked.items():
        if digest(path) != expected:
            raise RuntimeError(
                f"Input changed while preview/verification was running: {path}"
            )


def initialize(projection, output, compare_sort, clear):
    global DATA, OUTPUT, COMPARE_SORT, CLEAR
    with np.load(projection) as packed:
        names = ["pixels", "colors", "assignment", "order", "order_meta"]
        if compare_sort:
            names += ["per_frame_order", "per_frame_order_meta"]
        DATA = {name: packed[name] for name in names}
    OUTPUT = Path(output)
    COMPARE_SORT = compare_sort
    CLEAR = clear


def frame_image(item):
    capture, frame = item
    offset, count = DATA["order_meta"][DATA["assignment"][frame]]
    order = DATA["order"][offset : offset + count]
    background = [
        (None, [(0, 0), (319, 0), (319, 239)], [CLEAR] * 3),
        (None, [(0, 0), (319, 239), (0, 239)], [CLEAR] * 3),
    ]
    image = render(
        background
        + [
            (None, points, colors)
            for points, colors in zip(
                DATA["pixels"][frame, order], DATA["colors"][order]
            )
        ],
        320,
        240,
    )
    image.tofile(OUTPUT / f"frame_{frame:04d}.rgb332")
    to_image(image).save(OUTPUT / f"capture_{capture:04d}.png")
    result = dict(frame=frame)
    if COMPARE_SORT:
        start, length = DATA["per_frame_order_meta"][frame]
        ideal_order = DATA["per_frame_order"][start : start + length]
        ideal = render(
            background
            + [
                (None, points, colors)
                for points, colors in zip(
                    DATA["pixels"][frame, ideal_order], DATA["colors"][ideal_order]
                )
            ],
            320,
            240,
        )
        result["pixels_different_from_per_frame_sort"] = int(
            np.count_nonzero(image != ideal)
        )
        if result["pixels_different_from_per_frame_sort"] >= 120:
            to_image(ideal).save(OUTPUT / f"per_frame_sort_{frame:04d}.png")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--every", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--compare-sort", action="store_true")
    parser.add_argument("--animation-dir", type=Path, default=DEFAULT_ANIMATION)
    parser.add_argument("--rom-dir", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--projection", type=Path)
    args = parser.parse_args()
    if args.every < 1 or args.workers < 1:
        parser.error("--every and --workers must be positive")
    animation, rom = args.animation_dir.resolve(), args.rom_dir.resolve()
    if args.projection is None and (
        animation != DEFAULT_ANIMATION or rom != DEFAULT_ROM
    ):
        parser.error(
            "--projection is required when using non-default animation or ROM directories"
        )
    projection = (args.projection or DEFAULT_PROJECTION).resolve()
    args.output = args.output.resolve()
    manifest, locked = validate_projection(animation, rom, projection)
    frames = list(range(0, manifest["configuration"]["FRAME_COUNT"], args.every))
    args.output.mkdir(parents=True, exist_ok=True)
    comparisons = []
    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=initialize,
        initargs=(
            str(projection),
            str(args.output),
            args.compare_sort,
            manifest.get("clear_color_rgb332", 0xBE),
        ),
    ) as pool:
        for count, result in enumerate(pool.map(frame_image, enumerate(frames)), 1):
            comparisons.append(result)
            if count % 30 == 0 or count == len(frames):
                print(
                    f'Painter preview {count}/{len(frames)}, source frame {result["frame"]}',
                    flush=True,
                )
    if args.compare_sort:
        (args.output / "sort_comparison.json").write_text(
            json.dumps(
                dict(
                    method="Actual cached painter order versus per-frame front-surface dependency order; both images use only sequential triangle overwrite, with no depth buffer.",
                    frames=comparisons,
                ),
                indent=2,
            )
            + "\n"
        )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            str(30 / args.every),
            "-i",
            str(args.output / "capture_%04d.png"),
            "-frames:v",
            str(len(frames)),
            "-vf",
            "scale=640:480:flags=neighbor,drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='SOFTWARE PAINTER PREVIEW - NOT RTL':fontsize=16:fontcolor=white:box=1:boxcolor=black@0.6:x=10:y=10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "16",
            str(args.output / "painter_preview.mp4"),
        ],
        check=True,
    )
    assert_inputs_unchanged(locked)
    provenance = dict(
        engine="Independent fixed-point software rasterization, no depth buffer, actual ROM painter order; not RTL.",
        frames=frames,
        clear_color_rgb332=manifest.get("clear_color_rgb332", 0xBE),
        geometry_sha256=manifest["source_geometry_sha256"],
        matrices_sha256=manifest["source_matrices_sha256"],
        animation_dir=str(animation),
        rom_dir=str(rom),
        projection_path=str(projection),
        manifest_sha256=locked[rom / "manifest.json"],
        rom_payload_sha256={
            path.name: value
            for path, value in locked.items()
            if path.parent == rom and path.suffix in {".mem", ".svh"}
        },
        projection_sha256=locked[projection],
    )
    if "source_camera_matrices_sha256" in manifest:
        provenance["camera_matrices_sha256"] = manifest["source_camera_matrices_sha256"]
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
