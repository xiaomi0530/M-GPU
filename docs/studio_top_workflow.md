# Studio 统一 top.v 工作流

设计顶层是 top.v；仿真根模块是 top_tb（图片模式为生成的 top_image_tb）。testbench 仍需要存在以提供板载时钟、复位和采集结果，但不再直接实例化 mgpu，也不直接写入 framebuffer。

## Framebuffer Studio

运行 `python tools/view_framebuffer.py`。选择 Logo 开屏、校准图、太空背景或卫星一圈，然后点击“运行 top.v”。

默认勾选“加速功能仿真”：GPU 使用 50 MHz，停留缩短至 1 ms，仅用于加速逻辑验证，不能代表硬件时序或帧率。取消勾选则使用板级 6.25 MHz、阶段停留 4 秒、动画停留 40 ms，仿真耗时会明显增加。VGA 始终使用 top 内的 100 MHz 时钟。

输出在 out/studio_top/：framebuffer.trace、framebuffer.hex、framebuffer.png、simulation.log。可停止仿真并回放已产生的像素。两个 Studio 共用仿真占用状态，避免同时启动；关闭窗口会通知后台进程终止。

## Image Studio

1. 导入图片、调整位置、透明背景和三角形误差，点击“生成三角 + top Testbench”。
2. 输出 out/image_scene.tri、out/top_image_tb.v、预览、参考像素和元数据。
3. 点击“通过 top.v 仿真并查看”。图片数据由仿真专用 studio_triangle_source 提供，经 top 的 FETCH/LOAD/ISSUE/WAIT_GPU/ADVANCE 状态机送入真实 GPU；时钟、复位、FIFO、着色和 VGA 都在 top 层级运行。完成时逐像素比较软件参考。
4. 图片仿真输出在 out/studio_image/，不覆盖板级演示录制。
5. 侧栏支持滚动，窗口较小时仍可访问导出与取消按钮。

STUDIO_SIMULATION 宏只供 Studio 仿真；普通综合不包含这条输入。图片源最多 160002 条命令，独立 18 位索引，因此不受板级演示 ROM 地址宽度限制。原 GPU 核心文件不修改。缺文件、非法坐标、退化三角形会报错，空图也能正确结束。

## 导出可上板 top.v

生成图片后点击“导出上板 top.v”。输出 out/image_export/ 独立包：
- top.v：同步三角形 ROM 和绘制控制器，复位后清屏、绘图，完成后持续显示。
- rtl/：当前 GPU/VGA 核心副本。
- nexys_a7_vga.xdc：Nexys A7-100T 约束。
- build.tcl：综合、布局布线、时序检查及 image_top.bit 生成。
- manifest.json 和 README.txt：数量、存储估算、使用说明。

默认最多 8190 个图片三角形，加两条清屏共 8192 条；超过时明确拒绝，不自动降低质量。每条 84 位命令存放六个 10 位坐标与三个 8 位 RGB332 颜色。它是绘图命令表，不是程序指令或直接显示的 framebuffer。容量限制是保守预算，每个导出场景仍必须通过实际 Vivado 实现。

在导出目录运行 `vivado -mode batch -source build.tcl`，或创建独立 Vivado 工程加入该包。不要把原 top.v 和导出 top.v 同时加入一个工程。导出不会覆盖原 Logo/卫星演示，也不会采用加速仿真的 50 MHz 时钟设置。

## Vivado 和命令行

现有 MGPU.xpr 的 sim_1 已切换到 top_tb，综合顶层仍是 top。tools/setup_top_simulation.tcl 可重新配置：使用仿真宏、快速参数、绝对输出路径，默认录制到 Logo 完成。

Icarus 编译参数：`-g2012 -DSTUDIO_SIMULATION -s top_tb`，编译 source_1/new/*.v 与 sim_1/new/top_tb.v。图片模式改为 `-s top_image_tb` 并使用 out/top_image_tb.v。

运行参数：`+TRACE=路径`、`+FRAMEBUFFER=路径`、`+STOP_STAGE=logo|calibration|background|animation`、`+FRAMES=数量`。`+STUDIO_SCENE=路径` 可给共享 top_tb 指定图片场景。涉及空格时应使用参数数组或给完整参数加引号。输出目录必须存在。

旧 mgpu_tb.v 保留为核心级回归测试，不再是 Studio/Vivado 默认入口。tools/build_space_demo.py 再生成演示时会自动重新接入 Studio 仿真支持。

## 验证

- 图片颜色、透明度、GUI 控件及真实 top 图像仿真通过；含路径空格测试。
- 超过 8192 条图片命令的仿真、空场景、错误场景、取消和导出容量检查通过。
- 导出的测试工程实际通过综合、布局布线和 bitstream 生成：WNS +0.662 ns、WHS +0.038 ns。
- 导出 top 的 307200 个 framebuffer 像素与图片参考一致；测试图为小型青色方块，用于验证导出链路，并非替换用户演示。

- 共享运行器的板级模式也已实际验证：Logo 12800 条命令、603282 次写入、4188434 次 VGA 读取，最终像素与 Logo 参考完全一致。
