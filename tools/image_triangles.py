"""RGBA placement, adaptive RGB332 meshes and MGPU testbench generation.

Integer sample positions and Q12 arithmetic deliberately match rasterizer.v.
Disjoint, even-sized pixel tiles avoid cracks and conflicting shared boundaries.
Each tile chooses the better diagonal; high-error tiles are split first down to
2x2 pixels, where two triangles reproduce all four RGB332 samples exactly.
"""
from __future__ import annotations

from dataclasses import dataclass
import heapq
import json
import os
from pathlib import Path
import threading
from typing import Callable

import numpy as np
from PIL import Image, ImageOps

WIDTH, HEIGHT = 640, 480
RGB = np.array([[(c >> 5) * 255 // 7, ((c >> 2) & 7) * 255 // 7,
                 (c & 3) * 255 // 3] for c in range(256)], dtype=np.uint8)
PRESETS = {"精确还原": (0.0, 160000), "均衡细节": (8.0, 12000), "较少三角形": (20.0, 3000)}


@dataclass(frozen=True)
class Placement:
    x: int = 0
    y: int = 0
    width: int = 640
    height: int = 480
    background: int = 0


@dataclass(frozen=True)
class Triangle:
    # x0, y0, x1, y1, x2, y2, color0, color1, color2
    values: tuple[int, ...]


@dataclass
class Mesh:
    triangles: list[Triangle]
    target: np.ndarray
    prediction: np.ndarray
    alpha: np.ndarray
    placement: Placement
    rmse: float
    exact_percent: float
    budget_limited: bool
    tolerance: float


class Cancelled(Exception):
    pass


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as picture:
        # EXIF rotation and palette PNG transparency are resolved before resize.
        return ImageOps.exif_transpose(picture).convert("RGBA")


def quantize(rgb: np.ndarray) -> np.ndarray:
    channels = np.asarray(rgb, dtype=np.uint16)
    red = (channels[..., 0] * 7 + 127) // 255
    green = (channels[..., 1] * 7 + 127) // 255
    blue = (channels[..., 2] * 3 + 127) // 255
    return ((red << 5) | (green << 2) | blue).astype(np.uint8)


def compose(image: Image.Image, placement: Placement) -> tuple[np.ndarray, np.ndarray, Image.Image]:
    p = placement
    if not (1 <= p.width <= 4096 and 1 <= p.height <= 4096 and 0 <= p.background <= 255):
        raise ValueError("图片尺寸应在 1～4096 像素之间，背景应为有效 RGB332 颜色。")
    # Pillow's RGBA resampler uses premultiplied alpha to avoid dark edge halos.
    resized = image.convert("RGBA").resize((p.width, p.height), Image.Resampling.LANCZOS)
    layer = Image.new("RGBA", (WIDTH, HEIGHT))
    layer.paste(resized, (p.x, p.y))
    background = Image.new("RGBA", (WIDTH, HEIGHT), tuple(map(int, RGB[p.background])) + (255,))
    composite = Image.alpha_composite(background, layer).convert("RGB")
    return quantize(np.asarray(composite)), np.asarray(layer)[:, :, 3].copy(), composite


def trunc_div(numerator: np.ndarray, denominator: int) -> np.ndarray:
    return np.sign(numerator) * (1 if denominator > 0 else -1) * (np.abs(numerator) // abs(denominator))


def raster_triangle(triangle: Triangle) -> tuple[int, int, np.ndarray, np.ndarray]:
    """Bit-exact color/coverage oracle for in-bounds axis-aligned tile triangles."""
    x0, y0, x1, y1, x2, y2, c0, c1, c2 = triangle.values
    area = (x1-x0)*(y2-y0) - (y1-y0)*(x2-x0)
    if area == 0:
        raise ValueError("Zero-area triangle")
    left, top = min(x0, x1, x2), min(y0, y1, y2)
    right, bottom = max(x0, x1, x2), max(y0, y1, y2)
    yy, xx = np.indices((bottom-top+1, right-left+1), dtype=np.int64)
    xx += left
    yy += top
    edge0 = (y1-y0)*xx + (x0-x1)*yy + x1*y0-y1*x0
    edge1 = (y2-y1)*xx + (x1-x2)*yy + x2*y1-y2*x1
    edge2 = (y0-y2)*xx + (x2-x0)*yy + x0*y2-y0*x2
    mask = ((edge0 >= 0) & (edge1 >= 0) & (edge2 >= 0)) | ((edge0 <= 0) & (edge1 <= 0) & (edge2 <= 0))
    channels = np.array([[c >> 5, (c >> 2) & 7, c & 3] for c in (c0, c1, c2)], dtype=np.int64)
    norm = channels * 4096 // np.array([7, 7, 3])
    dx10, dy10, dx20, dy20 = x1-x0, y1-y0, x2-x0, y2-y0
    gx = trunc_div(norm[0]*(dy10-dy20) + norm[1]*dy20 - norm[2]*dy10, area)
    gy = trunc_div(norm[0]*(dx20-dx10) - norm[1]*dx20 + norm[2]*dx10, area)
    color = np.clip(norm[0] + (xx-x0)[..., None]*gx + (yy-y0)[..., None]*gy, 0, 4096)
    packed = (color * np.array([7, 7, 3]) + 2048) >> 12
    packed = ((packed[:, :, 0] << 5) | (packed[:, :, 1] << 2) | packed[:, :, 2]).astype(np.uint8)
    return left, top, packed, mask


def render(triangles: list[Triangle], background: int = 0) -> np.ndarray:
    result = np.full((HEIGHT, WIDTH), background, dtype=np.uint8)
    for triangle in triangles:
        x, y, pixels, mask = raster_triangle(triangle)
        region = result[y:y+pixels.shape[0], x:x+pixels.shape[1]]
        region[mask] = pixels[mask]
    return result


def rectangle_triangles(left: int, top: int, right: int, bottom: int,
                        colors: tuple[int, int, int, int], diagonal: int) -> list[Triangle]:
    a, b, c, d = map(int, colors)  # top-left, top-right, bottom-right, bottom-left
    if diagonal == 0:
        return [Triangle((left,top,right,top,right,bottom,a,b,c)),
                Triangle((left,top,right,bottom,left,bottom,a,c,d))]
    return [Triangle((left,top,right,top,left,bottom,a,b,d)),
            Triangle((right,top,right,bottom,left,bottom,b,c,d))]


@dataclass
class Tile:
    rect: tuple[int, int, int, int]  # right/bottom are exclusive
    triangles: list[Triangle]
    pixels: np.ndarray
    squared_error: int
    alpha_error: bool
    rmse: float


def triangulate(image: Image.Image, placement: Placement, tolerance: float = 8,
                max_triangles: int = 12000, cancel: threading.Event | None = None,
                progress: Callable[[int], None] | None = None) -> Mesh:
    if not np.isfinite(tolerance) or tolerance < 0 or not 2 <= max_triangles <= 160000:
        raise ValueError("误差必须非负，三角形上限应在 2～160000 之间。")
    target, alpha, _ = compose(image, placement)
    background = placement.background
    prefix = rectangle_triangles(0, 0, WIDTH-1, HEIGHT-1, (background,)*4, 0) if background else []
    prediction = np.full_like(target, background)
    target_rgb = RGB[target].astype(np.int32)

    def fit(rect):
        left, top, right, bottom = rect
        if not np.any(alpha[top:bottom, left:right]):
            return None
        colors = (target[top,left], target[top,right-1], target[bottom-1,right-1], target[bottom-1,left])
        reference = target_rgb[top:bottom, left:right]
        best = None
        for diagonal in (0, 1):
            triangles = rectangle_triangles(left,top,right-1,bottom-1,colors,diagonal)
            pixels = np.empty((bottom-top,right-left), dtype=np.uint8)
            for triangle in triangles:
                _, _, values, coverage = raster_triangle(triangle)
                pixels[coverage] = values[coverage]
            diff = RGB[pixels].astype(np.int32) - reference
            squared = int(np.sum(diff*diff, dtype=np.int64))
            alpha_error = bool(np.any((alpha[top:bottom,left:right] == 0) & (pixels != background)))
            candidate = Tile(rect, triangles, pixels, squared, alpha_error, (squared / diff.size)**.5)
            if best is None or (alpha_error, squared) < (best.alpha_error, best.squared_error):
                best = candidate
        return best

    leaves: dict[int, Tile] = {}
    heap = []
    next_id = 0

    def add(tile):
        nonlocal next_id
        if tile is None:
            return
        ident = next_id
        next_id += 1
        leaves[ident] = tile
        l, t, r, b = tile.rect
        if (tile.alpha_error or tile.rmse > tolerance) and (r-l > 2 or b-t > 2):
            heapq.heappush(heap, (-(10**16 if tile.alpha_error else 0)-tile.squared_error, ident))

    yy, xx = np.nonzero(alpha)
    if len(xx):
        # Even aligned bounds permit exact 2x2 leaves, including single-pixel art.
        bounds = (int(xx.min())//2*2, int(yy.min())//2*2,
                  min(WIDTH, (int(xx.max())//2+1)*2), min(HEIGHT, (int(yy.max())//2+1)*2))
        add(fit(bounds))
    if len(prefix) + 2*len(leaves) > max_triangles:
        raise ValueError("三角形上限不足以同时绘制背景与图片，请提高上限。")
    limited = False
    while heap:
        if cancel and cancel.is_set():
            raise Cancelled()
        _, ident = heapq.heappop(heap)
        tile = leaves[ident]
        l, t, r, b = tile.rect
        if r-l >= b-t and r-l > 2:
            middle = l + ((r-l)//4)*2
            rectangles = ((l,t,middle,b), (middle,t,r,b))
        else:
            middle = t + ((b-t)//4)*2
            rectangles = ((l,t,r,middle), (l,middle,r,b))
        children = [fit(rect) for rect in rectangles]
        if len(prefix) + 2*(len(leaves)-1 + sum(child is not None for child in children)) > max_triangles:
            limited = True
            if tile.alpha_error:
                raise ValueError("三角形上限不足以保留透明边缘，请提高上限或缩小图片。")
            break
        del leaves[ident]
        for child in children:
            add(child)
        if progress and next_id % 32 < 2:
            progress(len(prefix) + 2*len(leaves))
    triangles = list(prefix)
    for tile in sorted(leaves.values(), key=lambda item: (item.rect[1], item.rect[0])):
        l, t, r, b = tile.rect
        prediction[t:b,l:r] = tile.pixels
        triangles.extend(tile.triangles)
    visible = alpha > 0
    if np.any(visible):
        diff = RGB[prediction[visible]].astype(np.float64) - RGB[target[visible]]
        rmse = float(np.sqrt(np.mean(diff*diff)))
        exact = float(np.mean(prediction[visible] == target[visible]) * 100)
    else:
        rmse, exact = 0., 100.
    return Mesh(triangles, target, prediction, alpha, placement, rmse, exact, limited, tolerance)


def save_bundle(mesh: Mesh, project: Path, source: str = "") -> dict[str, Path]:
    """Export stimulus and a standalone testbench; never write DUT framebuffer."""
    project = Path(project).resolve()
    output = project / "out"
    output.mkdir(parents=True, exist_ok=True)
    paths = {"scene": output / "image_scene.tri", "testbench": output / "top_image_tb.v",
             "expected": output / "image_expected.hex", "target": output / "image_target.png",
             "prediction": output / "image_prediction.png", "metadata": output / "image_scene.json"}
    template = (project / "MGPU.srcs/sim_1/new/top_tb.v").read_text(encoding="utf-8")
    marker = 'localparam DEFAULT_IMAGE_SCENE = "";'
    if marker not in template or "module top_tb;" not in template:
        raise ValueError("top_tb.v 缺少图片场景入口，请使用项目中的新版 testbench。")
    scene_literal = str(paths["scene"]).replace("\\", "/").replace('"', '\\"')
    testbench = template.replace("module top_tb;", "module top_image_tb;\n`ifndef STUDIO_SIMULATION\n    initial $fatal(1, \"Enable STUDIO_SIMULATION for Image Studio\");\n`endif", 1).replace(
        marker, f'localparam DEFAULT_IMAGE_SCENE = "{scene_literal}";', 1)
    testbench = "// Generated by Image Studio. Compile all RTL with -DSTUDIO_SIMULATION -s top_image_tb. DUT is top.v.\n" + testbench
    scene = str(len(mesh.triangles)) + "\n"
    scene += "".join(" ".join(map(str, tri.values[:6])) + " " +
                     " ".join(f"{v:02x}" for v in tri.values[6:]) + "\n" for tri in mesh.triangles)
    metadata = {"design_top": "top", "simulation_top": "top_image_tb", "source": source, "placement": vars(mesh.placement), "triangles": len(mesh.triangles),
                "rmse_rgb888": mesh.rmse, "exact_visible_percent": mesh.exact_percent,
                "tolerance": mesh.tolerance, "budget_limited": mesh.budget_limited,
                "alpha": "composited over the selected RGB332 background"}
    for key, text in (("scene", scene), ("testbench", testbench),
                      ("expected", "".join(f"{value:02x}\n" for value in mesh.prediction.flat)),
                      ("metadata", json.dumps(metadata, ensure_ascii=False, indent=2))):
        temporary = paths[key].with_suffix(paths[key].suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, paths[key])
    Image.fromarray(RGB[mesh.target]).save(paths["target"])
    Image.fromarray(RGB[mesh.prediction]).save(paths["prediction"])
    return paths
