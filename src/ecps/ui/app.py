"""Jendela utama CustomTkinter.

Semua pekerjaan berat (deteksi koneksi, LLM, proses EffectCraft, render) berjalan di thread
pekerja; UI hanya membaca antrean event lewat `after()`, jadi jendela tidak membeku.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import customtkinter as ctk
from tkinter import filedialog, messagebox

from .. import APP_NAME, __version__
from ..config import RESOLUTIONS, STYLES, Settings, SettingsStore
from ..errors import EcpsError, PipelineError, PlanError, TranslationError
from ..llm.client import LlmClient, LlmConfig
from ..pipeline import Pipeline, PipelineResult
from ..planner.schema import validate_plan
from ..runner.detect import Detection, detect
from ..security.credentials import CredentialStore
from ..storage.projects import ProjectRecord, ProjectStore
from ..translator.translate import translate, validate_steps
from .media import extract_poster, human_size, open_folder, open_path
from .settings_dialog import SettingsDialog

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

PALETTE = {
    "bg": "#0b0f14",
    "panel": "#121821",
    "panel2": "#0f141b",
    "accent": "#3b82f6",
    "ok": "#22c55e",
    "warn": "#f59e0b",
    "danger": "#ef4444",
    "muted": "#94a3b8",
}


class PromptStudioApp(ctk.CTk):
    def __init__(
        self,
        *,
        settings_store: SettingsStore | None = None,
        credentials: CredentialStore | None = None,
    ) -> None:
        super().__init__()
        self.settings_store = settings_store or SettingsStore()
        self.settings: Settings = self.settings_store.load()
        self.credentials = credentials or CredentialStore()
        self.store = ProjectStore(self.settings.projects_root())
        self.events: queue.Queue[tuple[str, str, dict | None]] = queue.Queue()
        self.detection: Detection | None = None
        self.current: PipelineResult | None = None
        self.current_record: ProjectRecord | None = None
        self._busy = False
        self._poster_ref: Any = None

        self.title(f"{APP_NAME} {__version__}")
        self.geometry("1180x780")
        self.minsize(980, 660)
        self.configure(fg_color=PALETTE["bg"])

        self._build_ui()
        self.after(120, self._poll_events)
        self._detect_async()

    # =================================================================== UI
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---------------------------------------------------------- header
        header = ctk.CTkFrame(self, fg_color=PALETTE["panel"], corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text=f"  {APP_NAME}",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=12)
        self.mode_label = ctk.CTkLabel(header, text="Mendeteksi EffectCraft…", text_color=PALETTE["muted"])
        self.mode_label.grid(row=0, column=1, sticky="w", padx=12)
        ctk.CTkButton(header, text="Settings", width=100, fg_color="#1f2937", hover_color="#374151",
                      command=self._open_settings).grid(row=0, column=2, padx=6, pady=10)
        ctk.CTkButton(header, text="Folder proyek", width=120, fg_color="#1f2937", hover_color="#374151",
                      command=self._open_projects_folder).grid(row=1, column=2, padx=6, pady=(0, 10))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)
        body.grid_columnconfigure(0, weight=0, minsize=430)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

    def _build_left(self, parent) -> None:
        left = ctk.CTkFrame(parent, fg_color=PALETTE["panel"], corner_radius=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Prompt", font=ctk.CTkFont(size=15, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=16, pady=(16, 4)
        )
        ctk.CTkLabel(
            left,
            text="Contoh: Intro 5 detik, teks 'Majalah Dza Izza' muncul fade-in dengan latar gradasi biru",
            text_color=PALETTE["muted"], anchor="w", wraplength=380, justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=16)
        self.prompt_box = ctk.CTkTextbox(left, height=130, wrap="word")
        self.prompt_box.grid(row=2, column=0, sticky="ew", padx=16, pady=8)
        self.prompt_box.insert(
            "1.0",
            "Intro 5 detik, teks 'Majalah Dza Izza' muncul fade-in dengan latar gradasi biru",
        )

        opts = ctk.CTkFrame(left, fg_color=PALETTE["panel2"], corner_radius=10)
        opts.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 8))
        opts.grid_columnconfigure((1, 3), weight=1)
        ctk.CTkLabel(opts, text="Durasi", anchor="w").grid(row=0, column=0, padx=(12, 6), pady=(10, 4), sticky="w")
        self.duration_entry = ctk.CTkEntry(opts, width=80)
        self.duration_entry.insert(0, f"{self.settings.duration:g}")
        self.duration_entry.grid(row=0, column=1, sticky="w", pady=(10, 4))
        ctk.CTkLabel(opts, text="FPS", anchor="w").grid(row=0, column=2, padx=(12, 6), pady=(10, 4), sticky="w")
        self.fps_var = ctk.StringVar(value=str(self.settings.fps))
        ctk.CTkOptionMenu(opts, values=["24", "25", "30", "50", "60"], variable=self.fps_var, width=90).grid(
            row=0, column=3, sticky="w", pady=(10, 4), padx=(0, 12)
        )
        ctk.CTkLabel(opts, text="Resolusi", anchor="w").grid(row=1, column=0, padx=(12, 6), pady=4, sticky="w")
        self.res_var = ctk.StringVar(value=RESOLUTIONS[self.settings.resolution][2])
        ctk.CTkOptionMenu(
            opts, values=[v[2] for v in RESOLUTIONS.values()], variable=self.res_var, width=250
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=4, padx=(0, 12))
        ctk.CTkLabel(opts, text="Gaya", anchor="w").grid(row=2, column=0, padx=(12, 6), pady=(4, 12), sticky="w")
        self.style_var = ctk.StringVar(value=self.settings.style)
        ctk.CTkOptionMenu(opts, values=STYLES, variable=self.style_var, width=180).grid(
            row=2, column=1, sticky="w", pady=(4, 12)
        )
        self.llm_switch = ctk.CTkSwitch(opts, text="LLM")
        if self.settings.llm_enabled:
            self.llm_switch.select()
        self.llm_switch.grid(row=2, column=2, columnspan=2, sticky="w", padx=(12, 0), pady=(4, 12))

        self.generate_btn = ctk.CTkButton(
            left, text="▶  Buat Video", height=46, font=ctk.CTkFont(size=16, weight="bold"),
            command=lambda: self._start_generate(use_llm=True),
        )
        self.generate_btn.grid(row=4, column=0, sticky="ew", padx=16, pady=(6, 4))
        self.local_btn = ctk.CTkButton(
            left, text="Buat Video (tanpa LLM)", height=34, fg_color="#1f2937", hover_color="#374151",
            command=lambda: self._start_generate(use_llm=False),
        )
        self.local_btn.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 10))

        self.progress = ctk.CTkProgressBar(left, height=10)
        self.progress.grid(row=6, column=0, sticky="ew", padx=16)
        self.progress.set(0)
        self.status_label = ctk.CTkLabel(left, text="Siap.", anchor="w", text_color=PALETTE["muted"],
                                         wraplength=390, justify="left")
        self.status_label.grid(row=7, column=0, sticky="ew", padx=16, pady=(6, 12))

        info = ctk.CTkFrame(left, fg_color=PALETTE["panel2"], corner_radius=10)
        info.grid(row=8, column=0, sticky="ew", padx=16, pady=(0, 16))
        info.grid_columnconfigure(0, weight=1)
        self.info_label = ctk.CTkLabel(
            info, text="Belum ada hasil.", anchor="w", justify="left", wraplength=380,
            text_color=PALETTE["muted"],
        )
        self.info_label.grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        row = ctk.CTkFrame(info, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        ctk.CTkButton(row, text="Putar", width=80, command=self._play).pack(side="left")
        ctk.CTkButton(row, text="Buka folder", width=110, fg_color="#1f2937", hover_color="#374151",
                      command=self._open_project_folder).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Ekspor ulang", width=110, fg_color="#1f2937", hover_color="#374151",
                      command=self._rerender).pack(side="left")

    def _build_right(self, parent) -> None:
        tabs = ctk.CTkTabview(parent, fg_color=PALETTE["panel"])
        tabs.grid(row=0, column=1, sticky="nsew")
        self.tabs = tabs
        tabs.add("Preview")
        tabs.add("Rencana JSON")
        tabs.add("Log")
        tabs.add("Riwayat")

        # ---------------- Preview
        preview = tabs.tab("Preview")
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_rowconfigure(0, weight=1)
        self.poster_label = ctk.CTkLabel(
            preview, text="Preview akan muncul di sini setelah render.",
            fg_color=PALETTE["panel2"], corner_radius=10, text_color=PALETTE["muted"],
        )
        self.poster_label.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.preview_info = ctk.CTkLabel(preview, text="", anchor="w", text_color=PALETTE["muted"])
        self.preview_info.grid(row=1, column=0, sticky="ew", padx=12)

        # ---------------- Rencana
        plan_tab = tabs.tab("Rencana JSON")
        plan_tab.grid_columnconfigure(0, weight=1)
        plan_tab.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(plan_tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        ctk.CTkButton(bar, text="Validasi", width=100, command=self._validate_plan_text).pack(side="left")
        ctk.CTkButton(bar, text="Simpan && Render Ulang", width=200,
                      command=self._run_edited_plan).pack(side="left", padx=8)
        ctk.CTkLabel(bar, text="Edit rencana lalu render ulang tanpa LLM", text_color=PALETTE["muted"]).pack(
            side="left", padx=8
        )
        self.plan_box = ctk.CTkTextbox(plan_tab, wrap="none", font=ctk.CTkFont(family="Consolas", size=12))
        self.plan_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        # ---------------- Log
        log_tab = tabs.tab("Log")
        log_tab.grid_columnconfigure(0, weight=1)
        log_tab.grid_rowconfigure(1, weight=1)
        log_bar = ctk.CTkFrame(log_tab, fg_color="transparent")
        log_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        ctk.CTkButton(log_bar, text="Bersihkan", width=100, fg_color="#1f2937", hover_color="#374151",
                      command=lambda: self.log_box.delete("1.0", "end")).pack(side="left")
        ctk.CTkButton(log_bar, text="Salin ke clipboard", width=150, fg_color="#1f2937",
                      hover_color="#374151", command=self._copy_log).pack(side="left", padx=8)
        self.log_box = ctk.CTkTextbox(log_tab, wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.log_box.configure(state="disabled")

        # ---------------- Riwayat
        hist = tabs.tab("Riwayat")
        hist.grid_columnconfigure(0, weight=1)
        hist.grid_rowconfigure(1, weight=1)
        hbar = ctk.CTkFrame(hist, fg_color="transparent")
        hbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        ctk.CTkButton(hbar, text="Muat ulang daftar", width=150, command=self._refresh_history).pack(side="left")
        self.history_frame = ctk.CTkScrollableFrame(hist, fg_color=PALETTE["panel2"])
        self.history_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.history_frame.grid_columnconfigure(0, weight=1)
        self._refresh_history()

    # ============================================================== events
    def _push(self, kind: str, message: str, data: dict | None = None) -> None:
        self.events.put((kind, message, data or {}))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, message, data = self.events.get_nowait()
                self._handle_event(kind, message, data)
        except queue.Empty:
            pass
        self.after(120, self._poll_events)

    def _handle_event(self, kind: str, message: str, data: dict) -> None:
        if kind == "detected":
            detection: Detection = data["detection"]  # type: ignore[assignment]
            self.detection = detection
            color = PALETTE["warn"] if detection.degraded else PALETTE["ok"]
            prefix = "SIMULATOR — " if detection.degraded else ""
            self.mode_label.configure(text=f"{prefix}{detection.runner.label} · {detection.notice[:160]}", text_color=color)
            self._log("sistem", detection.notice)
        elif kind == "progress":
            done = data.get("done")
            total = data.get("total")
            if isinstance(done, int) and isinstance(total, int) and total > 0:
                self.progress.set(max(0.0, min(1.0, done / total)))
                self.status_label.configure(text=f"Render {done}/{total} frame")
        elif kind == "progress-sim":
            done = data.get("done")
            total = data.get("total")
            if isinstance(done, int) and isinstance(total, int) and total > 0:
                self.progress.set(max(0.0, min(1.0, done / total)))
                self.status_label.configure(text=f"Simulator: {done}/{total} frame")
        elif kind in ("error",):
            self._log("error", message)
            self.status_label.configure(text=message[:300], text_color=PALETTE["danger"])
        elif kind == "warning":
            self._log("peringatan", message)
        elif kind == "done":
            self.progress.set(1.0)
            self.status_label.configure(text=message, text_color=PALETTE["ok"])
            self._log("selesai", message)
        elif kind == "finished":
            self._set_busy(False)
            result = data.get("result")
            if result is not None:
                self._apply_result(result)
        elif kind == "failed":
            self._set_busy(False)
            self.progress.set(0)
            error = data.get("error")
            message = str(error) if error else "Gagal."
            self.status_label.configure(text=message[:400], text_color=PALETTE["danger"])
            self._log("error", message)
            hint = getattr(error, "hint", None) if error is not None else None
            detail = getattr(error, "detail", "") if error is not None else ""
            if hint:
                self._log("petunjuk", hint)
            if detail:
                self._log("detail", detail[-1200:])
        elif kind in ("info", "llm", "command", "step", "cli-stdout", "cli-stderr",
                      "docker-stdout", "docker-stderr", "sistem"):
            self._log(kind, message)
        else:
            self._log(kind, message)

    def _log(self, kind: str, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {kind:>12}: {message}\n"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line)
        # batasi ukuran log supaya UI tetap ringan
        if int(self.log_box.index("end-1c").split(".")[0]) > 4000:
            self.log_box.delete("1.0", "800.0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _copy_log(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.log_box.get("1.0", "end"))
        self.status_label.configure(text="Log disalin ke clipboard.")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.generate_btn.configure(state=state)
        self.local_btn.configure(state=state)
        if busy:
            self.progress.set(0)
            self.status_label.configure(text="Bekerja…", text_color=PALETTE["muted"])
        else:
            try:
                self.progress.stop()
            except Exception:  # noqa: BLE001
                pass

    # ============================================================== helpers
    def _ecps_options(self) -> dict:
        resolution = "1080p"
        label = self.res_var.get()
        for key, (_w, _h, text) in RESOLUTIONS.items():
            if text == label:
                resolution = key
                break
        try:
            duration = max(0.5, min(120.0, float(self.duration_entry.get().strip() or 5)))
        except ValueError:
            duration = 5.0
        try:
            fps = int(self.fps_var.get())
        except ValueError:
            fps = 30
        return {"duration": duration, "resolution": resolution, "fps": fps, "style": self.style_var.get()}

    def _llm_client(self) -> LlmClient | None:
        s = self.settings
        if not bool(self.llm_switch.get()):
            return None
        key = self.credentials.get_api_key(s.llm_provider)
        if not key:
            return None
        return LlmClient(
            LlmConfig(
                provider=s.llm_provider,
                base_url=s.llm_base_url,
                model=s.llm_model,
                api_key=key,
                timeout=float(s.llm_timeout),
                max_tokens=s.llm_max_tokens,
                temperature=s.llm_temperature,
            )
        )

    def _persist_defaults(self, options: dict) -> None:
        self.settings.duration = float(options["duration"])
        self.settings.resolution = str(options["resolution"])
        self.settings.fps = int(options["fps"])
        self.settings.style = str(options["style"])
        try:
            self.settings_store.save(self.settings)
        except OSError:
            pass

    # ============================================================ detection
    def _detect_async(self) -> None:
        def work() -> None:
            try:
                detection = detect(self.settings)
            except Exception as e:  # noqa: BLE001
                self._push("warning", f"Deteksi koneksi gagal: {e}")
                return
            self._push("detected", "mode terdeteksi", {"detection": detection})

        threading.Thread(target=work, daemon=True).start()

    # ============================================================== pipeline
    def _start_generate(self, *, use_llm: bool) -> None:
        if self._busy:
            return
        prompt = self.prompt_box.get("1.0", "end").strip()
        if not prompt:
            messagebox.showinfo("Prompt kosong", "Tulis prompt terlebih dahulu.", parent=self)
            return
        options = self._ecps_options()
        self._persist_defaults(options)
        self._set_busy(True)
        self.tabs.set("Log")
        self._log("sistem", f"Runner: {self.detection.runner.label if self.detection else 'mendeteksi…'}")
        # Klien LLM dibuat di thread UI (switch/entry adalah objek Tk yang tidak thread-safe).
        llm = self._llm_client() if use_llm else None
        threading.Thread(
            target=self._run_generate, args=(prompt, options, use_llm, llm), daemon=True
        ).start()

    def _run_generate(self, prompt: str, options: dict, use_llm: bool, llm: LlmClient | None) -> None:
        try:
            detection = self.detection or detect(self.settings)
            if self.detection is None:
                self._push("detected", "mode terdeteksi", {"detection": detection})
            if use_llm and llm is None:
                self._push("warning", "LLM tidak aktif atau API key belum diatur — memakai planner lokal.")
            pipeline = Pipeline(
                detection.runner,
                self.store,
                llm_client=llm,
                max_attempts=self.settings.max_repair_attempts,
                on_event=lambda k, m, d=None: self._push(k, m, d),
            )
            result = pipeline.run(
                prompt,
                options | {"prompt": prompt},
                use_llm=use_llm and llm is not None,
            )
            self._push("finished", "selesai", {"result": result})
        except (PipelineError, EcpsError) as e:
            self._push("failed", str(e), {"error": e})
        except Exception as e:  # noqa: BLE001
            self._push("failed", f"Kesalahan tak terduga: {e}", {"error": e})
            self._push("detail", traceback.format_exc()[-1500:])
        finally:
            # Jangan sentuh widget dari thread pekerja; kirim lewat antrean event.
            self._push("sistem", "Pekerjaan selesai.")

    def _apply_result(self, result: PipelineResult) -> None:
        self.current = result
        self.current_record = result.record
        if result.mp4 is not None and result.mp4.exists():
            self._show_poster(result.mp4)
            size = human_size(result.mp4)
            sim = " · SIMULATOR (bukan EffectCraft)" if result.simulator else ""
            self.preview_info.configure(text=f"{result.mp4.name} · {size} · {result.attempts} percobaan{sim}")
            self.info_label.configure(
                text=f"Selesai dalam {result.attempts} percobaan.\n{result.mp4}",
                text_color=PALETTE["muted"],
            )
        if result.plan:
            self.plan_box.delete("1.0", "end")
            self.plan_box.insert("1.0", json.dumps(result.plan, indent=2, ensure_ascii=False))
            self.tabs.set("Preview")
        self._refresh_history()
        if self.settings.open_folder_after_render and result.record.path.exists():
            try:
                open_folder(result.record.path)
            except OSError:
                pass

    def _show_poster(self, mp4: Path) -> None:
        poster = extract_poster(mp4, mp4.with_suffix(".poster.png"))
        if poster is None:
            self.poster_label.configure(image=None, text=f"MP4 siap: {mp4.name}\n(Tidak ada FFmpeg untuk poster; pakai tombol Putar.)")
            return
        try:
            from PIL import Image

            img = Image.open(poster)
            w, h = img.size
            target_w = 640
            target_h = max(1, int(h * target_w / w))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(target_w, target_h))
            self._poster_ref = ctk_img
            self.poster_label.configure(image=ctk_img, text="")
        except Exception as e:  # noqa: BLE001
            self.poster_label.configure(image=None, text=f"Poster gagal ditampilkan: {e}")

    # =============================================================== actions
    def _play(self) -> None:
        mp4 = self.current.mp4 if self.current else None
        if mp4 is None and self.current_record:
            mp4 = self.current_record.mp4_path()
        if mp4 is None or not Path(mp4).exists():
            messagebox.showinfo("Belum ada video", "Buat video dulu.", parent=self)
            return
        try:
            open_path(Path(mp4))
        except OSError as e:
            messagebox.showerror("Gagal membuka video", str(e), parent=self)

    def _open_project_folder(self) -> None:
        record = self.current_record
        if record is None:
            try:
                open_folder(self.settings.projects_root())
            except OSError as e:
                messagebox.showerror("Gagal membuka folder", str(e), parent=self)
            return
        try:
            open_folder(record.path)
        except OSError as e:
            messagebox.showerror("Gagal membuka folder", str(e), parent=self)

    def _open_projects_folder(self) -> None:
        try:
            open_folder(self.settings.projects_root())
        except OSError as e:
            messagebox.showerror("Gagal membuka folder", str(e), parent=self)

    def _rerender(self) -> None:
        if self._busy:
            return
        record = self.current_record
        if record is None:
            messagebox.showinfo("Belum ada proyek", "Buat video dulu.", parent=self)
            return
        self._set_busy(True)
        threading.Thread(target=self._run_rerender, args=(record,), daemon=True).start()

    def _run_rerender(self, record: ProjectRecord) -> None:
        try:
            runner = self.detection.runner if self.detection else detect(self.settings).runner
            pipeline = Pipeline(runner, self.store, on_event=lambda k, m, d=None: self._push(k, m, d))
            result = pipeline.rerender(record)
            self._push("finished", "render ulang selesai", {"result": result})
        except Exception as e:  # noqa: BLE001
            self._push("failed", f"Render ulang gagal: {e}", {"error": e})

    def _validate_plan_text(self) -> None:
        raw = self.plan_box.get("1.0", "end").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON tidak valid", f"Baris {e.lineno}: {e.msg}", parent=self)
            return
        try:
            plan = validate_plan(data)
            translation = translate(plan)
        except (PlanError, TranslationError) as e:
            messagebox.showerror("Rencana tidak valid", str(e), parent=self)
            return
        problems = validate_steps(translation.commands_json())
        if problems:
            messagebox.showwarning("Masalah whitelist", "\n".join(problems[:10]), parent=self)
            return
        messagebox.showinfo(
            "Rencana valid",
            f"{len(plan.layers)} layer, {len(translation.steps)} command, {translation.duration:g} detik.",
            parent=self,
        )

    def _run_edited_plan(self) -> None:
        if self._busy:
            return
        raw = self.plan_box.get("1.0", "end").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON tidak valid", f"Baris {e.lineno}: {e.msg}", parent=self)
            return
        record = self.current_record
        if record is None:
            record = self.store.create(title="Rencana manual", prompt="(diedit manual)")
        self._set_busy(True)
        threading.Thread(target=self._run_plan_thread, args=(data, record), daemon=True).start()

    def _run_plan_thread(self, data: dict, record: ProjectRecord) -> None:
        try:
            runner = self.detection.runner if self.detection else detect(self.settings).runner
            pipeline = Pipeline(runner, self.store, on_event=lambda k, m, d=None: self._push(k, m, d))
            result = pipeline.run_from_plan(data, record)
            self._push("finished", "rencana dijalankan", {"result": result})
        except Exception as e:  # noqa: BLE001
            self._push("failed", f"Render dari rencana gagal: {e}", {"error": e})

    # =============================================================== history
    def _refresh_history(self) -> None:
        for child in self.history_frame.winfo_children():
            child.destroy()
        records = self.store.list(limit=60)
        if not records:
            ctk.CTkLabel(self.history_frame, text="Belum ada proyek.", text_color=PALETTE["muted"]).grid(
                row=0, column=0, sticky="w", padx=8, pady=8
            )
            return
        for i, rec in enumerate(records):
            label = f"{rec.title[:52] or rec.id}\n{rec.created} · {rec.status} · {rec.mode}"
            if rec.simulator:
                label += " · SIMULATOR"
            btn = ctk.CTkButton(
                self.history_frame,
                text=label,
                anchor="w",
                height=52,
                fg_color=PALETTE["panel"] if i % 2 == 0 else "#161d27",
                hover_color="#1f2937",
                command=lambda r=rec: self._load_record(r.id),
            )
            btn.grid(row=i, column=0, sticky="ew", padx=4, pady=2)

    def _load_record(self, project_id: str) -> None:
        rec = self.store.get(project_id)
        if rec is None:
            return
        self.current_record = rec
        plan = self.store.read_json(rec.path / "plan.json")
        if plan is not None:
            self.plan_box.delete("1.0", "end")
            self.plan_box.insert("1.0", json.dumps(plan, indent=2, ensure_ascii=False))
        mp4 = rec.mp4_path()
        if mp4 is not None:
            self._show_poster(mp4)
            self.preview_info.configure(text=f"{mp4.name} · {human_size(mp4)} · {rec.status}")
        meta = json.dumps(rec.to_json(), indent=2, ensure_ascii=False)
        self._log("riwayat", f"Memuat {rec.id}\n{meta[:800]}")
        self.tabs.set("Preview")

    # ================================================================ settings
    def _open_settings(self) -> None:
        SettingsDialog(self, self.settings, self.credentials, self._settings_saved)

    def _settings_saved(self, settings: Settings) -> None:
        self.settings = settings
        try:
            self.settings_store.save(settings)
        except OSError as e:
            messagebox.showerror("Gagal menyimpan pengaturan", str(e), parent=self)
        self.store = ProjectStore(settings.projects_root())
        self.duration_entry.delete(0, "end")
        self.duration_entry.insert(0, f"{settings.duration:g}")
        self.fps_var.set(str(settings.fps))
        self.res_var.set(RESOLUTIONS[settings.resolution][2])
        self.style_var.set(settings.style)
        self._log("sistem", "Pengaturan disimpan; mendeteksi ulang koneksi…")
        self._detect_async()
        self._refresh_history()


def run() -> None:
    app = PromptStudioApp()
    app.mainloop()
