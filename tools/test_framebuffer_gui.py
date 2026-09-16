"""GUI callback and export integration checks; windows stay withdrawn."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import tkinter as tk

from framebuffer_gui import FramebufferViewer
from view_framebuffer import rgb332_to_rgb888

RECORDING = ("MGPU_TRACE 1 4 3 00 ns\n"
             "B 100000 1 0 0 3 0 0 2\n"
             "P 200000 1 0 0 e0\nE 300000 1\n"
             "B 400000 2 0 0 3 0 0 2\n"
             "P 500000 2 0 0 03\nE 600000 2\nD 700000 2 2\n")


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "sample.trace"
        self.path.write_text(RECORDING, encoding="ascii")
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.app = FramebufferViewer(self.root, self.path)
        self.addCleanup(self.app.close)
        self.root.update()

    def test_timeline_triangle_navigation_and_precise_jump(self):
        app = self.app
        app.seek(0)
        app.step_triangle(1)
        self.root.update()
        self.assertEqual(app.time_ns, 300000)
        app.step_triangle(1)
        self.root.update()
        self.assertEqual(app.time_ns, 600000)
        app.step_triangle(-1)
        self.root.update()
        self.assertEqual(app.time_ns, 300000)
        app.jump_value.set("0.25")
        app.jump_to_time()
        self.assertEqual(app.time_ns, 250000)
        app.render()
        self.assertEqual(app.display_frame[0], 224)
        app.seek(550000)
        app.render()
        self.assertEqual(app.display_frame[0], 3)
        self.assertFalse(self.errors)

    def test_play_pause_speed_and_live_return(self):
        app = self.app
        app.seek(0)
        app.speed.set("0.05")
        app.toggle_play()
        self.assertTrue(app.playing)
        app.root.after_cancel(app._timer)
        app.last_tick = 100
        with patch("framebuffer_gui.time.perf_counter", return_value=100.1):
            app._tick()
        self.assertEqual(app.time_ns, 5000)
        app.toggle_play()
        self.assertFalse(app.playing)
        app.go_live()
        self.assertTrue(app.follow)
        self.assertEqual(app.time_ns, 700000)
        app.seek(100000)
        self.assertFalse(app.follow)

    def test_export_uses_current_time_and_original_resolution(self):
        app = self.app
        target = Path(self.folder.name) / "export.png"
        app.seek(250000)
        with patch("framebuffer_gui.filedialog.asksaveasfilename", return_value=str(target)):
            app.export()
        with Image.open(target) as picture:
            self.assertEqual(picture.size, (4, 3))
            self.assertEqual(picture.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(picture.getpixel((1, 0)), (0, 0, 0))
        self.assertFalse(self.errors)

    def test_legacy_hex_command(self):
        target = Path(self.folder.name) / "input.hex"
        target.write_text("e0\n" + "00\n" * (640 * 480 - 1), encoding="ascii")
        script = Path(__file__).with_name("view_framebuffer.py")
        process = subprocess.run([sys.executable, str(script), str(target)],
                                 cwd=self.folder.name, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        with Image.open(Path(self.folder.name) / "out/framebuffer.png") as picture:
            self.assertEqual(picture.size, (640, 480))
            self.assertEqual(picture.getpixel((0, 0)), rgb332_to_rgb888(0xE0))


if __name__ == "__main__":
    unittest.main()
