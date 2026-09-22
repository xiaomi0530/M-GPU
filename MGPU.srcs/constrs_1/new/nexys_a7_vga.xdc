## Nexys A7-100T: reference manual sections 5, 8 and 9.
## Cross-checked with Digilent's Nexys-A7-100T-Master.xdc:
## https://github.com/Digilent/digilent-xdc/blob/master/Nexys-A7-100T-Master.xdc
## Nexys A7 configuration bank uses the board's 3.3 V supply.
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
set_property -dict {PACKAGE_PIN E3 IOSTANDARD LVCMOS33} [get_ports CLK100MHZ]
create_clock -name sys_clk -period 10.000 [get_ports CLK100MHZ]
create_generated_clock -name gpu_clk -source [get_ports CLK100MHZ] -divide_by 16 [get_pins u_gpu_clk_buf/O]

set_property -dict {PACKAGE_PIN C12 IOSTANDARD LVCMOS33} [get_ports CPU_RESETN]
set_property -dict {PACKAGE_PIN M18 IOSTANDARD LVCMOS33} [get_ports BTNU]

set_property -dict {PACKAGE_PIN A3 IOSTANDARD LVCMOS33} [get_ports {VGA_R[0]}]
set_property -dict {PACKAGE_PIN B4 IOSTANDARD LVCMOS33} [get_ports {VGA_R[1]}]
set_property -dict {PACKAGE_PIN C5 IOSTANDARD LVCMOS33} [get_ports {VGA_R[2]}]
set_property -dict {PACKAGE_PIN A4 IOSTANDARD LVCMOS33} [get_ports {VGA_R[3]}]
set_property -dict {PACKAGE_PIN C6 IOSTANDARD LVCMOS33} [get_ports {VGA_G[0]}]
set_property -dict {PACKAGE_PIN A5 IOSTANDARD LVCMOS33} [get_ports {VGA_G[1]}]
set_property -dict {PACKAGE_PIN B6 IOSTANDARD LVCMOS33} [get_ports {VGA_G[2]}]
set_property -dict {PACKAGE_PIN A6 IOSTANDARD LVCMOS33} [get_ports {VGA_G[3]}]
set_property -dict {PACKAGE_PIN B7 IOSTANDARD LVCMOS33} [get_ports {VGA_B[0]}]
set_property -dict {PACKAGE_PIN C7 IOSTANDARD LVCMOS33} [get_ports {VGA_B[1]}]
set_property -dict {PACKAGE_PIN D7 IOSTANDARD LVCMOS33} [get_ports {VGA_B[2]}]
set_property -dict {PACKAGE_PIN D8 IOSTANDARD LVCMOS33} [get_ports {VGA_B[3]}]
set_property -dict {PACKAGE_PIN B11 IOSTANDARD LVCMOS33} [get_ports VGA_HS]
set_property -dict {PACKAGE_PIN B12 IOSTANDARD LVCMOS33} [get_ports VGA_VS]

## Only asynchronous external inputs are excepted, never the GPU datapath.
set_false_path -from [get_ports BTNU] -to [get_cells {button_sync_reg[0]}]
set_false_path -from [get_ports CPU_RESETN] -to [get_cells {reset_pipe_reg[0]}]
set_false_path -from [get_ports CPU_RESETN] -to [get_cells {gpu_reset_pipe_reg[0]}]

## VGA has no returned/forwarded sampling clock. Bound register-to-pad delay
## explicitly; this is an internal routing budget, not monitor setup/hold.
set_max_delay -datapath_only 10.000 -from [get_clocks sys_clk] -to [get_ports {VGA_R[*] VGA_G[*] VGA_B[*] VGA_HS VGA_VS}]
