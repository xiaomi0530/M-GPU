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

            r8 = (clamp_R * 7) >> 12;
            g8 = (clamp_G * 7) >> 12;
            b8 = (clamp_B * 3) >> 12;

            Q312_to_RGB332 = {r8,g8,b8};

        end 
    endfunction

    
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

    always@(posedge clk)begin
        if(rst)begin
            
        end else begin
            if(frag_valid)begin
                frame_buffer[pixel_addr(frag_x,frag_y)] <= Q312_to_RGB332(frag_clor_R,frag_clor_G,frag_clor_B);
            end
        end
    end
    
    
endmodule
