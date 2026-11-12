"""Penyimpanan API key.

Windows : Windows Credential Manager lewat `ctypes` (advapi32), tipe generik per provider.
           Tidak ada key yang pernah ditulis ke file teks atau ke log.
Lainnya : fallback file `secrets.json` dengan izin 0600 di folder konfigurasi, hanya untuk
           pengembangan/di luar Windows; UI menandainya sebagai tidak aman.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

from ..config import config_dir
from ..errors import CredentialError

SERVICE_PREFIX = "EffectCraftPromptStudio"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


def target_name(provider: str) -> str:
    return f"{SERVICE_PREFIX}/{provider}"


def redact(secret: str | None, *, keep: int = 4) -> str:
    """Bentuk aman untuk log: 'sk-…abcd'."""
    if not secret:
        return "(kosong)"
    if len(secret) <= keep:
        return "…"
    return "…" + secret[-keep:]


class CredentialBackend(Protocol):
    name: str
    secure: bool

    def write(self, target: str, secret: str) -> None: ...
    def read(self, target: str) -> str | None: ...
    def delete(self, target: str) -> None: ...


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialBackend:
    """Windows Credential Manager (CRED_TYPE_GENERIC)."""

    name = "Windows Credential Manager"
    secure = True

    def __init__(self) -> None:
        if not sys.platform.startswith("win"):
            raise CredentialError("Windows Credential Manager hanya tersedia di Windows")
        self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._advapi.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        ]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi.CredDeleteW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi.CredFree.restype = None

    def write(self, target: str, secret: str) -> None:
        blob = secret.encode("utf-16-le")
        buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
        cred = _CREDENTIALW(
            Flags=0,
            Type=CRED_TYPE_GENERIC,
            TargetName=target,
            Comment="EffectCraft Prompt Studio API key",
            LastWritten=_FILETIME(),
            CredentialBlobSize=len(blob),
            CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)),
            Persist=CRED_PERSIST_LOCAL_MACHINE,
            AttributeCount=0,
            Attributes=None,
            TargetAlias=None,
            UserName="api-key",
        )
        if not self._advapi.CredWriteW(ctypes.byref(cred), 0):
            raise CredentialError(f"CredWrite gagal (kode {ctypes.get_last_error()})")

    def read(self, target: str) -> str | None:
        ptr = ctypes.POINTER(_CREDENTIALW)()
        if not self._advapi.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
            err = ctypes.get_last_error()
            if err == 1168:  # ERROR_NOT_FOUND
                return None
            raise CredentialError(f"CredRead gagal (kode {err})")
        try:
            cred = ptr.contents
            size = int(cred.CredentialBlobSize)
            if size <= 0:
                return ""
            data = ctypes.string_at(cred.CredentialBlob, size)
            return data.decode("utf-16-le", errors="replace")
        finally:
            self._advapi.CredFree(ptr)

    def delete(self, target: str) -> None:
        if not self._advapi.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            err = ctypes.get_last_error()
            if err != 1168:
                raise CredentialError(f"CredDelete gagal (kode {err})")


class FileCredentialBackend:
    """Fallback non-Windows: file JSON dengan izin 0600. Jelas tidak sekuat Credential Manager."""

    name = "file lokal (izin 0600, non-Windows)"
    secure = False

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "secrets.json")

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    def write(self, target: str, secret: str) -> None:
        data = self._load()
        data[target] = secret
        self._save(data)

    def read(self, target: str) -> str | None:
        return self._load().get(target)

    def delete(self, target: str) -> None:
        data = self._load()
        if data.pop(target, None) is not None:
            self._save(data)


class InMemoryBackend:
    """Dipakai unit test."""

    name = "memori (test)"
    secure = False

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def write(self, target: str, secret: str) -> None:
        self.data[target] = secret

    def read(self, target: str) -> str | None:
        return self.data.get(target)

    def delete(self, target: str) -> None:
        self.data.pop(target, None)


def default_backend() -> CredentialBackend:
    if sys.platform.startswith("win"):
        try:
            return WindowsCredentialBackend()
        except (CredentialError, OSError, AttributeError):
            return FileCredentialBackend()
    return FileCredentialBackend()


class CredentialStore:
    def __init__(self, backend: CredentialBackend | None = None) -> None:
        self.backend = backend or default_backend()

    @property
    def description(self) -> str:
        return f"{self.backend.name} ({'aman' if self.backend.secure else 'kurang aman'})"

    def set_api_key(self, provider: str, secret: str) -> None:
        secret = (secret or "").strip()
        if not secret:
            self.delete_api_key(provider)
            return
        if len(secret) > 4096:
            raise CredentialError("API key terlalu panjang")
        self.backend.write(target_name(provider), secret)

    def get_api_key(self, provider: str) -> str | None:
        try:
            return self.backend.read(target_name(provider))
        except CredentialError:
            return None

    def has_api_key(self, provider: str) -> bool:
        return bool(self.get_api_key(provider))

    def delete_api_key(self, provider: str) -> None:
        self.backend.delete(target_name(provider))
