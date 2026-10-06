`timescale 1ns/1ps

module double_buffer_tb;
    reg clk=0,reset_n=0,button=0;
    always #5 clk=~clk;
    wire [3:0] r,g,b;
    wire hs,vs;
    top #(.BUTTON_FILTER_BITS(2),.LOGO_HOLD_MS(1),.TARGET_FPS(1000),.START_LOGO_FRAME(419))
        dut(clk,reset_n,button,r,g,b,hs,vs);

    integer writes=0,triangles=0,requests=0,swaps=0,acks=0;
    integer i,colored=0,scan_reads=0;
    integer frame_fd;
    reg previous_present=0,previous_done=0;
    reg old_front,allowed_swap,expected_front;
    reg [7:0] sampled;
    reg [11:0] expected_rgb;
    reg check_rgb;

    always @(posedge dut.gpu_clk) begin
        if(dut.rst)begin
            writes=0;triangles=0;requests=0;acks=0;
            previous_present=0;previous_done=0;
        end else begin
            if(dut.gpu_error) $fatal(1,"GPU rejected a triangle");
            if(!dut.studio_mode && dut.u_mgpu.rast_start &&
               {dut.u_mgpu.rast_x0,dut.u_mgpu.rast_y0,dut.u_mgpu.rast_x1,dut.u_mgpu.rast_y1,
                dut.u_mgpu.rast_x2,dut.u_mgpu.rast_y2}!==
               {dut.gpu_x0,dut.gpu_y0,dut.gpu_x1,dut.gpu_y1,dut.gpu_x2,dut.gpu_y2})
                $fatal(1,"Viewport scaling mismatch");
            if(dut.demo_clear)begin
                if(dut.gpu_busy || requests!=acks) $fatal(1,"Clear before swap acknowledgement");
                writes=0;triangles=0;
            end
            if(dut.u_mgpu.clear_reg)begin
                if(dut.u_mgpu.clear_count!==writes) $fatal(1,"Clear skipped an address");
                writes=writes+1;
            end
            if(dut.u_mgpu.clear_reg || dut.u_mgpu.shad_done)begin
                if(dut.u_mgpu.swap_pending || dut.u_mgpu.back_bank===dut.u_mgpu.front_bank)
                    $fatal(1,"Writing a displayed or submitted buffer");
            end
            if(dut.u_mgpu.shad_done &&
               (dut.u_mgpu.pixel_x>=dut.H_RES || dut.u_mgpu.pixel_y>=dut.V_RES))
                $fatal(1,"Pixel outside framebuffer");
            if(dut.demo_start)begin
                if(writes!=dut.u_mgpu.FB_PIXELS || dut.gpu_busy || requests!=acks)
                    $fatal(1,"Draw before clear or swap completion");
                triangles=triangles+1;
            end
            if(dut.demo_present)begin
                if(previous_present || dut.gpu_busy || requests!=acks || writes!=dut.u_mgpu.FB_PIXELS)
                    $fatal(1,"Invalid presentation request");
                if(triangles!=(dut.studio_mode ? dut.studio_count : dut.frame_count))
                    $fatal(1,"Presented an incomplete frame");
                requests=requests+1;
            end
            if(dut.u_mgpu.swap_pending && (dut.demo_start || dut.demo_clear))
                $fatal(1,"Submitted work during swap");
            if(dut.present_done)begin
                if(previous_done || requests!=acks+1 || dut.u_mgpu.swap_pending ||
                   dut.u_mgpu.back_bank===dut.u_mgpu.front_bank)
                    $fatal(1,"Invalid swap acknowledgement");
                acks=acks+1;
                colored=0;
                for(i=0;i<dut.u_mgpu.FB_PIXELS;i=i+1)begin
                    if(dut.u_mgpu.front_bank ? (dut.u_mgpu.frame_buffer1[i]!==8'h00) :
                                              (dut.u_mgpu.frame_buffer0[i]!==8'h00)) colored=colored+1;
                end
                if(dut.studio_mode ? colored!=0 : colored<1000)
                    $fatal(1,"Unexpected displayed image: %0d colored pixels",colored);
                $display("Presented frame %0d: bank=%0d, triangles=%0d, colored=%0d",
                         acks,dut.u_mgpu.front_bank,triangles,colored);
                if($test$plusargs("DUMP_FRAMES"))begin
                    frame_fd=$fopen($sformatf("presented_%0d.hex",acks),"w");
                    if(!frame_fd) $fatal(1,"Cannot write frame dump");
                    for(i=0;i<dut.u_mgpu.FB_PIXELS;i=i+1)
                        $fwrite(frame_fd,"%02x\n",dut.u_mgpu.front_bank ? dut.u_mgpu.frame_buffer1[i] : dut.u_mgpu.frame_buffer0[i]);
                    $fclose(frame_fd);
                end
            end
            previous_present=dut.demo_present;
            previous_done=dut.present_done;
        end
    end

    always @(posedge clk) begin
        if(dut.vga_rst)begin
            swaps=0;scan_reads=0;
        end else begin
            old_front=dut.u_mgpu.front_bank;
            allowed_swap=dut.u_mgpu.vblank_start && dut.u_mgpu.req_sync[1]!=old_front;
            expected_front=dut.u_mgpu.req_sync[1];
            if(dut.u_mgpu.vga_fb_read_en)begin
                if(dut.u_mgpu.vga_fb_addr!==
                   ((dut.u_mgpu.u_vga.scan_y/(480/dut.V_RES))*dut.H_RES+dut.u_mgpu.u_vga.scan_x/(640/dut.H_RES)))
                    $fatal(1,"Incorrect scaled address");
                sampled=old_front ? dut.u_mgpu.frame_buffer1[dut.u_mgpu.vga_fb_addr] :
                                    dut.u_mgpu.frame_buffer0[dut.u_mgpu.vga_fb_addr];
                scan_reads=scan_reads+1;
            end
            check_rgb=dut.u_mgpu.u_vga.phase==1;
            expected_rgb=(dut.u_mgpu.u_vga.scan_x<640 && dut.u_mgpu.u_vga.scan_y<480) ?
                {sampled[7:5],sampled[7],sampled[4:2],sampled[4],sampled[1:0],sampled[1:0]} : 12'h000;
            #1;
            if(dut.u_mgpu.front_bank!==old_front)begin
                if(!allowed_swap || dut.u_mgpu.front_bank!==expected_front)
                    $fatal(1,"Buffer changed outside vertical blank");
                swaps=swaps+1;
            end else if(allowed_swap) $fatal(1,"Pending frame was not swapped");
            if(check_rgb && {r,g,b}!==expected_rgb) $fatal(1,"VGA read wrong buffer");
        end
    end

    task reset_board;
        begin
            @(negedge clk);reset_n=0;
            repeat(30) @(negedge clk);
            if(!dut.rst || !dut.vga_rst || dut.u_mgpu.front_bank!==0 || dut.u_mgpu.back_bank!==1)
                $fatal(1,"Reset did not restore separate banks");
            reset_n=1;
        end
    endtask

    task press_button;
        begin
            @(negedge clk);button=1;
            repeat(40) @(negedge clk);
            button=0;
            repeat(40) @(negedge clk);
        end
    endtask

    initial begin
        reset_board;
        if(dut.studio_mode)begin
            wait(dut.studio_finished);
            @(negedge dut.gpu_clk);
            if(requests!=1 || acks!=1 || swaps!=1 || colored!=0)
                $fatal(1,"Empty scene did not present a cleared frame");
            $display("PASS DOUBLE BUFFER: empty scene presentation");
            $finish;
        end
        wait(writes==100);
        reset_board;
        wait(dut.u_mgpu.swap_pending);
        reset_board;
        wait(dut.u_mgpu.swap_pending);
        @(negedge clk);
        force dut.gpu_clk_locked=1'b0;
        repeat(30) @(negedge clk);
        if(!dut.rst || !dut.vga_rst || dut.u_mgpu.front_bank!==0 || dut.u_mgpu.back_bank!==1)
            $fatal(1,"Clock loss did not reset both domains");
        release dut.gpu_clk_locked;
        wait(dut.u_mgpu.swap_pending);
        press_button;
        wait(acks==1);
        wait(dut.paused && dut.demo_state==dut.HOLD);
        repeat(2000) @(negedge clk);
        if(requests!=1 || acks!=1 || swaps!=1) $fatal(1,"Paused frame changed");
        press_button;
        wait(acks==3);
        @(negedge dut.gpu_clk);
        if(swaps!=3 || requests!=3 || dut.logo_active || dut.animation_frame!=26 || scan_reads<dut.u_mgpu.FB_PIXELS)
            $fatal(1,"Animation or presentation sequence failed");
        $display("PASS DOUBLE BUFFER: real 40/100 MHz RTL, clear, complete frames, vblank swaps, VGA data, pause, reset and clock loss");
        $finish;
    end

    initial begin #300000000;$fatal(1,"Double-buffer timeout");end
endmodule

`ifdef STUDIO_SIMULATION
module studio_triangle_source(
    input clk,
    input [17:0] index,
    output [83:0] data,
    output mode,
    output [17:0] count
);
    assign data=0;
    assign mode=1'b1;
    assign count=0;
endmodule
`endif
