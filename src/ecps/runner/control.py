"""Mode Live: control channel EffectCraft (`effectcraft --control 9877`), JSON per baris.

Protokol (docs/control-protocol.md): TCP 127.0.0.1, satu objek JSON per baris, request
`{"id": N, "method": "engine.execute", "params": {"command": …, "params": {…}}}` dan balasan
`{"id": N, "ok": true, "result": …}`. Timeout per request 60 detik (batas server).

Render panjang tidak dilakukan lewat channel ini: proyek disimpan lewat `file.save`, lalu render
dijalankan oleh runner CLI/Docker yang diberikan.
"""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import Any

from ..errors import RunnerError
from .base import EngineResult, EventFn, Preflight, RenderSettings, StepRecord, Timer, emit


class ControlClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 9877, timeout: float = 60.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._next_id = 1

    def connect(self) -> None:
        if self._sock is not None:
            return
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=5)
            self._sock.settimeout(self.timeout)
        except OSError as e:
            raise RunnerError(
                f"tidak bisa terhubung ke control channel {self.host}:{self.port}: {e}",
                hint="Jalankan `effectcraft --control 9877` lebih dulu, atau matikan mode Live.",
            ) from e

    def call(self, method: str, params: dict | None = None) -> Any:
        self.connect()
        assert self._sock is not None
        req = {"id": self._next_id, "method": method, "params": params or {}}
        self._next_id += 1
        payload = json.dumps(req, ensure_ascii=False) + "\n"
        try:
            self._sock.sendall(payload.encode("utf-8"))
            f = self._sock.makefile("rb")
            line = f.readline()
        except OSError as e:
            self.close()
            raise RunnerError(f"control channel terputus: {e}", hint="Periksa aplikasi EffectCraft.") from e
        if not line:
            self.close()
            raise RunnerError("control channel menutup koneksi tanpa balasan")
        try:
            reply = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            raise RunnerError(f"balasan bukan JSON: {line[:200]!r}") from e
        if reply.get("id") != req["id"]:
            raise RunnerError(f"balasan dengan id tak terduga: {reply.get('id')}")
        if not reply.get("ok"):
            raise RunnerError(str(reply.get("error") or "perintah ditolak"))
        return reply.get("result")

    def execute(self, command: str, params: dict) -> Any:
        return self.call("engine.execute", {"command": command, "params": params})

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


class LiveRunner:
    kind = "live"
    is_simulator = False
    label = "Live (control channel)"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9877,
        *,
        render_runner: object | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.render_runner = render_runner
        self.client = ControlClient(host, port)

    def preflight(self) -> Preflight:
        try:
            self.client.connect()
            caps = self.client.call("engine.commands", {"enabledOnly": False})
            n = len(caps) if isinstance(caps, list) else "?"
            return Preflight(available=True, detail=f"control channel {self.host}:{self.port} — {n} command")
        except RunnerError as e:
            return Preflight(available=False, detail=e.message, hint=e.hint or "")

    def build(self, steps: list[dict], project_path: Path, on_event: EventFn | None = None) -> EngineResult:
        records: list[StepRecord] = []
        with Timer() as t:
            for i, step in enumerate(steps):
                cmd = str(step.get("command") or "")
                params = step.get("params") or {}
                t0 = time.monotonic()
                try:
                    result = self.client.execute(cmd, params)
                except RunnerError as e:
                    records.append(
                        StepRecord(
                            command=cmd,
                            params=params,
                            ok=False,
                            error=e.message,
                            seconds=time.monotonic() - t0,
                        )
                    )
                    return EngineResult(
                        ok=False,
                        steps=records,
                        error=f"{cmd}: {e.message} (step {i})",
                        error_step=i,
                        error_command=cmd,
                        seconds=t.seconds,
                    )
                records.append(
                    StepRecord(command=cmd, params=params, result=result, seconds=time.monotonic() - t0)
                )
                emit(on_event, "step", f"{cmd} ok", {"step": i, "result": result})
            # Simpan proyek supaya bisa dirender dan disimpan di riwayat.
            try:
                self.client.execute("file.save", {"path": str(Path(project_path).resolve())})
            except RunnerError as e:
                return EngineResult(
                    ok=False,
                    steps=records,
                    error=f"file.save gagal: {e.message}",
                    seconds=t.seconds,
                )
        return EngineResult(ok=True, steps=records, seconds=t.seconds)

    def render(
        self,
        project_path: Path,
        out_path: Path,
        settings: RenderSettings,
        on_event: EventFn | None = None,
    ) -> EngineResult:
        if self.render_runner is None:
            raise RunnerError(
                "mode Live tidak punya jalur render",
                hint="Atur mode koneksi ke Lokal atau Docker untuk render, atau gunakan tombol Render Ulang.",
            )
        emit(on_event, "info", "render diteruskan ke " + getattr(self.render_runner, "label", "runner"))
        return self.render_runner.render(project_path, out_path, settings, on_event)  # type: ignore[no-any-return]

    def close(self) -> None:
        self.client.close()
