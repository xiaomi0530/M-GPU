`timescale 1ns/1ps

module vertex_shader #(
    parameter H_RES = 640,
    parameter V_RES = 480,
    parameter FB_PIXELS = H_RES * V_RES,
    parameter FB_ADDR_W = 19
)(
    input wire clk,
    input wire rst,
    input wire vs_start,

    input wire signed [31:0] vertex_x,
    input wire signed [31:0] vertex_y,
    input wire signed [31:0] vertex_z,
    input wire [7:0] vertex_color,

    input wire signed [31:0] m00,
    input wire signed [31:0] m01,
    input wire signed [31:0] m02,
    input wire signed [31:0] m03,
    input wire signed [31:0] m10,
    input wire signed [31:0] m11,
    input wire signed [31:0] m12,
    input wire signed [31:0] m13,
    input wire signed [31:0] m20,
    input wire signed [31:0] m21,
    input wire signed [31:0] m22,
    input wire signed [31:0] m23,
    input wire signed [31:0] m30,
    input wire signed [31:0] m31,
    input wire signed [31:0] m32,
    input wire signed [31:0] m33,

    output reg signed [31:0] screen_x,
    output reg signed [31:0] screen_y,
    output reg signed [31:0] screen_z,
    output reg [7:0] screen_color,

    output reg vs_busy,
    output reg vs_done,
    output reg vs_error
);

    localparam IDLE     = 3'd0;
    localparam MVP_0    = 3'd1;
    localparam MVP_1    = 3'd2;
    localparam PD_START = 3'd3;
    localparam PD_WAIT  = 3'd4;
    localparam VT       = 3'd5;
    localparam DONE     = 3'd6;

    localparam signed [63:0] WIDTH_I  = H_RES;
    localparam signed [63:0] HEIGHT_I = V_RES;

    reg [2:0] vs_state;

    reg signed [31:0] vertex_x_reg;
    reg signed [31:0] vertex_y_reg;
    reg signed [31:0] vertex_z_reg;

    reg signed [63:0] M00, M01, M02, M03;
    reg signed [63:0] M10, M11, M12, M13;
    reg signed [63:0] M20, M21, M22, M23;
    reg signed [63:0] M30, M31, M32, M33;

    reg signed [31:0] clip_x;
    reg signed [31:0] clip_y;
    reg signed [31:0] clip_z;
    reg signed [31:0] clip_w;

    reg signed [31:0] ndc_x;
    reg signed [31:0] ndc_y;
    reg signed [31:0] ndc_z;

    reg div_start0, div_start1, div_start2;
    reg signed [31:0] div_a0, div_a1, div_a2;
    reg signed [31:0] div_b0, div_b1, div_b2;

    wire div_ready0, div_ready1, div_ready2;
    wire div_busy0, div_busy1, div_busy2;
    wire div_done0, div_done1, div_done2;
    wire div_zero0, div_zero1, div_zero2;
    wire div_overflow0, div_overflow1, div_overflow2;

    wire signed [31:0] div_result0;
    wire signed [31:0] div_result1;
    wire signed [31:0] div_result2;

    wire div_done_all;
    wire div_zero_someone;
    wire div_overflow_someone;

    assign div_done_all =
        div_done0 & div_done1 & div_done2;

    assign div_zero_someone =
        div_zero0 | div_zero1 | div_zero2;

    assign div_overflow_someone =
        div_overflow0 | div_overflow1 | div_overflow2;

    divider_q16_16 u0_divider_q16_16 (
        .clk      (clk),
        .rst      (rst),
        .start    (div_start0),
        .a        (div_a0),
        .b        (div_b0),
        .ready    (div_ready0),
        .busy     (div_busy0),
        .done     (div_done0),
        .result   (div_result0),
        .div_zero (div_zero0),
        .overflow (div_overflow0)
    );

    divider_q16_16 u1_divider_q16_16 (
        .clk      (clk),
        .rst      (rst),
        .start    (div_start1),
        .a        (div_a1),
        .b        (div_b1),
        .ready    (div_ready1),
        .busy     (div_busy1),
        .done     (div_done1),
        .result   (div_result1),
        .div_zero (div_zero1),
        .overflow (div_overflow1)
    );

    divider_q16_16 u2_divider_q16_16 (
        .clk      (clk),
        .rst      (rst),
        .start    (div_start2),
        .a        (div_a2),
        .b        (div_b2),
        .ready    (div_ready2),
        .busy     (div_busy2),
        .done     (div_done2),
        .result   (div_result2),
        .div_zero (div_zero2),
        .overflow (div_overflow2)
    );

    function signed [65:0] sum4;
        input signed [63:0] a;
        input signed [63:0] b;
        input signed [63:0] c;
        input signed [63:0] d;

        begin
            sum4 =
                $signed({{2{a[63]}}, a}) +
                $signed({{2{b[63]}}, b}) +
                $signed({{2{c[63]}}, c}) +
                $signed({{2{d[63]}}, d});
        end
    endfunction

    wire signed [65:0] clip_x_wide;
    wire signed [65:0] clip_y_wide;
    wire signed [65:0] clip_z_wide;
    wire signed [65:0] clip_w_wide;
    wire mvp_overflow;

    assign clip_x_wide = sum4(M00, M10, M20, M30) >>> 16;
    assign clip_y_wide = sum4(M01, M11, M21, M31) >>> 16;
    assign clip_z_wide = sum4(M02, M12, M22, M32) >>> 16;
    assign clip_w_wide = sum4(M03, M13, M23, M33) >>> 16;

    assign mvp_overflow =
        (clip_x_wide[65:32] != {34{clip_x_wide[31]}}) ||
        (clip_y_wide[65:32] != {34{clip_y_wide[31]}}) ||
        (clip_z_wide[65:32] != {34{clip_z_wide[31]}}) ||
        (clip_w_wide[65:32] != {34{clip_w_wide[31]}});

    wire signed [63:0] ndc_x_ext;
    wire signed [63:0] ndc_y_ext;
    wire signed [63:0] ndc_z_ext;

    wire signed [63:0] viewport_x;
    wire signed [63:0] viewport_y;
    wire signed [63:0] viewport_z;
    wire viewport_overflow;

    assign ndc_x_ext = {{32{ndc_x[31]}}, ndc_x};
    assign ndc_y_ext = {{32{ndc_y[31]}}, ndc_y};
    assign ndc_z_ext = {{32{ndc_z[31]}}, ndc_z};

    assign viewport_x =
        ((ndc_x_ext + 64'sd65536) * WIDTH_I) >>> 1;

    assign viewport_y =
        ((64'sd65536 - ndc_y_ext) * HEIGHT_I) >>> 1;

    assign viewport_z =
        (ndc_z_ext + 64'sd65536) >>> 1;

    assign viewport_overflow =
        (viewport_x[63:32] != {32{viewport_x[31]}}) ||
        (viewport_y[63:32] != {32{viewport_y[31]}}) ||
        (viewport_z[63:32] != {32{viewport_z[31]}});

    always @(posedge clk) begin
        if (rst) begin
            vs_state <= IDLE;

            vs_busy  <= 1'b0;
            vs_done  <= 1'b0;
            vs_error <= 1'b0;

            vertex_x_reg <= 32'sd0;
            vertex_y_reg <= 32'sd0;
            vertex_z_reg <= 32'sd0;

            clip_x <= 32'sd0;
            clip_y <= 32'sd0;
            clip_z <= 32'sd0;
            clip_w <= 32'sd0;

            ndc_x <= 32'sd0;
            ndc_y <= 32'sd0;
            ndc_z <= 32'sd0;

            screen_x     <= 32'sd0;
            screen_y     <= 32'sd0;
            screen_z     <= 32'sd0;
            screen_color <= 8'd0;

            div_start0 <= 1'b0;
            div_start1 <= 1'b0;
            div_start2 <= 1'b0;

            div_a0 <= 32'sd0;
            div_b0 <= 32'sd0;
            div_a1 <= 32'sd0;
            div_b1 <= 32'sd0;
            div_a2 <= 32'sd0;
            div_b2 <= 32'sd0;
        end else begin
            vs_done <= 1'b0;

            div_start0 <= 1'b0;
            div_start1 <= 1'b0;
            div_start2 <= 1'b0;

            case (vs_state)
                IDLE: begin
                    vs_busy <= 1'b0;

                    if (vs_start) begin
                        vertex_x_reg <= vertex_x;
                        vertex_y_reg <= vertex_y;
                        vertex_z_reg <= vertex_z;

                        screen_color <= vertex_color;

                        vs_busy  <= 1'b1;
                        vs_error <= 1'b0;
                        vs_state <= MVP_0;
                    end
                end

                MVP_0: begin
                    M00 <= m00 * vertex_x_reg;
                    M10 <= m10 * vertex_y_reg;
                    M20 <= m20 * vertex_z_reg;
                    M30 <= $signed({{32{m30[31]}}, m30}) <<< 16;

                    M01 <= m01 * vertex_x_reg;
                    M11 <= m11 * vertex_y_reg;
                    M21 <= m21 * vertex_z_reg;
                    M31 <= $signed({{32{m31[31]}}, m31}) <<< 16;

                    M02 <= m02 * vertex_x_reg;
                    M12 <= m12 * vertex_y_reg;
                    M22 <= m22 * vertex_z_reg;
                    M32 <= $signed({{32{m32[31]}}, m32}) <<< 16;

                    M03 <= m03 * vertex_x_reg;
                    M13 <= m13 * vertex_y_reg;
                    M23 <= m23 * vertex_z_reg;
                    M33 <= $signed({{32{m33[31]}}, m33}) <<< 16;

                    vs_state <= MVP_1;
                end

                MVP_1: begin
                    if (mvp_overflow) begin
                        vs_error <= 1'b1;
                        vs_state <= DONE;
                    end else begin
                        clip_x <= clip_x_wide[31:0];
                        clip_y <= clip_y_wide[31:0];
                        clip_z <= clip_z_wide[31:0];
                        clip_w <= clip_w_wide[31:0];

                        vs_state <= PD_START;
                    end
                end

                PD_START: begin
                    if (div_ready0 && div_ready1 && div_ready2) begin
                        div_a0 <= clip_x;
                        div_b0 <= clip_w;

                        div_a1 <= clip_y;
                        div_b1 <= clip_w;

                        div_a2 <= clip_z;
                        div_b2 <= clip_w;

                        div_start0 <= 1'b1;
                        div_start1 <= 1'b1;
                        div_start2 <= 1'b1;

                        vs_state <= PD_WAIT;
                    end
                end

                PD_WAIT: begin
                    if (div_done_all) begin
                        if (div_zero_someone || div_overflow_someone) begin
                            vs_error <= 1'b1;
                            vs_state <= DONE;
                        end else begin
                            ndc_x <= div_result0;
                            ndc_y <= div_result1;
                            ndc_z <= div_result2;

                            vs_state <= VT;
                        end
                    end
                end

                VT: begin
                    if (viewport_overflow) begin
                        vs_error <= 1'b1;
                    end else begin
                        screen_x <= viewport_x[31:0];
                        screen_y <= viewport_y[31:0];
                        screen_z <= viewport_z[31:0];
                    end

                    vs_state <= DONE;
                end

                DONE: begin
                    vs_busy <= 1'b0;
                    vs_done <= 1'b1;
                    vs_state <= IDLE;
                end

                default: begin
                    vs_busy  <= 1'b0;
                    vs_error <= 1'b1;
                    vs_state <= IDLE;
                end
            endcase
        end
    end

endmodule