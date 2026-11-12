#!/usr/bin/env python3
"""Verifikasi end-to-end dengan EffectCraft ASLI (bukan simulator).

Jalankan di mesin yang punya `effectcraft-cli.exe` (mode lokal) atau Docker Desktop (mode docker):

    # 1) cek koneksi yang tersedia
    python scripts/verify_with_effectcraft.py --detect

    # 2) render demo dengan EffectCraft lokal
    python scripts/verify_with_effectcraft.py --mode local --cli-path "C:/.../effectcraft-cli.exe"

    # 3) render demo lewat Docker
    python scripts/verify_with_effectcraft.py --mode docker --image effectcraft-cli:0.24.1

    # 4) coba juga dengan LLM asli (butuh API key tersimpan di Settings/Credential Manager)
    python scripts/verify_with_effectcraft.py --mode local --llm

Skrip ini mencetak setiap command yang dijalankan beserta JSON hasilnya, lalu menyalin MP4
ke `docs/demo/effectcraft-asli.mp4`. Bila gagal, langkah yang gagal dan pesan engine
ditampilkan apa adanya (tidak ada klaim sukses palsu).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecps.config import Settings  # noqa: E402
from ecps.errors import EcpsError  # noqa: E402
from ecps.llm.client import LlmClient, LlmConfig  # noqa: E402
from ecps.pipeline import Pipeline, PipelineError  # noqa: E402
from ecps.runner.detect import build_runner, detect  # noqa: E402
from ecps.security.credentials import CredentialStore  # noqa: E402
from ecps.storage.projects import ProjectStore  # noqa: E402

DEMO_PROMPT = (
    "Intro 5 detik, teks 'Majalah Dza Izza' muncul fade-in dengan latar gradasi biru"
)


def _event(kind: str, message: str, data: dict | None = None) -> None:
    prefix = {
        "command": "CMD ",
        "step": "  ok ",
        "error": "ERR ",
        "warning": "WRN ",
        "info": "inf ",
        "done": "OK  ",
        "llm": "LLM ",
        "petunjuk": "TIP ",
    }.get(kind, f"{kind} ")
    print(prefix + message, flush=True)
    if data and kind in ("command", "step"):
        try:
            print("      " + json.dumps(data, ensure_ascii=False)[:400], flush=True)
        except (TypeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verifikasi pipeline dengan EffectCraft asli")
    ap.add_argument("--mode", choices=["auto", "local", "docker", "live", "simulator"], default="auto")
    ap.add_argument("--cli-path", default="")
    ap.add_argument("--image", default="")
    ap.add_argument("--llm", action="store_true", help="pakai LLM dari Settings (butuh API key)")
    ap.add_argument("--out", default=str(ROOT / "docs" / "demo" / "effectcraft-asli.mp4"))
    ap.add_argument("--detect", action="store_true", help="hanya tampilkan deteksi koneksi")
    ap.add_argument("--prompt", default=DEMO_PROMPT)
    args = ap.parse_args(argv)

    settings = Settings()
    settings.connection = args.mode
    if args.cli_path:
        settings.cli_path = args.cli_path
    if args.image:
        settings.docker_image = args.image
    settings.sanitize()

    if args.detect:
        detection = detect(settings)
        print(f"Terpilih: {detection.runner.label}\n{detection.notice}\n")
        for cand in detection.candidates:
            mark = "OK " if cand.preflight.available else "-- "
            print(f"{mark}{cand.runner.label}: {cand.preflight.detail}")
            if cand.preflight.hint and not cand.preflight.available:
                print(f"    petunjuk: {cand.preflight.hint}")
        return 0

    if settings.connection == "auto":
        detection = detect(settings)
        runner = detection.runner
        _event("info", detection.notice)
        if runner.is_simulator:
            _event("error", "Tidak ada EffectCraft asli yang terdeteksi — skrip ini tidak akan mengklaim sukses.")
            _event("petunjuk", "Pasang EffectCraft (installer Windows) atau jalankan Docker Desktop, "
                               "lalu pakai --mode local/--mode docker.")
            return 2

    llm = None
    if args.llm:
        key = CredentialStore().get_api_key(settings.llm_provider)
        if not key:
            _event("error", f"API key {settings.llm_provider} belum tersimpan; jalankan tanpa --llm.")
            return 2
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

    runner = build_runner(settings)
    store = ProjectStore(settings.projects_root())
    pipeline = Pipeline(
        runner,
        store,
        llm_client=llm,
        max_attempts=settings.max_repair_attempts,
        on_event=_event,
    )
    options = {
        "duration": 5,
        "resolution": settings.resolution,
        "fps": settings.fps,
        "style": settings.style,
    }
    try:
        result = pipeline.run(args.prompt, options, use_llm=llm is not None)
    except PipelineError as e:
        _event("error", e.message)
        if e.detail:
            _event("info", e.detail[-1500:])
        if e.hint:
            _event("petunjuk", e.hint)
        return 1
    except EcpsError as e:
        _event("error", e.message)
        return 1

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if result.mp4 and Path(result.mp4).exists():
        shutil.copy2(result.mp4, out)
        print(f"\nMP4: {out} ({out.stat().st_size / 1024:.0f} KB)")
    print(f"Proyek: {result.record.path}")
    print(f"Percobaan: {result.attempts} · command: {len(result.steps)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
