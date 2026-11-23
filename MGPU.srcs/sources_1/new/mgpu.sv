module mgpu #(
    parameter int H_RES = 640,
    parameter int V_RES = 480,
    parameter int FB_PIXELS = H_RES * V_RES,
    parameter int FB_ADDR_W = 19
)(
    input logic clk,
    input logic rst,
    input logic start,
    input logic clear,
    input logic present,
    output logic present_done,
    input logic signed [17:0] vertex_x0,
    input logic signed [17:0] vertex_y0,
    input logic signed [17:0] vertex_z0,
    input logic [7:0] vertex_color0,
    input logic signed [17:0] vertex_x1,
    input logic signed [17:0] vertex_y1,
    input logic signed [17:0] vertex_z1,
    input logic [7:0] vertex_color1,
    input logic signed [17:0] vertex_x2,
    input logic signed [17:0] vertex_y2,
    input logic signed [17:0] vertex_z2,
    input logic [7:0] vertex_color2,
    input logic signed [17:0] m00,
    input logic signed [17:0] m01,
    input logic signed [17:0] m02,
    input logic signed [17:0] m03,
    input logic signed [17:0] m10,
    input logic signed [17:0] m11,
    input logic signed [17:0] m12,
    input logic signed [17:0] m13,
    input logic signed [17:0] m20,
    input logic signed [17:0] m21,
    input logic signed [17:0] m22,
    input logic signed [17:0] m23,
    input logic signed [17:0] m30,
    input logic signed [17:0] m31,
    input logic signed [17:0] m32,
    input logic signed [17:0] m33,
    input logic [7:0] clear_color,
    output logic gpu_busy,
    output logic gpu_done,
    output logic gpu_error,
    input logic vga_clk,
    input logic vga_rst,
    output logic [3:0] vga_r,
    output logic [3:0] vga_g,
    output logic [3:0] vga_b,
    output logic vga_hs,
    output logic vga_vs
);

    typedef enum logic [2:0]{
        GPU_IDLE,
        GPU_VS_START,
        GPU_VS_WAIT,
        GPU_CHECK,
        GPU_LOAD,
        GPU_RAST_START,
        GPU_DRAW_WAIT,
        GPU_DONE
    } state_t;
    state_t state;

    localparam signed [31:0] SCREEN_X_LIMIT = H_RES * 4096;
    localparam signed [31:0] SCREEN_Y_LIMIT = V_RES * 4096;

    (* ram_style = "block" *) logic [7:0] frame_buffer0[0:FB_PIXELS-1];
    (* ram_style = "block" *) logic [7:0] frame_buffer1[0:FB_PIXELS-1];
    integer i;
    logic [2:0] vs_seen;
    logic [9:0] pending_pixels;
    logic gpu_done_reg;
    logic draw_error;
    logic vs_start0;
    logic vs_start1;
    logic vs_start2;
    logic vs_busy0;
    logic vs_busy1;
    logic vs_busy2;
    logic vs_done0;
    logic vs_done1;
    logic vs_done2;
    logic vs_error0;
    logic vs_error1;
    logic vs_error2;
    logic signed [31:0] screen_x0;
    logic signed [31:0] screen_y0;
    logic signed [31:0] screen_z0;
    logic signed [31:0] screen_x1;
    logic signed [31:0] screen_y1;
    logic signed [31:0] screen_z1;
    logic signed [31:0] screen_x2;
    logic signed [31:0] screen_y2;
    logic signed [31:0] screen_z2;
    logic [7:0] screen_color0;
    logic [7:0] screen_color1;
    logic [7:0] screen_color2;
    logic [9:0] rast_x0;
    logic [9:0] rast_y0;
    logic [9:0] rast_x1;
    logic [9:0] rast_y1;
    logic [9:0] rast_x2;
    logic [9:0] rast_y2;
    logic [7:0] rast_color0;
    logic [7:0] rast_color1;
    logic [7:0] rast_color2;
    logic [2:0] vs_seen_next;
    logic vs_error_any;
    logic screen_valid;
    logic clear_accept;
    logic rast_start;
    logic rast_valid;
    logic rast_done;
    logic rast_busy;
    logic rast_finished;
    logic [9:0] frag_x;
    logic [9:0] frag_y;
    logic [31:0] frag_clor_r;
    logic [31:0] frag_clor_g;
    logic [31:0] frag_clor_b;
    logic frag_valid;
    logic [27:0] fifo_rs_wdata;
    logic fifo_rs_wen;
    logic fifo_rs_ren;
    logic [27:0] fifo_rs_rdata;
    logic fifo_rs_rvalid;
    logic fifo_rs_empty;
    logic fifo_rs_full;
    logic shad_start;
    logic shad_done;
    logic shad_busy;
    logic [9:0] pixel_x;
    logic [9:0] pixel_y;
    logic [2:0] pixel_r;
    logic [2:0] pixel_g;
    logic [1:0] pixel_b;
    logic [31:0] clear_count;
    logic clear_reg;
    logic clear_busy;
    logic front_bank;
    logic back_bank;
    logic swap_req;
    logic swap_pending;
    logic vblank_start;
    (* ASYNC_REG = "TRUE" *) logic [1:0] req_sync;
    (* ASYNC_REG = "TRUE" *) logic [1:0] ack_sync;
    logic [18:0] vga_fb_addr;
    logic vga_fb_read_en;
    logic [7:0] vga_fb_data;
    logic [7:0] vga_fb_data0;
    logic [7:0] vga_fb_data1;

    initial begin
        for(i = 0; i <= FB_PIXELS - 1; i = i + 1)begin
            frame_buffer0[i] <= 8'h00;
            frame_buffer1[i] <= 8'h00;
        end
    end

    function [18:0] pixel_addr;
        input logic [9:0] x;
        input logic [9:0] y;
        begin
            pixel_addr = y * H_RES + x;
        end
    endfunction

    function [7:0] q312_to_rgb332;
        input logic signed [31:0] r;
        input logic signed [31:0] g;
        input logic signed [31:0] b;

        logic [2:0] r8;
        logic [2:0] g8;
        logic [1:0] b8;

        logic signed [31:0] clamp_r;
        logic signed [31:0] clamp_g;
        logic signed [31:0] clamp_b;
        begin
            if(r < 0)begin
                clamp_r = 0;
            end else if(r > 4096)begin
                clamp_r = 4096;
            end else begin
                clamp_r = r;
            end
            if(g < 0)begin
                clamp_g = 0;
            end else if(g > 4096)begin
                clamp_g = 4096;
            end else begin
                clamp_g = g;
            end
            if(b < 0)begin
                clamp_b = 0;
            end else if(b > 4096)begin
                clamp_b = 4096;
            end else begin
                clamp_b = b;
            end

            r8 = (clamp_r * 7 + 2048) >> 12;
            g8 = (clamp_g * 7 + 2048) >> 12;
            b8 = (clamp_b * 3 + 2048) >> 12;

            q312_to_rgb332 = {r8, g8, b8};

        end
    endfunction

    function screen_inside;
        input logic signed [31:0] x, y, z;
        begin
            screen_inside = (x >= 0) && (x < SCREEN_X_LIMIT) &&
                            (y >= 0) && (y < SCREEN_Y_LIMIT) &&
                            (z >= 0) && (z <= 32'sd4096);
        end
    endfunction

    assign vs_seen_next = vs_seen | {vs_done2, vs_done1, vs_done0};
    assign vs_error_any = vs_error0 | vs_error1 | vs_error2;
    assign screen_valid = screen_inside(
        screen_x0, screen_y0, screen_z0
    ) && screen_inside(
        screen_x1, screen_y1, screen_z1
    ) && screen_inside(
        screen_x2, screen_y2, screen_z2
    );
    assign clear_accept = clear && !rst && (state == GPU_IDLE) && !clear_busy && !clear_reg && !swap_pending;
    assign gpu_busy = (state != GPU_IDLE) || clear_busy || clear_reg || swap_pending;
    assign gpu_done = gpu_done_reg;
    assign gpu_error = draw_error;

    assign rast_valid = !fifo_rs_full;

    assign fifo_rs_wdata = {frag_x, frag_y, q312_to_rgb332(frag_clor_r, frag_clor_g, frag_clor_b)};
    assign fifo_rs_wen = (state == GPU_DRAW_WAIT) && !rst && frag_valid && rast_valid;

    always_ff@(posedge clk)begin
        if(rst)begin
            state <= GPU_IDLE;
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
            case(state)
                GPU_IDLE:begin
                    if(start && !clear && !clear_busy && !clear_reg && !swap_pending)begin
                        vs_seen <= 3'b000;
                        rast_finished <= 1'b0;
                        pending_pixels <= 10'd0;
                        draw_error <= 1'b0;
                        state <= GPU_VS_START;
                    end
                end
                GPU_VS_START:begin
                    if(!vs_busy0 && !vs_busy1 && !vs_busy2)begin
                        vs_start0 <= 1'b1;
                        vs_start1 <= 1'b1;
                        vs_start2 <= 1'b1;
                        state <= GPU_VS_WAIT;
                    end
                end
                GPU_VS_WAIT:begin
                    vs_seen <= vs_seen_next;
                    if(&vs_seen_next)begin
                        state <= GPU_CHECK;
                    end
                end
                GPU_CHECK:begin
                    if(vs_error_any || !screen_valid)begin
                        draw_error <= 1'b1;
                        state <= GPU_DONE;
                    end else begin
                        state <= GPU_LOAD;
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
                    state <= GPU_RAST_START;
                end
                GPU_RAST_START:begin
                    if(!rast_busy && rast_valid)begin
                        rast_start <= 1'b1;
                        shad_start <= 1'b1;
                        state <= GPU_DRAW_WAIT;
                    end
                end
                GPU_DRAW_WAIT:begin
                    if(rast_done)begin
                        rast_finished <= 1'b1;
                    end
                    case({
                        fifo_rs_wen, shad_done
                    })
                        2'b10:begin
                            pending_pixels <= pending_pixels + 10'd1;
                        end
                        2'b01:begin
                            pending_pixels <= pending_pixels - 10'd1;
                        end
                        default:begin
                            pending_pixels <= pending_pixels;
                        end
                    endcase
                    if(rast_finished && pending_pixels == 0 && fifo_rs_empty && !fifo_rs_wen && !shad_done)begin
                        state <= GPU_DONE;
                    end
                end
                GPU_DONE:begin
                    gpu_done_reg <= 1'b1;
                    state <= GPU_IDLE;
                end
                default:begin
                    draw_error <= 1'b1;
                    state <= GPU_DONE;
                end
            endcase
        end
    end

    vertex_shader

    #(
        .H_RES (H_RES),
        .V_RES (V_RES)
    )
    u_vertex_shader0(
        .clk          (clk          ),
        .rst          (rst          ),
        .vs_start     (vs_start0    ),
        .vertex_x     (vertex_x0    ),
        .vertex_y     (vertex_y0    ),
        .vertex_z     (vertex_z0    ),
        .vertex_color (vertex_color0),
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
        .screen_x     (screen_x0    ),
        .screen_y     (screen_y0    ),
        .screen_z     (screen_z0    ),
        .screen_color (screen_color0),
        .vs_busy      (vs_busy0     ),
        .vs_done      (vs_done0     ),
        .vs_error     (vs_error0    )
    );
    vertex_shader
    #(
        .H_RES (H_RES),
        .V_RES (V_RES)
    )
    u_vertex_shader1(
        .clk          (clk          ),
        .rst          (rst          ),
        .vs_start     (vs_start1    ),
        .vertex_x     (vertex_x1    ),
        .vertex_y     (vertex_y1    ),
        .vertex_z     (vertex_z1    ),
        .vertex_color (vertex_color1),
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
        .screen_x     (screen_x1    ),
        .screen_y     (screen_y1    ),
        .screen_z     (screen_z1    ),
        .screen_color (screen_color1),
        .vs_busy      (vs_busy1     ),
        .vs_done      (vs_done1     ),
        .vs_error     (vs_error1    )
    );
    vertex_shader
    #(
        .H_RES (H_RES),
        .V_RES (V_RES)
    )
    u_vertex_shader2(
        .clk          (clk          ),
        .rst          (rst          ),
        .vs_start     (vs_start2    ),
        .vertex_x     (vertex_x2    ),
        .vertex_y     (vertex_y2    ),
        .vertex_z     (vertex_z2    ),
        .vertex_color (vertex_color2),
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
        .screen_x     (screen_x2    ),
        .screen_y     (screen_y2    ),
        .screen_z     (screen_z2    ),
        .screen_color (screen_color2),
        .vs_busy      (vs_busy2     ),
        .vs_done      (vs_done2     ),
        .vs_error     (vs_error2    )
    );

    rasterizer u_rasterizer (
        .clk         (clk        ),
        .rst         (rst        ),
        .rast_start  (rast_start ),
        .rast_valid  (rast_valid ),
        .x0          (rast_x0    ),
        .y0          (rast_y0    ),
        .x1          (rast_x1    ),
        .y1          (rast_y1    ),
        .x2          (rast_x2    ),
        .y2          (rast_y2    ),
        .clor0       (rast_color0),
        .clor1       (rast_color1),
        .clor2       (rast_color2),
        .frag_x      (frag_x     ),
        .frag_y      (frag_y     ),
        .frag_clor_r (frag_clor_r),
        .frag_clor_g (frag_clor_g),
        .frag_clor_b (frag_clor_b),
        .frag_valid  (frag_valid ),
        .rast_busy   (rast_busy  ),
        .rast_done   (rast_done  )
    );

    fifo

    #(
        .DEPTH      (256),
        .DEPTH_BITS (8  ),
        .WIDTH      (28 )
    )
    rast_shad_fifo(
        .clk     (clk           ),
        .rst     (rst           ),
        .w_data  (fifo_rs_wdata ),
        .w_en    (fifo_rs_wen   ),
        .r_en    (fifo_rs_ren   ),
        .r_valid (fifo_rs_rvalid),
        .r_data  (fifo_rs_rdata ),
        .empty   (fifo_rs_empty ),
        .full    (fifo_rs_full  )
    );

    shader u_shader (
        .clk             (clk           ),
        .rst             (rst           ),
        .fifo_empty      (fifo_rs_empty ),
        .read_fifo_data  (fifo_rs_rdata ),
        .read_fifo_en    (fifo_rs_ren   ),
        .read_fifo_valid (fifo_rs_rvalid),
        .shad_start      (shad_start    ),
        .shad_busy       (shad_busy     ),
        .shad_done       (shad_done     ),
        .pixel_x         (pixel_x       ),
        .pixel_y         (pixel_y       ),
        .pixel_r         (pixel_r       ),
        .pixel_g         (pixel_g       ),
        .pixel_b         (pixel_b       )
    );

    always_ff@(posedge clk)begin
        if(rst)begin
            clear_reg <= 1'b0;
            clear_busy <= 1'b0;
            clear_count <= 1'b0;
        end else if(clear_accept)begin
            clear_reg <= 1'b1;
            clear_busy <= 1'b1;
        end else if(!swap_pending && (shad_done || clear_reg))begin
            if(back_bank)begin
                frame_buffer1[clear_reg ? clear_count[FB_ADDR_W-1:0] : pixel_addr(pixel_x, pixel_y)] <= clear_reg ?
                    clear_color : {pixel_r, pixel_g, pixel_b};
            end else begin
                frame_buffer0[clear_reg ? clear_count[FB_ADDR_W-1:0] : pixel_addr(pixel_x, pixel_y)] <= clear_reg ?
                    clear_color : {pixel_r, pixel_g, pixel_b};
            end
            if(clear_reg)begin
                if(clear_count < FB_PIXELS - 1)begin
                    clear_count <= clear_count + 1'b1;
                end else begin
                    clear_count <= 1'b0;
                    clear_reg <= 1'b0;
                    clear_busy <= 1'b0;
                end
            end
        end
    end

    always_ff@(posedge clk)begin
        if(rst)begin
            back_bank <= 1'b1;
            swap_req <= 1'b0;
            swap_pending <= 1'b0;
            ack_sync <= 2'b00;
            present_done <= 1'b0;
        end else begin
            ack_sync <= {ack_sync[0], front_bank};
            present_done <= 1'b0;

            if(present && !gpu_busy && !swap_pending)begin
                swap_req <= ~swap_req;
                swap_pending <= 1'b1;
            end else if(swap_pending && ack_sync[1] == swap_req)begin
                back_bank <= ~back_bank;
                swap_pending <= 1'b0;
                present_done <= 1'b1;
            end
        end
    end

    assign vga_fb_data = front_bank ? vga_fb_data1 : vga_fb_data0;

    always_ff@(posedge vga_clk)begin
        if(vga_fb_read_en)begin
            if(front_bank)begin
                vga_fb_data1 <= frame_buffer1[vga_fb_addr];
            end else begin
                vga_fb_data0 <= frame_buffer0[vga_fb_addr];
            end
        end
    end

    always_ff@(posedge vga_clk)begin
        if(vga_rst)begin
            front_bank <= 1'b0;
            req_sync <= 2'b00;
        end else begin
            req_sync <= {req_sync[0], swap_req};
            if(vblank_start && req_sync[1] != front_bank)begin
                front_bank <= req_sync[1];
            end
        end
    end

    vga

    #(
        .FB_WIDTH  (H_RES),
        .FB_HEIGHT (V_RES)
    )
    u_vga(
        .clk          (vga_clk       ),
        .rst          (vga_rst       ),
        .fb_addr      (vga_fb_addr   ),
        .fb_read_en   (vga_fb_read_en),
        .fb_data      (vga_fb_data   ),
        .vga_r        (vga_r         ),
        .vga_g        (vga_g         ),
        .vga_b        (vga_b         ),
        .vga_hs       (vga_hs        ),
        .vga_vs       (vga_vs        ),
        .vblank_start (vblank_start  )
    );

endmodule
