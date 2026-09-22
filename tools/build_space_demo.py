"""Generate RGB332 triangle ROM and previews; never alter handwritten GPU RTL.

Run with the project's numpy/Pillow Python. The background mesh is exported
by image_triangles.triangulate; all animation geometry is generated here.
"""
from pathlib import Path
import json
import math
import numpy as np
from PIL import Image
from image_triangles import Triangle, render, RGB

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets/lowpoly_space'
OUT = ROOT / 'out/lowpoly'
OUT.mkdir(parents=True, exist_ok=True)


def rect(x0, y0, x1, y1, color):
    return [(x0,y0,x1,y0,x1,y1,color,color,color),
            (x0,y0,x1,y1,x0,y1,color,color,color)]


def satellite(frame):
    angle=frame*2*math.pi/32
    cx,cy=round(158+65*math.cos(angle)),round(80+9*math.sin(angle))
    bank=0.15*math.sin(angle)
    commands=[]
    def tri(points,color):
        vertices=[]
        for x,y in points:
            vertices.extend((round(cx+x*math.cos(bank)-y*math.sin(bank)),
                             round(cy+x*math.sin(bank)+y*math.cos(bank))))
        x0,y0,x1,y1,x2,y2=vertices
        if (x1-x0)*(y2-y0)-(y1-y0)*(x2-x0):
            commands.append(tuple(vertices)+(color,)*3)
    def quad(points,color):
        tri(points[:3],color);tri([points[0],points[2],points[3]],color)
    # Solar arrays, metal supports and a shaded octagonal central bus.
    quad([(-20,-7),(-7,-7),(-7,7),(-20,7)],0x29)
    quad([(7,-7),(20,-7),(20,7),(7,7)],0x29)
    for side in (-1,1):
        for col in range(3):
            x=side*(9+col*4)
            for y in (-5,1):
                quad([(x,y),(x+3,y),(x+3,y+4),(x,y+4)],0x57 if col%2 else 0x2E)
    quad([(-8,-1),(8,-1),(8,1),(-8,1)],0xDB)
    points=[(-4,-6),(3,-6),(6,-2),(5,5),(-3,6),(-6,1)]
    colors=[0xFF,0xFB,0xD4,0xB0,0xDB,0xDF]
    for i in range(6):tri([(0,0),points[i],points[(i+1)%6]],colors[i])
    tri([(0,-6),(1,-11),(2,-6)],0xFF)
    return commands


def pack(command):
    word=0
    for i,v in enumerate(command):word=(word << (10 if i<6 else 8)) | v
    return word


def main():
    background=[tuple(t) for t in json.loads((ASSETS/'concept_triangles.json').read_text())
                if any(t[6:])]
    base=render([Triangle(t) for t in background])
    # This region is truly black in the fitted picture, so local black clears
    # restore the exact background without erasing stars or mountain details.
    assert not np.any(base[55:106,60:256])
    calibration=rect(0,0,639,479,0)
    for box in [(8,8,631,9),(8,470,631,471),(8,8,9,471),(630,8,631,471),
                (240,160,399,161),(240,318,399,319),(240,160,241,319),
                (398,160,399,319),(288,239,351,240),(319,208,320,271)]:
        calibration+=rect(*box,255)
    calibration+=rect(318,238,321,241,0xFC)
    commands=calibration+rect(0,0,639,479,0)+background
    art_start=len(calibration);art_end=len(commands)-1
    offsets=[];ends=[];frames=[]
    for frame in range(32):
        previous=satellite((frame-1)%32);current=satellite(frame)
        xs=[v for t in previous+current for v in t[:6:2]]
        ys=[v for t in previous+current for v in t[1:6:2]]
        erase=rect(min(xs)-1,min(ys)-1,max(xs)+1,max(ys)+1,0)
        assert min(xs)-1>=60 and max(xs)+1<=255
        assert min(ys)-1>=55 and max(ys)+1<=105
        offsets.append(len(commands));commands+=erase+current;ends.append(len(commands)-1)
        overlay=render([Triangle(t) for t in current])
        picture=base.copy();picture[overlay!=0]=overlay[overlay!=0]
        frames.append(Image.fromarray(RGB[picture]))
        np.save(OUT/f'frame_{frame:02}_expected.npy',picture)
    for t in commands:
        assert all(0<=t[i]<(640 if i%2==0 else 480) for i in range(6))
        assert (t[2]-t[0])*(t[5]-t[1])-(t[3]-t[1])*(t[4]-t[0])!=0
    Image.fromarray(RGB[base]).save(ASSETS/'background_preview.png')
    frames[8].save(ASSETS/'satellite_preview.png')
    frames[0].save(ASSETS/'satellite_motion.gif',save_all=True,append_images=frames[1:],duration=100,loop=0)
    np.save(OUT/'background_expected.npy',base)
    (OUT/'preview.hex').write_text(''.join(f'{v:02x}\n' for v in base.flat))
    metadata=dict(art_start=art_start,art_end=art_end,frame_starts=offsets,frame_ends=ends,
                  commands=len(commands),background_triangles=len(background),frames=32)
    (ASSETS/'scene_metadata.json').write_text(json.dumps(metadata,indent=2))
    (ASSETS/'scene_commands.json').write_text(json.dumps(commands))
    path=ROOT/'MGPU.srcs/sources_1/new/top.v'
    original=(ASSETS/'board_wrapper.v.in').read_text()
    prefix=original.split('// GENERATED_CONTROLLER')[0]
    prefix=prefix.replace('alignment target -> RGB triangle -> holographic rotating core.',
                          'alignment target -> low-poly space painting -> orbiting satellite.')
    prefix=prefix.replace('    // Half edge length in pixels before rotation (recommended 32..128).',
                          '    // Legacy parameter retained for compatibility; new art uses fixed coordinates.')
    body='''    // The generated ROM contains triangle commands, never framebuffer pixels.
    // The GPU still rasterizes and shades every triangle through its normal input.
    localparam GPU_HZ=100000000/(1 << GPU_CLK_DIV_LOG2);
    localparam STAGE_TICKS=(GPU_HZ/1000)*STAGE_HOLD_MS;
    localparam FRAME_TICKS=(GPU_HZ/1000)*CUBE_HOLD_MS;
    localparam FETCH=0, LOAD=1, ISSUE=2, WAIT_GPU=3, ADVANCE=4, HOLD=5;
    reg [2:0] demo_state;
    reg [1:0] scene;
    reg [4:0] animation_frame;
    reg [31:0] hold_count;
    reg [12:0] command_address;
    reg [12:0] drain_count;
    reg saw_busy;
    reg demo_start;
    wire gpu_busy,gpu_done;
    reg [9:0] gpu_x0,gpu_y0,gpu_x1,gpu_y1,gpu_x2,gpu_y2;
    reg [7:0] gpu_c0,gpu_c1,gpu_c2;
    wire [83:0] command_data;
    space_triangle_rom u_scene_rom(gpu_clk,command_address,command_data);
'''
    body+=f'    localparam ART_START=13\'d{art_start}, ART_END=13\'d{art_end};\n'
    for name,values in [('frame_start',offsets),('frame_end',ends)]:
        body+=f'    function [12:0] {name};\n        input [4:0] index;\n        begin\n            case(index)\n'
        body+=''.join(f'                5\'d{i}: {name}=13\'d{v};\n' for i,v in enumerate(values))
        body+=f'                default: {name}=13\'d{values[0]};\n            endcase\n        end\n    endfunction\n'
    body+='''    wire last_command=(scene==0 && command_address==23) ||
                      (scene==1 && command_address==ART_END) ||
                      (scene==2 && command_address==frame_end(animation_frame));
    always @(posedge gpu_clk) begin
        if(rst) begin
            demo_state<=FETCH; scene<=0; animation_frame<=0;
            command_address<=0; hold_count<=0; drain_count<=0;
            saw_busy<=0; demo_start<=0;
            gpu_x0<=0;gpu_y0<=0;gpu_x1<=0;gpu_y1<=0;gpu_x2<=0;gpu_y2<=0;
            gpu_c0<=0;gpu_c1<=0;gpu_c2<=0;
        end else begin
            demo_start<=0;
            case(demo_state)
                FETCH: demo_state<=LOAD; // synchronous ROM read latency
                LOAD: begin
                    {gpu_x0,gpu_y0,gpu_x1,gpu_y1,gpu_x2,gpu_y2,
                     gpu_c0,gpu_c1,gpu_c2}<=command_data;
                    demo_state<=ISSUE;
                end
                ISSUE: begin
                    demo_start<=1; saw_busy<=0; drain_count<=0;
                    demo_state<=WAIT_GPU;
                end
                WAIT_GPU: begin
                    if(gpu_busy) begin saw_busy<=1;drain_count<=0;end
                    else if(saw_busy) drain_count<=drain_count+1'b1;
                    // User's gpu_done can miss tiny triangles whose last pixel
                    // retires before rasterization ends. Only in that case use
                    // the original bounded drain: 8192 > 256*18 + one in flight.
                    if(saw_busy && (gpu_done || (!gpu_busy && &drain_count)))
                        demo_state<=ADVANCE;
                end
                ADVANCE: begin
                    if(last_command) begin
                        hold_count<=scene==2 ? ((FRAME_TICKS>0)?FRAME_TICKS-1:0)
                                                   : ((STAGE_TICKS>0)?STAGE_TICKS-1:0);
                        demo_state<=HOLD;
                    end else begin command_address<=command_address+1'b1;demo_state<=FETCH;end
                end
                HOLD: begin
                    if(hold_count==0 || button_press) begin
                        if(scene==0) begin scene<=1;command_address<=ART_START;end
                        else if(scene==1) begin
                            scene<=2;animation_frame<=0;command_address<=frame_start(0);
                        end else begin
                            animation_frame<=animation_frame+1'b1;
                            command_address<=frame_start(animation_frame+5'd1);
                        end
                        demo_state<=FETCH;
                    end else hold_count<=hold_count-1'b1;
                end
                default: demo_state<=FETCH;
            endcase
        end
    end
'''
    instance=original[original.index('    mgpu u_mgpu ('):]
    rom=f'''\n// Generated by tools/build_space_demo.py. Edit the generator, not this table.
// Synchronous initialized ROM permits block-RAM inference in Vivado.
module space_triangle_rom(input wire clk,input wire [12:0] address,output reg [83:0] data);
    (* rom_style="block" *) reg [83:0] commands [0:{len(commands)-1}];
    always @(posedge clk) data<=commands[address];
    initial begin
'''
    rom+=''.join(f"        commands[{i}]=84'h{pack(t):021x};\n" for i,t in enumerate(commands))
    rom+='    end\nendmodule\n'
    assert len(commands)<8192
    path.write_text(prefix+body+instance+rom)
    if (ROOT/"assets/logo/runs.json").exists():
        from logo_boot import integrate_logo
        integrate_logo(path)
    from studio_top_support import integrate_studio
    integrate_studio(path)
    from top_clear_support import integrate_clear
    integrate_clear(path)
    for array in OUT.glob('*_expected.npy'):
        pixels=np.load(array)
        array.with_suffix('.hex').write_text(''.join(f'{v:02x}\n' for v in pixels.flat))
    print(json.dumps(metadata))


if __name__=='__main__':main()
