`timescale 1ns/1ps

module regs#(
    parameter WIDTH = 28,
    parameter DEPTH = 8,
    parameter DEPTH_BITS = 3
)(
    input  wire                     clk,
    input  wire                     rst,
    input  wire                     w_en,
    input  wire [DEPTH_BITS-1:0]    w_addr,
    input  wire [WIDTH-1:0]         w_data,
    input  wire                     r_en,
    input  wire [DEPTH_BITS-1:0]    r_addr,
    output reg  [WIDTH-1:0]         r_data
);

    reg [WIDTH-1:0] regs [0:DEPTH-1];

    always @(posedge clk) begin
        if(rst)begin
            r_data <= 1'b0;
            regs[0] <= 1'b0;
        end else begin
            if(r_en)begin
                r_data <= regs[r_addr];
            end else begin
                r_data <= 1'b0;
            end
            if(w_en && w_addr!=1'b0)begin
                regs[w_addr] = w_data;
            end
        end
    end
    
endmodule