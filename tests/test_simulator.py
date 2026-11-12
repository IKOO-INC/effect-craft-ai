"""Simulator internal: memastikan pipeline prompt→MP4 benar-benar berjalan tanpa EffectCraft."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ecps.planner.local_planner import plan_from_prompt
from ecps.planner.schema import validate_plan
from ecps.runner.base import RenderSettings
from ecps.translator.translate import translate

pytest.importorskip("PIL")
imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")

from ecps.runner.simulator import SimulationRunner, SimError  # noqa: E402


def _project(tmp_path: Path, prompt: str, **options) -> tuple[Path, Path]:
    plan = validate_plan(plan_from_prompt(prompt, {"resolution": "720p", "fps": 12, "duration": 1.2, **options}))
    runner = SimulationRunner()
    project = tmp_path / "project.ecproj"
    out = tmp_path / "render.mp4"
    result = runner.build(translate(plan).commands_json(), project)
    assert result.ok, result.error
    return project, out


def test_simulator_renders_demo_prompt_to_mp4(tmp_path: Path):
    project, out = _project(
        tmp_path,
        "Intro 5 detik, teks 'Majalah Dza Izza' muncul fade-in dengan latar gradasi biru",
        duration=1.2,
    )
    runner = SimulationRunner()
    result = runner.render(project, out, RenderSettings(comp="Main", fps=12))
    assert result.ok, result.error
    assert out.exists()
    assert out.stat().st_size > 2000
    assert result.warnings  # penanda bahwa ini simulator
    data = json.loads(project.read_text(encoding="utf-8"))
    assert data["steps"][0]["command"] == "comp.new"


def test_simulator_rerender_from_project_file(tmp_path: Path):
    """`Ekspor ulang` harus bekerja walau runner dibuat baru (state memori kosong)."""
    from ecps.pipeline import Pipeline
    from ecps.storage.projects import ProjectStore

    store = ProjectStore(tmp_path / "projects")
    pipeline = Pipeline(SimulationRunner(), store, max_attempts=1)
    result = pipeline.run("Judul 'HALO' fade-in", {"duration": 1, "resolution": "720p", "fps": 12,
                                                   "style": "minimalis"})
    assert result.ok
    again = Pipeline(SimulationRunner(), store, max_attempts=1).rerender(result.record)
    assert again.ok and again.mp4 and again.mp4.exists()


def test_simulator_reports_step_number_on_unknown_command(tmp_path: Path):
    runner = SimulationRunner()
    result = runner.build(
        [
            {"command": "comp.new", "params": {"name": "Main", "width": 320, "height": 180, "duration": 1}},
            {"command": "tool.teleport", "params": {}},
        ],
        tmp_path / "p.ecproj",
    )
    assert not result.ok
    assert result.error_step == 2
    assert "tool.teleport" in (result.error or "")


def test_simulator_rejects_bad_params(tmp_path: Path):
    runner = SimulationRunner()
    result = runner.build(
        [{"command": "comp.new", "params": {"name": "Main", "width": "besar", "height": 180, "duration": 1}}],
        tmp_path / "p.ecproj",
    )
    assert not result.ok
    assert result.error_step == 1


def test_simulator_gradient_and_text_visible(tmp_path: Path):
    from PIL import Image

    project, out = _project(
        tmp_path, "Judul 'HALO' dengan latar gradasi ungu", duration=1.0, resolution="square_1080"
    )
    SimulationRunner().render(project, out, RenderSettings(comp="Main", fps=12))
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    import subprocess

    frame = tmp_path / "frame.png"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", "0.6", "-i", str(out), "-frames:v", "1", str(frame)],
                   check=True, timeout=60)
    img = Image.open(frame).convert("RGB")
    w, h = img.size
    top = img.getpixel((10, 10))
    bottom = img.getpixel((10, h - 10))
    assert top != bottom, "gradasi tidak terlihat"
    # Ada piksel terang (teks) di sekitar tengah frame.
    middle = img.crop((0, int(h * 0.35), w, int(h * 0.65)))
    assert middle.convert("L").getextrema()[1] > 200
