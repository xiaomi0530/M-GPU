module divider_q16_16(
    input logic clk,
    input logic rst,
    input logic start,
    input logic signed [17:0] a,
    input logic signed [17:0] b,
    output logic ready,
    output logic busy,
    output logic done,
    output logic signed [17:0] result,
    output logic div_zero,
    output logic overflow
);

    typedef enum logic [2:0]{
        IDLE,
        CHECK,
        PREP,
        ITER,
        FINISH,
        DONE
    } state_t;
    state_t state;

    logic signed [17:0] a_reg;
    logic signed [17:0] b_reg;
    logic negative;
    logic [29:0] dividend;
    logic [17:0] divisor;
    logic [18:0] remainder;
    logic [29:0] quotient;
    logic [4:0] count;
    logic [17:0] abs_a;
    logic [17:0] abs_b;
    logic [18:0] trial_remainder;
    logic quotient_bit;
    logic [18:0] next_remainder;

    assign abs_a = a_reg[17] ? (~a_reg + 18'd1) : a_reg;

    assign abs_b = b_reg[17] ? (~b_reg + 18'd1) : b_reg;

    assign ready = (state == IDLE) && !rst;

    assign trial_remainder = {remainder[17:0], dividend[29]};

    assign quotient_bit = trial_remainder >= {1'b0, divisor};

    assign next_remainder = quotient_bit ? trial_remainder - {1'b0, divisor} : trial_remainder;

    always_ff@(posedge clk)begin
        if(rst)begin
            state <= IDLE;

            a_reg <= 18'sd0;
            b_reg <= 18'sd0;
            negative <= 1'b0;

            dividend <= 30'd0;
            divisor <= 18'd0;
            remainder <= 19'd0;
            quotient <= 30'd0;
            count <= 5'd0;

            busy <= 1'b0;
            done <= 1'b0;

            result <= 18'sd0;
            div_zero <= 1'b0;
            overflow <= 1'b0;
        end else begin
            done <= 1'b0;

            case(state)
                IDLE:begin
                    busy <= 1'b0;

                    if(start)begin
                        a_reg <= a;
                        b_reg <= b;

                        busy <= 1'b1;

                        div_zero <= 1'b0;
                        overflow <= 1'b0;

                        state <= CHECK;
                    end
                end

                CHECK:begin
                    if(b_reg == 18'sd0)begin
                        result <= 18'sd0;
                        div_zero <= 1'b1;

                        state <= DONE;
                    end else begin
                        state <= PREP;
                    end
                end

                PREP:begin
                    negative <= a_reg[17] ^ b_reg[17];

                    dividend <= {abs_a, 12'b0};
                    divisor <= abs_b;

                    remainder <= 19'd0;
                    quotient <= 30'd0;
                    count <= 5'd0;

                    state <= ITER;
                end

                ITER:begin
                    remainder <= next_remainder;

                    dividend <= {dividend[28:0], 1'b0};

                    quotient <= {quotient[28:0], quotient_bit};

                    if(count == 5'd29)begin
                        state <= FINISH;
                    end else begin
                        count <= count + 1'b1;
                    end
                end

                FINISH:begin
                    if(!negative)begin
                        if(quotient > 30'h0001_FFFF)begin

                            result <= 18'sh1_FFFF;
                            overflow <= 1'b1;
                        end else begin
                            result <= quotient[17:0];
                        end
                    end else begin
                        if(quotient > 30'h0002_0000)begin

                            result <= 18'sh2_0000;
                            overflow <= 1'b1;
                        end else begin
                            result <= ~quotient[17:0] + 18'd1;
                        end
                    end

                    state <= DONE;
                end

                DONE:begin
                    busy <= 1'b0;
                    done <= 1'b1;

                    state <= IDLE;
                end

                default:begin
                    state <= IDLE;
                    busy <= 1'b0;
                end
            endcase
        end
    end

endmodule
