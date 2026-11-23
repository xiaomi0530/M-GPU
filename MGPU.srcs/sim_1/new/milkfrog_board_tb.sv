`timescale 1ns / 1ps

module milkfrog_board_tb;

    `include "milkfrog_config.svh"
    parameter int CAPTURE_FRAMES = 1;

    logic clk = 1'b0;
    logic reset_n = 1'b0;
    logic [16:0] read_addr = 17'd0;
    logic [7:0] read_data;
    logic frame_complete;
    logic [15:0] completed_frame;
    logic front_bank;
    logic error_latched;
    logic [31:0] issue_count;
    logic [31:0] pixel_writes;
    logic [9:0] pending_pixels;
    logic fifo_empty;
    integer fd;
    integer index;
    integer capture;
    integer report_fd;

    always #5 clk = ~clk;

    milkfrog_board_sim

    #(
        .GPU_CLK_DIV_LOG2 (0 ),
        .TARGET_FPS       (30)
    )
    u_milkfrog_board_sim(
        .clk              (clk            ),
        .reset_n          (reset_n        ),
        .button           (1'b0           ),
        .read_addr        (read_addr      ),
        .read_data        (read_data      ),
        .frame_complete   (frame_complete ),
        .completed_frame  (completed_frame),
        .front_bank       (front_bank     ),
        .error_latched    (error_latched  ),
        .gpu_cycles       (               ),
        .draw_cycles      (               ),
        .issue_count      (issue_count    ),
        .pixel_writes     (pixel_writes   ),
        .pending_pixels   (pending_pixels ),
        .fifo_empty       (fifo_empty     ),
        .paused           (               ),
        .holding          (               ),
        .animation_length (               )
    );

    initial begin
        u_milkfrog_board_sim.u_milkfrog_top.u_mgpu.u_rasterizer.frag_valid = 1'b0;
        repeat(40) @(negedge clk);
        reset_n = 1'b1;
        report_fd = $fopen("presentation_times.csv", "w");
        if(!report_fd) $fatal(1, "Cannot open presentation timing report");
        $fwrite(report_fd, "capture,time_ns,animation_frame\n");
        for(capture = 0; capture < CAPTURE_FRAMES; capture = capture + 1)begin
            wait (frame_complete);
            @(negedge clk);
            if(error_latched || completed_frame != capture % FRAME_COUNT || front_bank != !(capture % 2))
                $fatal(1, "Board frame sequence failed");
            if(pending_pixels != 0 || !fifo_empty) $fatal(1, "Board presented before draining fragments");
            $fwrite(report_fd, "%0d,%0.3f,%0d\n", capture, $realtime, completed_frame);
            if(capture == 0) fd = $fopen("board_icarus.hex", "w");
            else fd = $fopen($sformatf("board_icarus_%04d.hex", capture), "w");
            if(!fd) $fatal(1, "Cannot open board framebuffer");
            for(index = 0; index < 76800; index = index + 1)begin
                read_addr = index[16:0];
                #1;
                $fwrite(fd, "%02x\n", read_data);
            end
            $fclose(fd);
            $display("PASS BOARD ICARUS 40MHz: capture=%0d triangles=%0d pixels=%0d", capture, issue_count,
                     pixel_writes);
            wait (!frame_complete);
        end
        $fclose(report_fd);
        $finish;
    end

    initial begin
        #2000000000;
        $fatal(1, "Board first frame timeout");
    end

endmodule
