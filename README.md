# M-GPU

## **已经做的**

- **ver1.0 基于纯FSM的Rasterize和直接写Frame buffer**

<figure align="center">

<img src="docs/images/triangle_test0.png" width="600">

<figcaption>
<small>
测试光栅化与颜色插值 (python脚本直接读，无上板)
</small>
</figcaption>

</figure>


<br><br>


- **ver1.1 分离Rasterizer出来到rasterizer.v**

<figure align="center">

<img src="docs/images/ver1_1_figure.png" width="600">

<figcaption>
<small>
再见了一坨中间变量>0<
</small>
</figcaption>

</figure>


<br><br>

- **ver1.2 加入RAST-SHAD-FIFO衔接两模块**

<figure align="center">

<img src="docs/images/triangle_test1.png" width="600">

<figcaption>
<small>
GPT生成的testbench
</small>
</figcaption>

</figure>


<br>


- **ver1.3 加入VGA模块与可控制顶层top.v**
  
<figure align="center">

<img src="docs/images/ver1_3_figure.jpg" width="600">

<figcaption>
<small>
上VGA！
</small>
</figcaption>

</figure>

<br>

- **ver1.4 加入Vertex Shader**
  
<figure align="center">

<img src="docs/images/orbit.gif" width="600">

<figcaption>
<small>
上VGA！
</small>
</figcaption>

</figure>

<br>

- **ver1.5 CPU × GPU × 自制 RTOS**

让 CPU 与 GPU 在自制 RTOS 下协同工作。

<figure align="center">

<img src="docs/images/1.boot.gif" width="600" alt="MCG OS 开屏动画">

<figcaption><small>MCG OS 开屏</small></figcaption>

</figure>

<figure align="center">

<img src="docs/images/2.starwar.gif" width="600" alt="终端启动空战游戏">

<figcaption><small>终端与空战游戏</small></figcaption>

</figure>

<figure align="center">

<img src="docs/images/3.orbit.gif" width="600" alt="ORBIT 自由飞行演示">

<figcaption><small>ORBIT 自由飞行</small></figcaption>

</figure>

<figure align="center">

<img src="docs/images/4.milkdragon.gif" width="600" alt="MIDIYAS GPU 开屏与奶龙三维展示">

<figcaption><small>MIDIYAS GPU 与奶龙</small></figcaption>

</figure>

<br>

## **将要做的**

- ~~做一个Fragment FIFO。~~

- 做一个Fragment Shader

- 引入Depth

- 引入并行机制 

- ~~做一个Vertex Shader~~

- ~~做一个VGA模块，上板收敛时序~~
  
<br>

## **目标做的**

~~**用C命令CPU命令GPU渲染一个3D旋转Cube在VGA屏幕上转圈圈！！！**~~

<br><br><br>


