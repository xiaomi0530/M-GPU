# 当前工程结构与维护

工程保留 `top` 的 MIDIYAS 开屏、机械晶核和图片 Studio，以及 `milkfrog_top` 的奶蛙完整动画。奶蛙包含同等优先级的 V1 固定镜头与 V2 环绕镜头，二者共享核心与工具，并独立保存资产和交付物。奶蛙场景用离线绘制顺序完成无 Z-buffer 渲染。README 引用的历史展示 GIF、图片和原始视频保留。

当前场景预览：[机械晶核](images/mechanical_core/animation.gif)、[开屏与晶核衔接](images/midiyas_logo/boot_preview.gif)。这些图是场景生成器的参考渲染；实际 RTL 的像素比对结果输出到 `out/tests/framebuffer.png`。

| 目录或文件 | 用途 |
| --- | --- |
| `MGPU.srcs/sources_1/new/` | 10 个 RTL 模块；沿用 Vivado 工程路径，`.sv` 原生 SystemVerilog 源文件 |
| `MGPU.srcs/sources_1/demo/` | 独立奶蛙场景顶层 `milkfrog_top.sv` |
| `MGPU.srcs/sources_1/rom/` | 开屏与机械晶核的 8 个 ROM 数据文件，必须保留并纳入版本管理 |
| `MGPU.srcs/sim_1/new/` | 10 个 `.sv` 文件：6 个开屏/晶核回归测试，以及奶蛙的 4 个仿真顶层或测试平台 |
| `MGPU.srcs/constrs_1/new/` | Nexys A7 引脚、时钟和跨时钟约束 |
| `tools/` | 当前场景生成、参考渲染、Studio、仿真与回归脚本 |
| `scripts/clean.ps1` | 安全清除工程内的生成缓存和输出 |
| `assets/mechanical_core/`、`assets/midiyas_logo/` | 当前场景的网格与元数据 |
| `milkfrog.blend` | 用户提供的原始标准模型，保留原文件字节 |
| `assets/references/naiwa_laugh/` | 已采用的参考视频、用户姿态图片及来源记录 |
| `assets/naiwa/` | 固定相机、参考动作测量、源模型 LOD、核心 RTL 基准哈希 |
| `assets/milkfrog/v1_fixed/animation/`、`v1_fixed/rom/` | V1 固定镜头的正式模型、动作、测量约束与板级 ROM |
| `assets/milkfrog/v2_orbit/animation/`、`v2_orbit/rom/` | V2 环绕镜头的正式模型、动作、相机轨迹与板级 ROM |
| `assets/milkfrog/versions.json` | 两个正式版本的对等索引，记录资产、交付和工作流路径 |
| `deliverables/milkfrog/v1_fixed/`、`v2_orbit/` | 两版独立视频、比特流、报告和 SHA-256 清单，均纳入 Git |
| `docs/` | 当前流程文档及展示图片 |
| `out/` | 可再生成的仿真、预览、导出和 Vivado 构建结果，不纳入 Git |
| `MGPU.xpr` | 开屏/晶核的 Vivado 工程，综合顶层 `top`、默认仿真顶层 `top_tb`；奶蛙使用独立 Tcl 构建入口 |

## RTL 数据流

`top` 调度清屏、顶点命令、呈现和帧间等待；`mgpu` 驱动 `vertex_shader`、`rasterizer`、`fifo`、`shader` 和双缓冲。`vga` 读取前缓冲；`gpu_clock` 管理 GPU 时钟。两个 divider 分别服务顶点定点运算和光栅化除法。

`milkfrog_top` 读取独立的顶点、三角形、分组矩阵和绘制顺序 ROM，向相同 GPU 发送场景命令。它未加入运行时深度存储或比较。开屏/晶核和奶蛙分别选择自己的顶层与 ROM；打开 `MGPU.xpr` 不会自动切换到奶蛙场景。

状态枚举使用自动连续编号，跳转与测试检查均按状态名引用；端口位宽、定点符号、复位极性、同步/异步特性与握手周期保持原设计。内部状态变量统一为 `state`，RGB 信号和函数改用小写下划线。板级端口名保留大写，以兼容 XDC。测试平台继续使用普通 `always`、延时和层级检查；RTL 的边沿触发块使用 `always_ff`。

旧 shader 寄存器堆的读写使能只在复位时清零，之后没有置位，读出也未参与像素路径，因此删除该实例、相关死信号及唯一实现文件 `regs.sv`。

## 测试入口

```powershell
python tools/run_tests.py --python
```

| 测试 | 检查范围 |
| --- | --- |
| `vga_tb` | 扫描时序、同步、RGB 输出、复位、完整两帧 |
| `top_clear_tb` | 启动清屏、重复复位、清屏中复位和全部地址 |
| `space_sequence_tb` | 512 相位与回绕、ROM 次序、矩阵插值和握手 |
| `midiyas_boot_tb` | 420 开屏相位、暂停/继续、场景衔接、复位与动画回绕 |
| `double_buffer_tb` | 真实 40/100 MHz 时钟、前后缓冲隔离、消隐交换、暂停和时钟丢锁 |
| `top_tb` | 当前顶层真实 GPU/VGA 渲染，记录完整 trace 和 framebuffer |

运行器还调用独立参考渲染，逐像素比较机械晶核第 0 帧。Python 测试覆盖日志回放、GUI、透明图片三角化、图片实际 RTL 仿真、路径空格、大场景、取消和独立图片导出。

奶蛙使用单独的运行器，不包含在上表的 6 项 RTL 回归内：

| 仿真文件 | 入口与用途 |
| --- | --- |
| `milkfrog_board_sim.sv` | `tools/run_milkfrog_board.py` 的 Verilator 场景顶层，捕获真实板级帧缓冲并检查暂停、恢复和循环 |
| `milkfrog_board_tb.sv` | 同一运行器的 Icarus 40 MHz 交叉检查，使用 Vivado 生成的寄存器 INIT 证明 |
| `naiwa_sim.sv` | `tools/run_naiwa_sim.py` 的顶点命令仿真适配，用于 LOD 等独立场景检查 |
| `naiwa_icarus_tb.sv` | 顶点命令路径的 Icarus 测试平台 |

```powershell
python tools/run_milkfrog_board.py --output out/milkfrog_board/rtl --frames 542 --controls --video
```

此兼容命令使用 V1 ROM。对称入口为 `make milkfrog-v1-sim` 与 `make milkfrog-v2-sim`，两版各有 assets、preview、sim、bit、crosscheck、package 目标。541 帧为动画，第 542 帧检查循环回到第 0 帧。完整顺序分别见 [V1 工作流](milkfrog_workflow.md)与 [V2 工作流](milkfrog_orbit_v2.md)。

`space_sequence_tb` 和 `midiyas_boot_tb` 使用 `SPACE_SCENE_STUB`，需要运行器选择的 stub 源组合；不要把 stub 和真实 `mgpu` 同时作为同名模块编译。`top_tb` 默认用 `STUDIO_SIMULATION` 宏，由运行器配置。

## ROM 与生成器

开屏/晶核 ROM 从原顶层逐地址提取；已与生成器重新生成的数据逐文件比较 SHA-256，8 个文件完全一致。`scene_reference_pixels.mem` 仅服务仿真，其余 7 个参与硬件场景。

```powershell
python tools/build_vertex_lab.py
```

此命令只更新 ROM、相关数量/位宽常量和场景导出，不再重新拼接整个顶层。修改控制器直接编辑 `top.sv`。仿真运行器、非工程 Vivado 构建和 XPR 均已处理 ROM 加载路径；手工运行 `vvp` 时，应先将 ROM 文件复制到仿真工作目录。

V1 的生成链为 `milkfrog_animation.py` → `build_milkfrog_rom.py` → `run_milkfrog_board.py` / `build_milkfrog.tcl`；V2 用 `build_milkfrog_orbit.py` 派生环绕相机和侧视补面，再使用同一 ROM、仿真与构建工具。正式动画输入分别位于 `assets/milkfrog/v1_fixed/animation` 和 `assets/milkfrog/v2_orbit/animation`，共享测量与 LOD 位于 `assets/naiwa/`。两版都不依赖历史迭代的 `out/` 快照。软件预览需要对应 ROM 生成器的 `projection.npz`，因此清理后应先按各版工作流重建 ROM。独立的拟合和排序实验脚本可要求显式提供旧快照；这些诊断入口不替代正式生成链。

## 风格检查

```powershell
$env:VERIBLE_FORMAT = 'C:/path/to/verible-verilog-format.exe'
python tools/format_hdl.py
python tools/format_hdl.py --check
```

工具需要 Verible；也可将 `verible-verilog-format` 加入 PATH。采用 4 空格、自然声明排版、紧凑下标和控制语句、独立对齐的具名映射。格式检查必须幂等，语义修改仍需完整回归。此次验证使用 Verible `v0.0-4302-gc6b29d62`。

## 整理后的验证记录（2026-11-22）

以下是开屏/晶核整理时的历史记录；其中 16 个 HDL 文件和 6 个 RTL 测试不包括随后新增的奶蛙文件。当前工程共有 21 个手写 `.sv` 文件，奶蛙的 2026-11-23 完整验证结果见[奶蛙流程](milkfrog_workflow.md)。

- 16 个 RTL/TB 文件的格式检查通过，重复运行不产生差异。
- 8 个 ROM 重新生成后与提取的数据逐文件 SHA-256 一致。
- 6 个 RTL/TB 回归全部通过；机械晶核第 0 帧的 76,800 个像素与独立参考完全一致。
- 33 项 Python 测试全部通过，包括独立图片导出包的编译与实际仿真。
- Vivado 2025.1 的工程配置、XSim 编译与 2 µs 冒烟仿真通过，8 个 ROM 正常导入。
- 完整综合、布局布线和 bitstream 生成通过；WNS `+0.644 ns`、WHS `+0.019 ns`，所有已设置时序约束满足。
- 48 个 framebuffer BRAM 的 6,912 个 INIT/INITP 字均为零。DRC 无错误；仍保留 DSP 流水化建议等非阻断告警。

这次开屏/晶核结果输出到 `out/tests/` 和 `out/vga_current/`；下载文件为 `out/vga_current/nexys_a7_vga.bit`，时序报告为同目录的 `timing.rpt`。`out/tests/source_hashes.json` 记录该轮验证的 RTL/TB 与 ROM 哈希。`out/` 不纳入 Git，重新克隆后需要运行相应入口生成这些文件。未进行实板下载验证。

## 已移除内容

- 无法通过当前接口编译、且已被保留测试覆盖的 `mgpu_tb`、`logo_vga_tb`、`space_vga_tb`、`top_sequence_tb`、`top_vga_tb`。
- 早期 logo/太空场景生成器、文本拼接式补丁脚本、旧 `assets/milk_frog*` 手工候选模型与压缩包，以及对应过期说明和预览；基于标准源文件的 `assets/naiwa/candidates/` 保留。
- 旧单缓冲图片导出模板；导出现在从当前顶层生成。
- 旧波形配置与失效 DCP 引用；生成缓存、日志、诊断实验和 `out/` 构建结果不纳入版本管理。

历史展示以 README 引用的 GIF 和图片为准。额外的 H.264 转码副本已删除，4 个原始展示 MP4 保留。Git 跟踪过的历史文件仍可通过提交记录恢复。

## 清理生成文件

```powershell
./scripts/clean.ps1 -WhatIf
./scripts/clean.ps1
```

默认删除整个 `out/` 和 Vivado 生成目录，因此需要保存的仿真结果或 bitstream 应先另行导出。`-KeepTests` 仅保留 `out/tests/`，`-KeepBuild` 仅保留 `out/vga_current/`，两者可以组合使用；这些开关不会保留 `out/milkfrog_board/`、奶蛙历史比较归档或其他 `out/naiwa/` 输出。保留构建目录中的临时 `.Xil` 仍会删除。源模型、`assets/` 和仓库内独立交付目录不在该脚本的清理目标中。脚本先检查绝对路径位于工程根目录内，再使用 PowerShell 原生命令删除；不要在仿真或构建运行期间执行清理。

清理后，Python 运行器会自动重建自己的输出目录；在 Vivado 中直接启动仿真前，请重新运行 `tools/setup_top_simulation.tcl`，以重建其配置的 `out/studio_top/` 输出目录。
