`timescale 1ns/1ps

module shader (
    input           clk,
    input           rst,
    input           fifo_empty,
    input [27:0]    read_fifo_data,
    output  reg     read_fifo_en,
    input   wire    read_fifo_valid,

    input   wire    shad_start,
    output  reg     shad_busy,
    output  reg     shad_done,
    
    output  reg [9:0]  pixel_x,
    output  reg [9:0]  pixel_y,
    output  reg [7:5]  pixel_R,
    output  reg [4:2]  pixel_G,
    output  reg [1:0]  pixel_B
);

    reg          regs_w_en;
    reg  [2:0]   regs_w_addr;
    reg  [15:0]  regs_w_data;
    reg          regs_r_en;
    reg  [2:0]   regs_r_addr;
    wire [15:0]  regs_r_data;
    regs#(
        .WIDTH      (16 ),
        .DEPTH      (8  ),
        .DEPTH_BITS (3  )
    ) u_regs(
        .clk    (clk         ),
        .rst    (rst         ),
        .w_en   (regs_w_en   ),
        .w_addr (regs_w_addr ),
        .w_data (regs_w_data ),
        .r_en   (regs_r_en   ),
        .r_addr (regs_r_addr ),
        .r_data (regs_r_data )
    );

    reg [27:0] frag_data;
    reg [7:5]  frag_R;
    reg [4:2]  frag_G;
    reg [1:0]  frag_B;
    reg [9:0]  frag_x;
    reg [9:0]  frag_y;

    reg [2:0] shad_state;
    reg [3:0] get_frag_state;
    reg [3:0] out_pixel_state;
    localparam IDLE         = 3'd0;
    localparam GET_FRAG     = 3'd1;
    localparam FETCH        = 3'd2;
    localparam DECODE       = 3'd3;
    localparam EXCUTE       = 3'd4;
    localparam WRITE_BACK   = 3'd5;
    localparam OUT_PIXL     = 3'd6;
    localparam DONE         = 3'd7;
    always @(posedge clk) begin
        if(rst)begin
            regs_w_en <= 1'b0;
            regs_w_addr <= 1'b0;
            regs_w_data <= 1'b0;
            regs_r_en <= 1'b0;
            regs_r_addr <= 1'b0;
            shad_busy   <= 1'b0;
            shad_done   <= 1'b0;
            read_fifo_en <= 1'b0; 
            shad_state <= 1'b0;
            get_frag_state <= 1'b0;
            out_pixel_state <= 1'b0;
        end else begin
            case(shad_state)
                IDLE:begin
                    shad_done <= 1'b0;
                    if(shad_start) begin
                        shad_busy <= 1'b1;
                        get_frag_state <= 1'b0;
                        shad_state <= GET_FRAG;
                    end else begin
                        shad_state <= IDLE;
                    end
                end
                GET_FRAG:begin
                    shad_done <= 1'b0;
                    case (get_frag_state)
                        3'b000:begin
                            if(!fifo_empty)begin
                                read_fifo_en <= 1'b1;
                                get_frag_state <= 3'b001;                              
                            end else begin
                                read_fifo_en <= 1'b0;
                            end
                        end 
                        3'b001:begin
                            read_fifo_en <= 1'b0;
                            if(read_fifo_valid)begin
                                frag_data <= read_fifo_data;
                                get_frag_state <= 3'b010;
                            end
                        end
                        3'b010:begin
                            frag_x <= frag_data[27:18];
                            frag_y <= frag_data[17:8];
                            frag_R <= frag_data[7:5];
                            frag_G <= frag_data[4:2];
                            frag_B <= frag_data[1:0];
                            get_frag_state <= 3'b011;
                        end
                        3'b011:begin
                            regs_w_addr <= 1'b1;
                            regs_w_data <= frag_x;
                            regs_w_en <= 1'b1;
                            get_frag_state <= 3'b100;
                        end
                        3'b100:begin
                            regs_w_addr <= 3'd2;
                            regs_w_data <= frag_y;
                            regs_w_en <= 1'b1;
                            get_frag_state <= 3'b101;
                        end
                        3'b101:begin
                            regs_w_addr <= 3'd3;
                            regs_w_data <= frag_R;
                            regs_w_en <= 1'b1;
                            get_frag_state <= 3'b110;
                        end
                        3'b110:begin
                            regs_w_addr <= 3'd4;
                            regs_w_data <= frag_G;
                            regs_w_en <= 1'b1;
                            get_frag_state <= 3'b111;
                        end
                        3'b111:begin
                            regs_w_addr <= 3'd5;
                            regs_w_data <= frag_B;
                            regs_w_en <= 1'b1;
                            get_frag_state <= 4'b1000;
                        end
                        4'b1000:begin
                            regs_w_en <= 1'b0;
                            get_frag_state <= 1'b0;
                            shad_state <= OUT_PIXL;
                        end
                        default: get_frag_state <= 3'b000;
                    endcase
                end
                OUT_PIXL:begin
                    case(out_pixel_state)
                        4'd0:begin
                            regs_r_en   <= 1'b1;
                            regs_r_addr <= 1'd1;
                            out_pixel_state <= 1'd1;
                        end
                        4'd1:begin
                            regs_r_addr <= 3'd2;
                            out_pixel_state <= 3'd2;
                        end 
                        4'd2:begin
                            pixel_x <= regs_r_data;
                            regs_r_addr <= 3'd3;
                            out_pixel_state <= 3'd3;
                        end
                        4'd3:begin
                            pixel_y <= regs_r_data;
                            regs_r_addr <= 3'd4;
                            out_pixel_state <= 3'd4;
                        end
                        4'd4:begin
                            pixel_R <= regs_r_data;
                            regs_r_addr <= 3'd5;
                            out_pixel_state <= 3'd5;
                        end
                        4'd5:begin
                            pixel_G <= regs_r_data;
                            regs_r_en <= 1'b0;
                            out_pixel_state <= 3'd6;
                        end
                        4'd6:begin
                            pixel_B <= regs_r_data;
                            out_pixel_state <= 1'b0;
                            shad_state <= DONE;
                        end
                    endcase
                end
                DONE:begin
                    shad_busy <= 1'b0;
                    shad_done <= 1'b1;
                    shad_state <= GET_FRAG;
                end
            endcase
        end
    end

endmodule