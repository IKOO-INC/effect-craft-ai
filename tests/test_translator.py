"""Penerjemah rencana → command EffectCraft, untuk 5 prompt contoh."""

from __future__ import annotations

import json

import pytest

from conftest import FIXTURES
from ecps.errors import TranslationError
from ecps.planner.local_planner import plan_from_prompt
from ecps.planner.schema import validate_plan
from ecps.translator.translate import translate, validate_steps
from ecps.translator.whitelist import COMMANDS, EFFECTS, PROP_PATHS

PROMPTS = json.loads((FIXTURES / "prompts.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def translations():
    out = {}
    for item in PROMPTS:
        plan = validate_plan(plan_from_prompt(item["prompt"], {}))
        out[item["id"]] = translate(plan)
    return out


def test_all_five_prompts_translate(translations):
    assert len(translations) == 5
    for tr in translations.values():
        assert tr.steps, "tidak ada command"
        assert tr.steps[0].command == "comp.new"
        assert validate_steps(tr.commands_json()) == []


@pytest.mark.parametrize("name", [p["id"] for p in PROMPTS])
def test_every_command_and_param_is_whitelisted(translations, name):
    for step in translations[name].steps:
        assert step.command in COMMANDS, step.command
        unknown = set(step.params) - COMMANDS[step.command].allowed
        assert not unknown, f"{step.command}: {unknown}"


@pytest.mark.parametrize("name", [p["id"] for p in PROMPTS])
def test_comp_matches_prompt_options(translations, name):
    item = next(p for p in PROMPTS if p["id"] == name)
    tr = translations[name]
    comp = tr.steps[0].params
    assert comp["name"] == "Main"
    if name == "youtube_intro":
        assert (comp["width"], comp["height"]) == (1280, 720)
    if name == "logo_reveal":
        assert (comp["width"], comp["height"]) == (1080, 1920)
    assert comp["width"] % 2 == 0 and comp["height"] % 2 == 0
    assert comp["frameRate"] in (24, 25, 30, 50, 60)
    # Semua keyframe berada di dalam durasi komposisi.
    for step in tr.steps:
        if step.command in ("prop.set", "prop.addKey") and "time" in step.params:
            assert 0 <= step.params["time"] <= comp["duration"] + 1e-6


def test_title_prompt_has_text_and_fade(translations):
    steps = translations["title_fade_in"].steps
    texts = [s.params.get("text") for s in steps if s.command == "layer.newText"]
    assert "Selamat Datang" in texts
    opacity_keys = [
        s for s in steps if s.command == "prop.addKey" and s.params.get("path") == "transform/opacity"
    ]
    assert opacity_keys, "fade-in butuh keyframe opacity"
    assert any(s.params["value"] == 0 for s in opacity_keys)
    assert any(s.params["value"] == 100 for s in opacity_keys)
    assert all(s.params["timeBase"] == "comp" for s in opacity_keys)


def test_lower_third_has_panel_and_two_texts(translations):
    steps = translations["lower_third"].steps
    texts = [s.params.get("text") for s in steps if s.command == "layer.newText"]
    assert any("Budi Santoso" in (t or "") for t in texts)
    assert len(texts) >= 2
    assert any(s.command == "layer.newSolid" for s in steps)


def test_logo_reveal_uses_shapes_and_scale(translations):
    steps = translations["logo_reveal"].steps
    shapes = [s for s in steps if s.command == "layer.newShape"]
    assert len(shapes) >= 2
    scale_keys = [s for s in steps if s.command == "prop.addKey" and s.params["path"] == "transform/scale"]
    assert scale_keys
    assert any(s.params["value"] == [0, 0] for s in scale_keys)


def test_countdown_creates_number_layers_with_timing(translations):
    steps = translations["countdown"].steps
    texts = [s.params.get("text") for s in steps if s.command == "layer.newText"]
    numbers = [t for t in texts if t and t.isdigit()]
    assert numbers == ["3", "2", "1"]
    timings = [s for s in steps if s.command == "layer.timing"]
    assert len(timings) == 3
    for t in timings:
        assert "out" in t.params
        assert t.params.get("in", 0.0) < t.params["out"]


def test_youtube_intro_mentions_subscribe(translations):
    steps = translations["youtube_intro"].steps
    texts = " ".join(s.params.get("text", "") for s in steps if s.command == "layer.newText")
    assert "Kreator Nusantara" in texts
    assert "Subscribe" in texts or "subscribe" in texts


def test_gradient_points_are_converted_to_pixels(translations):
    steps = translations["title_fade_in"].steps
    ramp = next(s for s in steps if s.command == "effect.apply" and s.params["effect"] == "Gradient Ramp")
    assert ramp.params["layer"] == "BG"
    sets = [s for s in steps if s.command == "prop.set" and s.params["path"].startswith("effects/#1/")]
    values = {s.params["path"]: s.params["value"] for s in sets}
    assert values["effects/#1/start"] == [960.0, 0.0]
    assert values["effects/#1/end"] == [960.0, 1080.0]
    assert values["effects/#1/startColor"] == "#06122b"


def test_easing_emits_selection_then_ease(translations):
    steps = translations["title_fade_in"].steps
    select_idx = [i for i, s in enumerate(steps) if s.command == "keys.select"]
    ease_idx = [i for i, s in enumerate(steps) if s.command == "keys.easyEase"]
    assert select_idx and ease_idx
    for i in ease_idx:
        assert select_idx and min(select_idx) < i
    sel = steps[select_idx[0]].params
    assert sel["timeBase"] == "comp"
    assert all(k["time"] >= 0 for k in sel["keys"])


def test_unknown_effect_is_rejected_with_helpful_message():
    plan = validate_plan(plan_from_prompt(PROMPTS[0]["prompt"]))
    raw = plan.to_dict()
    raw["layers"][0]["effects"][0]["effect"] = "Super Fancy Effect 3000"
    with pytest.raises(TranslationError) as exc:
        translate(validate_plan(raw))
    assert "whitelist" in str(exc.value)
    assert "Gradient Ramp" in str(exc.value)


def test_invalid_color_in_effect_is_rejected():
    plan = validate_plan(plan_from_prompt(PROMPTS[0]["prompt"]))
    raw = plan.to_dict()
    raw["layers"][0]["effects"][0]["params"]["startColor"] = "biru"
    with pytest.raises(TranslationError) as exc:
        translate(validate_plan(raw))
    assert "warna" in str(exc.value).lower()


def test_unknown_effect_param_is_rejected():
    plan = validate_plan(plan_from_prompt(PROMPTS[0]["prompt"]))
    raw = plan.to_dict()
    raw["layers"][0]["effects"][0]["params"]["magic"] = 42
    with pytest.raises(TranslationError) as exc:
        translate(validate_plan(raw))
    assert "tidak didukung" in str(exc.value)


def test_effect_alias_is_resolved():
    raw = {
        "version": 1,
        "comp": {"name": "Main", "width": 640, "height": 360, "fps": 24, "duration": 1},
        "layers": [
            {
                "name": "BG",
                "type": "solid",
                "color": "#000000",
                "effects": [{"effect": "gradient", "params": {"startColor": "#000000", "endColor": "#ffffff"}}],
            }
        ],
    }
    steps = translate(validate_plan(raw)).steps
    assert any(s.params.get("effect") == "Gradient Ramp" for s in steps if s.command == "effect.apply")


def test_normalized_points_rejected_on_text_layer():
    raw = {
        "version": 1,
        "comp": {"name": "Main", "width": 640, "height": 360, "fps": 24, "duration": 1},
        "layers": [
            {
                "name": "Title",
                "type": "text",
                "text": "Halo",
                "effects": [{"effect": "Gradient Ramp", "params": {"start": [0.5, 0.0]}}],
            }
        ],
    }
    with pytest.raises(TranslationError) as exc:
        translate(validate_plan(raw))
    assert "layer solid" in str(exc.value)


def test_prop_paths_are_whitelisted():
    assert set(PROP_PATHS.values()) == {
        "transform/position",
        "transform/scale",
        "transform/rotation",
        "transform/opacity",
        "transform/anchor",
    }


def test_validate_steps_detects_outside_whitelist():
    problems = validate_steps([
        {"command": "comp.new", "params": {"name": "A"}},
        {"command": "file.deleteEverything", "params": {}},
        {"command": "prop.set", "params": {"layer": "A", "path": "x", "value": 1, "shell": "rm -rf /"}},
    ])
    assert len(problems) == 2
    assert "whitelist" in problems[0]
    assert "shell" in problems[1]
