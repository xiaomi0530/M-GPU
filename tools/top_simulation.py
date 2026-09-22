"""Shared top.v compilation/execution for both Studios (no shell command strings)."""
from pathlib import Path
import shutil
import subprocess
import threading
import time


class SimulationCancelled(Exception):
    pass


def run_top(project: Path, output: Path, cancel: threading.Event, *, testbench=None,
            module='top_tb', stage='logo', frames=1, fast=True, scene=None, progress=None):
    project=Path(project).resolve();output=Path(output).resolve()
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
    # Remove only stale outputs belonging to this run, before following its trace.
    for file in (trace,framebuffer,output/'framebuffer.png'):
        file.unlink(missing_ok=True)
    commands=[[compiler,'-g2012','-DSTUDIO_SIMULATION','-s',module,
               f'-P{module}.GPU_CLK_DIV_LOG2={1 if fast else 4}',
               f'-P{module}.STAGE_HOLD_MS={1 if fast else 4000}',
               f'-P{module}.CUBE_HOLD_MS={1 if fast else 40}',
               '-o',str(binary),*map(str,sources),str(testbench)],
              [runtime,str(binary),f'+TRACE={trace.as_posix()}',
               f'+FRAMEBUFFER={framebuffer.as_posix()}',f'+STOP_STAGE={stage}',f'+FRAMES={frames}']]
    if scene is not None:
        commands[1].append(f'+STUDIO_SCENE={Path(scene).resolve().as_posix()}')
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
    return {'trace':trace,'framebuffer':framebuffer,'log':logfile}
