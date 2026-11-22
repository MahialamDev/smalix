#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_client.py - minimal chat clients for Claude, Gemini and ChatGPT (standard library only).

    chat(provider, api_key, model, system, messages) -> str

`messages` is a list of {"role": "user" | "assistant", "content": str}.  The call is
blocking, so run it on a worker thread.  API keys are only ever sent in request
headers to the provider's own endpoint and never appear in error messages.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

ENDPOINTS = {
    "claude": "https://api.anthropic.com/v1/messages",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    "openai": "https://api.openai.com/v1/chat/completions",
}
RETRY_CODES = (429, 500, 502, 503, 504, 529)


class AIError(Exception):
    """Any failure talking to an AI provider (network, auth, quota, bad reply)."""


def _merge(messages: list) -> list:
    """Collapse consecutive same-role messages (some APIs insist on alternation)."""
    out: list = []
    for m in messages:
        role, content = m["role"], str(m["content"])
        if out and out[-1]["role"] == role:
            out[-1] = {"role": role, "content": out[-1]["content"] + "\n\n" + content}
        else:
            out.append({"role": role, "content": content})
    return out


def _err_message(raw: str) -> str:
    try:
        data = json.loads(raw)
        err = data.get("error", data)
        if isinstance(err, dict):
            return str(err.get("message") or err)[:400]
        return str(err)[:400]
    except Exception:
        return raw.strip()[:300] or "no details"


def _post(url: str, headers: dict, body: dict, timeout: int, retries: int = 2) -> dict:
    payload = json.dumps(body).encode("utf-8")
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = _err_message(e.read().decode("utf-8", "replace"))
            if e.code in RETRY_CODES and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            hint = " (check the API key in Settings)" if e.code in (401, 403) else ""
            raise AIError(f"HTTP {e.code}: {msg}{hint}") from None
        except urllib.error.URLError as e:
            raise AIError(f"Network error: {e.reason}") from None
        except (socket.timeout, TimeoutError):
            raise AIError("The request timed out.") from None
        except json.JSONDecodeError:
            raise AIError("The provider returned an invalid response.") from None
    raise AIError("Request failed.")


# --------------------------------------------------------------------------- #
#  Providers
# --------------------------------------------------------------------------- #
def _claude(key: str, model: str, system: str, messages: list, max_tokens: int, timeout: int) -> str:
    data = _post(ENDPOINTS["claude"],
                 {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                 {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}, timeout)
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _gemini(key: str, model: str, system: str, messages: list, max_tokens: int, timeout: int) -> str:
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
                for m in messages]
    data = _post(ENDPOINTS["gemini"].format(model=model),
                 {"x-goog-api-key": key, "content-type": "application/json"},
                 {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                  "generationConfig": {"maxOutputTokens": max_tokens}}, timeout)
    block = (data.get("promptFeedback") or {}).get("blockReason")
    if block:
        raise AIError(f"Gemini blocked the request ({block}).")
    cands = data.get("candidates") or []
    if not cands:
        raise AIError("Gemini returned no answer.")
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    if not text and cands[0].get("finishReason") not in (None, "STOP"):
        raise AIError(f"Gemini stopped without text (finishReason={cands[0].get('finishReason')}).")
    return text


def _openai(key: str, model: str, system: str, messages: list, max_tokens: int, timeout: int) -> str:
    data = _post(ENDPOINTS["openai"],
                 {"Authorization": "Bearer " + key, "content-type": "application/json"},
                 {"model": model, "max_completion_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system}] + messages}, timeout)
    choices = data.get("choices") or []
    if not choices:
        raise AIError("OpenAI returned no answer.")
    return choices[0].get("message", {}).get("content") or ""


_DISPATCH = {"claude": _claude, "gemini": _gemini, "openai": _openai}


def chat(provider: str, api_key: str, model: str, system: str, messages: list,
         max_tokens: int = 8192, timeout: int = 180) -> str:
    if provider not in _DISPATCH:
        raise AIError(f"Unknown provider '{provider}'.")
    if not api_key.strip():
        raise AIError("No API key set. Open Settings and paste your key.")
    if not messages:
        raise AIError("Nothing to send.")
    return _DISPATCH[provider](api_key.strip(), model.strip(), system, _merge(messages), max_tokens, timeout)
