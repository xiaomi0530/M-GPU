`timescale 1ns/1ps
// Studio simulation root. The design-under-test is always top.v.
// Icarus: -DSTUDIO_SIMULATION -s top_tb (include every source_1/new/*.v).
// No forced internal signals, direct framebuffer writes, or alternate clocks.
module top_tb;
    parameter GPU_CLK_DIV_LOG2=4;
    parameter STAGE_HOLD_MS=4000;
    parameter CUBE_HOLD_MS=40;
    reg clk=0,reset_n=0;
    always #5 clk=~clk;
    wire [3:0] r,g,b;wire hs,vs;
    top #(.GPU_CLK_DIV_LOG2(GPU_CLK_DIV_LOG2),.LOGO_HOLD_MS(STAGE_HOLD_MS),
          .STAGE_HOLD_MS(STAGE_HOLD_MS),.CUBE_HOLD_MS(CUBE_HOLD_MS))
        dut(clk,reset_n,1'b0,r,g,b,hs,vs);
    integer trace_fd,fd,i,triangles=0,pixels=0,fragments=0;
    integer scan_reads=0,completed_frames=0,requested_frames=1;
    integer clear_pixels=0;
    reg active=0;
    reg [2:0] previous_state=0;
    reg [8191:0] trace_path,frame_path,stop_stage;
    reg [7:0] sampled;
    reg [11:0] expected_video;
    reg check_video;

    always @(posedge dut.gpu_clk) if(!dut.rst) begin
        if(dut.u_mgpu.clear_reg) begin
            if(active || fragments!=pixels || dut.demo_start || dut.u_mgpu.shad_done)
                $fatal(1,"Clear overlaps drawing/writeback");
            if(dut.u_mgpu.clear_count>=307200) $fatal(1,"Clear address out of bounds");
            clear_pixels=clear_pixels+1;
            $fwrite(trace_fd,"P %0d 0 %0d %0d %02x\n",$time,
                    dut.u_mgpu.clear_count%640,dut.u_mgpu.clear_count/640,dut.u_mgpu.clear_color);
        end
        if(dut.demo_start) begin
            if(active || fragments!=pixels) $fatal(1,"Overlapping/undrained command");
            triangles=triangles+1;active=1;
            $fwrite(trace_fd,"B %0d %0d %0d %0d %0d %0d %0d %0d\n",$time,triangles,
                    dut.gpu_x0,dut.gpu_y0,dut.gpu_x1,dut.gpu_y1,dut.gpu_x2,dut.gpu_y2);
            $fflush(trace_fd);
        end
        if(dut.u_mgpu.fifo_rs_wen && !dut.u_mgpu.fifo_rs_full) fragments=fragments+1;
        if(dut.u_mgpu.shad_done) begin
            if(!active || dut.u_mgpu.pixel_x>=640 || dut.u_mgpu.pixel_y>=480)
                $fatal(1,"Unowned/out-of-bounds pixel");
            pixels=pixels+1;
            $fwrite(trace_fd,"P %0d %0d %0d %0d %02x\n",$time,triangles,
                    dut.u_mgpu.pixel_x,dut.u_mgpu.pixel_y,
                    {dut.u_mgpu.pixel_R,dut.u_mgpu.pixel_G,dut.u_mgpu.pixel_B});
            if((pixels%256)==0) $fflush(trace_fd);
        end
        if(dut.demo_state==dut.ADVANCE && active) begin
            if(fragments!=pixels || !dut.u_mgpu.fifo_rs_empty)
                $fatal(1,"Completion before writeback");
            $fwrite(trace_fd,"E %0d %0d\n",$time,triangles);$fflush(trace_fd);active=0;
        end
        if(!dut.logo_active && dut.scene==2 && dut.demo_state==dut.HOLD && previous_state!=dut.HOLD)
            completed_frames=completed_frames+1;
        previous_state=dut.demo_state;
    end

    // Verify the real scanout alongside writeback, including blanking.
    always @(posedge clk) if(!dut.vga_rst) begin
        if(dut.u_mgpu.vga_fb_read_en) begin
            sampled=dut.u_mgpu.frame_buffer[dut.u_mgpu.vga_fb_addr];scan_reads=scan_reads+1;
        end
        check_video=dut.u_mgpu.u_vga.phase==1;
        expected_video=(dut.u_mgpu.u_vga.scan_x<640 && dut.u_mgpu.u_vga.scan_y<480) ?
            {sampled[7:5],sampled[7],sampled[4:2],sampled[4],sampled[1:0],sampled[1:0]} : 12'h000;
        #1;
        if(check_video && {r,g,b}!==expected_video) $fatal(1,"VGA scanout mismatch");
    end

    task finish_recording;
        begin
            @(negedge dut.gpu_clk);
            if(active || fragments!=pixels) $fatal(1,"Recording ended with pending pixels");
            fd=$fopen(frame_path,"w");
            if(!fd) $fatal(1,"Cannot open framebuffer output");
            for(i=0;i<307200;i=i+1) $fwrite(fd,"%02x\n",dut.u_mgpu.frame_buffer[i]);
            $fclose(fd);
            $fwrite(trace_fd,"D %0d %0d %0d\n",$time,triangles,pixels+clear_pixels);
            $fflush(trace_fd);$fclose(trace_fd);
            $display("PASS TOP STUDIO: %0d triangles, %0d writes, %0d VGA reads",triangles,pixels,scan_reads);
            $display("Clear engine: %0d writes",clear_pixels);
            $finish;
        end
    endtask

    initial begin
        trace_path="out/framebuffer.trace";frame_path="out/framebuffer.hex";stop_stage="animation";
        if($value$plusargs("TRACE=%s",trace_path)) begin end
        if($value$plusargs("FRAMEBUFFER=%s",frame_path)) begin end
        if($value$plusargs("STOP_STAGE=%s",stop_stage)) begin end
        if($value$plusargs("FRAMES=%d",requested_frames)) begin end
        if(requested_frames<1 || requested_frames>1024) $fatal(1,"Invalid frame count");
        if(stop_stage!="logo" && stop_stage!="calibration" && stop_stage!="background" && stop_stage!="animation")
            $fatal(1,"Invalid STOP_STAGE");
        trace_fd=$fopen(trace_path,"w");
        if(!trace_fd) $fatal(1,"Cannot open trace; create output directory first");
        $fwrite(trace_fd,"MGPU_TRACE 1 640 480 00 ns\n");
        $fwrite(trace_fd,"# DUT top.v GPU_DIV_LOG2=%0d HOLD_MS=%0d\n",GPU_CLK_DIV_LOG2,STAGE_HOLD_MS);
        $fflush(trace_fd);
        repeat(8) @(negedge clk);reset_n=1;
        wait(!dut.rst);
`ifdef STUDIO_SIMULATION
        if(dut.studio_mode) begin
            wait(dut.studio_finished);finish_recording;
        end else
`endif
        begin
            case(stop_stage)
                "logo": wait(dut.logo_active && dut.demo_state==dut.HOLD);
                "calibration": wait(!dut.logo_active && dut.scene==0 && dut.demo_state==dut.HOLD);
                "background": wait(!dut.logo_active && dut.scene==1 && dut.demo_state==dut.HOLD);
                default: wait(completed_frames>=requested_frames);
            endcase
            finish_recording;
        end
    end
    initial begin #120000000000;$fatal(1,"Top Studio simulation timeout");end
endmodule

// Sim-only source feeds top's FETCH/LOAD/ISSUE/WAIT_GPU state machine.
module studio_triangle_source(input clk,input [17:0] index,output reg [83:0] data,
                             output reg active,output reg [17:0] count);
    localparam DEFAULT_IMAGE_SCENE = "";
    reg [8191:0] filename;
    reg [83:0] commands [0:160001];
    integer fd,n,fields,total,x0,y0,x1,y1,x2,y2;
    reg [7:0] c0,c1,c2;
    always @(posedge clk) if(active && index<count) data<=commands[index];
    initial begin
        active=0;count=0;data=0;filename=DEFAULT_IMAGE_SCENE;
        if($value$plusargs("STUDIO_SCENE=%s",filename)) begin end
        if(filename!="") begin
            fd=$fopen(filename,"r");
            if(!fd) $fatal(1,"Cannot open Studio scene: %0s",filename);
            fields=$fscanf(fd,"%d\n",total);
            if(fields!=1 || total<0 || total>160002) $fatal(1,"Invalid scene count");
            for(n=0;n<total;n=n+1) begin
                fields=$fscanf(fd,"%d %d %d %d %d %d %h %h %h\n",x0,y0,x1,y1,x2,y2,c0,c1,c2);
                if(fields!=9 || x0<0 || x0>=640 || x1<0 || x1>=640 || x2<0 || x2>=640 ||
                   y0<0 || y0>=480 || y1<0 || y1>=480 || y2<0 || y2>=480 ||
                   (x1-x0)*(y2-y0)==(y1-y0)*(x2-x0) || (^{c0,c1,c2})===1'bx)
                    $fatal(1,"Invalid Studio triangle %0d",n);
                commands[n]={x0[9:0],y0[9:0],x1[9:0],y1[9:0],x2[9:0],y2[9:0],c0,c1,c2};
            end
            $fclose(fd);count=total;active=1;
        end
    end
endmodule
