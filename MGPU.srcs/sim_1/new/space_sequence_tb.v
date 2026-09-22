`timescale 1ns/1ps
`ifdef SPACE_SCENE_STUB
module mgpu(input clk,rst,start,input [9:0] x0,y0,x1,y1,x2,y2,
 input [7:0] clor0,clor1,clor2,clear_color,output reg gpu_busy,gpu_done,
 input vga_clk,vga_rst,output [3:0] vga_r,vga_g,vga_b,output vga_hs,vga_vs);
 integer count=0,remaining=0;
 reg [83:0] held;
 assign {vga_r,vga_g,vga_b,vga_hs,vga_vs}=0;
 always @(posedge clk) begin
  if(rst) begin gpu_busy<=0;gpu_done<=0;count<=0;remaining<=0;end
  else begin
   gpu_done<=0;
   if(start) begin
    if(gpu_busy) $fatal(1,"Overlapping commands");
    held<={x0,y0,x1,y1,x2,y2,clor0,clor1,clor2};
    remaining<=7;gpu_busy<=1;count<=count+1;
   end else if(gpu_busy) begin
    if(held!=={x0,y0,x1,y1,x2,y2,clor0,clor1,clor2}) $fatal(1,"Unstable command");
    if(remaining==0) begin
     gpu_busy<=0;
     // Exercise the missed-completion fallback on every 97th command.
     gpu_done<=((count%97)!=0);
    end else remaining<=remaining-1;
   end
  end
 end
endmodule

module space_sequence_tb;
 reg clk=0,reset_n=0;
 always #5 clk=~clk;
 wire [3:0] r,g,b;wire hs,vs;
 top #(.GPU_CLK_DIV_LOG2(1),.LOGO_HOLD_MS(0),.STAGE_HOLD_MS(0),.CUBE_HOLD_MS(0))
  dut(clk,reset_n,1'b0,r,g,b,hs,vs);
 integer count=0,frames=0,dx1,dy1,dx2,dy2;
 reg [31:0] visited=0;
 reg [2:0] old_state=0;
 always @(posedge dut.gpu_clk) if(!dut.rst) begin
  if(dut.demo_start) begin
   if(!dut.logo_active && {dut.gpu_x0,dut.gpu_y0,dut.gpu_x1,dut.gpu_y1,dut.gpu_x2,dut.gpu_y2,
       dut.gpu_c0,dut.gpu_c1,dut.gpu_c2}!==dut.u_scene_rom.commands[dut.command_address])
       $fatal(1,"ROM latency/order mismatch");
   if(dut.gpu_x0>=640 || dut.gpu_x1>=640 || dut.gpu_x2>=640 ||
      dut.gpu_y0>=480 || dut.gpu_y1>=480 || dut.gpu_y2>=480) $fatal(1,"Coordinates");
   dx1=dut.gpu_x1-dut.gpu_x0;dy1=dut.gpu_y1-dut.gpu_y0;
   dx2=dut.gpu_x2-dut.gpu_x0;dy2=dut.gpu_y2-dut.gpu_y0;
   if(dx1*dy2-dy1*dx2==0) $fatal(1,"Degenerate triangle");
   if(dut.scene==2 && (dut.gpu_x0<60 || dut.gpu_x0>255 || dut.gpu_y0<55 || dut.gpu_y0>105 ||
      dut.gpu_x1<60 || dut.gpu_x1>255 || dut.gpu_y1<55 || dut.gpu_y1>105 ||
      dut.gpu_x2<60 || dut.gpu_x2>255 || dut.gpu_y2<55 || dut.gpu_y2>105))
      $fatal(1,"Satellite command escapes blank sky");
   count=count+1;
  end
  if(dut.demo_state==5 && old_state!=5 && dut.scene==2) begin
   visited[dut.animation_frame]=1;frames=frames+1;
   if(frames==33) begin
    if(visited!==32'hffffffff || dut.animation_frame!=0 || count!=19018)
      $fatal(1,"Loop/count coverage %0d",count);
    $display("PASS space sequence: %0d commands, 32 frames + wrap, ROM, bounds, missed-done recovery",count);
    $finish;
   end
  end
  old_state=dut.demo_state;
 end
 initial begin #80;reset_n=1;#100000000;$fatal(1,"Timeout");end
endmodule
`endif
