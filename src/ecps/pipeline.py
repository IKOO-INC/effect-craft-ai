"""Pipeline prompt → rencana → command → proyek EffectCraft → MP4.

Alur (sesuai spesifikasi):

1. Prompt + opsi dikirim ke LLM (atau planner lokal bila LLM tidak tersedia).
2. LLM hanya boleh mengembalikan rencana JSON; validator memeriksanya.
3. Penerjemah mengubah rencana menjadi command yang ada di whitelist.
4. Runner mengeksekusi (Lokal/Docker/Live/Simulator) lalu me-render MP4.
5. Kegagalan (validasi/penerjemahan/eksekusi) dikirim balik ke LLM untuk diperbaiki,
   maksimal `max_attempts` kali; setelah itu pesan error akhir yang jelas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .errors import EcpsError, LlmError, PipelineError, PlanError, RunnerError, TranslationError
from .llm.client import LlmClient
from .llm.prompts import plan_user_prompt, repair_user_prompt, system_prompt
from .planner.local_planner import plan_from_prompt
from .planner.schema import Plan, validate_plan
from .runner.base import EventFn, RenderSettings, Runner
from .security.sanitize import safe_filename
from .storage.projects import ProjectRecord, ProjectStore
from .translator.translate import Translation, translate

MAX_ATTEMPTS = 3


@dataclass
class PipelineResult:
    record: ProjectRecord
    plan: dict | None = None
    steps: list[dict] = field(default_factory=list)
    mp4: Path | None = None
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)
    simulator: bool = False

    @property
    def ok(self) -> bool:
        return self.record.status == "selesai" and self.mp4 is not None


def _emit(on_event: EventFn | None, kind: str, message: str, data: dict | None = None) -> None:
    if on_event is not None:
        try:
            on_event(kind, message, data)
        except Exception:  # noqa: BLE001
            pass


class Pipeline:
    def __init__(
        self,
        runner: Runner,
        store: ProjectStore,
        *,
        llm_client: LlmClient | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        on_event: EventFn | None = None,
    ) -> None:
        self.runner = runner
        self.store = store
        self.llm = llm_client
        self.max_attempts = max(1, int(max_attempts))
        self.on_event = on_event

    # ------------------------------------------------------------------ util
    def _event(self, kind: str, message: str, data: dict | None = None) -> None:
        _emit(self.on_event, kind, message, data)

    def _options_payload(self, options: dict) -> dict:
        from .planner.local_planner import RESOLUTIONS, detect_resolution

        resolution = options.get("resolution") or detect_resolution(options.get("prompt") or "")
        width, height = RESOLUTIONS.get(str(resolution), RESOLUTIONS["1080p"])
        return {
            "duration": float(options.get("duration") or 5.0),
            "resolution": resolution,
            "width": width,
            "height": height,
            "fps": int(options.get("fps") or 30),
            "style": options.get("style") or "minimalis",
        }

    # ------------------------------------------------------------------- run
    def run(
        self,
        prompt: str,
        options: dict | None = None,
        *,
        use_llm: bool = True,
        record: ProjectRecord | None = None,
    ) -> PipelineResult:
        options = dict(options or {})
        options.setdefault("prompt", prompt)
        payload = self._options_payload(options)
        rec = record or self.store.create(title=prompt[:60], prompt=prompt)
        rec.mode = self.runner.kind
        rec.simulator = bool(getattr(self.runner, "is_simulator", False))
        rec.duration = payload["duration"]
        rec.resolution = str(payload["resolution"])
        rec.status = "berjalan"
        rec.error = ""
        self.store.save(rec)

        plan_raw: dict | None = None
        feedback = ""
        last_error: EcpsError | None = None
        attempts = 0
        llm_available = bool(use_llm and self.llm is not None)

        while attempts < self.max_attempts:
            attempts += 1
            self._event("info", f"Percobaan {attempts}/{self.max_attempts}")

            # 1) rencana
            try:
                if llm_available:
                    if plan_raw is None or not feedback:
                        self._event("llm", "Meminta rencana animasi ke LLM…")
                        plan_raw = self.llm.complete_json(
                            system_prompt(), plan_user_prompt(prompt, payload)
                        )
                    else:
                        self._event("llm", "Mengirim error ke LLM untuk perbaikan rencana…")
                        plan_raw = self.llm.complete_json(
                            system_prompt(),
                            repair_user_prompt(prompt, payload, plan_raw, feedback),
                        )
                else:
                    self._event("info", "Memakai planner lokal (tanpa LLM).")
                    plan_raw = plan_from_prompt(prompt, payload)
            except LlmError as e:
                last_error = e
                self._event("warning", f"LLM gagal ({e.kind}): {e.message}. Memakai planner lokal.")
                rec.extra.setdefault("warnings", []).append(f"LLM: {e.message}")
                llm_available = False
                if plan_raw is None:
                    plan_raw = plan_from_prompt(prompt, payload)
                else:
                    # Sudah ada rencana dari percobaan sebelumnya: lanjutkan tanpa perbaikan LLM.
                    break

            # 2) validasi + terjemahan
            try:
                plan: Plan = validate_plan(plan_raw)
                translation: Translation = translate(plan)
            except PlanError as e:
                last_error = e
                feedback = e.feedback()
                self._event("error", f"Validasi gagal: {e.message}")
                self.store.append_log(rec, {"stage": "validate", "ok": False, "errors": e.errors})
                rec.extra.setdefault("warnings", []).append(e.message)
                if not llm_available:
                    raise PipelineError(
                        "Rencana lokal tidak lolos validasi (ini bug planner lokal, bukan kesalahan pengguna).",
                        attempts=attempts,
                        detail=e.feedback(),
                    ) from e
                continue
            except TranslationError as e:
                last_error = e
                feedback = e.message
                self._event("error", f"Penerjemahan gagal: {e.message}")
                self.store.append_log(rec, {"stage": "translate", "ok": False, "error": e.message})
                if not llm_available:
                    raise PipelineError(
                        "Rencana tidak bisa diterjemahkan ke command EffectCraft.",
                        attempts=attempts,
                        detail=e.message,
                    ) from e
                continue

            # 3) simpan artefak
            plan_json = plan.to_dict()
            self.store.write_json(rec, "plan.json", plan_json)
            self.store.write_json(rec, "steps.json", translation.commands_json())
            rec.plan = "plan.json"
            rec.steps = "steps.json"
            self.store.save(rec)
            self._event("info", f"{len(translation.steps)} command siap dijalankan")
            self.store.append_log(
                rec,
                {"stage": "steps", "ok": True, "count": len(translation.steps),
                 "commands": translation.commands_json()},
            )

            # 4) eksekusi
            try:
                result = self.runner.build(translation.commands_json(), rec.path / "project.ecproj", self.on_event)
            except RunnerError as e:
                last_error = e
                feedback = e.feedback()
                self._event("error", f"Eksekusi gagal: {e.message}")
                self.store.append_log(rec, {"stage": "build", "ok": False, "error": e.message,
                                            "hint": e.hint, "command": e.command})
                if not llm_available:
                    raise PipelineError(
                        f"EffectCraft menolak rencana: {e.message}",
                        attempts=attempts,
                        detail=feedback,
                        hint=e.hint,
                    ) from e
                continue

            for step in result.steps:
                self.store.append_log(rec, {"stage": "step", **step.to_json()})
            if not result.ok:
                last_error = RunnerError(
                    result.error or "eksekusi gagal",
                    command=result.error_command,
                    step=result.error_step,
                )
                feedback = last_error.feedback()
                self._event("error", f"Langkah gagal: {result.error}")
                rec.extra["lastBuildOutput"] = {"stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}
                if not llm_available:
                    raise PipelineError(
                        f"EffectCraft gagal menjalankan rencana: {result.error}",
                        attempts=attempts,
                        detail=feedback,
                    )
                continue

            # 5) render
            mp4_path = rec.path / "render.mp4"
            settings = RenderSettings(
                comp=translation.comp_name,
                fps=translation.fps,
                width=translation.width,
                height=translation.height,
            )
            try:
                rendered = self.runner.render(rec.path / "project.ecproj", mp4_path, settings, self.on_event)
            except RunnerError as e:
                rec.status = "gagal"
                rec.error = e.message
                self.store.save(rec)
                self.store.append_log(rec, {"stage": "render", "ok": False, "error": e.message})
                raise PipelineError(
                    f"Render gagal: {e.message}",
                    attempts=attempts,
                    detail=e.stderr[-2000:] or e.message,
                    hint=e.hint,
                ) from e

            if not rendered.ok or not mp4_path.exists():
                rec.status = "gagal"
                rec.error = rendered.error or "render tidak menghasilkan file"
                self.store.save(rec)
                raise PipelineError(
                    f"Render gagal: {rec.error}",
                    attempts=attempts,
                    detail=(rendered.stderr or "")[-2000:],
                )

            rec.mp4 = "render.mp4"
            rec.ecproj = "project.ecproj"
            rec.status = "selesai"
            rec.error = ""
            self.store.save(rec)
            self._event("done", f"Selesai: {mp4_path}")
            return PipelineResult(
                record=rec,
                plan=plan_json,
                steps=translation.commands_json(),
                mp4=mp4_path,
                attempts=attempts,
                warnings=list(rec.extra.get("warnings", [])),
                simulator=rec.simulator,
            )

        # Habis percobaan
        detail = ""
        if last_error is not None:
            detail = last_error.feedback() if hasattr(last_error, "feedback") else str(last_error)
        rec.status = "gagal"
        rec.error = f"Gagal setelah {attempts} percobaan. {last_error.message if last_error else ''}".strip()
        self.store.save(rec)
        raise PipelineError(
            rec.error,
            attempts=attempts,
            detail=detail,
            hint=getattr(last_error, "hint", None),
        )

    # ------------------------------------------------------- dari rencana manual
    def run_from_plan(
        self,
        plan_raw: dict,
        record: ProjectRecord,
        *,
        options: dict | None = None,
    ) -> PipelineResult:
        """Jalankan rencana yang sudah diedit pengguna (tanpa LLM), lalu render."""
        options = dict(options or {})
        record.mode = self.runner.kind
        record.simulator = bool(getattr(self.runner, "is_simulator", False))
        record.status = "berjalan"
        record.error = ""
        self.store.save(record)
        plan = validate_plan(plan_raw)
        translation = translate(plan)
        plan_json = plan.to_dict()
        self.store.write_json(record, "plan.json", plan_json)
        self.store.write_json(record, "steps.json", translation.commands_json())
        result = self.runner.build(translation.commands_json(), record.path / "project.ecproj", self.on_event)
        for step in result.steps:
            self.store.append_log(record, {"stage": "step", **step.to_json()})
        if not result.ok:
            record.status = "gagal"
            record.error = result.error or "eksekusi gagal"
            self.store.save(record)
            raise PipelineError(record.error, attempts=1, detail=result.stderr[-2000:])
        mp4_path = record.path / "render.mp4"
        settings = RenderSettings(comp=translation.comp_name, fps=translation.fps,
                                  width=translation.width, height=translation.height)
        rendered = self.runner.render(record.path / "project.ecproj", mp4_path, settings, self.on_event)
        if not rendered.ok or not mp4_path.exists():
            record.status = "gagal"
            record.error = rendered.error or "render gagal"
            self.store.save(record)
            raise PipelineError(record.error, attempts=1)
        record.mp4 = "render.mp4"
        record.ecproj = "project.ecproj"
        record.plan = "plan.json"
        record.steps = "steps.json"
        record.status = "selesai"
        self.store.save(record)
        return PipelineResult(record=record, plan=plan_json, steps=translation.commands_json(),
                              mp4=mp4_path, attempts=1, simulator=record.simulator)

    # ------------------------------------------------------------- render ulang
    def rerender(self, record: ProjectRecord, *, options: dict | None = None) -> PipelineResult:
        """Render ulang proyek yang sudah ada tanpa membangun ulang langkah."""
        project = record.path / "project.ecproj"
        if not project.exists():
            raise PipelineError("file proyek tidak ditemukan; jalankan ulang dari rencana.", attempts=0)
        plan_raw = self.store.read_json(record.path / "plan.json") or {}
        comp = (plan_raw.get("comp") or {}) if isinstance(plan_raw, dict) else {}
        settings = RenderSettings(
            comp=str(comp.get("name") or "Main"),
            fps=float(comp.get("fps") or 30),
            width=int(comp.get("width") or 1920),
            height=int(comp.get("height") or 1080),
        )
        mp4_path = record.path / "render.mp4"
        rendered = self.runner.render(project, mp4_path, settings, self.on_event)
        if not rendered.ok or not mp4_path.exists():
            record.status = "gagal"
            record.error = rendered.error or "render gagal"
            self.store.save(record)
            raise PipelineError(record.error, attempts=1)
        record.mp4 = "render.mp4"
        record.status = "selesai"
        record.error = ""
        self.store.save(record)
        return PipelineResult(record=record, plan=plan_raw, mp4=mp4_path, attempts=1,
                              simulator=record.simulator)


def default_options(prompt: str, duration: float, resolution: str, fps: int, style: str) -> dict:
    return {"prompt": prompt, "duration": duration, "resolution": resolution, "fps": fps, "style": style}


__all__ = ["Pipeline", "PipelineResult", "PipelineError", "default_options", "safe_filename"]
