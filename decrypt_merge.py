"""Decrypt downloaded AES-128 HLS and remux to MP4 without re-encoding.

Usage: python decrypt_merge.py
       python decrypt_merge.py --playlist video.m3u8 --output video.mp4
Requires FFmpeg on PATH, --ffmpeg PATH, or: pip install imageio-ffmpeg
Original files are never modified. Python 3.9+.
"""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit


def find_ffmpeg(explicit):
    if explicit:
        return explicit
    bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "ffmpeg.exe"
    if bundled.is_file():
        return str(bundled)
    packaged = bundled.with_name("ffmpeg-win-x86_64-v7.1.exe")
    if packaged.is_file():
        return str(packaged)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError(
            "找不到 FFmpeg。请运行 python -m pip install imageio-ffmpeg，"
            "或使用 --ffmpeg 指定 ffmpeg.exe。"
        ) from exc


def local_file(uri, root):
    # Android downloads sometimes lose the leading dot on the segment folder.
    path = unquote(urlsplit(uri.replace("\\", "/")).path)
    parts = path.rstrip("/").split("/")
    name = parts[-1]
    candidates = [root / name]
    if len(parts) > 1:
        parent = parts[-2]
        candidates.extend([root / parent / name, root / parent.lstrip(".") / name])
    if not path.startswith("/") and ":" not in path:
        candidates.insert(0, root / path)
    for candidate in candidates:
        resolved = candidate.resolve()
        # Only use files in this download directory, never remote URLs.
        if root != resolved and root not in resolved.parents:
            continue
        if resolved.is_file():
            return resolved
    raise FileNotFoundError(f"找不到清单引用的本地文件：{uri}")


def rewrite_playlist(source, target):
    root = source.parent.resolve()
    lines = source.read_text(encoding="utf-8-sig").splitlines()
    if not lines or lines[0].strip() != "#EXTM3U":
        raise ValueError("输入文件不是有效的 M3U8 清单。")
    if any(line.startswith("#EXT-X-STREAM-INF") for line in lines):
        raise ValueError("请选择包含视频分片的媒体清单，而不是多码率主清单。")

    def replacement(uri, is_key=False):
        local = local_file(uri, root)
        if is_key and local.stat().st_size != 16:
            raise ValueError(f"AES-128 密钥必须为 16 字节：{local.name}")
        return Path(os.path.relpath(local, target.parent)).as_posix()

    rewritten = []
    count = 0
    for line in lines:
        line = line.strip()
        if line.startswith("#EXT-X-KEY:"):
            method = re.search(r"(?:^|,)METHOD=([^,]+)", line.split(":", 1)[1])
            if not method or method.group(1) not in ("NONE", "AES-128"):
                raise ValueError("脚本只支持 AES-128 或未加密的 HLS 分片。")
        if line.startswith("#"):
            # Preserve IV, media sequence, durations, and discontinuity markers.
            is_key = line.startswith("#EXT-X-KEY:") and "METHOD=AES-128" in line
            line = re.sub(r'URI="([^"]+)"',
                          lambda m: 'URI="' + replacement(m.group(1), is_key) + '"',
                          line)
        elif line:
            line = replacement(line)
            count += 1
        rewritten.append(line)
    if not count:
        raise ValueError("清单内没有视频分片。")
    if "#EXT-X-ENDLIST" not in rewritten:
        rewritten.append("#EXT-X-ENDLIST")
    target.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    return count


def main():
    parser = argparse.ArgumentParser(description="解密本地 HLS 分片并无损合并为 MP4")
    parser.add_argument("--playlist", type=Path, help="M3U8 文件，默认自动查找脚本所在目录")
    parser.add_argument("--output", type=Path, help="输出 MP4 文件，默认 完整视频.mp4")
    parser.add_argument("--ffmpeg", help="ffmpeg.exe 的路径")
    parser.add_argument("--strict", action="store_true",
                        help="严格模式：遇到损坏包等错误立即停止，默认尝试继续处理")
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    if args.playlist:
        source = args.playlist.resolve()
    else:
        playlists = sorted(base.glob("*.m3u8"))
        if len(playlists) != 1:
            raise ValueError("目录内没有唯一的 M3U8 文件，请使用 --playlist 指定。")
        source = playlists[0]
    output = (args.output or source.parent / "完整视频.mp4").resolve()
    if output.suffix.lower() != ".mp4":
        raise ValueError("输出文件名必须以 .mp4 结尾。")
    if output.exists():
        raise FileExistsError(f"输出已存在，请使用 --output 选择其他名称：{output}")
    ffmpeg = find_ffmpeg(args.ffmpeg)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep temporary playlist on the same drive as the downloaded files.
    with tempfile.TemporaryDirectory(prefix=".hls_merge_", dir=source.parent) as temp:
        playlist = Path(temp) / "local.m3u8"
        count = rewrite_playlist(source, playlist)
        print(f"共 {count} 个分片，开始解密合并；不重新编码。", flush=True)
        # A partial file is retained on failure; never presented as a finished MP4.
        fd, partial_name = tempfile.mkstemp(prefix=output.stem + ".partial-",
                                            suffix=".mp4", dir=output.parent)
        os.close(fd)
        partial = Path(partial_name)
        # Let the demuxer recover from packet warnings at segment boundaries.
        # Do not discard flagged packets: they may still contain usable frames.
        command = [ffmpeg, "-hide_banner", "-nostdin", "-y"]
        if args.strict:
            command.append("-xerror")
        command += [
                   "-protocol_whitelist", "file,crypto,data",
                   "-allowed_extensions", "ALL", "-i", str(playlist),
                   "-map", "0:v?", "-map", "0:a?", "-c", "copy",
                   "-movflags", "+faststart", str(partial)]
        try:
            log_path = partial.with_suffix(".log")
            with log_path.open("w", encoding="utf-8") as log:
                result = subprocess.run(command, stdout=log, stderr=log)
            if result.returncode:
                raise RuntimeError(f"合并失败，详细原因请查看日志：{log_path}")
            if not partial.stat().st_size:
                raise RuntimeError("FFmpeg 没有生成视频内容。")
            # On Windows rename fails if a destination appeared while processing.
            if output.exists():
                raise FileExistsError(f"输出文件已存在：{output}")
            partial.rename(output)
        except BaseException:
            print(f"未完成；中间文件保留在：{partial}", file=sys.stderr)
            raise
    print(f"完成：{output}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
