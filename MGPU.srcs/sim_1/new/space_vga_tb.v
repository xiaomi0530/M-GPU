`timescale 1ns / 1ps

// Actual GPU writes and VGA reads run together. Compare the video to the byte
// visible at each synchronous read, across all three scenes and cube redraw.
module space_vga_tb;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset_n = 0;
    reg button = 0;
    wire [3:0] r,g,b;
    wire hs,vs;
    // Faster GPU clock in functional simulation only; hardware uses /16.
    top #(.BUTTON_FILTER_BITS(3), .GPU_CLK_DIV_LOG2(1),
          .STAGE_HOLD_MS(0), .CUBE_HOLD_MS(0)) dut(clk,reset_n,button,r,g,b,hs,vs);
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
    integer i,frame,fd,produced=0,retired=0;
    reg [7:0] expected_fb [0:307199];
    reg [1023:0] filename;
    always @(posedge dut.gpu_clk) if(!dut.rst) begin
        if(dut.demo_start && produced!=retired)
            $fatal(1,"Command began before writeback drained: %0d/%0d",produced,retired);
        if(dut.u_mgpu.fifo_rs_wen && !dut.u_mgpu.fifo_rs_full) produced=produced+1;
        if(dut.u_mgpu.shad_done) retired=retired+1;
    end
    task compare_frame;
        input [1023:0] path;
        begin
            $readmemh(path,expected_fb);
            for(i=0;i<307200;i=i+1)
                if(dut.u_mgpu.frame_buffer[i] !== expected_fb[i])
                    $fatal(1,"Pixel mismatch frame=%0d address=%0d actual=%h expected=%h",frame,i,dut.u_mgpu.frame_buffer[i],expected_fb[i]);
        end
    endtask
    initial begin
        repeat(8) @(negedge clk);reset_n=1;
        wait(!dut.rst);
        @(negedge dut.gpu_clk);dut.logo_active=0;
        wait(dut.scene==0 && dut.demo_state==5);
        @(negedge clk);
        if(dut.u_mgpu.frame_buffer[239*640+319]!==8'hFC) $fatal(1,"Calibration");
        $display("PASS calibration");
        wait(dut.scene==1 && dut.demo_state==5);
        @(negedge clk);
        compare_frame("out/lowpoly/background_expected.hex");
        $display("PASS complete space background: 307200 pixels");
        for(frame=0;frame<33;frame=frame+1) begin
            wait(dut.scene==2 && dut.animation_frame==(frame%32) && dut.demo_state==5);
            @(negedge clk);
            $sformat(filename,"out/lowpoly/frame_%02d_expected.hex",frame%32);
            compare_frame(filename);
            if(frame==8) begin
                fd=$fopen("out/lowpoly/actual_satellite.hex","w");
                for(i=0;i<307200;i=i+1) $fwrite(fd,"%02x\n",dut.u_mgpu.frame_buffer[i]);
                $fclose(fd);
            end
        end
        if(starts!=6218 || produced!=retired || reads==0 || colored==0) $fatal(1,"Coverage");
        $display("PASS space integration: %0d commands, %0d writes, %0d reads, 33 exact frames",starts,writes,reads);
        $finish;
    end
    initial begin #1500000000;$fatal(1,"Timeout scene=%0d state=%0d address=%0d",dut.scene,dut.demo_state,dut.command_address);end
endmodule
