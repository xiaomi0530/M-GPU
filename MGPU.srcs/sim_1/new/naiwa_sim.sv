`timescale 1ns / 1ps

module naiwa_sim(
    input logic clk,
    input logic rst,
    input logic start,
    input logic clear,
    input logic [7:0] clear_color,
    input logic present,
    input logic vga_clk,
    input logic vga_rst,
    input logic [16:0] read_addr,
    output logic [7:0] read_data,
    output logic front_bank,
    output logic gpu_busy,
    output logic gpu_done,
    output logic gpu_error,
    output logic present_done,
    output logic [31:0] pixel_writes,
    output logic [31:0] fragment_writes,
    output logic [9:0] pending_pixels,
    output logic fifo_empty,
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
    input logic signed [17:0] m33
);

    assign read_data = u_mgpu.front_bank ? u_mgpu.frame_buffer1[read_addr] : u_mgpu.frame_buffer0[read_addr];
    assign front_bank = u_mgpu.front_bank;
    assign pending_pixels = u_mgpu.pending_pixels;
    assign fifo_empty = u_mgpu.fifo_rs_empty;

    always_ff@(posedge clk)begin
        if(rst)begin
            pixel_writes <= 32'd0;
            fragment_writes <= 32'd0;
        end else if(u_mgpu.shad_done)begin
            pixel_writes <= pixel_writes + 1'b1;
        end
        if(!rst && u_mgpu.fifo_rs_wen && !u_mgpu.fifo_rs_full)begin
            fragment_writes <= fragment_writes + 1'b1;
        end
    end

    mgpu

    #(
        .H_RES (320),
        .V_RES (240)
    )
    u_mgpu(
        .clk           (clk          ),
        .rst           (rst          ),
        .start         (start        ),
        .clear         (clear        ),
        .present       (present      ),
        .present_done  (present_done ),
        .vga_clk       (vga_clk      ),
        .vga_rst       (vga_rst      ),
        .gpu_busy      (gpu_busy     ),
        .gpu_done      (gpu_done     ),
        .gpu_error     (gpu_error    ),
        .vertex_x0     (vertex_x0    ),
        .vertex_y0     (vertex_y0    ),
        .vertex_z0     (vertex_z0    ),
        .vertex_color0 (vertex_color0),
        .vertex_x1     (vertex_x1    ),
        .vertex_y1     (vertex_y1    ),
        .vertex_z1     (vertex_z1    ),
        .vertex_color1 (vertex_color1),
        .vertex_x2     (vertex_x2    ),
        .vertex_y2     (vertex_y2    ),
        .vertex_z2     (vertex_z2    ),
        .vertex_color2 (vertex_color2),
        .m00           (m00          ),
        .m01           (m01          ),
        .m02           (m02          ),
        .m03           (m03          ),
        .m10           (m10          ),
        .m11           (m11          ),
        .m12           (m12          ),
        .m13           (m13          ),
        .m20           (m20          ),
        .m21           (m21          ),
        .m22           (m22          ),
        .m23           (m23          ),
        .m30           (m30          ),
        .m31           (m31          ),
        .m32           (m32          ),
        .m33           (m33          ),
        .clear_color   (clear_color  ),
        .vga_r         (             ),
        .vga_g         (             ),
        .vga_b         (             ),
        .vga_hs        (             ),
        .vga_vs        (             )
    );

endmodule
