OUT_DIR := out

SRC := MGPU.srcs/sources_1/new/*.v
TB  := MGPU.srcs/sim_1/new/mgpu_tb.v

SIM_EXE := $(OUT_DIR)/mgpu_tb.vvp
FB_HEX  := $(OUT_DIR)/framebuffer.hex
FB_PNG  := $(OUT_DIR)/framebuffer.png

.PHONY: all run image clean

all: $(FB_PNG)

run: $(FB_HEX)

image: $(FB_PNG)

$(OUT_DIR):
	mkdir $(OUT_DIR)

$(SIM_EXE): $(SRC) $(TB) | $(OUT_DIR)
	iverilog -g2012 -o $(SIM_EXE) $(SRC) $(TB)

$(FB_HEX): $(SIM_EXE) | $(OUT_DIR)
	vvp $(SIM_EXE)

$(FB_PNG): $(FB_HEX) tools/view_framebuffer.py | $(OUT_DIR)
	python tools/view_framebuffer.py $(FB_HEX)

clean:
	-del /Q $(OUT_DIR)\mgpu_tb.vvp $(OUT_DIR)\framebuffer.hex $(OUT_DIR)\framebuffer.png $(OUT_DIR)\framebuffer.ppm 2>NUL
