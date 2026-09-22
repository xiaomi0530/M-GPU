"""Tk/Pillow desktop viewer for incremental MGPU framebuffer traces."""
from __future__ import annotations

import time
import queue
import threading
from bisect import bisect_left, bisect_right
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from framebuffer_trace import TraceTail

BG = "#090e19"
PANEL = "#111a2b"
SURFACE = "#172238"
LINE = "#273750"
TEXT = "#e4edf8"
MUTED = "#8295b1"
CYAN = "#56e0d1"
PURPLE = "#a796ff"
PALETTE = [channel for value in range(256)
           for channel in ((value >> 5) * 255 // 7,
                           ((value >> 2) & 7) * 255 // 7, (value & 3) * 255 // 3)]


class FramebufferViewer:
    def __init__(self, root: tk.Tk, path: Path, live: bool = False):
        self.root = root
        self.ui_scale = max(1.0, float(root.tk.call("tk", "scaling")) / (96 / 72))
        root.title("MGPU · Framebuffer Studio")
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        width = min(screen_w - 80, round(1280 * self.ui_scale))
        height = min(screen_h - 140, round(900 * self.ui_scale))
        root.geometry(f"{width}x{height}+{max(0, (screen_w-width)//2)}+40")
        root.minsize(min(width, round(1120 * self.ui_scale)),
                     min(height, round(820 * self.ui_scale)))
        root.configure(bg=BG)
        self.tail = TraceTail(path)
        self.follow = live
        self.playing = False
        self.time_ns = 0
        self.first_load = True
        self.selected_id: int | None = None
        self.dragging = False
        self.dirty = True
        self.last_tick = time.perf_counter()
        self.last_metadata = 0.0
        self.last_signature = None
        self.photo = None
        self.image_box = (0, 0, 1, 1)
        self.display_frame = bytearray()
        self._timer = None
        self._closed = False
        self.image_studio = None
        self.project = Path(__file__).resolve().parents[1]
        self.simulation_owner = None
        self.sim_cancel = threading.Event()
        self.sim_messages = queue.Queue()
        self.tree_page = 0
        self._styles()
        self._layout()
        root.protocol("WM_DELETE_WINDOW", self.close)
        # Run shortcuts before ttk class bindings, otherwise Space also clicks
        # the focused button and arrow keys can move the tree selection twice.
        shortcut_tag = f"MGPUPlayback{id(self)}"
        root.bind_class(shortcut_tag, "<space>", self._space)
        root.bind_class(shortcut_tag, "<Left>", lambda event: self._key_seek(event, -100_000))
        root.bind_class(shortcut_tag, "<Right>", lambda event: self._key_seek(event, 100_000))
        root.bind_class(shortcut_tag, "<Control-Left>", lambda event: self._key_triangle(event, -1))
        root.bind_class(shortcut_tag, "<Control-Right>", lambda event: self._key_triangle(event, 1))
        def install_shortcuts(widget):
            widget.bindtags((shortcut_tag,) + widget.bindtags())
            for child in widget.winfo_children():
                install_shortcuts(child)
        install_shortcuts(root)
        self._tick()

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("TButton", background=SURFACE, foreground=TEXT,
                        borderwidth=0, padding=(12, 9), font=("Microsoft YaHei UI", 10))
        style.map("TButton", background=[("active", LINE), ("pressed", "#35475f")])
        style.configure("Accent.TButton", background=CYAN, foreground=BG)
        style.map("Accent.TButton", background=[("active", "#9ff4e9")])
        style.configure("TCheckbutton", background=PANEL, foreground=MUTED,
                        font=("Microsoft YaHei UI", 9))
        style.configure("TRadiobutton", background=PANEL, foreground=TEXT,
                        font=("Microsoft YaHei UI", 9))
        style.map("TRadiobutton", background=[("active", PANEL)])
        style.map("TCheckbutton", background=[("active", PANEL)],
                  foreground=[("active", TEXT)])
        style.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE,
                        foreground=TEXT, arrowcolor=CYAN, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE)],
                  foreground=[("readonly", TEXT)], selectbackground=[("readonly", SURFACE)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=TEXT, rowheight=round(29 * self.ui_scale), borderwidth=0,
                        font=("Consolas", 10))
        style.configure("Treeview.Heading", background=SURFACE, foreground=MUTED,
                        font=("Microsoft YaHei UI", 9), padding=7, borderwidth=0)
        style.map("Treeview", background=[("selected", "#244452")],
                  foreground=[("selected", CYAN)])
        style.configure("Vertical.TScrollbar", background=LINE, troughcolor=PANEL,
                        borderwidth=0, arrowcolor=MUTED)
        self.root.option_add("*TCombobox*Listbox.background", SURFACE)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)

    @staticmethod
    def _label(parent, text="", color=TEXT, size=10, bg=PANEL, **kwargs):
        return tk.Label(parent, text=text, bg=bg, fg=color,
                        font=("Microsoft YaHei UI", size), **kwargs)

    def _layout(self):
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=26, pady=(22, 16))
        tk.Label(top, text="M GPU", font=("Segoe UI", 23, "bold"),
                 fg=CYAN, bg=BG).pack(side="left")
        title = tk.Frame(top, bg=BG)
        title.pack(side="left", padx=20)
        self._label(title, "FRAMEBUFFER STUDIO", TEXT, 12, BG).pack(anchor="w")
        self._label(title, "top.v → GPU → framebuffer · 实时观察与回放", MUTED, 9, BG).pack(anchor="w")
        self.live_button = ttk.Button(top, text="●  实时追踪", style="Accent.TButton", command=self.go_live)
        self.live_button.pack(side="right")
        ttk.Button(top, text="导出当前画面", command=self.export).pack(side="right", padx=8)
        ttk.Button(top, text="图片 → 三角形", command=self.open_image_studio).pack(side="right")

        source = tk.Frame(self.root, bg=PANEL, padx=14, pady=10)
        source.pack(fill="x", padx=26)
        self._label(source, "TRACE", CYAN, 9).pack(side="left", padx=(0, 12))
        self.source_text = self._label(source, str(self.tail.path), MUTED, 9, anchor="w")
        self.source_text.pack(side="left", fill="x", expand=True)
        ttk.Button(source, text="打开日志…", command=self.open_file).pack(side="right")

        simulation = tk.Frame(self.root, bg=BG)
        simulation.pack(fill="x", padx=26, pady=(8,0))
        self.sim_stage = tk.StringVar(value="Logo 开屏")
        self.sim_fast = tk.BooleanVar(value=True)
        ttk.Combobox(simulation,textvariable=self.sim_stage,state="readonly",width=15,
                     values=("Logo 开屏","校准图","太空背景","卫星一圈")).pack(side="left")
        self.sim_button=ttk.Button(simulation,text="运行 top.v",command=self.simulate_top)
        self.sim_button.pack(side="left",padx=8)
        self.sim_stop=ttk.Button(simulation,text="停止仿真",command=self.sim_cancel.set,state="disabled")
        self.sim_stop.pack(side="left")
        ttk.Checkbutton(simulation,text="加速功能仿真（50 MHz / 短停留）",variable=self.sim_fast).pack(side="left",padx=12)
        self.sim_status=self._label(simulation,"仿真顶层 top_tb，设计顶层 top",MUTED,9,BG)
        self.sim_status.pack(side="right")

        stats = tk.Frame(self.root, bg=BG)
        stats.pack(fill="x", padx=26, pady=14)
        self.stat_labels = []
        for column, caption in enumerate(("SOURCE / 数据源", "SIM TIME / 仿真时间", "PIXEL WRITES / 像素写入", "TRIANGLES / 三角形")):
            stats.columnconfigure(column, weight=1, uniform="stat")
            card = tk.Frame(stats, bg=PANEL, padx=16, pady=10)
            card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0))
            self._label(card, caption, MUTED, 8).pack(anchor="w")
            value = self._label(card, "—", CYAN if column == 0 else TEXT, 16)
            value.pack(anchor="w", pady=(4, 0))
            self.stat_labels.append(value)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=26)
        viewport = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        viewport.pack(side="left", fill="both", expand=True)
        view_head = tk.Frame(viewport, bg=PANEL, padx=14, pady=8)
        view_head.pack(fill="x")
        self.resolution = self._label(view_head, "RENDER OUTPUT  /  640 × 480 · RGB332", MUTED, 9)
        self.resolution.pack(side="left")
        self.mode_label = self._label(view_head, "PAUSED", CYAN, 9)
        self.mode_label.pack(side="right")
        self.canvas = tk.Canvas(viewport, bg="#03070e", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=12)
        self.canvas.bind("<Configure>", lambda event: self.invalidate())
        self.canvas.bind("<Motion>", self.inspect_pixel)
        view_foot = tk.Frame(viewport, bg=PANEL, padx=14, pady=8)
        view_foot.pack(fill="x")
        self.pixel_info = self._label(view_foot, "移动鼠标查看像素坐标与 RGB332", MUTED, 9)
        self.pixel_info.pack(side="left")
        self.outline = tk.BooleanVar(value=False)
        ttk.Checkbutton(view_foot, text="三角形轮廓", variable=self.outline,
                        command=self.invalidate).pack(side="right")

        side = tk.Frame(body, bg=PANEL, width=round(282 * self.ui_scale), padx=14, pady=12)
        side.pack(side="right", fill="y", padx=(14, 0))
        side.pack_propagate(False)
        self._label(side, "DRAW CALLS", TEXT, 11).pack(anchor="w")
        self._label(side, "选择一项，跳到该三角形完成时刻", MUTED, 9).pack(anchor="w", pady=(4, 10))
        table = tk.Frame(side, bg=PANEL)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("id", "pixels", "time"), show="headings", selectmode="browse")
        for name, title, width in (("id", "编号", 52), ("pixels", "像素", 83), ("time", "结束 ms", 89)):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=40, anchor="e", stretch=True)
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.select_triangle)
        pages = tk.Frame(side, bg=PANEL)
        pages.pack(fill="x", pady=(5,0))
        ttk.Button(pages, text="‹", width=3, command=lambda: self.change_page(-1)).pack(side="left")
        self.page_label = self._label(pages, "1 / 1", MUTED, 9)
        self.page_label.pack(side="left", expand=True)
        ttk.Button(pages, text="›", width=3, command=lambda: self.change_page(1)).pack(side="right")
        self.isolate = tk.BooleanVar(value=False)
        ttk.Checkbutton(side, text="仅看选中三角形", variable=self.isolate,
                        command=self.invalidate).pack(anchor="w", pady=(12, 6))
        self.triangle_info = self._label(side, "尚未选择三角形", MUTED, 9, justify="left", anchor="w")
        self.triangle_info.pack(anchor="w", fill="x")

        transport = tk.Frame(self.root, bg=PANEL, padx=16, pady=12)
        transport.pack(fill="x", padx=26, pady=(14, 0))
        timeline_head = tk.Frame(transport, bg=PANEL)
        timeline_head.pack(fill="x")
        self._label(timeline_head, "TIMELINE", CYAN, 9).pack(side="left")
        self.time_label = self._label(timeline_head, "0.000 / 0.000 ms", TEXT, 10)
        self.time_label.pack(side="right")
        self.timeline = tk.Canvas(transport, height=42, bg=PANEL, highlightthickness=0, cursor="hand2")
        self.timeline.pack(fill="x", pady=(3, 7))
        self.timeline.bind("<Configure>", lambda event: self.draw_timeline())
        self.timeline.bind("<Button-1>", self.scrub_start)
        self.timeline.bind("<B1-Motion>", self.scrub_move)
        self.timeline.bind("<ButtonRelease-1>", self.scrub_end)
        controls = tk.Frame(transport, bg=PANEL)
        controls.pack(fill="x")
        self.play_button = ttk.Button(controls, text="▶  播放", style="Accent.TButton", command=self.toggle_play)
        self.play_button.pack(side="left")
        for title, command in (("|◀", lambda: self.seek(0)),
                               ("−0.1 ms", lambda: self.seek(self.time_ns - 100_000)),
                               ("+0.1 ms", lambda: self.seek(self.time_ns + 100_000)),
                               ("上一三角形", lambda: self.step_triangle(-1)),
                               ("下一三角形", lambda: self.step_triangle(1))):
            ttk.Button(controls, text=title, command=command).pack(side="left", padx=(6, 0))
        self.speed = tk.StringVar(value="1")
        speed_box = ttk.Combobox(controls, textvariable=self.speed, width=5, state="readonly",
                                 values=("0.01", "0.05", "0.25", "1", "5", "25", "100"))
        speed_box.pack(side="right")
        self._label(controls, "仿真 ms / 秒  ", MUTED, 9).pack(side="right", padx=(10, 0))
        jump_row = tk.Frame(transport, bg=PANEL)
        jump_row.pack(fill="x", pady=(10, 0))
        self._label(jump_row, "定位到", MUTED, 9).pack(side="left")
        self.jump_value = tk.StringVar(value="0.000")
        jump = tk.Entry(jump_row, textvariable=self.jump_value, width=10, bg=SURFACE,
                        fg=TEXT, insertbackground=CYAN, relief="flat", font=("Consolas", 10))
        jump.pack(side="left", padx=8, ipady=4)
        jump.bind("<Return>", lambda event: self.jump_to_time())
        self._label(jump_row, "ms", MUTED, 9).pack(side="left")
        ttk.Button(jump_row, text="跳转", command=self.jump_to_time).pack(side="left", padx=8)
        self._label(jump_row, "Space 播放 / 暂停    ← → 时间步进    Ctrl + ← → 三角形", MUTED, 9).pack(side="right")

        self.footer = self._label(self.root, "准备读取日志…", MUTED, 9, BG, anchor="w")
        self.footer.pack(fill="x", padx=26, pady=(10, 14))

    def invalidate(self):
        self.dirty = True

    def close(self):
        self._closed = True
        self.sim_cancel.set()
        if self.image_studio and not self.image_studio.closed:
            self.image_studio.close()
        if self._timer:
            self.root.after_cancel(self._timer)
        self.root.destroy()

    def claim_simulation(self, owner):
        if self.simulation_owner is not None:
            return False
        self.simulation_owner=owner
        return True

    def release_simulation(self, owner):
        if self.simulation_owner is owner:
            self.simulation_owner=None

    def simulate_top(self):
        if not self.claim_simulation(self):
            messagebox.showinfo("仿真进行中","请先停止当前仿真。",parent=self.root)
            return
        from top_simulation import run_top,SimulationCancelled
        stage={"Logo 开屏":"logo","校准图":"calibration","太空背景":"background","卫星一圈":"animation"}[self.sim_stage.get()]
        fast=self.sim_fast.get()
        output=self.project/"out/studio_top"
        self.sim_cancel.clear()
        self.sim_button.configure(state="disabled");self.sim_stop.configure(state="normal")
        self.watch_trace(output/"framebuffer.trace")
        def work():
            try:
                paths=run_top(self.project,output,self.sim_cancel,stage=stage,frames=32 if stage=="animation" else 1,
                              fast=fast,progress=lambda text:self.sim_messages.put(("progress",text)))
                from view_framebuffer import read_hex_framebuffer,rgb332_to_rgb888,save_with_pillow
                pixels=read_hex_framebuffer(paths["framebuffer"])
                save_with_pillow([rgb332_to_rgb888(v) for v in pixels],output/"framebuffer.png")
                self.sim_messages.put(("done","top.v 仿真完成 · 可回放实际像素写入"))
            except SimulationCancelled:
                self.sim_messages.put(("done","仿真已停止 · 已写入的轨迹可继续回放"))
            except Exception as exc:
                self.sim_messages.put(("error",str(exc)))
            finally:
                self.release_simulation(self)
        threading.Thread(target=work,daemon=True).start()

    def poll_simulation(self):
        while True:
            try:kind,text=self.sim_messages.get_nowait()
            except queue.Empty:break
            self.sim_status.configure(text=text)
            if kind!="progress":
                self.sim_button.configure(state="normal");self.sim_stop.configure(state="disabled")
                if kind=="error":messagebox.showerror("top.v 仿真",text,parent=self.root)

    def open_image_studio(self):
        if self.image_studio and not self.image_studio.closed:
            self.image_studio.window.lift()
            return
        try:
            from image_studio import ImageStudio
        except ImportError as exc:
            messagebox.showerror("图片工具依赖", f"{exc}\n请运行 python -m pip install Pillow numpy", parent=self.root)
            return
        self.image_studio = ImageStudio(self, Path(__file__).resolve().parents[1])

    def watch_trace(self, path: Path):
        self.tail = TraceTail(path)
        self._new_recording()
        self.source_text.configure(text=str(path))
        self.go_live()

    def change_page(self, delta):
        maximum = max(0, (len(self.tail.model.triangles)-1)//200)
        self.tree_page = max(0, min(maximum, self.tree_page+delta))
        self.update_triangle_table()

    def update_triangle_table(self):
        triangles = self.tail.model.triangles
        start = self.tree_page*200
        page = triangles[start:start+200]
        wanted = {str(triangle.id) for triangle in page}
        for item in self.tree.get_children():
            if item not in wanted:
                self.tree.delete(item)
        for triangle in page:
            stop = triangle.last_pixel if triangle.last_pixel is not None else len(self.tail.model.times)
            values = (f"{triangle.id:03d}", f"{stop-triangle.first_pixel:,}",
                      f"{triangle.end_ns/1e6:.3f}" if triangle.end_ns is not None else "写入中")
            item = str(triangle.id)
            if self.tree.exists(item):
                if tuple(map(str,self.tree.item(item,"values"))) != values:
                    self.tree.item(item,values=values)
            else:
                self.tree.insert("","end",iid=item,values=values)
        self.page_label.configure(text=f"{self.tree_page+1} / {max(1,(len(triangles)+199)//200)}")

    def _text_focus(self):
        return isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox))

    def _space(self, event):
        if not self._text_focus():
            self.toggle_play()
            return "break"

    def _key_seek(self, event, delta):
        if not self._text_focus():
            self.seek(self.time_ns + delta)
            return "break"

    def _key_triangle(self, event, delta):
        if not self._text_focus():
            self.step_triangle(delta)
            return "break"

    def seek(self, stamp: int, pause: bool = True):
        if pause:
            self.follow = self.playing = self.first_load = False
        self.time_ns = max(0, min(int(stamp), self.tail.model.latest_ns))
        self.dirty = True

    def go_live(self):
        self.follow = True
        self.playing = self.first_load = False
        self.seek(self.tail.model.latest_ns, pause=False)

    def toggle_play(self):
        self.first_load = False
        if self.follow or self.playing:
            self.follow = self.playing = False
        else:
            if self.time_ns >= self.tail.model.latest_ns:
                self.seek(0)
            self.playing = True
            self.last_tick = time.perf_counter()
        self.dirty = True

    def jump_to_time(self):
        try:
            stamp = float(self.jump_value.get()) * 1_000_000
            self.seek(int(stamp))
        except (ValueError, OverflowError):
            messagebox.showerror("时间格式", "请输入有限的毫秒数，例如 12.5。", parent=self.root)

    def step_triangle(self, delta):
        triangles = self.tail.model.triangles
        if not triangles:
            return
        # Navigate completion boundaries, rather than blindly changing selection.
        ends = [t.end_ns if t.end_ns is not None else self.tail.model.latest_ns for t in triangles]
        if delta > 0:
            index = min(bisect_right(ends, self.time_ns), len(ends) - 1)
        else:
            index = bisect_left(ends, self.time_ns) - 1
        if index < 0:
            self.selected_id = None
            self.tree.selection_remove(*self.tree.selection())
            self.seek(0)
            return
        self.selected_id = triangles[index].id
        self.seek(ends[index])
        if self.tree_page != index//200:
            self.tree_page = index//200
            self.update_triangle_table()
        item = str(self.selected_id)
        if self.tree.exists(item):
            self.tree.selection_set(item)
            self.tree.see(item)

    def select_triangle(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        triangle = self.tail.model.by_id.get(int(selection[0]))
        if triangle:
            self.selected_id = triangle.id
            self.seek(triangle.end_ns if triangle.end_ns is not None else self.tail.model.latest_ns)

    def open_file(self):
        name = filedialog.askopenfilename(parent=self.root, title="打开 MGPU 像素日志",
                                         initialdir=self.tail.path.parent,
                                         filetypes=[("MGPU trace", "*.trace"), ("All files", "*.*")])
        if name:
            self.tail = TraceTail(Path(name))
            self.follow = self.playing = False
            self._new_recording()
            self.source_text.configure(text=name)

    def _new_recording(self):
        self.time_ns = 0
        self.playing = False
        self.selected_id = None
        self.tree_page = 0
        self.first_load = True
        self.last_signature = None
        self.display_frame = bytearray()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.dirty = True

    def scrub_start(self, event):
        self.dragging = True
        self.scrub_move(event)

    def scrub_move(self, event):
        width = max(1, self.timeline.winfo_width() - 24)
        fraction = max(0.0, min(1.0, (event.x - 12) / width))
        self.seek(round(fraction * self.tail.model.latest_ns))

    def scrub_end(self, event):
        self.scrub_move(event)
        self.dragging = False

    def draw_timeline(self):
        canvas = self.timeline
        canvas.delete("all")
        width = max(1, canvas.winfo_width() - 24)
        end = max(1, self.tail.model.latest_ns)
        y = 18
        canvas.create_line(12, y, 12 + width, y, fill=LINE, width=5, capstyle="round")
        triangles = self.tail.model.triangles
        # Dense image meshes can contain 150k triangles; don't allocate 150k
        # Canvas objects every playback frame. The table retains exact entries.
        for triangle in triangles[::max(1,(len(triangles)+599)//600)]:
            if triangle.end_ns is not None:
                x = 12 + width * triangle.end_ns / end
                canvas.create_line(x, 26, x, 31, fill=PURPLE)
        x = 12 + width * self.time_ns / end
        canvas.create_line(12, y, x, y, fill=CYAN, width=5, capstyle="round")
        canvas.create_oval(x - 6, y - 6, x + 6, y + 6, fill=CYAN, outline=TEXT)
        self.time_label.configure(text=f"{self.time_ns / 1e6:.3f} / {self.tail.model.latest_ns / 1e6:.3f} ms")

    def _current_triangle(self):
        model = self.tail.model
        if self.isolate.get() and self.selected_id in model.by_id:
            return model.by_id[self.selected_id]
        return model.triangle_at(self.time_ns)

    def render(self):
        model = self.tail.model
        canvas = self.canvas
        width, height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        if not model.ready:
            canvas.delete("all")
            canvas.create_text(width / 2, height / 2 - 18, text="WAITING FOR PIXELS",
                               fill=CYAN, font=("Segoe UI", 17, "bold"))
            canvas.create_text(width / 2, height / 2 + 20,
                               text="启动仿真，或打开已有的 framebuffer.trace",
                               fill=MUTED, font=("Microsoft YaHei UI", 10))
            return
        count = model.count_at(self.time_ns)
        triangle = self._current_triangle()
        signature = (id(model), count, width, height, self.isolate.get(),
                     triangle.id if triangle else None, self.outline.get())
        if signature == self.last_signature:
            return
        self.last_signature = signature
        if self.isolate.get() and triangle:
            pixels = model.isolated(triangle, count)
        else:
            pixels = model.seek_count(count)
        self.display_frame = bytes(pixels)
        picture = Image.frombytes("P", (model.width, model.height), self.display_frame)
        picture.putpalette(PALETTE)
        ratio = min(width / model.width, height / model.height)
        draw_w, draw_h = max(1, int(model.width * ratio)), max(1, int(model.height * ratio))
        picture = picture.resize((draw_w, draw_h), Image.Resampling.NEAREST).convert("RGB")
        self.photo = ImageTk.PhotoImage(picture, master=self.root)
        canvas.delete("all")
        left, top = (width - draw_w) // 2, (height - draw_h) // 2
        self.image_box = (left, top, draw_w, draw_h)
        canvas.create_image(left, top, image=self.photo, anchor="nw")
        if self.outline.get() and triangle:
            vertices = triangle.vertices
            points = [(left + (vertices[i] + .5) * draw_w / model.width,
                       top + (vertices[i + 1] + .5) * draw_h / model.height) for i in (0, 2, 4)]
            canvas.create_line(*[v for point in points + points[:1] for v in point],
                               fill=CYAN, width=1, dash=(5, 4))

    def inspect_pixel(self, event):
        model = self.tail.model
        if not model.ready or not self.display_frame:
            return
        left, top, width, height = self.image_box
        x = int((event.x - left) * model.width / width)
        y = int((event.y - top) * model.height / height)
        if event.x < left or event.y < top or not (0 <= x < model.width and 0 <= y < model.height):
            self.pixel_info.configure(text="移动鼠标查看像素坐标与 RGB332")
            return
        value = self.display_frame[y * model.width + x]
        self.pixel_info.configure(text=f"X {x:03d}  Y {y:03d}    #{value:02X}    R {value >> 5}  G {(value >> 2) & 7}  B {value & 3}")

    def export(self):
        model = self.tail.model
        if not model.ready:
            messagebox.showinfo("尚无画面", "读取到日志头和像素后即可导出。", parent=self.root)
            return
        self.render()
        name = filedialog.asksaveasfilename(parent=self.root, title="导出当前画面",
                                           initialdir=self.tail.path.parent,
                                           initialfile=f"frame_{self.time_ns}ns.png",
                                           defaultextension=".png", filetypes=[("PNG", "*.png")])
        if name:
            try:
                picture = Image.frombytes("P", (model.width, model.height), self.display_frame)
                picture.putpalette(PALETTE)
                picture.convert("RGB").save(name)
            except OSError as exc:
                messagebox.showerror("导出失败", str(exc), parent=self.root)

    def metadata(self):
        model = self.tail.model
        mode = "LIVE" if self.follow else "PLAYING" if self.playing else "PAUSED"
        status = "日志错误" if self.tail.error else "已完成" if model.complete else "接收中" if model.ready else "等待日志"
        self.stat_labels[0].configure(text=status, fg="#ff8d9d" if self.tail.error else CYAN)
        self.stat_labels[1].configure(text=f"{self.time_ns / 1e6:.3f} ms")
        self.stat_labels[2].configure(text=f"{model.count_at(self.time_ns):,} / {len(model.times):,}")
        started = bisect_right(model.starts, self.time_ns)
        current = model.triangles[started-1] if started else None
        completed = started - int(current is not None and (current.end_ns is None or current.end_ns > self.time_ns))
        self.stat_labels[3].configure(text=f"{completed:02d} / {len(model.triangles):02d}")
        self.mode_label.configure(text=mode)
        self.play_button.configure(text="Ⅱ  暂停" if self.playing or self.follow else "▶  播放")
        self.live_button.configure(text="●  正在追踪" if self.follow else "●  实时追踪")
        if model.ready:
            self.resolution.configure(text=f"RENDER OUTPUT  /  {model.width} × {model.height} · RGB332")
        self.update_triangle_table()
        triangle = self._current_triangle()
        if triangle:
            v = triangle.vertices
            duration = (triangle.end_ns if triangle.end_ns is not None else model.latest_ns) - triangle.start_ns
            self.triangle_info.configure(text=f"TRIANGLE {triangle.id:03d}  ·  {duration / 1e6:.4f} ms\n"
                                         f"A ({v[0]}, {v[1]})\nB ({v[2]}, {v[3]})\nC ({v[4]}, {v[5]})")
        else:
            self.triangle_info.configure(text="尚未开始绘制")
        if self.tail.error:
            footer = "日志错误 · " + self.tail.error
        elif not self.tail.exists:
            footer = "等待文件创建 · 可先打开本窗口，再运行仿真；也可用“打开日志”选择 Vivado 输出目录。"
        elif model.complete:
            footer = "录制完成 · 青色为当前进度，紫色刻度为三角形完成时刻；1 ms/秒表示每秒播放 1 ms 仿真时间。"
        else:
            footer = "日志持续读取中 · 暂停或拖动不会丢失新数据；点击“实时追踪”返回最新位置。"
        self.footer.configure(text=footer)

    def _tick(self):
        if self._closed:
            return
        self.poll_simulation()
        now = time.perf_counter()
        elapsed = min(now - self.last_tick, .2)
        self.last_tick = now
        generation = self.tail.generation
        changed = self.tail.poll()
        if generation != self.tail.generation:
            self._new_recording()
        model = self.tail.model
        if self.tail.error:
            self.playing = False
        if self.follow:
            self.seek(model.latest_ns, pause=False)
        elif self.first_load and changed:
            self.seek(model.latest_ns, pause=False)
            if model.complete:
                self.first_load = False
        elif self.playing:
            self.seek(self.time_ns + round(elapsed * float(self.speed.get()) * 1e6), pause=False)
            if self.time_ns >= model.latest_ns:
                self.playing = False
        if self.first_load and not changed and model.ready:
            self.first_load = False
        if self.dirty or changed:
            self.render()
            self.draw_timeline()
            self.dirty = False
        if now - self.last_metadata > .15 or changed:
            self.metadata()
            self.last_metadata = now
        self._timer = self.root.after(33, self._tick)


def launch(path: Path, live: bool = False) -> None:
    # Make Tk use native display pixels on Windows; no extra GUI dependency.
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    FramebufferViewer(root, path, live)
    root.mainloop()
