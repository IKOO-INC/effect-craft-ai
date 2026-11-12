"""Utilitas media untuk UI: poster frame, buka folder, putar dengan pemutar bawaan.

Tk tidak punya dekoder video. Poster diambil sekali dengan FFmpeg (kalau ada) lalu ditampilkan
sebagai gambar; pemutaran penuh memakai pemutar bawaan sistem supaya .exe tetap ringan.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0


def ffmpeg_path() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def extract_poster(mp4: Path, out_png: Path, *, at: float = 0.8) -> Path | None:
    """Ambil satu frame sebagai PNG. Kembalikan None bila FFmpeg tidak ada / gagal."""
    exe = ffmpeg_path()
    if not exe or not Path(mp4).exists():
        return None
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        exe,
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, at):.2f}",
        "-i",
        str(mp4),
        "-frames:v",
        "1",
        str(out_png),
    ]
    try:
        subprocess.run(argv, timeout=30, check=False, shell=False, creationflags=_NO_WINDOW,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return out_png if out_png.exists() and out_png.stat().st_size > 0 else None


def open_path(path: Path) -> None:
    """Buka file/folder dengan aplikasi bawaan."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_folder(path: Path) -> None:
    folder = Path(path)
    if folder.is_file():
        folder = folder.parent
    open_path(folder)


def human_size(path: Path) -> str:
    try:
        size = Path(path).stat().st_size
    except OSError:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
