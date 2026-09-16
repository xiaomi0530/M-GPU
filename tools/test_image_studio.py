"""Image Studio controls and background generation (no visible windows)."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk

from PIL import Image

from framebuffer_gui import FramebufferViewer
from image_studio import ImageStudio


class ImageStudioTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.project = Path(self.folder.name)
        path = self.project/"MGPU.srcs/sim_1/new/mgpu_tb.v"
        path.parent.mkdir(parents=True)
        path.write_text((Path(__file__).resolve().parents[1]/"MGPU.srcs/sim_1/new/mgpu_tb.v").read_text(),encoding="utf-8")
        self.input_path = self.project/"alpha.png"
        Image.new("RGBA",(16,8),(255,0,255,128)).save(self.input_path)
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.viewer = FramebufferViewer(self.root,self.project/"pending.trace")
        self.addCleanup(self.viewer.close)
        self.studio = ImageStudio(self.viewer,self.project)
        self.studio.window.withdraw()
        self.addCleanup(self.studio.close)
        self.studio.load_path(self.input_path)

    def test_import_position_scale_and_drag(self):
        studio = self.studio
        self.assertEqual(studio.placement().x,312)
        self.assertEqual(studio.placement().y,236)
        studio.variables["width"].set("32")
        studio.apply_fields("width")
        self.assertEqual(studio.placement().height,16)
        studio.box = (0,0,640,480)
        studio.drag_start(SimpleNamespace(x=320,y=240))
        studio.drag_move(SimpleNamespace(x=300,y=250))
        self.assertEqual(studio.placement().x,292)
        self.assertEqual(studio.placement().y,246)
        self.assertFalse(self.errors)

    def test_generate_writes_testbench_and_invalidates_after_moving(self):
        studio = self.studio
        studio.preset.set("精确还原")
        studio.apply_preset()
        studio.generate()
        deadline = time.monotonic()+15
        while studio.busy and time.monotonic()<deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(studio.busy)
        self.assertIsNotNone(studio.mesh)
        self.assertEqual(studio.mesh.exact_percent,100)
        self.assertTrue((self.project/"out/mgpu_image_tb.v").exists())
        self.assertTrue((self.project/"out/image_scene.tri").exists())
        studio.apply_fields("x",quiet=True)  # no-op focus-out must preserve result
        self.assertIsNotNone(studio.mesh)
        studio.variables["x"].set("0")
        studio.apply_fields("x")
        self.assertIsNone(studio.mesh)
        self.assertIsNone(studio.paths)
        self.assertFalse(self.errors)


if __name__ == "__main__":
    unittest.main()
