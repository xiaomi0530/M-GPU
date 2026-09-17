set root [file normalize [file join [file dirname [info script]] ../..]]
set output [file join $root out vga_build]
open_checkpoint [file join $output routed.dcp]
reset_timing
read_xdc [file join $root MGPU.srcs constrs_1 new nexys_a7_vga.xdc]
report_timing_summary -report_unconstrained -file [file join $output timing.rpt]
report_drc -file [file join $output drc.rpt]
report_utilization -file [file join $output utilization.rpt]
report_clocks -file [file join $output clocks.rpt]
set setup_paths [get_timing_paths -delay_type max -max_paths 1]
set hold_paths [get_timing_paths -delay_type min -max_paths 1]
if {[get_property SLACK $setup_paths]<0 || [get_property SLACK $hold_paths]<0} {error "Timing failed"}
write_checkpoint -force [file join $output routed.dcp]
write_bitstream -force [file join $output nexys_a7_vga.bit]
