# 奶蛙 V2：360° 环绕镜头工作流

V2 环绕镜头与 [V1 固定镜头](milkfrog_workflow.md) 为同等优先级的正式版本，统一入口见[版本索引](../deliverables/milkfrog/README.md)。本页只描述 V2。

2026-11-24 源码统一为 `.sv`，配置头为 `.svh`，状态枚举自动编号，RTL 与 TB 的时间单位规则见 [SystemVerilog 迁移说明](systemverilog_migration.md)。交付报告绑定重新构建后的源码。

第二版沿用第一版 541 帧、18 个变换组的大笑动作，相机在第 0–540 帧之间绕世界 Z 轴旋转 360°，每帧 2/3°。俯仰角保持约 9.898°，正交尺度固定为约 191.337 px/模型单位。相机跟踪躯干上的固定锚点，轨迹使用 sigma=4 帧的 Gaussian 平滑，整段统一取景，保留完整起跳与倒地动作。

第一版的模型、动作、ROM、比特流和交付目录均保留。第二版资产为 `assets/milkfrog/v2_orbit/animation/`、`assets/milkfrog/v2_orbit/rom/`，生成物为 `out/milkfrog_orbit_v2/`，验证后交付到 `deliverables/milkfrog/v2_orbit/`。原始 `milkfrog.blend`、GPU 核心和 `milkfrog_top.sv` 不变。

## 模型与投影约定

`matrices.npy` 是与第一版逐字节一致的物体到世界矩阵。`camera_matrices.npy` 是 541 帧完整世界到裁剪空间矩阵；ROM 构建器只执行一次 `camera[frame] @ object[frame, group]`，然后量化为 Q5.12。`camera_world.npy` 保存 Blender 中真正的环绕相机位姿。Blender 工作文件的几何、颜色、9,738 个对象变换和 541 个相机变换均由验证脚本检查。

绕到侧面后，第一版口腔的开放后部会漏出绿色背景。`milkfrog_orbit_geometry.py` 沿已有 32 点外唇边界补出后部口腔外壳，新增 65 个顶点和 96 个三角形，仍属于原嘴部分组 13；原前方口腔、牙列和动作不变。这些补面用于新增视角，并非从单目原片恢复的真实隐藏解剖。

现有矩阵 ROM 上限 4,096 word；18 组允许最多 227 个矩阵关键帧（4,086 word）。第二版使用动态规划最小化分组包围盒角点的最坏屏幕插值误差，同时保留全部表情/动作控制节点与 390–423 帧的密集过渡。报告记录实际误差，未达到 0.25 px 初始目标时不伪报达标。最终实际网格坐标误差见交付报告。

## 无 Z-buffer 遮挡

离线工具为全部 541 帧计算投影重叠和前后依赖，生成不超过 26 个缓存、131,072 条记录的绘制顺序。侧面、背面以及倒地时可能可见的三角形均保留。GPU 执行现有三角形覆盖写入，没有运行时深度比较或深度存储。

均匀分配全周缓存的首轮方案在起跳转身时仍有局部覆盖破碎，已弃用。正式方案将第 408–411 帧分配为独立缓存，并加密附近关键视角；这四帧与逐帧依赖排序图分别相差 1、0、0、8 像素。全段模型内部可见颜色排序误差的 95 分位值由 403 降至 186，最差帧由 951 降至 279。最终采用 26 个缓存、131,070 条顺序记录，保留全部可能可见的面。

相交表面的循环依赖与有限缓存可能残留像素误差，`ordering_report.json` 明确记录。模型内部几何诊断、独立软件和 RTL 像素一致性、原片外观相似度是不同概念。V2 改变了镜头，不沿用 V1 固定镜头的原片 IoU 来宣称复刻精度。

## 重建

依赖沿用第一版：Python（numpy、scipy、Pillow、opencv-python）、FFmpeg、Blender 5.2、Verilator、Icarus、Vivado 2025.1。以下命令在项目根目录执行，所有产物独立写入第二版目录。

```powershell
python -X utf8 tools/build_milkfrog_orbit.py
& 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe' --background --factory-startup --disable-autoexec --threads 4 --python-exit-code 1 --python tools/verify_milkfrog_blender.py -- --animation-dir assets/milkfrog/v2_orbit/animation --output out/milkfrog_orbit_v2/validation
python -X utf8 tools/build_milkfrog_rom.py --input-dir assets/milkfrog/v2_orbit/animation --output-dir assets/milkfrog/v2_orbit/rom --review-dir out/milkfrog_orbit_v2/board_reference --order-caches 26 --order-entry-budget 131072 --order-workers 4 --order-iterations 4 --order-reference-frames 0,40,80,123,166,210,250,290,332,365,390,396,402,405,407,408,409,410,411,412,415,419,435,470,505,540 --dedicated-order-frames 408,409,410,411
python tools/preview_milkfrog_rom.py --animation-dir assets/milkfrog/v2_orbit/animation --rom-dir assets/milkfrog/v2_orbit/rom --projection out/milkfrog_orbit_v2/board_reference/projection.npz --output out/milkfrog_orbit_v2/painter_verified --workers 4 --compare-sort
python tools/run_milkfrog_board.py --rom-dir assets/milkfrog/v2_orbit/rom --output out/milkfrog_orbit_v2/rtl --frames 542 --controls --video
& 'C:/Xilinx/2025.1/Vivado/bin/vivado.bat' -mode batch -source tools/build_milkfrog.tcl -tclargs assets/milkfrog/v2_orbit/rom out/milkfrog_orbit_v2/build
python tools/run_milkfrog_board.py --rom-dir assets/milkfrog/v2_orbit/rom --output out/milkfrog_orbit_v2/rtl --frames 542 --controls --video --reuse-capture --crosscheck --fpga-init-proof out/milkfrog_orbit_v2/build/register_init.rpt
python tools/verify_milkfrog.py --animation-dir assets/milkfrog/v2_orbit/animation --rom-dir assets/milkfrog/v2_orbit/rom --projection out/milkfrog_orbit_v2/board_reference/projection.npz --output out/milkfrog_orbit_v2/rtl --reference out/milkfrog_orbit_v2/painter_verified --editable-proof out/milkfrog_orbit_v2/validation/editable_blender_validation.json --bitstream out/milkfrog_orbit_v2/build/milkfrog_nexys_a7.bit
python tools/review_milkfrog_orbit.py
python tools/milkfrog_orbit_video.py
python tools/package_milkfrog_orbit.py
```

完整真实 RTL 捕获可与 Vivado 实现并行；40 MHz 四态检查必须使用本次 V2 构建的 `register_init.rpt`，不能使用第一版的证明文件。原核心的 `frag_valid` 未显式复位，测试台仅按 routed DCP 的 FDRE INIT 值在 time 0 初始化一次，之后不强制该信号。

## 检查与交付

`review_milkfrog_orbit.py` 测量真实相机的累计方位、固定尺度、整段裁剪边界、矩阵插值、541 帧前景组件、包围盒、封闭背景区域和 540 组时间差，并挑出侧视嘴部、起跳倒地、最差遮挡和缓存切换帧供目视复核。手臂与身体间的合法背景间隙不能自动当作模型漏洞。

`verify_milkfrog.py` 对完整 541×76,800 个像素执行独立无深度缓冲软件与 RTL 核验，并绑定模型、相机、顶层、核心、三份 ROM、Blender 证明与 bitstream 的哈希。第 542 帧用来验证动画计数回到首帧；原片结尾躺倒与开头站立仍是动作切换，不宣称无缝循环。

最终资源、时序、DRC 和比特流哈希以 [第二版交付说明](../deliverables/milkfrog/v2_orbit/README.md) 为准。仿真视频编码为 30 fps；绘制时间不包含 VGA 呈现等待。未下载到实体开发板。
