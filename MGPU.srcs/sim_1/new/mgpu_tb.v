`timescale 1ns / 1ps

// Testbench for the teaching MGPU core.
//
// It acts like a tiny CPU:
//   1. Provide triangle coordinates and colors.
//   2. Pulse start.
//   3. Wait for done.
//   4. Dump the framebuffer to out/framebuffer.hex.

module mgpu_tb;

    localparam H_RES = 640;
    localparam V_RES = 480;
    localparam FB_PIXELS = H_RES * V_RES;

    reg clk = 1'b0;
    reg rst = 1'b1;
    reg start = 1'b0;

    reg [9:0] x0;
    reg [9:0] y0;
    reg [7:0] clor0;

    reg [9:0] x1;
    reg [9:0] y1;
    reg [7:0] clor1;

    reg [9:0] x2;
    reg [9:0] y2;
    reg [7:0] clor2;

    reg [7:0] clear_color    = 8'h00;

    wire busy;
    wire done;

    integer fd;
    integer i;

    // 100 MHz-style clock for simulation: 10 ns period.
    always #5 clk = ~clk;

    mgpu #(
        .H_RES(H_RES),
        .V_RES(V_RES),
        .FB_PIXELS(FB_PIXELS),
        .FB_ADDR_W(19)
    ) u_mgpu (
        .clk(clk),
        .rst(rst),
        .start(start),
        .x0(x0),
        .y0(y0),
        .x1(x1),
        .y1(y1),
        .x2(x2),
        .y2(y2),
        .clor0(clor0),
        .clor1(clor1),
        .clor2(clor2),
        .clear_color(clear_color),
        .busy(busy),
        .done(done)
    );

    initial begin
        $display("MGPU simulation started.");
        repeat (5) @(posedge clk);
        rst <= 1'b0;

        @(posedge clk);
        x0 <= 10'd320;
        y0 <= 10'd80;
        clor0 <= 8'hE0;
        x1 <= 10'd60;
        y1 <= 10'd380;
        clor1 <= 8'h1C;
        x2 <= 10'd520;
        y2 <= 10'd300;
        clor2 <= 8'h03;
        @(posedge clk);
        start <= 1'b1;
        @(posedge clk);
        start <= 1'b0;

        wait (done == 1'b1);
        @(posedge clk);

        fd = $fopen("out/framebuffer.hex", "w");
        if (fd == 0) begin
            $display("ERROR: Could not open out/framebuffer.hex for writing.");
            $finish;
        end

        for (i = 0; i < FB_PIXELS; i = i + 1) begin
            $fwrite(fd, "%02x\n", u_mgpu.frame_buffer[i]);
        end

        $fclose(fd);
        $display("Framebuffer dumped to out/framebuffer.hex");
        $display("Run: python tools/view_framebuffer.py out/framebuffer.hex");

          $finish;
        end

endmodule
