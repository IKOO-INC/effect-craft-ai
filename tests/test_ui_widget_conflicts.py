"""Gagal bila subclass widget menimpa atribut internal tkinter/customtkinter.

Latar belakang: `tkinter.Misc` punya method privat seperti `_options(self, cnf, kw)` yang dipanggil
oleh `configure()`. Subclass `CTk`/`CTkToplevel` yang mendefinisikan nama sama akan membuat Tk
memanggil method kita dengan argumen internal → `TypeError` saat aplikasi start
(kasus nyata: `_options() takes 1 positional argument but 2 were given`).

Berkas ini punya dua lapis pemeriksaan:

1. `test_ui_classes_do_not_shadow_widget_internals` — statis (AST), selalu jalan termasuk di CI
   tanpa Tk. Memakai daftar nama internal yang stabil di tkinter 3.x dan customtkinter 5.x.
2. `test_ui_classes_do_not_shadow_installed_tk_internals` — runtime, mengintrospeksi `dir()` kelas
   tkinter/customtkinter yang benar-benar terpasang (butuh `tkinter` + `customtkinter`, jadi
   otomatis di-skip di lingkungan tanpa GUI).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
UI = SRC / "ecps" / "ui"

#: Atribut internal `tkinter.Misc`/`BaseWidget`/`Widget`/`Tk`/`Toplevel` (stabil di Python 3.8–3.15).
TK_INTERNALS = {
    "_options",
    "_configure",
    "_configure_fake",
    "_root",
    "_w",
    "_name",
    "_bind",
    "_bind_class",
    "_register",
    "_substitute",
    "_report_exception",
    "_windowingsystem",
    "_getints",
    "_getdoubles",
    "_getboolean",
    "_nametowidget",
    "_displayof",
    "_grid_configure",
    "_gridconvvalue",
    "_do",
    "_setup",
    "_tclCommands",
    "_last_child_ids",
    "_center",
    "_withdraw",
    "_getconfigure",
    "_getconfigure1",
    "_getconfigure2",
    "_loadtk",
    "_iconbitmap",
    "_getconfigurevalue",
}

#: Atribut internal customtkinter (`CTk`, `CTkToplevel`, `CTkFrame`, widget dasar).
CTK_INTERNALS = {
    "_window_exists",
    "_apply_appearance_mode",
    "_set_appearance_mode",
    "_set_scaling",
    "_detect_color_of_master",
    "_draw",
    "_on_enter",
    "_on_leave",
    "_click_animation",
    "_canvas",
    "_text_label",
    "_create_grid",
    "_set_dimensions",
    "_set_scaled_min_max",
    "_state_before_windows_set_titlebar_color",
    "_iconify_called_before_window_exists",
    "_current_width",
    "_current_height",
}

INTERNALS = TK_INTERNALS | CTK_INTERNALS


def _is_widget_subclass(bases: list[str]) -> bool:
    return any(("CTk" in base) or ("tkinter" in base) for base in bases)


def _member_names(cls: ast.ClassDef) -> set[str]:
    """Nama yang didefinisikan kelas: method, atribut kelas, dan `self.<attr> = …` di body-nya."""
    names: set[str] = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Store)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            names.add(node.attr)
    return {n for n in names if n.startswith("_") and not n.startswith("__")}


def _ui_widget_classes() -> list[tuple[str, str, list[str], set[str]]]:
    out = []
    for path in sorted(UI.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [ast.unparse(b) for b in node.bases]
            if not _is_widget_subclass(bases):
                continue
            out.append((path.name, node.name, bases, _member_names(node)))
    return out


def test_ui_widget_subclasses_are_found():
    """Sanity check: minimal satu subclass widget (kalau tidak, test bentrok jadi hampa)."""
    assert _ui_widget_classes(), "tidak ada subclass CTk/tkinter yang terdeteksi di src/ecps/ui"


@pytest.mark.parametrize("file_name, class_name, bases, members", _ui_widget_classes())
def test_ui_classes_do_not_shadow_widget_internals(file_name, class_name, bases, members):
    offenders = sorted(members & INTERNALS)
    assert not offenders, (
        f"{file_name}:{class_name}({', '.join(bases)}) menimpa atribut internal Tk/CTk: "
        f"{offenders}. Ganti nama dengan awalan `_ecps_` (mis. `_ecps_options`) karena Tk memanggil "
        "method privat itu dengan argumennya sendiri."
    )


def test_ui_classes_do_not_shadow_installed_tk_internals():
    """Lapis runtime: ikut versi tkinter/customtkinter yang benar-benar terpasang."""
    tkinter = pytest.importorskip("tkinter")
    ctk = pytest.importorskip("customtkinter")

    import sys

    sys.path.insert(0, str(SRC))
    from ecps.ui.app import PromptStudioApp
    from ecps.ui.settings_dialog import SettingsDialog

    internal: set[str] = set()
    for module, class_names in (
        (tkinter, ("Misc", "BaseWidget", "Widget", "Tk", "Toplevel")),
        (ctk, ("CTk", "CTkToplevel", "CTkFrame", "CTkBaseClass")),
    ):
        for name in class_names:
            cls = getattr(module, name, None)
            if cls is not None:
                internal |= set(dir(cls))
    internal = {n for n in internal if n.startswith("_") and not n.startswith("__")}

    problems = []
    for cls in (PromptStudioApp, SettingsDialog):
        offenders = sorted(set(vars(cls)) & internal)
        if offenders:
            problems.append(f"{cls.__name__}: {offenders}")
    assert not problems, (
        "subclass menimpa atribut internal Tk/CTk: " + "; ".join(problems) + ". Pakai awalan `_ecps_`."
    )
