`timescale 1ns / 1ps

module gpu_clock #(
    parameter GPU_CLK_DIV_LOG2 = 0
)(
    input  wire clk,
    input  wire rst,
    output wire gpu_clk,
    output wire locked
);
    wire clock_raw;

    generate
        if(GPU_CLK_DIV_LOG2 == 0)begin: gen_mmcm
`ifdef __ICARUS__
            reg clock_reg = 0;
            reg [3:0] lock_pipe = 0;
            always #12.5 clock_reg = ~clock_reg;
            always @(posedge clk) begin
                if(rst) lock_pipe <= 0;
                else lock_pipe <= {lock_pipe[2:0],1'b1};
            end
            assign clock_raw = clock_reg;
            assign locked = lock_pipe[3];
`else
            wire feedback;
            wire feedback_buf;
            MMCME2_BASE #(
                .CLKIN1_PERIOD(10.0),
                .CLKFBOUT_MULT_F(10.0),
                .DIVCLK_DIVIDE(1),
                .CLKOUT0_DIVIDE_F(25.0)
            ) u_mmcm (
                .CLKIN1(clk),
                .CLKFBIN(feedback_buf),
                .CLKFBOUT(feedback),
                .CLKOUT0(clock_raw),
                .LOCKED(locked),
                .PWRDWN(1'b0),
                .RST(rst)
            );
            BUFG u_feedback_buf (.I(feedback), .O(feedback_buf));
`endif
        end else begin: gen_divider
            reg [GPU_CLK_DIV_LOG2-1:0] gpu_divider = 0;
            always @(posedge clk)
                gpu_divider <= gpu_divider + 1'b1;
            assign clock_raw = gpu_divider[GPU_CLK_DIV_LOG2-1];
            assign locked = 1'b1;
        end
    endgenerate

`ifdef __ICARUS__
    assign gpu_clk = clock_raw;
`else
    BUFG u_gpu_clk_buf (.I(clock_raw), .O(gpu_clk));
`endif
endmodule
