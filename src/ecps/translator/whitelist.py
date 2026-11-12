"""Whitelist command + efek EffectCraft.

Semua isi tabel ini diambil dari sumber EffectCraft v0.24.1:

* `COMMANDS`  -> `CommandSpec` di `crates/engine/src/cmd/**` (params doc verbatim, diringkas).
* `EFFECTS`   -> `crates/effects/src/**` (`spec(...)`/`p("id", …)`), dengan tipe parameter yang
  dibaca langsung dari definisinya (Point/Color/slider/popup/Checkbox).

Penerjemah **hanya** boleh mengeluarkan command dan parameter yang ada di sini. Menambah
kemampuan = menambah entri di tabel ini (bukan mengarang nama parameter saat runtime).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import TranslationError
from ..security.sanitize import clamp, safe_color


@dataclass(frozen=True)
class Command:
    params_doc: str
    allowed: frozenset[str]
    source: str


def _cmd(params_doc: str, allowed: str, source: str) -> Command:
    return Command(params_doc=params_doc, allowed=frozenset(a.strip() for a in allowed.split(",") if a.strip()), source=source)


#: Command engine yang boleh dijalankan oleh penerjemah.
COMMANDS: dict[str, Command] = {
    "comp.new": _cmd(
        "{name?, width?, height?, frameRate?, duration? (s), startTime?, background? #hex, pixelAspect?, renderer?, open?}",
        "name,width,height,frameRate,duration,background,startTime,pixelAspect,open",
        "crates/engine/src/cmd/comp.rs::new_comp",
    ),
    "layer.newText": _cmd(
        "{text?, name?, position?, box?, font?, style?, size?, fill?, stroke?, applyFill?, applyStroke?, "
        "strokeWidth?, tracking?, leading?, justify?, allCaps?, fauxBold?, fauxItalic?}",
        "text,name,position,box,font,style,size,fill,stroke,applyFill,applyStroke,strokeWidth,"
        "tracking,justify,allCaps,fauxBold,fauxItalic",
        "crates/engine/src/cmd/layer/create.rs::new_text",
    ),
    "layer.newSolid": _cmd(
        "{name?, color? #hex, width?, height?, pixelAspect?}",
        "name,color,width,height,pixelAspect",
        "crates/engine/src/cmd/layer/create.rs::new_solid",
    ),
    "layer.newShape": _cmd(
        "{kind? rect|rounded|ellipse|star|polygon|none, name?, size?, fill?, fillOpacity?, "
        "stroke?, strokeWidth?, position?}",
        "kind,name,size,fill,fillOpacity,stroke,strokeType,strokeOpacity,strokeWidth,position",
        "crates/engine/src/cmd/layer/create.rs::new_shape",
    ),
    "effect.apply": _cmd(
        "{effect: id|name, layer? | layers?} -> {effects, paths}",
        "effect,layer,layers",
        "crates/engine/src/cmd/effect.rs::apply",
    ),
    "prop.set": _cmd(
        "{layer?, path|prop, value, time? (layer s), timeBase? layer|comp}",
        "layer,path,prop,value,time,timeBase",
        "crates/engine/src/cmd/prop.rs::set",
    ),
    "prop.addKey": _cmd(
        "{layer?, path|prop, time? (layer s), timeBase? layer|comp, value?}",
        "layer,path,prop,time,timeBase,value",
        "crates/engine/src/cmd/prop.rs::add_key",
    ),
    "keys.select": _cmd(
        "{keys: [{layer, prop|path, time}], timeBase? layer|comp, add?, toggle?}",
        "keys,timeBase,add,toggle,selectProperties",
        "crates/engine/src/cmd/prop.rs::select_keys",
    ),
    "keys.easyEase": _cmd("{which? both|in|out}", "which", "crates/engine/src/cmd/prop.rs::ease"),
    "keys.interpolation": _cmd(
        "{interpolation? linear|bezier|continuousBezier|autoBezier|hold, in?, out?}",
        "interpolation,in,out",
        "crates/engine/src/cmd/prop.rs::interpolation",
    ),
    "layer.timing": _cmd(
        "{layers?, start?, in?, out?, inDelta?, outDelta? (detik komposisi)}",
        "layers,start,in,out,inDelta,outDelta,op,delta",
        "crates/engine/src/cmd/layer/timing.rs::timing",
    ),
}

#: Properti transform yang boleh dianimasikan (path dari `prop.get`/`prop.set`).
PROP_PATHS: dict[str, str] = {
    "position": "transform/position",
    "scale": "transform/scale",
    "rotation": "transform/rotation",
    "opacity": "transform/opacity",
    "anchor": "transform/anchor",
}


def _num(lo: float | None = None, hi: float | None = None, *, unit: str = "number") -> dict:
    return {"type": "number", "min": lo, "max": hi, "unit": unit}


def _enum(*options: str) -> dict:
    return {"type": "enum", "options": list(options)}


EFFECTS: dict[str, dict[str, Any]] = {
    # ---------------------------------------------------------------- Generate
    "Gradient Ramp": {
        "id": "ec.generate.gradientramp",
        "category": "Generate",
        "params": {
            "start": {"type": "point_norm"},
            "startColor": {"type": "color"},
            "end": {"type": "point_norm"},
            "endColor": {"type": "color"},
            "shape": _enum("Linear Ramp", "Radial Ramp"),
            "scatter": _num(0, 512),
            "blend": _num(0, 100, unit="percent"),
        },
    },
    "4-Color Gradient": {
        "id": "ec.generate.fourcolor",
        "category": "Generate",
        "params": {
            "positionsColors/point1": {"type": "point_norm"},
            "positionsColors/color1": {"type": "color"},
            "positionsColors/point2": {"type": "point_norm"},
            "positionsColors/color2": {"type": "color"},
            "positionsColors/point3": {"type": "point_norm"},
            "positionsColors/color3": {"type": "color"},
            "positionsColors/point4": {"type": "point_norm"},
            "positionsColors/color4": {"type": "color"},
            "blend": _num(1, 10000),
            "jitter": _num(0, 500),
            "opacity": _num(0, 100, unit="percent"),
        },
    },
    "Fill": {
        "id": "ec.generate.fill",
        "category": "Generate",
        "params": {
            "color": {"type": "color"},
            "opacity": _num(0, 100, unit="percent"),
            "horizontalFeather": _num(0, 5000),
            "verticalFeather": _num(0, 5000),
        },
    },
    "Grid": {
        "id": "ec.generate.grid",
        "category": "Generate",
        "params": {
            "anchor": {"type": "point_norm"},
            "corner": {"type": "point_norm"},
            "width": _num(1, 4000, unit="px"),
            "height": _num(1, 4000, unit="px"),
            "border": _num(0, 2000, unit="px"),
            "feather/featherWidth": _num(0, 1000, unit="px"),
            "feather/featherHeight": _num(0, 1000, unit="px"),
            "invertGrid": {"type": "bool"},
            "color": {"type": "color"},
            "opacity": _num(0, 100, unit="percent"),
        },
    },
    "Checkerboard": {
        "id": "ec.generate.checkerboard",
        "category": "Generate",
        "params": {
            "anchor": {"type": "point_norm"},
            "corner": {"type": "point_norm"},
            "width": _num(1, 4000, unit="px"),
            "height": _num(1, 4000, unit="px"),
            "feather/featherWidth": _num(0, 1000, unit="px"),
            "feather/featherHeight": _num(0, 1000, unit="px"),
            "color": {"type": "color"},
            "opacity": _num(0, 100, unit="percent"),
        },
    },
    "Circle": {
        "id": "ec.generate.circle",
        "category": "Generate",
        "params": {
            "center": {"type": "point_norm"},
            "radius": _num(0, 20000, unit="px"),
            "edge": _enum("None", "Edge Radius", "Thickness"),
            "edgeRadius": _num(0, 20000, unit="px"),
            "thickness": _num(0, 20000, unit="px"),
            "feather/feather": _num(0, 20000, unit="px"),
            "feather/featherInner": _num(0, 20000, unit="px"),
            "invert": {"type": "bool"},
            "color": {"type": "color"},
            "opacity": _num(0, 100, unit="percent"),
        },
    },
    # ------------------------------------------------------------------- Color
    "Tint": {
        "id": "ec.color.tint",
        "category": "Color Correction",
        "params": {
            "black": {"type": "color"},
            "white": {"type": "color"},
            "amount": _num(0, 100, unit="percent"),
        },
    },
    "Brightness & Contrast": {
        "id": "ec.color.brightnesscontrast",
        "category": "Color Correction",
        "params": {
            "brightness": _num(-150, 150),
            "contrast": _num(-100, 100, unit="percent"),
            "useLegacy": {"type": "bool"},
        },
    },
    "Hue/Saturation": {
        "id": "ec.color.huesaturation",
        "category": "Color Correction",
        "params": {
            "hue": _num(-180, 180, unit="degree"),
            "saturation": _num(-100, 100, unit="percent"),
            "lightness": _num(-100, 100, unit="percent"),
        },
    },
    # ----------------------------------------------------------------- Stylize
    "Glow": {
        "id": "ec.stylize.glow",
        "category": "Stylize",
        "params": {
            "based": _enum("Alpha Channel", "Color Channels"),
            "threshold": _num(0, 100, unit="percent"),
            "radius": _num(0, 1000, unit="px"),
            "intensity": _num(0, 255),
            "operation": _enum("On Top", "Behind", "None"),
            "colorA": {"type": "color"},
            "colorB": {"type": "color"},
            "glowDimensions": _enum("Horizontal", "Vertical", "Horizontal and Vertical"),
        },
    },
    "Drop Shadow": {
        "id": "ec.perspective.dropshadow",
        "category": "Perspective",
        "params": {
            "color": {"type": "color"},
            "opacity": _num(0, 100, unit="percent"),
            "direction": _num(-3600, 3600, unit="degree"),
            "distance": _num(0, 32000, unit="px"),
            "softness": _num(0, 1000, unit="px"),
            "shadowOnly": {"type": "bool"},
        },
    },
    "Mosaic": {
        "id": "ec.stylize.mosaic",
        "category": "Stylize",
        "params": {
            "horizontal": _num(1, 4000),
            "vertical": _num(1, 4000),
            "sharpColors": {"type": "bool"},
        },
    },
    "Posterize": {
        "id": "ec.stylize.posterize",
        "category": "Stylize",
        "params": {"level": _num(2, 255)},
    },
    "Threshold": {
        "id": "ec.stylize.threshold",
        "category": "Stylize",
        "params": {"level": _num(0, 255)},
    },
    "Emboss": {
        "id": "ec.stylize.emboss",
        "category": "Stylize",
        "params": {
            "direction": _num(-3600, 3600, unit="degree"),
            "relief": _num(0, 1000),
            "contrast": _num(0, 1000),
            "blend": _num(0, 100, unit="percent"),
        },
    },
    "Find Edges": {
        "id": "ec.stylize.findedges",
        "category": "Stylize",
        "params": {"invert": {"type": "bool"}, "blend": _num(0, 100, unit="percent")},
    },
    # -------------------------------------------------------- Blur & Sharpen
    "Gaussian Blur": {
        "id": "ec.blur.gaussian",
        "category": "Blur & Sharpen",
        "params": {
            "blurriness": _num(0, 3000, unit="px"),
            "dimensions": _enum("Horizontal", "Vertical", "Horizontal and Vertical"),
            "repeatEdge": {"type": "bool"},
        },
    },
    "Fast Box Blur": {
        "id": "ec.blur.fastbox",
        "category": "Blur & Sharpen",
        "params": {
            "radius": _num(0, 3000, unit="px"),
            "iterations": _num(1, 50),
            "dimensions": _enum("Horizontal", "Vertical", "Horizontal and Vertical"),
            "repeatEdge": {"type": "bool"},
        },
    },
    "Directional Blur": {
        "id": "ec.blur.directional",
        "category": "Blur & Sharpen",
        "params": {
            "direction": _num(-3600, 3600, unit="degree"),
            "length": _num(0, 3000, unit="px"),
        },
    },
    "Radial Blur": {
        "id": "ec.blur.radial",
        "category": "Blur & Sharpen",
        "params": {
            "amount": _num(0, 1000),
            "center": {"type": "point_norm"},
            "type": _enum("Spin", "Zoom"),
            "antialiasing": _enum("Low", "High"),
        },
    },
    "Sharpen": {
        "id": "ec.blur.sharpen",
        "category": "Blur & Sharpen",
        "params": {"amount": _num(0, 1000)},
    },
    "Unsharp Mask": {
        "id": "ec.blur.unsharpmask",
        "category": "Blur & Sharpen",
        "params": {
            "amount": _num(0, 1000, unit="percent"),
            "radius": _num(0, 3000, unit="px"),
            "threshold": _num(0, 255),
        },
    },
    # -------------------------------------------------------------- Transition
    "Linear Wipe": {
        "id": "ec.transition.linearwipe",
        "category": "Transition",
        "params": {
            "completion": _num(0, 100, unit="percent"),
            "angle": _num(-3600, 3600, unit="degree"),
            "feather": _num(0, 32000, unit="px"),
        },
    },
    "Radial Wipe": {
        "id": "ec.transition.radialwipe",
        "category": "Transition",
        "params": {
            "completion": _num(0, 100, unit="percent"),
            "startAngle": _num(-3600, 3600, unit="degree"),
            "center": {"type": "point_norm"},
            "wipe": _enum("Clockwise", "Counterclockwise", "Both"),
            "feather": _num(0, 32000, unit="px"),
        },
    },
    "Venetian Blinds": {
        "id": "ec.transition.venetian",
        "category": "Transition",
        "params": {
            "completion": _num(0, 100, unit="percent"),
            "direction": _num(-3600, 3600, unit="degree"),
            "width": _num(1, 32000, unit="px"),
            "feather": _num(0, 32000, unit="px"),
        },
    },
    # -------------------------------------------------------------- Channel
    "Invert": {
        "id": "ec.channel.invert",
        "category": "Channel",
        "params": {
            "channel": _enum("RGB", "Red", "Green", "Blue", "Alpha", "Hue", "Lightness", "Saturation", "YIQ Luminance"),
            "blend": _num(0, 100, unit="percent"),
        },
    },
    # ---------------------------------------------------------------- Noise
    "Noise": {
        "id": "ec.noise.noise",
        "category": "Noise & Grain",
        "params": {"amount": _num(0, 100, unit="percent"), "color": {"type": "bool"}},
    },
}

#: Alias nama efek yang sering muncul dari LLM (huruf kecil).
EFFECT_ALIASES: dict[str, str] = {
    "gradient": "Gradient Ramp",
    "gradient ramp": "Gradient Ramp",
    "gradient overlay": "Gradient Ramp",
    "linear gradient": "Gradient Ramp",
    "ramp": "Gradient Ramp",
    "4 color gradient": "4-Color Gradient",
    "four color gradient": "4-Color Gradient",
    "glow": "Glow",
    "outer glow": "Glow",
    "neon glow": "Glow",
    "drop shadow": "Drop Shadow",
    "shadow": "Drop Shadow",
    "gaussian blur": "Gaussian Blur",
    "blur": "Gaussian Blur",
    "box blur": "Fast Box Blur",
    "fast box blur": "Fast Box Blur",
    "directional blur": "Directional Blur",
    "radial blur": "Radial Blur",
    "sharpen": "Sharpen",
    "unsharp mask": "Unsharp Mask",
    "tint": "Tint",
    "brightness & contrast": "Brightness & Contrast",
    "brightness and contrast": "Brightness & Contrast",
    "brightness/contrast": "Brightness & Contrast",
    "hue/saturation": "Hue/Saturation",
    "hue saturation": "Hue/Saturation",
    "fill": "Fill",
    "grid": "Grid",
    "checkerboard": "Checkerboard",
    "circle": "Circle",
    "mosaic": "Mosaic",
    "posterize": "Posterize",
    "threshold": "Threshold",
    "emboss": "Emboss",
    "find edges": "Find Edges",
    "linear wipe": "Linear Wipe",
    "wipe": "Linear Wipe",
    "radial wipe": "Radial Wipe",
    "venetian blinds": "Venetian Blinds",
    "invert": "Invert",
    "noise": "Noise",
}

#: Daftar efek yang dipakai di prompt LLM (nama + parameter).
def effects_doc() -> str:
    lines = []
    for name, spec in EFFECTS.items():
        params = []
        for pid, p in spec["params"].items():
            if p["type"] == "number":
                rng = ""
                if p.get("min") is not None and p.get("max") is not None:
                    rng = f" {p['min']}..{p['max']}"
                unit = "" if p.get("unit") in (None, "number") else f" {p['unit']}"
                params.append(f"{pid}:angka{rng}{unit}")
            elif p["type"] == "color":
                params.append(f"{pid}:warna")
            elif p["type"] == "bool":
                params.append(f"{pid}:bool")
            elif p["type"] == "point_norm":
                params.append(f"{pid}:titik0-1")
            elif p["type"] == "enum":
                params.append(f"{pid}:{'|'.join(p['options'])}")
        lines.append(f"- {name}: " + ", ".join(params))
    return "\n".join(lines)


def resolve_effect(name: str) -> str:
    """Nama efek (boleh alias / beda huruf besar-kecil) → nama kanonik di whitelist."""
    if not isinstance(name, str) or not name.strip():
        raise TranslationError("nama efek kosong")
    raw = name.strip()
    if raw in EFFECTS:
        return raw
    lowered = raw.lower()
    for canonical in EFFECTS:
        if canonical.lower() == lowered:
            return canonical
    if lowered in EFFECT_ALIASES:
        return EFFECT_ALIASES[lowered]
    # Alias berbasis kata kunci, tetap hanya ke efek yang ada di whitelist.
    for alias, canonical in EFFECT_ALIASES.items():
        if alias in lowered:
            return canonical
    raise TranslationError(
        f"efek '{raw}' tidak ada di whitelist. Efek yang didukung: " + ", ".join(sorted(EFFECTS))
    )


def _check_enum(p: dict, value: Any, *, where: str) -> int:
    options: list[str] = p["options"]
    if isinstance(value, bool):
        raise TranslationError(f"{where}: nilai enum tidak boleh boolean")
    if isinstance(value, (int, float)) and float(value).is_integer():
        idx = int(value)
        if not 0 <= idx < len(options):
            raise TranslationError(f"{where}: indeks {idx} di luar 0..{len(options) - 1}")
        return idx
    if isinstance(value, str):
        v = value.strip()
        for i, opt in enumerate(options):
            if opt.lower() == v.lower():
                return i
        raise TranslationError(f"{where}: '{value}' bukan pilihan yang sah ({', '.join(options)})")
    raise TranslationError(f"{where}: butuh nama pilihan atau indeks angka")


def _check_number(p: dict, value: Any, *, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TranslationError(f"{where}: butuh angka")
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):
        raise TranslationError(f"{where}: angka tidak valid")
    lo, hi = p.get("min"), p.get("max")
    if lo is not None and v < lo:
        raise TranslationError(f"{where}: {v} di bawah minimum {lo}")
    if hi is not None and v > hi:
        raise TranslationError(f"{where}: {v} di atas maksimum {hi}")
    return clamp(v, lo if lo is not None else -1e9, hi if hi is not None else 1e9)


def effect_param_value(
    effect: str,
    param: str,
    value: Any,
    *,
    layer_size: tuple[float, float] | None,
    where: str = "params",
) -> Any:
    """Validasi + konversi satu nilai parameter efek ke bentuk JSON EffectCraft."""
    spec = EFFECTS[effect]["params"]
    if param not in spec:
        raise TranslationError(
            f"{where}.{param}: parameter tidak didukung untuk efek {effect}. "
            f"Yang ada: " + ", ".join(spec)
        )
    p = spec[param]
    kind = p["type"]
    if kind == "number":
        return _check_number(p, value, where=f"{where}.{param}")
    if kind == "color":
        return safe_color(value, what=f"{where}.{param}")
    if kind == "bool":
        if not isinstance(value, bool):
            raise TranslationError(f"{where}.{param}: butuh boolean true/false")
        return value
    if kind == "enum":
        return _check_enum(p, value, where=f"{where}.{param}")
    if kind == "point_norm":
        if not (isinstance(value, (list, tuple)) and len(value) == 2
                and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in value)):
            raise TranslationError(f"{where}.{param}: butuh titik [x, y] ternormalisasi 0–1")
        x, y = float(value[0]), float(value[1])
        if not (-0.5 <= x <= 1.5 and -0.5 <= y <= 1.5):
            raise TranslationError(f"{where}.{param}: titik harus 0–1 (diterima {x}, {y})")
        if layer_size is None:
            raise TranslationError(
                f"{where}.{param}: titik ternormalisasi hanya didukung pada layer solid "
                "(ukurannya pasti); pakai layer solid untuk efek titik."
            )
        w, h = layer_size
        return [round(clamp(x, 0.0, 1.0) * w, 3), round(clamp(y, 0.0, 1.0) * h, 3)]
    raise TranslationError(f"{where}.{param}: tipe parameter tidak dikenal")  # pragma: no cover
