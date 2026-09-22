"""Image placement, adaptive triangulation and simulator controls for Studio."""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from framebuffer_gui import BG, PANEL, SURFACE, TEXT, MUTED, CYAN, LINE
from image_triangles import (Cancelled, Placement, PRESETS, RGB, compose, load_image,
                             quantize, save_bundle, triangulate)


class ImageStudio:
    def __init__(self, owner, project: Path):
        self.owner = owner
        self.project = Path(project)
        self.window = tk.Toplevel(owner.root)
        self.window.title("MGPU · Image Studio")
        scale = owner.ui_scale
        width = min(self.window.winfo_screenwidth()-80, round(1160*scale))
        height = min(self.window.winfo_screenheight()-140, round(820*scale))
        self.window.geometry(f"{width}x{height}+60+60")
        self.window.minsize(min(width, round(1020*scale)), min(height, round(760*scale)))
        self.window.configure(bg=BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.picture = None
        self.source = None
        self.mesh = None
        self.paths = None
        self.busy = False
        self.closed = False
        self.messages = queue.Queue()
        self.cancel = threading.Event()
        self.photo = None
        self.box = (0, 0, 1, 1)
        self.drag_origin = None
        self._preview_timer = None
        self.background = 0
        self.variables = {name: tk.StringVar(value=value) for name, value in
                          (("x","0"),("y","0"),("width","640"),("height","480"))}
        self.preset = tk.StringVar(value="均衡细节")
        self.tolerance = tk.StringVar(value="8")
        self.limit = tk.StringVar(value="12000")
        self.mode = tk.StringVar(value="RGB332")
        self.keep_ratio = tk.BooleanVar(value=True)
        self.mesh_lines = tk.BooleanVar(value=False)
        self.controls = []
        self._layout()
        self._poll_timer = self.window.after(80, self.poll)
        self.redraw()

    def label(self, parent, text, color=MUTED, size=10, **kwargs):
        return tk.Label(parent, text=text, fg=color, bg=parent.cget("bg"),
                        font=("Microsoft YaHei UI", size), **kwargs)

    def button(self, parent, text, command, accent=False):
        widget = ttk.Button(parent, text=text, command=command,
                            style="Accent.TButton" if accent else "TButton")
        self.controls.append(widget)
        return widget

    def _layout(self):
        header = tk.Frame(self.window, bg=BG)
        header.pack(fill="x", padx=22, pady=(18, 14))
        self.label(header, "IMAGE → TRIANGLES", CYAN, 19).pack(side="left")
        self.button(header, "导入图片…", self.import_file, True).pack(side="right")
        self.source_label = self.label(self.window, "PNG / JPEG / WebP / BMP / GIF · 支持透明通道", size=9, anchor="w")
        self.source_label.pack(fill="x", padx=24, pady=(0, 12))

        body = tk.Frame(self.window, bg=BG)
        body.pack(fill="both", expand=True, padx=22)
        sidebar = tk.Frame(body, bg=PANEL, width=round(290*self.owner.ui_scale))
        sidebar.pack(side="right",fill="y",padx=(14,0))
        sidebar.pack_propagate(False)
        self.side_canvas=tk.Canvas(sidebar,bg=PANEL,highlightthickness=0)
        scroll=ttk.Scrollbar(sidebar,orient="vertical",command=self.side_canvas.yview)
        scroll.pack(side="right",fill="y")
        self.side_canvas.pack(side="left",fill="both",expand=True)
        self.side_canvas.configure(yscrollcommand=scroll.set)
        side=tk.Frame(self.side_canvas,bg=PANEL,padx=16,pady=12)
        self.side_window=self.side_canvas.create_window((0,0),window=side,anchor="nw")
        side.bind("<Configure>",lambda event:self.side_canvas.configure(scrollregion=self.side_canvas.bbox("all")))
        self.side_canvas.bind("<Configure>",lambda event:self.side_canvas.itemconfigure(self.side_window,width=event.width))
        stage = tk.Frame(body, bg=PANEL)
        stage.pack(side="left", fill="both", expand=True)
        mode_bar = tk.Frame(stage, bg=PANEL, padx=10, pady=8)
        mode_bar.pack(fill="x")
        self.label(mode_bar, "640 × 480", TEXT, 10).pack(side="left")
        for title in ("原图合成", "RGB332", "三角形预览"):
            widget = ttk.Radiobutton(mode_bar, text=title, value=title,
                                     variable=self.mode, command=self.redraw)
            widget.pack(side="left", padx=5)
        self.canvas = tk.Canvas(stage, bg="#03070e", highlightthickness=0, cursor="fleur")
        self.canvas.pack(fill="both", expand=True, padx=10)
        self.canvas.bind("<Configure>", lambda event: self.redraw())
        self.canvas.bind("<Button-1>", self.drag_start)
        self.canvas.bind("<B1-Motion>", self.drag_move)
        self.canvas.bind("<ButtonRelease-1>", lambda event: setattr(self, "drag_origin", None))
        self.label(stage, "拖动图片调整位置 · 超出屏幕的部分会裁掉", size=9).pack(anchor="w", padx=14, pady=9)

        self.label(side, "01 / 位置与大小", TEXT, 11).pack(anchor="w", pady=(0,10))
        fields = tk.Frame(side, bg=PANEL)
        fields.pack(fill="x")
        for index, (name, caption) in enumerate((("x","X"),("y","Y"),("width","宽度"),("height","高度"))):
            row, col = divmod(index, 2)
            cell = tk.Frame(fields, bg=PANEL)
            cell.grid(row=row,column=col,sticky="ew",padx=(0,10),pady=(0,8))
            fields.columnconfigure(col, weight=1)
            self.label(cell, caption, size=9).pack(anchor="w")
            entry = tk.Entry(cell, textvariable=self.variables[name], width=9, bg=SURFACE,
                             fg=TEXT, insertbackground=CYAN, relief="flat", font=("Consolas",11))
            entry.pack(fill="x", ipady=5)
            entry.bind("<Return>", lambda event, key=name: self.apply_fields(key))
            entry.bind("<FocusOut>", lambda event, key=name: self.apply_fields(key, quiet=True))
            self.controls.append(entry)
        ttk.Checkbutton(side, text="锁定原图比例", variable=self.keep_ratio).pack(anchor="w")
        placement_buttons = tk.Frame(side, bg=PANEL)
        placement_buttons.pack(fill="x", pady=10)
        self.button(placement_buttons, "适合屏幕", self.fit).pack(side="left")
        self.button(placement_buttons, "居中", self.center).pack(side="left", padx=6)
        self.bg_button = self.button(side, "背景  #000000", self.choose_background)
        self.bg_button.pack(fill="x", pady=(0,8))
        self.label(side, "完全透明区域跳过；半透明与背景合成。", size=8, wraplength=round(240*self.owner.ui_scale), justify="left").pack(anchor="w")

        self.label(side, "02 / 自适应三角化", TEXT, 11).pack(anchor="w", pady=(18,10))
        preset = ttk.Combobox(side, textvariable=self.preset, values=tuple(PRESETS), state="readonly")
        preset.pack(fill="x")
        preset.bind("<<ComboboxSelected>>", self.apply_preset)
        self.controls.append(preset)
        for caption, variable in (("误差容限（0 为精确）",self.tolerance), ("三角形数量上限",self.limit)):
            row = tk.Frame(side, bg=PANEL)
            row.pack(fill="x", pady=(8,0))
            self.label(row, caption, size=9).pack(side="left")
            entry = tk.Entry(row, textvariable=variable, width=7, bg=SURFACE, fg=TEXT,
                             insertbackground=CYAN, relief="flat", font=("Consolas",10))
            entry.pack(side="right", ipady=4)
            self.controls.append(entry)
        ttk.Checkbutton(side, text="显示三角形网格", variable=self.mesh_lines,
                        command=self.redraw).pack(anchor="w", pady=10)
        self.generate_button = self.button(side, "生成三角 + top Testbench", self.generate, True)
        self.generate_button.pack(fill="x", pady=(4,8))
        self.simulate_button = self.button(side, "通过 top.v 仿真并查看", self.simulate)
        self.simulate_button.pack(fill="x")
        self.simulate_button.configure(state="disabled")
        self.export_button = self.button(side,"导出上板 top.v",self.export_board)
        self.export_button.pack(fill="x",pady=(8,0))
        self.export_button.configure(state="disabled")
        self.cancel_button = ttk.Button(side, text="取消当前操作", command=self.cancel.set, state="disabled")
        self.cancel_button.pack(fill="x", pady=8)

        def wheel(event):
            self.side_canvas.yview_scroll(-1 if event.delta>0 else 1,"units")
            return "break"
        def bind_wheel(widget):
            widget.bind("<MouseWheel>",wheel)
            for child in widget.winfo_children():bind_wheel(child)
        bind_wheel(side)
        self.side_canvas.bind("<MouseWheel>",wheel)

        self.metrics = self.label(self.window, "导入图片后，调整位置并点击生成。", TEXT, 11, anchor="w")
        self.metrics.pack(fill="x", padx=24, pady=(14,4))
        self.status = self.label(self.window, "精确模式保留量化后的像素；均衡模式用更少三角形近似。", size=9, anchor="w", justify="left")
        self.status.pack(fill="x", padx=24, pady=(0,18))

    def placement(self):
        values = {name: int(variable.get()) for name, variable in self.variables.items()}
        if abs(values["x"]) > 8192 or abs(values["y"]) > 8192:
            raise ValueError("位置应在 -8192～8192 之间。")
        if not 1 <= values["width"] <= 4096 or not 1 <= values["height"] <= 4096:
            raise ValueError("宽度和高度应在 1～4096 之间。")
        return Placement(**values, background=self.background)

    def import_file(self):
        path = filedialog.askopenfilename(parent=self.window, title="导入全彩或透明图片",
                                         filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"), ("All files","*.*")])
        if path:
            try:
                self.load_path(Path(path))
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                messagebox.showerror("图片读取失败", str(exc), parent=self.window)

    def load_path(self, path: Path):
        self.picture = load_image(path)
        self.source = Path(path)
        self.source_label.configure(text=f"{self.source.name}  ·  {self.picture.width} × {self.picture.height}  ·  RGBA")
        self.fit()

    def changed(self):
        self._last_fields = tuple(variable.get() for variable in self.variables.values()) + (self.background,)
        self.mesh = self.paths = None
        self.simulate_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.metrics.configure(text="位置或图片已更新 · 需要重新生成三角形。")
        if self.mode.get() == "三角形预览":
            self.mode.set("RGB332")
        if self._preview_timer:
            self.window.after_cancel(self._preview_timer)
        self._preview_timer = self.window.after(30, self.redraw)

    def apply_fields(self, key=None, quiet=False):
        if self.busy or self.picture is None:
            return
        try:
            placement = self.placement()
            if self.keep_ratio.get() and key in ("width", "height"):
                if key == "width":
                    self.variables["height"].set(str(max(1, round(placement.width*self.picture.height/self.picture.width))))
                else:
                    self.variables["width"].set(str(max(1, round(placement.height*self.picture.width/self.picture.height))))
                self.placement()
            current = tuple(variable.get() for variable in self.variables.values()) + (self.background,)
            if current != getattr(self, "_last_fields", None):
                self._last_fields = current
                self.changed()
        except ValueError as exc:
            if not quiet:
                messagebox.showerror("位置参数", str(exc), parent=self.window)

    def fit(self):
        if self.picture is None:
            return
        scale = min(640/self.picture.width, 480/self.picture.height, 1.)
        self.variables["width"].set(str(max(1, round(self.picture.width*scale))))
        self.variables["height"].set(str(max(1, round(self.picture.height*scale))))
        self.center()

    def center(self):
        try:
            p = self.placement()
            self.variables["x"].set(str((640-p.width)//2))
            self.variables["y"].set(str((480-p.height)//2))
            self.changed()
        except ValueError as exc:
            messagebox.showerror("位置参数", str(exc), parent=self.window)

    def choose_background(self):
        initial = "#" + "".join(f"{value:02x}" for value in RGB[self.background])
        color, _ = colorchooser.askcolor(color=initial, parent=self.window, title="选择透明区域的背景颜色")
        if color:
            self.background = int(quantize(np.array(color, dtype=np.uint8)))
            self.bg_button.configure(text="背景  #" + "".join(f"{v:02X}" for v in RGB[self.background]))
            self.changed()

    def apply_preset(self, event=None):
        tolerance, maximum = PRESETS[self.preset.get()]
        self.tolerance.set(str(tolerance))
        self.limit.set(str(maximum))

    def drag_start(self, event):
        if self.busy or self.picture is None:
            return
        try:
            p = self.placement()
            left, top, width, height = self.box
            x, y = (event.x-left)*640/width, (event.y-top)*480/height
            if p.x <= x < p.x+p.width and p.y <= y < p.y+p.height:
                self.drag_origin = (event.x,event.y,p.x,p.y)
        except ValueError:
            pass

    def drag_move(self, event):
        if not self.drag_origin or self.busy:
            return
        ex, ey, px, py = self.drag_origin
        self.variables["x"].set(str(max(-8192,min(8192,px+round((event.x-ex)*640/self.box[2])))))
        self.variables["y"].set(str(max(-8192,min(8192,py+round((event.y-ey)*480/self.box[3])))))
        self.changed()

    def redraw(self):
        if self.closed:
            return
        self._preview_timer = None
        width, height = max(1,self.canvas.winfo_width()), max(1,self.canvas.winfo_height())
        self.canvas.delete("all")
        if self.picture is None:
            self.canvas.create_text(width/2,height/2-16,text="YOUR IMAGE. YOUR GPU.",fill=CYAN,font=("Segoe UI",18,"bold"))
            self.canvas.create_text(width/2,height/2+24,text="导入图片，生成真实三角形绘制指令",fill=MUTED,font=("Microsoft YaHei UI",10))
            return
        try:
            p = self.placement()
            if self.mesh and self.mode.get() == "三角形预览":
                picture = Image.fromarray(RGB[self.mesh.prediction])
            else:
                target, _, original = compose(self.picture, p)
                picture = original if self.mode.get() == "原图合成" else Image.fromarray(RGB[target])
            if self.mesh and self.mesh_lines.get():
                pen = ImageDraw.Draw(picture)
                for tri in self.mesh.triangles:
                    v = tri.values
                    pen.line([v[:2],v[2:4],v[4:6],v[:2]],fill=(75,170,160),width=1)
            scale = min(width/640,height/480)
            draw_w, draw_h = max(1,round(640*scale)), max(1,round(480*scale))
            self.box = ((width-draw_w)//2,(height-draw_h)//2,draw_w,draw_h)
            self.photo = ImageTk.PhotoImage(picture.resize((draw_w,draw_h),Image.Resampling.NEAREST),master=self.window)
            left, top, _, _ = self.box
            self.canvas.create_image(left,top,image=self.photo,anchor="nw")
            x0,y0 = max(0,p.x),max(0,p.y)
            x1,y1 = min(640,p.x+p.width),min(480,p.y+p.height)
            if x1>x0 and y1>y0:
                self.canvas.create_rectangle(left+x0*scale,top+y0*scale,left+x1*scale,top+y1*scale,
                                             outline=CYAN,dash=(5,4))
        except ValueError:
            self.canvas.create_text(width/2,height/2,text="请输入有效的位置与尺寸",fill=MUTED)

    def set_busy(self, value):
        self.busy = value
        for widget in self.controls:
            widget.configure(state="disabled" if value else "readonly" if isinstance(widget,ttk.Combobox) else "normal")
        self.simulate_button.configure(state="normal" if not value and self.paths else "disabled")
        self.cancel_button.configure(state="normal" if value else "disabled")
        self.export_button.configure(state="normal" if not value and self.mesh is not None else "disabled")

    def generate(self):
        if self.busy:
            return
        if self.picture is None:
            self.import_file()
            if self.picture is None:
                return
        try:
            placement = self.placement()
            tolerance, maximum = float(self.tolerance.get()), int(self.limit.get())
            if not np.isfinite(tolerance) or tolerance < 0 or not 2 <= maximum <= 160000:
                raise ValueError("误差应非负，三角形上限应在 2～160000 之间。")
        except ValueError as exc:
            messagebox.showerror("生成参数",str(exc),parent=self.window)
            return
        self.cancel.clear()
        self.set_busy(True)
        self.status.configure(text="正在自适应划分：平坦区域合并，细节与透明边缘细分…")
        picture = self.picture.copy()
        def work():
            try:
                last = [0.]
                def progress(count):
                    now = time.monotonic()
                    if now-last[0] > .2:
                        self.messages.put(("progress",f"正在细分 · {count:,} 个三角形"))
                        last[0] = now
                mesh = triangulate(picture,placement,tolerance,maximum,self.cancel,progress)
                if self.cancel.is_set():
                    raise Cancelled()
                paths = save_bundle(mesh,self.project,str(self.source))
                self.messages.put(("mesh",(mesh,paths)))
            except Cancelled:
                self.messages.put(("cancelled",None))
            except Exception as exc:
                self.messages.put(("error",str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def export_board(self):
        if self.busy or self.mesh is None:
            return
        try:
            from export_image_top import export_top
            path=export_top(self.mesh,self.project)
            self.status.configure(text=f"已导出独立上板包：{path.parent}；原工程演示未覆盖。")
        except Exception as exc:
            messagebox.showerror("导出上板 top.v",str(exc),parent=self.window)

    def simulate(self):
        if self.busy or not self.paths:
            return
        if not self.owner.claim_simulation(self):
            messagebox.showinfo("仿真进行中","请先停止当前 top.v 仿真。",parent=self.window)
            return
        from top_simulation import run_top,SimulationCancelled
        self.cancel.clear()
        self.set_busy(True)
        self.status.configure(text="正在编译 top.v · 图片通过顶层命令控制器进入 GPU。")
        output=self.project/"out/studio_image"
        self.owner.watch_trace(output/"framebuffer.trace")
        self.owner.root.lift()
        paths=self.paths.copy()
        expected=self.mesh.prediction.copy()
        fast=self.owner.sim_fast.get()
        def work():
            try:
                results=run_top(self.project,output,self.cancel,testbench=paths["testbench"],
                                module="top_image_tb",scene=paths["scene"],fast=fast,
                                progress=lambda text:self.messages.put(("progress",text)))
                actual=np.array([int(line,16) for line in results["framebuffer"].read_text().split()],dtype=np.uint8).reshape((480,640))
                different=int(np.count_nonzero(actual!=expected))
                if different:
                    raise RuntimeError(f"top.v 输出与三角形预览有 {different:,} 个像素不同；日志：{results['log']}")
                Image.fromarray(RGB[actual]).save(output/"framebuffer.png")
                self.messages.put(("simulated",None))
            except SimulationCancelled:
                self.messages.put(("cancelled",None))
            except Exception as exc:
                self.messages.put(("error",str(exc)))
            finally:
                self.owner.release_simulation(self)
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.status.configure(text=value)
            else:
                self.set_busy(False)
                if kind == "mesh":
                    self.mesh,self.paths = value
                    self.mode.set("三角形预览")
                    self.simulate_button.configure(state="normal")
                    self.export_button.configure(state="normal")
                    mesh = self.mesh
                    self.metrics.configure(text=f"{len(mesh.triangles):,} 个三角形  ·  RGB 误差 {mesh.rmse:.2f}  ·  可见像素一致率 {mesh.exact_percent:.2f}%")
                    suffix = "已达到数量上限，当前为近似结果。" if mesh.budget_limited else ""
                    self.status.configure(text="已生成 out/image_scene.tri 与 out/top_image_tb.v；以 top.v 为设计顶层运行。" + suffix)
                    self.redraw()
                elif kind == "simulated":
                    self.status.configure(text="仿真通过 · top.v 输出与三角形预览逐像素一致。回放与图片在 out/studio_image/。")
                elif kind == "cancelled":
                    self.status.configure(text="操作已取消。")
                else:
                    self.status.configure(text="操作失败 · " + value)
                    messagebox.showerror("Image Studio",value,parent=self.window)
        self._poll_timer = self.window.after(80,self.poll)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel.set()
        if self._preview_timer:
            self.window.after_cancel(self._preview_timer)
        self.window.after_cancel(self._poll_timer)
        self.window.destroy()
