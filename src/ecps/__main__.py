"""Entry point: `python -m ecps` (UI) atau `python -m ecps --prompt …` (headless)."""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 1:
        from .cli import main as cli_main

        return cli_main(sys.argv[1:])
    try:
        from .ui.app import run
    except Exception as e:  # noqa: BLE001
        print("Gagal memuat UI (CustomTkinter/Tk):", e, file=sys.stderr)
        print("Coba `pip install customtkinter` atau jalankan mode headless dengan --prompt …", file=sys.stderr)
        return 1
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
