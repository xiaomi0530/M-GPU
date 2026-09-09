`timescale 1ns/1ps

module fifo#(
    parameter DEPTH = 8,
    parameter DEPTH_BITS = 3,
    parameter WIDTH = 28 //10 + 10 + 8
) (
    input wire              clk,
    input wire              rst,
    input wire [WIDTH-1:0]  w_data,
    input wire              w_en,
    input wire              r_en,
    output reg [WIDTH-1:0]  r_data,
    output reg              empty,
    output reg              full
);

    reg [WIDTH-1:0] fifo [0:DEPTH-1];

    reg [DEPTH_BITS:0] count;
    reg [DEPTH_BITS-1:0] w_ptr;
    reg [DEPTH_BITS-1:0] r_ptr;

    always @(posedge clk) begin
        if(rst)begin
            count <= 1'b0;
            r_data <= 1'b0;
            w_ptr  <= 1'b0;
            r_ptr  <= 1'b0;
        end else begin
            if(w_en && !full)begin
                fifo[w_ptr] <= w_data;
                w_ptr <= w_ptr + 1'b1;
                count <= count + 1'b1;
            end
            if(r_en && !empty)begin
                fifo[r_ptr] <= 1'b0;
                r_data <= fifo[r_ptr];
                r_ptr <= r_ptr + 1'b1;
                count <= count - 1'b1;
            end
        end
    end
    
    always @(*)begin
        if(w_ptr == r_ptr && count == 1'b0)begin
            empty = 1'b1;
        end else begin
            empty = 1'b0;
        end
            
        if(count == DEPTH)begin
            full = 1'b1;
        end else begin
            full = 1'b0;
        end
    end
    
endmodule