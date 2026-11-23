"""Top-level image injection, large scenes, export limits and cancellation."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from PIL import Image
from image_triangles import Placement,Triangle,triangulate
from export_image_top import export_top,MAX_BOARD_COMMANDS
from top_simulation import run_top,SimulationCancelled
from framebuffer_trace import TraceTail

PROJECT=Path(__file__).resolve().parents[1]


class TopStudioTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='top studio with spaces ')
        self.addCleanup(self.folder.cleanup)
        self.project=Path(self.folder.name)
        for directory in ['MGPU.srcs/sources_1/new','MGPU.srcs/constrs_1/new','MGPU.srcs/sources_1/rom']:
            shutil.copytree(PROJECT/directory,self.project/directory)
        tb=self.project/'MGPU.srcs/sim_1/new';tb.mkdir(parents=True)
        shutil.copy2(PROJECT/'MGPU.srcs/sim_1/new/top_tb.sv',tb/'top_tb.sv')
        self.mesh=triangulate(Image.new('RGB',(4,4),'cyan'),Placement(10,10,4,4),0,100)

    def test_export_is_standalone_and_does_not_overwrite_project(self):
        before=(self.project/'MGPU.srcs/sources_1/new/top.sv').read_bytes()
        path=export_top(self.mesh,self.project)
        text=path.read_text(encoding='utf-8')
        self.assertIn('module top #(',text)
        self.assertNotIn('studio_triangle_source',text)
        self.assertIn("image_commands[0] = 84'h",text)
        self.assertTrue((path.parent/'rtl/mgpu.sv').exists())
        self.assertTrue((path.parent/'build.tcl').exists())
        self.assertEqual(before,(self.project/'MGPU.srcs/sources_1/new/top.sv').read_bytes())
        metadata=json.loads((path.parent/'manifest.json').read_text())
        self.assertEqual(metadata['commands'],len(self.mesh.triangles)+2)
        if shutil.which('iverilog') and shutil.which('vvp'):
            binary = path.parent/'export_test.vvp'
            command = ['iverilog', '-g2012', '-s', 'top_tb', '-Ptop_tb.GPU_CLK_DIV_LOG2=1',
                       '-o', str(binary), str(path), *map(str, (path.parent/'rtl').glob('*.sv')),
                       str(self.project/'MGPU.srcs/sim_1/new/top_tb.sv')]
            compiled = subprocess.run(command, cwd=path.parent, capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            simulated = subprocess.run(['vvp', str(binary)], cwd=path.parent, capture_output=True, text=True, timeout=120)
            self.assertEqual(simulated.returncode, 0, simulated.stdout + simulated.stderr)
            self.assertNotIn('ERROR:', simulated.stdout)
            self.assertIn('PASS TOP STUDIO', simulated.stdout)

    def test_export_refuses_over_budget_before_writing(self):
        self.mesh.triangles=[Triangle((0,0,1,0,0,1,224,224,224))]*(MAX_BOARD_COMMANDS-1)
        with self.assertRaisesRegex(ValueError,'上板导出'):
            export_top(self.mesh,self.project)
        self.assertFalse((self.project/'out/image_export/top.sv').exists())

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus unavailable')
    def test_simulation_accepts_more_than_board_rom_capacity(self):
        scene=self.project/'large scene.tri'
        scene.write_text('8193\n'+('10 10 12 10 10 12 e0 e0 e0\n'*8193))
        paths=run_top(self.project,self.project/'output with spaces',threading.Event(),scene=scene)
        tail=TraceTail(paths['trace'])
        while tail.poll():pass
        self.assertIsNone(tail.error)
        self.assertTrue(tail.model.complete)
        self.assertEqual(len(tail.model.triangles),8193)
        self.assertEqual((tail.model.width,tail.model.height),(320,240))
        self.assertEqual(tail.model.frame_at(tail.model.latest_ns)[1605],224)
        self.assertEqual(tail.model.frame_at(tail.model.latest_ns)[0],0)

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus unavailable')
    def test_empty_scene_and_invalid_geometry(self):
        scene=self.project/'empty.tri';scene.write_text('0\n')
        paths=run_top(self.project,self.project/'output',threading.Event(),scene=scene)
        self.assertEqual(set(paths['framebuffer'].read_text().split()),{'00'})
        scene.write_text('1\n0 0 0 0 0 0 ff ff ff\n')
        with self.assertRaisesRegex(RuntimeError,'仿真失败'):
            run_top(self.project,self.project/'invalid',threading.Event(),scene=scene)

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus unavailable')
    def test_cancel_before_process_launch(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(SimulationCancelled):
            run_top(self.project,self.project/'output',cancel)


if __name__=='__main__':unittest.main()
