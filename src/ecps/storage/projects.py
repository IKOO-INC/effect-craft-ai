"""Riwayat proyek di `Documents/EffectCraftPromptStudio`.

Satu proyek = satu folder::

    <timestamp>_<slug>/
        meta.json      judul, prompt, mode, status, waktu
        prompt.txt     prompt asli
        plan.json      rencana JSON final (yang benar-benar dieksekusi)
        steps.json     urutan command EffectCraft
        project.ecproj file proyek EffectCraft (atau snapshot simulator)
        render.mp4     hasil render
        steps.log.jsonl  log setiap command + output JSON
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..security.sanitize import ensure_within, safe_filename


@dataclass
class ProjectRecord:
    id: str
    path: Path
    title: str = ""
    prompt: str = ""
    created: str = ""
    updated: str = ""
    mode: str = ""
    status: str = "draft"
    error: str = ""
    mp4: str = ""
    plan: str = ""
    steps: str = ""
    ecproj: str = ""
    simulator: bool = False
    duration: float = 0.0
    resolution: str = ""
    extra: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        out = {
            "id": self.id,
            "path": str(self.path),
            "title": self.title,
            "prompt": self.prompt,
            "created": self.created,
            "updated": self.updated,
            "mode": self.mode,
            "status": self.status,
            "error": self.error,
            "mp4": self.mp4,
            "plan": self.plan,
            "steps": self.steps,
            "ecproj": self.ecproj,
            "simulator": self.simulator,
            "duration": self.duration,
            "resolution": self.resolution,
        }
        out.update(self.extra)
        return out

    @classmethod
    def from_json(cls, d: dict) -> "ProjectRecord":
        known = {f for f in cls.__dataclass_fields__}
        extra = {k: v for k, v in d.items() if k not in known}
        base = {k: v for k, v in d.items() if k in known and k != "extra"}
        base["path"] = Path(base.get("path") or ".")
        rec = cls(**base)  # type: ignore[arg-type]
        rec.extra = extra
        return rec

    def mp4_path(self) -> Path | None:
        if not self.mp4:
            return None
        p = Path(self.mp4)
        return p if p.exists() else None

    def absolute(self, attr: str) -> Path | None:
        val = getattr(self, attr, "")
        if not val:
            return None
        p = Path(val)
        return p if p.is_absolute() else (self.path / p)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(text: str, *, fallback: str = "proyek") -> str:
    words = re.findall(r"[A-Za-z0-9]+", text or "")[:4]
    slug = "-".join(words).lower()
    return safe_filename(slug or fallback, fallback=fallback, max_len=48)


class ProjectStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ util
    def ensure_root(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def _index_path(self) -> Path:
        return self.root / "index.json"

    def create(self, *, title: str, prompt: str) -> ProjectRecord:
        self.ensure_root()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = f"{stamp}_{slugify(title or prompt)}"
        path = self.root / base
        n = 2
        while path.exists():
            path = self.root / f"{base}-{n}"
            n += 1
        path.mkdir(parents=True)
        rec = ProjectRecord(id=path.name, path=path, title=title, prompt=prompt, created=_now(), updated=_now())
        (path / "prompt.txt").write_text(prompt, encoding="utf-8")
        self.save(rec)
        return rec

    def write_json(self, rec: ProjectRecord, name: str, data: Any) -> Path:
        target = ensure_within(rec.path, rec.path / name)
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def read_json(self, path: Path | None) -> Any:
        if path is None or not Path(path).exists():
            return None
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, rec: ProjectRecord) -> None:
        rec.updated = _now()
        self.ensure_root()
        meta = rec.path / "meta.json"
        meta.write_text(json.dumps(rec.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")
        self._update_index(rec)

    def _update_index(self, rec: ProjectRecord) -> None:
        index = self._load_index()
        index = [r for r in index if r.get("id") != rec.id]
        index.append({k: v for k, v in rec.to_json().items() if k in ("id", "path", "title", "prompt", "created",
                                                                     "updated", "mode", "status", "mp4", "simulator")})
        index.sort(key=lambda r: r.get("updated") or "", reverse=True)
        tmp = self._index_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(index[:500], indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._index_path())

    def _load_index(self) -> list[dict]:
        try:
            data = json.loads(self._index_path().read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def list(self, limit: int = 200) -> list[ProjectRecord]:
        """Daftar proyek dari `meta.json` (sumber kebenaran), terbaru dulu."""
        self.ensure_root()
        records: list[ProjectRecord] = []
        for meta in self.root.glob("*/meta.json"):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            data.setdefault("path", str(meta.parent))
            try:
                records.append(ProjectRecord.from_json(data))
            except TypeError:
                continue
        records.sort(key=lambda r: r.updated or r.created or "", reverse=True)
        return records[:limit]

    def get(self, project_id: str) -> ProjectRecord | None:
        path = self.root / project_id
        meta = path / "meta.json"
        if not meta.exists():
            return None
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        data.setdefault("path", str(path))
        return ProjectRecord.from_json(data)

    def append_log(self, rec: ProjectRecord, entry: dict) -> None:
        with (rec.path / "steps.log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
