# 奶蛙 V2：大笑与 360° 环绕镜头

这是与 [V1 固定镜头](../v1_fixed/README.md) 同等维护的正式版本，两版均可独立查看和下载，统一入口见 [版本索引](../README.md)。保留完整 541 帧动作，相机在 18.033 秒内绕世界 Z 轴一周，保持固定正交尺度并平滑跟随躯干。本目录视频来自真实 MGPU RTL 帧缓冲，原生 320×240、RGB332、30 fps。

| 文件 | 用途 |
| --- | --- |
| [milkfrog_orbit_rtl.mp4](milkfrog_orbit_rtl.mp4) | 完整第二版实际 RTL 仿真视频 |
| [version1_vs_orbit_v2.mp4](version1_vs_orbit_v2.mp4) | 同时刻第一版固定镜头与第二版环绕镜头对照 |
| [orbit_preview.gif](orbit_preview.gif) | 完整动画预览 |
| [orbit_keyframes.jpg](orbit_keyframes.jpg) | 整圈镜头的 12 张关键帧 |
| [orbit_review.jpg](orbit_review.jpg) | 遮挡、侧视嘴部、倒地与缓存切换抽查帧 |
| [orbit_transitions.jpg](orbit_transitions.jpg) | 起跳、转身与着地的连续帧复核 |
| [milkfrog_nexys_a7.bit](milkfrog_nexys_a7.bit) | Nexys A7-100T / xc7a100tcsg324-1 比特流 |
| [reports/final_validation.json](reports/final_validation.json) | 真实 RTL、完整软件参考、控制、时钟及比特流核验 |
| [reports/orbit_review.json](reports/orbit_review.json) | 相机、几何、插值误差及逐帧图像测量 |

可编辑模型为 [assets/milkfrog/v2_orbit/animation/milkfrog_laugh.blend](../../../assets/milkfrog/v2_orbit/animation/milkfrog_laugh.blend)，重建命令见 [V2 工作流](../../../docs/milkfrog_orbit_v2.md)。原始用户模型未改动；核心与场景顶层使用已验证的 SystemVerilog 源码基线，GPU 数据通路和接口保持原设计，没有新增 Z-buffer。源码规范化记录见 [迁移说明](../../../docs/systemverilog_migration.md)。

侧视时可见的口腔后部新增 65 个顶点、96 个三角形，其余第一版几何与 18 组动作矩阵保持一致。背面和侧面属于在已有模型基础上的新视角，不能用原片固定镜头的轮廓相似度评分代替验证。

最终 ROM：5021 个顶点、9225 个三角形、227 个矩阵关键帧、26 个绘制顺序缓存、131070 条顺序记录。每个可能可见的面均保留；隐藏面剔除和绘制依赖在离线阶段完成。

全部 541 帧的 41,548,800 个像素与独立无深度缓冲定点软件参考完全一致。第 542 个捕获帧验证回到首帧；这不表示原动作的躺倒结尾与站立开头无缝衔接。暂停、恢复和复位通过，40 MHz Icarus 交叉检查通过。最坏清屏与绘制时间为 27.240375 ms（40 MHz），不包括 VGA 呈现等待。

有限的矩阵 ROM 采用 227 个关键帧，整段实际顶点投影的最大坐标插值差为 3 px；0.25 px 的初始误差目标未达到。RGB332、原生分辨率、模型近似以及有限绘制顺序缓存仍限制画质。没有进行实体板下载测试。

实现报告：

```text
PASS: milkfrog_top xc7a100tcsg324-1
BRAM tiles: 126.0 / 135
Setup slack: 0.821 ns
Hold slack: 0.045 ns
DRC errors: 0
Framebuffer zero INIT words: 6912
```

比特流 SHA-256：`70936bdf531e1d2cd0383dde0df550ced69c3ff99efff35b872c3a9eeb96c54e`。`manifest.json` 记录全部交付物和输入哈希；报告保留本次运行路径，完整逐帧捕获可按工作流重建到 `out/milkfrog_orbit_v2/`。
