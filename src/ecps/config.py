"""Pengaturan aplikasi (tanpa rahasia apa pun) dan lokasi folder standar.

API key TIDAK PERNAH ditulis ke file ini; lihat :mod:`ecps.security.credentials`.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import APP_NAME

DEFAULT_LLM_BASE = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}


def config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "EffectCraftPromptStudio"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "effectcraft-prompt-studio"


def documents_dir() -> Path:
    """`Documents` pengguna, dengan fallback yang wajar di Linux/macOS."""
    if sys.platform.startswith("win"):
        profile = os.environ.get("USERPROFILE") or str(Path.home())
        return Path(profile) / "Documents"
    docs = Path.home() / "Documents"
    return docs if docs.exists() or not (Path.home() / "Dokumen").exists() else Path.home() / "Dokumen"


def default_projects_dir() -> Path:
    return documents_dir() / "EffectCraftPromptStudio"


@dataclass
class Settings:
    # --- koneksi ke EffectCraft -------------------------------------------------
    connection: str = "auto"  # auto | local | docker | live | simulator
    cli_path: str = ""  # kosong = cari otomatis
    docker_image: str = "ghcr.io/storytold/effectcraft:latest"
    docker_container: str = ""  # opsional: pakai `docker exec` ke container yang sudah jalan
    control_host: str = "127.0.0.1"
    control_port: int = 9877
    # --- LLM ------------------------------------------------------------------
    llm_enabled: bool = True
    llm_provider: str = "openai"  # openai | anthropic
    llm_base_url: str = DEFAULT_LLM_BASE["openai"]
    llm_model: str = "gpt-4o-mini"
    llm_timeout: int = 90
    llm_max_tokens: int = 4000
    llm_temperature: float = 0.2
    # --- default produksi ------------------------------------------------------
    duration: float = 5.0
    resolution: str = "1080p"  # 720p | 1080p | vertical_1080x1920 | vertical_720x1280 | square_1080
    fps: int = 30
    style: str = "minimalis"
    # --- lain-lain -------------------------------------------------------------
    projects_dir: str = ""
    max_repair_attempts: int = 3
    open_folder_after_render: bool = False

    def projects_root(self) -> Path:
        return Path(self.projects_dir) if self.projects_dir else default_projects_dir()

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in (data or {}).items() if k in known}
        out = cls()
        for k, v in clean.items():
            setattr(out, k, v)
        out.sanitize()
        return out

    def sanitize(self) -> None:
        if self.connection not in {"auto", "local", "docker", "live", "simulator"}:
            self.connection = "auto"
        if self.llm_provider not in {"openai", "anthropic"}:
            self.llm_provider = "openai"
        if not self.llm_base_url:
            self.llm_base_url = DEFAULT_LLM_BASE[self.llm_provider]
        try:
            self.control_port = int(self.control_port)
        except (TypeError, ValueError):
            self.control_port = 9877
        if not 1 <= self.control_port <= 65535:
            self.control_port = 9877
        try:
            self.duration = min(120.0, max(0.5, float(self.duration)))
        except (TypeError, ValueError):
            self.duration = 5.0
        try:
            self.fps = min(60, max(1, int(self.fps)))
        except (TypeError, ValueError):
            self.fps = 30
        if self.resolution not in RESOLUTIONS:
            self.resolution = "1080p"
        if self.style not in STYLES:
            self.style = "minimalis"
        self.max_repair_attempts = min(5, max(1, int(self.max_repair_attempts or 3)))


#: Resolusi yang ditawarkan UI. `(width, height, label)`.
RESOLUTIONS: dict[str, tuple[int, int, str]] = {
    "720p": (1280, 720, "720p 16:9"),
    "1080p": (1920, 1080, "1080p 16:9"),
    "vertical_1080x1920": (1080, 1920, "Vertikal 1080×1920 (9:16)"),
    "vertical_720x1280": (720, 1280, "Vertikal 720×1280 (9:16)"),
    "square_1080": (1080, 1080, "Persegi 1080×1080 (1:1)"),
}

STYLES = ["minimalis", "neon", "korporat", "elegan", "retro", "bold", "podcast", "gelap"]


class SettingsStore:
    """Menyimpan `settings.json` di folder konfigurasi pengguna."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "settings.json")

    def load(self) -> Settings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Settings()
        except (OSError, json.JSONDecodeError):
            return Settings()
        return Settings.from_json(data if isinstance(data, dict) else {})

    def save(self, settings: Settings) -> None:
        settings.sanitize()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(settings.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)


def app_header() -> str:
    return f"{APP_NAME} {__import__('ecps').__version__}"
