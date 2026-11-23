import hashlib
import json
from pathlib import Path
import shutil

from verify_milkfrog import verify

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'out/milkfrog_orbit_v2'
ANIMATION = ROOT/'assets/milkfrog/v2_orbit/animation'
ROM = ROOT/'assets/milkfrog/v2_orbit/rom'
OUTPUT = ROOT/'deliverables/milkfrog/v2_orbit'
FILES = {
    'milkfrog_nexys_a7.bit': 'build/milkfrog_nexys_a7.bit',
    'milkfrog_orbit_rtl.mp4': 'rtl/milkfrog_board_rtl.mp4',
    'version1_vs_orbit_v2.mp4': 'rtl/version1_vs_orbit_v2.mp4',
    'orbit_preview.gif': 'rtl/orbit_preview.gif',
    'orbit_keyframes.jpg': 'rtl/orbit_keyframes.jpg',
    'orbit_review.jpg': 'rtl/review/orbit_review.jpg',
    'orbit_transitions.jpg': 'rtl/review/orbit_transitions.jpg',
    'reports/final_validation.json': 'rtl/final_validation.json',
    'reports/orbit_review.json': 'rtl/review/orbit_review.json',
    'reports/media_provenance.json': 'rtl/media_provenance.json',
    'reports/editable_blender_validation.json': 'validation/editable_blender_validation.json',
    'reports/build_validation.txt': 'build/build_validation.txt',
    'reports/timing.rpt': 'build/timing.rpt',
    'reports/utilization.rpt': 'build/utilization.rpt',
    'reports/drc.rpt': 'build/drc.rpt',
    'reports/register_init.rpt': 'build/register_init.rpt',
    'reports/framebuffer_init.rpt': 'build/framebuffer_init.rpt',
    'reports/icarus_comparison.json': 'rtl/icarus_40mhz/comparison.json',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    verify(RUN/'rtl', RUN/'build/milkfrog_nexys_a7.bit', RUN/'painter_verified',
           RUN/'validation/editable_blender_validation.json', animation_dir=ANIMATION,
           rom_dir=ROM, projection=RUN/'board_reference/projection.npz')
    review = json.loads((RUN/'rtl/review/orbit_review.json').read_text())
    assert review['engine'] == 'Actual MGPU RTL framebuffer'
    assert review['manifest_sha256'] == digest(ROM/'manifest.json')
    assert review['geometry_sha256'] == digest(ANIMATION/'geometry.npz')
    assert review['camera_matrices_sha256'] == digest(ANIMATION/'camera_matrices.npy')
    assert len(review['frames']) == 541
    for item in review['frames']:
        assert item['sha256'] == digest(RUN/f'rtl/frame_{item["frame"]:04d}.rgb332')
    entries = []
    for name, relative in FILES.items():
        source, destination = RUN/relative, OUTPUT/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        assert digest(source) == digest(destination)
        entries.append(dict(path=name, source=source.relative_to(ROOT).as_posix(),
                            bytes=source.stat().st_size, sha256=digest(source)))
    validation = json.loads((RUN/'rtl/final_validation.json').read_text())
    rom = json.loads((ROM/'manifest.json').read_text())
    config = rom['configuration']
    timing = validation['draw_timing_at_40mhz']
    readme = f'''# 奶蛙 V2：大笑与 360° 环绕镜头

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

最终 ROM：{config['VERTEX_COUNT']} 个顶点、{config['TRIANGLE_COUNT']} 个三角形、{config['KEY_COUNT']} 个矩阵关键帧、{config['ORDER_LIST_COUNT']} 个绘制顺序缓存、{config['ORDER_ENTRY_COUNT']} 条顺序记录。每个可能可见的面均保留；隐藏面剔除和绘制依赖在离线阶段完成。

全部 541 帧的 41,548,800 个像素与独立无深度缓冲定点软件参考完全一致。第 542 个捕获帧验证回到首帧；这不表示原动作的躺倒结尾与站立开头无缝衔接。暂停、恢复和复位通过，40 MHz Icarus 交叉检查通过。最坏清屏与绘制时间为 {timing['max_ms']:.6f} ms（40 MHz），不包括 VGA 呈现等待。

有限的矩阵 ROM 采用 227 个关键帧，整段实际顶点投影的最大坐标插值差为 {review['matrix_interpolation']['maximum_coordinate_error']} px；0.25 px 的初始误差目标未达到。RGB332、原生分辨率、模型近似以及有限绘制顺序缓存仍限制画质。没有进行实体板下载测试。

实现报告：

```text
{validation['bitstream']['validation'].strip()}
```

比特流 SHA-256：`{validation['bitstream']['sha256']}`。`manifest.json` 记录全部交付物和输入哈希；报告保留本次运行路径，完整逐帧捕获可按工作流重建到 `out/milkfrog_orbit_v2/`。
'''
    (OUTPUT/'README.md').write_text(readme, encoding='utf8', newline='\n')
    entries.append(dict(path='README.md', bytes=(OUTPUT/'README.md').stat().st_size,
                        sha256=digest(OUTPUT/'README.md')))
    inputs = [ROOT/'milkfrog.blend', *sorted(ANIMATION.glob('*')), *sorted(ROM.glob('*')),
              *sorted((ROOT/'MGPU.srcs/sources_1/new').glob('*.sv')),
              ROOT/'MGPU.srcs/sources_1/demo/milkfrog_top.sv']
    payload = dict(version='v2_orbit', status='supported', target='Nexys A7-100T / xc7a100tcsg324-1',
                   frames=541, fps=30, resolution=[320, 240], format='RGB332',
                   orbit_degrees=360, hardware_depth_buffer=False, physical_board_tested=False,
                   files=entries, inputs=[dict(path=path.relative_to(ROOT).as_posix(), sha256=digest(path))
                                          for path in inputs if path.is_file()])
    (OUTPUT/'manifest.json').write_text(json.dumps(payload, indent=2)+'\n', encoding='utf8', newline='\n')
    print(f'PACKAGED {len(entries)} verified V2 files in {OUTPUT}')


if __name__ == '__main__':
    main()
