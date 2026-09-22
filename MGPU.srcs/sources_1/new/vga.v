`timescale 1ns / 1ps

// Nexys A7 manual, section 8: 640x480, 25 MHz pixel rate.
// Run from the board's 100 MHz clock; GPU writes can use a slower clock.
// This module uses clock enables, not a separate 25 MHz clock.
// The framebuffer interface requires a one-clock synchronous read.
module vga (
    input  wire        clk,
    input  wire        rst,
    output wire [18:0] fb_addr,
    output wire        fb_read_en,
    input  wire [7:0]  fb_data,
    output reg  [3:0]  vga_r,
    output reg  [3:0]  vga_g,
    output reg  [3:0]  vga_b,
    output reg         vga_hs,
    output reg         vga_vs
);
    localparam H_ACTIVE = 640;
    localparam H_FRONT  = 16;
    localparam H_SYNC   = 96;
    localparam H_BACK   = 48;
    localparam H_TOTAL  = H_ACTIVE + H_FRONT + H_SYNC + H_BACK;
    localparam V_ACTIVE = 480;
    localparam V_FRONT  = 10;
    localparam V_SYNC   = 2;
    // Manual Fig. 8.1.3 specifies 29 back-porch lines, 521 total.
    // At 25 MHz this is 59.98 Hz (not the 25.175 MHz / 525-line mode).
    localparam V_BACK   = 29;
    localparam V_TOTAL  = V_ACTIVE + V_FRONT + V_SYNC + V_BACK;

    reg [1:0] phase;
    reg [9:0] scan_x;
    reg [9:0] scan_y;
    wire active = (scan_x < H_ACTIVE) && (scan_y < V_ACTIVE);
    wire [18:0] row_y = {9'b0, scan_y};

    // Keep the address in range even during blanking.
    assign fb_addr = active ? ((row_y << 9) + (row_y << 7)
                              + {9'b0, scan_x}) : 19'd0;
    assign fb_read_en = !rst && active && (phase == 2'd0);

    always @(posedge clk) begin
        if (rst) begin
            phase  <= 2'd0;
            scan_x <= 10'd0;
            scan_y <= 10'd0;
            vga_r  <= 4'd0;
            vga_g  <= 4'd0;
            vga_b  <= 4'd0;
            vga_hs <= 1'b1;
            vga_vs <= 1'b1;
        end else begin
            phase <= phase + 1'b1;

            // Phase 0: external memory captures fb_addr.
            // Phase 1: capture the returned byte AND its matching syncs.
            // Outputs then remain stable for a full 40 ns pixel interval.
            if (phase == 2'd1) begin
                vga_hs <= !((scan_x >= H_ACTIVE + H_FRONT) &&
                            (scan_x < H_ACTIVE + H_FRONT + H_SYNC));
                vga_vs <= !((scan_y >= V_ACTIVE + V_FRONT) &&
                            (scan_y < V_ACTIVE + V_FRONT + V_SYNC));
                if (active) begin
                    // Bit replication preserves black and full-scale white.
                    // The stored pixel remains RGB332, with only 256 colors.
                    vga_r <= {fb_data[7:5], fb_data[7]};
                    vga_g <= {fb_data[4:2], fb_data[4]};
                    vga_b <= {fb_data[1:0], fb_data[1:0]};
                end else begin
                    vga_r <= 4'd0;
                    vga_g <= 4'd0;
                    vga_b <= 4'd0;
                end
            end

            if (phase == 2'd3) begin
                if (scan_x == H_TOTAL - 1) begin
                    scan_x <= 10'd0;
                    if (scan_y == V_TOTAL - 1)
                        scan_y <= 10'd0;
                    else
                        scan_y <= scan_y + 1'b1;
                end else begin
                    scan_x <= scan_x + 1'b1;
                end
            end
        end
    end
endmodule
