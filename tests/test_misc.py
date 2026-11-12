"""Whitelist, planner lokal, kredensial, storage, dan sanitasi."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ecps.errors import CredentialError, TranslationError
from ecps.planner.local_planner import (
    detect_duration,
    detect_kind,
    detect_resolution,
    detect_style,
    extract_subject,
    plan_from_prompt,
)
from ecps.planner.schema import validate_plan
from ecps.security.credentials import CredentialStore, InMemoryBackend, redact, target_name
from ecps.security.sanitize import ensure_within, safe_color, safe_filename, safe_layer_name, safe_text
from ecps.storage.projects import ProjectStore
from ecps.translator.whitelist import (
    COMMANDS,
    EFFECTS,
    effect_param_value,
    effects_doc,
    resolve_effect,
)
from conftest import FIXTURES


# ------------------------------------------------------------------ whitelist
def test_every_effect_has_params_and_doc():
    assert len(EFFECTS) >= 15
    doc = effects_doc()
    for name in EFFECTS:
        assert name in doc
        assert EFFECTS[name]["id"].startswith("ec.")


def test_command_table_documents_params():
    for cmd, spec in COMMANDS.items():
        assert spec.params_doc
        assert spec.allowed, cmd
        assert spec.source


def test_resolve_effect_aliases():
    assert resolve_effect("glow") == "Glow"
    assert resolve_effect("GRADIENT") == "Gradient Ramp"
    assert resolve_effect("Gaussian Blur") == "Gaussian Blur"
    assert resolve_effect("drop shadow") == "Drop Shadow"
    with pytest.raises(TranslationError):
        resolve_effect("Quantum Teleport")


def test_effect_param_value_normalizes():
    assert effect_param_value("Gradient Ramp", "start", [0.5, 0.0], layer_size=(1920, 1080)) == [960.0, 0.0]
    assert effect_param_value("Tint", "black", "#FFFFFF", layer_size=None) == "#ffffff"
    assert effect_param_value("Glow", "based", "color channels", layer_size=None) == 1
    assert effect_param_value("Glow", "based", 0, layer_size=None) == 0
    with pytest.raises(TranslationError):
        effect_param_value("Glow", "based", "kucing", layer_size=None)
    with pytest.raises(TranslationError):
        effect_param_value("Gaussian Blur", "blurriness", 5000, layer_size=None)
    with pytest.raises(TranslationError):
        effect_param_value("Gradient Ramp", "start", [0.5, 0.5], layer_size=None)


# -------------------------------------------------------------- planner lokal
def test_extract_subject_prefers_quotes():
    assert extract_subject("Intro 5 detik, teks 'Majalah Dza Izza' fade-in") == "Majalah Dza Izza"
    assert extract_subject('Judul "Hello World" dengan latar biru') == "Hello World"
    assert extract_subject("teks: Selamat Pagi, dengan latar gelap") == "Selamat Pagi"


def test_detect_helpers():
    assert detect_duration("durasi 8 detik", 5) == 8
    assert detect_duration("10s intro", 5) == 10
    assert detect_duration("tanpa durasi", 5) == 5
    assert detect_style("gaya neon terang", "minimalis") == "neon"
    assert detect_resolution("format vertikal 9:16", "1080p") == "vertical_1080x1920"
    assert detect_resolution("720p", "1080p") == "720p"
    assert detect_kind("lower third nama") == "lower_third"
    assert detect_kind("hitung mundur 3") == "countdown"
    assert detect_kind("logo reveal") == "logo_reveal"
    assert detect_kind("intro youtube") == "youtube_intro"
    assert detect_kind("teks judul biasa") == "title"


def test_local_planner_honours_options():
    plan = validate_plan(
        plan_from_prompt(
            "Intro teks 'Halo Dunia'",
            {"duration": 7.5, "resolution": "vertical_1080x1920", "fps": 25, "style": "neon"},
        )
    )
    assert plan.comp.duration == 7.5
    assert (plan.comp.width, plan.comp.height) == (1080, 1920)
    assert plan.comp.fps == 25
    assert plan.style == "neon"


def test_demo_prompt_uses_blue_gradient():
    plan = validate_plan(plan_from_prompt(
        "Intro 5 detik, teks 'Majalah Dza Izza' muncul fade-in dengan latar gradasi biru", {}))
    bg = plan.layers[0]
    assert bg.type == "solid"
    assert bg.effects[0].name == "Gradient Ramp"
    assert bg.effects[0].params["startColor"].startswith("#06122b")
    assert any(l.text == "Majalah Dza Izza" for l in plan.layers)


def test_all_fixture_prompts_produce_valid_plans():
    prompts = json.loads((FIXTURES / "prompts.json").read_text(encoding="utf-8"))
    for item in prompts:
        validate_plan(plan_from_prompt(item["prompt"], {}))


# --------------------------------------------------------------- kredensial
def test_credential_store_roundtrip_and_redaction():
    backend = InMemoryBackend()
    store = CredentialStore(backend)
    assert store.get_api_key("openai") is None
    store.set_api_key("openai", "sk-test-123456789")
    assert store.get_api_key("openai") == "sk-test-123456789"
    assert target_name("openai") in backend.data
    assert redact("sk-test-123456789") == "…6789"
    assert redact(None) == "(kosong)"
    store.delete_api_key("openai")
    assert store.get_api_key("openai") is None


def test_credential_empty_value_deletes():
    backend = InMemoryBackend()
    store = CredentialStore(backend)
    store.set_api_key("anthropic", "key")
    store.set_api_key("anthropic", "")
    assert not store.has_api_key("anthropic")


def test_credential_backend_errors_are_wrapped():
    class Broken(InMemoryBackend):
        def read(self, target):
            raise CredentialError("rusak")

    store = CredentialStore(Broken())
    assert store.get_api_key("openai") is None


# ----------------------------------------------------------------- sanitasi
def test_sanitizers():
    assert safe_color("AABBCC") == "#aabbcc"
    assert safe_color("#00ff00") == "#00ff00"
    with pytest.raises(TranslationError):
        safe_color("#12345")
    assert safe_layer_name("Judul / Utama!") == "Judul Utama"
    assert safe_layer_name("  ") == "Layer"
    assert safe_filename("Intro: 5 detik?!") == "Intro-5-detik"
    assert safe_text("  Halo\nDunia  ") == "Halo\nDunia"
    with pytest.raises(TranslationError):
        safe_text("x" * 600)
    with pytest.raises(TranslationError):
        safe_text("bad\x00null")


def test_ensure_within_blocks_traversal(tmp_path: Path):
    base = tmp_path / "root"
    base.mkdir()
    assert ensure_within(base, base / "a.json") == (base / "a.json").resolve()
    with pytest.raises(ValueError):
        ensure_within(base, tmp_path / "outside.json")


# ------------------------------------------------------------------ storage
def test_project_store_create_list_get(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    rec = store.create(title="Intro 5 detik Majalah Dza Izza", prompt="Intro ...")
    assert rec.path.exists()
    assert (rec.path / "prompt.txt").read_text(encoding="utf-8").startswith("Intro")
    store.write_json(rec, "plan.json", {"version": 1})
    rec.status = "selesai"
    store.save(rec)

    listed = store.list()
    assert len(listed) == 1
    assert listed[0].id == rec.id
    loaded = store.get(rec.id)
    assert loaded and loaded.title.startswith("Intro")
    assert store.read_json(loaded.path / "plan.json") == {"version": 1}
    assert (tmp_path / "projects" / "index.json").exists()


def test_project_store_unique_folders(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    a = store.create(title="sama", prompt="p")
    b = store.create(title="sama", prompt="p")
    assert a.id != b.id
