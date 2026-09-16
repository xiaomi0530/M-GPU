"""Geometry, alpha, quantization and real RTL image reconstruction tests."""
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from image_triangles import (Cancelled, Placement, RGB, compose, load_image,
                             quantize, render, save_bundle, triangulate)
from framebuffer_trace import TraceTail

PROJECT = Path(__file__).resolve().parents[1]


def specimen():
    # All 256 palette entries, gradients, partial alpha, holes and sharp edges.
    rgba = np.zeros((32, 48, 4), dtype=np.uint8)
    rgba[:16,:16,:3] = RGB[np.arange(256).reshape(16,16)]
    rgba[:16,:16,3] = 255
    rng = np.random.default_rng(31)
    rgba[16:,:,:] = rng.integers(0,256,(16,48,4),dtype=np.uint8)
    rgba[20:24,10:15,3] = 0
    yy,xx = np.indices((16,32))
    rgba[:16,16:,:3] = np.stack((xx*8,yy*16,255-xx*8),axis=-1)
    rgba[:16,16:,3] = 255
    return Image.fromarray(rgba)


class ImageMeshTests(unittest.TestCase):
    def test_all_rgb332_colors_roundtrip(self):
        np.testing.assert_array_equal(quantize(RGB),np.arange(256,dtype=np.uint8))

    def test_alpha_composition_clipping_and_odd_sizes(self):
        picture = Image.new("RGBA",(3,3),(255,0,0,128))
        target,alpha,_ = compose(picture,Placement(-1,479,3,3))
        self.assertEqual(target[479,0],128)
        self.assertEqual(target[479,1],128)
        self.assertEqual(np.count_nonzero(alpha),2)
        mesh = triangulate(picture,Placement(-1,479,3,3),0,160000)
        np.testing.assert_array_equal(mesh.prediction,mesh.target)
        np.testing.assert_array_equal(render(mesh.triangles),mesh.target)

    def test_precise_mode_reconstructs_rgba(self):
        mesh = triangulate(specimen(),Placement(17,23,48,32),0,160000)
        self.assertEqual(mesh.exact_percent,100.)
        np.testing.assert_array_equal(mesh.prediction,mesh.target)
        np.testing.assert_array_equal(render(mesh.triangles),mesh.target)
        for triangle in mesh.triangles:
            v = triangle.values
            self.assertNotEqual((v[2]-v[0])*(v[5]-v[1])-(v[3]-v[1])*(v[4]-v[0]),0)
            self.assertTrue(all(0 <= coordinate < (640 if i%2 == 0 else 480) for i,coordinate in enumerate(v[:6])))

    def test_flat_region_merges_and_transparent_region_skips(self):
        mesh = triangulate(Image.new("RGBA",(128,96),(182,109,85,255)),Placement(0,0,128,96),0,160000)
        self.assertEqual(len(mesh.triangles),2)
        self.assertEqual(mesh.rmse,0)
        blank = triangulate(Image.new("RGBA",(8,8)),Placement(0,0,8,8))
        self.assertEqual(len(blank.triangles),0)
        np.testing.assert_array_equal(blank.prediction,np.zeros((480,640),np.uint8))
        colored = triangulate(Image.new("RGBA",(8,8)),Placement(0,0,8,8,0x49))
        self.assertEqual(len(colored.triangles),2)
        np.testing.assert_array_equal(render(colored.triangles),colored.prediction)

    def test_budget_and_cancellation(self):
        picture = specimen().convert("RGB")
        mesh = triangulate(picture,Placement(0,0,48,32),0,20)
        self.assertLessEqual(len(mesh.triangles),20)
        self.assertTrue(mesh.budget_limited)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            triangulate(picture,Placement(0,0,48,32),0,160000,cancel)

    def test_palette_png_transparency(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"palette.png"
            image = Image.new("P",(2,2))
            image.putpalette([255,0,0,0,255,0]+[0]*762)
            image.putdata([0,1,0,1])
            image.save(path,transparency=0)
            rgba = np.asarray(load_image(path))
            self.assertEqual(rgba[0,0,3],0)
            self.assertEqual(rgba[0,1,3],255)

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"),"Icarus Verilog is unavailable")
    def test_generated_testbench_matches_real_gpu(self):
        with tempfile.TemporaryDirectory(prefix="mgpu image test ") as folder:
            project = Path(folder)
            sources = project/"MGPU.srcs/sources_1/new"
            testbench = project/"MGPU.srcs/sim_1/new"
            sources.mkdir(parents=True)
            testbench.mkdir(parents=True)
            for path in (PROJECT/"MGPU.srcs/sources_1/new").glob("*.v"):
                shutil.copy2(path,sources/path.name)
            shutil.copy2(PROJECT/"MGPU.srcs/sim_1/new/mgpu_tb.v",testbench/"mgpu_tb.v")
            mesh = triangulate(specimen(),Placement(16,20,48,32),0,160000)
            paths = save_bundle(mesh,project,"RGBA test fixture")
            self.assertTrue(paths["scene"].exists())
            binary = project/"out/check.vvp"
            compile_result = subprocess.run([shutil.which("iverilog"),"-g2012","-s","mgpu_image_tb","-o",str(binary),
                                             *map(str,sources.glob("*.v")),str(paths["testbench"])],
                                            cwd=project,capture_output=True,text=True,timeout=60)
            self.assertEqual(compile_result.returncode,0,compile_result.stderr)
            simulation = subprocess.run([shutil.which("vvp"),str(binary)],cwd=project,capture_output=True,text=True,timeout=120)
            self.assertEqual(simulation.returncode,0,simulation.stdout+simulation.stderr)
            actual = np.array([int(line,16) for line in (project/"out/framebuffer.hex").read_text().splitlines()],dtype=np.uint8).reshape((480,640))
            np.testing.assert_array_equal(actual,mesh.target)
            np.testing.assert_array_equal(actual,mesh.prediction)
            tail = TraceTail(project/"out/framebuffer.trace")
            while tail.poll():
                pass
            self.assertIsNone(tail.error)
            self.assertTrue(tail.model.complete)
            self.assertEqual(len(tail.model.triangles),len(mesh.triangles))
            self.assertEqual(bytes(tail.model.ingest),mesh.prediction.tobytes())


if __name__ == "__main__":
    unittest.main()
