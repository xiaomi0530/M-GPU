module vga #(
    parameter int FB_WIDTH = 640,
    parameter int FB_HEIGHT = 480
)(
    input logic clk,
    input logic rst,
    output logic [18:0] fb_addr,
    output logic fb_read_en,
    input logic [7:0] fb_data,
    output logic [3:0] vga_r,
    output logic [3:0] vga_g,
    output logic [3:0] vga_b,
    output logic vga_hs,
    output logic vga_vs,
    output logic vblank_start
);

    localparam int H_ACTIVE = 640;
    localparam int H_FRONT = 16;
    localparam int H_SYNC = 96;
    localparam int H_BACK = 48;
    localparam int H_TOTAL = H_ACTIVE + H_FRONT + H_SYNC + H_BACK;
    localparam int V_ACTIVE = 480;
    localparam int V_FRONT = 10;
    localparam int V_SYNC = 2;
    localparam int V_BACK = 29;
    localparam int V_TOTAL = V_ACTIVE + V_FRONT + V_SYNC + V_BACK;

    logic [1:0] phase;
    logic [9:0] scan_x;
    logic [9:0] scan_y;
    logic active;

    assign active = (scan_x < H_ACTIVE) && (scan_y < V_ACTIVE);

    assign fb_addr = active ? ((scan_y / (V_ACTIVE / FB_HEIGHT)) * FB_WIDTH + scan_x / (H_ACTIVE / FB_WIDTH)) : 19'd0;
    assign fb_read_en = !rst && active && (phase == 2'd0);

    assign vblank_start = !rst && (scan_x == 10'b0) && (scan_y == V_ACTIVE) && (phase == 2'd0);

    always_ff@(posedge clk)begin
        if(rst)begin
            phase <= 2'd0;
            scan_x <= 10'd0;
            scan_y <= 10'd0;
            vga_r <= 4'd0;
            vga_g <= 4'd0;
            vga_b <= 4'd0;
            vga_hs <= 1'b1;
            vga_vs <= 1'b1;
        end else begin
            phase <= phase + 1'b1;

            if(phase == 2'd1)begin
                vga_hs <= !((scan_x >= H_ACTIVE + H_FRONT) && (scan_x < H_ACTIVE + H_FRONT + H_SYNC));
                vga_vs <= !((scan_y >= V_ACTIVE + V_FRONT) && (scan_y < V_ACTIVE + V_FRONT + V_SYNC));
                if(active)begin

                    vga_r <= {fb_data[7:5], fb_data[7]};
                    vga_g <= {fb_data[4:2], fb_data[4]};
                    vga_b <= {fb_data[1:0], fb_data[1:0]};
                end else begin
                    vga_r <= 4'd0;
                    vga_g <= 4'd0;
                    vga_b <= 4'd0;
                end
            end

            if(phase == 2'd3)begin
                if(scan_x == H_TOTAL - 1)begin
                    scan_x <= 10'd0;
                    if(scan_y == V_TOTAL - 1) scan_y <= 10'd0;
                    else scan_y <= scan_y + 1'b1;
                end else begin
                    scan_x <= scan_x + 1'b1;
                end
            end
        end
    end
endmodule
