# Run from the project root:
# vivado -mode batch -source tools/build_vga.tcl
# Uses a separate non-project build; does not reset existing project runs.
set root [file normalize [file join [file dirname [info script]] ..]]
set output [file join $root out vga_current]
file mkdir $output
cd $output
set_param general.maxThreads 4
read_verilog [glob [file join $root MGPU.srcs sources_1 new *.v]]
read_xdc [file join $root MGPU.srcs constrs_1 new nexys_a7_vga.xdc]
synth_design -top top -part xc7a100tcsg324-1
report_utilization -file [file join $output utilization_synth.rpt]
opt_design
place_design
phys_opt_design
route_design
report_timing_summary -report_unconstrained -file [file join $output timing.rpt]
report_drc -file [file join $output drc.rpt]
report_utilization -file [file join $output utilization.rpt]
report_clocks -file [file join $output clocks.rpt]
# The original input-based RAM initial block is not constant at elaboration.
# Verify the actual mapped framebuffer initialization instead of assuming it.
set framebuffer_rams [get_cells -hier -filter {REF_NAME =~ RAMB* && NAME =~ *frame_buffer*}]
if {[llength $framebuffer_rams] == 0} {error "Framebuffer was not mapped to block RAM"}
set init_words 0
foreach ram $framebuffer_rams {
    foreach prop [list_property $ram] {
        if {[regexp {^INIT(P)?_[0-9A-F]{2}$} $prop]} {
            set value [get_property $prop $ram]
            if {![regexp -nocase {^256'h0+$} $value]} {
                error "Unexpected framebuffer initialization: $ram $prop $value"
            }
            incr init_words
        }
    }
}
if {$init_words == 0} {error "No framebuffer initialization properties found"}
set audit [open [file join $output framebuffer_init.rpt] w]
puts $audit "PASS: [llength $framebuffer_rams] framebuffer BRAM primitives; $init_words INIT/INITP words are zero."
close $audit
write_checkpoint -force [file join $output routed.dcp]
set setup_paths [get_timing_paths -delay_type max -max_paths 1]
set hold_paths [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup_paths] == 0 || [llength $hold_paths] == 0} {
    error "No timing paths found"
}
if {[get_property SLACK $setup_paths] < 0 || [get_property SLACK $hold_paths] < 0} {
    error "Timing failed; see out/vga_current/timing.rpt (original GPU RTL was not modified)"
}
write_bitstream -force [file join $output nexys_a7_vga.bit]
