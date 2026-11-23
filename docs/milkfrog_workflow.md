# 奶蛙 V1 固定镜头：模型、动画与 MGPU 渲染流程

V1 固定镜头与 [V2 环绕镜头](milkfrog_orbit_v2.md) 为同等优先级的正式版本，统一入口见[版本索引](../deliverables/milkfrog/README.md)。本页只描述 V1。

2026-11-24 源码已统一迁移为 SystemVerilog，并按新源码重新验证两版交付。文件命名、状态自动编号与头部约定见 [SystemVerilog 迁移说明](systemverilog_migration.md)。下文 2026-11-23 的实现数值保留为那次建模迭代的历史记录，最新比特流与时序以交付报告为准。

2026-11-23 本轮迭代已完成：541 帧实际 MGPU RTL、独立软件参考、可编辑 Blender 动画及 Vivado 比特流已通过最终一致性验证。原始 `milkfrog.blend`、10 个核心 RTL 和场景顶层 `milkfrog_top.sv` 均保持不变，GPU 没有增加 Z-buffer。尚未下载到实体开发板。

已验证的视频、比特流和报告另存于纳入 Git 的 [deliverables/milkfrog/v1_fixed](../deliverables/milkfrog/v1_fixed/README.md)，新克隆无需先运行仿真即可下载查看。下面的 `out/` 路径用于重新构建；完成后运行 `python tools/package_milkfrog.py` 重新校验并更新交付快照。`make milkfrog-sim` 运行完整捕获，`make milkfrog-bit` 生成实现，随后 `make milkfrog-crosscheck` 使用新的 INIT 证明完成交叉验证。

## 正式产物

| 文件 | 内容 |
| --- | --- |
| `out/milkfrog_board/rtl/milkfrog_board_rtl.mp4` | 真实 GPU 帧缓冲视频，320×240 RGB332，541 帧，30 fps，18.033 秒 |
| `out/milkfrog_board/rtl/reference_vs_rtl.mp4` | 原片与本轮 RTL 的固定画面映射对照 |
| `out/milkfrog_board/rtl/rtl_preview.gif` | 完整动画预览 |
| `out/milkfrog_board/rtl/review/visual_review_compact.png` | 原片、上一版真实 RTL、本版真实 RTL 的四组关键帧对比 |
| `out/milkfrog_board/build/milkfrog_nexys_a7.bit` | Nexys A7-100T，器件 xc7a100tcsg324-1 |
| `assets/milkfrog/v1_fixed/animation/milkfrog_laugh.blend` | 18 组仿射动画的可编辑工作副本 |
| `out/milkfrog_board/rtl/final_validation.json` | 模型、原核心、全部像素、循环、控制、40 MHz 与比特流的总验证 |
| `out/milkfrog_board/rtl/review/visual_review.json` | 541 帧轮廓、472 个可测嘴部帧、闭眼和分阶段统计 |
| `out/milkfrog_board/rtl/review/regions.json` | 124 帧躺倒手脚区域位置、方向和面积 |
| `out/milkfrog_board/rtl/review/temporal.json` | 540 对相邻帧变化及缓存切换检查 |
| `out/naiwa/validation/editable_blender_validation.json` | Blender 与正式几何、颜色和 9,738 个变换的核验 |

最终 bitstream 为 3,825,913 字节，SHA-256：`de89d5a1eb7843f6574a0db8419f5656d3f0cb2130134845664653edec086e2a`。

## 输入与复刻方法

原模型 SHA-256 为 `3531d8c81c2d03d7f6a4f2ea1a491a8ad58dc1200316a105e81f915cf8d10654`。批准的参考视频为 `assets/references/naiwa_laugh/candidate_a_green.mp4`，SHA-256 为 `4970130ac69f86097219548144b66cb124afe6d5f2ef4ad53cbc3cbbf1df364e`。

相机和屏幕占比固定，全部 541 帧使用 `assets/naiwa/camera.json` 和 `reference_motion.json` 中的同一映射；没有逐帧缩放包围盒以提高轮廓分数。原片坐标到 320×240 的比例为 0.24256837098692033，平移为 (-71.77407847800237, -25.147443519619486)。

模型由原文件的 B 档 LOD 派生。动画工作网格有 4,712 个顶点、9,214 个三角形和 18 个变换组。原手与腹部融合的区域按源表面测量重构并分组；嘴腔、牙齿、舌、眼睑和颈部连接面是工作副本中的新增三维表面。单目视频无法唯一恢复隐藏深度、骨架或三维关节角，这些量仍是受参考约束的人工拟合，不应称作原片原始骨骼。

本轮嘴形使用逐帧暗域的宽、高、中心和置信度约束，牙列保留三维弧度；颈部连接面按原表面采样，并修掉第 225 帧嘴内的颈部橙条。`eye_closure_curve.json` 控制闭眼时段。脚部在源坐标 Z=-0.430 处与小腿分开，使用实际切环中心连接，允许脚腕独立转动。`motion_refinement.json` 约束起跳、转身、落地、脚掌方向和手部接触。

永久测量输入包括 `mouth_reference_measurements.json`、`mouth_reference_masks.npz`、`eye_closure_curve.json`、`landing_landmarks.json`、`lying_upper_foot_reference.json` 和 `fall_pose_constraints.json`，均位于 `assets/milkfrog/v1_fixed/animation/`。嘴部评分仅使用可见且置信度至少 0.6 的 472 帧；411–415 的脸部自遮挡不强行拟合为可见嘴部。二维手脚轴是投影方向，不能当作三维关节角；局部脚趾 ROI 也不能当作完整脚掌的面积。

Blender 每个 GPU 分组使用两对象 SVD 层次，保留非均匀缩放和剪切。541×18 个整数帧 `matrix_world` 的最大绝对误差为 8.9406967e-7，低于 2e-5 阈值；局部顶点、三角连接和 CORNER 源颜色也逐项核验。工作文件跨组保留共享顶点后共有 4,947 个顶点。部分脸部及手部补面有边界，报告列出其实际拓扑，不宣称全模型水密。

## 无 Z-buffer 的绘制顺序

`build_milkfrog_rom.py`、`painter_dependencies.py`、`optimize_milkfrog_caches.py` 和 `milkfrog_order_cache.py` 在离线阶段分析投影三角形的前后覆盖依赖。GPU 仅按 ROM 顺序绘制三角形，没有运行时深度比较或深度存储。几何深度用于离线诊断，最终软件参考和硬件都按三角形顺序覆盖像素。

最终打包为 4,427 个顶点、7,487 个三角形、18 组、214 个矩阵关键帧、26 个排序缓存和 131,065 条顺序记录，未超过原 131,072 条地址容量。所有可能可见面均保留；减少的面是整片动画中从未可见的面。矩阵使用 214×18=3,852 个 word，仍在现有 4,096 word 容量内。

最初共用缓存的 412–415 帧会把手臂局部盖碎，已拒收。正式版为这四帧各保留独立顺序，其缓存图与逐帧依赖排序图分别相差 3、0、25、0 像素。相交几何及有限缓存仍可能造成少量排序误差；逐帧依赖图也不是全局最优性的证明。诊断报告为 `assets/milkfrog/v1_fixed/rom/ordering_report.json`，不可把模型内部遮挡分数当成与原片的像素相似度。

## 本轮实际画质测量

所有数值以固定的上一版真实 RTL 归档与本版真实 RTL 对比。IoU 越高越好，中心误差越低越好。

| 指标 | 上一版 | 本版 |
| --- | ---: | ---: |
| 541 帧平均轮廓 IoU | 0.780960 | 0.800751 |
| 472 帧嘴暗域平均 IoU | 0.334358 | 0.454061 |
| 嘴暗域中心误差中位数 | 6.162 px | 1.686 px |
| 起跳转身轮廓 IoU，390–416 | 0.693481 | 0.801844 |
| 躺倒轮廓 IoU，417–540 | 0.764335 | 0.810724 |
| 后段上脚中心误差中位数 | 15.04 px | 3.21 px |
| 后段上脚投影轴误差中位数 | 52.81° | 11.80° |

并非所有局部指标都改善。后段上手中心误差中位数为 7.84 px，上一版为 4.23 px；掌面虽然已恢复完整可见形状，仍偏高、偏侧。躺倒嘴暗域 IoU 从 0.384209 降到 0.356291，抱头轮廓 IoU 从 0.758839 降到 0.756492。290 个完全闭眼控制帧中，17 帧仍有 1–2 个绿色像素，目视未形成睁眼虹膜。第 262–263 帧放手比原片更快。颜色渐变与细节还受到原生 320×240、RGB332 和网格近似限制，因此本版不等于原片逐像素 1:1 复现。

时间方向检查比较了全部 540 对相邻帧的前景对称差和颜色变化，并检查主要异常点及缓存切换附近的连续帧。快速起跳转身的 390–430 段单独复核，不与静态段使用同一异常排名。未发现新缓存导致的整片覆盖跳变或肢体断开；这些检查不能证明运动速度与原片完全一致。

## RTL 与 FPGA 验证

实际捕获 542 帧，其中 541 帧为完整动画，第 542 帧验证回到首帧。暂停到帧边界、暂停画面稳定、恢复到下一帧、复位回第 0 帧均通过。541×76,800=41,548,800 个 RGB332 像素与独立定点软件 painter 全部一致；这是硬件与软件渲染的一致性，不是原片与重建动画的零误差。

| 实现检查 | 结果 |
| --- | ---: |
| BRAM | 123.5 / 135 |
| 综合 LUT | 25,771 / 63,400 |
| DSP | 92 |
| Setup slack | +1.264 ns |
| Hold slack | +0.025 ns |
| DRC 错误 | 0 |
| Framebuffer INIT/INITP | 6,912 项全部为 0 |
| 最坏绘制周期 | 1,033,779 |
| 40 MHz 最坏清屏与绘制时间 | 25.844475 ms |

绘制时间小于 30 fps 的周期预算；该数值不包括 VGA 呈现等待。视频按参考的 30 fps 编码。完整 Verilator 捕获采用加速仿真配置，不能用其墙钟耗时证明实板播放速度。

40 MHz Icarus 首帧的 76,800 个像素与 Verilator 完全一致。原 `rasterizer.sv` 的 `frag_valid` 没有复位赋值，因此四态检查按本次 routed DCP 确认的 `FDRE INIT=1'b0` 在 time 0 赋值一次，后续复位不强制该信号；核心 RTL 未修改。证据为 `out/milkfrog_board/build/register_init.rpt` 和 `out/milkfrog_board/rtl/icarus_40mhz/comparison.json`。单帧交叉检查不替代完整 541 帧验证，也未测量呈现间隔。

最终总验证绑定原模型、10 个核心文件、场景顶层、几何/矩阵、Blender 工作文件、三处 ROM 快照、RTL 全帧和 bitstream 的哈希。`.sv/.sv` 代码风格检查通过，未引入本轮核心 HDL 改动。

## 重建与复核

在项目根目录使用 Python（numpy、scipy、Pillow、opencv-python）、FFmpeg、Blender 5.2、Verilator、Icarus 和 Vivado 2025.1。以下 PowerShell 命令与本轮产物路径一致。先完成 Vivado 以取得新的 INIT 证明，再运行 40 MHz 检查。

```powershell
python -X utf8 tools/milkfrog_animation.py
python tools/build_milkfrog_rom.py --order-caches 26 --order-entry-budget 131072 --order-workers 4 --order-iterations 3
python tools/preview_milkfrog_rom.py --output out/naiwa/painter_verified --workers 4 --compare-sort
python tools/run_milkfrog_board.py --output out/milkfrog_board/rtl --frames 542 --controls --video
& 'C:/Xilinx/2025.1/Vivado/bin/vivado.bat' -mode batch -source tools/build_milkfrog.tcl -tclargs assets/milkfrog/v1_fixed/rom out/milkfrog_board/build
python tools/run_milkfrog_board.py --output out/milkfrog_board/rtl --frames 542 --controls --video --reuse-capture --crosscheck
& 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe' --background --factory-startup --disable-autoexec --threads 4 --python tools/verify_milkfrog_blender.py
python tools/verify_milkfrog.py --output out/milkfrog_board/rtl --reference out/naiwa/painter_verified --bitstream out/milkfrog_board/build/milkfrog_nexys_a7.bit --editable-proof out/naiwa/validation/editable_blender_validation.json
python tools/milkfrog_comparison_video.py --output out/milkfrog_board/rtl
```

`tools/review_milkfrog.py`、`tools/review_milkfrog_regions.py` 和 `tools/review_milkfrog_temporal.py` 可重跑视觉测量；其输入原片、固定映射和阈值来自永久资产。默认比较基线为纳入 Git 的 `assets/naiwa/validation_baseline/baseline_rtl.npz`，同目录保存原始验证报告与归档哈希，新克隆不依赖历史 `out/`。例如：

```powershell
python tools/review_milkfrog.py out/milkfrog_board/rtl --name visual_review --engine 'Actual MGPU RTL framebuffer' --expect-frames 541 --output out/milkfrog_board/rtl/review --producer-manifest assets/milkfrog/v1_fixed/rom/manifest.json --compact --face-sheet
```

本机原版真实帧、旧构建与失败缓存尝试分别保存在忽略目录 `out/milkfrog_iteration2/baseline_*` 和 `rejected_cache25`，失败目录有 `INVALIDATED.txt`，不得作为当前产物。
