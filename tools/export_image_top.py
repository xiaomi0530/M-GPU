"""Export a standalone, synthesizable top.sv using the same triangle mesh as Studio."""
import json
import math
from pathlib import Path
import shutil

MAX_BOARD_COMMANDS=8192


def export_top(mesh,project,output=None):
    project=Path(project).resolve()
    output=Path(output or project/'out/image_export').resolve()
    commands=[(0,0,639,0,639,479,0,0,0),(0,0,639,479,0,479,0,0,0)]
    commands += [tuple(t.values) for t in mesh.triangles]
    if len(commands)>MAX_BOARD_COMMANDS:
        raise ValueError(f'上板导出最多支持 {MAX_BOARD_COMMANDS-2:,} 个图片三角形；当前 {len(mesh.triangles):,} 个。请降低三角形上限后重新生成。仿真仍支持更大场景。')
    source=(project/'MGPU.srcs/sources_1/new/top.sv').read_text(encoding='utf-8')
    import re
    payload = []
    for command in commands:
        word = 0
        for index, value in enumerate(command):
            word = (word << (10 if index < 6 else 8)) | value
        payload.append(word)
    source_block = """    logic studio_mode;
    assign studio_mode = 1'b1;
    logic [17:0] studio_count;
    assign studio_count = 18'dCOUNT;
    logic [83:0] studio_data;
    (* rom_style = "block" *) logic [83:0] image_commands [0:COUNT-1];
    always_ff@(posedge gpu_clk)begin
        studio_data <= image_commands[studio_index];
    end
    initial begin
WORDS
    end""".replace('COUNT', str(len(commands)))
    source_block = source_block.replace('WORDS', '\n'.join(
        f"        image_commands[{i}] = 84'h{word:021x};" for i, word in enumerate(payload)))
    source, count = re.subn(r'`ifdef STUDIO_SIMULATION[\s\S]*?`endif', source_block, source)
    if count != 1:
        raise ValueError('Expected one Studio source in top.sv')
    source = re.sub(r'    initial begin\s*(?:\$readmemh\([^;]+;\s*)+end\n', '', source)
    output.mkdir(parents=True, exist_ok=True)
    (output/'top.sv').write_text(source, encoding='utf-8', newline='\n')
    rtl=output/'rtl';rtl.mkdir(exist_ok=True)
    for file in (project/'MGPU.srcs/sources_1/new').glob('*.sv'):
        if file.name!='top.sv':shutil.copy2(file,rtl/file.name)
    shutil.copy2(project/'MGPU.srcs/constrs_1/new/nexys_a7_vga.xdc',output/'nexys_a7_vga.xdc')
    (output/'build.tcl').write_text('''set root [file dirname [file normalize [info script]]]
cd $root
read_verilog -sv [glob [file join $root rtl *.sv]]
read_verilog -sv [file join $root top.sv]
read_xdc [file join $root nexys_a7_vga.xdc]
synth_design -top top -part xc7a100tcsg324-1
opt_design -propconst -sweep -remap -bufg_opt -shift_register_opt
place_design
phys_opt_design
route_design
report_timing_summary -file timing.rpt
report_utilization -file utilization.rpt
report_drc -file drc.rpt
foreach kind {max min} {
    set path [get_timing_paths -delay_type $kind -max_paths 1]
    if {[llength $path]==0 || [get_property SLACK $path]<0} {error "Timing failed"}
}
write_bitstream -force image_top.bit
''',encoding='utf-8')
    metadata=dict(top='top',render_width=320,render_height=240,image_triangles=len(mesh.triangles),commands=len(commands),
                  rom_bits=84*len(commands),rom_bram36_upper_bound=3*math.ceil(len(commands)/1024),
                  gpu_mhz=40.0,hardware_limit=MAX_BOARD_COMMANDS)
    (output/'manifest.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    (output/'README.txt').write_text('''Image Studio 上板包：目标 Nexys A7-100T，RGB332。
top.sv 是综合顶层，rtl/ 是原 GPU/VGA 的副本，nexys_a7_vga.xdc 是板级约束。
运行 vivado -mode batch -source build.tcl 生成 image_top.bit；每个新图片仍须通过布局布线时序检查。
也可在独立 Vivado 工程中加入这些文件并把 top 设为顶层。不要同时加入原工程的另一个 top.sv。
复位后先清屏，再绘制图片，完成后一直显示；CPU_RESETN 可重画。
此目录不会替换原工程的机械晶核演示。不要手改数字表，修改图片后重新导出。
''',encoding='utf-8')
    return output/'top.sv'
