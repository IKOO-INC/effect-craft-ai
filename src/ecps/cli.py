"""Mode headless: prompt → MP4 tanpa membuka jendela (dipakai skrip demo/CI).

Contoh:
    python -m ecps --prompt "Intro 5 detik ..." --mode simulator --out demo.mp4
    python -m ecps --prompt "..." --mode local --duration 6 --resolution vertical_1080x1920
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .config import RESOLUTIONS, STYLES, Settings, SettingsStore
from .errors import EcpsError
from .llm.client import LlmClient, LlmConfig
from .pipeline import Pipeline, PipelineError
from .runner.detect import build_runner, detect
from .security.credentials import CredentialStore
from .storage.projects import ProjectStore


def _event(kind: str, message: str, data: dict | None = None) -> None:
    if kind in ("command", "error", "warning", "info", "done", "llm", "petunjuk"):
        print(f"[{kind}] {message}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ecps", description="EffectCraft Prompt Studio (headless)")
    p.add_argument("--prompt", help="prompt yang ingin dibuat videonya")
    p.add_argument("--out", help="salin hasil MP4 ke path ini")
    p.add_argument("--duration", type=float, default=None)
    p.add_argument("--resolution", choices=list(RESOLUTIONS), default=None)
    p.add_argument("--fps", type=int, default=None)
    p.add_argument("--style", choices=STYLES, default=None)
    p.add_argument("--mode", choices=["auto", "local", "docker", "live", "simulator"], default=None)
    p.add_argument("--cli-path", default=None, help="path effectcraft-cli (mode local)")
    p.add_argument("--docker-image", default=None)
    p.add_argument("--no-llm", action="store_true", help="pakai planner lokal")
    p.add_argument("--provider", choices=["openai", "anthropic"], default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--projects-dir", default=None)
    p.add_argument("--json", action="store_true", help="cetak ringkasan JSON")
    p.add_argument("--detect", action="store_true", help="hanya deteksi koneksi lalu keluar")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = SettingsStore()
    settings: Settings = store.load()
    if args.mode:
        settings.connection = args.mode
    if args.cli_path:
        settings.cli_path = args.cli_path
    if args.docker_image:
        settings.docker_image = args.docker_image
    if args.projects_dir:
        settings.projects_dir = args.projects_dir
    if args.provider:
        settings.llm_provider = args.provider
    if args.model:
        settings.llm_model = args.model
    settings.sanitize()

    if args.detect:
        detection = detect(settings)
        payload = {
            "chosen": detection.runner.label,
            "kind": detection.runner.kind,
            "notice": detection.notice,
            "candidates": [
                {"label": c.runner.label, "available": c.preflight.available, "detail": c.preflight.detail}
                for c in detection.candidates
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if not args.prompt:
        build_parser().print_help()
        return 2

    if settings.connection == "auto":
        detection = detect(settings)
        runner = detection.runner
        _event("info", detection.notice)
    else:
        runner = build_runner(settings)
        pf = runner.preflight()
        _event("info", f"{runner.label}: {pf.detail}")
        if not pf.available:
            _event("error", pf.hint or pf.detail)
            return 3

    llm = None
    if not args.no_llm and settings.llm_enabled:
        key = CredentialStore().get_api_key(settings.llm_provider)
        if key:
            llm = LlmClient(
                LlmConfig(
                    provider=settings.llm_provider,
                    base_url=settings.llm_base_url,
                    model=settings.llm_model,
                    api_key=key,
                    timeout=float(settings.llm_timeout),
                    max_tokens=settings.llm_max_tokens,
                    temperature=settings.llm_temperature,
                )
            )
        else:
            _event("warning", "API key belum ada — memakai planner lokal.")

    options = {
        "prompt": args.prompt,
        "duration": args.duration if args.duration is not None else settings.duration,
        "resolution": args.resolution or settings.resolution,
        "fps": args.fps if args.fps is not None else settings.fps,
        "style": args.style or settings.style,
    }
    pipeline = Pipeline(
        runner,
        ProjectStore(settings.projects_root()),
        llm_client=llm,
        max_attempts=settings.max_repair_attempts,
        on_event=_event,
    )
    try:
        result = pipeline.run(args.prompt, options, use_llm=llm is not None)
    except PipelineError as e:
        _event("error", e.message)
        if e.hint:
            _event("petunjuk", e.hint)
        if e.detail:
            _event("info", e.detail[-1000:])
        return 1
    except EcpsError as e:
        _event("error", e.message)
        return 1

    if args.out and result.mp4:
        target = Path(args.out).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result.mp4, target)
        result.mp4 = target

    summary = {
        "ok": True,
        "mp4": str(result.mp4) if result.mp4 else None,
        "project": str(result.record.path),
        "attempts": result.attempts,
        "simulator": result.simulator,
        "steps": len(result.steps),
        "warnings": result.warnings,
    }
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"MP4  : {summary['mp4']}")
        print(f"Proyek: {summary['project']}")
        if result.simulator:
            print("Catatan: hasil ini dari SIMULATOR, bukan rendering EffectCraft.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
