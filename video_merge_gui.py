"""Desktop interface for local encrypted HLS downloads."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from decrypt_merge import find_ffmpeg, rewrite_playlist
import bluestacks_import


def desktop():
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0:
        return Path(buffer.value)
    return Path.home() / "Desktop"


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.running = False
        self.result = None
        self.log = None
        root.title("视频解密合并")
        if getattr(sys, "frozen", False):
            root.iconbitmap(default=sys.executable)
        root.configure(bg="#f3f5f9")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f9")
        style.configure("TLabel", background="#f3f5f9", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=8)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("TProgressbar", background="#3869d4")
        frame = ttk.Frame(root, padding=28)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="将分片视频合成完整 MP4", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text="自动识别北大好学 APP 中下载的", wraplength=620).grid(row=1, column=0, sticky="w", pady=(8, 22))
        self.folder = tk.StringVar()
        self.output = tk.StringVar(value=str(desktop()))
        self.inputs = []
        for row, label, variable in [(2, "视频源文件夹", self.folder), (4, "保存到", self.output)]:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(frame, textvariable=variable, font=("Microsoft YaHei UI", 10))
            entry.grid(row=row+1, column=0, sticky="ew", pady=(6, 16))
            button = ttk.Button(frame, text="浏览…", command=lambda v=variable: self.browse(v))
            button.grid(row=row+1, column=1, padx=(10, 0), pady=(6, 16))
            self.inputs.extend([entry, button])
        self.progress = ttk.Progressbar(frame, maximum=100)
        self.progress.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(6, 10))
        self.status = tk.StringVar(value="选择源文件夹，然后点击开始合并。")
        ttk.Label(frame, textvariable=self.status, wraplength=620).grid(row=7, column=0, columnspan=2, sticky="w")
        actions = ttk.Frame(frame)
        actions.grid(row=8, column=0, columnspan=2, sticky="w", pady=(22, 0))
        self.start_button = ttk.Button(actions, text="开始合并", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="取消", state="disabled", command=self.stop)
        self.stop_button.pack(side="left", padx=10)
        self.open_button = ttk.Button(actions, text="打开输出文件夹", command=self.open_output)
        self.open_button.pack(side="left")
        self.log_button = ttk.Button(actions, text="查看日志", command=self.open_log, state="disabled")
        self.log_button.pack(side="left", padx=10)
        self.import_button = ttk.Button(frame, text="从 BlueStacks 导入…", command=self.scan_emulator)
        self.import_button.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        self.inputs.append(self.import_button)
        logo_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "personal_logo.png"
        original_logo = tk.PhotoImage(file=str(logo_path))
        factor = max(1, round(original_logo.width() / 88))
        self.logo_image = original_logo.subsample(factor, factor)
        self.logo_button = tk.Button(frame, image=self.logo_image, cursor="hand2",
                                     relief="flat", borderwidth=0, highlightthickness=1,
                                     highlightbackground="#e2e5ec", background="white",
                                     activebackground="white", takefocus=True,
                                     command=lambda: messagebox.showinfo("关于本软件", "本软件由化院 24 本郭嘉开发，祝使用愉快。", parent=root))
        self.logo_button.grid(row=0, column=1, rowspan=2, sticky="ne", padx=(16, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.fit_window()
        root.after(100, self.poll)

    def fit_window(self):
        # Tk fonts follow Windows DPI; a fixed pixel size does not.
        # Measure the complete layout before choosing the initial client size.
        self.root.update_idletasks()
        area = wintypes.RECT()
        if not ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0):
            area = wintypes.RECT(0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        available_w = area.right - area.left
        available_h = area.bottom - area.top
        width = max(720, self.root.winfo_reqwidth() + 24)
        height = max(460, self.root.winfo_reqheight() + 24)
        # Leave room for the title bar and taskbar on smaller displays.
        if width > available_w - 48 or height > available_h - 80:
            ratio = min((available_w - 48) / width, (available_h - 80) / height)
            # Positive Tk font sizes are points. Compact only when necessary.
            for widget in self.root.winfo_children():
                self.compact_fonts(widget, ratio)
            style = ttk.Style()
            style.configure("TLabel", font=("Microsoft YaHei UI", max(8, int(10 * ratio))))
            style.configure("TButton", font=("Microsoft YaHei UI", max(8, int(10 * ratio))))
            style.configure("Title.TLabel", font=("Microsoft YaHei UI", max(12, int(22 * ratio)), "bold"))
            self.root.update_idletasks()
            width = self.root.winfo_reqwidth() + 24
            height = self.root.winfo_reqheight() + 24
        width = min(width, available_w - 32)
        height = min(height, available_h - 64)
        x = area.left + (available_w - width) // 2
        y = area.top + max(0, (available_h - height - 40) // 2)
        self.root.minsize(width, height)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def compact_fonts(self, widget, ratio):
        if isinstance(widget, ttk.Entry):
            widget.configure(font=("Microsoft YaHei UI", max(8, int(10 * ratio))))
        for child in widget.winfo_children():
            self.compact_fonts(child, ratio)

    def browse(self, variable):
        selected = filedialog.askdirectory(parent=self.root, title="选择文件夹")
        if selected:
            variable.set(os.path.normpath(selected))

    def busy(self, text):
        self.running = True
        self.cancel.clear()
        self.progress["value"] = 0
        self.status.set(text)
        for widget in self.inputs + [self.start_button]:
            widget.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def scan_emulator(self):
        if self.running:
            return
        self.busy("正在查找模拟器里的已下载视频…")
        def scan():
            try:
                self.events.put(("scanned", bluestacks_import.scan(self.cancel)))
            except bluestacks_import.Cancelled:
                self.events.put(("cancelled", None))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=scan, daemon=True).start()

    def choose_video(self, videos):
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        dialog.title("选择模拟器中的视频")
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="请先在好学 APP 中确认下载完成，再选择视频导入。", wraplength=600).pack(anchor="w", pady=(0, 12))
        labels = []
        for video in videos:
            seconds = int(video["duration"])
            labels.append(f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02} · {video["count"]} 分片 · {video["name"][:12]} · {video["serial"]}')
        choice = ttk.Combobox(frame, values=labels, state="readonly", width=65)
        choice.pack(fill="x")
        choice.current(0)
        ttk.Label(frame, text="输出文件名（可修改）").pack(anchor="w", pady=(16, 6))
        filename = tk.StringVar(value="好学视频_" + Path(videos[0]["name"]).stem[:12])
        entry = ttk.Entry(frame, textvariable=filename)
        entry.pack(fill="x")
        def selected(event=None):
            filename.set("好学视频_" + Path(videos[choice.current()]["name"]).stem[:12])
        choice.bind("<<ComboboxSelected>>", selected)
        def begin():
            name = filename.get().strip()
            output_text = self.output.get().strip().strip('"')
            if not name or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith((".", " ")) or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
                messagebox.showinfo("请修改名称", "请输入有效的 Windows 文件名。", parent=dialog)
                return
            if not output_text:
                messagebox.showinfo("请选择保存位置", "请先在主窗口设置输出文件夹。", parent=dialog)
                return
            video = videos[choice.current()]
            if not video["complete"]:
                messagebox.showinfo("下载尚未完成", "请等待好学 APP 下载完成后重新扫描。", parent=dialog)
                return
            dialog.destroy()
            self.result = None
            self.busy("正在从模拟器复制文件…")
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
            threading.Thread(target=self.import_work, args=(video, Path(output_text).resolve(), name.removesuffix(".mp4")), daemon=True).start()
        ttk.Button(frame, text="导入并合并", command=begin).pack(anchor="e", pady=(18, 0))
        dialog.update_idletasks()
        dialog.minsize(dialog.winfo_reqwidth(), dialog.winfo_reqheight())
        dialog.deiconify()
        dialog.grab_set()

    def import_work(self, video, destination, name):
        try:
            destination.mkdir(parents=True, exist_ok=True)
            # Unique disposable copy; never modify or delete Android originals.
            with tempfile.TemporaryDirectory(prefix=".haoxue-import-", dir=destination) as temp:
                source = bluestacks_import.fetch(video, Path(temp), self.cancel,
                                                lambda text: self.events.put(("status", text)))
                if self.cancel.is_set():
                    raise bluestacks_import.Cancelled()
                self.events.put(("imported", None))
                self.work(source, destination, name)
        except bluestacks_import.Cancelled:
            self.events.put(("cancelled", None))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def open_output(self):
        path = self.result.parent if self.result else Path(self.output.get())
        if path.is_dir():
            os.startfile(str(path))

    def open_log(self):
        if self.log and self.log.exists():
            os.startfile(str(self.log))

    def start(self):
        if self.running:
            return
        folder_text = self.folder.get().strip().strip('"')
        output_text = self.output.get().strip().strip('"')
        if not folder_text or not Path(folder_text).is_dir():
            messagebox.showinfo("请选择文件夹", "请输入包含 M3U8、密钥和分片目录的文件夹。")
            return
        if not output_text:
            messagebox.showinfo("请选择保存位置", "请输入输出文件夹。")
            return
        folder, destination = Path(folder_text).resolve(), Path(output_text).resolve()
        playlists = sorted(folder.glob("*.m3u8"))
        if len(playlists) != 1:
            messagebox.showinfo("无法选择清单", "源文件夹内需要有且只有一个 M3U8 清单。")
            return
        self.running = True
        self.result = None
        self.cancel.clear()
        self.progress["value"] = 0
        self.status.set("正在识别文件，准备合并…")
        for widget in self.inputs + [self.start_button]:
            widget.configure(state="disabled")
        self.stop_button.configure(state="normal")
        threading.Thread(target=self.work, args=(playlists[0], destination), daemon=True).start()

    def stop(self):
        self.cancel.set()
        self.stop_button.configure(state="disabled")
        self.status.set("正在停止…")

    def close(self):
        if self.running:
            self.stop()
            self.status.set("正在停止任务，请稍后关闭窗口。")
        else:
            self.root.destroy()

    def work(self, source, destination, output_name=None):
        partial = None
        process = None
        log_path = None
        try:
            destination.mkdir(parents=True, exist_ok=True)
            log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VideoMerge" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            fd, log_name = tempfile.mkstemp(prefix=time.strftime("merge-%Y%m%d-%H%M%S-"), suffix=".log", dir=log_dir)
            os.close(fd)
            log_path = Path(log_name)
            self.events.put(("log", log_path))
            ffmpeg = find_ffmpeg(None)
            duration = sum(float(n) for n in re.findall(r"#EXTINF:([\d.]+)", source.read_text(encoding="utf-8-sig")))
            with tempfile.TemporaryDirectory(prefix=".hls_merge_", dir=source.parent) as temp:
                playlist = Path(temp) / "local.m3u8"
                count = rewrite_playlist(source, playlist)
                if self.cancel.is_set():
                    self.events.put(("cancelled", None))
                    return
                name = output_name or source.parent.name + "_完整视频"
                output = destination / (name + ".mp4")
                index = 2
                while output.exists():
                    output = destination / f"{name}_{index}.mp4"
                    index += 1
                fd, partial_name = tempfile.mkstemp(prefix=".video-", suffix=".partial.mp4", dir=destination)
                os.close(fd)
                partial = Path(partial_name)
                command = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-nostats",
                           "-loglevel", "warning", "-progress", "pipe:1",
                           "-protocol_whitelist", "file,crypto,data", "-allowed_extensions", "ALL",
                           "-i", str(playlist), "-map", "0:v?", "-map", "0:a?", "-c", "copy",
                           "-movflags", "+faststart", str(partial)]
                self.events.put(("status", f"已识别 {count} 个分片，正在解密合并…"))
                with log_path.open("w", encoding="utf-8") as log:
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log,
                                               text=True, encoding="utf-8", errors="replace",
                                               creationflags=subprocess.CREATE_NO_WINDOW)
                    finished = threading.Event()
                    def cancel_watcher():
                        while not finished.wait(0.15):
                            if self.cancel.is_set():
                                try:
                                    process.terminate()
                                except OSError:
                                    pass
                                return
                    threading.Thread(target=cancel_watcher, daemon=True).start()
                    try:
                        for line in process.stdout:
                            key, _, value = line.strip().partition("=")
                            if key == "out_time_us" and duration:
                                try:
                                    percent = max(0, min(99, float(value) / 1_000_000 / duration * 100))
                                    self.events.put(("progress", percent))
                                except ValueError:
                                    pass
                        code = process.wait()
                    finally:
                        finished.set()
                        process.stdout.close()
                if self.cancel.is_set():
                    partial.unlink(missing_ok=True)
                    self.events.put(("cancelled", None))
                    return
                if code != 0 or not partial.stat().st_size:
                    raise RuntimeError("合并未能完成。请查看日志了解具体原因。")
                partial.rename(output)
                self.events.put(("done", output))
        except Exception as exc:
            if process and process.poll() is None:
                process.terminate()
                process.wait()
            if log_path:
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(f"\n{exc}\n")
            self.events.put(("error", str(exc)))

    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self.log = data
                    self.log_button.configure(state="normal")
                elif kind == "status":
                    if not self.cancel.is_set():
                        self.status.set(data)
                elif kind == "progress":
                    if not self.cancel.is_set():
                        self.progress["value"] = data
                        self.status.set(f"正在合并 · {data:.0f}%" if data < 99 else "正在整理 MP4 文件，请稍候…")
                elif kind == "imported":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                elif kind in ("done", "error", "cancelled", "scanned"):
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.running = False
                    for widget in self.inputs + [self.start_button]:
                        widget.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    if kind == "scanned":
                        if self.cancel.is_set():
                            self.status.set("已取消。")
                        else:
                            self.status.set(f"找到 {len(data)} 个视频，请选择导入。")
                            self.choose_video(data)
                    elif kind == "done":
                        self.result = data
                        self.progress["value"] = 100
                        self.status.set(f"已完成：{data.name}")
                        messagebox.showinfo("合并完成", f"视频已保存到：\n{data}")
                    elif kind == "cancelled":
                        self.status.set("已取消，原文件保持不变。")
                    else:
                        self.status.set("未能完成，请查看提示或日志。")
                        messagebox.showerror("未能完成", data)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


if __name__ == "__main__":
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    root.withdraw()
    App(root)
    root.deiconify()
    root.mainloop()
