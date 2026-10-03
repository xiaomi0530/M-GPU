from pathlib import Path
import json
import math
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
Q = 4096
MATRIX = [6144,0,0,0, 0,8192,0,0, 0,0,5006,4096, 0,0,-9102,0]


def project(vertex):
    clip = [sum(vertex[j]*MATRIX[j*4+i] for j in range(3)) + MATRIX[12+i]*Q for i in range(4)]
    clip = [v >> 12 for v in clip]
    assert clip[3] > 0
    ndc = [(abs(v)*Q//clip[3])*(-1 if v < 0 else 1) for v in clip[:3]]
    sx, sy, sz = (ndc[0]+Q)*320, (Q-ndc[1])*240, (ndc[2]+Q)>>1
    assert 0 <= sx < 640*Q and 0 <= sy < 480*Q and 0 <= sz <= Q
    return sx>>12, sy>>12


def rgb(r, g, b):
    return (round(max(0,min(255,r))*7/255)<<5) | (round(max(0,min(255,g))*7/255)<<2) | round(max(0,min(255,b))*3/255)


def scene():
    faces=[]
    center=np.array([0.,0.,5.4])

    def rotation(ax,az):
        cx,sx=math.cos(ax),math.sin(ax)
        cz,sz=math.cos(az),math.sin(az)
        return np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]]) @ np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])

    def tri(points,colors):
        vertices=[tuple(round(float(c)*Q) for c in p) for p in points]
        pixels=[project(v) for v in vertices]
        a,b,c=pixels
        if (b[0]-a[0])*(c[1]-a[1]) == (b[1]-a[1])*(c[0]-a[0]):
            return
        faces.append((vertices,pixels,[rgb(*color) for color in colors]))

    for radius,width,ax,az,palette in [
        (1.90,.095,1.02,.43,((255,105,30),(255,230,140))),
        (2.15,.055,.92,-.64,((30,100,225),(105,245,255)))
    ]:
        transform=rotation(ax,az)
        for i in range(32):
            angles=[2*math.pi*i/32,2*math.pi*(i+1)/32]
            points=[];colors=[]
            for theta,r in [(angles[0],radius-width/2),(angles[1],radius-width/2),
                            (angles[1],radius+width/2),(angles[0],radius+width/2)]:
                points.append(transform@np.array([r*math.cos(theta),r*math.sin(theta),0.])+center)
                t=(1+math.sin(theta+.7))/2
                colors.append(np.array(palette[0])*(1-t)+np.array(palette[1])*t)
            tri([points[k] for k in (0,1,2)],[colors[k] for k in (0,1,2)])
            tri([points[k] for k in (0,2,3)],[colors[k] for k in (0,2,3)])

    transform=rotation(.13,-.12)
    top=transform@np.array([0.,1.72,0.])+center
    bottom=transform@np.array([0.,-1.60,0.])+center
    upper=[];lower=[]
    for i in range(6):
        theta=2*math.pi*i/6+.24
        upper.append(transform@np.array([.69*math.cos(theta),.15,.69*math.sin(theta)])+center)
        lower.append(transform@np.array([.63*math.cos(theta),-.18,.63*math.sin(theta)])+center)
    for i in range(6):
        j=(i+1)%6
        gain=.52+.48*(1+math.cos(2*math.pi*i/6+.4))/2
        tip=np.array([190,255,255])*gain
        waist=np.array([35,185,250])*gain
        foot=np.array([115,45,225])*gain
        tri([top,upper[i],upper[j]],[tip,waist,waist*.78])
        tri([upper[i],lower[i],lower[j]],[waist,waist*.75,waist*.55])
        tri([upper[i],lower[j],upper[j]],[waist,waist*.55,waist*.78])
        tri([bottom,lower[j],lower[i]],[foot,waist*.55,waist*.75])
    return sorted(faces,key=lambda f:sum(v[2] for v in f[0]),reverse=True)


def generate():
    target=ROOT/'MGPU.srcs/sources_1/new/top.v'
    source=target.read_text(encoding='utf-8')
    prefix=source[:source.index('    localparam FETCH')] if '    // The generated ROM contains' not in source else source[:source.index('    // The generated ROM contains')]
    prefix='\n'.join(line.split('//')[0].rstrip() for line in prefix.splitlines())+'\n'
    from orbit_scene import matrix,project as orbit_project,order
    triangles=scene()
    assert len(triangles)<=256
    orders=[order(frame) for frame in range(32)]
    matrices=[matrix(frame) for frame in range(32)]
    prefix=prefix.replace('parameter CUBE_HOLD_MS = 40','parameter CUBE_HOLD_MS = 200')
    body='''    localparam FETCH=0,LOAD=1,ISSUE=2,WAIT_GPU=3,ADVANCE=4,HOLD=5,CLEAR_ISSUE=6,CLEAR_WAIT=7,INDEX=8;
    localparam COMMAND_COUNT=COUNT_VALUE;
    localparam HOLD_TICKS=(100000000/(1 << GPU_CLK_DIV_LOG2)/1000)*CUBE_HOLD_MS;
    reg [3:0] demo_state;
    reg [31:0] hold_count;
    reg paused;
    reg [17:0] command_address;
    reg demo_start,demo_clear,saw_busy;
    wire gpu_busy,gpu_done,gpu_error;
    reg [9:0] gpu_x0,gpu_y0,gpu_x1,gpu_y1,gpu_x2,gpu_y2;
    reg [7:0] gpu_c0,gpu_c1,gpu_c2;
    reg signed [17:0] gpu_vx0,gpu_vy0,gpu_vz0;
    reg signed [17:0] gpu_vx1,gpu_vy1,gpu_vz1;
    reg signed [17:0] gpu_vx2,gpu_vy2,gpu_vz2;
    wire logo_active=1'b0;
    wire [1:0] scene=2'd2;
    reg [4:0] animation_frame;
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
    (* rom_style="block" *) reg [185:0] commands [0:COMMAND_COUNT-1];
    reg [185:0] command_data;
    (* rom_style="block" *) reg [7:0] draw_order [0:32*COMMAND_COUNT-1];
    reg [7:0] frame_counts [0:31];
    (* rom_style="block" *) reg [287:0] matrices [0:31];
    reg [287:0] matrix_data;
    reg [7:0] order_data;
    wire [12:0] order_address=animation_frame*COMMAND_COUNT+command_address;
    wire [7:0] frame_count=frame_counts[animation_frame];
`ifndef SYNTHESIS
    reg [59:0] reference_pixels [0:32*COMMAND_COUNT-1];
    reg [59:0] reference_data;
    always @(posedge gpu_clk) reference_data<=reference_pixels[order_address];
`endif
    always @(posedge gpu_clk) begin
        order_data<=draw_order[order_address];
        if(order_data<COMMAND_COUNT) command_data<=commands[order_data];
        matrix_data<=matrices[animation_frame];
    end
    always @(posedge gpu_clk) begin
        if(rst) begin
            demo_state<=CLEAR_ISSUE;command_address<=0;
            animation_frame<=0;hold_count<=0;paused<=0;
            demo_start<=0;demo_clear<=0;saw_busy<=0;
            gpu_x0<=0;gpu_y0<=0;gpu_x1<=0;gpu_y1<=0;gpu_x2<=0;gpu_y2<=0;
            gpu_c0<=0;gpu_c1<=0;gpu_c2<=0;
            gpu_vx0<=0;gpu_vy0<=0;gpu_vz0<=0;
            gpu_vx1<=0;gpu_vy1<=0;gpu_vz1<=0;
            gpu_vx2<=0;gpu_vy2<=0;gpu_vz2<=0;
        end else begin
            demo_start<=0;demo_clear<=0;
            if(button_press) paused<=!paused;
            case(demo_state)
                CLEAR_ISSUE: begin
                    demo_clear<=1;saw_busy<=0;hold_count<=0;demo_state<=CLEAR_WAIT;
                end
                CLEAR_WAIT: begin
                    if(gpu_busy) saw_busy<=1;
                    if(saw_busy && !gpu_busy) demo_state<=INDEX;
                end
                INDEX: demo_state<=FETCH;
                FETCH: demo_state<=(studio_mode && studio_count==0) ? HOLD : LOAD;
                LOAD: begin
                    if(studio_mode) begin
                        {gpu_x0,gpu_y0,gpu_x1,gpu_y1,gpu_x2,gpu_y2,gpu_c0,gpu_c1,gpu_c2}<=studio_data;
                        gpu_vx0<={1'd0,studio_data[83:74],7'd0};gpu_vy0<={1'd0,studio_data[73:64],7'd0};gpu_vz0<=0;
                        gpu_vx1<={1'd0,studio_data[63:54],7'd0};gpu_vy1<={1'd0,studio_data[53:44],7'd0};gpu_vz1<=0;
                        gpu_vx2<={1'd0,studio_data[43:34],7'd0};gpu_vy2<={1'd0,studio_data[33:24],7'd0};gpu_vz2<=0;
                    end else begin
                        {gpu_vx0,gpu_vy0,gpu_vz0,gpu_c0,gpu_vx1,gpu_vy1,gpu_vz1,gpu_c1,
                         gpu_vx2,gpu_vy2,gpu_vz2,gpu_c2}<=command_data;
`ifndef SYNTHESIS
                        {gpu_x0,gpu_y0,gpu_x1,gpu_y1,gpu_x2,gpu_y2}<=reference_data;
`endif
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
                    if(command_address+1 >= (studio_mode ? studio_count : frame_count)) demo_state<=HOLD;
                    else begin command_address<=command_address+1'b1;demo_state<=INDEX;end
                end
                HOLD: begin
                    if(!studio_mode && !gpu_error && !paused && !button_press) begin
                        if(hold_count>=HOLD_TICKS) begin
                            animation_frame<=animation_frame+1'b1;
                            command_address<=0;demo_state<=CLEAR_ISSUE;hold_count<=0;
                        end else hold_count<=hold_count+1'b1;
                    end
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
        .m00(studio_mode ? 18'sd6144 : $signed(matrix_data[287:270])), .m01(studio_mode ? 18'sd0 : $signed(matrix_data[269:252])), .m02(studio_mode ? 18'sd0 : $signed(matrix_data[251:234])), .m03(studio_mode ? 18'sd0 : $signed(matrix_data[233:216])),
        .m10(studio_mode ? 18'sd0 : $signed(matrix_data[215:198])), .m11(studio_mode ? -18'sd8192 : $signed(matrix_data[197:180])), .m12(studio_mode ? 18'sd0 : $signed(matrix_data[179:162])), .m13(studio_mode ? 18'sd0 : $signed(matrix_data[161:144])),
        .m20(studio_mode ? 18'sd0 : $signed(matrix_data[143:126])), .m21(studio_mode ? 18'sd0 : $signed(matrix_data[125:108])), .m22(studio_mode ? 18'sd4096 : $signed(matrix_data[107:90])), .m23(studio_mode ? 18'sd0 : $signed(matrix_data[89:72])),
        .m30(studio_mode ? -18'sd61344 : $signed(matrix_data[71:54])), .m31(studio_mode ? 18'sd61312 : $signed(matrix_data[53:36])), .m32(studio_mode ? 18'sd0 : $signed(matrix_data[35:18])), .m33(studio_mode ? 18'sd61440 : $signed(matrix_data[17:0])),
        .clear_color(8'h00), .gpu_busy(gpu_busy), .gpu_done(gpu_done), .gpu_error(gpu_error),
        .vga_clk(CLK100MHZ), .vga_rst(vga_rst),
        .vga_r(VGA_R), .vga_g(VGA_G), .vga_b(VGA_B), .vga_hs(VGA_HS), .vga_vs(VGA_VS)
    );
    initial begin
'''.replace('COUNT_VALUE',str(len(triangles)))
    for index,(vertices,pixels,colors) in enumerate(triangles):
        word=0
        for vertex,color in zip(vertices,colors):
            for coordinate in vertex:word=(word<<18)|(coordinate&0x3ffff)
            word=(word<<8)|color
        body+=f"        commands[{index}]=186'h{word:047x};\n"
    for frame,ordering in enumerate(orders):
        word=0
        for value in matrices[frame]:word=(word<<18)|(value&0x3ffff)
        body+=f"        matrices[{frame}]=288'h{word:072x};\n"
        body+=f"        frame_counts[{frame}]=8'd{len(ordering)};\n"
        for index in range(len(triangles)):
            ident=ordering[index] if index<len(ordering) else 0
            body+=f"        draw_order[{frame*len(triangles)+index}]=8'd{ident};\n"
    body+='    end\n`ifndef SYNTHESIS\n    initial begin\n'
    for frame,ordering in enumerate(orders):
        for index,ident in enumerate(ordering):
            word=0
            for vertex in triangles[ident][0]:
                for value in orbit_project(vertex,matrices[frame])[0]:word=(word<<10)|value
            body+=f"        reference_pixels[{frame*len(triangles)+index}]=60'h{word:015x};\n"
    body+='    end\n`endif\n'

    target.write_text(prefix+body+'endmodule\n',encoding='utf-8')
    output=ROOT/'out/vertex_lab';output.mkdir(parents=True,exist_ok=True)
    (output/'scene.json').write_text(json.dumps(triangles))
    print(f'{len(triangles)} triangles -> {target}')


if __name__=='__main__':generate()
