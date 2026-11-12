"""Deteksi koneksi & keamanan eksekusi proses."""

from __future__ import annotations

import inspect
from pathlib import Path

from ecps.config import Settings
from ecps.runner.detect import build_runner, detect
from ecps.runner.docker import DockerRunner
from ecps.runner.local import LocalCliRunner
from ecps.runner.simulator import SimulationRunner


def test_explicit_modes_build_expected_runner(tmp_path: Path):
    settings = Settings()
    settings.connection = "local"
    settings.cli_path = str(tmp_path / "effectcraft-cli")
    assert isinstance(build_runner(settings), LocalCliRunner)
    settings.connection = "docker"
    assert isinstance(build_runner(settings), DockerRunner)
    settings.connection = "simulator"
    assert isinstance(build_runner(settings), SimulationRunner)


def _no_tools(monkeypatch):
    """Tidak ada CLI di PATH dan tidak ada Docker (keduanya memakai shutil.which)."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)


def test_auto_falls_back_to_simulator_when_nothing_installed(monkeypatch):
    _no_tools(monkeypatch)
    settings = Settings()
    settings.connection = "auto"
    settings.cli_path = "/tidak/ada/effectcraft-cli"
    detection = detect(settings)
    assert detection.runner.kind == "simulator"
    assert detection.degraded
    assert "simulator" in detection.notice.lower()
    assert detection.candidates  # kandidat lain tetap dilaporkan


def test_auto_prefers_local_cli_when_present(monkeypatch, tmp_path: Path):
    fake = tmp_path / "effectcraft-cli"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    _no_tools(monkeypatch)
    settings = Settings()
    settings.connection = "auto"
    settings.cli_path = str(fake)
    detection = detect(settings)
    assert detection.runner.kind == "local"
    assert not detection.degraded


def test_no_shell_true_anywhere_in_runners():
    root = Path(__file__).resolve().parents[1] / "src" / "ecps"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "shell=True" in text:
            offenders.append(path.name)
    assert not offenders, offenders


def test_process_runner_uses_list_argv():
    from ecps.runner.process import run_command

    source = inspect.getsource(run_command)
    assert "Popen(" in source or "run(" in source
    assert "shell=True" not in source
