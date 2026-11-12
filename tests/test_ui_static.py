"""Pemeriksaan statis UI (GUI tidak bisa dijalankan di lingkungan Linux tanpa Tk)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
UI = SRC / "ecps" / "ui"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_ui_modules_parse():
    for path in sorted(UI.glob("*.py")):
        _tree(path)


def test_event_kinds_are_handled_in_app():
    app_tree = _tree(UI / "app.py")
    app_text = (UI / "app.py").read_text(encoding="utf-8")

    # Kumpulkan semua jenis event yang dikirim pipeline/runner maupun UI.
    kinds: set[str] = set()
    for path in (SRC / "ecps").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        kinds |= set(re.findall(r"emit\(\s*on_event\s*,\s*\"([\w-]+)\"", text))
        kinds |= set(re.findall(r"_emit\(\s*on_event\s*,\s*\"([\w-]+)\"", text))
        kinds |= set(re.findall(r"self\._push\(\s*\"([\w-]+)\"", text))

    handle = next(
        node
        for node in ast.walk(app_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_handle_event"
    )
    body = ast.get_source_segment(app_text, handle) or ""
    missing = sorted(k for k in kinds if f'"{k}"' not in body)
    assert not missing, f"event tanpa penanganan di _handle_event: {missing}"


def test_no_shell_true_in_ui():
    for path in UI.glob("*.py"):
        assert "shell=True" not in path.read_text(encoding="utf-8"), path.name


def test_headless_imports_do_not_pull_tkinter():
    import ecps.pipeline  # noqa: F401
    import ecps.cli  # noqa: F401
    import sys

    loaded = {name for name in sys.modules if name.split(".")[0] in ("tkinter", "customtkinter")}
    assert not loaded, f"modul GUI ikut terimpor: {loaded}"


def test_entrypoint_guards_gui_import():
    text = (SRC / "ecps" / "__main__.py").read_text(encoding="utf-8")
    assert "from .ui.app import run" in text
    assert "except Exception" in text  # UI gagal dimuat → pesan jelas, bukan traceback
