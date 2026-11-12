"""Mode Lokal: memanggil `effectcraft-cli` / `effectcraft` di mesin pengguna."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from ..errors import RunnerError
from .base import EngineResult, EventFn, Preflight, RenderSettings, StepRecord, Timer, emit
from .process import run_command

CLI_NAMES = ("effectcraft-cli.exe", "effectcraft-cli", "effectcraft.exe", "effectcraft")
_STEP_RE = re.compile(r"\(step (\d+)\)")


def candidate_paths(explicit: str = "") -> list[Path]:
    """Tempat-tempat wajar untuk mencari binary EffectCraft."""
    out: list[Path] = []
    if explicit:
        p = Path(explicit).expanduser()
        out.append(p)
    env = os.environ.get("ECPS_EFFECTCRAFT_CLI") or os.environ.get("EFFECTCRAFT_CLI")
    if env:
        out.append(Path(env))
    for name in CLI_NAMES:
        found = shutil.which(name)
        if found:
            out.append(Path(found))
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        roots = [
            Path(local) / "Programs" / "ArtCraft" / "EffectCraft",
            Path("C:/Program Files/ArtCraft/EffectCraft"),
            Path("C:/Program Files (x86)/ArtCraft/EffectCraft"),
        ]
        for root in roots:
            for name in CLI_NAMES:
                out.append(root / name)
    else:
        out += [Path("/usr/bin/effectcraft-cli"), Path("/usr/local/bin/effectcraft-cli"), Path("/opt/effectcraft/effectcraft-cli")]
    here = Path(__file__).resolve()
    for parent in here.parents:
        for name in CLI_NAMES:
            out.append(parent / name)
            out.append(parent / "bin" / name)
            out.append(parent / "tools" / name)
            out.append(parent / "target" / "release" / name)
    return out


def find_cli(explicit: str = "") -> Path | None:
    for p in candidate_paths(explicit):
        try:
            if p.is_file() and os.access(p, os.X_OK):
                return p.resolve()
        except OSError:
            continue
    return None


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start >= 0:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            return None
    return None


def _error_text(stdout: str, stderr: str) -> str:
    data = _extract_json(stdout)
    if isinstance(data, dict) and data.get("error"):
        return str(data["error"])
    tail = (stderr or stdout or "").strip().splitlines()
    return tail[-1] if tail else "tidak ada keluaran"


class LocalCliRunner:
    kind = "local"
    is_simulator = False

    def __init__(self, cli_path: str = "", *, build_timeout: float = 180.0, render_timeout: float = 3600.0) -> None:
        self.configured = cli_path
        self.path = find_cli(cli_path)
        self.build_timeout = build_timeout
        self.render_timeout = render_timeout
        self.label = "Lokal (effectcraft-cli)"

    # ------------------------------------------------------------------ info
    def preflight(self) -> Preflight:
        if self.path is None:
            return Preflight(
                available=False,
                detail="effectcraft-cli tidak ditemukan.",
                hint=(
                    "Pasang EffectCraft dari https://github.com/storytold/effectcraft/releases "
                    "(installer Windows menyertakan effectcraft-cli.exe), atau bangun sendiri dengan "
                    "`cargo build --release -p effectcraft-cli`, lalu isi path binary di Settings. "
                    "Anda juga bisa mengatur variabel lingkungan ECPS_EFFECTCRAFT_CLI."
                ),
            )
        argv = [str(self.path), "info", "--empty", "--json"]
        res = run_command(argv, timeout=60)
        if not res.ok:
            return Preflight(
                available=False,
                detail=f"`{self.path.name} info` gagal: {_error_text(res.stdout, res.stderr)}",
                hint="Pastikan binary bisa dijalankan dan bukan versi yang terlalu lama.",
            )
        data = _extract_json(res.stdout) or {}
        version = str(data.get("version") or "?")
        return Preflight(
            available=True,
            detail=f"{self.path} — EffectCraft {version}, {data.get('commands', '?')} command, {data.get('effects', '?')} efek",
            version=version,
        )

    # ----------------------------------------------------------------- jalankan
    def build(self, steps: list[dict], project_path: Path, on_event: EventFn | None = None) -> EngineResult:
        if self.path is None:
            raise RunnerError("effectcraft-cli tidak ditemukan", hint="Isi path CLI di Settings.")
        project_path = Path(project_path)
        project_path.parent.mkdir(parents=True, exist_ok=True)
        steps_file = project_path.with_name("steps.json")
        steps_file.write_text(json.dumps(steps, indent=2, ensure_ascii=False), encoding="utf-8")

        argv = [
            str(self.path),
            "run",
            "--commands",
            str(steps_file),
            "--empty",
            "--save-as",
            str(project_path),
            "--json",
        ]
        emit(on_event, "command", "$ " + " ".join(argv))
        with Timer() as t:
            res = run_command(
                argv,
                timeout=self.build_timeout,
                on_line=lambda stream, line: emit(on_event, f"cli-{stream}", line),
            )
        if res.timed_out:
            raise RunnerError(
                f"effectcraft-cli run melebihi {self.build_timeout:.0f} detik",
                hint="Naikkan timeout atau sederhanakan rencana.",
                stderr=res.stderr,
            )
        data = _extract_json(res.stdout)
        records: list[StepRecord] = []
        if isinstance(data, list):
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                cmd = str(item.get("command") or "")
                params = steps[i].get("params", {}) if i < len(steps) else {}
                records.append(StepRecord(command=cmd, params=params, ok=True, result=item.get("result")))

        if res.returncode != 0:
            message = _error_text(res.stdout, res.stderr)
            m = _STEP_RE.search(message)
            step_idx = int(m.group(1)) if m else None
            if step_idx is not None and 0 <= step_idx < len(steps):
                cmd = steps[step_idx]["command"]
                for i in range(len(records), step_idx):
                    records.append(StepRecord(command=steps[i]["command"], params=steps[i].get("params", {})))
                rec = StepRecord(command=cmd, params=steps[step_idx].get("params", {}), ok=False, error=message)
                records.append(rec)
                return EngineResult(
                    ok=False,
                    steps=records,
                    stdout=res.stdout,
                    stderr=res.stderr,
                    error=message,
                    error_step=step_idx,
                    error_command=cmd,
                    seconds=t.seconds,
                )
            return EngineResult(
                ok=False,
                steps=records,
                stdout=res.stdout,
                stderr=res.stderr,
                error=message,
                seconds=t.seconds,
            )

        if not project_path.exists() or project_path.stat().st_size == 0:
            return EngineResult(
                ok=False,
                steps=records,
                stdout=res.stdout,
                stderr=res.stderr,
                error=f"file proyek tidak terbentuk: {project_path}",
                seconds=t.seconds,
            )
        return EngineResult(ok=True, steps=records, stdout=res.stdout, stderr=res.stderr, seconds=t.seconds)

    def render(
        self,
        project_path: Path,
        out_path: Path,
        settings: RenderSettings,
        on_event: EventFn | None = None,
    ) -> EngineResult:
        if self.path is None:
            raise RunnerError("effectcraft-cli tidak ditemukan", hint="Isi path CLI di Settings.")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            out_path.unlink()
        argv = [
            str(self.path),
            "render",
            str(project_path),
            "--comp",
            settings.comp,
            "--out",
            str(out_path),
            "--format",
            settings.format,
            "--fps",
            str(settings.fps),
            "--resolution",
            "full",
            "--quality",
            "best",
            "--progress",
            "--json",
        ]
        emit(on_event, "command", "$ " + " ".join(argv))

        def line(stream: str, text: str) -> None:
            if text.startswith("progress "):
                emit(on_event, "progress", text, {"raw": text})
            else:
                emit(on_event, f"cli-{stream}", text)

        with Timer() as t:
            res = run_command(argv, timeout=self.render_timeout, on_line=line)
        if res.timed_out:
            raise RunnerError(
                f"render melebihi {self.render_timeout:.0f} detik",
                hint="Kurangi durasi/resolusi, atau naikkan render_timeout.",
                stderr=res.stderr,
            )
        if res.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            return EngineResult(
                ok=False,
                stdout=res.stdout,
                stderr=res.stderr,
                error=_error_text(res.stdout, res.stderr),
                seconds=t.seconds,
            )
        return EngineResult(ok=True, stdout=res.stdout, stderr=res.stderr, seconds=t.seconds)

    def close(self) -> None:  # pragma: no cover - tidak ada resource yang perlu ditutup
        return None
