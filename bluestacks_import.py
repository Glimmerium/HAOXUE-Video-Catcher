"""Read-only import of downloaded Haoxue HLS videos through local ADB."""
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time
import winreg
from urllib.parse import unquote, urlsplit

REMOTE = "/storage/emulated/0/Android/data/com.pku.studious/files/Video/Download"
SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")


class Cancelled(Exception):
    pass


def adb_path():
    candidates = []
    for product in ("BlueStacks_nxt_cn", "BlueStacks_nxt", "BlueStacks"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + product) as key:
                candidates.append(Path(winreg.QueryValueEx(key, "InstallDir")[0]) / "HD-Adb.exe")
        except OSError:
            pass
        candidates.append(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / product / "HD-Adb.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("未找到 BlueStacks 自带的连接工具，请先安装并启动 BlueStacks。")


def run(adb, args, cancel, timeout=30, progress=None):
    # Spool ADB output to disk: no terminal window, no pipe buffer deadlock.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen([adb, *args], stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if cancel.wait(0.15):
                    raise Cancelled()
                if time.monotonic() - started > timeout:
                    raise RuntimeError("连接或传输超时，请确认模拟器仍在运行后重试。")
                if progress:
                    progress()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
        output.seek(0)
        text = output.read().decode("utf-8", errors="replace")
    if cancel.is_set():
        raise Cancelled()
    if process.returncode:
        raise RuntimeError("无法读取模拟器文件。请确认 BlueStacks 已启动，并在设置→高级中开启 ADB。\n" + text[-600:])
    return text


def safe_name(name):
    if not SAFE.fullmatch(name) or name in (".", ".."):
        raise RuntimeError("下载文件名格式不受支持：" + name)
    return name


def listing(adb, serial, cancel):
    result = run(adb, ["-s", serial, "shell", "ls", "-a", REMOTE + "/"], cancel)
    return {line.strip() for line in result.splitlines() if line.strip() not in ("", ".", "..")}


def scan(cancel):
    adb = adb_path()
    devices = run(adb, ["devices"], cancel)
    serials = [line.split()[0] for line in devices.splitlines() if re.match(r"^\S+\s+device$", line.strip())]
    if not serials:
        raise RuntimeError("未连接到模拟器。请启动 BlueStacks，并在设置→高级中开启 Android 调试桥（ADB）。")
    videos, errors = [], []
    for serial in serials:
        try:
            names = listing(adb, serial, cancel)
            for name in sorted(names):
                if not name.endswith(".m3u8"):
                    continue
                safe_name(name)
                content = run(adb, ["-s", serial, "shell", "cat", REMOTE + "/" + name], cancel)
                if "#EXTM3U" not in content or "#EXT-X-STREAM-INF" in content:
                    continue
                duration = sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", content))
                count = sum(bool(x.strip()) and not x.startswith("#") for x in content.splitlines())
                videos.append(dict(adb=adb, serial=serial, name=name, content=content,
                                   duration=duration, count=count, complete="#EXT-X-ENDLIST" in content))
        except RuntimeError as exc:
            errors.append(str(exc))
    if not videos:
        raise RuntimeError(errors[0] if errors else "没有找到已下载视频。请先在好学 APP 中下载完成，再重新扫描。")
    return videos


def fetch(video, target, cancel, status):
    adb, serial, name = video["adb"], video["serial"], video["name"]
    names = listing(adb, serial, cancel)
    content = run(adb, ["-s", serial, "shell", "cat", REMOTE + "/" + name], cancel)
    if "#EXT-X-ENDLIST" not in content:
        raise RuntimeError("这个视频的清单尚未结束，请在好学 APP 中确认下载完成后重试。")
    resources = set()
    uris = re.findall(r'URI="([^"]+)"', content)
    uris += [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
    for uri in uris:
        path = PurePosixPath(unquote(urlsplit(uri).path))
        leaf = safe_name(path.name)
        parent = path.parent.name
        if leaf in names:
            resources.add(leaf)
        elif parent in names:
            resources.add(safe_name(parent))
        elif parent.lstrip(".") in names:
            resources.add(safe_name(parent.lstrip(".")))
        else:
            raise RuntimeError("下载文件不齐全，未找到：" + leaf)
    target.mkdir(parents=True, exist_ok=True)
    for index, resource in enumerate(sorted(resources), 1):
        status(f"正在从模拟器复制文件（{index}/{len(resources)}），请稍候…")
        run(adb, ["-s", serial, "pull", REMOTE + "/" + resource, str(target)], cancel,
            timeout=3600)
    after = run(adb, ["-s", serial, "shell", "cat", REMOTE + "/" + name], cancel)
    if after != content:
        raise RuntimeError("下载清单在传输期间发生变化，请等待下载结束后重试。")
    source = target / name
    source.write_text(content, encoding="utf-8")
    # Resolve every referenced segment and key before merging.
    from decrypt_merge import rewrite_playlist
    rewritten = target / "validation.m3u8"
    rewrite_playlist(source, rewritten)
    rewritten.unlink()
    return source
