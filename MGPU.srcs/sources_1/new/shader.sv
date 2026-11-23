module shader(
    input logic clk,
    input logic rst,
    input logic fifo_empty,
    input logic [27:0] read_fifo_data,
    output logic read_fifo_en,
    input logic read_fifo_valid,
    input logic shad_start,
    output logic shad_busy,
    output logic shad_done,
    output logic [9:0] pixel_x,
    output logic [9:0] pixel_y,
    output logic [7:5] pixel_r,
    output logic [4:2] pixel_g,
    output logic [1:0] pixel_b
);

    typedef enum logic [2:0]{
        IDLE,
        CHECK_FIFO,
        GET_FRAG,
        SHADE,
        OUT_PIXL,
        DONE
    } state_t;
    state_t state;

    logic [27:0] frag_data;

    always_ff@(posedge clk)begin
        if(rst)begin
            shad_busy <= 1'b0;
            shad_done <= 1'b0;
            read_fifo_en <= 1'b0;
            state <= IDLE;
        end else begin
            shad_done <= 1'b0;
            case(state)
                IDLE:begin
                    if(shad_start)begin
                        state <= CHECK_FIFO;
                    end else begin
                        state <= IDLE;
                    end
                end
                CHECK_FIFO:begin
                    shad_busy <= 1'b1;
                    if(fifo_empty)begin
                        state <= CHECK_FIFO;
                    end else begin
                        read_fifo_en <= 1'b1;
                        state <= GET_FRAG;
                    end
                end
                GET_FRAG:begin
                    shad_done <= 1'b0;
                    read_fifo_en <= 1'b0;
                    if(read_fifo_valid)begin
                        frag_data <= read_fifo_data;
                        state <= SHADE;
                    end else begin
                        state <= GET_FRAG;
                    end
                end
                SHADE:begin
                    frag_data[7:5] <= frag_data[7:5];
                    frag_data[4:2] <= frag_data[4:2];
                    frag_data[1:0] <= frag_data[1:0];
                    state <= OUT_PIXL;
                end
                OUT_PIXL:begin
                    pixel_r <= frag_data[7:5];
                    pixel_g <= frag_data[4:2];
                    pixel_b <= frag_data[1:0];
                    pixel_x <= frag_data[27:18];
                    pixel_y <= frag_data[17:8];
                    state <= DONE;
                end
                DONE:begin
                    shad_busy <= 1'b0;
                    shad_done <= 1'b1;
                    state <= CHECK_FIFO;
                end
            endcase
        end
    end

endmodule
