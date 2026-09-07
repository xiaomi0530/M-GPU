# M-GPU

This project is a teaching-oriented minimal GPU prototype written in Verilog.

## What it does

- Accepts one triangle at a time
- Rasterizes it into a 640x480 RGB332 framebuffer
- Supports per-vertex color interpolation
- Dumps the framebuffer through simulation for inspection

## Main files

- `MGPU.srcs/sources_1/new/mgpu.v`: top-level GPU core
- `MGPU.srcs/sim_1/new/mgpu_tb.v`: simulation testbench
- `tools/view_framebuffer.py`: framebuffer viewer

## Run simulation

```bash
make run
make image
```

## Notes

- `out/` contains generated simulation output
- Vivado cache and simulation directories are not meant to be versioned
