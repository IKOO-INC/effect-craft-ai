#!/usr/bin/env python3
"""Membuat demo end-to-end dengan SIMULATOR internal (tanpa EffectCraft).

    python scripts/make_demo.py [--out docs/demo]

Hasil:
    docs/demo/intro-majalah-dza-izza.mp4   video MP4 (H.264, 1080p, 5 detik)
    docs/demo/intro-majalah-dza-izza.png   poster (frame 2,5 detik)
    docs/demo/plan.json / steps.json       rencana JSON & command yang dijalankan
    docs/demo/log.txt                      log eksekusi lengkap

PENTING: video ini dirender oleh simulator Pillow+FFmpeg milik aplikasi, BUKAN oleh
EffectCraft. Untuk hasil asli EffectCraft jalankan `scripts/verify_with_effectcraft.py`
di mesin Windows yang punya `effectcraft-cli.exe` atau Docker.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecps.config import Settings  # noqa: E402
from ecps.pipeline import Pipeline  # noqa: E402
from ecps.runner.base import RenderSettings  # noqa: E402
from ecps.runner.simulator import SimulationRunner  # noqa: E402
from ecps.storage.projects import ProjectStore  # noqa: E402
from ecps.ui.media import extract_poster  # noqa: E402

DEMO_PROMPT = (
    "Intro 5 detik, teks 'Majalah Dza Izza' muncul fade-in dengan latar gradasi biru"
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Buat demo MP4 dengan simulator")
    ap.add_argument("--out", default=str(ROOT / "docs" / "demo"))
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--resolution", default="1080p")
    args = ap.parse_args(argv)

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="ecps-demo-"))

    log_lines: list[str] = []

    def on_event(kind: str, message: str, data: dict | None = None) -> None:
        line = f"[{kind}] {message}"
        log_lines.append(line)
        print(line, flush=True)

    settings = Settings()
    settings.projects_dir = str(work)
    runner = SimulationRunner()
    pipeline = Pipeline(runner, ProjectStore(work), max_attempts=1, on_event=on_event)

    options = {
        "duration": 5,
        "resolution": args.resolution,
        "fps": args.fps,
        "style": "minimalis",
    }
    result = pipeline.run(DEMO_PROMPT, options, use_llm=False)
    if not result.mp4 or not Path(result.mp4).exists():
        print("GAGAL: MP4 tidak dihasilkan", file=sys.stderr)
        return 1

    video = out_dir / "intro-majalah-dza-izza.mp4"
    shutil.copy2(result.mp4, video)
    poster = out_dir / "intro-majalah-dza-izza.png"
    if not extract_poster(video, poster, at=2.5):
        print("peringatan: poster gagal dibuat", file=sys.stderr)

    plan_data = result.plan.to_dict() if hasattr(result.plan, "to_dict") else (result.plan or {})
    (out_dir / "plan.json").write_text(
        json.dumps(plan_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "steps.json").write_text(
        json.dumps(result.steps, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log_lines.append("")
    log_lines.append("SIMULATOR: video ini BUKAN hasil rendering EffectCraft.")
    log_lines.append("Jalankan scripts/verify_with_effectcraft.py di Windows untuk hasil asli.")
    (out_dir / "log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print(f"\nMP4    : {video} ({video.stat().st_size / 1024:.0f} KB)")
    print(f"Poster : {poster}")
    print(f"Proyek : {result.record.path}")
    print("Catatan: dirender oleh SIMULATOR, bukan EffectCraft.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
