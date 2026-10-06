#!/usr/bin/env python3
"""
Open MGPU Framebuffer Studio or export a native RGB332 framebuffer.

Expected input format:
    One hex byte per line, 320*240 or legacy 640*480 lines.

Example:
    python tools/view_framebuffer.py              # desktop replay GUI
    python tools/view_framebuffer.py --live       # follow the running simulator
    python tools/view_framebuffer.py recording.trace
    python tools/view_framebuffer.py out/framebuffer.hex

The legacy .hex command writes:
    out/framebuffer.png

If Pillow is installed, it uses Pillow. Otherwise it writes a plain PPM file,
which many image viewers can open.
"""

from __future__ import annotations

import argparse
from pathlib import Path


WIDTH = 640
HEIGHT = 480
PIXELS = WIDTH * HEIGHT


def rgb332_to_rgb888(value: int) -> tuple[int, int, int]:
    """Convert one RGB332 byte into a normal 24-bit RGB tuple."""
    red_3bit = (value >> 5) & 0x07
    green_3bit = (value >> 2) & 0x07
    blue_2bit = value & 0x03

    red = red_3bit * 255 // 7
    green = green_3bit * 255 // 7
    blue = blue_2bit * 255 // 3
    return red, green, blue


def framebuffer_size(count: int, width: int | None = None, height: int | None = None) -> tuple[int,int]:
    if width is None and height is None:
        for w,h in ((320,240),(640,480)):
            if count==w*h:
                return w,h
        raise ValueError(f"Expected 76800 or 307200 pixels, got {count}; specify width and height for other sizes")
    if width is None or height is None or not (1<=width<=4096 and 1<=height<=4096):
        raise ValueError("Specify both width and height in 1..4096")
    if count!=width*height:
        raise ValueError(f"Expected {width*height} pixels, got {count}")
    return width,height


def read_hex_framebuffer(path: Path, width: int | None = None, height: int | None = None) -> list[int]:
    pixels: list[int] = []

    with path.open("r", encoding="ascii") as file:
        for line_number, line in enumerate(file, start=1):
            text = line.strip()
            if not text:
                continue

            try:
                value = int(text, 16)
            except ValueError as exc:
                raise ValueError(f"Invalid hex byte at line {line_number}: {text!r}") from exc

            if value < 0 or value > 0xFF:
                raise ValueError(f"Value out of byte range at line {line_number}: {text!r}")

            pixels.append(value)

    framebuffer_size(len(pixels),width,height)
    return pixels


def output_size(count, width=None, height=None, scale=None):
    width,height=framebuffer_size(count,width,height)
    if scale is None:
        scale=2 if (width,height)==(320,240) else 1
    if not isinstance(scale,int) or not 1<=scale<=8:
        raise ValueError("Scale must be an integer in 1..8")
    return width,height,scale


def save_with_pillow(rgb_pixels: list[tuple[int, int, int]], output_png: Path, width=None, height=None, scale=None) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False

    width,height,scale=output_size(len(rgb_pixels),width,height,scale)
    image = Image.new("RGB", (width, height))
    image.putdata(rgb_pixels)
    if scale!=1:
        image=image.resize((width*scale,height*scale),Image.Resampling.NEAREST)
    image.save(output_png)
    return True


def save_as_ppm(rgb_pixels: list[tuple[int, int, int]], output_ppm: Path, width=None, height=None, scale=None) -> None:
    # PPM P6 is a tiny binary image format:
    #   header: P6 <width> <height> 255
    #   payload: raw RGB bytes
    width,height,scale=output_size(len(rgb_pixels),width,height,scale)
    with output_ppm.open("wb") as file:
        file.write(f"P6\n{width*scale} {height*scale}\n255\n".encode("ascii"))
        for y in range(height):
            row=b"".join(bytes(value)*scale for value in rgb_pixels[y*width:(y+1)*width])
            file.write(row*scale)


def main() -> None:
    parser = argparse.ArgumentParser(description="MGPU live framebuffer viewer and trace replay.")
    parser.add_argument(
        "framebuffer",
        nargs="?",
        default=None,
        help="Trace to view, or .hex framebuffer to export as a static image",
    )
    parser.add_argument("--live", action="store_true", help="Follow newest trace events")
    parser.add_argument("--gui", action="store_true", help="Open the trace GUI explicitly")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--scale", type=int, help="Integer image scale; 320x240 defaults to 2, use 1 for native pixels")
    args = parser.parse_args()

    if args.framebuffer is None or args.gui or args.live or Path(args.framebuffer).suffix.lower() != ".hex":
        path = Path(args.framebuffer) if args.framebuffer else Path(__file__).resolve().parents[1] / "out/studio_top/framebuffer.trace"
        if path.suffix.lower() == ".hex":
            parser.error("Live playback requires a .trace log; .hex only contains the final frame.")
        try:
            from framebuffer_gui import launch
        except ImportError as exc:
            parser.exit(1, f"GUI dependency missing: {exc}. Install Pillow: python -m pip install Pillow\n")
        launch(path.resolve(), args.live)
        return

    framebuffer_path = Path(args.framebuffer)
    output_dir = Path("out")
    output_dir.mkdir(exist_ok=True)

    raw_pixels = read_hex_framebuffer(framebuffer_path,args.width,args.height)
    rgb_pixels = [rgb332_to_rgb888(value) for value in raw_pixels]

    output_png = output_dir / "framebuffer.png"
    output_ppm = output_dir / "framebuffer.ppm"

    if save_with_pillow(rgb_pixels, output_png,args.width,args.height,args.scale):
        print(f"Wrote {output_png}")
    else:
        save_as_ppm(rgb_pixels, output_ppm,args.width,args.height,args.scale)
        print("Pillow is not installed, so PNG output was skipped.")
        print(f"Wrote {output_ppm}")
        print("Install Pillow with: python -m pip install pillow")


if __name__ == "__main__":
    main()
