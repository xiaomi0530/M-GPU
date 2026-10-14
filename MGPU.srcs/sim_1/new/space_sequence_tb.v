`timescale 1ns/1ps
`ifdef SPACE_SCENE_STUB
module mgpu #(
 parameter H_RES=640,V_RES=480
)(
 input clk,rst,start,clear,present,
 output reg present_done,
 input signed [17:0] vertex_x0,vertex_y0,vertex_z0,
 input [7:0] vertex_color0,
 input signed [17:0] vertex_x1,vertex_y1,vertex_z1,
 input [7:0] vertex_color1,
 input signed [17:0] vertex_x2,vertex_y2,vertex_z2,
 input [7:0] vertex_color2,
 input signed [17:0] m00,m01,m02,m03,
 input signed [17:0] m10,m11,m12,m13,
 input signed [17:0] m20,m21,m22,m23,
 input signed [17:0] m30,m31,m32,m33,
 input [7:0] clear_color,
 output reg gpu_busy,gpu_done,output wire gpu_error,
 input vga_clk,vga_rst,output [3:0] vga_r,vga_g,vga_b,output vga_hs,vga_vs);
 integer remaining=0;
 reg clearing,presenting;
 wire [473:0] command;
 reg [473:0] held;
 assign gpu_error=1'b0;
 assign {vga_r,vga_g,vga_b,vga_hs,vga_vs}=0;
 assign command={vertex_x0,vertex_y0,vertex_z0,vertex_x1,vertex_y1,vertex_z1,
                 vertex_x2,vertex_y2,vertex_z2,vertex_color0,vertex_color1,vertex_color2,
                 m00,m01,m02,m03,m10,m11,m12,m13,m20,m21,m22,m23,m30,m31,m32,m33};
 always @(posedge clk) begin
  if(rst) begin gpu_busy<=0;gpu_done<=0;present_done<=0;remaining<=0;clearing<=0;presenting<=0;end
  else begin
   gpu_done<=0;
   present_done<=0;
   if(clear || start || present) begin
    if(gpu_busy) $fatal(1,"Overlapping commands");
    held<=command;
    clearing<=clear;
    presenting<=present;
    remaining<=7;gpu_busy<=1;
   end else if(gpu_busy) begin
    if(!clearing && !presenting && held!==command) $fatal(1,"Unstable vertex or matrix");
    if(remaining==0) begin gpu_busy<=0;gpu_done<=!clearing && !presenting;present_done<=presenting;end
    else remaining<=remaining-1;
   end
  end
 end
endmodule

module space_sequence_tb;
 parameter TARGET_FPS=10000;
 reg clk=0,reset_n=0;
 always #5 clk=~clk;
 wire [3:0] r,g,b;wire hs,vs;
 top #(.H_RES(640),.V_RES(480),.GPU_CLK_DIV_LOG2(1),.LOGO_HOLD_MS(0),.STAGE_HOLD_MS(0),.CUBE_HOLD_MS(0),.TARGET_FPS(TARGET_FPS))
  dut(clk,reset_n,1'b0,r,g,b,hs,vs);
 integer count=0,frames=0,dx1,dy1,dx2,dy2;
 bit visited[];
 integer checked,slot_a,slot_b,matrix_item,value_a,value_b,value_lerp,model_group,fraction;
 reg [287:0] expected_matrix;
 reg [3:0] old_state=0;
 integer cycle=0,last_clear=-1,hold_cycle=0,expected_cycle=0;
 always @(posedge dut.gpu_clk) if(!dut.rst) begin
  cycle=cycle+1;
  if(dut.demo_state==dut.CLEAR_ISSUE) begin
   if(last_clear>=0) begin
    expected_cycle=last_clear+dut.FRAME_TICKS;
    if(hold_cycle+1>expected_cycle) expected_cycle=hold_cycle+1;
    if(cycle!=expected_cycle) $fatal(1,"Frame scheduling %0d expected %0d",cycle,expected_cycle);
   end
   last_clear=cycle;
  end
  if(dut.demo_start) begin
   model_group=dut.command_group[dut.draw_order[dut.order_address]]-16;
   slot_a=(dut.animation_frame/8)*dut.MODEL_GROUP_COUNT+model_group;
   slot_b=((dut.animation_frame/8+1)%dut.MODEL_KEY_COUNT)*dut.MODEL_GROUP_COUNT+model_group;
   fraction=dut.animation_frame%8;
   for(matrix_item=0;matrix_item<16;matrix_item=matrix_item+1)begin
    value_a=$signed(dut.matrices[dut.matrix_indices[slot_a]][matrix_item*18+:18]);
    value_b=$signed(dut.matrices[dut.matrix_indices[slot_b]][matrix_item*18+:18]);
    value_lerp=(value_b-value_a)*fraction;
    value_lerp=value_a+(value_lerp>>>3);
    expected_matrix[matrix_item*18+:18]=value_lerp;
   end
   if(dut.matrix_data!==expected_matrix) $fatal(1,"Interpolated matrix mismatch");
   if({dut.gpu_vx0,dut.gpu_vy0,dut.gpu_vz0,dut.gpu_c0,
       dut.gpu_vx1,dut.gpu_vy1,dut.gpu_vz1,dut.gpu_c1,
       dut.gpu_vx2,dut.gpu_vy2,dut.gpu_vz2,dut.gpu_c2}!==dut.commands[dut.draw_order[dut.order_address]])
       $fatal(1,"ROM latency/order mismatch");
   if(dut.gpu_x0>=640 || dut.gpu_x1>=640 || dut.gpu_x2>=640 ||
      dut.gpu_y0>=480 || dut.gpu_y1>=480 || dut.gpu_y2>=480) $fatal(1,"Coordinates");
   dx1=dut.gpu_x1-dut.gpu_x0;dy1=dut.gpu_y1-dut.gpu_y0;
   dx2=dut.gpu_x2-dut.gpu_x0;dy2=dut.gpu_y2-dut.gpu_y0;
   if(dx1*dy2-dy1*dx2==0) $fatal(1,"Degenerate triangle");
   count=count+1;
  end
  if(dut.demo_state==dut.HOLD && old_state!=dut.HOLD) begin
    hold_cycle=cycle;
    if(count!=dut.frame_count) $fatal(1,"Command count %0d",count);
    visited[dut.animation_frame]=1;
    frames=frames+1;count=0;
    if(frames==dut.FRAME_COUNT+1) begin
        for(checked=0;checked<dut.FRAME_COUNT;checked=checked+1)
         if(!visited[checked]) $fatal(1,"Skipped model phase %0d",checked);
        if(dut.animation_frame!=0) $fatal(1,"Orbit wrap");
        $display("PASS orbit sequence: %0d views + wrap, interpolated ROM, bounds, stable vertex/matrix and clear/done handshakes",dut.FRAME_COUNT);
        $finish;
    end
  end
  old_state=dut.demo_state;
 end
 initial begin visited=new[dut.FRAME_COUNT];#80;reset_n=1;#100000000;$fatal(1,"Timeout");end
endmodule
`endif
