# Studio 统一 top.v 工作流

设计顶层是 top.v；仿真根模块是 top_tb（图片模式为生成的 top_image_tb）。testbench 仍需要存在以提供板载时钟、复位和采集结果，但不再直接实例化 mgpu，也不直接写入 framebuffer。

## Framebuffer Studio

运行 `python tools/view_framebuffer.py`。选择“机械晶核（512 帧）”“机械晶核（单帧）”或“MIDIYAS GPU 开屏（420 帧）”，然后点击“运行 top.v”。当前开屏为 **PRISM CORE 晶核启动**：25 个运动组、420 个连续相位，约 7 秒，其中 16 组用于 Logo，9 组用于机械晶核。前 3 个相位保留黑场，再以比旧版放慢约 1.4 倍的节奏展示双翼与能量框汇聚、字母出现和 GPU 标签入位；Logo 随后向中心晶核收拢。第 372～419 相位用 48 帧让机械场景从相同位置放大出现，并缓缓开始旋转。末帧与普通机械动画相位 24 完全衔接，硬件接着播放相位 25；GPU 核心保持不变。

机械晶核使用 304 个静态三角形和 9 个运动组，展示六瓣外壳展开、金色晶核旋转、青紫断环反向运动和相机环绕，最后合拢后循环。512 个相位按板级显示帧周期播放，一轮约 8.536 秒。普通机械动画每 8 个相位保存 MVP 关键帧，其余相位线性插值，最后一个区间连接第 0 组关键帧；预览、软件参考和硬件使用相同的定点插值结果。

默认勾选“加速功能仿真”：GPU 使用 50 MHz，取消帧率等待，仅用于加速逻辑验证，不能代表硬件时序或帧率。取消勾选则使用板级 40 MHz、目标 60 FPS；当前 VGA 限制实际显示约为 59.98 FPS。VGA 使用 100 MHz 输入和 25 MHz 像素使能。开屏默认持续约 7 秒，控制器会等待末帧完成显示再进入机械动画；单独录制机械晶核或图片会跳过开屏。顶层参数 `LOGO_HOLD_MS=0` 也可直接跳过，此时 `START_FRAME` 指定机械动画初始相位。

输出在 out/studio_top/：framebuffer.trace、framebuffer.hex、framebuffer.png、framebuffer.json、simulation.log。仿真分辨率从 top.v 的 H_RES/V_RES 读取，当前为 320×240；HEX 保存 76,800 个 RGB332 字节，PNG 放大到 640×480。可停止仿真并回放已产生的像素。两个 Studio 共用仿真占用状态，避免同时启动；关闭窗口会通知后台进程终止。

画面上方可切换“屏幕显示”和“绘制过程”：前者只在 VGA 真正交换缓冲后显示新帧，后者显示后台逐像素清屏、绘制。按三角形前后移动或选择列表项会自动切换到绘制过程。两种视图均可拖动时间轴、向前向后跳转和慢速回放；1000 ms/s 表示每秒播放一秒仿真时间。时间轴青色刻度是缓冲交换，紫色刻度是三角形完成。实时追踪的是仿真日志进度。

新版日志为 `MGPU_TRACE 2`：`P 时间 三角形编号 缓冲编号 x y RGB332` 记录后缓冲写入，`S 时间 前缓冲编号` 记录实际交换；初始前缓冲为 0。`# DISPLAY 640 480` 指定输出尺寸。回放保留两份像素和交换历史，可任意回退；仍能读取 `MGPU_TRACE 1` 旧日志。

## Image Studio

1. 导入图片、调整位置、透明背景和三角形误差，点击“生成三角 + top Testbench”。布局坐标仍为 640×480；RGBA 图片先按 GPU 分辨率重采样、合成背景和量化 RGB332，再划分三角形，避免细小三角形缩放后退化。
2. 输出 out/image_scene.tri、out/top_image_tb.v、预览、参考像素和元数据。
3. 点击“通过 top.v 仿真并查看”。图片数据由仿真专用 studio_triangle_source 提供，经 top 的 FETCH/LOAD/ISSUE/WAIT_GPU/ADVANCE 状态机送入真实 GPU，完成后通过 PRESENT/SWAP_WAIT 交换显示；时钟、复位、FIFO、着色和 VGA 都在 top 层级运行。完成时比较 320×240 原始像素，显示和导出使用最近邻放大。
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

在导出目录运行 `vivado -mode batch -source build.tcl`，或创建独立 Vivado 工程加入该包。不要把原 top.v 和导出 top.v 同时加入一个工程。导出不会覆盖原演示，也不会采用加速仿真的 50 MHz 时钟设置。此导出流程的既有硬件验证属于旧版单缓冲工程，本次双缓冲适配验证范围为 Studio 仿真和回放。

## Vivado 和命令行

现有 MGPU.xpr 的 sim_1 已切换到 top_tb，综合顶层仍是 top。tools/setup_top_simulation.tcl 可重新配置：使用仿真宏、320×240 快速参数、绝对输出路径，默认跳过开屏、录制机械晶核单帧。

Icarus 编译参数：`-g2012 -DSTUDIO_SIMULATION -s top_tb`，编译 source_1/new/*.v 与 sim_1/new/top_tb.v。图片模式改为 `-s top_image_tb` 并使用 out/top_image_tb.v。

运行参数：`+TRACE=路径`、`+FRAMEBUFFER=路径`、`+STOP_STAGE=logo|calibration|background|animation`、`+FRAMES=数量`。`+STUDIO_SCENE=路径` 可给共享 top_tb 指定图片场景。涉及空格时应使用参数数组或给完整参数加引号。输出目录必须存在。

静态导出：`python tools/view_framebuffer.py out/studio_top/framebuffer.hex` 自动识别 320×240 或旧版 640×480，并写入 out/framebuffer.png；320×240 默认放大两倍，添加 `--scale 1` 保存原尺寸。其他尺寸需同时指定 `--width`、`--height`。打开日志：`python tools/view_framebuffer.py out/studio_top/framebuffer.trace --live`。

直接在 Vivado 启动 `top_tb`、未指定输出参数时，默认输出到仿真工作目录中的 `framebuffer.trace` 和 `framebuffer.hex`，无需预建 `out` 子目录。通常工作目录为 `MGPU.sim/sim_1/behav/xsim/`，以当前仿真实际目录为准。trace 在启动时创建，hex 在所选场景完成后生成。修改 testbench 后需关闭仿真再重新启动 Behavioral Simulation；只点 Restart 不会重新编译。`run 5000 ns` 只运行 5 微秒，不足以绘制完整画面；完整场景需继续运行或使用上面的快速配置脚本。

旧 mgpu_tb.v 保留为核心级回归测试，不再是 Studio/Vivado 默认入口。tools/build_space_demo.py 再生成演示时会自动重新接入 Studio 仿真支持。

## 已有双缓冲基础验证

- 上一版 320×240 Logo 一帧、奶蛙连续两帧与参考渲染逐像素一致；真实日志的交换次数、最终前缓冲、后台写入期间的稳定画面和回退检查通过。当前机械场景的验证结果见 [README](../README.md)。
- 原生分辨率 RGBA 图片、非黑背景和真实 top 图像仿真逐像素一致；GUI、旧格式兼容、路径空格、8193 个三角形、空场景、错误场景和取消检查通过。

## 历史单缓冲验证

- 图片颜色、透明度、GUI 控件及真实 top 图像仿真通过；含路径空格测试。
- 超过 8192 条图片命令的仿真、空场景、错误场景、取消和导出容量检查通过。
- 导出的测试工程实际通过综合、布局布线和 bitstream 生成：WNS +0.662 ns、WHS +0.038 ns。
- 导出 top 的 307200 个 framebuffer 像素与图片参考一致；测试图为小型青色方块，用于验证导出链路，并非替换用户演示。

- 共享运行器的板级模式也已实际验证：Logo 12800 条命令、603282 次写入、4188434 次 VGA 读取，最终像素与 Logo 参考完全一致。
