# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — satu file .exe (onefile) untuk EffectCraft Prompt Studio.

Build:
    pyinstaller --clean --noconfirm effectcraft-prompt-studio.spec
Hasil: dist/EffectCraftPromptStudio.exe
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)  # type: ignore[name-defined]

datas = collect_data_files("customtkinter")
icon = ROOT / "assets" / "icon.ico"

hiddenimports = [
    "ecps.ui.app",
    "ecps.ui.settings_dialog",
    "ecps.ui.media",
    "PIL._tkinter_finder",
] + collect_submodules("ecps")

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "numpy", "matplotlib", "pandas", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EffectCraftPromptStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # tanpa jendela konsol; log tampil di panel Log aplikasi
    disable_windowed_traceback=False,
    icon=str(icon) if icon.exists() else None,
)
