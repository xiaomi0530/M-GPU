# Configure the existing Vivado simulation set for the same top.v Studio flow.
# Run: vivado -mode batch -source tools/setup_top_simulation.tcl
set root [file normalize [file join [file dirname [info script]] ..]]
open_project [file join $root MGPU.xpr]
set tb [file join $root MGPU.srcs sim_1 new top_tb.v]
if {[llength [get_files -quiet $tb]]==0} {add_files -fileset sim_1 -norecurse $tb}
set_property used_in_synthesis false [get_files $tb]
set_property used_in_implementation false [get_files $tb]
set sim [get_filesets sim_1]
set_property top top_tb $sim
set defs [get_property verilog_define $sim]
if {[lsearch -exact $defs STUDIO_SIMULATION]<0} {lappend defs STUDIO_SIMULATION}
set_property verilog_define $defs $sim
set_property generic {GPU_CLK_DIV_LOG2=1 STAGE_HOLD_MS=1 CUBE_HOLD_MS=1} $sim
set output [file join $root out studio_top]
file mkdir $output
set_property -name xsim.simulate.xsim.more_options -value [list -testplusarg "TRACE=$output/framebuffer.trace" -testplusarg "FRAMEBUFFER=$output/framebuffer.hex" -testplusarg STOP_STAGE=logo] -objects $sim
set_property xsim.simulate.runtime all $sim
update_compile_order -fileset sim_1
close_project
