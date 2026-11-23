module rasterizer(
    input logic clk,
    input logic rst,
    input logic rast_start,
    input logic rast_valid,
    input logic [9:0] x0,
    input logic [9:0] y0,
    input logic [9:0] x1,
    input logic [9:0] y1,
    input logic [9:0] x2,
    input logic [9:0] y2,
    input logic [7:0] clor0,
    input logic [7:0] clor1,
    input logic [7:0] clor2,
    output logic [9:0] frag_x,
    output logic [9:0] frag_y,
    output logic [31:0] frag_clor_r,
    output logic [31:0] frag_clor_g,
    output logic [31:0] frag_clor_b,
    output logic frag_valid,
    output logic rast_busy,
    output logic rast_done
);

    typedef enum logic [3:0]{
        IDLE,
        BOUND,
        RAST_V_1,
        RAST_V_2,
        RAST_I_INI,
        COLOR_INI_1,
        COLOR_INI_2,
        RAST_I_JUD,
        RAST_I_NEX,
        DONE,
        WAIT,
        DIV_WAIT
    } state_t;
    state_t state;
    state_t wait_state;

    logic [9:0] reg_x0;
    logic [9:0] reg_x1;
    logic [9:0] reg_x2;
    logic [9:0] reg_y0;
    logic [9:0] reg_y1;
    logic [9:0] reg_y2;
    logic [7:0] c_r0;
    logic [7:0] c_g0;
    logic [7:0] c_b0;
    logic [7:0] c_r1;
    logic [7:0] c_g1;
    logic [7:0] c_b1;
    logic [7:0] c_r2;
    logic [7:0] c_g2;
    logic [7:0] c_b2;
    logic signed [14:0] norm_c_r0;
    logic signed [14:0] norm_c_g0;
    logic signed [14:0] norm_c_b0;
    logic signed [14:0] norm_c_r1;
    logic signed [14:0] norm_c_g1;
    logic signed [14:0] norm_c_b1;
    logic signed [14:0] norm_c_r2;
    logic signed [14:0] norm_c_g2;
    logic signed [14:0] norm_c_b2;
    logic [9:0] bound_x0;
    logic [9:0] bound_x1;
    logic [9:0] bound_y0;
    logic [9:0] bound_y1;
    logic signed [20:0] a0;
    logic signed [20:0] b0;
    logic signed [21:0] c0;
    logic signed [20:0] a1;
    logic signed [20:0] b1;
    logic signed [21:0] c1;
    logic signed [20:0] a2;
    logic signed [20:0] b2;
    logic signed [21:0] c2;
    logic signed [20:0] ef_v0;
    logic signed [20:0] ef_v1;
    logic signed [20:0] ef_v2;
    logic signed [20:0] ef_i0;
    logic signed [20:0] ef_i1;
    logic signed [20:0] ef_i2;
    logic [9:0] scan_x;
    logic [9:0] scan_y;
    logic signed [14:0] dclor_r_x;
    logic signed [14:0] dclor_r_y;
    logic signed [14:0] dclor_g_x;
    logic signed [14:0] dclor_g_y;
    logic signed [14:0] dclor_b_x;
    logic signed [14:0] dclor_b_y;
    logic signed [31:0] dclor_r_x_num;
    logic signed [31:0] dclor_r_y_num;
    logic signed [31:0] dclor_g_x_num;
    logic signed [31:0] dclor_g_y_num;
    logic signed [31:0] dclor_b_x_num;
    logic signed [31:0] dclor_b_y_num;
    logic signed [31:0] ini_clor_r;
    logic signed [31:0] ini_clor_g;
    logic signed [31:0] ini_clor_b;
    logic signed [31:0] cur_clor_r;
    logic signed [31:0] cur_clor_g;
    logic signed [31:0] cur_clor_b;
    logic signed [10:0] delta_x;
    logic signed [10:0] delta_y;
    logic signed [21:0] area;
    logic signed [10:0] dx10;
    logic signed [10:0] dy10;
    logic signed [10:0] dx20;
    logic signed [10:0] dy20;
    logic div_start;
    logic [5:0] div_done;
    logic signed [31:0] div_result0;
    logic signed [31:0] div_result1;
    logic signed [31:0] div_result2;
    logic signed [31:0] div_result3;
    logic signed [31:0] div_result4;
    logic signed [31:0] div_result5;
    logic if_inside;

    function [9:0] min;
        input logic [9:0] a;
        input logic [9:0] b;
        input logic [9:0] c;
        begin
            min = (a < b) ? ((a < c) ? a : c) : ((b < c) ? b : c);
        end
    endfunction
    function [9:0] max;
        input logic [9:0] a;
        input logic [9:0] b;
        input logic [9:0] c;
        begin
            max = (a > b) ? ((a > c) ? a : c) : ((b > c) ? b : c);
        end
    endfunction

    function signed [20:0] edge_a;
        input logic [9:0] x0;
        input logic [9:0] y0;
        input logic [9:0] x1;
        input logic [9:0] y1;
        begin
            edge_a = $signed({1'b0, y1}) - $signed({1'b0, y0});
        end
    endfunction
    function signed [20:0] edge_b;
        input logic [9:0] x0;
        input logic [9:0] y0;
        input logic [9:0] x1;
        input logic [9:0] y1;
        begin
            edge_b = $signed({1'b0, x0}) - $signed({1'b0, x1});
        end
    endfunction
    function signed [21:0] edge_c;
        input logic [9:0] x0;
        input logic [9:0] y0;
        input logic [9:0] x1;
        input logic [9:0] y1;
        begin
            edge_c = $signed({1'b0, x1}) * $signed({1'b0, y0}) - $signed({1'b0, y1}) * $signed({1'b0, x0});
        end
    endfunction

    function signed [20:0] edge_func;
        input logic [9:0] xp;
        input logic [9:0] yp;
        input logic signed [20:0] a;
        input logic signed [20:0] b;
        input logic signed [21:0] c;
        begin
            edge_func = a * $signed({1'b0, xp}) + b * $signed({1'b0, yp}) + c;
        end
    endfunction

    function is_inside;
        input logic signed [20:0] e0;
        input logic signed [20:0] e1;
        input logic signed [20:0] e2;
        begin
            is_inside = (e0 >= 0) && (e1 >= 0) && (e2 >= 0) || (e0 <= 0) && (e1 <= 0) && (e2 <= 0);
        end
    endfunction

    function [18:0] pixel_addr;
        input logic [9:0] x;
        input logic [9:0] y;
        begin
            pixel_addr = (y << 9) + (y << 7) + x;
        end
    endfunction

    function signed [31:0] dcolor_num_x;
        input logic signed [14:0] c0, c1, c2;
        input logic signed [10:0] d10, d20;
        begin
            dcolor_num_x = (c0) * (d10 - d20) + (c1) * (d20) - (c2) * (d10);
        end
    endfunction

    function signed [31:0] dcolor_num_y;
        input logic signed [14:0] c0, c1, c2;
        input logic signed [10:0] d10, d20;
        begin
            dcolor_num_y = (c0) * (d20 - d10) - (c1) * (d20) + (c2) * (d10);
        end
    endfunction

    function [7:0] q312_to_rgb332;
        input logic signed [31:0] r;
        input logic signed [31:0] g;
        input logic signed [31:0] b;

        logic [2:0] r8;
        logic [2:0] g8;
        logic [1:0] b8;

        logic signed [31:0] clamp_r;
        logic signed [31:0] clamp_g;
        logic signed [31:0] clamp_b;
        begin
            if(r < 0)begin
                clamp_r = 0;
            end else if(r > 4096)begin
                clamp_r = 4096;
            end else begin
                clamp_r = r;
            end
            if(g < 0)begin
                clamp_g = 0;
            end else if(g > 4096)begin
                clamp_g = 4096;
            end else begin
                clamp_g = g;
            end
            if(b < 0)begin
                clamp_b = 0;
            end else if(b > 4096)begin
                clamp_b = 4096;
            end else begin
                clamp_b = b;
            end

            r8 = (clamp_r * 7 + 2048) >> 12;
            g8 = (clamp_g * 7 + 2048) >> 12;
            b8 = (clamp_b * 3 + 2048) >> 12;

            q312_to_rgb332 = {r8, g8, b8};

        end
    endfunction

    divider_signed u0_divider_signed (
        .clk      (clk                   ),
        .rst      (rst                   ),
        .start    (div_start             ),
        .a        (dclor_r_x_num         ),
        .b        ({{10{area[21]}}, area}),
        .ready    (                      ),
        .busy     (                      ),
        .done     (div_done[0]           ),
        .result   (div_result0           ),
        .div_zero (                      ),
        .overflow (                      )
    );

    divider_signed u1_divider_signed (
        .clk      (clk                   ),
        .rst      (rst                   ),
        .start    (div_start             ),
        .a        (dclor_r_y_num         ),
        .b        ({{10{area[21]}}, area}),
        .ready    (                      ),
        .busy     (                      ),
        .done     (div_done[1]           ),
        .result   (div_result1           ),
        .div_zero (                      ),
        .overflow (                      )
    );

    divider_signed u2_divider_signed (
        .clk      (clk                   ),
        .rst      (rst                   ),
        .start    (div_start             ),
        .a        (dclor_g_x_num         ),
        .b        ({{10{area[21]}}, area}),
        .ready    (                      ),
        .busy     (                      ),
        .done     (div_done[2]           ),
        .result   (div_result2           ),
        .div_zero (                      ),
        .overflow (                      )
    );

    divider_signed u3_divider_signed (
        .clk      (clk                   ),
        .rst      (rst                   ),
        .start    (div_start             ),
        .a        (dclor_g_y_num         ),
        .b        ({{10{area[21]}}, area}),
        .ready    (                      ),
        .busy     (                      ),
        .done     (div_done[3]           ),
        .result   (div_result3           ),
        .div_zero (                      ),
        .overflow (                      )
    );

    divider_signed u4_divider_signed (
        .clk      (clk                   ),
        .rst      (rst                   ),
        .start    (div_start             ),
        .a        (dclor_b_x_num         ),
        .b        ({{10{area[21]}}, area}),
        .ready    (                      ),
        .busy     (                      ),
        .done     (div_done[4]           ),
        .result   (div_result4           ),
        .div_zero (                      ),
        .overflow (                      )
    );

    divider_signed u5_divider_signed (
        .clk      (clk                   ),
        .rst      (rst                   ),
        .start    (div_start             ),
        .a        (dclor_b_y_num         ),
        .b        ({{10{area[21]}}, area}),
        .ready    (                      ),
        .busy     (                      ),
        .done     (div_done[5]           ),
        .result   (div_result5           ),
        .div_zero (                      ),
        .overflow (                      )
    );

    assign if_inside = is_inside(ef_i0, ef_i1, ef_i2);

    assign div_start = (state == RAST_I_INI) && (area != 0);

    always_ff@(posedge clk)begin
        if(rst)begin
            state <= IDLE;
            rast_busy <= 1'b0;
            rast_done <= 1'b0;
            frag_x <= 1'b0;
            frag_y <= 1'b0;
            frag_clor_r <= 1'b0;
            frag_clor_g <= 1'b0;
            frag_clor_b <= 1'b0;
        end else begin
            case(state)
                IDLE:begin
                    if(rast_start && rast_valid)begin
                        rast_busy <= 1'b1;

                        reg_x0 <= x0;
                        reg_x1 <= x1;
                        reg_x2 <= x2;
                        reg_y0 <= y0;
                        reg_y1 <= y1;
                        reg_y2 <= y2;

                        c_r0 <= clor0[7:5];
                        c_g0 <= clor0[4:2];
                        c_b0 <= clor0[1:0];
                        c_r1 <= clor1[7:5];
                        c_g1 <= clor1[4:2];
                        c_b1 <= clor1[1:0];
                        c_r2 <= clor2[7:5];
                        c_g2 <= clor2[4:2];
                        c_b2 <= clor2[1:0];

                        state <= BOUND;
                    end else begin
                        state <= IDLE;
                    end
                    rast_done <= 1'b0;
                end
                BOUND:begin
                    bound_x0 <= min(reg_x0, reg_x1, reg_x2);
                    bound_x1 <= max(reg_x0, reg_x1, reg_x2);
                    bound_y0 <= min(reg_y0, reg_y1, reg_y2);
                    bound_y1 <= max(reg_y0, reg_y1, reg_y2);

                    dx10 <= $signed({1'b0, reg_x1}) - $signed({1'b0, reg_x0});
                    dy10 <= $signed({1'b0, reg_y1}) - $signed({1'b0, reg_y0});
                    dx20 <= $signed({1'b0, reg_x2}) - $signed({1'b0, reg_x0});
                    dy20 <= $signed({1'b0, reg_y2}) - $signed({1'b0, reg_y0});

                    norm_c_r0 <= ($signed({1'b0, c_r0}) <<< 12) / 7;
                    norm_c_r1 <= ($signed({1'b0, c_r1}) <<< 12) / 7;
                    norm_c_r2 <= ($signed({1'b0, c_r2}) <<< 12) / 7;
                    norm_c_g0 <= ($signed({1'b0, c_g0}) <<< 12) / 7;
                    norm_c_g1 <= ($signed({1'b0, c_g1}) <<< 12) / 7;
                    norm_c_g2 <= ($signed({1'b0, c_g2}) <<< 12) / 7;
                    norm_c_b0 <= ($signed({1'b0, c_b0}) <<< 12) / 3;
                    norm_c_b1 <= ($signed({1'b0, c_b1}) <<< 12) / 3;
                    norm_c_b2 <= ($signed({1'b0, c_b2}) <<< 12) / 3;

                    if(rast_valid)begin
                        state <= RAST_V_1;
                    end else begin
                        state <= WAIT;
                        wait_state <= RAST_V_1;
                    end

                end
                RAST_V_1:begin
                    a0 <= edge_a(reg_x0, reg_y0, reg_x1, reg_y1);
                    b0 <= edge_b(reg_x0, reg_y0, reg_x1, reg_y1);
                    c0 <= edge_c(reg_x0, reg_y0, reg_x1, reg_y1);

                    a1 <= edge_a(reg_x1, reg_y1, reg_x2, reg_y2);
                    b1 <= edge_b(reg_x1, reg_y1, reg_x2, reg_y2);
                    c1 <= edge_c(reg_x1, reg_y1, reg_x2, reg_y2);

                    a2 <= edge_a(reg_x2, reg_y2, reg_x0, reg_y0);
                    b2 <= edge_b(reg_x2, reg_y2, reg_x0, reg_y0);
                    c2 <= edge_c(reg_x2, reg_y2, reg_x0, reg_y0);

                    area <= dx10 * dy20 - dy10 * dx20;
                    dclor_r_x_num <= dcolor_num_x(norm_c_r0, norm_c_r1, norm_c_r2, dy10, dy20);
                    dclor_r_y_num <= dcolor_num_y(norm_c_r0, norm_c_r1, norm_c_r2, dx10, dx20);
                    dclor_g_x_num <= dcolor_num_x(norm_c_g0, norm_c_g1, norm_c_g2, dy10, dy20);
                    dclor_g_y_num <= dcolor_num_y(norm_c_g0, norm_c_g1, norm_c_g2, dx10, dx20);
                    dclor_b_x_num <= dcolor_num_x(norm_c_b0, norm_c_b1, norm_c_b2, dy10, dy20);
                    dclor_b_y_num <= dcolor_num_y(norm_c_b0, norm_c_b1, norm_c_b2, dx10, dx20);

                    delta_x <= $signed({1'b0, bound_x0}) - $signed({1'b0, reg_x0});
                    delta_y <= $signed({1'b0, bound_y0}) - $signed({1'b0, reg_y0});

                    if(rast_valid)begin
                        state <= RAST_V_2;
                    end else begin
                        state <= WAIT;
                        wait_state <= RAST_V_2;
                    end
                end
                RAST_V_2:begin
                    ef_v0 <= edge_func(bound_x0, bound_y0, a0, b0, c0);
                    ef_v1 <= edge_func(bound_x0, bound_y0, a1, b1, c1);
                    ef_v2 <= edge_func(bound_x0, bound_y0, a2, b2, c2);

                    scan_x <= bound_x0;
                    scan_y <= bound_y0;

                    if(rast_valid)begin
                        state <= RAST_I_INI;
                    end else begin
                        state <= WAIT;
                        wait_state <= RAST_I_INI;
                    end
                end
                RAST_I_INI:begin
                    ef_i0 <= ef_v0;
                    ef_i1 <= ef_v1;
                    ef_i2 <= ef_v2;

                    if(area == 0)begin
                        state <= DONE;
                    end else begin
                        state <= DIV_WAIT;
                    end
                end
                DIV_WAIT:begin
                    if(&div_done)begin
                        dclor_r_x <= div_result0[14:0];
                        dclor_r_y <= div_result1[14:0];
                        dclor_g_x <= div_result2[14:0];
                        dclor_g_y <= div_result3[14:0];
                        dclor_b_x <= div_result4[14:0];
                        dclor_b_y <= div_result5[14:0];

                        if(rast_valid)begin
                            state <= COLOR_INI_1;
                        end else begin
                            state <= WAIT;
                            wait_state <= COLOR_INI_1;
                        end
                    end
                end
                COLOR_INI_1:begin
                    ini_clor_r <= norm_c_r0 + dclor_r_x * delta_x + dclor_r_y * delta_y;
                    ini_clor_g <= norm_c_g0 + dclor_g_x * delta_x + dclor_g_y * delta_y;
                    ini_clor_b <= norm_c_b0 + dclor_b_x * delta_x + dclor_b_y * delta_y;

                    if(rast_valid)begin
                        state <= COLOR_INI_2;
                    end else begin
                        state <= WAIT;
                        wait_state <= COLOR_INI_2;
                    end
                end
                COLOR_INI_2:begin
                    cur_clor_r <= ini_clor_r;
                    cur_clor_g <= ini_clor_g;
                    cur_clor_b <= ini_clor_b;

                    if(rast_valid)begin
                        state <= RAST_I_JUD;
                    end else begin
                        state <= WAIT;
                        wait_state <= RAST_I_JUD;
                    end
                end
                RAST_I_JUD:begin
                    frag_x <= scan_x;
                    frag_y <= scan_y;
                    frag_clor_r <= cur_clor_r;
                    frag_clor_g <= cur_clor_g;
                    frag_clor_b <= cur_clor_b;
                    if(if_inside && rast_valid)begin
                        frag_valid <= 1'b1;
                    end else begin
                        frag_valid <= 1'b0;
                    end

                    if(rast_valid)begin
                        state <= RAST_I_NEX;
                    end else begin
                        state <= WAIT;
                        wait_state <= RAST_I_JUD;
                    end
                end
                RAST_I_NEX:begin
                    frag_valid <= 1'b0;
                    if(scan_x < bound_x1)begin
                        scan_x <= scan_x + 1'b1;
                        ef_i0 <= ef_i0 + a0;
                        ef_i1 <= ef_i1 + a1;
                        ef_i2 <= ef_i2 + a2;
                        cur_clor_r <= cur_clor_r + dclor_r_x;
                        cur_clor_g <= cur_clor_g + dclor_g_x;
                        cur_clor_b <= cur_clor_b + dclor_b_x;

                        if(rast_valid)begin
                            state <= RAST_I_JUD;
                        end else begin
                            state <= WAIT;
                            wait_state <= RAST_I_JUD;
                        end
                    end else begin
                        scan_x <= bound_x0;
                        if(scan_y < bound_y1)begin
                            scan_y <= scan_y + 1'b1;
                            ef_i0 <= ef_v0 + b0;
                            ef_i1 <= ef_v1 + b1;
                            ef_i2 <= ef_v2 + b2;
                            ef_v0 <= ef_v0 + b0;
                            ef_v1 <= ef_v1 + b1;
                            ef_v2 <= ef_v2 + b2;
                            cur_clor_r <= ini_clor_r + dclor_r_y;
                            cur_clor_g <= ini_clor_g + dclor_g_y;
                            cur_clor_b <= ini_clor_b + dclor_b_y;
                            ini_clor_r <= ini_clor_r + dclor_r_y;
                            ini_clor_g <= ini_clor_g + dclor_g_y;
                            ini_clor_b <= ini_clor_b + dclor_b_y;

                            if(rast_valid)begin
                                state <= RAST_I_JUD;
                            end else begin
                                state <= WAIT;
                                wait_state <= RAST_I_JUD;
                            end
                        end else begin
                            state <= DONE;
                        end
                    end
                end
                DONE:begin
                    rast_busy <= 1'b0;
                    rast_done <= 1'b1;
                    state <= IDLE;
                end
                WAIT:begin
                    if(rast_valid)begin
                        state <= wait_state;
                    end else begin
                        state <= WAIT;
                    end
                end
                default:begin
                    state <= IDLE;
                end
            endcase
        end
    end
endmodule
