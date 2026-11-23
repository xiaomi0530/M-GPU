"""Version-bound comparison of native no-Z candidate pixels against reference and old RTL."""

from pathlib import Path
import argparse, hashlib, io, json
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out/milkfrog_iteration2/review"


def load_reference():
    """Recreate native reference frames from permanent video and measurement assets."""
    paths = {
        "motion_measurement": ROOT / "assets/naiwa/reference_motion.json",
        "mouth_measurement": ROOT
        / "assets/milkfrog/v1_fixed/animation/mouth_reference_measurements.json",
        "mouth_masks": ROOT / "assets/milkfrog/v1_fixed/animation/mouth_reference_masks.npz",
    }
    raw = {key: path.read_bytes() for key, path in paths.items()}
    motion = json.loads(raw["motion_measurement"])
    mouth = json.loads(raw["mouth_measurement"])
    video = ROOT / motion["source_video"]
    video_hash = hashlib.sha256(video.read_bytes()).hexdigest()
    if video_hash != motion["source_sha256"] or video_hash != mouth["source_sha256"]:
        raise RuntimeError("Reference video no longer matches permanent measurements")
    mapping = motion["display_mapping"]
    scale = mapping["uniform_scale"]
    tx, ty = mapping["translation_xy"]
    warp = np.array([[scale, 0, tx], [0, scale, ty]], np.float64)
    cap = cv2.VideoCapture(str(video))
    frames = []
    try:
        for frame in range(motion["frames"]):
            ok, bgr = cap.read()
            if not ok:
                raise RuntimeError(f"Missing source frame {frame}")
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            frames.append(
                cv2.warpAffine(
                    rgb,
                    warp,
                    (320, 240),
                    flags=cv2.INTER_AREA,
                    borderValue=(130, 255, 157),
                )
            )
    finally:
        cap.release()
    masks = np.load(io.BytesIO(raw["mouth_masks"]))["masks"]
    if masks.shape != (len(frames), 240, 320):
        raise RuntimeError("Reference mask dimensions do not match source frames")
    provenance = {
        key: {"path": str(paths[key]), "sha256": hashlib.sha256(value).hexdigest()}
        for key, value in raw.items()
    }
    provenance["video"] = {"path": str(video), "sha256": video_hash}
    provenance["fixed_mapping"] = mapping
    return np.stack(frames), masks, mouth["frames"], provenance


def load_baseline(path):
    """Read the pinned old actual-RTL archive and verify its recorded hash."""
    raw = Path(path).read_bytes()
    provenance = json.loads(
        Path(path).with_name("baseline_provenance.json").read_text()
    )
    if hashlib.sha256(raw).hexdigest() != provenance["packed_archive_sha256"]:
        raise RuntimeError("Pinned previous RTL archive changed")
    frames = np.load(io.BytesIO(raw))["rgb332"]
    if frames.shape != (541, 240, 320):
        raise RuntimeError("Baseline must contain 541 complete native frames")
    return frames, provenance


def producer_files(directory, manifest=None):
    """Bind a report to its producer's metadata without borrowing an unrelated run."""
    paths = [Path(directory) / name for name in ["provenance.json", "manifest.json"]]
    if manifest is not None:
        paths.append(Path(manifest))
    result = []
    for path in dict.fromkeys(path.resolve() for path in paths):
        if path.is_file():
            result.append(
                {
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        elif manifest is not None and path == Path(manifest).resolve():
            raise FileNotFoundError(path)
    return result


def dark_region_component(rgb, roi):
    """Visible dark color region in an explicit ROI; not an anatomical joint."""
    x0, y0, x1, y1 = roi
    image = rgb[y0:y1, x0:x1]
    dark = (
        (image[:, :, 0] < 145) & (image[:, :, 1] < 135) & (image[:, :, 2] < 130)
    ).astype(np.uint8)
    count, labels, stats, centers = cv2.connectedComponentsWithStats(dark, 8)
    if count <= 1:
        return None, dark.astype(bool)
    index = 1 + np.argmax(stats[1:, 4])
    x, y, width, height, area = stats[index]
    yy, xx = np.where(labels == index)
    points = np.column_stack((xx, yy))
    values, vectors = (
        np.linalg.eigh(np.cov(points.T)) if len(points) > 2 else (np.ones(2), np.eye(2))
    )
    axis = vectors[:, -1]
    measurement = {
        "center_xy": (centers[index] + [x0, y0]).tolist(),
        "bbox_xyxy": [
            int(x0 + x),
            int(y0 + y),
            int(x0 + x + width),
            int(y0 + y + height),
        ],
        "area_px": int(area),
        "major_axis_screen_deg": float(np.degrees(np.arctan2(axis[1], axis[0])) % 180),
        "axis_ratio": float(np.sqrt(values[-1] / max(1e-9, values[0]))),
        "roi_clipped": bool(
            x == 0 or y == 0 or x + width == x1 - x0 or y + height == y1 - y0
        ),
    }
    return measurement, labels == index


def unpack(p):
    p = p.astype(np.uint16)
    return np.stack(
        ((p >> 5) * 255 // 7, ((p >> 2) & 7) * 255 // 7, (p & 3) * 255 // 3), -1
    ).astype(np.uint8)


def box(mask):
    y, x = np.where(mask)
    return (
        [int(x.min()), int(y.min()), int(x.max() + 1), int(y.max() + 1)]
        if len(x)
        else None
    )


def mouth_component(rgb, target):
    mask = np.zeros((240, 320), bool)
    if target is None:
        return mask, None
    roi = np.array(target["bbox_xyxy"]) + [-13, -10, 13, 10]
    x0, y0, x1, y1 = np.clip(roi, [0, 0, 0, 0], [319, 239, 320, 240])
    a = rgb[y0:y1, x0:x1]
    binary = ((a[:, :, 0] < 145) & (a[:, :, 1] < 135) & (a[:, :, 2] < 130)).astype(
        np.uint8
    )
    n, labels, stats, centers = cv2.connectedComponentsWithStats(binary, 8)
    if n <= 1:
        return mask, None
    distances = np.sum((centers[1:] + [x0, y0] - target["center_xy"]) ** 2, axis=1)
    score = stats[1:, 4] * np.exp(-distances / 200.0)
    k = 1 + int(np.argmax(score))
    x, y, w, h, area = stats[k]
    if w < target["width_px"] * 0.4 or (
        target["height_px"] < 8 and h > target["height_px"] * 2.1
    ):
        return mask, None
    mask[y0:y1, x0:x1] = labels == k
    center = centers[k] + [x0, y0]
    return mask, dict(
        bbox_xyxy=[int(x0 + x), int(y0 + y), int(x0 + x + w), int(y0 + y + h)],
        width_px=int(w),
        height_px=int(h),
        area_px=int(area),
        center_xy=center.tolist(),
        roi_clipped=bool(x == 0 or y == 0 or x + w == x1 - x0 or y + h == y1 - y0),
        center_error_px=float(np.linalg.norm(center - target["center_xy"])),
    )


def enclosed_skin_pixels(rgb, mouth_mask):
    """Flag isolated yellow/orange pixels inside a dark mouth for manual inspection."""
    if not mouth_mask.any():
        return dict(area_px=0, bbox_xyxy=None)
    _, labels, _, _ = cv2.connectedComponentsWithStats(
        (~mouth_mask).astype(np.uint8), 8
    )
    holes = (labels != labels[0, 0]) & (~mouth_mask)
    skin = (
        (rgb[:, :, 0] > 160)
        & (rgb[:, :, 1] > 110)
        & (rgb[:, :, 2] < 120)
        & (rgb[:, :, 0] > rgb[:, :, 1])
    )
    mask = holes & skin
    return dict(area_px=int(mask.sum()), bbox_xyxy=box(mask))


def iris_in_closed_eye_roi(rgb, target):
    """Flag even one green iris pixel during fully closed control frames."""
    if target is None:
        return None
    x0, y0, x1, _ = target["bbox_xyxy"]
    roi = [max(0, x0 - 18), max(0, y0 - 29), min(320, x1 + 24), min(240, y0 + 2)]
    x0, y0, x1, y1 = roi
    a = rgb.astype(np.int16)
    green = (
        (a[:, :, 1] > a[:, :, 0] + 6)
        & (a[:, :, 1] > a[:, :, 2] + 4)
        & (a[:, :, 1] < 230)
    )
    mask = np.zeros((240, 320), bool)
    mask[y0:y1, x0:x1] = green[y0:y1, x0:x1]
    foreground = np.any(rgb != rgb[0, 0], axis=-1)
    interior = cv2.erode(foreground.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    return {
        "search_roi_xyxy": roi,
        "green_pixel_count": int(mask.sum()),
        "interior_green_pixel_count": int((mask & interior).sum()),
        "green_bbox_xyxy": box(mask),
    }


def compact_comparison(images, reference, baseline, destination, engine):
    selected = [
        (84, "后仰大笑"),
        (225, "双手抱头"),
        (408, "起跳转身"),
        (430, "倒地捧腹"),
    ]
    if any(frame not in images for frame, _ in selected):
        raise RuntimeError("Compact comparison requires frames 84,225,408,430")
    sheet = Image.new("RGB", (960, 1130), "#20252b")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
    actual = engine == "Actual MGPU RTL framebuffer"
    for col, label in enumerate(
        [
            "参考原片 · 固定画面映射",
            "上一版 · 实际 RTL",
            "本版 · 实际 RTL" if actual else "本版 · 软件预览，非 RTL",
        ]
    ):
        draw.text((col * 320 + 8, 7), label, font=font, fill="white")
    for row, (frame, label) in enumerate(selected):
        top = 34 + row * 266
        draw.text(
            (8, top),
            f"第 {frame} 帧 / {frame/30:.2f} 秒 · {label}",
            font=font,
            fill="#cbd3df",
        )
        for col, rgb in enumerate(
            [reference[frame], unpack(baseline[frame]), images[frame]]
        ):
            sheet.paste(Image.fromarray(rgb), (col * 320, top + 21))
    draw.text(
        (8, 1103),
        "相同固定画面映射；本版与上一版均为 320×240 原生像素。",
        font=font,
        fill="#cbd3df",
    )
    sheet.save(destination)


def face_contact_sheet(images, reference, mouth, eye_control, destination, engine):
    selected = [
        19,
        21,
        30,
        33,
        63,
        64,
        65,
        66,
        67,
        68,
        69,
        70,
        147,
        150,
        153,
        156,
        162,
        165,
        168,
        178,
        186,
        207,
        219,
        225,
        258,
        267,
        280,
        282,
        284,
        294,
        296,
        370,
        372,
        374,
        379,
        388,
        390,
        392,
        398,
        399,
        400,
        402,
    ]
    selected = [
        frame
        for frame in selected
        if frame in images and mouth[frame]["native_measurement"]
    ]
    sheet = Image.new(
        "RGB", (8 * 220, 35 + ((len(selected) + 7) // 8) * 160), "#20252b"
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 13)
    draw.text(
        (5, 7), "Each pair: REFERENCE / CANDIDATE. " + engine, font=font, fill="white"
    )
    for index, frame in enumerate(selected):
        target = mouth[frame]["native_measurement"]
        x0, y0, x1, y1 = target["bbox_xyxy"]
        roi = [max(0, x0 - 18), max(0, y0 - 30), min(320, x1 + 24), min(240, y1 + 12)]
        x0, y0, x1, y1 = roi
        left, top = index % 8 * 220, 35 + index // 8 * 160
        iris = iris_in_closed_eye_roi(images[frame], target)
        draw.text(
            (left + 4, top + 2),
            f'f{frame} closed={eye_control[frame]:.2f} green={iris["green_pixel_count"]}',
            font=font,
            fill="white",
        )
        for column, rgb in enumerate([reference[frame], images[frame]]):
            crop = Image.fromarray(rgb[y0:y1, x0:x1])
            scale = min(106 / crop.width, 132 / crop.height)
            crop = crop.resize(
                (round(crop.width * scale), round(crop.height * scale)),
                Image.Resampling.NEAREST,
            )
            sheet.paste(crop, (left + column * 110, top + 24))
    sheet.save(destination)


def phase_summaries(rows):
    phases = [
        ("standing", 0, 62),
        ("laughing_1", 63, 206),
        ("hands_on_head", 207, 267),
        ("laughing_2", 268, 389),
        ("jump_and_turn", 390, 416),
        ("lying", 417, 540),
    ]
    result = {}
    for name, first, last in phases:
        selected = [row for row in rows if first <= row["frame"] <= last]
        if not selected:
            continue
        mouth = [row for row in selected if "candidate_mouth_iou" in row]
        detected = [row for row in mouth if row["candidate_mouth"] is not None]
        result[name] = {
            "frame_range": [first, last],
            "available_frames": len(selected),
            "candidate_silhouette_mean": float(
                np.mean([r["reference_iou"] for r in selected])
            ),
            "baseline_silhouette_mean": float(
                np.mean([r["old_reference_iou"] for r in selected])
            ),
            "measured_mouth_frames": len(mouth),
            "candidate_mouth_detected_frames": len(detected),
            "candidate_mouth_iou_mean": (
                float(np.mean([r["candidate_mouth_iou"] for r in mouth]))
                if mouth
                else None
            ),
            "baseline_mouth_iou_mean": (
                float(np.mean([r["old_mouth_iou"] for r in mouth])) if mouth else None
            ),
            "candidate_mouth_center_error_median": (
                float(
                    np.median(
                        [r["candidate_mouth"]["center_error_px"] for r in detected]
                    )
                )
                if detected
                else None
            ),
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--pattern", default="frame_{frame:04d}.png")
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--engine", default="Software no-depth-buffer painter preview, NOT RTL"
    )
    parser.add_argument("--expect-frames", type=int)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--baseline", type=Path, default=ROOT / "assets/naiwa/validation_baseline/baseline_rtl.npz")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--face-sheet", action="store_true")
    parser.add_argument("--producer-manifest", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.input.resolve()
    producer = producer_files(source, args.producer_manifest)
    reference, refmasks, mouth, reference_provenance = load_reference()
    old, baseline_provenance = load_baseline(args.baseline)
    eye_path = ROOT / "assets/milkfrog/v1_fixed/animation/eye_closure_curve.json"
    eye_raw = eye_path.read_bytes()
    eye_control = json.loads(eye_raw)["eye_closed"]
    reference_provenance["eye_closure_curve"] = {
        "path": str(eye_path),
        "sha256": hashlib.sha256(eye_raw).hexdigest(),
    }
    rows = []
    images = {}
    inputs = []
    previous = None
    previous_frame = None
    for f in range(541):
        path = source / args.pattern.format(frame=f)
        if not path.is_file():
            continue
        raw = path.read_bytes()
        inputs.append(
            dict(frame=f, path=str(path), sha256=hashlib.sha256(raw).hexdigest())
        )
        current = (
            unpack(np.frombuffer(raw, np.uint8).reshape(240, 320))
            if path.suffix == ".rgb332"
            else np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
        )
        if current.shape != (240, 320, 3):
            raise RuntimeError(f"Not native320x240:{path}")
        clear = current[0, 0]
        fg = np.any(current != clear, axis=-1)
        a = reference[f].astype(np.int16)
        rf = ~(
            (a[:, :, 1] > a[:, :, 0] + 24)
            & (a[:, :, 1] > a[:, :, 2] + 24)
            & (a[:, :, 1] > 170)
        )
        oldfg = old[f] != old[f, 0, 0]
        n, labels, stats, centers = cv2.connectedComponentsWithStats(
            fg.astype(np.uint8), 8
        )
        areas = sorted(stats[1:, 4].tolist(), reverse=True)
        _, _, background_stats, _ = cv2.connectedComponentsWithStats(
            (~fg).astype(np.uint8), 8
        )
        holes = [
            int(area)
            for x, y, w, h, area in background_stats[1:]
            if x > 0 and y > 0 and x + w < 320 and y + h < 240 and area >= 4
        ]
        row = dict(
            frame=f,
            reference_iou=float((fg & rf).sum() / max(1, (fg | rf).sum())),
            old_reference_iou=float((oldfg & rf).sum() / max(1, (oldfg | rf).sum())),
            bbox_xyxy=box(fg),
            reference_bbox_xyxy=box(rf),
            secondary_component_area=int(sum(areas[1:])),
            hole_areas_at_least4px=holes,
            changed_from_frame=previous_frame,
            changed_pixels=(
                0
                if previous is None
                else int(np.any(current != previous, axis=-1).sum())
            ),
        )
        if mouth[f]["visibility"] == "visible" and mouth[f]["confidence"] >= 0.6:
            target = mouth[f]["native_measurement"]
            new_mask, new_measure = mouth_component(current, target)
            old_mask, old_measure = mouth_component(unpack(old[f]), target)
            row.update(
                reference_mouth=target,
                candidate_mouth=new_measure,
                old_mouth=old_measure,
                candidate_mouth_iou=float(
                    (new_mask & refmasks[f]).sum()
                    / max(1, (new_mask | refmasks[f]).sum())
                ),
                old_mouth_iou=float(
                    (old_mask & refmasks[f]).sum()
                    / max(1, (old_mask | refmasks[f]).sum())
                ),
                candidate_mouth_enclosed_skin=enclosed_skin_pixels(current, new_mask),
                old_mouth_enclosed_skin=enclosed_skin_pixels(unpack(old[f]), old_mask),
            )
        if eye_control[f] >= 0.999 and f <= 405:
            row["closed_eye_control"] = eye_control[f]
            row["candidate_closed_eye_iris"] = iris_in_closed_eye_roi(
                current, mouth[f]["native_measurement"]
            )
            row["baseline_closed_eye_iris"] = iris_in_closed_eye_roi(
                unpack(old[f]), mouth[f]["native_measurement"]
            )
        rows.append(row)
        images[f] = current
        previous = current
        previous_frame = f
    if not rows:
        raise RuntimeError("No candidate frames")
    if args.expect_frames is not None and len(rows) != args.expect_frames:
        raise RuntimeError(
            f"Incomplete candidate:{len(rows)}frames, expected{args.expect_frames}"
        )
    for item in inputs + producer:
        if (
            hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
            != item["sha256"]
        ):
            raise RuntimeError("Candidate changed during review")
    eligible = [r for r in rows if "candidate_mouth_iou" in r]
    summary = {
        "frames": len(rows),
        "silhouette_mean": float(np.mean([r["reference_iou"] for r in rows])),
        "old_silhouette_mean": float(np.mean([r["old_reference_iou"] for r in rows])),
        "mouth_measured_frames": len(eligible),
        "mouth_iou_mean": (
            float(np.mean([r["candidate_mouth_iou"] for r in eligible]))
            if eligible
            else None
        ),
        "old_mouth_iou_mean": (
            float(np.mean([r["old_mouth_iou"] for r in eligible])) if eligible else None
        ),
        "mouth_center_error_median": (
            float(
                np.median(
                    [
                        r["candidate_mouth"]["center_error_px"]
                        for r in eligible
                        if r["candidate_mouth"]
                    ]
                )
            )
            if eligible
            else None
        ),
        "max_secondary_component_area": max(
            r["secondary_component_area"] for r in rows
        ),
        "max_enclosed_background_area": max(
            sum(r["hole_areas_at_least4px"]) for r in rows
        ),
    }
    closed = [r for r in rows if r.get("candidate_closed_eye_iris") is not None]
    summary["fully_closed_control_frames"] = len(closed)
    summary["fully_closed_candidate_iris_frames"] = sum(
        r["candidate_closed_eye_iris"]["green_pixel_count"] > 0 for r in closed
    )
    summary["fully_closed_baseline_iris_frames"] = sum(
        r["baseline_closed_eye_iris"]["green_pixel_count"] > 0 for r in closed
    )
    summary["maximum_closed_candidate_iris_pixels"] = max(
        (r["candidate_closed_eye_iris"]["green_pixel_count"] for r in closed), default=0
    )
    report = {
        "engine": args.engine,
        "input_directory": str(source),
        "summary": summary,
        "phases": phase_summaries(rows),
        "limitations": "Detected mouth component can be absent when target ROI excludes an incorrectly positioned mouth; absence is reported rather than selecting an eye. Mouth masks include thresholded dark regions, not anatomical apertures. Enclosed green areas can be natural arm gaps. Green-iris flags use the reference-constrained closed-eye control, not a recovered anatomical eyelid angle, and need visual review at object boundaries. Per-pixel color correctness and true painter ordering must be separately verified against actual RTL.",
        "reference_inputs": reference_provenance,
        "baseline_provenance": baseline_provenance,
        "producer_files": producer,
        "input_files": inputs,
        "frames": rows,
    }
    (args.output / f"{args.name}.json").write_text(json.dumps(report, indent=2) + "\n")
    chosen = [
        f
        for f in [
            0,
            66,
            72,
            84,
            120,
            135,
            150,
            165,
            186,
            225,
            285,
            315,
            360,
            379,
            390,
            399,
            405,
            408,
            411,
            414,
            417,
            450,
            540,
        ]
        if f in images
    ]
    sheet = Image.new("RGB", (960, len(chosen) * 264), "#20252b")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 15)
    for i, f in enumerate(chosen):
        for j, (im, label) in enumerate(
            [
                (reference[f], "REFERENCE"),
                (unpack(old[f]), "OLD ACTUAL RTL"),
                (images[f], "CANDIDATE: " + args.engine),
            ]
        ):
            sheet.paste(Image.fromarray(im), (j * 320, i * 264 + 24))
            draw.text(
                (j * 320 + 3, i * 264 + 3), f"f{f} {label}", font=font, fill="white"
            )
    sheet.save(args.output / f"{args.name}.jpg", quality=95)
    if args.compact:
        compact_comparison(
            images,
            reference,
            old,
            args.output / f"{args.name}_compact.png",
            args.engine,
        )
    if args.face_sheet:
        face_contact_sheet(
            images,
            reference,
            mouth,
            eye_control,
            args.output / f"{args.name}_faces.png",
            args.engine,
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
