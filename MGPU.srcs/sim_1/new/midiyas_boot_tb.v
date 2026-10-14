`timescale 1ns/1ps
`ifdef SPACE_SCENE_STUB
module midiyas_boot_tb;
 parameter TARGET_FPS=10000;
 parameter LOGO_HOLD_MS=2;
 parameter START_FRAME=123;
 reg clk=0,reset_n=0,button=0;
 always #5 clk=~clk;
 wire [3:0] r,g,b;
 wire hs,vs;
 top #(.H_RES(640),.V_RES(480),.BUTTON_FILTER_BITS(2),.GPU_CLK_DIV_LOG2(1),.LOGO_HOLD_MS(LOGO_HOLD_MS),
       .STAGE_HOLD_MS(0),.CUBE_HOLD_MS(0),.TARGET_FPS(TARGET_FPS),.START_FRAME(START_FRAME))
  dut(clk,reset_n,button,r,g,b,hs,vs);
 integer cycle=0,commands=0,logo_frames=0,model_frames=0,transitions=0;
 integer first_clear=-1,last_clear=-1,dx1,dy1,dx2,dy2;
 integer saved_boot,saved_logo,saved_clear,run=0;
 bit visited[];
 bit logo_visited[];
 integer checked,slot_a,slot_b,matrix_item,value_a,value_b,value_lerp,model_group,fraction;
 reg [287:0] expected_matrix;
 reg [8:0] old_logo_frame=0;
 reg [3:0] old_state=0;
 reg old_valid=0,old_logo=0,old_busy=0,old_paused=0;
 reg [31:0] old_boot=0;
 reg first_model_pending=0;
 always @(posedge dut.gpu_clk) begin
  if(dut.rst) begin
   cycle=0;commands=0;logo_frames=0;model_frames=0;transitions=0;
   first_clear=-1;last_clear=-1;visited=new[dut.FRAME_COUNT];logo_visited=new[dut.LOGO_FRAME_COUNT];old_logo_frame=0;
   old_state=0;old_valid=0;old_logo=0;old_busy=0;old_paused=0;old_boot=0;
   first_model_pending=0;
  end else begin
   cycle=cycle+1;
   if(dut.gpu_error) $fatal(1,"GPU error");
   if(old_valid && old_logo && !dut.logo_active) begin
    if(old_state!=dut.HOLD || old_busy || old_paused) $fatal(1,"Unsafe logo transition");
    if(old_boot<dut.LOGO_TICKS) $fatal(1,"Logo duration too short");
    if(logo_frames<dut.LOGO_FRAME_COUNT || commands!=0 || old_logo_frame!=dut.LOGO_FRAME_COUNT-1)
       $fatal(1,"Incomplete logo animation");
    for(checked=0;checked<dut.LOGO_FRAME_COUNT;checked=checked+1)
     if(!logo_visited[checked]) $fatal(1,"Skipped logo phase %0d",checked);
    if(dut.animation_frame!=dut.INTRO_NEXT_FRAME || dut.command_address!=0) $fatal(1,"Character start frame");
    transitions=transitions+1;
    if(transitions!=1) $fatal(1,"Repeated intro transition");
    first_model_pending=1;
    $display("Logo transition run %0d: %0d frames, %0d active ticks, %0d wall ticks",run,logo_frames,old_boot,cycle-first_clear);
   end
   if(old_valid && !old_logo && dut.logo_active) $fatal(1,"Intro repeated without reset");
   if(dut.logo_active) begin
    if(dut.scene_frame!=dut.FRAME_COUNT+dut.logo_frame) $fatal(1,"Logo ROM frame");
    if(dut.animation_frame!=START_FRAME) $fatal(1,"Character advanced during intro");
   end else if(dut.scene_frame!=dut.animation_frame) $fatal(1,"Character ROM frame");
   if(dut.demo_state==dut.CLEAR_ISSUE) begin
    if(first_clear<0) begin
     first_clear=cycle;
     if(!dut.logo_active || dut.logo_frame!=0) $fatal(1,"Reset did not start intro");
    end
    if(last_clear>=0 && cycle-last_clear<dut.FRAME_TICKS) $fatal(1,"Frame period too short");
    if(first_model_pending) begin
     if(dut.logo_active || dut.animation_frame!=dut.INTRO_NEXT_FRAME) $fatal(1,"First character clear");
     first_model_pending=0;
    end
    last_clear=cycle;
   end
   if(dut.demo_clear && (dut.gpu_busy || commands!=0)) $fatal(1,"Clear before frame completion");
   if(dut.demo_start) begin
    if(dut.gpu_busy) $fatal(1,"Start while busy");
    if(dut.frame_count==0) $fatal(1,"Triangle submitted in empty frame");
    model_group=dut.command_group[dut.draw_order[dut.order_address]];
    if(dut.logo_active)begin
     slot_a=dut.MODEL_SLOT_COUNT+dut.logo_frame*dut.LOGO_GROUP_COUNT+model_group;
     slot_b=slot_a;
    end else begin
     slot_a=(dut.animation_frame/8)*dut.MODEL_GROUP_COUNT+model_group-16;
     slot_b=((dut.animation_frame/8+1)%dut.MODEL_KEY_COUNT)*dut.MODEL_GROUP_COUNT+model_group-16;
    end
    fraction=dut.logo_active ? 0 : dut.animation_frame%8;
    for(matrix_item=0;matrix_item<16;matrix_item=matrix_item+1)begin
     value_a=$signed(dut.matrices[dut.matrix_indices[slot_a]][matrix_item*18+:18]);
     value_b=$signed(dut.matrices[dut.matrix_indices[slot_b]][matrix_item*18+:18]);
     value_lerp=(value_b-value_a)*fraction;
     value_lerp=value_a+(value_lerp>>>3);
     expected_matrix[matrix_item*18+:18]=value_lerp;
    end
    if(dut.matrix_data!==expected_matrix) $fatal(1,"Interpolated matrix mismatch frame %0d group %0d",dut.scene_frame,model_group);
    if({dut.gpu_vx0,dut.gpu_vy0,dut.gpu_vz0,dut.gpu_c0,
        dut.gpu_vx1,dut.gpu_vy1,dut.gpu_vz1,dut.gpu_c1,
        dut.gpu_vx2,dut.gpu_vy2,dut.gpu_vz2,dut.gpu_c2}!==dut.commands[dut.draw_order[dut.order_address]])
        $fatal(1,"Command ROM mismatch");
    if(dut.gpu_x0>=640 || dut.gpu_x1>=640 || dut.gpu_x2>=640 ||
       dut.gpu_y0>=480 || dut.gpu_y1>=480 || dut.gpu_y2>=480) $fatal(1,"Coordinates");
    dx1=dut.gpu_x1-dut.gpu_x0;dy1=dut.gpu_y1-dut.gpu_y0;
    dx2=dut.gpu_x2-dut.gpu_x0;dy2=dut.gpu_y2-dut.gpu_y0;
    if(dx1*dy2-dy1*dx2==0) $fatal(1,"Degenerate triangle");
    commands=commands+1;
   end
   if(dut.demo_state==dut.HOLD && old_state!=dut.HOLD) begin
    if(dut.gpu_busy || commands!=dut.frame_count) $fatal(1,"Incomplete frame: %0d of %0d commands",commands,dut.frame_count);
    if(dut.logo_active) begin
     if(dut.logo_frame!=((logo_frames<dut.LOGO_FRAME_COUNT) ? logo_frames : dut.LOGO_FRAME_COUNT-1))
      $fatal(1,"Logo phase did not advance or hold at the final pose");
     logo_visited[dut.logo_frame]=1;
     logo_frames=logo_frames+1;
    end
    else begin
     if(transitions!=1 || dut.animation_frame!=((dut.INTRO_NEXT_FRAME+model_frames)%dut.FRAME_COUNT)) $fatal(1,"Character frame sequence");
     visited[dut.animation_frame]=1;
     model_frames=model_frames+1;
    end
    commands=0;
   end
   old_state=dut.demo_state;old_valid=1;old_logo=dut.logo_active;
   old_busy=dut.gpu_busy;old_paused=dut.paused;old_boot=dut.boot_elapsed;old_logo_frame=dut.logo_frame;
  end
 end
 task press_button;
  begin
   @(negedge clk);button=1;
   repeat(24) @(posedge clk);
   @(negedge clk);button=0;
   repeat(24) @(posedge clk);
  end
 endtask
 initial begin
  repeat(8) @(negedge clk);
  reset_n=1;
  wait(logo_frames>=2);
  press_button;
  wait(dut.paused && dut.demo_state==dut.HOLD);
  @(negedge dut.gpu_clk);
  saved_boot=dut.boot_elapsed;saved_logo=dut.logo_frame;saved_clear=last_clear;
  repeat(dut.LOGO_TICKS+100) @(negedge dut.gpu_clk);
  if(!dut.logo_active || dut.boot_elapsed!=saved_boot || dut.logo_frame!=saved_logo || last_clear!=saved_clear)
   $fatal(1,"Paused intro advanced");
  press_button;
  wait(!dut.paused);
  wait(model_frames==dut.FRAME_COUNT+1);
  for(checked=0;checked<dut.FRAME_COUNT;checked=checked+1)
   if(!visited[checked]) $fatal(1,"Skipped model phase %0d",checked);
  if(dut.animation_frame!=dut.INTRO_NEXT_FRAME) $fatal(1,"Character orbit wrap");
  @(negedge clk);run=1;reset_n=0;
  repeat(12) @(negedge clk);
  reset_n=1;
  wait(dut.rst==0);
  wait(logo_frames>=2);
  if(!dut.logo_active || transitions!=0) $fatal(1,"Intro missing after reset");
  wait(model_frames==1);
  if(transitions!=1 || dut.animation_frame!=dut.INTRO_NEXT_FRAME) $fatal(1,"Reset transition");
  $display("PASS MIDIYAS boot: all %0d intro phases, pause/resume, complete-frame transition into orbit %0d, %0d views + wrap, reset and interpolated ROM/handshake checks",dut.LOGO_FRAME_COUNT,dut.INTRO_NEXT_FRAME,dut.FRAME_COUNT);
  $finish;
 end
 initial begin #400000000;$fatal(1,"Timeout");end
endmodule
`endif
