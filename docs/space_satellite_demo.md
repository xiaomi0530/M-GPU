# 环星山谷与巡航卫星

保留第一阶段校准图。第二阶段显示低多边形太空图，停留默认 4 秒。第三阶段沿用同一背景，卫星在左上方空白星空沿 32 帧椭圆轨迹巡航；每帧绘制完成后停留默认 40 ms。BTNU 跳过当前停留，CPU_RESETN 重启全部流程。

## 美术与生成

- 使用内置 imagegen 生成参考图：assets/lowpoly_space/concept.png。
- 完整提示词：assets/lowpoly_space/image_prompt.txt。
- 使用现有 tools/image_triangles.py 的 triangulate，Placement()、tolerance=8、max_triangles=6000，将图片拟合为 RGB332 顶点颜色三角形。跳过全黑三角形后实际背景为 4905 个三角形；场景前另有两个清除三角形。
- tools/build_space_demo.py 从保存的 concept_triangles.json 构建卫星网格、局部清除命令、ROM 和预览。机身使用白/金色，太阳能板使用冰蓝色。每帧 39 条命令，轨迹及姿态离线预计算；FPGA 实时提交三角形并执行光栅化和着色，不直接显示预制 framebuffer。
- 初次画图会逐步完成；背景之后不再重画。逐帧清除矩形限制在 x=60..255、y=55..105，该区域在实际 RGB332 背景中已验证全部为黑色。
- satellite_motion.gif 为按 100 ms/帧播放的设计预览，不能代表实板帧率。satellite_preview.png 是脚本输出，实际仿真截图位于 out/lowpoly/out/framebuffer.png（生成后）。
- tools/view_framebuffer.py 已在 out/lowpoly 工作目录运行以检查导出的 framebuffer，避免覆盖用户已有 out/framebuffer.png。

## 硬件结构

- top.v 保留时钟、复位、按键和 mgpu 实例；末尾的 space_triangle_rom 使用同步读，以推断 BRAM。控制器在 FETCH/LOAD 阶段等待同步 ROM 数据。
- ROM 共 6179 条 84 位三角形命令（24 条校准、4907 条图像、32×39 条动画）。每条为六个 10 位坐标和三个 8 位 RGB332 颜色。
- mgpu、rasterizer、shader、fifo、regs、vga 以及 XDC 均未因本次展示改动。保留当前 6.25 MHz GPU 时钟。
- 原 gpu_done 对某些小三角形可能没有脉冲：top 在确实看到 gpu_busy 之后，如果 rasterizer 已空闲但完成信号未到，等待 8192 拍再前进。该保守边界基于现有 256 深度 FIFO 和约 18 拍/片元的 shader；以后修改核心时应改成准确的绘制完成接口。

## 再生成与验证

在具备 numpy/Pillow 的 Python 中运行 tools/build_space_demo.py；它读取 assets/lowpoly_space/board_wrapper.v.in、concept_triangles.json 并生成 top.v、预览和仿真参考。修改场景后先重新生成，再运行测试。

- space_sequence_tb：使用 SPACE_SCENE_STUB 宏，测试同步 ROM、命令稳定性、边界、32 帧回绕及模拟漏掉 done 时的恢复。
- space_vga_tb：实际 GPU/VGA 联合测试，逐像素比较背景和 33 帧动画，检查每条新命令之前所有前序片元已写回。
- tools/test_vga.ps1 已切换至新场景测试，同时保留独立 VGA 和原 GPU 回归入口。

下载文件：out/vga_current/nexys_a7_vga.bit。尚未实板验证。


## 本次验证结果

- 命令级测试：6218 条命令，32 帧加回绕，模拟每 97 条命令漏掉一次 done，全部通过。
- 实际 GPU/VGA：校准图、完整背景、32 帧加回绕共 33 帧动画均通过；每帧全部 307200 像素与独立参考一致。843170 次写回，5695762 次 VGA 实时读取。
- 在每条新命令开始时，累计输入片元数等于累计写回数，未出现前序像素尚未落盘即开始新命令的情况。
- Vivado 2025.1 布线和 bitstream 通过：sys_clk WNS +1.400 ns，gpu_clk WNS +41.160 ns，最小 WHS +0.039 ns。BRAM 共 101/135（74.81%）。
- 所有 GPU/VGA 核心文件 SHA256 保持不变；重新运行生成脚本得到逐字节一致的 top.v。
