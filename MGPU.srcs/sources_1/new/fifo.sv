module fifo #(
    parameter int DEPTH = 8,
    parameter int DEPTH_BITS = 3,
    parameter int WIDTH = 28
)(
    input logic clk,
    input logic rst,
    input logic [WIDTH-1:0] w_data,
    input logic w_en,
    input logic r_en,
    output logic [WIDTH-1:0] r_data,
    output logic r_valid,
    output logic empty,
    output logic full
);

    logic [WIDTH-1:0] fifo[0:DEPTH-1];
    logic [DEPTH_BITS:0] count;
    logic [DEPTH_BITS-1:0] w_ptr;
    logic [DEPTH_BITS-1:0] r_ptr;
    logic write;
    logic read;

    assign write = w_en && !full;
    assign read = r_en && !empty;

    always_ff@(posedge clk)begin
        if(rst)begin
            count <= 1'b0;
            r_data <= 1'b0;
            w_ptr <= 1'b0;
            r_ptr <= 1'b0;
            r_valid <= 1'b0;
        end else begin
            if(w_en && !full)begin
                fifo[w_ptr] <= w_data;
                w_ptr <= w_ptr + 1'b1;
            end
            if(r_en && !empty)begin
                r_data <= fifo[r_ptr];
                r_valid <= 1'b1;
                r_ptr <= r_ptr + 1'b1;
            end else begin
                r_valid <= 1'b0;
            end
            case({
                write, read
            })
                2'b00:begin
                    count <= count;
                end
                2'b01:begin
                    count <= count - 1'b1;
                end
                2'b10:begin
                    count <= count + 1'b1;
                end
                2'b11:begin
                    count <= count;
                end
            endcase
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
