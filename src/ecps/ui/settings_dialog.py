"""Dialog Settings: koneksi EffectCraft, LLM, kredensial, dan default produksi."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import customtkinter as ctk
from tkinter import filedialog, messagebox

from ..config import RESOLUTIONS, STYLES, Settings
from ..errors import CredentialError
from ..security.credentials import CredentialStore
from ..security.credentials import redact

CONNECTIONS = [
    ("auto", "Otomatis"),
    ("local", "Lokal (effectcraft-cli)"),
    ("docker", "Docker"),
    ("live", "Live (control channel)"),
    ("simulator", "Simulator (tanpa EffectCraft)"),
]


class SettingsDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        settings: Settings,
        credentials: CredentialStore,
        on_saved: Callable[[Settings], None],
    ) -> None:
        super().__init__(master)
        self.title("Settings — EffectCraft Prompt Studio")
        self.geometry("720x760")
        self.settings = settings
        self.credentials = credentials
        self.on_saved = on_saved
        self.transient(master)
        self.grab_set()
        self._build()
        self.after(120, self.lift)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        pad = {"padx": 16, "pady": (8, 0)}
        body = ctk.CTkScrollableFrame(self, label_text="")
        body.pack(fill="both", expand=True, padx=4, pady=4)
        body.grid_columnconfigure(0, weight=1)

        # ---- Koneksi
        ctk.CTkLabel(body, text="Koneksi EffectCraft", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w", **pad
        )
        self.conn_var = ctk.StringVar(value=self._connection_label(self.settings.connection))
        ctk.CTkOptionMenu(
            body, values=[label for _, label in CONNECTIONS], variable=self.conn_var, width=320
        ).grid(row=1, column=0, sticky="w", **pad)

        cli_row = ctk.CTkFrame(body, fg_color="transparent")
        cli_row.grid(row=2, column=0, sticky="ew", **pad)
        cli_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(cli_row, text="Path effectcraft-cli", width=150, anchor="w").grid(row=0, column=0)
        self.cli_entry = ctk.CTkEntry(cli_row, placeholder_text="kosong = cari otomatis")
        self.cli_entry.insert(0, self.settings.cli_path)
        self.cli_entry.grid(row=0, column=1, sticky="ew", padx=8)
        ctk.CTkButton(cli_row, text="Pilih…", width=80, command=self._browse_cli).grid(row=0, column=2)

        docker_row = ctk.CTkFrame(body, fg_color="transparent")
        docker_row.grid(row=3, column=0, sticky="ew", **pad)
        docker_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(docker_row, text="Image Docker", width=150, anchor="w").grid(row=0, column=0)
        self.image_entry = ctk.CTkEntry(docker_row)
        self.image_entry.insert(0, self.settings.docker_image)
        self.image_entry.grid(row=0, column=1, sticky="ew", padx=8)
        ctk.CTkLabel(docker_row, text="Container (opsional)", width=150, anchor="w").grid(
            row=1, column=0, pady=(6, 0)
        )
        self.container_entry = ctk.CTkEntry(docker_row, placeholder_text="kosong = docker run --rm")
        self.container_entry.insert(0, self.settings.docker_container)
        self.container_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=(6, 0))

        control_row = ctk.CTkFrame(body, fg_color="transparent")
        control_row.grid(row=4, column=0, sticky="ew", **pad)
        ctk.CTkLabel(control_row, text="Control host", width=150, anchor="w").grid(row=0, column=0)
        self.host_entry = ctk.CTkEntry(control_row, width=180)
        self.host_entry.insert(0, self.settings.control_host)
        self.host_entry.grid(row=0, column=1, padx=8)
        ctk.CTkLabel(control_row, text="Port", width=50, anchor="w").grid(row=0, column=2)
        self.port_entry = ctk.CTkEntry(control_row, width=90)
        self.port_entry.insert(0, str(self.settings.control_port))
        self.port_entry.grid(row=0, column=3, padx=8)

        # ---- LLM
        ctk.CTkLabel(body, text="LLM", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=5, column=0, sticky="w", padx=16, pady=(18, 0)
        )
        self.llm_switch = ctk.CTkSwitch(body, text="Pakai LLM (matikan untuk planner lokal)")
        if self.settings.llm_enabled:
            self.llm_switch.select()
        self.llm_switch.grid(row=6, column=0, sticky="w", **pad)

        llm_row = ctk.CTkFrame(body, fg_color="transparent")
        llm_row.grid(row=7, column=0, sticky="ew", **pad)
        llm_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(llm_row, text="Provider", width=150, anchor="w").grid(row=0, column=0)
        self.provider_var = ctk.StringVar(value="Anthropic" if self.settings.llm_provider == "anthropic" else "OpenAI-compatible")
        ctk.CTkOptionMenu(
            llm_row, values=["OpenAI-compatible", "Anthropic"], variable=self.provider_var, width=220,
            command=lambda _v: self._provider_changed(),
        ).grid(row=0, column=1, sticky="w", padx=8)

        ctk.CTkLabel(llm_row, text="Base URL", width=150, anchor="w").grid(row=1, column=0, pady=(6, 0))
        self.base_entry = ctk.CTkEntry(llm_row)
        self.base_entry.insert(0, self.settings.llm_base_url)
        self.base_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=(6, 0))

        ctk.CTkLabel(llm_row, text="Model", width=150, anchor="w").grid(row=2, column=0, pady=(6, 0))
        self.model_entry = ctk.CTkEntry(llm_row, placeholder_text="mis. gpt-4o-mini / claude-3-5-sonnet")
        self.model_entry.insert(0, self.settings.llm_model)
        self.model_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=(6, 0))

        ctk.CTkLabel(llm_row, text="Timeout (detik)", width=150, anchor="w").grid(row=3, column=0, pady=(6, 0))
        self.timeout_entry = ctk.CTkEntry(llm_row, width=120)
        self.timeout_entry.insert(0, str(self.settings.llm_timeout))
        self.timeout_entry.grid(row=3, column=1, sticky="w", padx=8, pady=(6, 0))

        key_row = ctk.CTkFrame(body, fg_color="transparent")
        key_row.grid(row=8, column=0, sticky="ew", **pad)
        key_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(key_row, text="API key", width=150, anchor="w").grid(row=0, column=0)
        self.key_entry = ctk.CTkEntry(key_row, show="•", placeholder_text="disimpan di Credential Manager")
        self.key_entry.grid(row=0, column=1, sticky="ew", padx=8)
        ctk.CTkButton(key_row, text="Simpan key", width=100, command=self._save_key).grid(row=0, column=2)
        ctk.CTkButton(key_row, text="Hapus", width=70, fg_color="#7f1d1d", hover_color="#991b1b",
                      command=self._delete_key).grid(row=0, column=3, padx=(6, 0))
        self.key_status = ctk.CTkLabel(body, text=self._key_status_text(), anchor="w", text_color="#9ca3af")
        self.key_status.grid(row=9, column=0, sticky="w", padx=16)

        # ---- Default & folder
        ctk.CTkLabel(body, text="Default produksi", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=10, column=0, sticky="w", padx=16, pady=(18, 0)
        )
        defaults = ctk.CTkFrame(body, fg_color="transparent")
        defaults.grid(row=11, column=0, sticky="ew", **pad)
        ctk.CTkLabel(defaults, text="Durasi", width=150, anchor="w").grid(row=0, column=0)
        self.duration_entry = ctk.CTkEntry(defaults, width=90)
        self.duration_entry.insert(0, f"{self.settings.duration:g}")
        self.duration_entry.grid(row=0, column=1, sticky="w", padx=8)
        ctk.CTkLabel(defaults, text="FPS", width=60, anchor="w").grid(row=0, column=2)
        self.fps_var = ctk.StringVar(value=str(self.settings.fps))
        ctk.CTkOptionMenu(defaults, values=["24", "25", "30", "50", "60"], variable=self.fps_var, width=90).grid(
            row=0, column=3, padx=8
        )
        ctk.CTkLabel(defaults, text="Resolusi", width=90, anchor="w").grid(row=1, column=0, pady=(6, 0))
        self.res_var = ctk.StringVar(value=RESOLUTIONS[self.settings.resolution][2])
        ctk.CTkOptionMenu(
            defaults, values=[v[2] for v in RESOLUTIONS.values()], variable=self.res_var, width=240
        ).grid(row=1, column=1, columnspan=2, sticky="w", padx=8, pady=(6, 0))
        ctk.CTkLabel(defaults, text="Gaya", width=90, anchor="w").grid(row=2, column=0, pady=(6, 0))
        self.style_var = ctk.StringVar(value=self.settings.style)
        ctk.CTkOptionMenu(defaults, values=STYLES, variable=self.style_var, width=180).grid(
            row=2, column=1, sticky="w", padx=8, pady=(6, 0)
        )

        folder_row = ctk.CTkFrame(body, fg_color="transparent")
        folder_row.grid(row=12, column=0, sticky="ew", **pad)
        folder_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(folder_row, text="Folder proyek", width=150, anchor="w").grid(row=0, column=0)
        self.projects_entry = ctk.CTkEntry(folder_row)
        self.projects_entry.insert(0, str(self.settings.projects_dir or self.settings.projects_root()))
        self.projects_entry.grid(row=0, column=1, sticky="ew", padx=8)
        ctk.CTkButton(folder_row, text="Pilih…", width=80, command=self._browse_projects).grid(row=0, column=2)

        self.attempts_entry = ctk.CTkEntry(body, width=80)
        self.attempts_entry.insert(0, str(self.settings.max_repair_attempts))
        ctk.CTkLabel(body, text="Maks. percobaan perbaikan LLM (1–5)", anchor="w").grid(
            row=13, column=0, sticky="w", padx=16, pady=(10, 0)
        )
        self.attempts_entry.grid(row=14, column=0, sticky="w", padx=16, pady=(4, 0))

        # ---- tombol
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(buttons, text="Batal", width=110, fg_color="#374151", hover_color="#4b5563",
                      command=self.destroy).pack(side="right")
        ctk.CTkButton(buttons, text="Simpan", width=140, command=self._save).pack(side="right", padx=8)

    # ------------------------------------------------------------------ helper
    def _connection_label(self, value: str) -> str:
        for key, label in CONNECTIONS:
            if key == value:
                return label
        return CONNECTIONS[0][1]

    def _connection_value(self) -> str:
        label = self.conn_var.get()
        for key, text in CONNECTIONS:
            if text == label:
                return key
        return "auto"

    def _key_status_text(self) -> str:
        provider = "anthropic" if self.provider_var.get() == "Anthropic" else "openai"
        key = self.credentials.get_api_key(provider)
        store = self.credentials.description
        if key:
            return f"Tersimpan: {redact(key)} — {store}"
        return f"Belum ada key untuk {provider} — {store}"

    def _provider_changed(self) -> None:
        provider = "anthropic" if self.provider_var.get() == "Anthropic" else "openai"
        from ..config import DEFAULT_LLM_BASE

        self.base_entry.delete(0, "end")
        self.base_entry.insert(0, DEFAULT_LLM_BASE[provider])
        self.key_status.configure(text=self._key_status_text())

    def _browse_cli(self) -> None:
        types = [("Executable", "*.exe"), ("Semua file", "*")] if __import__("sys").platform.startswith("win") else [("Semua file", "*")]
        path = filedialog.askopenfilename(title="Pilih effectcraft-cli", filetypes=types)
        if path:
            self.cli_entry.delete(0, "end")
            self.cli_entry.insert(0, path)

    def _browse_projects(self) -> None:
        path = filedialog.askdirectory(title="Folder proyek")
        if path:
            self.projects_entry.delete(0, "end")
            self.projects_entry.insert(0, path)

    def _save_key(self) -> None:
        provider = "anthropic" if self.provider_var.get() == "Anthropic" else "openai"
        key = self.key_entry.get().strip()
        if not key:
            messagebox.showinfo("API key", "Isi API key terlebih dahulu.", parent=self)
            return
        try:
            self.credentials.set_api_key(provider, key)
        except CredentialError as e:
            messagebox.showerror("Gagal menyimpan key", str(e), parent=self)
            return
        self.key_entry.delete(0, "end")
        self.key_status.configure(text=self._key_status_text())
        messagebox.showinfo("API key", "API key disimpan dengan aman (tidak ditulis ke file pengaturan).", parent=self)

    def _delete_key(self) -> None:
        provider = "anthropic" if self.provider_var.get() == "Anthropic" else "openai"
        try:
            self.credentials.delete_api_key(provider)
        except CredentialError as e:
            messagebox.showerror("Gagal menghapus key", str(e), parent=self)
            return
        self.key_status.configure(text=self._key_status_text())

    # -------------------------------------------------------------------- save
    def _save(self) -> None:
        s = self.settings
        s.connection = self._connection_value()
        s.cli_path = self.cli_entry.get().strip()
        s.docker_image = self.image_entry.get().strip() or s.docker_image
        s.docker_container = self.container_entry.get().strip()
        s.control_host = self.host_entry.get().strip() or "127.0.0.1"
        try:
            s.control_port = int(self.port_entry.get().strip() or 9877)
        except ValueError:
            messagebox.showerror("Port tidak valid", "Port harus angka 1–65535.", parent=self)
            return
        s.llm_enabled = bool(self.llm_switch.get())
        s.llm_provider = "anthropic" if self.provider_var.get() == "Anthropic" else "openai"
        s.llm_base_url = self.base_entry.get().strip()
        s.llm_model = self.model_entry.get().strip()
        try:
            s.llm_timeout = max(10, int(self.timeout_entry.get().strip() or 90))
        except ValueError:
            s.llm_timeout = 90
        try:
            s.duration = float(self.duration_entry.get().strip() or 5)
        except ValueError:
            s.duration = 5.0
        s.fps = int(self.fps_var.get())
        for key, (_, _, label) in RESOLUTIONS.items():
            if label == self.res_var.get():
                s.resolution = key
                break
        s.style = self.style_var.get()
        s.projects_dir = self.projects_entry.get().strip()
        try:
            s.max_repair_attempts = max(1, min(5, int(self.attempts_entry.get().strip() or 3)))
        except ValueError:
            s.max_repair_attempts = 3
        s.sanitize()
        self.on_saved(s)
        self.destroy()
