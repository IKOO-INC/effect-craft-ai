"""Penerjemah deterministik: rencana JSON → urutan command EffectCraft.

Tidak ada LLM di lapisan ini. Setiap langkah divalidasi terhadap :mod:`ecps.translator.whitelist`
(command id dan nama parameter), dan semua nilai disanitasi sebelum menjadi argumen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..errors import TranslationError
from ..planner.schema import Layer, Plan
from ..security.sanitize import safe_color, safe_text
from .whitelist import COMMANDS, EFFECTS, PROP_PATHS, effect_param_value, resolve_effect


@dataclass
class Step:
    command: str
    params: dict[str, Any]
    note: str = ""

    def to_json(self) -> dict:
        return {"command": self.command, "params": self.params}


@dataclass
class Translation:
    steps: list[Step]
    comp_name: str
    width: int
    height: int
    fps: float
    duration: float
    warnings: list[str] = field(default_factory=list)

    def commands_json(self) -> list[dict]:
        return [s.to_json() for s in self.steps]


def _step(out: list[Step], command: str, params: dict[str, Any], note: str = "") -> None:
    """Tambahkan langkah setelah memastikan command & nama parameternya ada di whitelist."""
    if command not in COMMANDS:
        raise TranslationError(f"command '{command}' tidak ada di whitelist")
    allowed = COMMANDS[command].allowed
    unknown = set(params) - allowed
    if unknown:
        raise TranslationError(
            f"{command}: parameter {sorted(unknown)} tidak ada di whitelist "
            f"(yang sah: {sorted(allowed)})"
        )
    out.append(Step(command=command, params=params, note=note))


def _validate_prop_path(path: str) -> None:
    if path not in PROP_PATHS.values():
        raise TranslationError(f"path properti '{path}' tidak ada di whitelist")


def _layer_creation(layer: Layer, comp_w: int, comp_h: int) -> tuple[str, dict]:
    if layer.type == "text":
        params: dict[str, Any] = {
            "name": layer.name,
            "text": safe_text(layer.text or "", max_len=300, what=f"layer '{layer.name}' text"),
        }
        if layer.box is not None:
            params["box"] = [float(v) for v in layer.box]
        if layer.position is not None:
            params["position"] = [float(layer.position[0]), float(layer.position[1])]
        if layer.font_size is not None:
            params["size"] = float(layer.font_size)
        if layer.fill:
            params["fill"] = safe_color(layer.fill, what=f"layer '{layer.name}' fill")
        if layer.justify:
            params["justify"] = layer.justify
        if layer.font:
            params["font"] = layer.font
        if layer.tracking is not None:
            params["tracking"] = float(layer.tracking)
        return "layer.newText", params

    if layer.type == "solid":
        return "layer.newSolid", {
            "name": layer.name,
            "color": safe_color(layer.color or "#000000", what=f"layer '{layer.name}' color"),
            "width": int(round(layer.width if layer.width is not None else comp_w)),
            "height": int(round(layer.height if layer.height is not None else comp_h)),
        }

    if layer.type == "shape":
        params = {
            "kind": layer.shape or "rect",
            "name": layer.name,
            "size": [
                float(layer.size[0]) if layer.size else 300.0,
                float(layer.size[1]) if layer.size else 300.0,
            ],
        }
        if layer.fill:
            params["fill"] = safe_color(layer.fill, what=f"layer '{layer.name}' fill")
        if layer.position is not None:
            params["position"] = [float(layer.position[0]), float(layer.position[1])]
        return "layer.newShape", params

    raise TranslationError(f"tipe layer '{layer.type}' tidak didukung")  # pragma: no cover


def translate(plan: Plan) -> Translation:
    """Terjemahkan rencana tervalidasi menjadi command EffectCraft."""
    steps: list[Step] = []
    warnings: list[str] = []
    comp = plan.comp

    _step(
        steps,
        "comp.new",
        {
            "name": comp.name,
            "width": comp.width,
            "height": comp.height,
            "frameRate": comp.fps,
            "duration": round(comp.duration, 4),
            "background": safe_color(comp.background, what="comp.background"),
        },
        note=f"komposisi {comp.width}×{comp.height} @ {comp.fps:g} fps, {comp.duration:g}s",
    )

    for layer in plan.layers:
        command, params = _layer_creation(layer, comp.width, comp.height)
        _step(steps, command, params, note=f"layer {layer.type}: {layer.name}")

        # --- ukuran layer untuk mengubah titik ternormalisasi → piksel
        if layer.type == "solid":
            layer_size = (
                float(int(round(layer.width if layer.width is not None else comp.width))),
                float(int(round(layer.height if layer.height is not None else comp.height))),
            )
        elif layer.type == "shape" and layer.size:
            layer_size = (float(layer.size[0]), float(layer.size[1]))
        else:
            layer_size = None

        # --- efek (indeks = urutan pemasangan pada layer ini, 1-based)
        for i, eff in enumerate(layer.effects, start=1):
            canonical = resolve_effect(eff.name)
            _step(
                steps,
                "effect.apply",
                {"effect": canonical, "layer": layer.name},
                note=f"{canonical} → {layer.name}",
            )
            for pid, value in eff.params.items():
                converted = effect_param_value(
                    canonical,
                    pid,
                    value,
                    layer_size=layer_size if layer.type == "solid" else None,
                    where=f"layer '{layer.name}'.effects['{canonical}']",
                )
                _step(
                    steps,
                    "prop.set",
                    {
                        "layer": layer.name,
                        "path": f"effects/#{i}/{pid}",
                        "value": converted,
                    },
                    note=f"{canonical}.{pid}",
                )

        # --- animasi properti transform
        for prop, keys in layer.animate.items():
            path = PROP_PATHS[prop]
            _validate_prop_path(path)
            if not keys:
                continue
            if len(keys) == 1:
                _step(
                    steps,
                    "prop.set",
                    {
                        "layer": layer.name,
                        "path": path,
                        "value": keys[0].value,
                        "time": round(keys[0].time, 4),
                        "timeBase": "comp",
                    },
                    note=f"{prop} @ {keys[0].time:g}s",
                )
                continue
            for key in keys:
                _step(
                    steps,
                    "prop.addKey",
                    {
                        "layer": layer.name,
                        "path": path,
                        "time": round(key.time, 4),
                        "timeBase": "comp",
                        "value": key.value,
                    },
                    note=f"{prop} key {key.time:g}s",
                )
            if layer.easing in ("easyEase", "hold"):
                _step(
                    steps,
                    "keys.select",
                    {
                        "keys": [
                            {"layer": layer.name, "path": path, "time": round(k.time, 4)}
                            for k in keys
                        ],
                        "timeBase": "comp",
                    },
                    note=f"pilih key {prop}",
                )
                if layer.easing == "easyEase":
                    _step(steps, "keys.easyEase", {"which": "both"}, note=f"ease {prop}")
                else:
                    _step(
                        steps,
                        "keys.interpolation",
                        {"interpolation": "hold"},
                        note=f"hold {prop}",
                    )

        # --- waktu layer
        timing: dict[str, Any] = {"layers": [layer.name]}
        if layer.in_time > 0:
            timing["in"] = round(layer.in_time, 4)
        if layer.out_time is not None:
            timing["out"] = round(layer.out_time, 4)
        if len(timing) > 1:
            _step(steps, "layer.timing", timing, note=f"trim {layer.name}")

    if len(steps) > 4000:
        raise TranslationError(f"rencana terlalu besar: {len(steps)} langkah (maks 4000)")

    return Translation(
        steps=steps,
        comp_name=comp.name,
        width=comp.width,
        height=comp.height,
        fps=comp.fps,
        duration=comp.duration,
        warnings=warnings,
    )


def validate_steps(commands: list[dict]) -> list[str]:
    """Validasi daftar `{command, params}` terhadap whitelist; kembalikan daftar masalah."""
    problems: list[str] = []
    for i, st in enumerate(commands):
        if not isinstance(st, dict):
            problems.append(f"step {i}: bukan objek")
            continue
        cmd = st.get("command")
        params = st.get("params", {})
        if cmd not in COMMANDS:
            problems.append(f"step {i}: command '{cmd}' tidak ada di whitelist")
            continue
        if not isinstance(params, dict):
            problems.append(f"step {i}: params harus objek")
            continue
        unknown = set(params) - COMMANDS[cmd].allowed
        if unknown:
            problems.append(f"step {i} ({cmd}): parameter tidak diizinkan {sorted(unknown)}")
    return problems


__all__ = ["Step", "Translation", "translate", "validate_steps", "COMMANDS", "EFFECTS"]
