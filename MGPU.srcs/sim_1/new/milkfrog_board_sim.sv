`timescale 1ns / 1ps

module milkfrog_board_sim #(
    parameter int GPU_CLK_DIV_LOG2 = 1,
    parameter int TARGET_FPS = 0
)(
    input logic clk,
    input logic reset_n,
    input logic button,
    input logic [16:0] read_addr,
    output logic [7:0] read_data,
    output logic frame_complete,
    output logic [15:0] completed_frame,
    output logic front_bank,
    output logic error_latched,
    output logic [31:0] gpu_cycles,
    output logic [31:0] draw_cycles,
    output logic [31:0] issue_count,
    output logic [31:0] pixel_writes,
    output logic [9:0] pending_pixels,
    output logic fifo_empty,
    output logic paused,
    output logic holding,
    output logic [15:0] animation_length
);

    `include "milkfrog_config.svh"

    logic [31:0] frame_started;
    logic previous_drawn;

    assign read_data = u_milkfrog_top.u_mgpu.front_bank ?
        u_milkfrog_top.u_mgpu.frame_buffer1[read_addr] : u_milkfrog_top.u_mgpu.frame_buffer0[read_addr];
    assign frame_complete = u_milkfrog_top.frame_complete;
    assign completed_frame = u_milkfrog_top.completed_frame;
    assign front_bank = u_milkfrog_top.u_mgpu.front_bank;
    assign error_latched = u_milkfrog_top.error_latched;
    assign pending_pixels = u_milkfrog_top.u_mgpu.pending_pixels;
    assign fifo_empty = u_milkfrog_top.u_mgpu.fifo_rs_empty;
    assign paused = u_milkfrog_top.paused;
    assign holding = u_milkfrog_top.frame_holding;
    assign animation_length = FRAME_COUNT;

    always_ff@(posedge u_milkfrog_top.gpu_clk)begin
        if(u_milkfrog_top.rst)begin
            gpu_cycles <= 0;
            draw_cycles <= 0;
            frame_started <= 0;
            previous_drawn <= 1'b0;
            issue_count <= 0;
            pixel_writes <= 0;
        end else begin
            gpu_cycles <= gpu_cycles + 1'b1;
            if(u_milkfrog_top.demo_clear) frame_started <= gpu_cycles;
            previous_drawn <= u_milkfrog_top.frame_drawn;
            if(u_milkfrog_top.frame_drawn && !previous_drawn) draw_cycles <= gpu_cycles - frame_started;
            if(u_milkfrog_top.demo_start) issue_count <= issue_count + 1'b1;
            if(u_milkfrog_top.u_mgpu.shad_done) pixel_writes <= pixel_writes + 1'b1;
        end
    end

    milkfrog_top

    #(
        .GPU_CLK_DIV_LOG2 (GPU_CLK_DIV_LOG2),
        .TARGET_FPS       (TARGET_FPS      )
    )
    u_milkfrog_top(
        .CLK100MHZ  (clk    ),
        .CPU_RESETN (reset_n),
        .BTNU       (button ),
        .VGA_R      (       ),
        .VGA_G      (       ),
        .VGA_B      (       ),
        .VGA_HS     (       ),
        .VGA_VS     (       )
    );

endmodule

module BUFG(
    input logic I,
    output logic O
);

    assign O = I;

endmodule
