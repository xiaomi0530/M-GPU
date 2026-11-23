# Nexys A7-100T 板级构建

器件为 `xc7a100tcsg324-1`。约束为 `MGPU.srcs/constrs_1/new/nexys_a7_vga.xdc`。

- `CLK100MHZ`：板载 100 MHz 输入；`gpu_clock` 的 MMCM 生成 40 MHz GPU 时钟。
- `CPU_RESETN`：低有效板级复位；保留各时钟域现有复位同步和锁定等待。
- `BTNU`：消抖后暂停/继续动画。
- `VGA_R/G/B`、`VGA_HS/VS`：保持原 XDC 引脚命名。
- 内部 framebuffer 为两组 320×240 RGB332；VGA 放大到 640×480，每四拍推进一个像素。
- 后缓冲完成清屏和绘制后请求交换，前缓冲在垂直消隐期切换，GPU 收到确认后开始下一帧。

从工程根目录运行：

```powershell
vivado -mode batch -source tools/build_vga.tcl
```

脚本自动复制 ROM 到独立输出目录，以 SystemVerilog 读取 `.sv`，完成综合、实现、时序和 BRAM 初始化检查。通过后输出 `out/vga_current/nexys_a7_vga.bit`。

也可直接打开 `MGPU.xpr`，设计顶层为 `top`，默认仿真顶层为 `top_tb`。工程已将 `.sv` 标记为 SystemVerilog，并登记全部 ROM 文件。仅供仿真的 `scene_reference_pixels.mem` 不参与综合。

```powershell
vivado -mode batch -source tools/setup_top_simulation.tcl
```

以上命令将仿真集设为 Studio 模式、320×240 快速仿真，并把输出放到 `out/studio_top/`。正常上板的 40 MHz 时钟和快速功能仿真的 50 MHz 时钟用途不同；功能仿真通过不等于实现时序通过。
