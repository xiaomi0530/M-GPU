`timescale 1ns / 1ps

// Actual GPU writes and VGA reads run together. Compare the video to the byte
// visible at each synchronous read, across all three scenes and cube redraw.
module top_vga_tb;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset_n = 0;
    reg button = 0;
    wire [3:0] r,g,b;
    wire hs,vs;
    // Faster GPU clock in functional simulation only; hardware uses /16.
    top #(.BUTTON_FILTER_BITS(3), .GPU_CLK_DIV_LOG2(1),
          .STAGE_HOLD_MS(1), .CUBE_HOLD_MS(1)) dut(clk,reset_n,button,r,g,b,hs,vs);
    integer reads = 0, writes = 0, starts = 0, colored = 0;
    integer frames = 0;
    reg [7:0] sampled;
    reg [11:0] expected;
    reg check_pixel;
    reg active_pixel;
    always @(posedge dut.gpu_clk) begin
        if (!dut.rst) begin
            if (dut.demo_start) starts = starts + 1;
            if (dut.u_mgpu.shad_done) writes = writes + 1;
        end
    end
    always @(posedge clk) begin
        if (!dut.vga_rst) begin
            if (dut.u_mgpu.vga_fb_read_en) begin
                sampled = dut.u_mgpu.frame_buffer[dut.u_mgpu.vga_fb_addr];
                reads = reads + 1;
            end
            check_pixel = dut.u_mgpu.u_vga.phase == 1;
            active_pixel = dut.u_mgpu.u_vga.scan_x < 640 && dut.u_mgpu.u_vga.scan_y < 480;
            if (dut.u_mgpu.u_vga.phase == 3 &&
                dut.u_mgpu.u_vga.scan_x == 799 && dut.u_mgpu.u_vga.scan_y == 520)
                frames = frames + 1;
            expected = active_pixel ? {sampled[7:5],sampled[7],sampled[4:2],sampled[4],sampled[1:0],sampled[1:0]} : 12'h000;
            #1;
            if (check_pixel) begin
                if ((^expected) === 1'bx || {r,g,b} !== expected)
                    $fatal(1,"Framebuffer/video mismatch: got %h expected %h",{r,g,b},expected);
                if (expected != 0) colored = colored + 1;
            end
        end
    end
    integer fd, i;
    task dump_frame;
        input [1023:0] path;
        begin
            fd=$fopen(path,"w");
            if (!fd) $fatal(1,"Cannot create frame dump");
            for (i=0;i<307200;i=i+1)
                $fwrite(fd,"%02x\n",dut.u_mgpu.frame_buffer[i]);
            $fclose(fd);
        end
    endtask
    initial begin
        repeat (8) @(negedge clk);
        reset_n = 1;
`ifdef HOLO_CUBE_ONLY
        // Focused integration run: a nonzero old image tests scene-entry clear.
        wait(!dut.rst);
        @(negedge dut.gpu_clk);
        dut.scene=2; dut.demo_state=5; dut.command_index=0;
        for(i=0;i<307200;i=i+1) dut.u_mgpu.frame_buffer[i]=8'hA5;
`else
        wait (dut.scene == 0 && dut.demo_state == 4);
        @(negedge clk);
        if (dut.u_mgpu.frame_buffer[239*640+319] !== 8'hFC ||
            dut.u_mgpu.frame_buffer[160*640+240] !== 8'hFF ||
            dut.u_mgpu.frame_buffer[9*640+8] !== 8'hFF ||
            dut.u_mgpu.frame_buffer[0] !== 0)
            $fatal(1,"Calibration target locations/colors wrong");
        dump_frame("out/holo/target.hex");
        $display("PASS calibration target");
        wait (dut.scene == 1 && dut.demo_state == 4);
        @(negedge clk);
        if (dut.u_mgpu.frame_buffer[8*640+8] !== 0 ||
            dut.u_mgpu.frame_buffer[80*640+320] !== 8'hE0 ||
            dut.u_mgpu.frame_buffer[400*640+120] !== 8'h1C ||
            dut.u_mgpu.frame_buffer[400*640+520] !== 8'h03)
            $fatal(1,"Triangle scene/clear wrong");
        dump_frame("out/holo/triangle.hex");
        $display("PASS original triangle and scene clearing");
`endif
        wait (dut.scene == 2 && dut.cube_angle == 0 && dut.demo_state == 4);
        @(negedge clk);
        if (dut.u_mgpu.frame_buffer[400*640+120] !== 0 ||
            dut.u_mgpu.frame_buffer[240*640+320] === 8'h00 ||
            dut.u_mgpu.frame_buffer[65*640+60] !== 8'h5F)
            $fatal(1,"Cube scene/clear wrong");
        dump_frame("out/holo/cube_00.hex");
        wait (dut.scene == 2 && dut.cube_angle == 1 && dut.demo_state == 4);
        @(negedge clk);
        dump_frame("out/holo/cube_01.hex");
`ifdef HOLO_CUBE_ONLY
        if (starts != 56 || colored == 0 || frames == 0)
`else
        if (starts != 83 || colored == 0 || frames == 0)
`endif
            $fatal(1,"Integration coverage failed starts=%0d writes=%0d reads=%0d colored=%0d",starts,writes,reads,colored);
        $display("PASS TOP SCENES: %0d commands, %0d GPU writes, %0d live reads, %0d colored scanout pixels",starts,writes,reads,colored);
        $finish;
    end
    initial begin
        #900000000;
        $fatal(1,"Top integration timeout, scene=%0d state=%0d command=%0d",dut.scene,dut.demo_state,dut.command_index);
    end
endmodule
