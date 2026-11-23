# 奶蛙正式版本索引

**V1 固定镜头与 V2 360° 环绕镜头是同等优先级的两个正式版本。** 两版分别维护，均提供完整视频、可编辑模型、独立 ROM、Nexys A7-100T 比特流和验证报告。

| 项目 | V1 · 固定镜头 | V2 · 360° 环绕镜头 |
| --- | --- | --- |
| 版本说明 | [V1 交付目录](v1_fixed/README.md) | [V2 交付目录](v2_orbit/README.md) |
| 完整实际 RTL 视频 | [固定镜头](v1_fixed/milkfrog_board_rtl.mp4) | [环绕镜头](v2_orbit/milkfrog_orbit_rtl.mp4) |
| 比特流 | [V1 bitstream](v1_fixed/milkfrog_nexys_a7.bit) | [V2 bitstream](v2_orbit/milkfrog_nexys_a7.bit) |
| 可编辑模型 | [V1 Blender](../../assets/milkfrog/v1_fixed/animation/milkfrog_laugh.blend) | [V2 Blender](../../assets/milkfrog/v2_orbit/animation/milkfrog_laugh.blend) |
| 资产与 ROM | [V1 资产](../../assets/milkfrog/v1_fixed/) | [V2 资产](../../assets/milkfrog/v2_orbit/) |
| 总验证报告 | [V1 报告](v1_fixed/reports/final_validation.json) | [V2 报告](v2_orbit/reports/final_validation.json) |
| 重建流程 | [V1 工作流](../../docs/milkfrog_workflow.md) | [V2 工作流](../../docs/milkfrog_orbit_v2.md) |
| SHA-256 清单 | [V1 manifest](v1_fixed/manifest.json) | [V2 manifest](v2_orbit/manifest.json) |

两版都是 541 帧、30 fps、18.033 秒、320×240 RGB332。各自 41,548,800 个原始帧缓冲像素均与独立无深度缓冲软件参考一致；暂停、恢复、复位、循环与 40 MHz 首帧交叉检查通过。两版共用已验证的 SystemVerilog 核心和场景顶层，GPU 数据通路与接口保持原设计，均未增加 Z-buffer；均未进行实体开发板下载测试。源码规范化与前后比较见 [SystemVerilog 迁移说明](../../docs/systemverilog_migration.md)。

| V1 固定镜头预览 | V2 环绕镜头预览 |
| --- | --- |
| ![V1](v1_fixed/rtl_preview.gif) | ![V2](v2_orbit/orbit_preview.gif) |

[同时刻双版本对照视频](v2_orbit/version1_vs_orbit_v2.mp4)用于比较镜头方案。[资产分类与版本索引](../../assets/milkfrog/README.md)说明共享材料和独立输入。

在项目根目录使用对称的 Make 入口；依赖及完整执行顺序见各版工作流：

| 操作 | V1 | V2 |
| --- | --- | --- |
| 生成模型与 ROM | `make milkfrog-v1-assets` | `make milkfrog-v2-assets` |
| 软件参考 | `make milkfrog-v1-preview` | `make milkfrog-v2-preview` |
| 完整 RTL 仿真 | `make milkfrog-v1-sim` | `make milkfrog-v2-sim` |
| 比特流 | `make milkfrog-v1-bit` | `make milkfrog-v2-bit` |
| 40 MHz 交叉检查 | `make milkfrog-v1-crosscheck` | `make milkfrog-v2-crosscheck` |
| 验证并打包 | `make milkfrog-v1-package` | `make milkfrog-v2-package` |

`python tools/check_milkfrog_releases.py` 可在新克隆中直接核对两版文件、输入、ROM、核心与比特流哈希，不依赖 `out/` 或 FPGA 工具。运行缓存与实验候选保存在忽略的 `out/`，正式交付文件不在清理脚本的删除范围内。
