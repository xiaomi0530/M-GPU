"""Incremental MGPU trace reader and reversible framebuffer playback.

Protocol v1 (ASCII, newline terminated, timestamps in integer nanoseconds):
    MGPU_TRACE 1 width height clear_rgb332 ns
    B time triangle_id x0 y0 x1 y1 x2 y2
    P time triangle_id x y rgb332
    E time triangle_id
    D time triangle_count pixel_count

Only complete lines are consumed. Checkpoints bound random-seek work while a
separate ingestion buffer keeps following the producer during paused playback.
"""
from __future__ import annotations

from array import array
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Triangle:
    id: int
    start_ns: int
    vertices: tuple[int, ...]
    first_pixel: int
    end_ns: int | None = None
    last_pixel: int | None = None


class Trace:
    CHECKPOINT_STRIDE = 4096
    # At most ~32 MiB of full-frame checkpoints, even for long recordings.
    CHECKPOINT_BUDGET = 32 * 1024 * 1024

    def __init__(self) -> None:
        self.width = self.height = self.clear = 0
        self.ready = False
        self.complete = False
        self.latest_ns = 0
        self.times = array("Q")
        self.addresses = array("I")
        self.colors = bytearray()
        self.previous = bytearray()
        self.triangle_ids = array("I")
        self.triangles: list[Triangle] = []
        self.by_id: dict[int, Triangle] = {}
        self.starts: list[int] = []
        self.active: Triangle | None = None
        self.ingest = bytearray()
        self.frame = bytearray()
        self.cursor = 0
        self.checkpoint_stride = self.CHECKPOINT_STRIDE
        self.checkpoints: dict[int, bytes] = {}

    def parse_line(self, line: str) -> None:
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            return
        if not self.ready:
            if len(parts) != 6 or parts[:2] != ["MGPU_TRACE", "1"] or parts[5] != "ns":
                raise ValueError("Expected MGPU_TRACE 1 width height clear ns header")
            width, height, clear = int(parts[2]), int(parts[3]), int(parts[4], 16)
            if not (1 <= width <= 4096 and 1 <= height <= 4096 and 0 <= clear <= 255):
                raise ValueError("Invalid framebuffer dimensions or clear color")
            self.width, self.height, self.clear = width, height, clear
            self.ingest = bytearray([clear]) * (width * height)
            self.frame = self.ingest.copy()
            self.checkpoints = {0: bytes(self.ingest)}
            self.ready = True
            return
        if self.complete:
            raise ValueError("Unexpected event after D (end of recording)")
        kind = parts[0]
        lengths = {"B": 9, "P": 6, "E": 3, "D": 4}
        if kind not in lengths or len(parts) != lengths[kind]:
            raise ValueError("Malformed trace event")
        stamp = int(parts[1])
        if stamp < self.latest_ns or stamp > 2**64 - 1:
            raise ValueError("Timestamps must be nonnegative and monotonic")
        if kind == "B":
            ident = int(parts[2])
            vertices = tuple(map(int, parts[3:]))
            if self.active or ident in self.by_id or not 0 < ident <= 2**32 - 1:
                raise ValueError("Duplicate triangle ID or overlapping triangle submissions")
            if any(not 0 <= v < (self.width if n % 2 == 0 else self.height)
                   for n, v in enumerate(vertices)):
                raise ValueError("Triangle coordinates outside framebuffer")
            triangle = Triangle(ident, stamp, vertices, len(self.times))
            self.active = triangle
            self.triangles.append(triangle)
            self.by_id[ident] = triangle
            self.starts.append(stamp)
        elif kind == "P":
            ident, x, y = map(int, parts[2:5])
            color = int(parts[5], 16)
            if not self.active or ident != self.active.id:
                raise ValueError("Pixel does not belong to the active triangle")
            if not (0 <= x < self.width and 0 <= y < self.height and 0 <= color <= 255):
                raise ValueError("Pixel coordinates or RGB332 value out of range")
            address = y * self.width + x
            self.previous.append(self.ingest[address])
            self.ingest[address] = color
            self.times.append(stamp)
            self.addresses.append(address)
            self.colors.append(color)
            self.triangle_ids.append(ident)
            count = len(self.times)
            if count % self.checkpoint_stride == 0:
                self.checkpoints[count] = bytes(self.ingest)
                max_checkpoints = max(2, self.CHECKPOINT_BUDGET // len(self.ingest))
                if len(self.checkpoints) > max_checkpoints:
                    self.checkpoint_stride *= 2
                    self.checkpoints = {k: v for k, v in self.checkpoints.items()
                                        if k % self.checkpoint_stride == 0}
        elif kind == "E":
            if not self.active or int(parts[2]) != self.active.id:
                raise ValueError("Triangle end without matching begin")
            self.active.end_ns = stamp
            self.active.last_pixel = len(self.times)
            self.active = None
        else:
            if self.active or int(parts[2]) != len(self.triangles) or int(parts[3]) != len(self.times):
                raise ValueError("Recording totals do not match its events")
            self.complete = True
        self.latest_ns = stamp

    def count_at(self, time_ns: int) -> int:
        return bisect_right(self.times, time_ns)

    def triangle_at(self, time_ns: int) -> Triangle | None:
        index = bisect_right(self.starts, time_ns) - 1
        return self.triangles[index] if index >= 0 else None

    def seek_count(self, count: int) -> bytearray:
        count = max(0, min(count, len(self.times)))
        # Use the closest cached frame or the current frame, then replay or undo.
        checkpoint = min(self.checkpoints, key=lambda n: abs(n - count))
        if abs(checkpoint - count) < abs(self.cursor - count):
            self.frame[:] = self.checkpoints[checkpoint]
            self.cursor = checkpoint
        if count < self.cursor:
            for index in range(self.cursor - 1, count - 1, -1):
                self.frame[self.addresses[index]] = self.previous[index]
        else:
            for index in range(self.cursor, count):
                self.frame[self.addresses[index]] = self.colors[index]
        self.cursor = count
        return self.frame

    def isolated(self, triangle: Triangle, count: int) -> bytearray:
        frame = bytearray([self.clear]) * (self.width * self.height)
        stop = min(count, triangle.last_pixel if triangle.last_pixel is not None else len(self.times))
        for index in range(triangle.first_pixel, stop):
            frame[self.addresses[index]] = self.colors[index]
        return frame


class TraceTail:
    """Nonblocking bounded reads; tolerates partial writes and simulator restarts."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.model = Trace()
        self.offset = 0
        self.pending = b""
        self.line_number = 0
        self.anchor = b""
        self.signature: tuple[int, int, int] | None = None
        self.generation = 0
        self.error: str | None = None
        self.exists = False

    def reset(self) -> None:
        self.model = Trace()
        self.offset = 0
        self.pending = b""
        self.line_number = 0
        self.anchor = b""
        self.error = None
        self.generation += 1

    def poll(self, limit: int = 256 * 1024) -> bool:
        try:
            with self.path.open("rb") as stream:
                stat = self.path.stat()
                self.exists = True
                signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
                restart = stat.st_size < self.offset
                if self.signature and stat.st_ino != self.signature[0]:
                    restart = True
                # Completed/malformed recordings are reloaded when replaced in place.
                if (self.model.complete or self.error) and self.signature != signature:
                    restart = True
                if self.anchor and not restart:
                    stream.seek(self.offset - len(self.anchor))
                    restart = stream.read(len(self.anchor)) != self.anchor
                if restart:
                    self.reset()
                self.signature = signature
                if self.error:
                    return False
                stream.seek(self.offset)
                data = stream.read(limit)
                self.offset += len(data)
                self.anchor = (self.anchor + data)[-64:]
        except FileNotFoundError:
            self.exists = False
            return False
        except (OSError, PermissionError):
            # Windows may briefly deny access while the simulator reopens a file.
            return False
        if not data:
            return restart
        lines = (self.pending + data).split(b"\n")
        self.pending = lines.pop()
        if len(self.pending) > 4096:
            self.error = "Trace line exceeds 4096 bytes"
            return True
        for raw in lines:
            self.line_number += 1
            try:
                self.model.parse_line(raw.decode("ascii"))
            except (ValueError, OverflowError) as exc:
                self.error = f"Line {self.line_number}: {exc}"
                break
        return True
