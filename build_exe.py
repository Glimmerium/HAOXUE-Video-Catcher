"""Build a self-contained Windows executable using installed dependencies."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import imageio_ffmpeg


def main():
    if sys.platform != "win32":
        raise SystemExit("Please build the Windows executable on Windows.")
    root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="videomerge-build-") as temporary:
        ffmpeg = Path(temporary) / "ffmpeg.exe"
        shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), ffmpeg)
        subprocess.run([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile",
            "--windowed", "--name", "VideoMerge",
            "--add-data", f"{root / 'personal_logo.png'}{os.pathsep}.",
            "--add-binary", f"{ffmpeg}{os.pathsep}.",
            str(root / "video_merge_gui.py"),
        ], cwd=root, check=True)
    print(root / "dist" / "VideoMerge.exe")


if __name__ == "__main__":
    main()
