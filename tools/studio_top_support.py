"""Add a simulation-only command source to generated top.v (default RTL unchanged)."""
from pathlib import Path
import re


def integrate_studio(path):
    path=Path(path)
    text=path.read_text()
    if '// STUDIO_SIMULATION command source' in text:
        return
    text=text.replace('    wire [83:0] command_data;\n    space_triangle_rom u_scene_rom(gpu_clk,command_address,command_data);', '''    wire [83:0] command_data;
    wire [83:0] board_command_data;
    space_triangle_rom u_scene_rom(gpu_clk,command_address,board_command_data);
    // STUDIO_SIMULATION command source: defined only by the Studio testbench.
    // Normal synthesis and board simulation keep the original ROM/controller.
`ifdef STUDIO_SIMULATION
    wire studio_mode;
    wire [17:0] studio_count;
    reg [17:0] studio_index;
    reg studio_finished;
    wire [83:0] studio_data;
    studio_triangle_source u_studio_source(gpu_clk,studio_index,studio_data,studio_mode,studio_count);
    assign command_data=studio_mode ? studio_data : board_command_data;
`else
    assign command_data=board_command_data;
`endif''')
    text=re.sub(r'(    wire last_command=)([^;]+);',r'''\1
`ifdef STUDIO_SIMULATION
        studio_mode ? (studio_index+18'd1>=studio_count) :
`endif
        \2;''',text,count=1)
    text=text.replace('            logo_active<=1;logo_command<=0;', '''            logo_active<=1;logo_command<=0;
`ifdef STUDIO_SIMULATION
            studio_index<=0;studio_finished<=0;
            if(studio_mode) begin logo_active<=0;scene<=1;end
`endif''')
    text=text.replace('                FETCH: demo_state<=LOAD; // synchronous ROM read latency', '''                FETCH: begin
                    demo_state<=LOAD; // synchronous command-source read latency
`ifdef STUDIO_SIMULATION
                    if(studio_mode && studio_count==0) begin
                        studio_finished<=1;demo_state<=HOLD;
                    end
`endif
                end''')
    text=text.replace('                    if(last_command) begin', '''                    if(last_command) begin
`ifdef STUDIO_SIMULATION
                        if(studio_mode) studio_finished<=1;
`endif''')
    text=text.replace("                        if(logo_active) logo_command<=logo_command+1'b1;", '''`ifdef STUDIO_SIMULATION
                        if(studio_mode) studio_index<=studio_index+1'b1;
                        else
`endif
                        if(logo_active) logo_command<=logo_command+1'b1;''')
    text=text.replace('''                HOLD: begin
                    if(hold_count==0 || button_press) begin''','''                HOLD: begin
`ifdef STUDIO_SIMULATION
                    if(studio_mode) begin demo_state<=HOLD;end
                    else
`endif
                    if(hold_count==0 || button_press) begin''')
    assert 'u_studio_source' in text and 'studio_index<=studio_index' in text
    path.write_text(text)


if __name__=='__main__':
    integrate_studio(Path(__file__).resolve().parents[1]/'MGPU.srcs/sources_1/new/top.v')
