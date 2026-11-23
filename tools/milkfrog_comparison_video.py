import argparse
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]


def main(output):
    metadata=json.loads((ROOT/'assets/naiwa/reference_motion.json').read_text(encoding='utf8'))
    mapping=metadata['display_mapping'];scale=mapping['uniform_scale'];tx,ty=mapping['translation_xy']
    affine=np.array([[scale,0,tx],[0,scale,ty]],np.float32)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
    small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',18)
    cap=cv2.VideoCapture(str(ROOT/'assets/references/naiwa_laugh/candidate_a_green.mp4'))
    command=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pixel_format','rgb24','-video_size','1280x540','-framerate','30','-i','-',
             '-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(output/'reference_vs_rtl.mp4')]
    process=subprocess.Popen(command,stdin=subprocess.PIPE)
    keyframes=[]
    try:
        for frame in range(541):
            ok,source=cap.read()
            if not ok:raise RuntimeError(f'Reference video ended at frame {frame}')
            reference=cv2.warpAffine(source,affine,(320,240),flags=cv2.INTER_AREA,borderValue=(157,255,130))
            reference=Image.fromarray(cv2.cvtColor(reference,cv2.COLOR_BGR2RGB)).resize((640,480),Image.Resampling.NEAREST)
            actual=Image.open(output/f'frame_{frame:04d}.png').convert('RGB').resize((640,480),Image.Resampling.NEAREST)
            canvas=Image.new('RGB',(1280,540),'#20252b');draw=ImageDraw.Draw(canvas)
            draw.text((20,15),'Reference video - fixed crop',font=font,fill='white')
            draw.text((660,15),'MGPU RTL - 320 x 240 RGB332',font=font,fill='white')
            draw.text((1100,20),f'{frame/30:05.2f} s',font=small,fill='#a8b3bc')
            canvas.paste(reference,(0,60));canvas.paste(actual,(640,60))
            process.stdin.write(canvas.tobytes())
            if frame in (0,84,135,225,315,360,405,417,540):keyframes.append((frame,canvas.copy()))
    finally:
        cap.release();process.stdin.close()
    if process.wait():raise RuntimeError('Comparison video encoder failed')
    sheet=Image.new('RGB',(1280,540*len(keyframes)))
    for row,(_,image) in enumerate(keyframes):sheet.paste(image,(0,row*540))
    sheet.resize((960,round(sheet.height*.75)),Image.Resampling.LANCZOS).save(output/'reference_vs_rtl_keyframes.jpg',quality=94)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate','30','-i',str(output/'frame_%04d.png'),
                    '-vf','trim=end_frame=541,fps=12,scale=480:360:flags=neighbor,split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=none',
                    '-loop','0',str(output/'rtl_preview.gif')],check=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'out/milkfrog_board/rtl');args=parser.parse_args();main(args.output.resolve())
