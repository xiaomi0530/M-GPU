# top 全屏清屏

Logo、校准图和太空背景各自开始前，top 发出一拍 `demo_clear`，调用现有 MGPU 清屏逻辑。`CLEAR_WAIT` 先观察 `gpu_busy=1`，再等待其变成 0，随后跳过 ROM 中原来的两个全屏清屏三角形。ROM 编号保留，后续绘图地址不变。

卫星动画仍然使用局部矩形擦除；全屏 clear 会擦掉静态背景，因此不用于每个动画帧。

使用已有 `gpu_busy = rast_busy | clear_busy` 接口，不新增状态端口。用户已补充 `rast_busy` 的复位赋值，因此启动时也可以可靠等待 busy 握手。没有改变清屏计数、shader 或 RGB332 数据结构。

top 仅在启动或前一幅画已完成后的阶段切换处清屏；clear 期间不发 start。当前 6.25 MHz GPU 时钟下，307200 次写入约需 49.15 ms，另有少量握手周期。

`tools/top_clear_support.py` 在生成器完成 Logo 和 Studio 集成后应用相同修改，避免重新生成 top 时恢复旧清屏策略。Image Studio 的自定义三角形输入不自动跳过命令。

`top_tb.v` 同时记录清屏写入并检查它不与绘图写回重叠。trace 的 `P` 事件中 ID 0 表示清屏写入，不计入三角形数量；Framebuffer Studio 支持回放和撤销这些写入。
