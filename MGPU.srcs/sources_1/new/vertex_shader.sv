module vertex_shader #(
    parameter int H_RES = 640,
    parameter int V_RES = 480,
    parameter int FB_PIXELS = H_RES * V_RES,
    parameter int FB_ADDR_W = 19
)(
    input logic clk,
    input logic rst,
    input logic vs_start,
    input logic signed [17:0] vertex_x,
    input logic signed [17:0] vertex_y,
    input logic signed [17:0] vertex_z,
    input logic [7:0] vertex_color,
    input logic signed [17:0] m00,
    input logic signed [17:0] m01,
    input logic signed [17:0] m02,
    input logic signed [17:0] m03,
    input logic signed [17:0] m10,
    input logic signed [17:0] m11,
    input logic signed [17:0] m12,
    input logic signed [17:0] m13,
    input logic signed [17:0] m20,
    input logic signed [17:0] m21,
    input logic signed [17:0] m22,
    input logic signed [17:0] m23,
    input logic signed [17:0] m30,
    input logic signed [17:0] m31,
    input logic signed [17:0] m32,
    input logic signed [17:0] m33,
    output logic signed [31:0] screen_x,
    output logic signed [31:0] screen_y,
    output logic signed [31:0] screen_z,
    output logic [7:0] screen_color,
    output logic vs_busy,
    output logic vs_done,
    output logic vs_error
);

    typedef enum logic [2:0]{
        IDLE,
        MVP_0,
        MVP_1,
        PD_START,
        PD_WAIT,
        VT,
        DONE
    } state_t;
    state_t state;

    localparam signed [63:0] WIDTH_I = H_RES;
    localparam signed [63:0] HEIGHT_I = V_RES;

    logic signed [17:0] vertex_x_reg;
    logic signed [17:0] vertex_y_reg;
    logic signed [17:0] vertex_z_reg;
    logic signed [35:0] m00_q;
    logic signed [35:0] m01_q;
    logic signed [35:0] m02_q;
    logic signed [35:0] m03_q;
    logic signed [35:0] m10_q;
    logic signed [35:0] m11_q;
    logic signed [35:0] m12_q;
    logic signed [35:0] m13_q;
    logic signed [35:0] m20_q;
    logic signed [35:0] m21_q;
    logic signed [35:0] m22_q;
    logic signed [35:0] m23_q;
    logic signed [35:0] m30_q;
    logic signed [35:0] m31_q;
    logic signed [35:0] m32_q;
    logic signed [35:0] m33_q;
    logic signed [17:0] clip_x;
    logic signed [17:0] clip_y;
    logic signed [17:0] clip_z;
    logic signed [17:0] clip_w;
    logic signed [17:0] ndc_x;
    logic signed [17:0] ndc_y;
    logic signed [17:0] ndc_z;
    logic div_start0;
    logic div_start1;
    logic div_start2;
    logic signed [17:0] div_a0;
    logic signed [17:0] div_a1;
    logic signed [17:0] div_a2;
    logic signed [17:0] div_b0;
    logic signed [17:0] div_b1;
    logic signed [17:0] div_b2;
    logic div_ready0;
    logic div_ready1;
    logic div_ready2;
    logic div_busy0;
    logic div_busy1;
    logic div_busy2;
    logic div_done0;
    logic div_done1;
    logic div_done2;
    logic div_zero0;
    logic div_zero1;
    logic div_zero2;
    logic div_overflow0;
    logic div_overflow1;
    logic div_overflow2;
    logic signed [17:0] div_result0;
    logic signed [17:0] div_result1;
    logic signed [17:0] div_result2;
    logic div_done_all;
    logic div_zero_someone;
    logic div_overflow_someone;
    logic signed [37:0] clip_x_wide;
    logic signed [37:0] clip_y_wide;
    logic signed [37:0] clip_z_wide;
    logic signed [37:0] clip_w_wide;
    logic mvp_overflow;
    logic signed [63:0] ndc_x_ext;
    logic signed [63:0] ndc_y_ext;
    logic signed [63:0] ndc_z_ext;
    logic signed [63:0] viewport_x;
    logic signed [63:0] viewport_y;
    logic signed [63:0] viewport_z;
    logic viewport_overflow;

    assign div_done_all = div_done0 & div_done1 & div_done2;

    assign div_zero_someone = div_zero0 | div_zero1 | div_zero2;

    assign div_overflow_someone = div_overflow0 | div_overflow1 | div_overflow2;

    divider_q16_16 u0_divider_q16_16 (
        .clk      (clk          ),
        .rst      (rst          ),
        .start    (div_start0   ),
        .a        (div_a0       ),
        .b        (div_b0       ),
        .ready    (div_ready0   ),
        .busy     (div_busy0    ),
        .done     (div_done0    ),
        .result   (div_result0  ),
        .div_zero (div_zero0    ),
        .overflow (div_overflow0)
    );

    divider_q16_16 u1_divider_q16_16 (
        .clk      (clk          ),
        .rst      (rst          ),
        .start    (div_start1   ),
        .a        (div_a1       ),
        .b        (div_b1       ),
        .ready    (div_ready1   ),
        .busy     (div_busy1    ),
        .done     (div_done1    ),
        .result   (div_result1  ),
        .div_zero (div_zero1    ),
        .overflow (div_overflow1)
    );

    divider_q16_16 u2_divider_q16_16 (
        .clk      (clk          ),
        .rst      (rst          ),
        .start    (div_start2   ),
        .a        (div_a2       ),
        .b        (div_b2       ),
        .ready    (div_ready2   ),
        .busy     (div_busy2    ),
        .done     (div_done2    ),
        .result   (div_result2  ),
        .div_zero (div_zero2    ),
        .overflow (div_overflow2)
    );

    function signed [37:0] sum4;
        input logic signed [35:0] a;
        input logic signed [35:0] b;
        input logic signed [35:0] c;
        input logic signed [35:0] d;

        begin
            sum4 = $signed({{2{a[35]}}, a}) + $signed({{2{b[35]}}, b}) + $signed({{2{c[35]}}, c}) +
                $signed({{2{d[35]}}, d});
        end
    endfunction

    assign clip_x_wide = sum4(m00_q, m10_q, m20_q, m30_q) >>> 12;
    assign clip_y_wide = sum4(m01_q, m11_q, m21_q, m31_q) >>> 12;
    assign clip_z_wide = sum4(m02_q, m12_q, m22_q, m32_q) >>> 12;
    assign clip_w_wide = sum4(m03_q, m13_q, m23_q, m33_q) >>> 12;

    assign mvp_overflow =
        (clip_x_wide[37:18] != {20{clip_x_wide[17]}}) ||
        (clip_y_wide[37:18] != {20{clip_y_wide[17]}}) ||
        (clip_z_wide[37:18] != {20{clip_z_wide[17]}}) ||
        (clip_w_wide[37:18] != {20{clip_w_wide[17]}});

    assign ndc_x_ext = {{46{ndc_x[17]}}, ndc_x};
    assign ndc_y_ext = {{46{ndc_y[17]}}, ndc_y};
    assign ndc_z_ext = {{46{ndc_z[17]}}, ndc_z};

    assign viewport_x = ((ndc_x_ext + 64'sd4096) * WIDTH_I) >>> 1;

    assign viewport_y = ((64'sd4096 - ndc_y_ext) * HEIGHT_I) >>> 1;

    assign viewport_z = (ndc_z_ext + 64'sd4096) >>> 1;

    assign viewport_overflow =
        (viewport_x[63:32] != {32{viewport_x[31]}}) ||
        (viewport_y[63:32] != {32{viewport_y[31]}}) ||
        (viewport_z[63:32] != {32{viewport_z[31]}});

    always_ff@(posedge clk)begin
        if(rst)begin
            state <= IDLE;

            vs_busy <= 1'b0;
            vs_done <= 1'b0;
            vs_error <= 1'b0;

            vertex_x_reg <= 18'sd0;
            vertex_y_reg <= 18'sd0;
            vertex_z_reg <= 18'sd0;

            clip_x <= 18'sd0;
            clip_y <= 18'sd0;
            clip_z <= 18'sd0;
            clip_w <= 18'sd0;

            ndc_x <= 18'sd0;
            ndc_y <= 18'sd0;
            ndc_z <= 18'sd0;

            screen_x <= 32'sd0;
            screen_y <= 32'sd0;
            screen_z <= 32'sd0;
            screen_color <= 8'd0;

            div_start0 <= 1'b0;
            div_start1 <= 1'b0;
            div_start2 <= 1'b0;

            div_a0 <= 18'sd0;
            div_b0 <= 18'sd0;
            div_a1 <= 18'sd0;
            div_b1 <= 18'sd0;
            div_a2 <= 18'sd0;
            div_b2 <= 18'sd0;
        end else begin
            vs_done <= 1'b0;

            div_start0 <= 1'b0;
            div_start1 <= 1'b0;
            div_start2 <= 1'b0;

            case(state)
                IDLE:begin
                    vs_busy <= 1'b0;

                    if(vs_start)begin
                        vertex_x_reg <= vertex_x;
                        vertex_y_reg <= vertex_y;
                        vertex_z_reg <= vertex_z;

                        screen_color <= vertex_color;

                        vs_busy <= 1'b1;
                        vs_error <= 1'b0;
                        state <= MVP_0;
                    end
                end

                MVP_0:begin
                    m00_q <= m00 * vertex_x_reg;
                    m10_q <= m10 * vertex_y_reg;
                    m20_q <= m20 * vertex_z_reg;
                    m30_q <= $signed({{18{m30[17]}}, m30}) <<< 12;

                    m01_q <= m01 * vertex_x_reg;
                    m11_q <= m11 * vertex_y_reg;
                    m21_q <= m21 * vertex_z_reg;
                    m31_q <= $signed({{18{m31[17]}}, m31}) <<< 12;

                    m02_q <= m02 * vertex_x_reg;
                    m12_q <= m12 * vertex_y_reg;
                    m22_q <= m22 * vertex_z_reg;
                    m32_q <= $signed({{18{m32[17]}}, m32}) <<< 12;

                    m03_q <= m03 * vertex_x_reg;
                    m13_q <= m13 * vertex_y_reg;
                    m23_q <= m23 * vertex_z_reg;
                    m33_q <= $signed({{18{m33[17]}}, m33}) <<< 12;

                    state <= MVP_1;
                end

                MVP_1:begin
                    if(mvp_overflow)begin
                        vs_error <= 1'b1;
                        state <= DONE;
                    end else begin
                        clip_x <= clip_x_wide[17:0];
                        clip_y <= clip_y_wide[17:0];
                        clip_z <= clip_z_wide[17:0];
                        clip_w <= clip_w_wide[17:0];

                        state <= PD_START;
                    end
                end

                PD_START:begin
                    if(div_ready0 && div_ready1 && div_ready2)begin
                        div_a0 <= clip_x;
                        div_b0 <= clip_w;

                        div_a1 <= clip_y;
                        div_b1 <= clip_w;

                        div_a2 <= clip_z;
                        div_b2 <= clip_w;

                        div_start0 <= 1'b1;
                        div_start1 <= 1'b1;
                        div_start2 <= 1'b1;

                        state <= PD_WAIT;
                    end
                end

                PD_WAIT:begin
                    if(div_done_all)begin
                        if(div_zero_someone || div_overflow_someone)begin
                            vs_error <= 1'b1;
                            state <= DONE;
                        end else begin
                            ndc_x <= div_result0;
                            ndc_y <= div_result1;
                            ndc_z <= div_result2;

                            state <= VT;
                        end
                    end
                end

                VT:begin
                    if(viewport_overflow)begin
                        vs_error <= 1'b1;
                    end else begin
                        screen_x <= viewport_x[31:0];
                        screen_y <= viewport_y[31:0];
                        screen_z <= viewport_z[31:0];
                    end

                    state <= DONE;
                end

                DONE:begin
                    vs_busy <= 1'b0;
                    vs_done <= 1'b1;
                    state <= IDLE;
                end

                default:begin
                    vs_busy <= 1'b0;
                    vs_error <= 1'b1;
                    state <= IDLE;
                end
            endcase
        end
    end

endmodule
