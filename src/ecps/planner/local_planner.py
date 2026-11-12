"""Planner lokal (tanpa LLM, tanpa internet).

Dipakai saat: API key belum diatur, tidak ada koneksi, LLM menolak, atau pengguna memilih
"tanpa LLM". Hasilnya deterministik dan selalu memenuhi skema, sehingga pipeline tetap jalan.
Kemampuannya sengaja terbatas pada pola motion graphic umum: judul, lower third, logo reveal,
countdown, dan intro YouTube.
"""

from __future__ import annotations

import re
from typing import Any

RESOLUTIONS: dict[str, tuple[int, int]] = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "vertical_1080x1920": (1080, 1920),
    "vertical_720x1280": (720, 1280),
    "square_1080": (1080, 1080),
}

#: Palet per gaya: (gradasi awal, gradasi akhir, warna teks, warna aksen).
PALETTES: dict[str, tuple[str, str, str, str]] = {
    "minimalis": ("#0e1116", "#1d2733", "#f8fafc", "#7dd3fc"),
    "neon": ("#05010f", "#2a0b53", "#f5f3ff", "#22d3ee"),
    "korporat": ("#0b2545", "#134074", "#ffffff", "#8ecae6"),
    "elegan": ("#1a1410", "#3b2f2a", "#f6e7cb", "#c9a227"),
    "retro": ("#2b1b17", "#7a4b2a", "#ffe8c2", "#ffb703"),
    "bold": ("#111111", "#2f2f2f", "#ffffff", "#ff4d29"),
    "podcast": ("#101418", "#22303c", "#f8fafc", "#34d399"),
    "gelap": ("#05070a", "#101826", "#e5e7eb", "#6366f1"),
}

COLOR_HINTS: dict[str, tuple[str, str]] = {
    "biru": ("#06122b", "#2f6bff"),
    "blue": ("#06122b", "#2f6bff"),
    "merah": ("#240407", "#c81e3a"),
    "red": ("#240407", "#c81e3a"),
    "hijau": ("#04170f", "#12a150"),
    "green": ("#04170f", "#12a150"),
    "ungu": ("#120626", "#7c3aed"),
    "purple": ("#120626", "#7c3aed"),
    "emas": ("#1b1405", "#c9a227"),
    "gold": ("#1b1405", "#c9a227"),
    "oranye": ("#1c0f04", "#f97316"),
    "orange": ("#1c0f04", "#f97316"),
    "magenta": ("#1a0416", "#d946ef"),
    "hitam": ("#000000", "#1f2937"),
    "black": ("#000000", "#1f2937"),
    "putih": ("#f8fafc", "#cbd5e1"),
    "white": ("#f8fafc", "#cbd5e1"),
}

_QUOTED = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{1,120})[\"'“”‘’]")
_DURATION = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:detik|dtk|sec(?:ond)?s?|s)\b", re.I)
_FPS = re.compile(r"(\d{1,2})\s*fps\b", re.I)
_AFTER_LABEL = re.compile(
    r"(?:teks|text|judul|title|tulisan|bertuliskan|berbunyi)\s*(?:itu\s*)?[:=]?\s*(.+)$",
    re.I | re.S,
)
_STYLE_WORDS = [
    ("neon", ("neon", "glow", "bercahaya")),
    ("korporat", ("korporat", "corporate", "bisnis", "business", "perusahaan")),
    ("elegan", ("elegan", "elegant", "mewah", "luxury", "klasik")),
    ("retro", ("retro", "vintage", "jadul")),
    ("bold", ("bold", "tegas", "tebal", "keras")),
    ("podcast", ("podcast", "siniar")),
    ("gelap", ("gelap", "dark", "malam")),
    ("minimalis", ("minimalis", "minimal", "bersih", "clean")),
]


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip(" .,;:-")
    return text[:120]


def extract_subject(prompt: str) -> str:
    """Teks yang akan ditampilkan: tanda kutip dulu, lalu setelah kata 'teks/judul'."""
    quoted = [m.group(1).strip() for m in _QUOTED.finditer(prompt) if m.group(1).strip()]
    if quoted:
        return _clean_text(quoted[0])
    m = _AFTER_LABEL.search(prompt)
    if m:
        raw = m.group(1)
        raw = re.split(r"\b(?:dengan|with|di|latar|background|berlatar|durasi|duration)\b", raw, maxsplit=1,
                       flags=re.I)[0]
        cleaned = _clean_text(raw)
        if cleaned:
            return cleaned
    # Buang instruksi umum supaya yang tersisa bisa dipakai sebagai judul pendek.
    stripped = re.sub(
        r"\b(intro|motion graphic|video|durasi|detik|fps|resolusi|vertikal|horizontal|dengan|yang|buat|buatkan|"
        r"tolong|fade[- ]?in|fade[- ]?out|muncul|latar|gradasi|background|style|gaya)\b",
        " ",
        prompt,
        flags=re.I,
    )
    words = [w for w in re.split(r"[\s,]+", stripped) if w]
    return _clean_text(" ".join(words[:6])) or "EffectCraft"


def detect_kind(prompt: str) -> str:
    p = prompt.lower()
    if any(k in p for k in ("lower third", "lower-third", "lowerthird", "nama dan jabatan", "name and title")):
        return "lower_third"
    if any(k in p for k in ("countdown", "hitung mundur", "angka mundur")):
        return "countdown"
    if any(k in p for k in ("logo reveal", "logo", "reaveal logo")):
        return "logo_reveal"
    if "youtube" in p and any(k in p for k in ("intro", "subscribe", "channel", "kanal")):
        return "youtube_intro"
    return "title"


def detect_style(prompt: str, fallback: str = "minimalis") -> str:
    p = prompt.lower()
    for style, words in _STYLE_WORDS:
        if any(w in p for w in words):
            return style
    return fallback if fallback in PALETTES else "minimalis"


def detect_duration(prompt: str, fallback: float = 5.0) -> float:
    m = _DURATION.search(prompt)
    if not m:
        return fallback
    try:
        value = float(m.group(1).replace(",", "."))
    except ValueError:
        return fallback
    return max(0.8, min(120.0, value))


def detect_fps(prompt: str, fallback: int = 30) -> int:
    m = _FPS.search(prompt)
    if not m:
        return fallback
    try:
        return max(1, min(60, int(m.group(1))))
    except ValueError:
        return fallback


def detect_resolution(prompt: str, fallback: str = "1080p") -> str:
    p = prompt.lower()
    if any(k in p for k in ("9:16", "vertikal", "vertical", "portrait", "tiktok", "reels", "shorts", "story")):
        return "vertical_720x1280" if "720" in p else "vertical_1080x1920"
    if any(k in p for k in ("1:1", "persegi", "square")):
        return "square_1080"
    if "720p" in p:
        return "720p"
    if "1080p" in p:
        return "1080p"
    return fallback if fallback in RESOLUTIONS else "1080p"


def detect_palette(prompt: str, style: str) -> tuple[str, str, str, str]:
    p = prompt.lower()
    for word, (start, end) in COLOR_HINTS.items():
        if word in p and ("gradasi" in p or "gradient" in p or "latar" in p or "background" in p or "warna" in p):
            text_color = "#0b1020" if word in ("putih", "white") else "#ffffff"
            return start, end, text_color, PALETTES.get(style, PALETTES["minimalis"])[3]
    return PALETTES.get(style, PALETTES["minimalis"])


def _gradient_bg(name: str, start: str, end: str) -> dict:
    return {
        "name": name,
        "type": "solid",
        "color": start,
        "effects": [
            {
                "effect": "Gradient Ramp",
                "params": {
                    "startColor": start,
                    "endColor": end,
                    "start": [0.5, 0.0],
                    "end": [0.5, 1.0],
                },
            }
        ],
    }


def _fade_keys(duration: float, *, delay: float = 0.0, rise: float = 0.0, y: float = 0.0,
               strong: bool = False) -> dict[str, list[dict]]:
    start = round(min(delay, max(0.0, duration - 0.4)), 3)
    end = round(min(duration - 0.05, start + (0.45 if strong else 0.8)), 3)
    keys: dict[str, list[dict]] = {
        "opacity": [
            {"time": start, "value": 0},
            {"time": end, "value": 100},
        ]
    }
    if rise:
        keys["position"] = [
            {"time": start, "value": [0, round(y + rise, 2)]},
            {"time": end, "value": [0, round(y, 2)]},
        ]
    return keys


def _title_plan(prompt: str, *, text: str, comp: dict, palette: tuple[str, str, str, str]) -> list[dict]:
    start, end, fg, accent = palette
    w, h = comp["width"], comp["height"]
    dur = comp["duration"]
    vertical = h > w
    size = int(min(w, h) * (0.13 if not vertical else 0.11))
    y = h * 0.5
    layers = [
        _gradient_bg("BG", start, end),
        {
            "name": "Accent Bar",
            "type": "shape",
            "shape": "rounded",
            "size": [w * (0.22 if not vertical else 0.3), max(6, h * 0.008)],
            "fill": accent,
            "position": [w / 2, y + size * 0.95],
            "animate": {
                "scale": [
                    {"time": 0.0, "value": [0, 100]},
                    {"time": 0.7, "value": [100, 100]},
                ],
                "opacity": [
                    {"time": 0.0, "value": 0},
                    {"time": 0.5, "value": 100},
                ],
            },
            "easing": "easyEase",
        },
        {
            "name": "Title",
            "type": "text",
            "text": text,
            "position": [w / 2, y],
            "fontSize": size,
            "fill": fg,
            "justify": "center",
            "animate": {
                **_fade_keys(dur, delay=0.12, rise=min(70, h * 0.07), y=y),
            },
            "easing": "easyEase",
        },
    ]
    # Ganti nilai Y pada key position: _fade_keys memakai 0 sebagai x, jadi perbaiki di sini.
    title = layers[-1]
    if "position" in title["animate"]:
        title["animate"]["position"] = [
            {"time": k["time"], "value": [w / 2, k["value"][1]]} for k in title["animate"]["position"]
        ]
    if len(text) > 24:
        subtitle = "Motion graphic dibuat dengan EffectCraft"
        layers.append(
            {
                "name": "Subtitle",
                "type": "text",
                "text": subtitle,
                "position": [w / 2, y + size * 0.95 + max(28, h * 0.045)],
                "fontSize": max(20, int(size * 0.28)),
                "fill": accent,
                "justify": "center",
                "animate": {
                    "opacity": [
                        {"time": min(dur - 0.2, 0.55), "value": 0},
                        {"time": min(dur - 0.05, 1.25), "value": 100},
                    ]
                },
                "easing": "easyEase",
            }
        )
    return layers


def _lower_third_plan(prompt: str, *, text: str, comp: dict, palette: tuple[str, str, str, str]) -> list[dict]:
    quotes = [m.group(1).strip() for m in _QUOTED.finditer(prompt) if m.group(1).strip()]
    role_text = quotes[1] if len(quotes) > 1 else "Jabatan"
    start, end, fg, accent = palette
    w, h = comp["width"], comp["height"]
    dur = comp["duration"]
    bar_x = w * 0.09
    bar_y = h * 0.72
    title_size = int(min(w, h) * 0.055)
    sub_size = int(title_size * 0.62)
    layers = [
        _gradient_bg("BG", start, end),
        {
            "name": "Lower Third Panel",
            "type": "solid",
            "color": "#0b1220",
            "width": int(w * 0.62),
            "height": int(h * 0.16),
            "position": [bar_x + w * 0.31, bar_y + h * 0.05],
            "animate": {
                "position": [
                    {"time": 0.2, "value": [bar_x + w * 0.31 - w * 0.12, bar_y + h * 0.05]},
                    {"time": 0.85, "value": [bar_x + w * 0.31, bar_y + h * 0.05]},
                ],
                "opacity": [{"time": 0.15, "value": 0}, {"time": 0.7, "value": 92}],
            },
            "easing": "easyEase",
        },
        {
            "name": "Accent Bar",
            "type": "shape",
            "shape": "rect",
            "size": [max(6, w * 0.012), int(h * 0.16)],
            "fill": accent,
            "position": [bar_x, bar_y + h * 0.05],
            "animate": {
                "scale": [{"time": 0.25, "value": [100, 0]}, {"time": 0.8, "value": [100, 100]}],
            },
            "easing": "easyEase",
        },
        {
            "name": "Name",
            "type": "text",
            "text": text,
            "position": [bar_x + w * 0.04, bar_y + h * 0.015],
            "fontSize": title_size,
            "fill": fg,
            "justify": "left",
            "animate": {
                "opacity": [{"time": 0.45, "value": 0}, {"time": 1.0, "value": 100}],
                "position": [
                    {"time": 0.45, "value": [bar_x + w * 0.04 - 40, bar_y + h * 0.015]},
                    {"time": 1.0, "value": [bar_x + w * 0.04, bar_y + h * 0.015]},
                ],
            },
            "easing": "easyEase",
        },
        {
            "name": "Role",
            "type": "text",
            "text": role_text,
            "position": [bar_x + w * 0.04, bar_y + h * 0.075],
            "fontSize": sub_size,
            "fill": accent,
            "justify": "left",
            "animate": {"opacity": [{"time": 0.7, "value": 0}, {"time": 1.2, "value": 100}]},
            "easing": "easyEase",
        },
    ]
    if dur > 4:
        layers[-2]["animate"]["opacity"].append({"time": round(dur - 0.6, 3), "value": 0})
        layers[-1]["animate"]["opacity"].append({"time": round(dur - 0.6, 3), "value": 0})
        layers[1]["animate"]["opacity"].append({"time": round(dur - 0.6, 3), "value": 0})
        layers[2]["animate"]["scale"].append({"time": round(dur - 0.6, 3), "value": [100, 0]})
    return layers


def _logo_plan(prompt: str, *, text: str, comp: dict, palette: tuple[str, str, str, str]) -> list[dict]:
    start, end, fg, accent = palette
    w, h = comp["width"], comp["height"]
    dur = comp["duration"]
    ring = min(w, h) * 0.26
    layers = [
        _gradient_bg("BG", start, end),
        {
            "name": "Logo Ring",
            "type": "shape",
            "shape": "ellipse",
            "size": [ring, ring],
            "fill": accent,
            "position": [w / 2, h * 0.42],
            "animate": {
                "scale": [{"time": 0.0, "value": [0, 0]}, {"time": 0.7, "value": [100, 100]}],
                "rotation": [{"time": 0.0, "value": -40}, {"time": 0.9, "value": 0}],
                "opacity": [{"time": 0.0, "value": 0}, {"time": 0.45, "value": 100}],
            },
            "easing": "easyEase",
        },
        {
            "name": "Logo Mark",
            "type": "shape",
            "shape": "rounded",
            "size": [ring * 0.55, ring * 0.55],
            "fill": start,
            "position": [w / 2, h * 0.42],
            "animate": {
                "scale": [{"time": 0.25, "value": [0, 0]}, {"time": 0.9, "value": [100, 100]}],
            },
            "easing": "easyEase",
        },
        {
            "name": "Brand",
            "type": "text",
            "text": text,
            "position": [w / 2, h * 0.66],
            "fontSize": int(min(w, h) * 0.075),
            "fill": fg,
            "justify": "center",
            "animate": {
                "opacity": [{"time": 0.8, "value": 0}, {"time": 1.35, "value": 100}],
                "position": [
                    {"time": 0.8, "value": [w / 2, h * 0.66 + h * 0.03]},
                    {"time": 1.35, "value": [w / 2, h * 0.66]},
                ],
            },
            "easing": "easyEase",
        },
    ]
    return layers


def _countdown_plan(prompt: str, *, text: str, comp: dict, palette: tuple[str, str, str, str]) -> list[dict]:
    start, end, fg, accent = palette
    w, h = comp["width"], comp["height"]
    dur = comp["duration"]
    m = re.search(r"(\d{1,2})\s*(?:detik|dtk|s\b)?", prompt)
    count = 3
    if m:
        try:
            count = max(2, min(5, int(m.group(1))))
        except ValueError:
            count = 3
    if dur / count < 0.6:
        count = max(2, int(dur / 0.6))
    # Caption pendek: teks kutipan bila ada, kalau tidak cukup label "Countdown".
    caption = text if _QUOTED.search(prompt) else "Countdown"
    if len(caption) > 28:
        caption = "Countdown"
    layers: list[dict] = [
        _gradient_bg("BG", start, end),
        {
            "name": "Caption",
            "type": "text",
            "text": caption,
            "position": [w / 2, h * 0.82],
            "fontSize": int(min(w, h) * 0.045),
            "fill": accent,
            "justify": "center",
            "animate": {"opacity": [{"time": 0.0, "value": 0}, {"time": 0.5, "value": 100}]},
            "easing": "easyEase",
        },
    ]
    step = dur / count
    for i in range(count):
        number = count - i
        t_in = round(i * step, 3)
        t_out = round(min(dur, (i + 1) * step), 3)
        size = int(min(w, h) * 0.34)
        layers.append(
            {
                "name": f"Count {number}",
                "type": "text",
                "text": str(number),
                "position": [w / 2, h * 0.45],
                "fontSize": size,
                "fill": fg,
                "justify": "center",
                "in": t_in,
                "out": round(max(t_in + 0.05, t_out - 0.02), 3),
                "animate": {
                    "scale": [
                        {"time": t_in, "value": [130, 130]},
                        {"time": round(min(t_out, t_in + step * 0.45), 3), "value": [100, 100]},
                    ],
                    "opacity": [
                        {"time": t_in, "value": 0},
                        {"time": round(min(t_out, t_in + step * 0.25), 3), "value": 100},
                    ],
                },
                "easing": "easyEase",
            }
        )
    return layers


def _youtube_plan(prompt: str, *, text: str, comp: dict, palette: tuple[str, str, str, str]) -> list[dict]:
    start, end, fg, accent = palette
    w, h = comp["width"], comp["height"]
    dur = comp["duration"]
    layers = [
        _gradient_bg("BG", start, end),
        {
            "name": "Band",
            "type": "shape",
            "shape": "rounded",
            "size": [w * 0.74, h * 0.22],
            "fill": "#ffffff",
            "position": [w / 2, h * 0.5],
            "animate": {
                "scale": [{"time": 0.0, "value": [0, 100]}, {"time": 0.65, "value": [100, 100]}],
                "opacity": [{"time": 0.0, "value": 0}, {"time": 0.3, "value": 18}],
            },
            "easing": "easyEase",
        },
        {
            "name": "Channel",
            "type": "text",
            "text": text,
            "position": [w / 2, h * 0.46],
            "fontSize": int(min(w, h) * 0.085),
            "fill": fg,
            "justify": "center",
            "animate": {
                "opacity": [{"time": 0.35, "value": 0}, {"time": 1.0, "value": 100}],
                "position": [
                    {"time": 0.35, "value": [w / 2, h * 0.46 + h * 0.05]},
                    {"time": 1.0, "value": [w / 2, h * 0.46]},
                ],
            },
            "easing": "easyEase",
        },
        {
            "name": "Tagline",
            "type": "text",
            "text": "Subscribe untuk video berikutnya",
            "position": [w / 2, h * 0.57],
            "fontSize": int(min(w, h) * 0.035),
            "fill": accent,
            "justify": "center",
            "animate": {"opacity": [{"time": 0.9, "value": 0}, {"time": 1.5, "value": 100}]},
            "easing": "easyEase",
        },
        {
            "name": "Subscribe Bar",
            "type": "shape",
            "shape": "rounded",
            "size": [w * 0.3, max(10, h * 0.018)],
            "fill": accent,
            "position": [w / 2, h * 0.64],
            "animate": {
                "scale": [{"time": 1.0, "value": [0, 100]}, {"time": 1.6, "value": [100, 100]}],
                "opacity": [{"time": 1.0, "value": 0}, {"time": 1.3, "value": 100}],
            },
            "easing": "easyEase",
        },
    ]
    return layers


def plan_from_prompt(prompt: str, options: dict | None = None) -> dict[str, Any]:
    """Buat rencana JSON dari prompt + opsi UI (durasi/resolusi/fps/gaya)."""
    options = options or {}
    style = detect_style(prompt, str(options.get("style") or "minimalis"))
    duration = float(options.get("duration") or detect_duration(prompt))
    fps = int(options.get("fps") or detect_fps(prompt))
    resolution = str(options.get("resolution") or detect_resolution(prompt))
    width, height = RESOLUTIONS.get(resolution, RESOLUTIONS["1080p"])
    text = extract_subject(prompt)
    palette = detect_palette(prompt, style)
    kind = detect_kind(prompt)

    comp = {
        "name": "Main",
        "width": width,
        "height": height,
        "fps": fps,
        "duration": round(duration, 3),
        "background": palette[0],
    }

    if kind == "lower_third":
        layers = _lower_third_plan(prompt, text=text, comp=comp, palette=palette)
    elif kind == "countdown":
        layers = _countdown_plan(prompt, text=text, comp=comp, palette=palette)
    elif kind == "logo_reveal":
        layers = _logo_plan(prompt, text=text, comp=comp, palette=palette)
    elif kind == "youtube_intro":
        layers = _youtube_plan(prompt, text=text, comp=comp, palette=palette)
    else:
        layers = _title_plan(prompt, text=text, comp=comp, palette=palette)

    return {
        "version": 1,
        "title": text[:60],
        "style": style,
        "comp": comp,
        "layers": layers,
    }
