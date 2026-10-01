`timescale 1ns/1ps
`ifdef SPACE_SCENE_STUB
module mgpu(
 input clk,rst,start,clear,
 input signed [31:0] vertex_x0,vertex_y0,vertex_z0,
 input [7:0] vertex_color0,
 input signed [31:0] vertex_x1,vertex_y1,vertex_z1,
 input [7:0] vertex_color1,
 input signed [31:0] vertex_x2,vertex_y2,vertex_z2,
 input [7:0] vertex_color2,
 input signed [31:0] m00,m01,m02,m03,
 input signed [31:0] m10,m11,m12,m13,
 input signed [31:0] m20,m21,m22,m23,
 input signed [31:0] m30,m31,m32,m33,
 input [7:0] clear_color,
 output reg gpu_busy,gpu_done,output wire gpu_error,
 input vga_clk,vga_rst,output [3:0] vga_r,vga_g,vga_b,output vga_hs,vga_vs);
 integer remaining=0;
 reg clearing;
 wire [823:0] command;
 reg [823:0] held;
 assign gpu_error=1'b0;
 assign {vga_r,vga_g,vga_b,vga_hs,vga_vs}=0;
 assign command={vertex_x0,vertex_y0,vertex_z0,vertex_x1,vertex_y1,vertex_z1,
                 vertex_x2,vertex_y2,vertex_z2,vertex_color0,vertex_color1,vertex_color2,
                 m00,m01,m02,m03,m10,m11,m12,m13,m20,m21,m22,m23,m30,m31,m32,m33};
 always @(posedge clk) begin
  if(rst) begin gpu_busy<=0;gpu_done<=0;remaining<=0;clearing<=0;end
  else begin
   gpu_done<=0;
   if(clear || start) begin
    if(gpu_busy) $fatal(1,"Overlapping commands");
    held<=command;
    clearing<=clear;
    remaining<=7;gpu_busy<=1;
   end else if(gpu_busy) begin
    if(!clearing && held!==command) $fatal(1,"Unstable vertex or matrix");
    if(remaining==0) begin gpu_busy<=0;gpu_done<=!clearing;end
    else remaining<=remaining-1;
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
   if({dut.gpu_vx0,dut.gpu_vy0,dut.gpu_vz0,dut.gpu_c0,
       dut.gpu_vx1,dut.gpu_vy1,dut.gpu_vz1,dut.gpu_c1,
       dut.gpu_vx2,dut.gpu_vy2,dut.gpu_vz2,dut.gpu_c2,
       dut.gpu_x0,dut.gpu_y0,dut.gpu_x1,dut.gpu_y1,dut.gpu_x2,dut.gpu_y2}!==dut.commands[dut.command_address])
       $fatal(1,"ROM latency/order mismatch");
   if(dut.gpu_x0>=640 || dut.gpu_x1>=640 || dut.gpu_x2>=640 ||
      dut.gpu_y0>=480 || dut.gpu_y1>=480 || dut.gpu_y2>=480) $fatal(1,"Coordinates");
   dx1=dut.gpu_x1-dut.gpu_x0;dy1=dut.gpu_y1-dut.gpu_y0;
   dx2=dut.gpu_x2-dut.gpu_x0;dy2=dut.gpu_y2-dut.gpu_y0;
   if(dx1*dy2-dy1*dx2==0) $fatal(1,"Degenerate triangle");
   count=count+1;
  end
  if(dut.demo_state==dut.HOLD && old_state!=dut.HOLD) begin
    if(count!=dut.COMMAND_COUNT) $fatal(1,"Command count %0d",count);
    $display("PASS vertex sequence: %0d commands, ROM, bounds, vertex/matrix stability and clear/done handshakes",count);
    $finish;
  end
  old_state=dut.demo_state;
 end
 initial begin #80;reset_n=1;#100000000;$fatal(1,"Timeout");end
endmodule
`endif
