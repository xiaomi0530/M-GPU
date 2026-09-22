`timescale 1ns / 1ps

// Independent timing/address model: two complete frames, all 256 colors,
// one-cycle synchronous RAM latency, blanking, pixel hold and mid-frame reset.
module vga_tb;
    reg clk = 0;
    always #5 clk = !clk;
    reg rst = 1;
    wire [18:0] addr;
    wire read_en;
    reg [7:0] data;
    wire [3:0] r, g, b;
    wire hs, vs;
    vga dut(clk, rst, addr, read_en, data, r, g, b, hs, vs);

    integer phase = 0, x = 0, y = 0, frames = 0;
    integer reads = 0, hs_pixels = 0, vs_pixels = 0;
    integer checks = 0;
    reg epoch = 0;
    reg [7:0] expected_data;
    reg [13:0] held = {12'b0, 2'b11};
    reg [13:0] expected;
    reg [255:0] seen = 0;
    function [7:0] pattern;
        input integer address;
        input bank;
        begin
            pattern = (address ^ (address >> 8)) ^ (bank ? 8'hA5 : 8'h00);
        end
    endfunction

    always @(posedge clk) begin
        if (rst) begin
            phase = 0; x = 0; y = 0; frames = 0;
            reads = 0; hs_pixels = 0; vs_pixels = 0;
            held = {12'b0, 2'b11};
            #1;
            if ({r,g,b,hs,vs} !== held || read_en !== 0)
                $fatal(1, "Reset output mismatch");
        end else begin
            if (read_en !== (phase == 0 && x < 640 && y < 480))
                $fatal(1, "Read enable mismatch at %0d,%0d phase %0d",x,y,phase);
            if (addr !== ((x < 640 && y < 480) ? y*640+x : 0))
                $fatal(1, "Address mismatch at %0d,%0d",x,y);
            if (read_en) begin
                data <= pattern(addr, epoch);
                expected_data = pattern(y*640+x, epoch);
                seen[expected_data] = 1;
                reads = reads + 1;
            end
            expected = held;
            if (phase == 1) begin
                expected[1] = !(x >= 656 && x < 752);
                expected[0] = !(y >= 490 && y < 492);
                if (x < 640 && y < 480) begin
                    // Arithmetic reference for 3->4 and 2->4 bit expansion.
                    expected[13:10] = (expected_data[7:5] * 15 + 3) / 7;
                    expected[9:6]   = (expected_data[4:2] * 15 + 3) / 7;
                    expected[5:2]   = expected_data[1:0] * 5;
                end else expected[13:2] = 0;
                if (!expected[1]) hs_pixels = hs_pixels + 1;
                if (!expected[0]) vs_pixels = vs_pixels + 1;
            end
            #1;
            if ({r,g,b,hs,vs} !== expected)
                $fatal(1,"RGB/sync/hold mismatch at %0d,%0d phase %0d got %h expected %h",
                       x,y,phase,{r,g,b,hs,vs},expected);
            held = expected;
            checks = checks + 1;
            if (phase == 3) begin
                if (x == 799) begin
                    x = 0;
                    if (y == 520) begin
                        y = 0;
                        frames = frames + 1;
                        if (reads != 307200 || hs_pixels != 96*521 || vs_pixels != 2*800)
                            $fatal(1,"Frame totals wrong: %0d %0d %0d",reads,hs_pixels,vs_pixels);
                        reads = 0; hs_pixels = 0; vs_pixels = 0;
                        epoch = !epoch;
                    end else y = y + 1;
                end else x = x + 1;
            end
            phase = (phase + 1) % 4;
        end
    end

    initial begin
        repeat (4) @(negedge clk);
        rst = 0;
        repeat (12345) @(negedge clk);
        rst = 1;
        repeat (3) @(negedge clk);
        rst = 0;
        wait (frames == 2);
        @(negedge clk);
        if (seen !== {256{1'b1}}) $fatal(1,"Not all RGB332 colors tested");
        $display("PASS VGA: two frames, 307200 reads/frame, all colors, live data, reset, sync and hold (%0d clocks)",checks);
        $finish;
    end
    initial begin
        #40000000;
        $fatal(1,"VGA test timeout");
    end
endmodule
