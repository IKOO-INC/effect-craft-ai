"""Sanitasi semua nilai yang akan menjadi argumen command EffectCraft.

Aturan umum: tolak karakter kontrol (termasuk NUL dan baris baru) karena nilai-nilai ini bisa
berakhir di argumen proses; batasi panjang; dan untuk nama layer pakai charset sempit supaya
referensi `"layer": "<nama>"` tidak ambigu.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..errors import TranslationError

#: Charset nama layer. EffectCraft mengizinkan hampir semua karakter, tapi kita batasi supaya
#: nama aman dipakai sebagai nilai JSON dan sebagai nama file log.
_LAYER_ALLOWED = re.compile(r"[^A-Za-z0-9 _.\-()]+")
_FILENAME_ALLOWED = re.compile(r"[^A-Za-z0-9._-]+")
_HEX_COLOR = re.compile(r"^#?([0-9a-fA-F]{6})$")
#: Karakter yang tidak boleh muncul di argumen proses.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def check_no_control_chars(value: str, *, what: str = "nilai") -> str:
    if _CONTROL.search(value) or "\x00" in value:
        raise TranslationError(f"{what} mengandung karakter kontrol yang tidak diizinkan")
    return value


def safe_text(value: str, *, max_len: int = 500, what: str = "teks") -> str:
    """Teks yang boleh berisi baris baru (untuk isi layer teks) tetapi bukan karakter kontrol."""
    if not isinstance(value, str):
        raise TranslationError(f"{what} harus berupa string")
    if "\r" in value:
        value = value.replace("\r\n", "\n").replace("\r", "\n")
    if _CONTROL.search(value):
        raise TranslationError(f"{what} mengandung karakter kontrol yang tidak diizinkan")
    value = value.strip()
    if not value:
        raise TranslationError(f"{what} kosong")
    if len(value) > max_len:
        raise TranslationError(f"{what} terlalu panjang ({len(value)} > {max_len} karakter)")
    return value


def safe_layer_name(value: str, *, fallback: str = "Layer", max_len: int = 60) -> str:
    name = _LAYER_ALLOWED.sub(" ", str(value or "")).strip()
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = fallback
    return name[:max_len]


def safe_identifier(value: str, *, fallback: str = "video", max_len: int = 60) -> str:
    return safe_layer_name(value, fallback=fallback, max_len=max_len).replace(" ", "_")


def safe_filename(value: str, *, fallback: str = "project", max_len: int = 80) -> str:
    name = _FILENAME_ALLOWED.sub("-", str(value or "")).strip("-._")
    if not name:
        name = fallback
    return name[:max_len]


def safe_color(value: str, *, what: str = "warna") -> str:
    """Normalisasi `#rrggbb` (atau `rrggbb`) menjadi `#rrggbb` huruf kecil."""
    if not isinstance(value, str):
        raise TranslationError(f"{what} harus berupa string hex seperti '#1e3a8a'")
    m = _HEX_COLOR.match(value.strip())
    if not m:
        raise TranslationError(f"{what} bukan warna hex 6 digit: {value!r}")
    return "#" + m.group(1).lower()


def clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def ensure_within(base: Path, candidate: Path) -> Path:
    """Pastikan `candidate` berada di dalam `base` (mencegah path traversal saat menyimpan)."""
    base_r = Path(base).resolve()
    cand = Path(candidate).resolve()
    if base_r != cand and base_r not in cand.parents:
        raise ValueError(f"path di luar folder yang diizinkan: {candidate}")
    return cand
