"""Shared top.v compilation/execution for both Studios (no shell command strings)."""
from pathlib import Path
import shutil
import subprocess
import threading
import time
import re
import json


class SimulationCancelled(Exception):
    pass


def design_resolution(project: Path):
    source=(Path(project)/'MGPU.srcs/sources_1/new/top.v').read_text(encoding='utf-8')
    values=[]
    for name in ('H_RES','V_RES'):
        found=re.search(r'parameter\s+'+name+r'\s*=\s*(\d+)\b',source)
        if not found:
            raise ValueError(f'top.v 缺少可读取的 {name} 分辨率参数。')
        values.append(int(found.group(1)))
    width,height=values
    if not (width>0 and height>0 and 640%width==0 and 480%height==0):
        raise ValueError('VGA 仿真要求分辨率能够整倍数放大到 640×480。')
    return width,height


def run_top(project: Path, output: Path, cancel: threading.Event, *, testbench=None,
            module='top_tb', stage='logo', frames=1, fast=True, scene=None, progress=None, dump_frames=False,start_frame=0,logo_hold_ms=None,start_logo_frame=0):
    project=Path(project).resolve();output=Path(output).resolve()
    width,height=design_resolution(project)
    compiler,runtime=shutil.which('iverilog'),shutil.which('vvp')
    if not compiler or not runtime:
        raise RuntimeError('未找到 Icarus Verilog（iverilog / vvp）。')
    output.mkdir(parents=True,exist_ok=True)
    testbench=Path(testbench or project/'MGPU.srcs/sim_1/new/top_tb.v')
    sources=sorted((project/'MGPU.srcs/sources_1/new').glob('*.v'))
    if not testbench.is_file() or not (project/'MGPU.srcs/sources_1/new/top.v').is_file():
        raise RuntimeError('缺少 top.v 或 top_tb.v。')
    binary=output/'top_simulation.vvp';logfile=output/'simulation.log'
    trace=output/'framebuffer.trace';framebuffer=output/'framebuffer.hex'
    if logo_hold_ms is None:logo_hold_ms=7000 if stage=='logo' and scene is None else 0
    # Remove only stale outputs belonging to this run, before following its trace.
    for file in (trace,framebuffer,output/'framebuffer.png'):
        file.unlink(missing_ok=True)
    commands=[[compiler,'-g2012','-DSTUDIO_SIMULATION','-s',module,
               f'-P{module}.GPU_CLK_DIV_LOG2={1 if fast else 0}',
               f'-P{module}.STAGE_HOLD_MS={logo_hold_ms}',
               f'-P{module}.TARGET_FPS={0 if fast else 60}',
               f'-P{module}.START_FRAME={start_frame}',
               f'-P{module}.START_LOGO_FRAME={start_logo_frame}',
               f'-P{module}.H_RES={width}',f'-P{module}.V_RES={height}',
               '-o',str(binary),*map(str,sources),str(testbench)],
              [runtime,str(binary),f'+TRACE={trace.as_posix()}',
               f'+FRAMEBUFFER={framebuffer.as_posix()}',f'+STOP_STAGE={stage}',f'+FRAMES={frames}']]
    if scene is not None:
        commands[1].append(f'+STUDIO_SCENE={Path(scene).resolve().as_posix()}')
    if dump_frames:
        commands[1].append('+DUMP_FRAMES')
    with logfile.open('w',encoding='utf-8') as log:
        for number,command in enumerate(commands):
            if cancel.is_set():raise SimulationCancelled()
            if progress:progress('正在编译 top.v…' if number==0 else '正在运行 top.v，实时记录像素写回…')
            process=subprocess.Popen(command,cwd=project,stdout=log,stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            started=time.monotonic()
            try:
                while process.poll() is None:
                    if cancel.wait(.1):raise SimulationCancelled()
                    if time.monotonic()-started>1800:
                        raise RuntimeError('仿真超过 30 分钟；可选择加速仿真或降低三角形数量。')
                if process.returncode:
                    raise RuntimeError(f'top.v 仿真失败，查看 {logfile}')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
    metadata=dict(width=width,height=height,display_width=640,display_height=480,
                  format='RGB332',buffers=2,trace_version=2)
    (output/'framebuffer.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    return {'trace':trace,'framebuffer':framebuffer,'log':logfile,**metadata}
