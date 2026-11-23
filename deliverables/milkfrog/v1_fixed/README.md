# 奶蛙 V1：大笑与固定镜头

这是与 [V2 环绕镜头](../v2_orbit/README.md) 同等维护的正式版本，两版均可独立查看和下载，统一入口见 [版本索引](../README.md)。本目录保存 V1 模型及 ROM 对应的正式产物；`out/` 用于可再生成的完整帧、日志和构建缓存。

- [完整 MGPU RTL 视频](milkfrog_board_rtl.mp4)：541 帧，30 fps，18.033 秒，320×240 RGB332。
- [原片与 RTL 并排对照](reference_vs_rtl.mp4)。
- [关键帧对比](keyframes.png)：原片、上一版实际 RTL、本版实际 RTL。
- [Nexys A7-100T 比特流](milkfrog_nexys_a7.bit)：器件 xc7a100tcsg324-1，尚未做实体开发板下载测试。
- [可编辑 Blender 动画](../../../assets/milkfrog/v1_fixed/animation/milkfrog_laugh.blend)与[原始标准模型](../../../milkfrog.blend)。
- [总验证报告](reports/final_validation.json)、[视觉测量](reports/visual_review.json)、[资源](reports/utilization.rpt)、[时序](reports/timing.rpt)和[文件 SHA-256 清单](manifest.json)。

541 帧、41,548,800 个像素与独立无深度缓冲软件参考一致；第 542 帧循环复验和暂停/恢复/复位通过。40 MHz Icarus 首帧 76,800 个像素一致，该检查按本次布线确认的 FDRE INIT=0 仅在 time 0 建模上电初值。BRAM 123.5/135，setup +1.065 ns，hold +0.029 ns，DRC 错误 0。

2026-11-24 使用统一为 `.sv` 的源码重新完成全帧仿真、综合、布局布线和比特流生成。迁移前后 542 帧的像素及周期计数完全一致，GPU 数据通路和接口保持原设计，详见[源码迁移说明](../../../docs/systemverilog_migration.md)。

本版没有增加 GPU Z-buffer。后段上手位置与朝向、部分放手速度和局部嘴形仍有参考误差；报告中的硬件/软件零像素差异不表示重建动画与原片逐像素一致。测量方法、残差和重建命令见[V1 工作流](../../../docs/milkfrog_workflow.md)。报告中的原运行目录是历史来源记录，重新构建时会在当前工程 `out/` 下生成。

重新生成本交付目录：完成工作流中的完整构建和验证后，运行 `python tools/package_milkfrog.py`。打包程序先重新核对全部原始 RTL 帧、源模型、ROM、Blender 和比特流，再按白名单复制本目录中的产物，保存文件与输入哈希。
