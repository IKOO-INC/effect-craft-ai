"""Mode Docker: menjalankan EffectCraft di dalam container, folder proyek di-mount ke /work.

Dua cara pakai:

* **satu-kali** (default): `docker run --rm -v <proj>:/work -w /work <image> effectcraft-cli …`
  Setiap command memulai container baru — sederhana dan tidak menyisakan state.
* **container tetap** (opsional): `docker exec -w <workdir> <container> effectcraft-cli …`
  untuk container jangka panjang yang sudah me-mount folder proyek.

Tidak ada shell yang dipakai: argumen dikirim langsung ke executable docker.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import RunnerError
from .base import EngineResult, EventFn, Preflight, RenderSettings, StepRecord, Timer, emit
from .local import _extract_json, _error_text
from .process import run_command

WORKDIR = "/work"


class DockerRunner:
    kind = "docker"
    is_simulator = False
    label = "Docker"

    def __init__(
        self,
        image: str = "ghcr.io/storytold/effectcraft:latest",
        container: str = "",
        *,
        cli_in_image: str = "effectcraft-cli",
        build_timeout: float = 300.0,
        render_timeout: float = 3600.0,
    ) -> None:
        self.image = image or "ghcr.io/storytold/effectcraft:latest"
        self.container = container or ""
        self.cli_in_image = cli_in_image
        self.build_timeout = build_timeout
        self.render_timeout = render_timeout

    # ------------------------------------------------------------------ cek
    def _docker_path(self) -> str | None:
        import shutil

        return shutil.which("docker") or shutil.which("docker.exe")

    def preflight(self) -> Preflight:
        docker = self._docker_path()
        if not docker:
            return Preflight(
                available=False,
                detail="Docker tidak ditemukan di PATH.",
                hint="Pasang Docker Desktop (https://www.docker.com/products/docker-desktop/) lalu jalankan kembali.",
            )
        ver = run_command([docker, "version", "--format", "{{.Server.Version}}"], timeout=30)
        if not ver.ok:
            return Preflight(
                available=False,
                detail="Docker terpasang tetapi daemon tidak menjawab.",
                hint="Jalankan Docker Desktop dan tunggu sampai status 'running'. "
                f"Pesan: {_error_text(ver.stdout, ver.stderr)}",
            )
        if self.container:
            inspect = run_command([docker, "inspect", "--format", "{{.State.Running}}", self.container], timeout=30)
            if not inspect.ok or inspect.stdout.strip() != "true":
                return Preflight(
                    available=False,
                    detail=f"container '{self.container}' tidak berjalan.",
                    hint="Jalankan container itu atau kosongkan nama container di Settings.",
                )
            return Preflight(available=True, detail=f"Docker {ver.stdout.strip()} — exec ke container '{self.container}'")
        img = run_command([docker, "image", "inspect", "--format", "{{.Id}}", self.image], timeout=30)
        if not img.ok:
            return Preflight(
                available=False,
                detail=f"image '{self.image}' tidak ada secara lokal.",
                hint=(
                    f"Jalankan `docker pull {self.image}`. Bila image itu tidak tersedia, bangun image lokal "
                    "dengan `docker build -t effectcraft:local docker/` dari folder repo ini lalu isi nama image "
                    "di Settings."
                ),
            )
        return Preflight(available=True, detail=f"Docker {ver.stdout.strip()} — image {self.image}")

    # --------------------------------------------------------------- eksekusi
    def _argv(self, project_dir: Path, cli_args: list[str]) -> list[str]:
        docker = self._docker_path()
        if not docker:
            raise RunnerError("Docker tidak ditemukan", hint="Pasang Docker Desktop lalu coba lagi.")
        if self.container:
            return [docker, "exec", "-w", WORKDIR, self.container, self.cli_in_image, *cli_args]
        return [
            docker,
            "run",
            "--rm",
            "-v",
            f"{project_dir.resolve()}:{WORKDIR}",
            "-w",
            WORKDIR,
            self.image,
            self.cli_in_image,
            *cli_args,
        ]

    def build(self, steps: list[dict], project_path: Path, on_event: EventFn | None = None) -> EngineResult:
        import json

        project_path = Path(project_path)
        project_dir = project_path.parent
        project_dir.mkdir(parents=True, exist_ok=True)
        steps_file = project_path.with_name("steps.json")
        steps_file.write_text(json.dumps(steps, indent=2, ensure_ascii=False), encoding="utf-8")

        argv = self._argv(
            project_dir,
            [
                "run",
                "--commands",
                steps_file.name,
                "--empty",
                "--save-as",
                project_path.name,
                "--json",
            ],
        )
        emit(on_event, "command", "$ " + " ".join(argv))
        with Timer() as t:
            res = run_command(
                argv,
                timeout=self.build_timeout,
                on_line=lambda stream, line: emit(on_event, f"docker-{stream}", line),
            )
        if res.timed_out:
            raise RunnerError(
                f"docker run melebihi {self.build_timeout:.0f} detik",
                hint="Periksa kesehatan Docker, atau naikkan timeout.",
                stderr=res.stderr,
            )
        data = _extract_json(res.stdout)
        records: list[StepRecord] = []
        if isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, dict):
                    params = steps[i].get("params", {}) if i < len(steps) else {}
                    records.append(StepRecord(command=str(item.get("command") or ""), params=params, result=item.get("result")))
        if res.returncode != 0:
            message = _error_text(res.stdout, res.stderr)
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
                error=f"file proyek tidak muncul di folder host: {project_path}",
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
        project_path = Path(project_path)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            out_path.unlink()
        argv = self._argv(
            project_path.parent,
            [
                "render",
                project_path.name,
                "--comp",
                settings.comp,
                "--out",
                out_path.name,
                "--format",
                settings.format,
                "--fps",
                str(settings.fps),
                "--resolution",
                "full",
                "--progress",
                "--json",
            ],
        )
        emit(on_event, "command", "$ " + " ".join(argv))
        with Timer() as t:
            res = run_command(
                argv,
                timeout=self.render_timeout,
                on_line=lambda stream, line: emit(on_event, "progress" if line.startswith("progress ") else f"docker-{stream}", line),
            )
        if res.timed_out:
            raise RunnerError(
                f"render Docker melebihi {self.render_timeout:.0f} detik",
                hint="Kurangi durasi/resolusi atau naikkan timeout.",
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

    def close(self) -> None:  # pragma: no cover
        return None
