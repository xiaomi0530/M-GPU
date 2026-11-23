"""Screen adjacent-frame changes and cache boundaries; not a recovered motion model."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from review_milkfrog import (
    ROOT,
    OUT,
    load_reference,
    load_baseline,
    producer_files,
    unpack,
)


def change(a, b):
    count = int(np.count_nonzero(a ^ b))
    return {
        "xor_pixels": count,
        "xor_union_fraction": count / max(1, int((a | b).sum())),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--baseline", type=Path, default=ROOT / "assets/naiwa/validation_baseline/baseline_rtl.npz")
    parser.add_argument("--producer-manifest", type=Path, required=True)
    parser.add_argument("--engine", default="Software ROM-cache painter, NOT RTL")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    producer = producer_files(args.input, args.producer_manifest)
    manifest = json.loads(args.producer_manifest.read_text())
    assignment = manifest["order_assignment_per_frame"]
    reference, _, _, reference_provenance = load_reference()
    baseline, baseline_provenance = load_baseline(args.baseline)
    arrays, inputs = [], []
    for frame in range(541):
        path = args.input / f"frame_{frame:04d}.rgb332"
        raw = path.read_bytes()
        arrays.append(np.frombuffer(raw, np.uint8).reshape(240, 320))
        inputs.append(
            {
                "frame": frame,
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    candidate = np.stack(arrays)
    fg = candidate != candidate[:, :1, :1]
    oldfg = baseline != baseline[:, :1, :1]
    ref = reference.astype(np.int16)
    rf = ~(
        (ref[..., 1] > ref[..., 0] + 24)
        & (ref[..., 1] > ref[..., 2] + 24)
        & (ref[..., 1] > 170)
    )
    rows = []
    for frame in range(1, 541):
        row = {
            "frame": frame,
            "cache_before": assignment[frame - 1],
            "cache_after": assignment[frame],
            "cache_switch": assignment[frame - 1] != assignment[frame],
            "candidate": change(fg[frame - 1], fg[frame]),
            "reference": change(rf[frame - 1], rf[frame]),
            "baseline": change(oldfg[frame - 1], oldfg[frame]),
            "candidate_color_changed_pixels": int(
                np.count_nonzero(candidate[frame] != candidate[frame - 1])
            ),
            "baseline_color_changed_pixels": int(
                np.count_nonzero(baseline[frame] != baseline[frame - 1])
            ),
        }
        rows.append(row)
    for row in rows:
        frame = row["frame"]
        neighbors = [
            r["candidate"]["xor_union_fraction"]
            for r in rows
            if 0 < abs(r["frame"] - frame) <= 2
        ]
        row["candidate_excess_over_local_median"] = row["candidate"][
            "xor_union_fraction"
        ] - float(np.median(neighbors))
    ordinary = [row for row in rows if not 390 <= row["frame"] <= 430]
    largest = sorted(
        ordinary, key=lambda row: row["candidate"]["xor_union_fraction"], reverse=True
    )[:8]
    spikes = sorted(
        ordinary,
        key=lambda row: row["candidate_excess_over_local_median"],
        reverse=True,
    )[:8]
    switches = sorted(
        [row for row in ordinary if row["cache_switch"]],
        key=lambda row: row["candidate_color_changed_pixels"],
        reverse=True,
    )[:8]
    chosen = []
    for row in largest[:2] + spikes[:4] + switches[:5]:
        frame = row["frame"]
        if frame not in chosen and frame < 540:
            chosen.append(frame)
    for item in inputs + producer:
        if (
            hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
            != item["sha256"]
        ):
            raise RuntimeError("Input changed during temporal review")
    report = {
        "engine": args.engine,
        "frame_count": 541,
        "adjacent_pairs": 540,
        "method": "Foreground symmetric-difference pixel count and fraction of the adjacent foreground union, compared with reference and pinned old RTL. Color-change count additionally screens cache-switch flashes. Local excess is relative to the median of two neighboring pairs on either side.",
        "limitations": "Screening only: normal articulation, silhouette quantization, duplicate source poses and color interpolation can increase these measures. Frames390..430 are excluded from anomaly ranking because the source deliberately jumps and turns rapidly. These scores do not establish exact source velocities or prove motion naturalness without viewing consecutive frames.",
        "largest_foreground_changes_outside_jump": largest,
        "largest_local_spikes_outside_jump": spikes,
        "largest_cache_switch_color_changes_outside_jump": switches,
        "contact_sheet_frames": chosen,
        "reference_inputs": reference_provenance,
        "baseline_provenance": baseline_provenance,
        "producer_files": producer,
        "input_files": inputs,
        "frames": rows,
    }
    (args.output / f"{args.name}.json").write_text(json.dumps(report, indent=2) + "\n")
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14)
    sheet = Image.new("RGB", (1920, max(1, len(chosen)) * 268), "#20252b")
    draw = ImageDraw.Draw(sheet)
    for row, frame in enumerate(chosen):
        for col, (label, frames) in enumerate(
            [("REFERENCE", reference), ("CANDIDATE: " + args.engine, candidate)]
        ):
            for step, target in enumerate([frame - 1, frame, frame + 1]):
                rgb = frames[target] if col == 0 else unpack(frames[target])
                x = col * 960 + step * 320
                sheet.paste(Image.fromarray(rgb), (x, row * 268 + 27))
                draw.text(
                    (x + 4, row * 268 + 5),
                    f"{target}: {label}",
                    font=font,
                    fill="white",
                )
    sheet.save(args.output / f"{args.name}_consecutive.jpg", quality=96)
    graph = Image.new("RGB", (1440, 420), "#20252b")
    draw = ImageDraw.Draw(graph)
    left, top, width, height = 65, 50, 1345, 300
    maximum = max(
        max(row[k]["xor_union_fraction"] for row in rows)
        for k in ["candidate", "reference"]
    )
    maximum = max(0.1, np.ceil(maximum * 10) / 10)
    draw.rectangle(
        (left + width * 390 / 540, top, left + width * 430 / 540, top + height),
        fill="#3d342b",
    )
    for tick in range(6):
        y = top + height - tick / 5 * height
        draw.line((left, y, left + width, y), fill="#44505c")
        draw.text((5, y - 8), f"{maximum*tick/5:.2f}", font=font, fill="white")
    for key, color in [("reference", "#c1c5cc"), ("candidate", "#56cfff")]:
        points = [
            (
                left + row["frame"] / 540 * width,
                top + height - row[key]["xor_union_fraction"] / maximum * height,
            )
            for row in rows
        ]
        draw.line(points, fill=color, width=2)
    for row in rows:
        if row["cache_switch"]:
            x = left + row["frame"] / 540 * width
            draw.line(
                (x, top + height + 4, x, top + height + 12), fill="#f2ba62", width=1
            )
    for tick in range(10):
        x = left + tick / 9 * width
        draw.text((x - 10, top + height + 17), str(tick * 60), font=font, fill="white")
    draw.text(
        (65, 8),
        "Adjacent foreground XOR / union: gray=reference, cyan=candidate. Orange ticks=cache switch.",
        font=font,
        fill="white",
    )
    draw.text(
        (65, 390),
        "Shaded390..430: deliberate jump/turn, excluded from ranked anomaly screening. Viewing consecutive frames remains required.",
        font=font,
        fill="white",
    )
    graph.save(args.output / f"{args.name}_timeline.png")
    print(
        json.dumps(
            {
                "contact_sheet_frames": chosen,
                "largest": [
                    (
                        r["frame"],
                        r["candidate"]["xor_pixels"],
                        r["reference"]["xor_pixels"],
                    )
                    for r in largest
                ],
                "cache_switches": [
                    (r["frame"], r["candidate_color_changed_pixels"]) for r in switches
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
