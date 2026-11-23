# 奶蛙资产：两个并列正式版本

V1 固定镜头与 V2 环绕镜头具有同等优先级，分别保存完整模型、动作与 ROM。版本号只区分镜头方案。机器可读目录为 [versions.json](versions.json)，可直接观看或下载的成果见[交付索引](../../deliverables/milkfrog/README.md)。

```text
assets/milkfrog/
├── versions.json
├── v1_fixed/
│   ├── animation/   # 模型、动作、表情与原片测量约束
│   └── rom/         # 顶点、三角形、矩阵、时间线、顺序及诊断
└── v2_orbit/
    ├── animation/   # 模型、动作、相机轨迹与侧视口腔补面
    └── rom/         # 独立的全周视角 ROM 及诊断
```

两版的 `animation/milkfrog_laugh.blend` 都是可编辑模型；`geometry.npz`、`matrices.npy` 和各自的 ROM 是对应交付物的输入。V2 使用与 V1 逐字节一致的动作矩阵，并增加相机轨迹和口腔侧视补面。修改其中一版后，需要显式构建该版；不会自动覆盖另一版。

共享原始模型保留于 [`milkfrog.blend`](../../milkfrog.blend)，参考视频和用户姿态图位于 [`assets/references/naiwa_laugh`](../references/naiwa_laugh/)，源 LOD、测量与核心基准位于 [`assets/naiwa`](../naiwa/)。`tools/` 中的投影、排序、仿真及校验工具由两版共享；专用工具的范围见各版工作流。

此次目录整理保持模型、几何、动作、ROM、视频和比特流的字节不变。历史生成元数据中记录的旧路径是当时的来源信息，不能作为当前文件定位入口；当前路径以 `versions.json` 和交付清单为准。`out/milkfrog_board` 与 `out/milkfrog_orbit_v2` 继续分别用作 V1、V2 的可清理运行目录。
