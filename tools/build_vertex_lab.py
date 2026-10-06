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


def crystal_scene():
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


def scene():
    faces=[]
    for face in json.loads((ROOT/'assets/milk_frog/mesh.json').read_text()):
        vertices=[tuple(round((c+(5.4 if j==2 else 0))*Q) for j,c in enumerate(v)) for v in face['vertices']]
        faces.append((vertices,[project(v) for v in vertices],[rgb(*c) for c in face['colors']]))
    return faces


def generate():
    target=ROOT/'MGPU.srcs/sources_1/new/top.v'
    source=target.read_text(encoding='utf-8')
    prefix=source[:source.index('    localparam FETCH')] if '    // The generated ROM contains' not in source else source[:source.index('    // The generated ROM contains')]
    prefix='\n'.join(line.split('//')[0].rstrip() for line in prefix.splitlines())+'\n'
    from orbit_scene import matrix,project as orbit_project,order,FRAME_COUNT
    import midiyas_logo
    triangles=scene()
    model_count=len(triangles)
    orders=[order(frame) for frame in range(FRAME_COUNT)]
    matrices=[matrix(frame) for frame in range(FRAME_COUNT)]
    logo_triangles=midiyas_logo.scene()
    logo_count=len(logo_triangles)-model_count
    triangles+=logo_triangles[:logo_count]
    groups=[midiyas_logo.GROUP_COUNT-1]*model_count+list(midiyas_logo.groups())[:logo_count]
    assert len(groups)==len(triangles) and all(0<=group<midiyas_logo.GROUP_COUNT for group in groups)
    orders+=[[model_count+i if i<logo_count else i-logo_count for i in midiyas_logo.order(frame)] for frame in range(midiyas_logo.FRAME_COUNT)]
    matrices+=[midiyas_logo.matrix(frame,group) for frame in range(midiyas_logo.FRAME_COUNT) for group in range(midiyas_logo.GROUP_COUNT)]
    matrix_indices=list(range(FRAME_COUNT));unique_matrices=matrices[:FRAME_COUNT]
    matrix_lookup={tuple(values):index for index,values in enumerate(unique_matrices)}
    for values in matrices[FRAME_COUNT:]:
        key=tuple(values)
        if key not in matrix_lookup:
            matrix_lookup[key]=len(unique_matrices);unique_matrices.append(values)
        matrix_indices.append(matrix_lookup[key])
    matrices=unique_matrices
    frame_offsets=[];order_count=0
    for ordering in orders:
        frame_offsets.append(order_count);order_count+=len(ordering)
    assert len(triangles)<=2048
    index_bits=len(triangles).bit_length()
    group_bits=max(1,(midiyas_logo.GROUP_COUNT-1).bit_length())
    matrix_bits=max(1,(len(matrices)-1).bit_length())
    order_bits=max(1,(order_count-1).bit_length())
    prefix=prefix.replace('parameter CUBE_HOLD_MS = 200','parameter CUBE_HOLD_MS = 0')
    prefix=prefix.replace('parameter LOGO_HOLD_MS = 5000','parameter LOGO_HOLD_MS = 7000')
    if 'parameter TARGET_FPS' not in prefix:
        prefix=prefix.replace('parameter CUBE_HOLD_MS = 0,','parameter CUBE_HOLD_MS = 0,\n    parameter TARGET_FPS = 60,')
    if 'parameter START_FRAME' not in prefix:
        prefix=prefix.replace('parameter TARGET_FPS = 60,','parameter TARGET_FPS = 60,\n    parameter START_FRAME = 0,')
    if 'parameter START_LOGO_FRAME' not in prefix:
        prefix=prefix.replace('parameter START_FRAME = 0,','parameter START_FRAME = 0,\n    parameter START_LOGO_FRAME = 0,')
    body='''    localparam FETCH=0,LOAD=1,ISSUE=2,WAIT_GPU=3,ADVANCE=4,HOLD=5,CLEAR_ISSUE=6,CLEAR_WAIT=7,INDEX=8,PRESENT=9,SWAP_WAIT=10;
    localparam COMMAND_COUNT=COUNT_VALUE;
    localparam FRAME_COUNT=PHASE_VALUE;
    localparam LOGO_FRAME_COUNT=LOGO_PHASE_VALUE;
    localparam LOGO_GROUP_COUNT=GROUP_VALUE;
    localparam ROM_FRAME_COUNT=FRAME_COUNT+LOGO_FRAME_COUNT;
    localparam MATRIX_SLOT_COUNT=FRAME_COUNT+LOGO_FRAME_COUNT*LOGO_GROUP_COUNT;
    localparam MATRIX_COUNT=MATRICES_VALUE;
    localparam ORDER_COUNT=ORDERS_VALUE;
    localparam INTRO_NEXT_FRAME=25;
    localparam FRAME_TICKS=(TARGET_FPS>0) ? GPU_HZ/TARGET_FPS : 1;
    localparam LOGO_TICKS=(GPU_HZ/1000)*LOGO_HOLD_MS;
    reg [3:0] demo_state;
    reg [31:0] frame_elapsed;
    reg [31:0] boot_elapsed;
    reg paused;
    reg [17:0] command_address;
    reg demo_start,demo_clear,demo_present,saw_busy;
    wire gpu_busy,gpu_done,gpu_error,present_done;
    reg [9:0] gpu_x0,gpu_y0,gpu_x1,gpu_y1,gpu_x2,gpu_y2;
    reg [7:0] gpu_c0,gpu_c1,gpu_c2;
    reg signed [17:0] gpu_vx0,gpu_vy0,gpu_vz0;
    reg signed [17:0] gpu_vx1,gpu_vy1,gpu_vz1;
    reg signed [17:0] gpu_vx2,gpu_vy2,gpu_vz2;
    reg logo_active;
    wire [1:0] scene=logo_active ? 2'd0 : 2'd2;
    reg [$clog2(FRAME_COUNT)-1:0] animation_frame;
    reg [$clog2(LOGO_FRAME_COUNT)-1:0] logo_frame;
    wire [$clog2(ROM_FRAME_COUNT)-1:0] scene_frame=logo_active ? FRAME_COUNT+logo_frame : animation_frame;
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
    reg [GROUP_HIGH:0] command_group [0:COMMAND_COUNT-1];
    reg [185:0] command_data;
    (* rom_style="block" *) reg [INDEX_HIGH:0] draw_order [0:ORDER_COUNT-1];
    reg [INDEX_HIGH:0] frame_counts [0:ROM_FRAME_COUNT-1];
    reg [$clog2(ORDER_COUNT)-1:0] frame_offsets [0:ROM_FRAME_COUNT-1];
    (* rom_style="block" *) reg [287:0] matrices [0:MATRIX_COUNT-1];
    reg [$clog2(MATRIX_COUNT)-1:0] matrix_indices [0:MATRIX_SLOT_COUNT-1];
    reg [287:0] matrix_data;
    reg [INDEX_HIGH:0] order_data;
    wire [$clog2(ORDER_COUNT)-1:0] order_address=frame_offsets[scene_frame]+command_address;
    wire [$clog2(MATRIX_SLOT_COUNT)-1:0] matrix_slot=logo_active ? FRAME_COUNT+logo_frame*LOGO_GROUP_COUNT+command_group[order_data] : animation_frame;
    wire [$clog2(MATRIX_COUNT)-1:0] matrix_address=matrix_indices[matrix_slot];
    wire [INDEX_HIGH:0] frame_count=frame_counts[scene_frame];
`ifndef SYNTHESIS
    reg [59:0] reference_pixels [0:ORDER_COUNT-1];
    reg [59:0] reference_data;
    always @(posedge gpu_clk) reference_data<=reference_pixels[order_address];
`endif
    always @(posedge gpu_clk) begin
        order_data<=draw_order[order_address];
        if(order_data<COMMAND_COUNT) command_data<=commands[order_data];
        matrix_data<=matrices[matrix_address];
    end
    always @(posedge gpu_clk) begin
        if(rst) begin
            demo_state<=CLEAR_ISSUE;command_address<=0;
            animation_frame<=START_FRAME;frame_elapsed<=0;paused<=0;
            logo_active<=LOGO_HOLD_MS>0;logo_frame<=START_LOGO_FRAME;boot_elapsed<=0;
            demo_start<=0;demo_clear<=0;demo_present<=0;saw_busy<=0;
            gpu_x0<=0;gpu_y0<=0;gpu_x1<=0;gpu_y1<=0;gpu_x2<=0;gpu_y2<=0;
            gpu_c0<=0;gpu_c1<=0;gpu_c2<=0;
            gpu_vx0<=0;gpu_vy0<=0;gpu_vz0<=0;
            gpu_vx1<=0;gpu_vy1<=0;gpu_vz1<=0;
            gpu_vx2<=0;gpu_vy2<=0;gpu_vz2<=0;
        end else begin
            demo_start<=0;demo_clear<=0;demo_present<=0;
            if(button_press) paused<=!paused;
            if(studio_mode) logo_active<=0;
            if(logo_active && !paused && boot_elapsed<LOGO_TICKS) boot_elapsed<=boot_elapsed+1'b1;
            if(frame_elapsed<FRAME_TICKS) frame_elapsed<=frame_elapsed+1'b1;
            case(demo_state)
                CLEAR_ISSUE: begin
                    demo_clear<=1;saw_busy<=0;frame_elapsed<=1;demo_state<=CLEAR_WAIT;
                end
                CLEAR_WAIT: begin
                    if(gpu_busy) saw_busy<=1;
                    if(saw_busy && !gpu_busy) demo_state<=INDEX;
                end
                INDEX: demo_state<=FETCH;
                FETCH: demo_state<=((studio_mode ? studio_count : frame_count)==0) ? PRESENT : LOAD;
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
                        gpu_x0<=reference_data[59:50]*H_RES/640;gpu_y0<=reference_data[49:40]*V_RES/480;
                        gpu_x1<=reference_data[39:30]*H_RES/640;gpu_y1<=reference_data[29:20]*V_RES/480;
                        gpu_x2<=reference_data[19:10]*H_RES/640;gpu_y2<=reference_data[9:0]*V_RES/480;
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
                    if(command_address+1 >= (studio_mode ? studio_count : frame_count)) demo_state<=PRESENT;
                    else begin command_address<=command_address+1'b1;demo_state<=INDEX;end
                end
                PRESENT: begin
                    demo_present<=1;demo_state<=SWAP_WAIT;
                end
                SWAP_WAIT: begin
                    if(present_done) demo_state<=HOLD;
                end
                HOLD: begin
                    if(!studio_mode && !gpu_error && !paused && !button_press) begin
                        if(frame_elapsed>=FRAME_TICKS-1) begin
                            if(logo_active) begin
                                if(boot_elapsed>=LOGO_TICKS && logo_frame==LOGO_FRAME_COUNT-1) begin
                                    logo_active<=0;animation_frame<=INTRO_NEXT_FRAME;
                                end else if(logo_frame<LOGO_FRAME_COUNT-1) logo_frame<=logo_frame+1'b1;
                            end else animation_frame<=animation_frame+1'b1;
                            command_address<=0;demo_state<=CLEAR_ISSUE;
                        end
                    end
                end
                default: demo_state<=CLEAR_ISSUE;
            endcase
        end
    end
    mgpu #(.H_RES(H_RES),.V_RES(V_RES)) u_mgpu (
        .clk(gpu_clk), .rst(rst), .start(demo_start), .clear(demo_clear),
        .present(demo_present), .present_done(present_done),
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
'''.replace('COUNT_VALUE',str(len(triangles))).replace('LOGO_PHASE_VALUE',str(midiyas_logo.FRAME_COUNT)).replace('PHASE_VALUE',str(FRAME_COUNT)).replace('GROUP_VALUE',str(midiyas_logo.GROUP_COUNT)).replace('MATRICES_VALUE',str(len(matrices))).replace('ORDERS_VALUE',str(order_count)).replace('INDEX_HIGH',str(index_bits-1)).replace('GROUP_HIGH',str(group_bits-1))
    for index,(vertices,pixels,colors) in enumerate(triangles):
        word=0
        for vertex,color in zip(vertices,colors):
            for coordinate in vertex:word=(word<<18)|(coordinate&0x3ffff)
            word=(word<<8)|color
        body+=f"        commands[{index}]=186'h{word:047x};\n"
        body+=f"        command_group[{index}]={group_bits}'d{groups[index]};\n"
    for address,values in enumerate(matrices):
        word=0
        for value in values:word=(word<<18)|(value&0x3ffff)
        body+=f"        matrices[{address}]=288'h{word:072x};\n"
    for address,index in enumerate(matrix_indices):
        body+=f"        matrix_indices[{address}]={matrix_bits}'d{index};\n"
    for frame,ordering in enumerate(orders):
        body+=f"        frame_counts[{frame}]={index_bits}'d{len(ordering)};\n"
        body+=f"        frame_offsets[{frame}]={order_bits}'d{frame_offsets[frame]};\n"
        for index,ident in enumerate(ordering):
            body+=f"        draw_order[{frame_offsets[frame]+index}]={index_bits}'d{ident};\n"
    body+='    end\n`ifndef SYNTHESIS\n    initial begin\n'
    for frame,ordering in enumerate(orders):
        for index,ident in enumerate(ordering):
            word=0
            slot=frame if frame<FRAME_COUNT else FRAME_COUNT+(frame-FRAME_COUNT)*midiyas_logo.GROUP_COUNT+groups[ident]
            for vertex in triangles[ident][0]:
                for value in orbit_project(vertex,matrices[matrix_indices[slot]])[0]:word=(word<<10)|value
            body+=f"        reference_pixels[{frame_offsets[frame]+index}]=60'h{word:015x};\n"
    body+='    end\n`endif\n'

    target.write_text(prefix+body+'endmodule\n',encoding='utf-8')
    output=ROOT/'out/vertex_lab';output.mkdir(parents=True,exist_ok=True)
    (output/'scene.json').write_text(json.dumps(triangles))
    print(f'{len(triangles)} triangles -> {target}')


if __name__=='__main__':generate()
