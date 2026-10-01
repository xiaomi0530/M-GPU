OUT_DIR := out

SRC := MGPU.srcs/sources_1/new/*.v
TB  := MGPU.srcs/sim_1/new/top_tb.v

SIM_EXE := $(OUT_DIR)/top_tb.vvp
FB_HEX  := $(OUT_DIR)/framebuffer.hex
FB_PNG  := $(OUT_DIR)/framebuffer.png

.PHONY: all run image gui live simulate-image clean

all: $(FB_PNG)

run: $(FB_HEX)

image: $(FB_PNG)

gui:
	python tools/view_framebuffer.py

live:
	python tools/view_framebuffer.py --live

simulate-image:
	iverilog -g2012 -DSTUDIO_SIMULATION -s mgpu_image_tb -Pmgpu_image_tb.GPU_CLK_DIV_LOG2=1 -o $(OUT_DIR)/mgpu_image_tb.vvp $(SRC) $(OUT_DIR)/mgpu_image_tb.v
	vvp $(OUT_DIR)/mgpu_image_tb.vvp

$(OUT_DIR):
	mkdir $(OUT_DIR)

$(SIM_EXE): $(SRC) $(TB) | $(OUT_DIR)
	iverilog -g2012 -DSTUDIO_SIMULATION -s top_tb -Ptop_tb.GPU_CLK_DIV_LOG2=1 -o $(SIM_EXE) $(SRC) $(TB)

$(FB_HEX): $(SIM_EXE) $(wildcard $(OUT_DIR)/image_scene.tri) | $(OUT_DIR)
	vvp $(SIM_EXE) +TRACE=$(OUT_DIR)/framebuffer.trace +FRAMEBUFFER=$(FB_HEX) +STOP_STAGE=background

$(FB_PNG): $(FB_HEX) tools/view_framebuffer.py | $(OUT_DIR)
	python tools/view_framebuffer.py $(FB_HEX)

clean:
	-del /Q $(OUT_DIR)\mgpu_tb.vvp $(OUT_DIR)\framebuffer.hex $(OUT_DIR)\framebuffer.png $(OUT_DIR)\framebuffer.ppm 2>NUL
