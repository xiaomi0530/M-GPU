"""Pixel-exact RGB332 logo boot stage using compressed horizontal color runs.

Each run becomes two nondegenerate triangles. Runs paint one extra row and
one extra column for single-pixel runs; subsequent runs/rows restore these.
The black right/bottom margin is required and verified by the generator.
"""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]


def prepare_logo():
    """Fit the approved black-background asset, preserving RGB332 pixels."""
    import numpy as np
    from PIL import Image
    from image_triangles import load_image,quantize,RGB
    folder=ROOT/'assets/logo'
    output=ROOT/'out/logo'
    output.mkdir(parents=True,exist_ok=True)
    a=np.array(load_image(folder/'black_logo.png').convert('RGB'))
    yy,xx=np.where(np.max(a,axis=2)>60)
    box=(int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1))
    crop=Image.fromarray(a).crop(box)
    width=560;height=round(crop.height*width/crop.width)
    assert height<=236
    canvas=Image.new('RGB',(576,240),'black')
    canvas.paste(crop.resize((width,height),Image.Resampling.LANCZOS),
                 ((576-width)//2,(240-height)//2))
    pixels=quantize(np.array(canvas))
    assert not np.any(pixels[:,-2:]) and not np.any(pixels[-2:,:])
    runs=[]
    for y in range(240):
        x=0
        while x<576:
            end=x+1
            while end<576 and pixels[y,end]==pixels[y,x]:end+=1
            runs.append([x,y,end-x,int(pixels[y,x])]);x=end
    (folder/'runs.json').write_text(json.dumps(runs))
    np.save(folder/'rgb332.npy',pixels)
    framebuffer=np.zeros((480,640),dtype=np.uint8)
    framebuffer[120:360,32:608]=pixels
    Image.fromarray(RGB[framebuffer]).save(folder/'preview.png')
    (output/'expected.hex').write_text(''.join(f'{v:02x}\n' for v in framebuffer.flat))
    (folder/'metadata.json').write_text(json.dumps(dict(source='assets/logo/black_logo.png',
        crop=box,width=576,height=240,x=32,y=120,runs=len(runs)),indent=2))


def integrate_logo(path):
    runs=json.loads((ROOT/'assets/logo/runs.json').read_text())
    assert len(runs)<8192
    s=Path(path).read_text()
    assert 'module boot_logo_rom' not in s
    s=s.replace('    parameter STAGE_HOLD_MS = 4000,',
                '    parameter LOGO_HOLD_MS = 4000,\n    parameter STAGE_HOLD_MS = 4000,')
    s=s.replace('alignment target -> low-poly space painting -> orbiting satellite.',
                'logo -> alignment target -> low-poly space painting -> orbiting satellite.')
    s=s.replace('    reg [2:0] demo_state;',f'''    localparam LOGO_LAST=14'd{2*len(runs)+1};
    localparam LOGO_TICKS=(GPU_HZ/1000)*LOGO_HOLD_MS;
    reg logo_active;
    reg [13:0] logo_command;
    wire [13:0] logo_offset=logo_command-14'd2;
    wire [12:0] logo_address=(logo_command<2) ? 13'd0 : logo_offset[13:1];
    wire [35:0] logo_data;
    boot_logo_rom u_logo_rom(gpu_clk,logo_address,logo_data);
    wire [9:0] logo_left=10'd32+logo_data[27:18];
    wire [9:0] logo_right=logo_left+((logo_data[17:8]>1) ? logo_data[17:8]-10'd1 : 10'd1);
    wire [9:0] logo_y=10'd120+{{2'b0,logo_data[35:28]}};
    reg [2:0] demo_state;''')
    s=s.replace('wire last_command=(scene==0',
                'wire last_command=logo_active ? (logo_command==LOGO_LAST) : (scene==0')
    s=s.replace('demo_state<=FETCH; scene<=0; animation_frame<=0;',
                'demo_state<=FETCH; scene<=0; animation_frame<=0;\n            logo_active<=1;logo_command<=0;')
    s=s.replace('''                    {gpu_x0,gpu_y0,gpu_x1,gpu_y1,gpu_x2,gpu_y2,
                     gpu_c0,gpu_c1,gpu_c2}<=command_data;''','''                    if(logo_active) begin
                        if(logo_command<2) begin
                            gpu_x0<=0;gpu_y0<=0;gpu_x1<=639;
                            gpu_y1<=logo_command[0] ? 479 : 0;
                            gpu_x2<=logo_command[0] ? 0 : 639;gpu_y2<=479;
                            gpu_c0<=0;gpu_c1<=0;gpu_c2<=0;
                        end else begin
                            gpu_x0<=logo_left;gpu_y0<=logo_y;
                            gpu_x1<=logo_right;gpu_y1<=logo_command[0] ? logo_y+10'd1 : logo_y;
                            gpu_x2<=logo_command[0] ? logo_left : logo_right;gpu_y2<=logo_y+10'd1;
                            gpu_c0<=logo_data[7:0];gpu_c1<=logo_data[7:0];gpu_c2<=logo_data[7:0];
                        end
                    end else begin
                        {gpu_x0,gpu_y0,gpu_x1,gpu_y1,gpu_x2,gpu_y2,
                         gpu_c0,gpu_c1,gpu_c2}<=command_data;
                    end''')
    s=s.replace('hold_count<=scene==2 ?',
                'hold_count<=logo_active ? ((LOGO_TICKS>0)?LOGO_TICKS-1:0) : scene==2 ?')
    s=s.replace('end else begin command_address<=command_address+1\'b1;demo_state<=FETCH;end',
                '''end else begin
                        if(logo_active) logo_command<=logo_command+1'b1;
                        else command_address<=command_address+1'b1;
                        demo_state<=FETCH;
                    end''')
    s=s.replace('if(scene==0) begin scene<=1;command_address<=ART_START;end',
                '''if(logo_active) begin
                            logo_active<=0;command_address<=0;
                        end else if(scene==0) begin scene<=1;command_address<=ART_START;end''')
    s+=f'''\n// Lossless horizontal runs of the displayed RGB332 logo.
module boot_logo_rom(input wire clk,input wire [12:0] address,output reg [35:0] data);
    (* rom_style="block" *) reg [35:0] runs [0:{len(runs)-1}];
    always @(posedge clk) data<=runs[address];
    initial begin
'''
    for i,(x,y,length,color) in enumerate(runs):
        word=(y<<28)|(x<<18)|(length<<8)|color
        s+=f"        runs[{i}]=36'h{word:09x};\n"
    s+='    end\nendmodule\n'
    Path(path).write_text(s)


if __name__=='__main__':
    from build_space_demo import main
    prepare_logo()
    main()
