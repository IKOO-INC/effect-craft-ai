"""Deteksi mode koneksi otomatis (dan daftar kandidat untuk halaman Settings)."""

from __future__ import annotations

import socket
from dataclasses import dataclass

from ..config import Settings
from .base import Preflight, Runner
from .docker import DockerRunner
from .local import LocalCliRunner


@dataclass
class Candidate:
    runner: Runner
    preflight: Preflight


@dataclass
class Detection:
    runner: Runner
    notice: str
    candidates: list[Candidate]
    degraded: bool = False  # True bila yang dipakai simulator


def build_runner(settings: Settings) -> Runner:
    """Runner sesuai pilihan eksplisit di Settings (tanpa fallback)."""
    if settings.connection == "simulator":
        return _simulator()
    if settings.connection == "local":
        return LocalCliRunner(settings.cli_path)
    if settings.connection == "docker":
        return DockerRunner(settings.docker_image, settings.docker_container)
    if settings.connection == "live":
        from .control import LiveRunner

        delegate = LocalCliRunner(settings.cli_path)
        if delegate.path is None:
            delegate = DockerRunner(settings.docker_image, settings.docker_container)  # type: ignore[assignment]
        return LiveRunner(settings.control_host, settings.control_port, render_runner=delegate)
    raise ValueError(f"mode koneksi tidak dikenal: {settings.connection}")


def _simulator() -> Runner:
    from .simulator import SimulationRunner

    return SimulationRunner()


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def detect(settings: Settings) -> Detection:
    """Pilih runner terbaik yang tersedia dan jelaskan pilihannya."""
    if settings.connection != "auto":
        runner = build_runner(settings)
        pf = runner.preflight()
        notice = f"Mode {settings.connection}: {pf.detail}"
        if not pf.available:
            notice += (" — " + pf.hint) if pf.hint else ""
        return Detection(
            runner=runner,
            notice=notice,
            candidates=[Candidate(runner, pf)],
            degraded=runner.is_simulator,
        )

    candidates: list[Candidate] = []
    local = LocalCliRunner(settings.cli_path)
    candidates.append(Candidate(local, local.preflight()))
    docker = DockerRunner(settings.docker_image, settings.docker_container)
    candidates.append(Candidate(docker, docker.preflight()))
    sim = _simulator()
    candidates.append(Candidate(sim, sim.preflight()))

    if candidates[0].preflight.available:
        return Detection(local, "Mode Lokal terdeteksi: " + candidates[0].preflight.detail, candidates)
    if candidates[1].preflight.available:
        return Detection(docker, "Mode Docker terdeteksi: " + candidates[1].preflight.detail, candidates)
    if _port_open(settings.control_host, settings.control_port):
        from .control import LiveRunner

        live = LiveRunner(settings.control_host, settings.control_port, render_runner=local if local.path else docker)
        pf = live.preflight()
        if pf.available:
            candidates.append(Candidate(live, pf))
            return Detection(live, "Control channel terdeteksi: " + pf.detail, candidates)

    if candidates[2].preflight.available:
        reasons = " | ".join(f"{c.runner.label}: {c.preflight.detail}" for c in candidates[:2])
        return Detection(
            sim,
            "EffectCraft tidak ditemukan — memakai SIMULATOR internal. Hasil bukan rendering EffectCraft. "
            f"({reasons})",
            candidates,
            degraded=True,
        )

    return Detection(
        local,
        "Tidak ada jalur eksekusi yang tersedia. Pasang EffectCraft, Docker, atau dependensi simulator "
        "(pip install pillow imageio-ffmpeg).",
        candidates,
        degraded=False,
    )
