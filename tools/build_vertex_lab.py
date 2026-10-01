from pathlib import Path
import json
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
Q = 65536
MATRIX = [98304,0,0,0, 0,131072,0,0, 0,0,80100,65536, 0,0,-145636,0]


def project(vertex):
    clip = [sum(vertex[j]*MATRIX[j*4+i] for j in range(3)) + MATRIX[12+i]*Q for i in range(4)]
    clip = [v >> 16 for v in clip]
    assert clip[3] > 0
    ndc = [(abs(v)*Q//clip[3])*(-1 if v < 0 else 1) for v in clip[:3]]
    sx, sy, sz = (ndc[0]+Q)*320, (Q-ndc[1])*240, (ndc[2]+Q)>>1
    assert 0 <= sx < 640*Q and 0 <= sy < 480*Q and 0 <= sz <= Q
    return sx>>16, sy>>16


def rgb(r, g, b):
    return (round(max(0,min(255,r))*7/255)<<5) | (round(max(0,min(255,g))*7/255)<<2) | round(max(0,min(255,b))*3/255)


def scene():
    triangles = []

    def tri(points, color):
        vertices = [tuple(round(float(c)*Q) for c in p) for p in points]
        pixels = [project(v) for v in vertices]
        a,b,c = pixels
        if (b[0]-a[0])*(c[1]-a[1]) == (b[1]-a[1])*(c[0]-a[0]):
            return
        triangles.append((vertices, pixels, color))

    def plane(x,y,z=3):
        return ((2*(x+.5)/640-1)*z/1.5, (1-2*(y+.5)/480)*z/2, z)

    def rect(x,y,w,h,col):
        p = [plane(x,y),plane(x+w,y),plane(x+w,y+h),plane(x,y+h)]
        tri(p[:3],col);tri([p[0],p[2],p[3]],col)

    def line(x0,y0,x1,y1,width,col):
        dx,dy=x1-x0,y1-y0
        length=math.hypot(dx,dy)
        nx,ny=-dy*width/(2*length),dx*width/(2*length)
        p=[plane(x0+nx,y0+ny),plane(x1+nx,y1+ny),plane(x1-nx,y1-ny),plane(x0-nx,y0-ny)]
        tri(p[:3],col);tri([p[0],p[2],p[3]],col)

    def text(x,y,value,size,col):
        font=ImageFont.truetype('C:/Windows/Fonts/consola.ttf',size)
        box=font.getbbox(value)
        mask=Image.new('1',(box[2]+1,box[3]-box[1]+1))
        ImageDraw.Draw(mask).text((0,-box[1]),value,font=font,fill=1)
        for py in range(mask.height):
            px=0
            while px<mask.width:
                if not mask.getpixel((px,py)):
                    px+=1;continue
                start=px
                while px<mask.width and mask.getpixel((px,py)):px+=1
                rect(x+start,y+py,max(1,px-start-1),1,col)

    cyan,white,muted,amber=rgb(60,220,255),rgb(220,240,255),rgb(75,110,145),rgb(255,182,40)
    text(24,20,'MGPU',26,white)
    text(102,28,'/  VERTEX LAB',16,cyan)
    text(407,28,'01 / PERSPECTIVE',13,muted)
    rect(24,57,592,1,muted)
    text(24,72,'Q16.16 XYZ  >  MVP  >  DIVIDE  >  RGB332',12,muted)
    for x in range(32,397,26):line(x,115,x,353,1,rgb(0,36,0))
    for y in range(119,354,26):line(32,y,396,y,1,rgb(0,36,0))
    rect(416,112,1,241,muted)

    faces=[]
    cx,sx=math.cos(.73),math.sin(.73)
    cy,sy=math.cos(-.43),math.sin(-.43)
    rotation=np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]]) @ np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])
    def shade(points,base):
        p=np.asarray(points)
        normal=np.cross(p[1]-p[0],p[2]-p[0])
        normal/=np.linalg.norm(normal)
        light=np.array([-.4,.65,-.65]);light/=np.linalg.norm(light)
        gain=.32+.68*max(0,float(normal@light))
        return rgb(*(np.asarray(base)*gain))
    def torus(u,v):
        p=np.array([(1.08+.32*math.cos(v))*math.cos(u),(1.08+.32*math.cos(v))*math.sin(u),.32*math.sin(v)])
        return rotation@p+np.array([-.85,.02,4.5])
    for i in range(32):
        for j in range(12):
            u,v=i*2*math.pi/32,j*2*math.pi/12
            p=[torus(u,v),torus(u+2*math.pi/32,v),torus(u+2*math.pi/32,v+2*math.pi/12),torus(u,v+2*math.pi/12)]
            for idx in [(0,1,2),(0,2,3)]:
                points=[p[k] for k in idx]
                base=(70,235,255) if i%8 else (190,250,255)
                faces.append((points,shade(points,base)))
    octa=[np.array(v)*.48+np.array([-.85,.02,4.5]) for v in [(1,0,0),(0,1,0),(-1,0,0),(0,-1,0),(0,0,1),(0,0,-1)]]
    for i in range(4):
        for indices in [(i,(i+1)%4,4),((i+1)%4,i,5)]:
            p=[octa[k] for k in indices];faces.append((p,shade(p,(255,195,65))))

    for px,py,z in [(485,169,3.0),(539,254,4.5),(484,324,6.5)]:
        center=np.array(plane(px,py,z))
        vertices=[rotation@np.array([x,y,d])*.20+center for x,y,d in [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]
        for face in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(3,7,6,2),(0,4,7,3),(1,2,6,5)]:
            for a,b,c in [(0,1,2),(0,2,3)]:
                p=[vertices[face[k]] for k in (a,b,c)]
                faces.append((p,shade(p,(255,195,65))))
    for points,color in sorted(faces,key=lambda f:np.mean([p[2] for p in f[0]]),reverse=True):tri(points,color)

    text(439,113,'SAME SIZE',12,white)
    text(548,169,'Z=3.0',11,amber)
    text(438,245,'4.5',11,amber)
    text(526,319,'6.5',11,amber)
    text(47,363,'TORUS / 32 x 12',12,cyan)
    text(439,363,'SCALE ~ 1/Z',12,cyan)
    line(36,339,64,339,2,amber);line(36,339,36,312,2,cyan)
    text(68,335,'X',10,amber);text(32,299,'Y',10,cyan)
    rect(24,389,592,1,muted)
    text(24,404,'RGB332',12,white)
    for row,n in enumerate((8,8,4)):
        for i in range(n):
            col=(i<<5) if row==0 else (i<<2) if row==1 else i
            rect(112+i*28*8/n,402+row*10,28*8/n-3,6,col)
    text(376,404,'N/F  1.0 / 10.0',11,muted)
    text(376,423,'FOV-Y  53.13 DEG',11,muted)
    text(24,453,'PERSPECTIVE VERIFIED',11,cyan)
    text(282,453,'PAINTER ORDER / NO Z-BUFFER',11,muted)
    return triangles


def generate():
    target=ROOT/'MGPU.srcs/sources_1/new/top.v'
    source=target.read_text(encoding='utf-8')
    prefix=source[:source.index('    localparam FETCH')] if '    // The generated ROM contains' not in source else source[:source.index('    // The generated ROM contains')]
    prefix='\n'.join(line.split('//')[0].rstrip() for line in prefix.splitlines())+'\n'
    triangles=scene()
    body='''    localparam FETCH=0,LOAD=1,ISSUE=2,WAIT_GPU=3,ADVANCE=4,HOLD=5,CLEAR_ISSUE=6,CLEAR_WAIT=7;
    localparam COMMAND_COUNT=COUNT_VALUE;
    reg [2:0] demo_state;
    reg [17:0] command_address;
    reg demo_start,demo_clear,saw_busy;
    wire gpu_busy,gpu_done,gpu_error;
    reg [9:0] gpu_x0,gpu_y0,gpu_x1,gpu_y1,gpu_x2,gpu_y2;
    reg [7:0] gpu_c0,gpu_c1,gpu_c2;
    reg signed [31:0] gpu_vx0,gpu_vy0,gpu_vz0;
    reg signed [31:0] gpu_vx1,gpu_vy1,gpu_vz1;
    reg signed [31:0] gpu_vx2,gpu_vy2,gpu_vz2;
    wire logo_active=1'b0;
    wire [1:0] scene=2'd1;
    wire [4:0] animation_frame=0;
    wire [17:0] studio_index=command_address;
    wire studio_finished=(demo_state==HOLD);
`ifdef STUDIO_SIMULATION
    wire studio_mode;
    wire [17:0] studio_count;
    wire [83:0] studio_data;
    studio_triangle_source u_studio_source(gpu_clk,studio_index,studio_data,studio_mode,studio_count);
`else
    wire studio_mode=1'b0;
    wire [17:0] studio_count=0;
    wire [83:0] studio_data=0;
`endif
    (* rom_style="block" *) reg [371:0] commands [0:COMMAND_COUNT-1];
    reg [371:0] command_data;
    always @(posedge gpu_clk) begin
        if(command_address<COMMAND_COUNT) command_data<=commands[command_address];
    end
    always @(posedge gpu_clk) begin
        if(rst) begin
            demo_state<=CLEAR_ISSUE;command_address<=0;
            demo_start<=0;demo_clear<=0;saw_busy<=0;
            gpu_x0<=0;gpu_y0<=0;gpu_x1<=0;gpu_y1<=0;gpu_x2<=0;gpu_y2<=0;
            gpu_c0<=0;gpu_c1<=0;gpu_c2<=0;
            gpu_vx0<=0;gpu_vy0<=0;gpu_vz0<=0;
            gpu_vx1<=0;gpu_vy1<=0;gpu_vz1<=0;
            gpu_vx2<=0;gpu_vy2<=0;gpu_vz2<=0;
        end else begin
            demo_start<=0;demo_clear<=0;
            case(demo_state)
                CLEAR_ISSUE: begin
                    demo_clear<=1;saw_busy<=0;demo_state<=CLEAR_WAIT;
                end
                CLEAR_WAIT: begin
                    if(gpu_busy) saw_busy<=1;
                    if(saw_busy && !gpu_busy) demo_state<=FETCH;
                end
                FETCH: demo_state<=(studio_mode && studio_count==0) ? HOLD : LOAD;
                LOAD: begin
                    if(studio_mode) begin
                        {gpu_x0,gpu_y0,gpu_x1,gpu_y1,gpu_x2,gpu_y2,gpu_c0,gpu_c1,gpu_c2}<=studio_data;
                        gpu_vx0<={6'd0,studio_data[83:74],16'd0};gpu_vy0<={6'd0,studio_data[73:64],16'd0};gpu_vz0<=0;
                        gpu_vx1<={6'd0,studio_data[63:54],16'd0};gpu_vy1<={6'd0,studio_data[53:44],16'd0};gpu_vz1<=0;
                        gpu_vx2<={6'd0,studio_data[43:34],16'd0};gpu_vy2<={6'd0,studio_data[33:24],16'd0};gpu_vz2<=0;
                    end else begin
                        {gpu_vx0,gpu_vy0,gpu_vz0,gpu_c0,gpu_vx1,gpu_vy1,gpu_vz1,gpu_c1,
                         gpu_vx2,gpu_vy2,gpu_vz2,gpu_c2,gpu_x0,gpu_y0,gpu_x1,gpu_y1,gpu_x2,gpu_y2}<=command_data;
                    end
                    demo_state<=ISSUE;
                end
                ISSUE: begin
                    if(!gpu_busy) begin demo_start<=1;demo_state<=WAIT_GPU;end
                end
                WAIT_GPU: begin
                    if(gpu_done) demo_state<=gpu_error ? HOLD : ADVANCE;
                end
                ADVANCE: begin
                    if(command_address+1 >= (studio_mode ? studio_count : COMMAND_COUNT)) demo_state<=HOLD;
                    else begin command_address<=command_address+1'b1;demo_state<=FETCH;end
                end
                HOLD: begin
                    if(button_press) begin command_address<=0;demo_state<=CLEAR_ISSUE;end
                end
                default: demo_state<=CLEAR_ISSUE;
            endcase
        end
    end
    mgpu u_mgpu (
        .clk(gpu_clk), .rst(rst), .start(demo_start), .clear(demo_clear),
        .vertex_x0(gpu_vx0), .vertex_y0(gpu_vy0), .vertex_z0(gpu_vz0), .vertex_color0(gpu_c0),
        .vertex_x1(gpu_vx1), .vertex_y1(gpu_vy1), .vertex_z1(gpu_vz1), .vertex_color1(gpu_c1),
        .vertex_x2(gpu_vx2), .vertex_y2(gpu_vy2), .vertex_z2(gpu_vz2), .vertex_color2(gpu_c2),
        .m00(studio_mode ? 32'sd393216 : 32'sd98304), .m01(32'sd0), .m02(32'sd0), .m03(32'sd0),
        .m10(32'sd0), .m11(studio_mode ? -32'sd524288 : 32'sd131072), .m12(32'sd0), .m13(32'sd0),
        .m20(32'sd0), .m21(32'sd0), .m22(studio_mode ? 32'sd65536 : 32'sd80100), .m23(studio_mode ? 32'sd0 : 32'sd65536),
        .m30(studio_mode ? -32'sd125632512 : 32'sd0), .m31(studio_mode ? 32'sd125566976 : 32'sd0),
        .m32(studio_mode ? 32'sd0 : -32'sd145636), .m33(studio_mode ? 32'sd125829120 : 32'sd0),
        .clear_color(8'h00), .gpu_busy(gpu_busy), .gpu_done(gpu_done), .gpu_error(gpu_error),
        .vga_clk(CLK100MHZ), .vga_rst(vga_rst),
        .vga_r(VGA_R), .vga_g(VGA_G), .vga_b(VGA_B), .vga_hs(VGA_HS), .vga_vs(VGA_VS)
    );
    initial begin
'''.replace('COUNT_VALUE',str(len(triangles)))
    for index,(vertices,pixels,color) in enumerate(triangles):
        word=0
        for vertex in vertices:
            for coordinate in vertex:word=(word<<32)|(coordinate&0xffffffff)
            word=(word<<8)|color
        for pixel in pixels:
            for coordinate in pixel:word=(word<<10)|coordinate
        body+=f"        commands[{index}]=372'h{word:093x};\n"
    target.write_text(prefix+body+'    end\nendmodule\n',encoding='utf-8')
    output=ROOT/'out/vertex_lab';output.mkdir(parents=True,exist_ok=True)
    (output/'scene.json').write_text(json.dumps(triangles))
    print(f'{len(triangles)} triangles -> {target}')


if __name__=='__main__':generate()
