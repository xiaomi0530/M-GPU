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
        .WIDTH      (32 ),
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
    localparam CHECK_FIFO   = 3'd1;
    localparam GET_FRAG     = 3'd2;
    localparam SHADE        = 3'd3;
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
            shad_done <= 1'b0;
            case(shad_state)
                IDLE:begin
                    if(shad_start) begin
                        shad_state <= CHECK_FIFO;
                    end else begin
                        shad_state <= IDLE;
                    end
                end
                CHECK_FIFO:begin             
                    shad_busy <= 1'b1;
                    if(fifo_empty)begin
                        shad_state <= CHECK_FIFO;
                    end else begin
                        read_fifo_en <= 1'b1;
                        shad_state <= GET_FRAG;
                    end
                end
                GET_FRAG:begin
                    shad_done <= 1'b0;
                    read_fifo_en <= 1'b0;
                    if(read_fifo_valid)begin
                        frag_data <= read_fifo_data;
                        shad_state <= SHADE;
                    end else begin
                        shad_state <= GET_FRAG;
                    end
                end
                SHADE:begin
                    frag_data[7:5] <= frag_data[7:5];
                    frag_data[4:2] <= frag_data[4:2];
                    frag_data[1:0] <= frag_data[1:0];
                    shad_state <= OUT_PIXL;
                end
                OUT_PIXL:begin
                    pixel_R <= frag_data[7:5];
                    pixel_G <= frag_data[4:2];
                    pixel_B <= frag_data[1:0];
                    pixel_x <= frag_data[27:18];
                    pixel_y <= frag_data[17:8];
                    shad_state <= DONE;
                end
                DONE:begin
                    shad_busy <= 1'b0;
                    shad_done <= 1'b1;
                    shad_state <= CHECK_FIFO;
                end
            endcase
        end
    end

endmodule