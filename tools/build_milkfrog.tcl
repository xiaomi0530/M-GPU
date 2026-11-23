set root [file normalize [file join [file dirname [info script]] ..]]
set rom [file join $root assets milkfrog v1_fixed rom]
set output [file join $root out milkfrog_board]
set mode full
if {$argc >= 1} {set rom [file normalize [lindex $argv 0]]}
if {$argc >= 2} {set output [file normalize [lindex $argv 1]]}
if {$argc >= 3} {set mode [lindex $argv 2]}
file mkdir $output
foreach name {milkfrog_config.svh milkfrog_vertex.mem milkfrog_triangle.mem milkfrog_order.mem milkfrog_order_meta.mem milkfrog_matrix.mem milkfrog_timeline.mem} {
    set source [file join $rom $name]
    if {![file isfile $source]} {error "Missing scene ROM: $source"}
    file copy -force $source [file join $output $name]
}
set scene_top [file join $output milkfrog_top.sv]
file copy -force [file join $root MGPU.srcs sources_1 demo milkfrog_top.sv] $scene_top
cd $output
set_param general.maxThreads 4
foreach name {mgpu.sv vertex_shader.sv rasterizer.sv fifo.sv shader.sv divider_signed.sv divider_q16_16.sv vga.sv gpu_clock.sv} {
    read_verilog -sv [file join $root MGPU.srcs sources_1 new $name]
}
read_verilog -sv $scene_top
set_property include_dirs [list $output $rom] [current_fileset]
read_xdc [file join $root MGPU.srcs constrs_1 new nexys_a7_vga.xdc]
synth_design -top milkfrog_top -part xc7a100tcsg324-1
report_utilization -file [file join $output utilization_synth.rpt]
set bram36 [get_cells -hier -filter {REF_NAME =~ RAMB36*}]
set bram18 [get_cells -hier -filter {REF_NAME =~ RAMB18*}]
set bram_tiles [expr {[llength $bram36] + 0.5 * [llength $bram18]}]
if {$bram_tiles > 135} {error "Scene exceeds xc7a100t BRAM budget: $bram_tiles > 135"}
if {$mode eq "synth"} {
    write_checkpoint -force [file join $output synthesized.dcp]
    set audit [open [file join $output synthesis_validation.txt] w]
    puts $audit "PASS synthesis: $bram_tiles BRAM tiles / 135"
    close $audit
    return
}
opt_design
place_design
phys_opt_design
route_design
report_timing_summary -report_unconstrained -file [file join $output timing.rpt]
report_drc -file [file join $output drc.rpt]
set drc_errors [get_drc_violations -quiet -filter {SEVERITY == Error}]
if {[llength $drc_errors] != 0} {error "DRC has errors: $drc_errors"}
report_utilization -file [file join $output utilization.rpt]
report_clocks -file [file join $output clocks.rpt]
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
set frag_valid_regs [get_cells -hier -filter {NAME =~ *u_rasterizer/frag_valid_reg && REF_NAME =~ FD*}]
if {[llength $frag_valid_regs] != 1} {error "Cannot identify the rasterizer fragment-valid FPGA register"}
set frag_valid_reg [lindex $frag_valid_regs 0]
set frag_valid_init [get_property INIT $frag_valid_reg]
if {$frag_valid_init ne "1'b0"} {error "Unexpected rasterizer fragment-valid FPGA INIT: $frag_valid_init"}
set audit [open [file join $output register_init.rpt] w]
puts $audit "CELL=$frag_valid_reg REF_NAME=[get_property REF_NAME $frag_valid_reg] INIT=$frag_valid_init"
close $audit
write_checkpoint -force [file join $output routed.dcp]
set setup_paths [get_timing_paths -delay_type max -max_paths 1]
set hold_paths [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup_paths] == 0 || [llength $hold_paths] == 0} {error "No timing paths found"}
set setup_slack [get_property SLACK $setup_paths]
set hold_slack [get_property SLACK $hold_paths]
if {$setup_slack < 0 || $hold_slack < 0} {error "Timing failed; see $output/timing.rpt"}
write_bitstream -force [file join $output milkfrog_nexys_a7.bit]
set report [open [file join $output build_validation.txt] w]
puts $report "PASS: milkfrog_top xc7a100tcsg324-1"
puts $report "BRAM tiles: $bram_tiles / 135"
puts $report "Setup slack: $setup_slack ns"
puts $report "Hold slack: $hold_slack ns"
puts $report "DRC errors: [llength $drc_errors]"
puts $report "Framebuffer zero INIT words: $init_words"
close $report
