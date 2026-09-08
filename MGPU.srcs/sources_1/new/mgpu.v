`timescale 1ns / 1ps

module mgpu #(
    parameter H_RES = 640,
    parameter V_RES = 480,
    parameter FB_PIXELS = H_RES * V_RES,
    parameter FB_ADDR_W = 19
)(
    input  wire       clk,
    input  wire       rst,
    input  wire       start,
    input  wire [9:0] x0,
    input  wire [9:0] y0,
    input  wire [9:0] x1,
    input  wire [9:0] y1,
    input  wire [9:0] x2,
    input  wire [9:0] y2,
    input  wire [7:0] clor0, 
    input  wire [7:0] clor1, 
    input  wire [7:0] clor2, 
    input  wire [7:0] clear_color,
    output wire        busy,
    output wire        done
);
    reg [7:0] frame_buffer [0:FB_PIXELS-1];

    integer i;
    initial begin
        for(i=0;i<=FB_PIXELS-1;i=i+1)begin
            frame_buffer[i] <= clear_color;
        end
    end
    
    wire        rast_start;
    wire        rast_valid;
    wire        rast_done;
    wire        rast_busy;
    
    wire  [9:0]  frag_x;
    wire  [9:0]  frag_y;
    wire  [31:0] frag_clor_R;
    wire  [31:0] frag_clor_G;
    wire  [31:0] frag_clor_B;
    wire         frag_valid;

    assign rast_start = start;
    assign rast_valid = 1'b1;
    assign busy = rast_busy;
    assign done = rast_done;
    
    rasterizer u_rasterizer(
        .clk         (clk         ),
        .rst         (rst         ),
        .rast_start  (rast_start  ),
        .rast_valid  (rast_valid  ),
        .x0          (x0          ),
        .y0          (y0          ),
        .x1          (x1          ),
        .y1          (y1          ),
        .x2          (x2          ),
        .y2          (y2          ),
        .clor0       (clor0       ),
        .clor1       (clor1       ),
        .clor2       (clor2       ),
        .frag_x      (frag_x      ),
        .frag_y      (frag_y      ),
        .frag_clor_R (frag_clor_R ),
        .frag_clor_G (frag_clor_G ),
        .frag_clor_B (frag_clor_B ),
        .frag_valid  (frag_valid  ),
        .rast_busy   (rast_busy   ),
        .rast_done   (rast_done   )
    );
    
    
endmodule
