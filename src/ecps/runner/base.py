"""Kontrak runner: apa pun yang bisa menjalankan urutan command EffectCraft lalu me-render."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from ..errors import RunnerError

#: Callback log: `event(kind, message, data=None)`.
EventFn = Callable[[str, str, dict | None], None]


@dataclass
class StepRecord:
    command: str
    params: dict
    ok: bool = True
    result: Any = None
    error: str | None = None
    seconds: float = 0.0

    def to_json(self) -> dict:
        out = {
            "command": self.command,
            "params": self.params,
            "ok": self.ok,
            "seconds": round(self.seconds, 3),
        }
        if self.ok:
            out["result"] = self.result
        else:
            out["error"] = self.error
        return out


@dataclass
class EngineResult:
    ok: bool
    steps: list[StepRecord] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    error_step: int | None = None
    error_command: str | None = None
    seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "ok": self.ok,
            "error": self.error,
            "errorStep": self.error_step,
            "errorCommand": self.error_command,
            "seconds": round(self.seconds, 3),
            "steps": [s.to_json() for s in self.steps],
        }


@dataclass
class Preflight:
    available: bool
    detail: str
    hint: str = ""
    version: str | None = None


@dataclass
class RenderSettings:
    comp: str = "Main"
    fps: float = 30.0
    width: int = 1920
    height: int = 1080
    format: str = "h264"


class Runner(Protocol):
    """Antarmuka yang dipakai pipeline."""

    kind: str
    label: str
    is_simulator: bool

    def preflight(self) -> Preflight: ...

    def build(self, steps: list[dict], project_path: Path, on_event: EventFn | None = None) -> EngineResult: ...

    def render(
        self,
        project_path: Path,
        out_path: Path,
        settings: RenderSettings,
        on_event: EventFn | None = None,
    ) -> EngineResult: ...

    def close(self) -> None: ...


class Timer:
    def __enter__(self) -> "Timer":
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *exc: object) -> None:
        self.seconds = time.monotonic() - self.t0


def emit(on_event: EventFn | None, kind: str, message: str, data: dict | None = None) -> None:
    if on_event is not None:
        try:
            on_event(kind, message, data)
        except Exception:  # noqa: BLE001 - log tidak boleh mematikan pipeline
            pass


def fail(message: str, *, hint: str | None = None) -> RunnerError:
    return RunnerError(message, hint=hint)
