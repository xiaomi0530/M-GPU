`timescale 1ns / 1ps

module mgpu #(
    parameter H_RES = 640,
    parameter V_RES = 480,
    parameter FB_PIXELS = H_RES * V_RES,
    parameter FB_ADDR_W = 19
)(
    input  wire        clk,
    input  wire        rst,
    input  wire        start,
    input  wire        clear,
    input  wire signed [17:0]  vertex_x0,
    input  wire signed [17:0]  vertex_y0,
    input  wire signed [17:0]  vertex_z0,
    input         wire [7:0]  vertex_color0,

    input  wire signed [17:0]  vertex_x1,
    input  wire signed [17:0]  vertex_y1,
    input  wire signed [17:0]  vertex_z1,
    input         wire [7:0]  vertex_color1,

    input  wire signed [17:0]  vertex_x2,
    input  wire signed [17:0]  vertex_y2,
    input  wire signed [17:0]  vertex_z2,
    input         wire [7:0]  vertex_color2,

    input signed [17:0] m00,
    input signed [17:0] m01,
    input signed [17:0] m02,
    input signed [17:0] m03,

    input signed [17:0] m10,
    input signed [17:0] m11,
    input signed [17:0] m12,
    input signed [17:0] m13,

    input signed [17:0] m20,
    input signed [17:0] m21,
    input signed [17:0] m22,
    input signed [17:0] m23,

    input signed [17:0] m30,
    input signed [17:0] m31,
    input signed [17:0] m32,
    input signed [17:0] m33,

    input  wire [7:0] clear_color,
    output wire       gpu_busy,
    output wire       gpu_done,
    output wire       gpu_error,

    input  wire       vga_clk,
    input  wire       vga_rst,
    output wire [3:0] vga_r,
    output wire [3:0] vga_g,
    output wire [3:0] vga_b,
    output wire       vga_hs,
    output wire       vga_vs
);
    reg [7:0] frame_buffer [0:FB_PIXELS-1];

    integer i;
    initial begin
        for(i=0;i<=FB_PIXELS-1;i=i+1)begin
            frame_buffer[i] <= clear_color;
        end
    end

    function [18:0] pixel_addr;
        input [9:0] x;
        input [9:0] y;
        begin
            pixel_addr = (y<<9)+(y<<7) + x;
        end
    endfunction
    function [7:0] Q312_to_RGB332;
        input signed [31:0] R;
        input signed [31:0] G;
        input signed [31:0] B;

        reg [2:0] r8;
        reg [2:0] g8;
        reg [1:0] b8;

        reg signed [31:0] clamp_R;
        reg signed [31:0] clamp_G;
        reg signed [31:0] clamp_B;
        begin
            if(R < 0)begin
                clamp_R = 0;
            end else if (R > 4096)begin
                clamp_R = 4096;
            end else begin
                clamp_R = R;
            end
            if(G < 0)begin
                clamp_G = 0;
            end else if (G > 4096)begin
                clamp_G = 4096;
            end else begin
                clamp_G = G;
            end
            if(B < 0)begin
                clamp_B = 0;
            end else if (B > 4096)begin
                clamp_B = 4096;
            end else begin
                clamp_B = B;
            end

            r8 = (clamp_R * 7 + 2048) >> 12;
            g8 = (clamp_G * 7 + 2048) >> 12;
            b8 = (clamp_B * 3 + 2048) >> 12;

            Q312_to_RGB332 = {r8,g8,b8};

        end
    endfunction

    localparam GPU_IDLE       = 3'd0;
    localparam GPU_VS_START   = 3'd1;
    localparam GPU_VS_WAIT    = 3'd2;
    localparam GPU_CHECK      = 3'd3;
    localparam GPU_LOAD       = 3'd4;
    localparam GPU_RAST_START = 3'd5;
    localparam GPU_DRAW_WAIT  = 3'd6;
    localparam GPU_DONE       = 3'd7;

    localparam signed [31:0] SCREEN_X_LIMIT = H_RES * 4096;
    localparam signed [31:0] SCREEN_Y_LIMIT = V_RES * 4096;

    reg [2:0] gpu_state;
    reg [2:0] vs_seen;
    reg [9:0] pending_pixels;
    reg gpu_done_reg;
    reg draw_error;

    reg vs_start0, vs_start1, vs_start2;
    wire vs_busy0, vs_busy1, vs_busy2;
    wire vs_done0, vs_done1, vs_done2;
    wire vs_error0, vs_error1, vs_error2;

    wire signed [31:0] screen_x0, screen_y0, screen_z0;
    wire signed [31:0] screen_x1, screen_y1, screen_z1;
    wire signed [31:0] screen_x2, screen_y2, screen_z2;
    wire [7:0] screen_color0, screen_color1, screen_color2;

    reg [9:0] rast_x0, rast_y0;
    reg [9:0] rast_x1, rast_y1;
    reg [9:0] rast_x2, rast_y2;
    reg [7:0] rast_color0, rast_color1, rast_color2;

    wire [2:0] vs_seen_next;
    wire vs_error_any;
    wire screen_valid;
    wire clear_accept;

    function screen_inside;
        input signed [31:0] x,y,z;
        begin
            screen_inside = (x >= 0) && (x < SCREEN_X_LIMIT) &&
                            (y >= 0) && (y < SCREEN_Y_LIMIT) &&
                            (z >= 0) && (z <= 32'sd4096);
        end
    endfunction

    assign vs_seen_next = vs_seen | {vs_done2,vs_done1,vs_done0};
    assign vs_error_any = vs_error0 | vs_error1 | vs_error2;
    assign screen_valid = screen_inside(screen_x0,screen_y0,screen_z0) &&
                          screen_inside(screen_x1,screen_y1,screen_z1) &&
                          screen_inside(screen_x2,screen_y2,screen_z2);
    assign clear_accept = clear && !rst && (gpu_state == GPU_IDLE) && !clear_busy && !clear_reg;
    assign gpu_busy = (gpu_state != GPU_IDLE) || clear_busy || clear_reg;
    assign gpu_done = gpu_done_reg;
    assign gpu_error = draw_error;

    reg         rast_start;
    wire        rast_valid;
    wire        rast_done;
    wire        rast_busy;
    reg         rast_finished;

    wire  [9:0]  frag_x;
    wire  [9:0]  frag_y;
    wire  [31:0] frag_clor_R;
    wire  [31:0] frag_clor_G;
    wire  [31:0] frag_clor_B;
    wire         frag_valid;

    assign rast_valid = !fifo_rs_full;

    wire [27:0] fifo_rs_wdata;
    wire        fifo_rs_wen;
    wire        fifo_rs_ren;
    wire [27:0] fifo_rs_rdata;
    wire        fifo_rs_rvalid;
    wire        fifo_rs_empty;
    wire        fifo_rs_full;

    assign fifo_rs_wdata = {frag_x,frag_y,Q312_to_RGB332(frag_clor_R,frag_clor_G,frag_clor_B)};
    assign fifo_rs_wen = (gpu_state == GPU_DRAW_WAIT) && !rst && frag_valid && rast_valid;

    always @(posedge clk) begin
        if(rst)begin
            gpu_state <= GPU_IDLE;
            vs_start0 <= 1'b0;
            vs_start1 <= 1'b0;
            vs_start2 <= 1'b0;
            rast_start <= 1'b0;
            shad_start <= 1'b0;
            vs_seen <= 3'b000;
            rast_finished <= 1'b0;
            pending_pixels <= 10'd0;
            gpu_done_reg <= 1'b0;
            draw_error <= 1'b0;
            rast_x0 <= 10'd0;
            rast_y0 <= 10'd0;
            rast_x1 <= 10'd0;
            rast_y1 <= 10'd0;
            rast_x2 <= 10'd0;
            rast_y2 <= 10'd0;
            rast_color0 <= 8'd0;
            rast_color1 <= 8'd0;
            rast_color2 <= 8'd0;
        end else begin
            vs_start0 <= 1'b0;
            vs_start1 <= 1'b0;
            vs_start2 <= 1'b0;
            rast_start <= 1'b0;
            shad_start <= 1'b0;
            gpu_done_reg <= 1'b0;
            case(gpu_state)
                GPU_IDLE:begin
                    if(start && !clear && !clear_busy && !clear_reg)begin
                        vs_seen <= 3'b000;
                        rast_finished <= 1'b0;
                        pending_pixels <= 10'd0;
                        draw_error <= 1'b0;
                        gpu_state <= GPU_VS_START;
                    end
                end
                GPU_VS_START:begin
                    if(!vs_busy0 && !vs_busy1 && !vs_busy2)begin
                        vs_start0 <= 1'b1;
                        vs_start1 <= 1'b1;
                        vs_start2 <= 1'b1;
                        gpu_state <= GPU_VS_WAIT;
                    end
                end
                GPU_VS_WAIT:begin
                    vs_seen <= vs_seen_next;
                    if(&vs_seen_next)begin
                        gpu_state <= GPU_CHECK;
                    end
                end
                GPU_CHECK:begin
                    if(vs_error_any || !screen_valid)begin
                        draw_error <= 1'b1;
                        gpu_state <= GPU_DONE;
                    end else begin
                        gpu_state <= GPU_LOAD;
                    end
                end
                GPU_LOAD:begin
                    rast_x0 <= screen_x0[21:12];
                    rast_y0 <= screen_y0[21:12];
                    rast_x1 <= screen_x1[21:12];
                    rast_y1 <= screen_y1[21:12];
                    rast_x2 <= screen_x2[21:12];
                    rast_y2 <= screen_y2[21:12];
                    rast_color0 <= screen_color0;
                    rast_color1 <= screen_color1;
                    rast_color2 <= screen_color2;
                    gpu_state <= GPU_RAST_START;
                end
                GPU_RAST_START:begin
                    if(!rast_busy && rast_valid)begin
                        rast_start <= 1'b1;
                        shad_start <= 1'b1;
                        gpu_state <= GPU_DRAW_WAIT;
                    end
                end
                GPU_DRAW_WAIT:begin
                    if(rast_done)begin
                        rast_finished <= 1'b1;
                    end
                    case({fifo_rs_wen,shad_done})
                        2'b10: pending_pixels <= pending_pixels + 10'd1;
                        2'b01: pending_pixels <= pending_pixels - 10'd1;
                        default: pending_pixels <= pending_pixels;
                    endcase
                    if(rast_finished && pending_pixels == 0 && fifo_rs_empty && !fifo_rs_wen && !shad_done)begin
                        gpu_state <= GPU_DONE;
                    end
                end
                GPU_DONE:begin
                    gpu_done_reg <= 1'b1;
                    gpu_state <= GPU_IDLE;
                end
                default:begin
                    draw_error <= 1'b1;
                    gpu_state <= GPU_DONE;
                end
            endcase
        end
    end

    vertex_shader u_vertex_shader0(
        .clk          (clk          ),
        .rst          (rst          ),
        .vs_start     (vs_start0     ),
        .vertex_x     (vertex_x0     ),
        .vertex_y     (vertex_y0     ),
        .vertex_z     (vertex_z0     ),
        .vertex_color (vertex_color0 ),
        .m00          (m00          ),
        .m01          (m01          ),
        .m02          (m02          ),
        .m03          (m03          ),
        .m10          (m10          ),
        .m11          (m11          ),
        .m12          (m12          ),
        .m13          (m13          ),
        .m20          (m20          ),
        .m21          (m21          ),
        .m22          (m22          ),
        .m23          (m23          ),
        .m30          (m30          ),
        .m31          (m31          ),
        .m32          (m32          ),
        .m33          (m33          ),
        .screen_x     (screen_x0     ),
        .screen_y     (screen_y0     ),
        .screen_z     (screen_z0     ),
        .screen_color (screen_color0 ),
        .vs_busy      (vs_busy0      ),
        .vs_done      (vs_done0      ),
        .vs_error     (vs_error0     )
    );
    vertex_shader u_vertex_shader1(
        .clk          (clk          ),
        .rst          (rst          ),
        .vs_start     (vs_start1     ),
        .vertex_x     (vertex_x1     ),
        .vertex_y     (vertex_y1     ),
        .vertex_z     (vertex_z1     ),
        .vertex_color (vertex_color1 ),
        .m00          (m00          ),
        .m01          (m01          ),
        .m02          (m02          ),
        .m03          (m03          ),
        .m10          (m10          ),
        .m11          (m11          ),
        .m12          (m12          ),
        .m13          (m13          ),
        .m20          (m20          ),
        .m21          (m21          ),
        .m22          (m22          ),
        .m23          (m23          ),
        .m30          (m30          ),
        .m31          (m31          ),
        .m32          (m32          ),
        .m33          (m33          ),
        .screen_x     (screen_x1     ),
        .screen_y     (screen_y1     ),
        .screen_z     (screen_z1     ),
        .screen_color (screen_color1 ),
        .vs_busy      (vs_busy1      ),
        .vs_done      (vs_done1      ),
        .vs_error     (vs_error1     )
    );
    vertex_shader u_vertex_shader2(
        .clk          (clk          ),
        .rst          (rst          ),
        .vs_start     (vs_start2     ),
        .vertex_x     (vertex_x2     ),
        .vertex_y     (vertex_y2     ),
        .vertex_z     (vertex_z2     ),
        .vertex_color (vertex_color2 ),
        .m00          (m00          ),
        .m01          (m01          ),
        .m02          (m02          ),
        .m03          (m03          ),
        .m10          (m10          ),
        .m11          (m11          ),
        .m12          (m12          ),
        .m13          (m13          ),
        .m20          (m20          ),
        .m21          (m21          ),
        .m22          (m22          ),
        .m23          (m23          ),
        .m30          (m30          ),
        .m31          (m31          ),
        .m32          (m32          ),
        .m33          (m33          ),
        .screen_x     (screen_x2     ),
        .screen_y     (screen_y2     ),
        .screen_z     (screen_z2     ),
        .screen_color (screen_color2 ),
        .vs_busy      (vs_busy2      ),
        .vs_done      (vs_done2      ),
        .vs_error     (vs_error2     )
    );


    rasterizer u_rasterizer(
        .clk         (clk         ),
        .rst         (rst         ),
        .rast_start  (rast_start  ),
        .rast_valid  (rast_valid  ),
        .x0          (rast_x0     ),
        .y0          (rast_y0     ),
        .x1          (rast_x1     ),
        .y1          (rast_y1     ),
        .x2          (rast_x2     ),
        .y2          (rast_y2     ),
        .clor0       (rast_color0 ),
        .clor1       (rast_color1 ),
        .clor2       (rast_color2 ),
        .frag_x      (frag_x      ),
        .frag_y      (frag_y      ),
        .frag_clor_R (frag_clor_R ),
        .frag_clor_G (frag_clor_G ),
        .frag_clor_B (frag_clor_B ),
        .frag_valid  (frag_valid  ),
        .rast_busy   (rast_busy   ),
        .rast_done   (rast_done   )
    );

    fifo#(
        .DEPTH(256),
        .DEPTH_BITS(8),
        .WIDTH(28)
    ) rast_shad_fifo (
        .clk            (clk                        ),
        .rst            (rst                        ),
        .w_data         (fifo_rs_wdata              ),
        .w_en           (fifo_rs_wen                ),
        .r_en           (fifo_rs_ren                ),
        .r_valid        (fifo_rs_rvalid             ),
        .r_data         (fifo_rs_rdata              ),
        .empty          (fifo_rs_empty              ),
        .full           (fifo_rs_full               )
    );


    reg shad_start;
    wire shad_done;
    wire shad_busy;
    wire [9:0] pixel_x;
    wire [9:0] pixel_y;
    wire [2:0] pixel_R;
    wire [2:0] pixel_G;
    wire [1:0] pixel_B;
    shader u_shader(
        .clk             (clk             ),
        .rst             (rst             ),
        .fifo_empty      (fifo_rs_empty  ),
        .read_fifo_data  (fifo_rs_rdata  ),
        .read_fifo_en    (fifo_rs_ren    ),
        .read_fifo_valid (fifo_rs_rvalid ),
        .shad_start      (shad_start      ),
        .shad_busy       (shad_busy       ),
        .shad_done       (shad_done       ),
        .pixel_x         (pixel_x         ),
        .pixel_y         (pixel_y         ),
        .pixel_R         (pixel_R         ),
        .pixel_G         (pixel_G         ),
        .pixel_B         (pixel_B         )
    );
    reg [31:0]   clear_count;
    reg         clear_reg;
    reg         clear_busy;

    always @(posedge clk) begin
        if(rst)begin
            clear_reg <= 1'b0;
            clear_busy <= 1'b0;
            clear_count <= 1'b0;
        end else if(clear_accept)begin
            clear_reg <= 1'b1;
            clear_busy <= 1'b1;
        end else if(shad_done || clear_reg)begin
            frame_buffer[clear_reg ? clear_count[FB_ADDR_W-1:0] : pixel_addr(pixel_x,pixel_y)] <= clear_reg ? clear_color : {pixel_R,pixel_G,pixel_B};
            if(clear_reg)begin
                if(clear_count < FB_PIXELS-1)begin
                    clear_count <= clear_count + 1'b1;
                end else begin
                    clear_count <= 1'b0;
                    clear_reg <= 1'b0;
                    clear_busy <= 1'b0;
                end
            end
        end
    end

    wire [18:0] vga_fb_addr;
    wire        vga_fb_read_en;
    reg  [7:0]  vga_fb_data;

    always @(posedge vga_clk) begin
        if (vga_fb_read_en)
            vga_fb_data <= frame_buffer[vga_fb_addr];
    end

    vga u_vga (
        .clk        (vga_clk),
        .rst        (vga_rst),
        .fb_addr    (vga_fb_addr),
        .fb_read_en (vga_fb_read_en),
        .fb_data    (vga_fb_data),
        .vga_r      (vga_r),
        .vga_g      (vga_g),
        .vga_b      (vga_b),
        .vga_hs     (vga_hs),
        .vga_vs     (vga_vs)
    );

endmodule
