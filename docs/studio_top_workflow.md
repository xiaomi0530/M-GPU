# 仿真与 Studio

## 命令行入口

```powershell
python tools/top_simulation.py --output out/simulation
python tools/view_framebuffer.py out/simulation/framebuffer.hex
python tools/run_tests.py --python
```

默认录制机械晶核第 0 帧。`--stage logo --frames 1` 录制开屏；`--frames N --dump-frames` 保存连续帧；`--board-clock` 使用板级 40 MHz 时钟。运行器复制 ROM 到本次输出目录，再在该目录启动仿真，支持包含空格的路径。

输出为 `framebuffer.trace`、`framebuffer.hex`、`framebuffer.json` 和 `simulation.log`。HEX 保存原生 320×240 RGB332，查看器默认放大到 640×480。测试根模块是 `top_tb`，设计顶层始终是 `top`。

## 图形界面

```powershell
python tools/view_framebuffer.py
```

Framebuffer Studio 提供机械晶核与 MIDIYAS GPU 开屏的录制、回放、时间轴和像素写回检查。屏幕视图只在真正交换前缓冲后更新；绘制视图展示后缓冲的逐像素过程。

Image Studio 导入图片、三角化后生成 `out/image_scene.tri`、`out/top_image_tb.sv`、预览与参考像素。仿真通过 `STUDIO_SIMULATION` 宏接入 `studio_triangle_source`，随后使用当前顶层和真实 GPU 的清屏、绘制与交换流程。

```powershell
python tools/top_simulation.py --scene out/image_scene.tri --output out/studio_image
```

两种 Studio 共享仿真占用状态；取消或关闭窗口会终止所属仿真进程。`MGPU_TRACE 2` 记录后缓冲像素写入和前缓冲交换，查看器保留对旧日志的读取支持。

## 图片上板导出

Image Studio 的“导出上板 top.sv”写入 `out/image_export/`。包内包含独立 `top.sv`、GPU/VGA 核心、XDC 和 `build.tcl`，复用当前双缓冲顶层控制器，以静态图片 ROM 替换仿真输入源。输出不依赖主工程的机械场景 ROM。

最多 8190 个图片三角形，另含两条背景命令；超出时明确报错。每个包仍需在其目录运行 `vivado -mode batch -source build.tcl`，完成实现与时序检查后才能确认上板结果。

## 场景与 ROM

当前开屏共 420 个相位，随后衔接机械晶核相位 25。机械动画共 512 个相位，每 8 相位保存一次矩阵关键帧，其间做定点插值。生成入口：

```powershell
python tools/build_vertex_lab.py
```

生成器更新 `MGPU.srcs/sources_1/rom/` 和顶层中相关常量，不再覆盖整个控制器。预览图可用 `tools/orbit_scene.py`、`tools/midiyas_logo.py` 重新生成。`verify_intro.py`、`verify_mechanical.py` 用于场景数值检查，`verify_vertex_lab.py` 用于实际 framebuffer 的逐像素比对。
