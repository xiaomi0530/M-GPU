"""Compare visible lying foot/hand regions without a geometric depth-buffer oracle."""

from pathlib import Path
import argparse
import hashlib
import io
import json

import numpy as np
from PIL import Image, ImageDraw

from review_milkfrog import (
    unpack,
    dark_region_component as component,
    load_reference,
    load_baseline,
    producer_files,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out/milkfrog_iteration2/review"
REGIONS = {
    "upper_foot": [80, 105, 140, 178],
    "near_foot_partial": [75, 180, 110, 221],
    "upper_hand": [165, 120, 215, 169],
    "lower_hand": [126, 158, 172, 202],
}


def difference(a, b):
    if a is None or b is None:
        return None
    angle = abs(a["major_axis_screen_deg"] - b["major_axis_screen_deg"])
    return {
        "center_error_px": float(
            np.linalg.norm(np.array(a["center_xy"]) - b["center_xy"])
        ),
        "area_ratio": b["area_px"] / a["area_px"],
        "axis_difference_deg": min(angle, 180 - angle),
        "axis_reliable": min(a["axis_ratio"], b["axis_ratio"]) >= 1.5,
        "any_roi_clipping": a["roi_clipped"] or b["roi_clipped"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--pattern", default="frame_{frame:04d}.rgb332")
    parser.add_argument("--name", required=True)
    parser.add_argument("--expect-frames", type=int)
    parser.add_argument("--engine", default="Software painter, not RTL")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--baseline", type=Path, default=ROOT / "assets/naiwa/validation_baseline/baseline_rtl.npz")
    parser.add_argument("--producer-manifest", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    producer = producer_files(args.input, args.producer_manifest)
    reference, _, _, reference_provenance = load_reference()
    baseline, baseline_info = load_baseline(args.baseline)
    rows, inputs, pictures = [], [], {}
    for frame in range(417, 541):
        path = args.input / args.pattern.format(frame=frame)
        if not path.is_file():
            continue
        raw = path.read_bytes()
        rgb = (
            unpack(np.frombuffer(raw, np.uint8).reshape(240, 320))
            if path.suffix == ".rgb332"
            else np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
        )
        inputs.append(
            {
                "frame": frame,
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        pictures[frame] = rgb
        for label, roi in REGIONS.items():
            target, _ = component(reference[frame], roi)
            before, _ = component(unpack(baseline[frame]), roi)
            after, _ = component(rgb, roi)
            rows.append(
                {
                    "frame": frame,
                    "region": label,
                    "roi_xyxy": roi,
                    "reference": target,
                    "baseline": before,
                    "candidate": after,
                    "baseline_difference": difference(target, before),
                    "candidate_difference": difference(target, after),
                }
            )
    if args.expect_frames is not None and len(inputs) != args.expect_frames:
        raise RuntimeError(
            f"Expected {args.expect_frames} lying frames, found {len(inputs)}"
        )
    if not inputs:
        raise RuntimeError("No lying frames")
    for item in inputs + producer:
        if (
            hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
            != item["sha256"]
        ):
            raise RuntimeError("Input changed during review")
    summary = {}
    for label in REGIONS:
        selected = [r for r in rows if r["region"] == label]
        summary[label] = {}
        for side in ["baseline", "candidate"]:
            values = [
                r[side + "_difference"] for r in selected if r[side + "_difference"]
            ]
            summary[label][side] = {
                "detected_frames": len(values),
                "median_center_error_px": (
                    float(np.median([v["center_error_px"] for v in values]))
                    if values
                    else None
                ),
                "median_axis_difference_deg": (
                    float(
                        np.median(
                            [
                                v["axis_difference_deg"]
                                for v in values
                                if v["axis_reliable"]
                            ]
                        )
                    )
                    if any(v["axis_reliable"] for v in values)
                    else None
                ),
                "clipped_frames": sum(v["any_roi_clipping"] for v in values),
            }
    report = {
        "engine": args.engine,
        "frames": len(inputs),
        "summary": summary,
        "method": "Identical fixed native ROIs and dark-color threshold for reference, pinned previous actual RTL, and candidate. Largest connected dark region; 2D PCA major axis modulo180.",
        "limitations": "Color regions are not anatomical joints. Near-foot ROI intentionally measures a partial dark region to exclude attached belly shadow. Different materials and occlusion affect area and center. Axis has180-degree ambiguity and is unreliable for nearly round components. Inspect images before interpreting outliers.",
        "baseline_provenance": baseline_info,
        "reference_inputs": reference_provenance,
        "producer_files": producer,
        "input_files": inputs,
        "rows": rows,
    }
    (args.output / f"{args.name}.json").write_text(json.dumps(report, indent=2) + "\n")
    chosen = [f for f in [417, 425, 430, 450, 480, 510, 540] if f in pictures]
    sheet = Image.new("RGB", (960, max(1, len(chosen)) * 264), "#20252b")
    draw = ImageDraw.Draw(sheet)
    for i, frame in enumerate(chosen):
        for j, (rgb, label) in enumerate(
            [
                (reference[frame], "REFERENCE"),
                (unpack(baseline[frame]), "OLD ACTUAL RTL"),
                (pictures[frame], args.engine),
            ]
        ):
            image = Image.fromarray(rgb)
            mark = ImageDraw.Draw(image)
            for roi in REGIONS.values():
                mark.rectangle(roi, outline="white", width=1)
            sheet.paste(image, (j * 320, i * 264 + 24))
            draw.text((j * 320 + 3, i * 264 + 5), f"f{frame} {label}", fill="white")
    sheet.save(args.output / f"{args.name}.jpg", quality=95)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
