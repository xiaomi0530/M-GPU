`timescale 1ns / 1ps

module rasterizer (
    input  wire       clk,
    input  wire       rst,
    input  wire       rast_start,
    input  wire       rast_valid,
    input  wire [9:0] x0,
    input  wire [9:0] y0,
    input  wire [9:0] x1,
    input  wire [9:0] y1,
    input  wire [9:0] x2,
    input  wire [9:0] y2,
    input  wire [7:0] clor0, 
    input  wire [7:0] clor1, 
    input  wire [7:0] clor2,
    output reg  [9:0]  frag_x,
    output reg  [9:0]  frag_y,
    output reg  [31:0] frag_clor_R,
    output reg  [31:0] frag_clor_G,
    output reg  [31:0] frag_clor_B,
    output reg         frag_valid,
    output reg         rast_busy,
    output reg         rast_done
);

    function [9:0] min;
        input [9:0] a;
        input [9:0] b;
        input [9:0] c;
        begin
            min = (a<b)?((a<c)?a:c):((b<c)?b:c);
        end
    endfunction
    function [9:0] max;
        input [9:0] a;
        input [9:0] b;
        input [9:0] c;
        begin
            max = (a>b)?((a>c)?a:c):((b>c)?b:c);
        end
    endfunction

    function signed [20:0] edge_A;
        input [9:0] x0;
        input [9:0] y0;
        input [9:0] x1;
        input [9:0] y1;
        begin
            edge_A = $signed({1'b0,y1}) - $signed({1'b0,y0});
        end
    endfunction
    function signed [20:0] edge_B;
        input [9:0] x0;
        input [9:0] y0;
        input [9:0] x1;
        input [9:0] y1;
        begin
            edge_B = $signed({1'b0,x0}) - $signed({1'b0,x1});
        end
    endfunction
    function signed [21:0] edge_C;
        input [9:0] x0;
        input [9:0] y0;
        input [9:0] x1;
        input [9:0] y1;
        begin
            edge_C = $signed({1'b0,x1})*$signed({1'b0,y0}) - $signed({1'b0,y1})*$signed({1'b0,x0});
        end
    endfunction

    function signed [20:0] edge_func;
        input [9:0] xp;
        input [9:0] yp;
        input signed [20:0] A;
        input signed [20:0] B;
        input signed [21:0] C;
        begin
            edge_func = A*$signed({1'b0,xp}) + B*$signed({1'b0,yp}) + C;
        end
    endfunction

    function is_inside;
        input signed [20:0] e0;
        input signed [20:0] e1;
        input signed [20:0] e2;
        begin
            is_inside = (e0>=0)&&(e1>=0)&&(e2>=0) || (e0<=0)&&(e1<=0)&&(e2<=0);
        end
    endfunction

    function [18:0] pixel_addr;
        input [9:0] x;
        input [9:0] y;
        begin
            pixel_addr = (y<<9)+(y<<7) + x;
        end
    endfunction

    function signed [31:0] dcolor_num_x;
        input signed [14:0] C0,C1,C2;
        input signed [10:0] d10,d20;
        begin
           dcolor_num_x = (C0) * (d10-d20) + (C1) * (d20) - (C2) * (d10);
        end
    endfunction

    function signed [31:0] dcolor_num_y;
        input signed [14:0] C0,C1,C2;
        input signed [10:0] d10,d20;
        begin
           dcolor_num_y = (C0) * (d20-d10) - (C1) * (d20) + (C2) * (d10);
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

    reg [9:0] reg_x0;
    reg [9:0] reg_x1;
    reg [9:0] reg_x2;
    reg [9:0] reg_y0;
    reg [9:0] reg_y1;
    reg [9:0] reg_y2;

    reg [7:0] cR0, cG0, cB0;
    reg [7:0] cR1, cG1, cB1;
    reg [7:0] cR2, cG2, cB2;

    reg signed [14:0] norm_cR0, norm_cG0, norm_cB0;
    reg signed [14:0] norm_cR1, norm_cG1, norm_cB1;
    reg signed [14:0] norm_cR2, norm_cG2, norm_cB2;
        
    reg [9:0] bound_x0;
    reg [9:0] bound_x1;
    reg [9:0] bound_y0;
    reg [9:0] bound_y1;

    reg signed [20:0] A0;
    reg signed [20:0] B0;
    reg signed [21:0] C0;
    reg signed [20:0] A1;
    reg signed [20:0] B1;
    reg signed [21:0] C1;
    reg signed [20:0] A2;
    reg signed [20:0] B2;
    reg signed [21:0] C2;

    reg signed [20:0] ef_v0;
    reg signed [20:0] ef_v1;
    reg signed [20:0] ef_v2;
    reg signed [20:0] ef_i0;
    reg signed [20:0] ef_i1;
    reg signed [20:0] ef_i2;

    reg [9:0] scan_x;
    reg [9:0] scan_y;

    reg signed [14:0] dclorR_x;
    reg signed [14:0] dclorR_y; 
    reg signed [14:0] dclorG_x;
    reg signed [14:0] dclorG_y;
    reg signed [14:0] dclorB_x;
    reg signed [14:0] dclorB_y;
    
    reg signed [31:0] dclorR_x_num;
    reg signed [31:0] dclorR_y_num; 
    reg signed [31:0] dclorG_x_num;
    reg signed [31:0] dclorG_y_num;
    reg signed [31:0] dclorB_x_num;
    reg signed [31:0] dclorB_y_num;

    reg signed [31:0] ini_clor_R;
    reg signed [31:0] ini_clor_G;
    reg signed [31:0] ini_clor_B;
    reg signed [31:0] cur_clor_R;
    reg signed [31:0] cur_clor_G;
    reg signed [31:0] cur_clor_B;
    reg signed [10:0] delta_x;
    reg signed [10:0] delta_y;

    reg signed [21:0] area;
    reg signed [10:0] dx10;
    reg signed [10:0] dy10;
    reg signed [10:0] dx20;
    reg signed [10:0] dy20;

    wire if_inside;
    assign if_inside = is_inside(ef_i0,ef_i1,ef_i2);

    reg [3:0] wait_state;

    reg [3:0] rast_state;
    localparam IDLE       = 4'd0;
    localparam BOUND      = 4'd1;
    localparam RAST_V_1   = 4'd2;
    localparam RAST_V_2   = 4'd3;
    localparam RAST_I_ini = 4'd4;
    localparam COLOR_ini_1= 4'd5;
    localparam COLOR_ini_2= 4'd6;
    localparam RAST_I_jud = 4'd7;
//    localparam SHADE      = 4'd8;
    localparam RAST_I_nex = 4'd9;
    localparam DONE       = 4'd10;
    localparam WAIT       = 4'd11;

    always@(posedge clk)begin
        if(rst)begin
            rast_state <= IDLE;
            rast_done <= 1'b0;
            frag_x <= 1'b0;
            frag_y <= 1'b0;
            frag_clor_R <= 1'b0;
            frag_clor_G <= 1'b0;
            frag_clor_B <= 1'b0;
        end else begin
            case(rast_state)
                IDLE:begin
                    if(rast_start && rast_valid)begin
                        rast_busy <= 1'b1;

                        reg_x0 <= x0;
                        reg_x1 <= x1;
                        reg_x2 <= x2;
                        reg_y0 <= y0;
                        reg_y1 <= y1;
                        reg_y2 <= y2;

                        cR0 <= clor0[7:5];
                        cG0 <= clor0[4:2];
                        cB0 <= clor0[1:0];
                        cR1 <= clor1[7:5];
                        cG1 <= clor1[4:2];
                        cB1 <= clor1[1:0];
                        cR2 <= clor2[7:5];
                        cG2 <= clor2[4:2];
                        cB2 <= clor2[1:0];

                        rast_state <= BOUND;
                    end else begin
                        rast_state <= IDLE;
                    end
                    rast_done <= 1'b0;
                end
                BOUND:begin
                    bound_x0 <= min(reg_x0,reg_x1,reg_x2);
                    bound_x1 <= max(reg_x0,reg_x1,reg_x2);
                    bound_y0 <= min(reg_y0,reg_y1,reg_y2);
                    bound_y1 <= max(reg_y0,reg_y1,reg_y2);
                    
                    dx10 <= $signed({1'b0,reg_x1}) - $signed({1'b0,reg_x0});
                    dy10 <= $signed({1'b0,reg_y1}) - $signed({1'b0,reg_y0});
                    dx20 <= $signed({1'b0,reg_x2}) - $signed({1'b0,reg_x0});
                    dy20 <= $signed({1'b0,reg_y2}) - $signed({1'b0,reg_y0});

                    norm_cR0 <= ($signed({1'b0,cR0}) <<< 12) / 7;
                    norm_cR1 <= ($signed({1'b0,cR1}) <<< 12) / 7;
                    norm_cR2 <= ($signed({1'b0,cR2}) <<< 12) / 7;
                    norm_cG0 <= ($signed({1'b0,cG0}) <<< 12) / 7;
                    norm_cG1 <= ($signed({1'b0,cG1}) <<< 12) / 7;
                    norm_cG2 <= ($signed({1'b0,cG2}) <<< 12) / 7;
                    norm_cB0 <= ($signed({1'b0,cB0}) <<< 12) / 3;
                    norm_cB1 <= ($signed({1'b0,cB1}) <<< 12) / 3;
                    norm_cB2 <= ($signed({1'b0,cB2}) <<< 12) / 3;

                    if(rast_valid)begin
                        rast_state <= RAST_V_1;
                    end else begin
                        rast_state <= WAIT;
                        wait_state <= RAST_V_1;
                    end
                    
                end
                RAST_V_1:begin
                    A0 <= edge_A(reg_x0,reg_y0,reg_x1,reg_y1);
                    B0 <= edge_B(reg_x0,reg_y0,reg_x1,reg_y1);
                    C0 <= edge_C(reg_x0,reg_y0,reg_x1,reg_y1);

                    A1 <= edge_A(reg_x1,reg_y1,reg_x2,reg_y2);
                    B1 <= edge_B(reg_x1,reg_y1,reg_x2,reg_y2);
                    C1 <= edge_C(reg_x1,reg_y1,reg_x2,reg_y2);

                    A2 <= edge_A(reg_x2,reg_y2,reg_x0,reg_y0);
                    B2 <= edge_B(reg_x2,reg_y2,reg_x0,reg_y0);
                    C2 <= edge_C(reg_x2,reg_y2,reg_x0,reg_y0);

                    area <= dx10 * dy20 - dy10 * dx20;
                    dclorR_x_num <= dcolor_num_x(norm_cR0,norm_cR1,norm_cR2,dy10,dy20);
                    dclorR_y_num <= dcolor_num_y(norm_cR0,norm_cR1,norm_cR2,dx10,dx20);
                    dclorG_x_num <= dcolor_num_x(norm_cG0,norm_cG1,norm_cG2,dy10,dy20);
                    dclorG_y_num <= dcolor_num_y(norm_cG0,norm_cG1,norm_cG2,dx10,dx20);
                    dclorB_x_num <= dcolor_num_x(norm_cB0,norm_cB1,norm_cB2,dy10,dy20);
                    dclorB_y_num <= dcolor_num_y(norm_cB0,norm_cB1,norm_cB2,dx10,dx20);
                    
                    delta_x <= $signed({1'b0,bound_x0}) - $signed({1'b0,reg_x0});
                    delta_y <= $signed({1'b0,bound_y0}) - $signed({1'b0,reg_y0});

                    if(rast_valid)begin
                        rast_state <= RAST_V_2;
                    end else begin
                        rast_state <= WAIT;
                        wait_state <= RAST_V_2;
                    end
                end
                RAST_V_2:begin
                    ef_v0 <= edge_func(bound_x0,bound_y0,A0,B0,C0);
                    ef_v1 <= edge_func(bound_x0,bound_y0,A1,B1,C1);
                    ef_v2 <= edge_func(bound_x0,bound_y0,A2,B2,C2);

                    scan_x <= bound_x0;
                    scan_y <= bound_y0;

                    if(rast_valid)begin
                        rast_state <= RAST_I_ini;
                    end else begin
                        rast_state <= WAIT;
                        wait_state <= RAST_I_ini;
                    end
                end
                RAST_I_ini:begin
                    ef_i0 <= ef_v0;
                    ef_i1 <= ef_v1;
                    ef_i2 <= ef_v2;

                    dclorR_x <= dclorR_x_num / area;    
                    dclorR_y <= dclorR_y_num / area;
                    dclorG_x <= dclorG_x_num / area;
                    dclorG_y <= dclorG_y_num / area;
                    dclorB_x <= dclorB_x_num / area;
                    dclorB_y <= dclorB_y_num / area;

                    if(rast_valid)begin
                        rast_state <= COLOR_ini_1;
                    end else begin
                        rast_state <= WAIT;
                        wait_state <= COLOR_ini_1;
                    end
                end
                COLOR_ini_1:begin
                    ini_clor_R <= norm_cR0 + dclorR_x*delta_x + dclorR_y*delta_y;
                    ini_clor_G <= norm_cG0 + dclorG_x*delta_x + dclorG_y*delta_y;
                    ini_clor_B <= norm_cB0 + dclorB_x*delta_x + dclorB_y*delta_y;
                    
                    if(rast_valid)begin
                        rast_state <= COLOR_ini_2;
                    end else begin
                        rast_state <= WAIT;
                        wait_state <= COLOR_ini_2;
                    end
                end
                COLOR_ini_2:begin
                    cur_clor_R <= ini_clor_R;
                    cur_clor_G <= ini_clor_G;
                    cur_clor_B <= ini_clor_B;
                    
                    if(rast_valid)begin
                        rast_state <= RAST_I_jud;
                    end else begin
                        rast_state <= WAIT;
                        wait_state <= RAST_I_jud;
                    end
                end
                RAST_I_jud:begin
                    frag_x <= scan_x;
                    frag_y <= scan_y;
                    frag_clor_R <= cur_clor_R;
                    frag_clor_G <= cur_clor_G;
                    frag_clor_B <= cur_clor_B;
                    if(if_inside && rast_valid)begin
                        frag_valid <= 1'b1;
                    end else begin
                        frag_valid <= 1'b0;
                    end
                    
                    if(rast_valid)begin
                        rast_state <= RAST_I_nex;
                    end else begin
                        rast_state <= WAIT;
                        wait_state <= RAST_I_jud;
                    end
                end
                RAST_I_nex:begin
                    frag_valid <= 1'b0;
                    if(scan_x < bound_x1)begin
                        scan_x <= scan_x + 1'b1;
                        ef_i0 <= ef_i0 + A0;
                        ef_i1 <= ef_i1 + A1;
                        ef_i2 <= ef_i2 + A2;
                        cur_clor_R <= cur_clor_R + dclorR_x;
                        cur_clor_G <= cur_clor_G + dclorG_x;
                        cur_clor_B <= cur_clor_B + dclorB_x;
                        
                        if(rast_valid)begin
                            rast_state <= RAST_I_jud;
                        end else begin
                            rast_state <= WAIT;
                            wait_state <= RAST_I_jud;
                        end
                    end else begin
                        scan_x <= bound_x0;
                        if(scan_y < bound_y1)begin
                            scan_y <= scan_y + 1'b1;
                            ef_i0 <= ef_v0 + B0;
                            ef_i1 <= ef_v1 + B1;
                            ef_i2 <= ef_v2 + B2;
                            ef_v0 <= ef_v0 + B0;
                            ef_v1 <= ef_v1 + B1;
                            ef_v2 <= ef_v2 + B2;
                            cur_clor_R <= ini_clor_R + dclorR_y;
                            cur_clor_G <= ini_clor_G + dclorG_y;
                            cur_clor_B <= ini_clor_B + dclorB_y;
                            ini_clor_R <= ini_clor_R + dclorR_y;
                            ini_clor_G <= ini_clor_G + dclorG_y;
                            ini_clor_B <= ini_clor_B + dclorB_y;
                            
                            if(rast_valid)begin
                                rast_state <= RAST_I_jud;
                            end else begin
                                rast_state <= WAIT;
                                wait_state <= RAST_I_jud;
                            end
                        end else begin
                            rast_state <= DONE;
                        end
                    end
                end
                DONE:begin
                    rast_busy <= 1'b0;
                    rast_done <= 1'b1;
                    rast_state <= IDLE;
                end
                WAIT:begin
                    if(rast_valid)begin
                        rast_state <= wait_state;
                    end else begin
                        rast_state <= WAIT;
                    end
                end
                default: rast_state <= IDLE;
            endcase
        end
    end
endmodule