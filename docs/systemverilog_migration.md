# SystemVerilog 源文件与状态枚举整理

2026-11-24 按项目编码规范统一 RTL、测试平台和构建入口。迁移前版本为 `97a43eb1caaa1227143549da41d6ee73193a6789`，源文件哈希和状态编号映射见 `assets/validation/systemverilog_migration.json`。

## 源文件约定

- 11 个 RTL 和 10 个仿真顶层/测试平台统一使用 `.sv`；两版奶蛙的生成配置头使用 `.svh`。
- 10 个普通 RTL 删除文件头 `timescale` 指令；10 个仿真文件保留原有 `1ns / 1ps` 指令。按用户最终确认，`gpu_clock.sv` 是唯一的 RTL 例外，保留 `timescale 1ns / 1ps` 文件头，用于 `#12.5` 的 40 MHz Icarus 时钟模型，不声明模块内 `timeunit/timeprecision`。
- 所有受维护 RTL/TB 均使用 `logic`，没有 `wire` 或 `reg` 声明。
- 8 个状态机均使用 `typedef enum logic [...]`，枚举成员只写状态名，自动连续编号。FIFO 的读写组合分支、分辨率、地址位宽、帧数等普通常量保持其原有用途。
- 删除生成者标签，格式化工具和生成器不再添加标签；格式化工具保留必要设计注释。

## 状态编号与行为

`shader` 的 `OUT_PIXL`、`DONE` 编号由 6、7 改为 4、5。`rasterizer` 的 `RAST_I_NEX`、`DONE`、`WAIT`、`DIV_WAIT` 编号由 9、10、11、12 改为 8、9、10、11。其他枚举在自动编号后保持原数值。

状态跳转、返回状态和 TB 检查都通过状态名引用，未使用这些内部数值作为外部协议。数据通路、寄存边界、时钟、复位、GPU 接口和无 Z-buffer 绘制方式保持原设计。迁移前后两版各 542 个捕获帧的全部像素及 `frames.csv` 中的周期、三角形和像素写入计数完全一致；每版完整 541 帧的 41,548,800 个像素也与独立软件参考完全一致。

## 工程与生成入口

`MGPU.xpr`、Tcl、Icarus/Verilator 运行器、图片 Studio 导出、Python 测试和两版奶蛙打包工具均使用新扩展名。图片导出生成 `top.sv` 和 `top_image_tb.sv`。状态机规范与 RTL/TB 文件头规则由 `tools/format_hdl.py --check` 检查。

原始模型、动画几何、动作矩阵和三角形/颜色 ROM 不因源码风格整理而改变。已有交付绑定源码哈希，因此两版奶蛙使用迁移后的源码重新运行完整仿真与 FPGA 构建，并更新对应报告和比特流。`assets/naiwa/hardware_baseline.json` 记录本次评审后的 `.sv` 快照，旧基线与新旧文件哈希映射另存于迁移报告。历史报告中的旧源路径仍作为当时运行信息保留。V1 的视觉测量和并排对照素材在核实原始捕获逐字节一致后沿用，新的仿真及实现报告独立生成。

完整回归入口：

```powershell
python tools/format_hdl.py --check --verible C:/path/to/verible-verilog-format.exe
python tools/run_tests.py --python
python tools/check_milkfrog_releases.py
```

两版独立构建、软件参考和 40 MHz 交叉检查使用[正式版本索引](../deliverables/milkfrog/README.md)中的对称命令。最新比特流与时序结果分别以 V1、V2 的交付报告为准。

本次常规回归通过 6 个 RTL 测试平台和 33 个 Python 测试，覆盖 VGA、清屏、场景序列、启动流程、真实 40/100 MHz 双缓冲以及图片 Studio 导出/仿真。50 个 Python 文件的语法检查、工程中 11 个 HDL 引用的路径/文件类型检查和全部 21 个 HDL 文件的格式检查均通过。完整日志保存在 `out/systemverilog_migration/`，用户确认 `gpu_clock.sv` 文件头后的最终复验日志位于 `out/history_consolidation/`；迁移报告记录源码映射、回归日志摘要、逐帧等价校验摘要及交付验证报告的哈希。
