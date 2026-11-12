"""Kesalahan bertipe supaya UI bisa menampilkan pesan yang jelas (bukan traceback)."""

from __future__ import annotations


class EcpsError(Exception):
    """Kesalahan dasar aplikasi ini."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def as_dict(self) -> dict:
        return {"error": self.message, "hint": self.hint}


class PlanError(EcpsError):
    """Rencana JSON dari LLM tidak memenuhi skema."""

    def __init__(self, errors: list[str], *, raw: object = None) -> None:
        self.errors = errors
        self.raw = raw
        head = "Rencana animasi tidak valid"
        more = "" if len(errors) <= 6 else f" (dan {len(errors) - 6} masalah lain)"
        super().__init__(f"{head}: " + "; ".join(errors[:6]) + more)

    def feedback(self) -> str:
        """Teks yang dikirim balik ke LLM untuk perbaikan."""
        return "\n".join(f"- {e}" for e in self.errors[:20])


class TranslationError(EcpsError):
    """Rencana valid tetapi tidak bisa diterjemahkan ke command yang diizinkan."""


class RunnerError(EcpsError):
    """Eksekusi perintah EffectCraft gagal (CLI, Docker, atau control channel)."""

    def __init__(
        self,
        message: str,
        *,
        command: str | None = None,
        step: int | None = None,
        stdout: str = "",
        stderr: str = "",
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.command = command
        self.step = step
        self.stdout = stdout
        self.stderr = stderr

    def feedback(self) -> str:
        """Ringkasan untuk LLM: command mana, langkah ke berapa, pesan errornya."""
        parts = []
        if self.command:
            parts.append(f"Command: {self.command}")
        if self.step is not None:
            parts.append(f"Langkah: {self.step}")
        parts.append(f"Pesan: {self.message}")
        tail = (self.stderr or self.stdout or "").strip()
        if tail:
            parts.append("Keluaran: " + tail[-1500:])
        return "\n".join(parts)


class LlmError(EcpsError):
    """Kegagalan memanggil LLM. `kind` dipakai UI untuk pesan yang berbeda."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "http",
        status: int | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.kind = kind  # config | auth | offline | http | json | aborted
        self.status = status


class CredentialError(EcpsError):
    """Penyimpanan kredensial tidak tersedia / gagal."""


class PipelineError(EcpsError):
    """Pipeline prompt → video berhenti setelah semua percobaan."""

    def __init__(self, message: str, *, attempts: int, detail: str = "", hint: str | None = None) -> None:
        super().__init__(message, hint=hint)
        self.attempts = attempts
        self.detail = detail
