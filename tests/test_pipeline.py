"""Pipeline prompt→video dengan runner dan LLM palsu (tanpa EffectCraft, tanpa jaringan)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ecps.errors import PipelineError
from ecps.pipeline import Pipeline
from ecps.planner.schema import EXAMPLE_PLAN
from ecps.runner.base import EngineResult, Preflight, RenderSettings, StepRecord
from ecps.storage.projects import ProjectStore


class FakeRunner:
    kind = "fake"
    label = "Fake Runner"
    is_simulator = False

    def __init__(self, *, fail_first: bool = False, fail_always: bool = False) -> None:
        self.calls: list[list[dict]] = []
        self.renders = 0
        self.fail_first = fail_first
        self.fail_always = fail_always

    def preflight(self) -> Preflight:
        return Preflight(available=True, detail="fake")

    def build(self, steps, project_path: Path, on_event=None) -> EngineResult:
        self.calls.append(steps)
        project_path = Path(project_path)
        project_path.parent.mkdir(parents=True, exist_ok=True)
        if self.fail_always or (self.fail_first and len(self.calls) == 1):
            return EngineResult(
                ok=False,
                steps=[StepRecord(command=steps[-1]["command"], params=steps[-1]["params"], ok=False,
                                  error="unknown effect `X`")],
                error="unknown effect `X` (step 3)",
                error_step=3,
                error_command=steps[3]["command"] if len(steps) > 3 else steps[-1]["command"],
            )
        project_path.write_text(json.dumps({"steps": steps}), encoding="utf-8")
        return EngineResult(ok=True, steps=[StepRecord(command=s["command"], params=s["params"]) for s in steps])

    def render(self, project_path, out_path, settings: RenderSettings, on_event=None) -> EngineResult:
        self.renders += 1
        Path(out_path).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 512)
        return EngineResult(ok=True)

    def close(self) -> None:
        return None


class FakeLlm:
    """Mengembalikan rencana rusak dulu, lalu rencana valid."""

    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        return copy.deepcopy(self.responses[min(len(self.calls) - 1, len(self.responses) - 1)])


def _bad_plan() -> dict:
    plan = copy.deepcopy(EXAMPLE_PLAN)
    plan["layers"][0]["effects"][0]["effect"] = "Super Fancy Effect 3000"
    return plan


def _good_plan() -> dict:
    return copy.deepcopy(EXAMPLE_PLAN)


def test_llm_failure_is_repaired_and_pipeline_succeeds(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    runner = FakeRunner()
    llm = FakeLlm([_bad_plan(), _good_plan()])
    events: list[tuple[str, str]] = []
    pipeline = Pipeline(runner, store, llm_client=llm, max_attempts=3,
                        on_event=lambda k, m, d=None: events.append((k, m)))
    result = pipeline.run("Intro 5 detik teks 'Halo'", {"duration": 5, "resolution": "1080p", "fps": 30,
                                                         "style": "minimalis"})
    assert result.ok
    assert result.attempts == 2
    assert len(llm.calls) == 2
    assert "Super Fancy Effect 3000" in llm.calls[1][1]  # error dikirim ke LLM
    assert result.mp4 and result.mp4.exists()
    assert (result.record.path / "plan.json").exists()
    assert (result.record.path / "steps.json").exists()
    assert any(k == "error" for k, _ in events)


def test_runner_failure_is_reported_to_llm_and_retried(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    runner = FakeRunner(fail_first=True)
    llm = FakeLlm([_good_plan(), _good_plan()])
    pipeline = Pipeline(runner, store, llm_client=llm, max_attempts=3)
    result = pipeline.run("Judul sederhana", {"duration": 5, "resolution": "720p", "fps": 24, "style": "neon"})
    assert result.ok
    assert result.attempts == 2
    assert len(runner.calls) == 2
    assert "unknown effect" in llm.calls[1][1]


def test_pipeline_gives_up_after_max_attempts(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    runner = FakeRunner(fail_always=True)
    llm = FakeLlm([_good_plan()])
    pipeline = Pipeline(runner, store, llm_client=llm, max_attempts=3)
    with pytest.raises(PipelineError) as exc:
        pipeline.run("Apa saja", {"duration": 4, "resolution": "1080p", "fps": 30, "style": "minimalis"})
    assert exc.value.attempts == 3
    assert len(runner.calls) == 3
    records = store.list()
    assert records and records[0].status == "gagal"


def test_pipeline_without_llm_uses_local_planner(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    runner = FakeRunner()
    pipeline = Pipeline(runner, store, llm_client=None, max_attempts=3)
    result = pipeline.run("Intro 5 detik, teks 'Majalah Dza Izza' muncul fade-in dengan latar gradasi biru",
                          {"duration": 5, "resolution": "1080p", "fps": 30, "style": "minimalis"})
    assert result.ok
    assert result.attempts == 1
    commands = [s["command"] for s in runner.calls[0]]
    assert commands[0] == "comp.new"
    assert "layer.newText" in commands
    assert any(s["params"].get("text") == "Majalah Dza Izza" for s in runner.calls[0]
               if s["command"] == "layer.newText")


def test_run_from_plan_skips_llm(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    runner = FakeRunner()
    llm = FakeLlm([_good_plan()])
    pipeline = Pipeline(runner, store, llm_client=llm, max_attempts=1)
    record = store.create(title="manual", prompt="manual")
    result = pipeline.run_from_plan(_good_plan(), record)
    assert result.ok
    assert llm.calls == []
    assert result.mp4 and result.mp4.exists()


def test_rerender_uses_existing_project(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    runner = FakeRunner()
    pipeline = Pipeline(runner, store, max_attempts=1)
    result = pipeline.run("Judul", {"duration": 3, "resolution": "1080p", "fps": 30, "style": "minimalis"})
    again = pipeline.rerender(result.record)
    assert runner.renders == 2
    assert again.mp4 and again.mp4.exists()
