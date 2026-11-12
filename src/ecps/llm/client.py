"""Klien LLM minimal (stdlib saja): endpoint kompatibel OpenAI dan Anthropic.

Kenapa urllib, bukan `requests`/SDK resmi: satu-file .exe tetap kecil, dan permukaannya cukup
sempit (satu POST JSON + baca JSON). Tidak ada key yang ditulis ke log; header Authorization
disunting dari setiap pesan error.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..errors import LlmError

ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class LlmConfig:
    provider: str = "openai"  # openai | anthropic
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    timeout: float = 90.0
    max_tokens: int = 4000
    temperature: float = 0.2

    def sanitized(self) -> "LlmConfig":
        return LlmConfig(
            provider=self.provider,
            base_url=self.base_url.rstrip("/"),
            model=self.model,
            api_key="***",
            timeout=self.timeout,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return m.group(1) if m else text


def extract_json_object(text: str) -> dict:
    """Ambil objek JSON pertama dari jawaban model (toleran terhadap pagar kode / teks pengantar)."""
    if not isinstance(text, str) or not text.strip():
        raise LlmError("jawaban model kosong", kind="json")
    candidate = _strip_fences(text)
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
        raise LlmError("jawaban model bukan objek JSON", kind="json")
    except json.JSONDecodeError:
        pass
    start = candidate.find("{")
    while start >= 0:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(candidate[start:i + 1])
                        if isinstance(data, dict):
                            return data
                    except json.JSONDecodeError:
                        break
        start = candidate.find("{", start + 1)
    raise LlmError("jawaban model tidak berisi objek JSON yang valid", kind="json")


def _clean_message(text: str, api_key: str) -> str:
    text = (text or "").strip()
    if api_key:
        text = text.replace(api_key, "***")
    return text[:800]


class LlmClient:
    """Satu metode publik: `complete_json(system, user)` → dict."""

    def __init__(self, config: LlmConfig, *, opener=None) -> None:
        self.config = config
        self._opener = opener or urllib.request.urlopen

    # --------------------------------------------------------------- payload
    def _request(self, system: str, user: str) -> urllib.request.Request:
        cfg = self.config
        if cfg.provider == "anthropic":
            url = cfg.base_url.rstrip("/")
            if not url.endswith("/messages"):
                url = url + "/v1/messages" if not url.endswith("/v1") else url + "/messages"
            body = {
                "model": cfg.model,
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            headers = {
                "content-type": "application/json",
                "x-api-key": cfg.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            }
        else:
            url = cfg.base_url.rstrip("/") + "/chat/completions"
            body = {
                "model": cfg.model,
                "temperature": cfg.temperature,
                "max_tokens": cfg.max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {cfg.api_key}",
            }
        return urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    # ------------------------------------------------------------------ call
    def complete_json(self, system: str, user: str) -> dict:
        cfg = self.config
        if not cfg.api_key:
            raise LlmError(
                "API key belum diatur",
                kind="config",
                hint="Buka Settings → LLM dan simpan API key (disimpan di Windows Credential Manager).",
            )
        if not cfg.model:
            raise LlmError("model belum diatur", kind="config")
        req = self._request(system, user)
        try:
            with self._opener(req, timeout=cfg.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")
            except OSError:
                pass
            message = _clean_message(detail, cfg.api_key) or str(e.reason)
            if e.code in (401, 403):
                raise LlmError(
                    f"API key ditolak ({e.code}). Periksa key di Settings.",
                    kind="auth",
                    status=e.code,
                    hint=message,
                ) from e
            if e.code == 429:
                raise LlmError("kuota/rate limit provider tercapai (429)", kind="http", status=429, hint=message) from e
            raise LlmError(f"provider mengembalikan HTTP {e.code}", kind="http", status=e.code, hint=message) from e
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            reason = getattr(e, "reason", e)
            raise LlmError(
                f"tidak bisa menghubungi LLM: {reason}",
                kind="offline",
                hint="Periksa koneksi internet, base URL, dan proxy. Aplikasi tetap bisa memakai planner lokal.",
            ) from e
        except OSError as e:
            raise LlmError(f"gagal menghubungi LLM: {e}", kind="offline") from e

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise LlmError("balasan provider bukan JSON", kind="json") from e
        text = self._text_from_payload(payload)
        return extract_json_object(text)

    def _text_from_payload(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            raise LlmError("balasan provider tidak dikenali", kind="json")
        if self.config.provider == "anthropic":
            blocks = payload.get("content")
            if isinstance(blocks, list):
                parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
                if parts:
                    return "\n".join(parts)
            raise LlmError("balasan Anthropic tanpa blok teks", kind="json")
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict):
                return str(msg.get("content") or "")
        # Sebagian endpoint kompatibel mengembalikan {"output": ...} atau teks polos.
        for key in ("output", "text", "response"):
            if isinstance(payload.get(key), str):
                return payload[key]
        raise LlmError("balasan provider tanpa isi teks", kind="json")
