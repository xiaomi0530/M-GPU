`timescale 1ns / 1ps

module divider_signed (
    input  wire               clk,
    input  wire               rst,

    input  wire               start,
    input  wire signed [31:0] a,
    input  wire signed [31:0] b,

    output wire               ready,
    output reg                busy,
    output reg                done,

    output reg signed [31:0] result,
    output reg                div_zero,
    output reg                overflow
);

    localparam IDLE   = 3'd0;
    localparam CHECK  = 3'd1;
    localparam PREP   = 3'd2;
    localparam ITER   = 3'd3;
    localparam FINISH = 3'd4;
    localparam DONE   = 3'd5;

    reg [2:0] state;

    reg signed [31:0] a_reg;
    reg signed [31:0] b_reg;

    reg negative;

    reg [31:0] dividend;
    reg [31:0] divisor;
    reg [32:0] remainder;
    reg [31:0] quotient;

    reg [4:0] count;

    wire [31:0] abs_a;
    wire [31:0] abs_b;

    assign abs_a = a_reg[31]
                 ? (~a_reg + 32'd1)
                 : a_reg;

    assign abs_b = b_reg[31]
                 ? (~b_reg + 32'd1)
                 : b_reg;

    assign ready = (state == IDLE) && !rst;

    wire [32:0] trial_remainder;
    wire        quotient_bit;
    wire [32:0] next_remainder;

    assign trial_remainder =
        {remainder[31:0], dividend[31]};

    assign quotient_bit =
        trial_remainder >= {1'b0, divisor};

    assign next_remainder =
        quotient_bit
        ? trial_remainder - {1'b0, divisor}
        : trial_remainder;

    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE;

            a_reg <= 32'sd0;
            b_reg <= 32'sd0;
            negative <= 1'b0;

            dividend  <= 32'd0;
            divisor   <= 32'd0;
            remainder <= 33'd0;
            quotient  <= 32'd0;
            count     <= 5'd0;

            busy <= 1'b0;
            done <= 1'b0;

            result   <= 32'sd0;
            div_zero <= 1'b0;
            overflow <= 1'b0;
        end else begin
            done <= 1'b0;

            case (state)
                IDLE: begin
                    busy <= 1'b0;

                    if (start) begin
                        a_reg <= a;
                        b_reg <= b;

                        busy <= 1'b1;

                        div_zero <= 1'b0;
                        overflow <= 1'b0;

                        state <= CHECK;
                    end
                end

                CHECK: begin
                    if (b_reg == 32'sd0) begin
                        result   <= 32'sd0;
                        div_zero <= 1'b1;

                        state <= DONE;
                    end else begin
                        state <= PREP;
                    end
                end

                PREP: begin
                    negative <= a_reg[31] ^ b_reg[31];

                    dividend <= abs_a;
                    divisor  <= abs_b;

                    remainder <= 33'd0;
                    quotient  <= 32'd0;
                    count     <= 5'd0;

                    state <= ITER;
                end

                ITER: begin
                    remainder <= next_remainder;

                    dividend <= {dividend[30:0], 1'b0};

                    quotient <= {
                        quotient[30:0],
                        quotient_bit
                    };

                    if (count == 5'd31) begin
                        state <= FINISH;
                    end else begin
                        count <= count + 1'b1;
                    end
                end

                FINISH: begin
                    result <= negative ? (~quotient + 32'd1) : quotient;
                    overflow <= !negative && quotient[31];

                    state <= DONE;
                end

                DONE: begin
                    busy <= 1'b0;
                    done <= 1'b1;

                    state <= IDLE;
                end

                default: begin
                    state <= IDLE;
                    busy  <= 1'b0;
                end
            endcase
        end
    end

endmodule