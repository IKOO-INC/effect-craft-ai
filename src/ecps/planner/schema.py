"""Skema rencana animasi + validator ketat.

Rencana JSON adalah **satu-satunya** keluaran yang boleh dibuat LLM. Semua nilai yang masuk ke
command EffectCraft berasal dari sini, jadi validator ini adalah garis pertahanan pertama:
tipe, rentang, panjang, jumlah, warna, dan waktu.

Bentuk rencana (versi 1)::

    {
      "version": 1,
      "title": "Intro",
      "style": "neon",
      "comp": {"name": "Main", "width": 1920, "height": 1080,
               "fps": 30, "duration": 5.0, "background": "#0b1020"},
      "layers": [
        {"name": "BG", "type": "solid", "color": "#12224a",
         "effects": [{"effect": "Gradient Ramp",
                      "params": {"startColor": "#0b1e3a", "endColor": "#2f6bff",
                                 "start": [0.5, 0.0], "end": [0.5, 1.0]}}]},
        {"name": "Title", "type": "text", "text": "Majalah Dza Izza",
         "position": [960, 520], "fontSize": 140, "fill": "#ffffff",
         "animate": {"opacity": [{"time": 0, "value": 0},
                                 {"time": 0.8, "value": 100}],
                     "position": [{"time": 0, "value": [960, 560]},
                                  {"time": 0.8, "value": [960, 520]}]},
         "easing": "easyEase"}
      ]
    }

Titik efek: **ternormalisasi 0–1** terhadap ukuran layer (penerjemah mengalikannya dengan
lebar/tinggi layer, karena Gradient Ramp dan kawan-kawan memakai piksel ruang layer).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..errors import PlanError
from ..security.sanitize import safe_color, safe_layer_name, safe_text

PLAN_VERSION = 1
MAX_LAYERS = 40
MAX_EFFECTS_PER_LAYER = 8
MAX_KEYS_PER_PROPERTY = 30
MAX_TOTAL_KEYS = 400
MAX_TEXT_LEN = 300
MAX_DURATION = 120.0
MIN_DURATION = 0.5
MAX_DIM = 7680

LAYER_TYPES = ("text", "solid", "shape")
SHAPE_KINDS = ("rect", "rounded", "ellipse", "star", "polygon")
ANIM_PROPS = ("position", "scale", "rotation", "opacity", "anchor")
EASINGS = ("linear", "easyEase", "hold")
JUSTIFY = ("left", "center", "right")

_EPS = 1e-6


@dataclass
class Key:
    time: float
    value: Any


@dataclass
class EffectSpec:
    name: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Layer:
    name: str
    type: str
    text: str | None = None
    color: str | None = None
    shape: str | None = None
    size: tuple[float, float] | None = None
    position: tuple[float, float] | None = None
    box: tuple[float, float, float, float] | None = None
    font: str | None = None
    font_size: float | None = None
    fill: str | None = None
    justify: str | None = None
    tracking: float | None = None
    effects: list[EffectSpec] = field(default_factory=list)
    animate: dict[str, list[Key]] = field(default_factory=dict)
    easing: str = "easyEase"
    in_time: float = 0.0
    out_time: float | None = None
    width: float | None = None  # solid
    height: float | None = None  # solid


@dataclass
class Comp:
    name: str = "Main"
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    duration: float = 5.0
    background: str = "#000000"


@dataclass
class Plan:
    comp: Comp
    layers: list[Layer]
    title: str = "Untitled"
    style: str = "minimalis"
    version: int = PLAN_VERSION

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "title": self.title,
            "style": self.style,
            "comp": {
                "name": self.comp.name,
                "width": self.comp.width,
                "height": self.comp.height,
                "fps": self.comp.fps,
                "duration": self.comp.duration,
                "background": self.comp.background,
            },
            "layers": [
                {
                    "name": l.name,
                    "type": l.type,
                    **({"text": l.text} if l.text is not None else {}),
                    **({"color": l.color} if l.color is not None else {}),
                    **({"shape": l.shape} if l.shape is not None else {}),
                    **({"size": list(l.size)} if l.size is not None else {}),
                    **({"width": l.width, "height": l.height} if l.width is not None else {}),
                    **({"position": list(l.position)} if l.position is not None else {}),
                    **({"box": list(l.box)} if l.box is not None else {}),
                    **({"font": l.font} if l.font else {}),
                    **({"fontSize": l.font_size} if l.font_size is not None else {}),
                    **({"fill": l.fill} if l.fill else {}),
                    **({"justify": l.justify} if l.justify else {}),
                    **({"tracking": l.tracking} if l.tracking is not None else {}),
                    **(
                        {"effects": [{"effect": e.name, "params": e.params} for e in l.effects]}
                        if l.effects
                        else {}
                    ),
                    **(
                        {
                            "animate": {
                                k: [{"time": round(kt.time, 4), "value": kt.value} for kt in keys]
                                for k, keys in l.animate.items()
                            }
                        }
                        if l.animate
                        else {}
                    ),
                    **({"easing": l.easing} if l.easing else {}),
                    **({"in": round(l.in_time, 4)} if l.in_time else {}),
                    **(
                        {"out": round(l.out_time, 4)}
                        if l.out_time is not None and l.out_time < self.comp.duration - _EPS
                        else {}
                    ),
                }
                for l in self.layers
            ],
        }


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        return float(v)
    return None


def _pair(v: Any, *, allow_scalar: bool = False) -> tuple[float, float] | None:
    if allow_scalar:
        n = _num(v)
        if n is not None:
            return (n, n)
    if isinstance(v, (list, tuple)) and len(v) == 2:
        a, b = _num(v[0]), _num(v[1])
        if a is not None and b is not None:
            return (a, b)
    return None


def _as_dict(v: Any, where: str, errs: list[str]) -> dict:
    if not isinstance(v, dict):
        errs.append(f"{where}: harus objek JSON")
        return {}
    return v


def validate_plan(raw: Any, *, strict_unknown_keys: bool = True) -> Plan:
    """Validasi `raw` dan kembalikan :class:`Plan`. Melempar :class:`PlanError` bila gagal."""
    errs: list[str] = []
    data = _as_dict(raw, "rencana", errs)
    if errs:
        raise PlanError(errs, raw=raw)

    if data.get("version", PLAN_VERSION) != PLAN_VERSION:
        errs.append(f"version: hanya versi {PLAN_VERSION} yang didukung, diterima {data.get('version')!r}")

    title = str(data.get("title") or "Untitled").strip()[:80] or "Untitled"
    style = str(data.get("style") or "minimalis").strip()[:32] or "minimalis"

    comp_raw = _as_dict(data.get("comp"), "comp", errs)
    comp = Comp()
    name = str(comp_raw.get("name") or "Main")
    comp.name = safe_layer_name(name, fallback="Main", max_len=40) or "Main"

    width = _num(comp_raw.get("width", 1920))
    height = _num(comp_raw.get("height", 1080))
    if width is None or not 16 <= width <= MAX_DIM:
        errs.append(f"comp.width: harus angka 16–{MAX_DIM}")
    else:
        comp.width = int(round(width / 2) * 2)
    if height is None or not 16 <= height <= MAX_DIM:
        errs.append(f"comp.height: harus angka 16–{MAX_DIM}")
    else:
        comp.height = int(round(height / 2) * 2)

    fps = _num(comp_raw.get("fps", 30))
    if fps is None or not 1 <= fps <= 60:
        errs.append("comp.fps: harus angka 1–60")
    else:
        comp.fps = float(fps)

    duration = _num(comp_raw.get("duration", 5))
    if duration is None or not MIN_DURATION <= duration <= MAX_DURATION:
        errs.append(f"comp.duration: harus {MIN_DURATION}–{MAX_DURATION} detik")
    else:
        comp.duration = float(duration)

    if "background" in comp_raw and comp_raw["background"]:
        try:
            comp.background = safe_color(str(comp_raw["background"]), what="comp.background")
        except Exception as e:  # noqa: BLE001 - pesannya sudah ramah
            errs.append(f"comp.background: {e}")

    layers_raw = data.get("layers")
    if not isinstance(layers_raw, list) or not layers_raw:
        errs.append("layers: harus array dengan minimal satu layer")
        layers_raw = []
    if len(layers_raw) > MAX_LAYERS:
        errs.append(f"layers: maksimal {MAX_LAYERS} layer, diterima {len(layers_raw)}")

    layers: list[Layer] = []
    used_names: set[str] = set()
    total_keys = 0

    for i, lraw in enumerate(layers_raw):
        where = f"layers[{i}]"
        ld = _as_dict(lraw, where, errs)
        if not ld:
            continue
        ltype = ld.get("type")
        if ltype not in LAYER_TYPES:
            errs.append(f"{where}.type: harus salah satu {', '.join(LAYER_TYPES)}")
            continue

        base_name = safe_layer_name(str(ld.get("name") or ltype.title()), fallback=f"Layer {i + 1}")
        lname = base_name
        n = 2
        while lname.lower() in used_names:
            lname = f"{base_name} {n}"[:60]
            n += 1
        used_names.add(lname.lower())

        layer = Layer(name=lname, type=ltype)

        # --- posisi / geometri
        if ld.get("position") is not None:
            pos = _pair(ld.get("position"))
            if pos is None:
                errs.append(f"{where}.position: harus [x, y]")
            else:
                layer.position = pos

        if ltype == "text":
            try:
                layer.text = safe_text(str(ld.get("text") or ""), max_len=MAX_TEXT_LEN, what=f"{where}.text")
            except Exception as e:  # noqa: BLE001
                errs.append(str(e))
            if ld.get("box") is not None:
                box = ld.get("box")
                if isinstance(box, list) and len(box) == 4 and all(_num(v) is not None for v in box):
                    layer.box = tuple(float(v) for v in box)  # type: ignore[assignment]
                else:
                    errs.append(f"{where}.box: harus [x, y, lebar, tinggi]")
            fs = _num(ld.get("fontSize", ld.get("size")))
            if fs is not None:
                if not 4 <= fs <= 2000:
                    errs.append(f"{where}.fontSize: harus 4–2000")
                else:
                    layer.font_size = fs
            if ld.get("fill") is not None:
                try:
                    layer.fill = safe_color(str(ld["fill"]), what=f"{where}.fill")
                except Exception as e:  # noqa: BLE001
                    errs.append(str(e))
            if ld.get("justify") is not None:
                if str(ld["justify"]) not in JUSTIFY:
                    errs.append(f"{where}.justify: harus salah satu {', '.join(JUSTIFY)}")
                else:
                    layer.justify = str(ld["justify"])
            if ld.get("font") is not None:
                font = str(ld["font"])
                if not font or len(font) > 80:
                    errs.append(f"{where}.font: nama font tidak wajar")
                else:
                    layer.font = font
            tracking = _num(ld.get("tracking"))
            if tracking is not None:
                if not -1000 <= tracking <= 1000:
                    errs.append(f"{where}.tracking: harus -1000–1000")
                else:
                    layer.tracking = tracking

        elif ltype == "solid":
            try:
                layer.color = safe_color(str(ld.get("color") or "#000000"), what=f"{where}.color")
            except Exception as e:  # noqa: BLE001
                errs.append(str(e))
            for key, target in (("width", "width"), ("height", "height")):
                v = _num(ld.get(key))
                if v is not None:
                    if not 1 <= v <= 30000:
                        errs.append(f"{where}.{key}: harus 1–30000")
                    else:
                        setattr(layer, target, v)

        else:  # shape
            kind = str(ld.get("shape") or ld.get("kind") or "rect")
            if kind not in SHAPE_KINDS:
                errs.append(f"{where}.shape: harus salah satu {', '.join(SHAPE_KINDS)}")
            else:
                layer.shape = kind
            size = _pair(ld.get("size"), allow_scalar=True)
            if size is None:
                errs.append(f"{where}.size: harus [lebar, tinggi] atau satu angka")
            else:
                if not (1 <= size[0] <= MAX_DIM and 1 <= size[1] <= MAX_DIM):
                    errs.append(f"{where}.size: harus 1–{MAX_DIM}")
                else:
                    layer.size = size
            if ld.get("fill") is not None:
                try:
                    layer.fill = safe_color(str(ld["fill"]), what=f"{where}.fill")
                except Exception as e:  # noqa: BLE001
                    errs.append(str(e))

        # --- waktu
        in_t = _num(ld.get("in", 0.0)) or 0.0
        if not -0.0 <= in_t <= comp.duration:
            errs.append(f"{where}.in: harus 0–{comp.duration} detik")
        layer.in_time = max(0.0, in_t)
        if ld.get("out") is not None:
            out_t = _num(ld.get("out"))
            if out_t is None or not 0 <= out_t <= comp.duration + _EPS:
                errs.append(f"{where}.out: harus 0–{comp.duration} detik")
            elif out_t <= layer.in_time + _EPS:
                errs.append(f"{where}.out: harus lebih besar dari in")
            else:
                layer.out_time = out_t

        # --- efek
        effects_raw = ld.get("effects") or []
        if not isinstance(effects_raw, list):
            errs.append(f"{where}.effects: harus array")
            effects_raw = []
        if len(effects_raw) > MAX_EFFECTS_PER_LAYER:
            errs.append(f"{where}.effects: maksimal {MAX_EFFECTS_PER_LAYER} efek per layer")
        for j, ef in enumerate(effects_raw[:MAX_EFFECTS_PER_LAYER]):
            ew = f"{where}.effects[{j}]"
            ed = _as_dict(ef, ew, errs)
            eid = ed.get("effect") or ed.get("name") or ed.get("id")
            if not isinstance(eid, str) or not eid.strip():
                errs.append(f"{ew}.effect: harus nama efek")
                continue
            params = ed.get("params") or {}
            if not isinstance(params, dict):
                errs.append(f"{ew}.params: harus objek")
                continue
            layer.effects.append(EffectSpec(name=eid.strip(), params=dict(params)))

        # --- animasi
        easing = str(ld.get("easing") or "easyEase")
        if easing not in EASINGS:
            errs.append(f"{where}.easing: harus salah satu {', '.join(EASINGS)}")
        else:
            layer.easing = easing

        animate_raw = ld.get("animate") or {}
        if not isinstance(animate_raw, dict):
            errs.append(f"{where}.animate: harus objek")
            animate_raw = {}
        for prop, keys_raw in animate_raw.items():
            if prop not in ANIM_PROPS:
                if strict_unknown_keys:
                    errs.append(f"{where}.animate.{prop}: properti tidak didukung (pakai {', '.join(ANIM_PROPS)})")
                continue
            if not isinstance(keys_raw, list) or not keys_raw:
                errs.append(f"{where}.animate.{prop}: harus array keyframe")
                continue
            if len(keys_raw) > MAX_KEYS_PER_PROPERTY:
                errs.append(f"{where}.animate.{prop}: maksimal {MAX_KEYS_PER_PROPERTY} keyframe")
                keys_raw = keys_raw[:MAX_KEYS_PER_PROPERTY]
            keys: list[Key] = []
            last_t = -math.inf
            for k, kraw in enumerate(keys_raw):
                kw = f"{where}.animate.{prop}[{k}]"
                kd = _as_dict(kraw, kw, errs)
                t = _num(kd.get("time", kd.get("t")))
                if t is None:
                    errs.append(f"{kw}.time: harus angka detik")
                    continue
                if t < -_EPS or t > comp.duration + _EPS:
                    errs.append(f"{kw}.time: di luar durasi komposisi (0–{comp.duration})")
                    continue
                if t <= last_t + _EPS and keys:
                    errs.append(f"{kw}.time: harus naik (unik dan berurutan)")
                    continue
                value = _anim_value(prop, kd.get("value", kd.get("v")), kw, errs)
                if value is None:
                    continue
                keys.append(Key(time=max(0.0, t), value=value))
                last_t = t
            if keys:
                layer.animate[prop] = keys
                total_keys += len(keys)
        layers.append(layer)

    if total_keys > MAX_TOTAL_KEYS:
        errs.append(f"animate: total keyframe melebihi {MAX_TOTAL_KEYS}")

    if errs:
        raise PlanError(errs, raw=raw)
    if not layers:
        raise PlanError(["layers: tidak ada layer valid"], raw=raw)
    return Plan(comp=comp, layers=layers, title=title, style=style)


def _anim_value(prop: str, v: Any, where: str, errs: list[str]) -> Any:
    if prop == "opacity":
        n = _num(v)
        if n is None or not 0 <= n <= 100:
            errs.append(f"{where}.value: opacity harus 0–100")
            return None
        return n
    if prop == "rotation":
        n = _num(v)
        if n is None or not -1440 <= n <= 1440:
            errs.append(f"{where}.value: rotation harus -1440–1440 derajat")
            return None
        return n
    if prop in ("scale",):
        pair = _pair(v, allow_scalar=True)
        if pair is None or not all(0 <= c <= 1000 for c in pair):
            errs.append(f"{where}.value: scale harus angka/[x,y] 0–1000 (persen)")
            return None
        return [pair[0], pair[1]]
    pair = _pair(v)
    if pair is None or not all(-20000 <= c <= 20000 for c in pair):
        errs.append(f"{where}.value: {prop} harus [x, y] dalam piksel komposisi")
        return None
    return [pair[0], pair[1]]


#: Teks skema yang ditempelkan ke prompt LLM.
PLAN_SCHEMA_TEXT = """\
Rencana JSON (versi 1) — hanya field di bawah ini yang diizinkan:

{
  "version": 1,
  "title": "judul singkat",
  "style": "minimalis|neon|korporat|elegan|retro|bold|podcast|gelap",
  "comp": {"name": "Main", "width": 1920, "height": 1080, "fps": 30,
           "duration": 5.0, "background": "#0b1020"},
  "layers": [
    {
      "name": "BG",                       // unik, huruf/angka/spasi
      "type": "solid|text|shape",
      "text": "Teks judul",               // wajib untuk text
      "color": "#12224a",                 // wajib untuk solid
      "shape": "rect|rounded|ellipse|star|polygon",  // wajib untuk shape
      "size": [640, 360],                 // shape: [lebar, tinggi] piksel
      "width": 1920, "height": 1080,      // solid opsional (default ukuran comp)
      "position": [960, 540],
      "box": [460, 380, 1000, 320],       // opsional, teks paragraf
      "font": "Inter", "fontSize": 140, "fill": "#ffffff",
      "justify": "left|center|right", "tracking": 0,
      "in": 0.2, "out": 4.6,
      "effects": [{"effect": "Gradient Ramp",
                   "params": {"startColor": "#0b1e3a", "endColor": "#2f6bff",
                              "start": [0.5, 0.0], "end": [0.5, 1.0]}}],
      "animate": {
        "opacity":  [{"time": 0.0, "value": 0}, {"time": 0.8, "value": 100}],
        "position": [{"time": 0.0, "value": [960, 600]}, {"time": 0.8, "value": [960, 540]}],
        "scale":    [{"time": 0.0, "value": [80, 80]}, {"time": 0.8, "value": [100, 100]}],
        "rotation": [{"time": 0.0, "value": -4}, {"time": 0.8, "value": 0}],
        "anchor":   [{"time": 0.0, "value": [960, 540]}]
      },
      "easing": "linear|easyEase|hold"
    }
  ]
}

Aturan:
- Waktu dalam DETIK, 0..comp.duration, harus naik dan unik per properti.
- `animate` hanya boleh berisi position, scale, rotation, opacity, anchor.
- opacity 0–100; scale persen (100 = normal); rotation derajat.
- Titik parameter efek (`start`, `end`, `center`, `positionsColors/point1` …) TERNORMALISASI
  0–1 terhadap ukuran layer: [0.5, 0.0] = tengah-atas, [0.5, 1.0] = tengah-bawah.
- Warna selalu "#rrggbb".
- Maksimal 40 layer, 8 efek/layer, 30 keyframe/properti.
- Jangan memakai properti di luar daftar di atas. Tidak ada field tambahan.
"""

#: Contoh rencana minimal yang valid (dipakai di prompt few-shot dan di test).
EXAMPLE_PLAN: dict = {
    "version": 1,
    "title": "Contoh Intro",
    "style": "minimalis",
    "comp": {"name": "Main", "width": 1920, "height": 1080, "fps": 30, "duration": 5.0, "background": "#0b1020"},
    "layers": [
        {
            "name": "BG",
            "type": "solid",
            "color": "#0b1e3a",
            "effects": [
                {
                    "effect": "Gradient Ramp",
                    "params": {
                        "startColor": "#06122b",
                        "endColor": "#2f6bff",
                        "start": [0.5, 0.0],
                        "end": [0.5, 1.0],
                    },
                }
            ],
        },
        {
            "name": "Title",
            "type": "text",
            "text": "Majalah Dza Izza",
            "position": [960, 540],
            "fontSize": 140,
            "fill": "#ffffff",
            "justify": "center",
            "animate": {
                "opacity": [{"time": 0.0, "value": 0}, {"time": 0.8, "value": 100}],
                "position": [{"time": 0.0, "value": [960, 600]}, {"time": 0.8, "value": [960, 540]}],
            },
            "easing": "easyEase",
        },
    ],
}
