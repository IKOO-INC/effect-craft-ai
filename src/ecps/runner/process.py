"""Menjalankan proses eksternal dengan aman: tanpa shell, dengan timeout, tanpa membekukan UI.

Semua argumen berupa list (bukan string perintah), jadi tidak ada shell yang bisa menafsirkan
spasi, kutip, atau `&`/`|`. Karakter NUL ditolak di lapisan ini juga.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from ..security.sanitize import check_no_control_chars

LineFn = Callable[[str, str], None]  # (stream, line), stream = "stdout" | "stderr"

#: Jendela console tidak muncul saat .exe dipanggil dari GUI.
_NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0


@dataclass
class ProcResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    seconds: float = 0.0
    argv: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def _validate_argv(argv: Sequence[str]) -> list[str]:
    out = []
    for a in argv:
        if not isinstance(a, str):
            raise TypeError(f"argumen proses harus str, bukan {type(a)!r}")
        check_no_control_chars(a, what="argumen proses")
        out.append(a)
    if not out:
        raise ValueError("argv kosong")
    return out


def run_command(
    argv: Sequence[str],
    *,
    timeout: float = 120.0,
    cwd: str | os.PathLike | None = None,
    env: dict[str, str] | None = None,
    on_line: LineFn | None = None,
    stdin_text: str | None = None,
) -> ProcResult:
    args = _validate_argv(argv)
    t0 = time.monotonic()
    proc = subprocess.Popen(
        args,
        cwd=str(cwd) if cwd else None,
        env={**os.environ, **(env or {})} if env else None,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        shell=False,
        creationflags=_NO_WINDOW,
    )

    out_chunks: list[str] = []
    err_chunks: list[str] = []

    def pump(stream, name: str, sink: list[str]) -> None:
        try:
            for line in iter(stream.readline, ""):
                sink.append(line)
                if on_line is not None:
                    try:
                        on_line(name, line.rstrip("\n"))
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    threads = [
        threading.Thread(target=pump, args=(proc.stdout, "stdout", out_chunks), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, "stderr", err_chunks), daemon=True),
    ]
    for t in threads:
        t.start()

    if stdin_text is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin_text)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate(proc)

    for t in threads:
        t.join(timeout=5)

    return ProcResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout="".join(out_chunks),
        stderr="".join(err_chunks),
        timed_out=timed_out,
        seconds=time.monotonic() - t0,
        argv=tuple(args),
    )


def _terminate(proc: subprocess.Popen) -> None:
    """Hentikan proses; di Windows ikut matikan anak-anaknya (tanpa shell)."""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
                timeout=15,
                check=False,
            )
        else:
            proc.terminate()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
