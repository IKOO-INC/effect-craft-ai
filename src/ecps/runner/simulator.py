"""SIMULATOR — mesin pengganti untuk lingkungan tanpa EffectCraft.

Runner ini **bukan** EffectCraft. Ia mengonsumsi urutan command yang sama (hasil penerjemah),
menjalankannya pada model internal yang meniru subset semantik engine (comp/layer/effect/
keyframe/timing), lalu merender MP4 dengan Pillow + FFmpeg. Dipakai untuk:

* demo end-to-end di mesin tanpa EffectCraft (mis. sandbox Linux ini),
* uji regresi pipeline (penerjemah → langkah → render) tanpa memasang EffectCraft,
* pratinjau cepat saat EffectCraft belum terpasang.

UI menampilkan label "SIMULATOR" dan setiap log dimulai dengan penanda yang sama. Untuk hasil
yang benar-benar berasal dari EffectCraft, jalankan `scripts/verify_with_effectcraft.py`.
"""

from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import RunnerError
from .base import EngineResult, EventFn, Preflight, RenderSettings, StepRecord, emit

try:  # Pillow hanya dibutuhkan mode simulator
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
except Exception:  # pragma: no cover - Pillow wajib untuk simulator
    Image = None  # type: ignore[assignment]


class SimError(Exception):
    """Kegagalan setara pesan engine EffectCraft."""


# --------------------------------------------------------------------------- model


@dataclass
class SimKey:
    time: float
    value: Any
    ease: bool = False
    hold: bool = False


@dataclass
class SimLayer:
    index: int
    name: str
    type: str
    text: str = ""
    font: str = "Inter"
    font_size: float = 72.0
    fill: str = "#ffffff"
    justify: str = "center"
    tracking: float = 0.0
    color: str = "#000000"
    shape: str = "rect"
    size: tuple[float, float] | None = None
    solid_size: tuple[float, float] | None = None
    position: tuple[float, float] = (0.0, 0.0)
    effects: list[dict] = field(default_factory=list)
    keys: dict[str, list[SimKey]] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)
    in_time: float = 0.0
    out_time: float | None = None
    base_surface: Any = None  # cache PIL


@dataclass
class SimComp:
    name: str = "Main"
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    duration: float = 5.0
    background: str = "#000000"


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _rgba(c: str, alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = _hex(c)
    return r, g, b, alpha


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def _lerp_value(a: Any, b: Any, t: float) -> Any:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _lerp(float(a), float(b), t)
    av = a if isinstance(a, (list, tuple)) else [a]
    bv = b if isinstance(b, (list, tuple)) else [b]
    n = max(len(av), len(bv))
    out = []
    for i in range(n):
        x = float(av[i] if i < len(av) else av[-1])
        y = float(bv[i] if i < len(bv) else bv[-1])
        out.append(_lerp(x, y, t))
    return out


DEFAULT_VALUES = {
    "position": None,  # diisi saat layer dibuat (tengah komposisi)
    "scale": [100.0, 100.0],
    "rotation": 0.0,
    "opacity": 100.0,
}


class SimProject:
    def __init__(self) -> None:
        self.comp = SimComp()
        self.layers: list[SimLayer] = []
        self.selection: list[tuple[int, str, float]] = []
        self.next_layer = 1

    # ------------------------------------------------------------- helper
    def find_layer(self, ref: Any) -> SimLayer:
        if isinstance(ref, bool):
            raise SimError(f"no layer {ref}")
        if isinstance(ref, (int, float)):
            for l in self.layers:
                if l.index == int(ref):
                    return l
            raise SimError(f"no layer {ref}")
        if isinstance(ref, str):
            s = ref.strip()
            if s.startswith("#"):
                try:
                    idx = int(s[1:])
                except ValueError as e:
                    raise SimError(f"no layer {ref}") from e
                for l in self.layers:
                    if l.index == idx:
                        return l
                raise SimError(f"no layer {ref}")
            for l in self.layers:
                if l.name == s:
                    return l
            raise SimError(f"no layer {ref}")
        raise SimError(f"no layer {ref}")

    def value_at(self, layer: SimLayer, prop: str, t: float) -> Any:
        keys = layer.keys.get(prop) or []
        if not keys:
            v = layer.values.get(prop, DEFAULT_VALUES.get(prop))
            if prop == "position" and v is None:
                return [self.comp.width / 2, self.comp.height / 2]
            return v
        if t <= keys[0].time:
            return keys[0].value
        if t >= keys[-1].time:
            return keys[-1].value
        for i in range(len(keys) - 1):
            a, b = keys[i], keys[i + 1]
            if a.time <= t <= b.time:
                span = b.time - a.time
                u = 0.0 if span <= 0 else (t - a.time) / span
                if a.hold:
                    return a.value
                if a.ease or b.ease:
                    u = _ease(u)
                return _lerp_value(a.value, b.value, u)
        return keys[-1].value


# --------------------------------------------------------------------------- steps


def _set_prop(project: SimProject, layer: SimLayer, path: str, value: Any, *, key_time: float | None) -> Any:
    if path.startswith("effects/"):
        parts = path.split("/")
        if len(parts) < 3 or not parts[1].startswith("#"):
            raise SimError(f"no such property on layer {layer.name}: {path}")
        try:
            idx = int(parts[1][1:]) - 1
        except ValueError as e:
            raise SimError(f"no such property on layer {layer.name}: {path}") from e
        if not 0 <= idx < len(layer.effects):
            raise SimError(f"no such property on layer {layer.name}: {path}")
        param = "/".join(parts[2:])
        layer.effects[idx]["params"][param] = value
        return value
    prop = path.split("/", 1)[1] if path.startswith("transform/") else path
    if prop not in ("position", "scale", "rotation", "opacity", "anchor"):
        raise SimError(f"no such property on layer {layer.name}: {path}")
    if key_time is None:
        layer.values[prop] = value
    else:
        keys = layer.keys.setdefault(prop, [])
        keys.append(SimKey(time=key_time, value=value))
        keys.sort(key=lambda k: k.time)
    return value


def apply_step(project: SimProject, command: str, params: dict) -> Any:
    p = params or {}
    if command == "comp.new":
        comp = SimComp(
            name=str(p.get("name") or "Main"),
            width=int(p.get("width") or 1920),
            height=int(p.get("height") or 1080),
            fps=float(p.get("frameRate") or 30),
            duration=float(p.get("duration") or 5),
            background=str(p.get("background") or "#000000"),
        )
        if comp.width < 16 or comp.height < 16:
            raise SimError("comp.new: width/height tidak valid")
        project.comp = comp
        return {"comp": 1}

    if command in ("layer.newText", "layer.newSolid", "layer.newShape"):
        comp = project.comp
        pos = p.get("position")
        if pos is not None and (not isinstance(pos, list) or len(pos) != 2):
            raise SimError(f"{command}: position harus [x, y]")
        position = (float(pos[0]), float(pos[1])) if pos else (comp.width / 2, comp.height / 2)
        name = str(p.get("name") or "")
        idx = project.next_layer
        project.next_layer += 1
        if command == "layer.newText":
            text = str(p.get("text") or "Text")
            layer = SimLayer(
                index=idx,
                name=name or text[:40] or "Text",
                type="text",
                text=text,
                font=str(p.get("font") or "Inter"),
                font_size=float(p.get("size") or 72),
                fill=str(p.get("fill") or "#ffffff"),
                justify=str(p.get("justify") or "center"),
                tracking=float(p.get("tracking") or 0),
                position=position,
            )
        elif command == "layer.newSolid":
            layer = SimLayer(
                index=idx,
                name=name or f"Solid {idx}",
                type="solid",
                color=str(p.get("color") or "#000000"),
                solid_size=(float(p.get("width") or comp.width), float(p.get("height") or comp.height)),
                position=position,
            )
        else:
            size = p.get("size") or [300, 300]
            layer = SimLayer(
                index=idx,
                name=name or f"Shape Layer {idx}",
                type="shape",
                shape=str(p.get("kind") or "rect"),
                size=(float(size[0]), float(size[1])),
                fill=str(p.get("fill") or "#ffffff"),
                position=position,
            )
        layer.values["position"] = [position[0], position[1]]
        project.layers.append(layer)
        return {"layer": idx}

    if command == "effect.apply":
        layer = project.find_layer(p.get("layer", p.get("layers")))
        eff = str(p.get("effect") or "")
        from ..translator.whitelist import EFFECTS, resolve_effect

        try:
            canonical = resolve_effect(eff)
        except Exception as e:  # noqa: BLE001
            raise SimError(f"unknown effect `{eff}`") from e
        if canonical not in EFFECTS:  # pragma: no cover - resolve_effect menjamin ini
            raise SimError(f"unknown effect `{eff}`")
        layer.effects.append({"name": canonical, "params": {}})
        layer.base_surface = None
        n = len(layer.effects)
        return {"effects": [n], "paths": [f"effects/#{n}"], "effect": EFFECTS[canonical]["id"]}

    if command in ("prop.set", "prop.addKey"):
        layer = project.find_layer(p.get("layer"))
        path = str(p.get("path") or p.get("prop") or "")
        if command == "prop.set" and "value" not in p:
            raise SimError("prop.set: missing `value`")
        # Layer start_time tetap 0 (trim in/out tidak menggesernya), jadi waktu layer == waktu
        # komposisi; `timeBase` hanya memilih basis masukan, hasilnya sama di sini.
        key_time = float(p["time"]) if "time" in p else None
        value = p.get("value")
        result = _set_prop(project, layer, path, value, key_time=key_time)
        layer.base_surface = None if path.startswith("effects/") else layer.base_surface
        if command == "prop.addKey":
            return len(layer.keys.get(path.split("/", 1)[-1], []))
        return result

    if command == "keys.select":
        sel = []
        for entry in p.get("keys") or []:
            layer = project.find_layer(entry.get("layer"))
            path = str(entry.get("path") or "")
            prop = path.split("/", 1)[-1]
            sel.append((layer.index, prop, float(entry.get("time") or 0)))
        project.selection = sel
        return {"count": len(sel)}

    if command in ("keys.easyEase", "keys.easyEaseIn", "keys.easyEaseOut", "keys.interpolation"):
        hold = command == "keys.interpolation" and str(p.get("interpolation", "")).lower() == "hold"
        n = 0
        for idx, prop, t in project.selection:
            layer = next((l for l in project.layers if l.index == idx), None)
            if layer is None:
                continue
            for key in layer.keys.get(prop, []):
                if abs(key.time - t) < 1e-3:
                    key.ease = not hold
                    key.hold = hold
                    n += 1
        if n == 0:
            raise SimError("no keyframes selected")
        layer.base_surface = None
        return {"count": n}

    if command == "layer.timing":
        layers = p.get("layers") or ([p["layer"]] if "layer" in p else [])
        targets = [project.find_layer(ref) for ref in layers]
        for layer in targets:
            if "in" in p:
                layer.in_time = float(p["in"])
            if "out" in p:
                layer.out_time = float(p["out"])
            if "start" in p:
                layer.in_time = max(layer.in_time, float(p["start"]))
        return {"layers": [l.index for l in targets]}

    if command == "file.save":
        return {"path": p.get("path")}

    raise SimError(f"unknown command `{command}`")


# --------------------------------------------------------------------------- gambar


def _find_font(name: str) -> str | None:
    candidates = []
    lowered = (name or "").lower()
    if "inter" in lowered:
        candidates += ["Inter-Regular.ttf", "Inter_18pt-Regular.ttf", "Inter.ttf"]
    candidates += [
        "arial.ttf",
        "Arial.ttf",
        "segoeui.ttf",
        "SegoeUIVariable.ttf",
        "DejaVuSans.ttf",
        "LiberationSans-Regular.ttf",
        "Roboto-Regular.ttf",
    ]
    dirs = [
        Path("C:/Windows/Fonts"),
        Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".fonts",
        Path.home() / ".local/share/fonts",
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
    ]
    for d in dirs:
        if not d.exists():
            continue
        for c in candidates:
            p = d / c
            if p.exists():
                return str(p)
        for p in d.rglob(candidates[0] if candidates else "*.ttf"):
            return str(p)
    return None


def _font(size: int, name: str = "Inter"):
    path = _find_font(name)
    if path:
        try:
            return ImageFont.truetype(path, size=max(4, int(size)))
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=max(4, int(size)))
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _gradient_surface(start: tuple[float, float], end: tuple[float, float], c0: str, c1: str,
                      size: tuple[int, int], radial: bool = False):
    """Gradient pada resolusi 1/4 lalu diperbesar — cukup halus, jauh lebih cepat."""
    w, h = size
    sw, sh = max(2, w // 4), max(2, h // 4)
    a, b = _hex(c0), _hex(c1)
    img = Image.new("RGB", (sw, sh))
    px = img.load()
    sx, sy = start[0] * sw, start[1] * sh
    ex, ey = end[0] * sw, end[1] * sh
    dx, dy = ex - sx, ey - sy
    len2 = max(1e-6, dx * dx + dy * dy)
    for y in range(sh):
        for x in range(sw):
            if radial:
                t = math.sqrt(((x - sx) ** 2 + (y - sy) ** 2) / len2)
            else:
                t = ((x - sx) * dx + (y - sy) * dy) / len2
            t = 0.0 if t < 0 else 1.0 if t > 1 else t
            px[x, y] = (
                int(a[0] + (b[0] - a[0]) * t),
                int(a[1] + (b[1] - a[1]) * t),
                int(a[2] + (b[2] - a[2]) * t),
            )
    return img.resize((w, h), Image.BILINEAR).convert("RGBA")


def _four_color_surface(params: dict, size: tuple[int, int]):
    w, h = size
    sw, sh = max(2, w // 4), max(2, h // 4)
    pts = []
    for i in range(1, 5):
        pt = params.get(f"positionsColors/point{i}") or [0.0, 0.0]
        pts.append((float(pt[0]), float(pt[1]), _hex(str(params.get(f"positionsColors/color{i}") or "#000000"))))
    img = Image.new("RGB", (sw, sh))
    px = img.load()
    for y in range(sh):
        for x in range(sw):
            num = [0.0, 0.0, 0.0]
            den = 0.0
            for (ppx, ppy, c) in pts:
                d = math.hypot(x - ppx * sw, y - ppy * sh)
                wgt = 1.0 / (d * d + 1.0)
                num[0] += c[0] * wgt
                num[1] += c[1] * wgt
                num[2] += c[2] * wgt
                den += wgt
            px[x, y] = (int(num[0] / den), int(num[1] / den), int(num[2] / den))
    return img.resize((w, h), Image.BILINEAR).convert("RGBA")


def _apply_effect(img, effect: dict, size: tuple[int, int]):
    name = effect["name"]
    p = effect.get("params", {})
    w, h = img.size
    if name == "Gradient Ramp":
        start = p.get("start") or [0.0, 0.0]
        end = p.get("end") or [0.0, float(h)]
        radial = int(p.get("shape") or 0) == 1
        grad = _gradient_surface(
            (float(start[0]) / max(1, size[0]), float(start[1]) / max(1, size[1])),
            (float(end[0]) / max(1, size[0]), float(end[1]) / max(1, size[1])),
            str(p.get("startColor") or "#000000"),
            str(p.get("endColor") or "#ffffff"),
            (w, h),
            radial,
        )
        blend = float(p.get("blend") or 0) / 100.0
        grad.putalpha(img.getchannel("A"))
        if blend <= 0:
            return grad
        return Image.blend(img, grad, 1.0 - blend)
    if name == "4-Color Gradient":
        grad = _four_color_surface(p, (w, h))
        grad.putalpha(img.getchannel("A"))
        opacity = float(p.get("opacity") or 100) / 100.0
        if opacity < 1:
            grad.putalpha(grad.getchannel("A").point(lambda v: int(v * opacity)))
        return grad
    if name == "Fill":
        color = _rgba(str(p.get("color") or "#ff0000"))
        layer = Image.new("RGBA", (w, h), color)
        alpha = float(p.get("opacity") or 100) / 100.0
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
        return Image.alpha_composite(img, layer)
    if name == "Tint":
        black = _hex(str(p.get("black") or "#000000"))
        white = _hex(str(p.get("white") or "#ffffff"))
        amount = float(p.get("amount") or 100) / 100.0
        gray = img.convert("L")
        tinted = ImageOps.colorize(gray, black=black, white=white).convert("RGBA")
        tinted.putalpha(img.getchannel("A"))
        return Image.blend(img, tinted, amount)
    if name == "Brightness & Contrast":
        out = ImageEnhance.Brightness(img).enhance(1 + float(p.get("brightness") or 0) / 100.0)
        return ImageEnhance.Contrast(out).enhance(1 + float(p.get("contrast") or 0) / 100.0)
    if name == "Hue/Saturation":
        out = ImageEnhance.Color(img).enhance(max(0.0, 1 + float(p.get("saturation") or 0) / 100.0))
        return ImageEnhance.Brightness(out).enhance(max(0.0, 1 + float(p.get("lightness") or 0) / 100.0))
    if name == "Glow":
        radius = float(p.get("radius") or 10)
        intensity = float(p.get("intensity") or 1)
        blurred = img.filter(ImageFilter.GaussianBlur(max(0.1, radius / 2)))
        glow = ImageEnhance.Brightness(blurred).enhance(max(0.0, intensity))
        return Image.alpha_composite(img, Image.blend(Image.new("RGBA", (w, h), (0, 0, 0, 0)), glow, 0.85))
    if name == "Drop Shadow":
        dist = float(p.get("distance") or 5)
        ang = math.radians(float(p.get("direction") or 135))
        dx, dy = math.cos(ang) * dist, -math.sin(ang) * dist
        alpha = img.getchannel("A").point(lambda v: int(v * float(p.get("opacity") or 50) / 100))
        alpha = alpha.filter(ImageFilter.GaussianBlur(max(0.1, float(p.get("softness") or 0) / 2)))
        shadow = Image.new("RGBA", (w, h), _rgba(str(p.get("color") or "#000000"), 0))
        shadow.putalpha(alpha)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.alpha_composite(shadow, (int(dx), int(dy)))
        if p.get("shadowOnly"):
            return canvas
        canvas.alpha_composite(img)
        return canvas
    if name in ("Gaussian Blur", "Fast Box Blur"):
        r = float(p.get("blurriness") if name == "Gaussian Blur" else p.get("radius") or 0)
        if r <= 0:
            return img
        if name == "Gaussian Blur":
            return img.filter(ImageFilter.GaussianBlur(r / 2))
        return img.filter(ImageFilter.BoxBlur(min(50, max(0.1, r / 2))))
    if name == "Directional Blur":
        length = float(p.get("length") or 0)
        if length <= 0:
            return img
        ang = math.radians(float(p.get("direction") or 0))
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        steps = 8
        for i in range(steps):
            t = (i / (steps - 1) - 0.5) * length
            shifted = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            shifted.alpha_composite(img, (int(math.cos(ang) * t), int(math.sin(ang) * t)))
            out = Image.blend(out, shifted, 1.0 / (i + 1))
        return out
    if name == "Radial Blur":
        return img.filter(ImageFilter.GaussianBlur(max(0.1, float(p.get("amount") or 0) / 50)))
    if name in ("Sharpen",):
        return img.filter(ImageFilter.SHARPEN)
    if name == "Unsharp Mask":
        return img.filter(
            ImageFilter.UnsharpMask(
                radius=max(0.1, float(p.get("radius") or 2)),
                percent=int(float(p.get("amount") or 50)),
                threshold=int(float(p.get("threshold") or 0)),
            )
        )
    if name == "Linear Wipe":
        done = float(p.get("completion") or 0) / 100.0
        feather = float(p.get("feather") or 0)
        ang = math.radians(float(p.get("angle") or 0))
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        dx, dy = math.cos(ang), math.sin(ang)
        # proyeksi jarak tiap piksel pada arah wipe
        width_span = abs(dx) * w + abs(dy) * h
        limit = done * width_span
        step = 2
        for y in range(0, h, step):
            for x in range(0, w, step):
                d = (x - w / 2) * dx + (y - h / 2) * dy + width_span / 2
                if feather > 0:
                    v = 255 - int(255 * max(0.0, min(1.0, (d - limit + feather) / (2 * feather))))
                else:
                    v = 0 if d >= limit else 255
                draw.rectangle([x, y, x + step - 1, y + step - 1], fill=v)
        alpha = Image.composite(img.getchannel("A"), Image.new("L", (w, h), 0), mask)
        out = img.copy()
        out.putalpha(alpha)
        return out
    if name == "Radial Wipe":
        done = float(p.get("completion") or 0) / 100.0
        center = p.get("center") or [w / 2, h / 2]
        cx, cy = float(center[0]), float(center[1])
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        start = -float(p.get("startAngle") or 0)
        draw.pieslice([cx - max(w, h) * 2, cy - max(w, h) * 2, cx + max(w, h) * 2, cy + max(w, h) * 2],
                      start=start, end=start + 360 * done, fill=255)
        alpha = Image.composite(img.getchannel("A"), Image.new("L", (w, h), 0), mask)
        out = img.copy()
        out.putalpha(alpha)
        return out
    if name == "Venetian Blinds":
        done = float(p.get("completion") or 0) / 100.0
        width = max(1.0, float(p.get("width") or 30))
        ang = float(p.get("direction") or 90)
        period = width * 2
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        band = max(1.0, done * period)
        for i in range(int((w + h) / period) + 2):
            off = i * period
            if abs(ang - 90) < 45:
                draw.rectangle([off, 0, off + band, h], fill=255)
            else:
                draw.rectangle([0, off, w, off + band], fill=255)
        alpha = Image.composite(img.getchannel("A"), Image.new("L", (w, h), 0), mask)
        out = img.copy()
        out.putalpha(alpha)
        return out
    if name == "Invert":
        rgb = ImageOps.invert(img.convert("RGB"))
        out = rgb.convert("RGBA")
        out.putalpha(img.getchannel("A"))
        return out
    if name == "Mosaic":
        hb = max(1, int(float(p.get("horizontal") or 10)))
        vb = max(1, int(float(p.get("vertical") or 10)))
        small = img.resize((max(1, w // hb), max(1, h // vb)), Image.BILINEAR)
        return small.resize((w, h), Image.NEAREST if p.get("sharpColors") else Image.BILINEAR)
    if name == "Posterize":
        level = max(2, int(float(p.get("level") or 6)))
        out = ImageOps.posterize(img.convert("RGB"), max(1, min(8, int(math.log2(level))))).convert("RGBA")
        out.putalpha(img.getchannel("A"))
        return out
    if name == "Threshold":
        level = int(float(p.get("level") or 128))
        gray = img.convert("L").point(lambda v: 255 if v >= level else 0)
        out = Image.merge("RGBA", (gray, gray, gray, img.getchannel("A")))
        return out
    if name == "Emboss":
        return img.filter(ImageFilter.EMBOSS)
    if name == "Find Edges":
        return img.filter(ImageFilter.FIND_EDGES)
    if name == "Grid":
        color = _rgba(str(p.get("color") or "#ffffff"))
        draw = ImageDraw.Draw(img)
        step_x = max(2, int(float(p.get("width") or 64)))
        step_y = max(2, int(float(p.get("height") or 64)))
        border = int(float(p.get("border") or 2))
        for x in range(0, w, step_x):
            draw.rectangle([x, 0, x + border, h], fill=color)
        for y in range(0, h, step_y):
            draw.rectangle([0, y, w, y + border], fill=color)
        return img
    if name == "Checkerboard":
        color = _rgba(str(p.get("color") or "#ffffff"))
        cw = max(2, int(float(p.get("width") or 64)))
        ch = max(2, int(float(p.get("height") or 64)))
        draw = ImageDraw.Draw(img)
        for y in range(0, h, ch):
            for x in range(0, w, cw):
                if ((x // cw) + (y // ch)) % 2 == 0:
                    draw.rectangle([x, y, x + cw - 1, y + ch - 1], fill=color)
        return img
    if name == "Circle":
        color = _rgba(str(p.get("color") or "#ffffff"))
        center = p.get("center") or [w / 2, h / 2]
        radius = float(p.get("radius") or 100)
        draw = ImageDraw.Draw(img)
        cx, cy = float(center[0]), float(center[1])
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)
        return img
    if name == "Noise":
        amount = float(p.get("amount") or 0)
        if amount <= 0:
            return img
        rnd = random.Random(1234)
        noise = Image.effect_noise((w, h), max(1.0, amount * 2)).convert("L")
        tint = Image.new("RGBA", (w, h), (rnd.randint(0, 255),) * 3 + (255,))
        noise_rgba = Image.merge("RGBA", (noise, noise, noise, noise.point(lambda v: int(v * 0.35))))
        return Image.alpha_composite(img, noise_rgba)
    return img  # efek yang belum disimulasikan: dibiarkan


def _solid_surface(layer: SimLayer) -> Any:
    w, h = (int(layer.solid_size[0]), int(layer.solid_size[1])) if layer.solid_size else (1920, 1080)
    img = Image.new("RGBA", (w, h), _rgba(layer.color))
    for eff in layer.effects:
        img = _apply_effect(img, eff, (w, h))
    return img


def _shape_surface(layer: SimLayer) -> Any:
    w, h = (int(layer.size[0]), int(layer.size[1])) if layer.size else (300, 300)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = _rgba(layer.fill)
    kind = layer.shape
    if kind == "ellipse":
        draw.ellipse([0, 0, w - 1, h - 1], fill=color)
    elif kind == "rounded":
        draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=max(1, min(w, h) // 6), fill=color)
    elif kind in ("star", "polygon"):
        cx, cy = w / 2, h / 2
        pts = []
        spikes = 5 if kind == "star" else 6
        for i in range(spikes * 2 if kind == "star" else spikes):
            ang = -math.pi / 2 + i * (math.pi / spikes if kind == "star" else 2 * math.pi / spikes)
            rr = (min(w, h) / 2) * (0.5 if (kind == "star" and i % 2) else 1.0)
            pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
        draw.polygon(pts, fill=color)
    else:
        draw.rectangle([0, 0, w - 1, h - 1], fill=color)
    for eff in layer.effects:
        img = _apply_effect(img, eff, (w, h))
    return img


def _text_surface(layer: SimLayer) -> Any:
    size = max(4, int(layer.font_size))
    font = _font(size, layer.font)
    lines = layer.text.splitlines() or [""]
    pad = max(8, size // 4)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    widths = []
    heights = []
    for line in lines:
        box = probe.textbbox((0, 0), line or " ", font=font)
        widths.append(box[2] - box[0])
        heights.append(box[3] - box[1])
    line_gap = int(size * 0.25)
    w = max(1, max(widths) + pad * 2)
    h = max(1, sum(heights) + line_gap * (len(lines) - 1) + pad * 2)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = pad
    for line, lh in zip(lines, heights):
        box = draw.textbbox((0, 0), line or " ", font=font)
        lw = box[2] - box[0]
        if layer.justify == "left":
            x = pad - box[0]
        elif layer.justify == "right":
            x = w - pad - lw - box[0]
        else:
            x = (w - lw) / 2 - box[0]
        draw.text((x + layer.tracking * 0, y - box[1]), line, font=font, fill=_rgba(layer.fill))
        y += lh + line_gap
    for eff in layer.effects:
        img = _apply_effect(img, eff, (w, h))
    return img


def _layer_surface(layer: SimLayer) -> Any:
    if layer.base_surface is None:
        if layer.type == "solid":
            layer.base_surface = _solid_surface(layer)
        elif layer.type == "shape":
            layer.base_surface = _shape_surface(layer)
        else:
            layer.base_surface = _text_surface(layer)
    return layer.base_surface


# --------------------------------------------------------------------------- render


def _ffmpeg_exe() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


class SimulatedEngine:
    """Model mini EffectCraft + renderer Pillow/FFmpeg."""

    def __init__(self, on_warning=None) -> None:
        self.project = SimProject()
        self.on_warning = on_warning or (lambda msg: None)

    def execute(self, command: str, params: dict) -> Any:
        return apply_step(self.project, command, params)

    def render(self, out_path: Path, *, fps: float | None = None, on_event: EventFn | None = None) -> dict:
        comp = self.project.comp
        fps = float(fps or comp.fps)
        frames = max(1, int(round(comp.duration * fps)))
        w, h = comp.width, comp.height
        ffmpeg = _ffmpeg_exe()
        if ffmpeg is None:
            raise RunnerError(
                "FFmpeg tidak ditemukan untuk simulator",
                hint="Pasang FFmpeg, atau `pip install imageio-ffmpeg` (menyertakan binary ffmpeg).",
            )
        bg = _rgba(comp.background)
        argv = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{w}x{h}",
            "-r",
            f"{fps:g}",
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        assert proc.stdin is not None
        t0 = time.monotonic()
        try:
            for f in range(frames):
                t = f / fps
                canvas = Image.new("RGBA", (w, h), bg)
                for layer in self.project.layers:
                    if t + 1e-9 < layer.in_time:
                        continue
                    if layer.out_time is not None and t >= layer.out_time:
                        continue
                    surface = _layer_surface(layer)
                    if surface is None or surface.width < 1 or surface.height < 1:
                        continue
                    scale = self.project.value_at(layer, "scale", t)
                    if isinstance(scale, (int, float)):
                        sx = sy = float(scale) / 100.0
                    else:
                        sx = float(scale[0]) / 100.0
                        sy = float(scale[1]) / 100.0
                    opacity = float(self.project.value_at(layer, "opacity", t) or 0) / 100.0
                    rotation = float(self.project.value_at(layer, "rotation", t) or 0)
                    pos = self.project.value_at(layer, "position", t)
                    px, py = float(pos[0]), float(pos[1])
                    if sx <= 0 or sy <= 0 or opacity <= 0.003:
                        continue
                    img = surface
                    if abs(sx - 1) > 1e-3 or abs(sy - 1) > 1e-3:
                        img = img.resize((max(1, int(img.width * sx)), max(1, int(img.height * sy))), Image.BICUBIC)
                    if abs(rotation) > 1e-3:
                        img = img.rotate(-rotation, expand=True, resample=Image.BICUBIC)
                    if opacity < 0.999:
                        alpha = img.getchannel("A").point(lambda v: int(v * opacity))
                        img = img.copy()
                        img.putalpha(alpha)
                    # Teks mengikuti `justify` (anchor kiri/tengah/kanan), layer lain di tengah.
                    if layer.type == "text" and layer.justify == "left":
                        left = px
                    elif layer.type == "text" and layer.justify == "right":
                        left = px - img.width
                    else:
                        left = px - img.width / 2
                    canvas.alpha_composite(img, (int(round(left)), int(round(py - img.height / 2))))
                proc.stdin.write(canvas.convert("RGB").tobytes())
                if f % max(1, frames // 20) == 0:
                    emit(on_event, "progress-sim", f"frame {f + 1}/{frames}", {"done": f + 1, "total": frames})
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            stderr = b""
            try:
                stderr = proc.stderr.read() if proc.stderr else b""
            except OSError:
                pass
            proc.wait(timeout=120)
        if proc.returncode != 0:
            raise RunnerError(
                "FFmpeg gagal meng-encode MP4",
                hint="Periksa pemasangan FFmpeg.",
                stderr=stderr.decode("utf-8", errors="replace")[-1500:],
            )
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RunnerError("MP4 hasil simulator kosong")
        return {
            "path": str(out_path),
            "frames": frames,
            "seconds": time.monotonic() - t0,
            "width": w,
            "height": h,
            "fps": fps,
        }


class SimulationRunner:
    kind = "simulator"
    is_simulator = True
    label = "SIMULATOR (bukan EffectCraft)"

    def __init__(self, *, frame_limit: int = 1800) -> None:
        self.frame_limit = frame_limit
        self._steps: list[dict] = []

    def preflight(self) -> Preflight:
        if Image is None:
            return Preflight(
                available=False,
                detail="Pillow tidak terpasang.",
                hint="`pip install pillow imageio-ffmpeg` untuk mode simulator.",
            )
        if _ffmpeg_exe() is None:
            return Preflight(
                available=False,
                detail="FFmpeg tidak ditemukan.",
                hint="`pip install imageio-ffmpeg` menyertakan binary FFmpeg.",
            )
        return Preflight(
            available=True,
            detail="Simulator internal (Pillow + FFmpeg). Hasil BUKAN rendering EffectCraft.",
        )

    def build(self, steps: list[dict], project_path: Path, on_event: EventFn | None = None) -> EngineResult:
        project_path = Path(project_path)
        project_path.parent.mkdir(parents=True, exist_ok=True)
        steps_file = project_path.with_name("steps.json")
        steps_file.write_text(json.dumps(steps, indent=2, ensure_ascii=False), encoding="utf-8")

        engine = SimulatedEngine()
        records: list[StepRecord] = []
        t_start = time.monotonic()
        for i, step in enumerate(steps):
            cmd = str(step.get("command") or "")
            params = step.get("params") or {}
            t0 = time.monotonic()
            try:
                result = engine.execute(cmd, params)
            except (SimError, ValueError, TypeError, KeyError) as e:
                records.append(StepRecord(command=cmd, params=params, ok=False, error=str(e), seconds=time.monotonic() - t0))
                return EngineResult(
                    ok=False,
                    steps=records,
                    # EffectCraft menomori step dari 0: `{id}: {e} (step {n})`.
                    error=f"{cmd}: {e} (step {i})",
                    error_step=i,
                    error_command=cmd,
                    seconds=time.monotonic() - t_start,
                )
            records.append(StepRecord(command=cmd, params=params, result=result, seconds=time.monotonic() - t0))
            emit(on_event, "step", f"{cmd} ok", {"step": i})
        # Proyek disimpan sebagai snapshot JSON supaya riwayat tetap terbaca.
        snapshot = project_path.with_suffix(".sim.json")
        snapshot.write_text(
            json.dumps(
                {
                    "simulator": True,
                    "comp": engine.project.comp.__dict__,
                    "layers": [
                        {
                            "index": l.index,
                            "name": l.name,
                            "type": l.type,
                            "text": l.text,
                            "effects": l.effects,
                            "values": l.values,
                            "keys": {k: [kk.__dict__ for kk in v] for k, v in l.keys.items()},
                            "in": l.in_time,
                            "out": l.out_time,
                        }
                        for l in engine.project.layers
                    ],
                    "steps": steps,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        project_path.write_text(
            json.dumps({"simulator": True, "steps": steps}, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._engine = engine
        self._steps = steps
        return EngineResult(ok=True, steps=records, seconds=time.monotonic() - t_start,
                            warnings=["SIMULATOR: tidak ada EffectCraft yang dijalankan."])

    def render(
        self,
        project_path: Path,
        out_path: Path,
        settings: RenderSettings,
        on_event: EventFn | None = None,
    ) -> EngineResult:
        engine = getattr(self, "_engine", None)
        if engine is None:
            engine, problem = self._replay(Path(project_path))
            if engine is None:
                return EngineResult(ok=False, error=problem or "simulator belum membangun proyek")
        try:
            info = engine.render(Path(out_path), fps=settings.fps, on_event=on_event)
        except RunnerError as e:
            return EngineResult(ok=False, error=e.message, stderr=e.stderr)
        if self.frame_limit and info["frames"] > self.frame_limit:
            return EngineResult(ok=False, error=f"terlalu banyak frame untuk simulator ({info['frames']})")
        emit(on_event, "info", f"SIMULATOR merender {info['frames']} frame {info['width']}×{info['height']}")
        return EngineResult(ok=True, seconds=info["seconds"], warnings=["SIMULATOR"])

    def _replay(self, project_path: Path) -> tuple[SimulatedEngine | None, str | None]:
        """Muat ulang step dari berkas proyek (dipakai saat render tanpa build di sesi yang sama)."""
        steps: list[dict] | None = None
        for candidate in (project_path, project_path.with_suffix(".sim.json")):
            try:
                data = json.loads(Path(candidate).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            raw = data.get("steps")
            if isinstance(raw, list) and raw:
                steps = raw
                break
        if not steps and getattr(self, "_steps", None):
            steps = self._steps
        if not steps:
            return None, "berkas proyek simulator tidak berisi langkah apa pun"
        engine = SimulatedEngine()
        for i, step in enumerate(steps):
            cmd = str(step.get("command") or "")
            try:
                engine.execute(cmd, step.get("params") or {})
            except (SimError, ValueError, TypeError, KeyError) as e:
                return None, f"{cmd}: {e} (step {i})"
        self._engine = engine
        return engine, None

    def close(self) -> None:
        self._engine = None
