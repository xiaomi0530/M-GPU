`timescale 1ns / 1ps
// Compile with -DTOP_SCENE_STUB and only top.v plus this file. The short
// GPU model isolates the sequencer/geometry so a full revolution is practical.
`ifdef TOP_SCENE_STUB
module mgpu (
    input clk,rst,start,
    input [9:0] x0,y0,x1,y1,x2,y2,
    input [7:0] clor0,clor1,clor2,clear_color,
    output reg gpu_busy,gpu_done,
    input vga_clk,vga_rst,
    output [3:0] vga_r,vga_g,vga_b,
    output vga_hs,vga_vs
);
    integer remaining;
    reg [83:0] held_command;
    assign {vga_r,vga_g,vga_b,vga_hs,vga_vs}=14'b11;
    always @(posedge clk) begin
        if (rst) begin gpu_busy<=0; gpu_done<=0; remaining<=0; end
        else begin
            gpu_done<=0;
            if (start) begin
                if (gpu_busy) $fatal(1,"Overlapping commands");
                gpu_busy<=1; remaining<=7;
                held_command<={x0,y0,x1,y1,x2,y2,clor0,clor1,clor2};
            end else if (gpu_busy) begin
                if ({x0,y0,x1,y1,x2,y2,clor0,clor1,clor2} !== held_command)
                    $fatal(1,"Inputs changed during triangle");
                if (remaining==0) begin gpu_busy<=0; gpu_done<=1; end
                else remaining<=remaining-1;
            end
        end
    end
endmodule

module top_sequence_tb;
    reg clk=0;
    always #5 clk=!clk;
    reg reset_n=0;
    wire [3:0] r,g,b;
    wire hs,vs;
    top #(.GPU_CLK_DIV_LOG2(1), .BUTTON_FILTER_BITS(3),
          .STAGE_HOLD_MS(1), .CUBE_HOLD_MS(1)) dut(clk,reset_n,1'b0,r,g,b,hs,vs);
    integer ticks=0,last_done=-10000,hold_ticks=0,commands=0,frame_count=0;
    integer previous_state=0,previous_scene=0;
    integer k,area,mx,my,mz,dx1,dy1,dx2,dy2;
    real theta,rx,rz,ey,ex;
    reg [63:0] angles=0;
    always @(posedge dut.gpu_clk) begin
        if (!dut.rst) begin
            ticks=ticks+1;
            if (dut.gpu_done) last_done=ticks;
            if (dut.demo_start) begin
                if (commands>0 && ticks-last_done < 2) $fatal(1,"Command overlap");
                if (dut.gpu_x0>=640 || dut.gpu_x1>=640 || dut.gpu_x2>=640 ||
                    dut.gpu_y0>=480 || dut.gpu_y1>=480 || dut.gpu_y2>=480)
                    $fatal(1,"Out-of-screen triangle");
                dx1=$signed({1'b0,dut.gpu_x1})-$signed({1'b0,dut.gpu_x0});
                dy1=$signed({1'b0,dut.gpu_y1})-$signed({1'b0,dut.gpu_y0});
                dx2=$signed({1'b0,dut.gpu_x2})-$signed({1'b0,dut.gpu_x0});
                dy2=$signed({1'b0,dut.gpu_y2})-$signed({1'b0,dut.gpu_y0});
                area=dx1*dy2-dy1*dx2;
                if (area==0) $fatal(1,"Degenerate triangle submitted");
                if (dut.scene==2 && dut.command_index>=2 && dut.command_index<26 && area>=0)
                    $fatal(1,"Hidden cube face submitted at angle %0d",dut.cube_angle);
                commands=commands+1;
            end
            if (dut.scene==2 && dut.command_index==0 && dut.demo_state==0) begin
                // Compare RTL fixed point to an independent real 3D rotation.
                theta=dut.cube_angle*6.283185307179586/64.0;
                for (k=0;k<8;k=k+1) begin
                    mx=(k&1) ? 96 : -96;
                    my=(k&2) ? 96 : -96;
                    mz=(k&4) ? 96 : -96;
                    rx=mx*$cos(theta)+mz*$sin(theta);
                    rz=-mx*$sin(theta)+mz*$cos(theta);
                    ex=320.0+rx;
                    ey=240.0-(my*$cos(3.141592653589793/6.0)-rz*0.5);
                    if (dut.cube_x[k]<ex-2 || dut.cube_x[k]>ex+2 ||
                        dut.cube_y[k]<ey-2 || dut.cube_y[k]>ey+2)
                        $fatal(1,"Projection mismatch angle=%0d vertex=%0d",dut.cube_angle,k);
                    if (dut.cube_x[k]<176 || dut.cube_x[k]>464 ||
                        dut.cube_y[k]<80 || dut.cube_y[k]>400)
                        $fatal(1,"Cube escapes clear rectangle");
                end
                angles[dut.cube_angle]=1;
            end
            if (dut.demo_state==4) begin
                hold_ticks=hold_ticks+1;
                if (previous_state!=4 && dut.scene==2) begin
                    frame_count=frame_count+1;
                    if (frame_count==65) begin
                        if (angles!=={64{1'b1}} || dut.cube_angle!==0)
                            $fatal(1,"Rotation did not wrap");
                        $display("PASS SEQUENCE: all 64 angles + wrap, projection, culling, holds, completion handshake and %0d commands",commands);
                        $finish;
                    end
                end
            end else if (previous_state==4) begin
                if (hold_ticks!=50000) $fatal(1,"Wrong completed-image hold: %0d",hold_ticks);
                if (previous_scene<2 && dut.scene!=previous_scene+1)
                    $fatal(1,"Scene order wrong");
                hold_ticks=0;
            end
            previous_state=dut.demo_state;
            previous_scene=dut.scene;
        end
    end
    initial begin
        repeat (8) @(negedge clk);
        reset_n=1;
        #250000000;
        $fatal(1,"Sequence timeout");
    end
endmodule
`endif
