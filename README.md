# M-GPU

完全无GPU基础，边做边学，纯老一辈手工敲代码项目。

基于 VGA 屏幕 **640*480** **RGB332**。

<br>


## **已经做的**

- **ver1.0 基于纯FSM的Rasterize和直接写Frame buffer**

<figure align="center">

<img src="out/triangle_test0.png" width="600">

<figcaption>
<small>
测试光栅化与颜色插值 (python脚本直接读，无上板)
</small>
</figcaption>

</figure>


<br>


- **ver1.1 分离Rasterizer出来到rasterizer.v**

<figure align="center">

<img src="out/ver1_1_figure.png" width="600">

<figcaption>
<small>
再见了一坨中间变量>0<
</small>
</figcaption>

</figure>


<br>


## **将要做的**

- 做一个Fragment FIFO。

- 做一个Shader

- 引入Depth

- 做一个VGA模块，上板收敛时序


<br>


## **目标做的**

**用C命令CPU命令GPU渲染一个3D旋转Cube在VGA屏幕上转圈圈！！！**