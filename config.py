#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py - constants, theme and external-tool discovery for SmaliX Desktop.

Nothing in this module touches the GUI toolkit, so it can be imported from
the backend thread code as well as from the UI code.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------- #
#  Application constants
# --------------------------------------------------------------------------- #
APP_NAME = "SmaliX Desktop"
APP_VERSION = "1.4.0"
IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0  # hide console windows of child processes

APP_DIR = Path.home() / ".smalix_desktop"
CONFIG_FILE = APP_DIR / "config.json"
AI_FILE = APP_DIR / "ai_settings.json"       # provider / model / steps (no secrets)
AI_KEYS_FILE = APP_DIR / "ai_keys.json"      # fallback key store when no OS keyring is available
WORK_ROOT = APP_DIR / "projects"
DEBUG_KEYSTORE = APP_DIR / "smalix_debug.keystore"
JADX_HOME = APP_DIR / "jadx"

# --------------------------------------------------------------------------- #
#  Theme
# --------------------------------------------------------------------------- #
MONO = ("Consolas", 10) if IS_WIN else ("DejaVu Sans Mono", 10)
UI_FONT = ("Segoe UI", 10) if IS_WIN else ("DejaVu Sans", 10)
UI_BOLD = (UI_FONT[0], 10, "bold")
SMALL = (UI_FONT[0], 8, "bold")

C = {
    "bg": "#070b14",
    "panel": "#0c1220",
    "code": "#0a0f1b",
    "gutter": "#080c16",
    "border": "#1b2a3d",
    "accent": "#1fc8b4",
    "fg": "#d6deeb",
    "dim": "#6b7a90",
    "sel": "#1f3a5f",
    "cur": "#13233a",
    "teal": "#1fc8b4",
    "blue": "#5b8cf0",
    "purple": "#a24be0",
    "green": "#22c55e",
    "dark": "#10151f",
    "pink": "#ff6ac1",
    "cyan": "#38bdf8",
    "orange": "#f59e6b",
    "yellow": "#fbbf24",
    "str": "#4ade80",
    "red": "#f87171",
}


class ToolError(Exception):
    """Raised when an external tool is missing or fails."""


# --------------------------------------------------------------------------- #
#  Tool discovery / persistence
# --------------------------------------------------------------------------- #
class Tools:
    """Locates java, keytool, apktool, zipalign, apksigner and jadx."""

    KEYS = ["java", "keytool", "apktool", "zipalign", "apksigner", "jadx"]

    def __init__(self) -> None:
        self.paths: dict[str, str] = {}
        self.load()
        self.detect(only_missing=True)

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        try:
            if CONFIG_FILE.exists():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self.paths = {k: v for k, v in data.get("tools", {}).items() if v}
        except Exception:
            self.paths = {}

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({"tools": self.paths}, indent=2), encoding="utf-8")

    # -- Android SDK -------------------------------------------------------
    def sdk_roots(self) -> list[Path]:
        roots: list[Path] = []
        for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]))
        if IS_WIN and os.environ.get("LOCALAPPDATA"):
            roots.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk")
        roots += [Path.home() / "Android" / "Sdk", Path.home() / "Library" / "Android" / "sdk"]
        # <sdk>/build-tools/<ver>/zipalign  ->  <sdk>
        for key in ("zipalign", "apksigner"):
            p = self.paths.get(key)
            if p:
                try:
                    roots.append(Path(p).resolve().parents[2])
                except IndexError:
                    pass
        seen: set[Path] = set()
        out: list[Path] = []
        for r in roots:
            if r not in seen and r.is_dir():
                seen.add(r)
                out.append(r)
        return out

    def build_tools_dirs(self) -> list[Path]:
        found: list[Path] = []
        for root in self.sdk_roots():
            bt = root / "build-tools"
            if bt.is_dir():
                def ver(p: Path):
                    return tuple(int(n) for n in re.findall(r"\d+", p.name))
                found += sorted((p for p in bt.iterdir() if p.is_dir()), key=ver, reverse=True)
        return found

    def latest_android_jar(self) -> Optional[Path]:
        """Newest <sdk>/platforms/android-NN/android.jar (used as a modern apktool framework)."""
        best: Optional[Path] = None
        best_key = (-1, -1)
        for root in self.sdk_roots():
            plat = root / "platforms"
            if not plat.is_dir():
                continue
            for d in plat.iterdir():
                m = re.match(r"android-(\d+)(?:\.(\d+))?$", d.name)
                jar = d / "android.jar"
                if m and jar.exists():
                    key = (int(m.group(1)), int(m.group(2) or 0))
                    if key > best_key:
                        best, best_key = jar, key
        return best

    # -- auto-detection ----------------------------------------------------
    def detect(self, only_missing: bool = False) -> None:
        def need(key: str) -> bool:
            return not (only_missing and self.paths.get(key) and Path(self.paths[key]).exists())

        if need("java"):
            p = shutil.which("java")
            if p:
                self.paths["java"] = p
        if need("keytool"):
            p = shutil.which("keytool")
            if not p and self.paths.get("java"):
                cand = Path(self.paths["java"]).parent / ("keytool.exe" if IS_WIN else "keytool")
                p = str(cand) if cand.exists() else None
            if p:
                self.paths["keytool"] = p
        if need("apktool"):
            p = shutil.which("apktool")
            if not p:
                here = Path(__file__).resolve().parent
                for base in (Path.cwd(), here, APP_DIR):
                    jars = sorted(base.glob("apktool*.jar"), reverse=True)
                    if jars:
                        p = str(jars[0])
                        break
            if p:
                self.paths["apktool"] = p
        for key, names in (("zipalign", ["zipalign.exe", "zipalign"]),
                           ("apksigner", ["apksigner.bat", "apksigner"])):
            if need(key):
                p = shutil.which(key)
                if not p:
                    for bt in self.build_tools_dirs():
                        for n in names:
                            if (bt / n).exists():
                                p = str(bt / n)
                                break
                        if p:
                            break
                if p:
                    self.paths[key] = p
        if need("jadx"):
            p = shutil.which("jadx")
            if p:
                self.paths["jadx"] = p

    # -- accessors ---------------------------------------------------------
    def get(self, key: str) -> Optional[str]:
        p = self.paths.get(key)
        return p if p and Path(p).exists() else None

    def require(self, key: str) -> str:
        p = self.get(key)
        if not p:
            raise ToolError(f"'{key}' not found. Use the 'Tools' button to set its path "
                            f"(or add it to PATH) and try again.")
        return p

    def apktool_cmd(self) -> list[str]:
        p = self.require("apktool")
        if p.lower().endswith(".jar"):
            return [self.require("java"), "-jar", p]
        return [p]


# --------------------------------------------------------------------------- #
#  AI assistant settings (provider, model, API keys)
# --------------------------------------------------------------------------- #
AI_PROVIDERS = {
    "claude": {"label": "Claude (Anthropic)", "env": "ANTHROPIC_API_KEY", "model": "claude-sonnet-5-5"},
    "gemini": {"label": "Gemini (Google)", "env": "GEMINI_API_KEY", "model": "gemini-2.5-flash"},
    "openai": {"label": "ChatGPT (OpenAI)", "env": "OPENAI_API_KEY", "model": "gpt-4o"},
}
KEYRING_SERVICE = "smalix-desktop"


class AISettings:
    """
    Non-secret settings live in ai_settings.json.  API keys are kept in the OS keyring
    (Windows Credential Manager / macOS Keychain / Secret Service) when the optional
    `keyring` package is installed; otherwise in ai_keys.json inside the user's app folder
    (permissions 600 where supported).  Environment variables are a read-only last resort.
    """

    def __init__(self) -> None:
        self.provider = "claude"
        self.models: dict[str, str] = {}
        self.max_steps = 8
        self.last_folder = ""
        self.load()

    # -- plain settings ------------------------------------------------------
    def load(self) -> None:
        try:
            if AI_FILE.exists():
                d = json.loads(AI_FILE.read_text(encoding="utf-8"))
                if d.get("provider") in AI_PROVIDERS:
                    self.provider = d["provider"]
                self.models = {k: v for k, v in d.get("models", {}).items() if k in AI_PROVIDERS and v}
                self.max_steps = max(1, min(30, int(d.get("max_steps", 8))))
                self.last_folder = str(d.get("last_folder", ""))
        except Exception:
            pass

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        AI_FILE.write_text(json.dumps({"provider": self.provider, "models": self.models,
                                       "max_steps": self.max_steps, "last_folder": self.last_folder},
                                      indent=2), encoding="utf-8")

    def model(self, provider: Optional[str] = None) -> str:
        p = provider or self.provider
        return self.models.get(p) or AI_PROVIDERS[p]["model"]

    # -- API keys --------------------------------------------------------------
    @staticmethod
    def _keyring():
        try:
            import keyring
            from keyring.backends import fail
            if isinstance(keyring.get_keyring(), fail.Keyring):
                return None
            return keyring
        except Exception:
            return None

    def _file_keys(self) -> dict:
        try:
            if AI_KEYS_FILE.exists():
                return json.loads(AI_KEYS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _write_file_keys(self, data: dict) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if not data:
            AI_KEYS_FILE.unlink(missing_ok=True)
            return
        AI_KEYS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(AI_KEYS_FILE, 0o600)
        except OSError:
            pass

    def get_key(self, provider: str) -> str:
        kr = self._keyring()
        if kr:
            try:
                v = kr.get_password(KEYRING_SERVICE, provider)
                if v:
                    return v
            except Exception:
                pass
        v = self._file_keys().get(provider, "")
        if v:
            return v
        return os.environ.get(AI_PROVIDERS[provider]["env"], "")

    def set_key(self, provider: str, key: str) -> str:
        """Store a key; returns 'keyring' or 'file' (where it ended up)."""
        kr = self._keyring()
        if kr:
            try:
                kr.set_password(KEYRING_SERVICE, provider, key)
                data = self._file_keys()
                if data.pop(provider, None) is not None:      # don't leave a stale plain-text copy
                    self._write_file_keys(data)
                return "keyring"
            except Exception:
                pass
        data = self._file_keys()
        data[provider] = key
        self._write_file_keys(data)
        return "file"

    def delete_key(self, provider: str) -> None:
        kr = self._keyring()
        if kr:
            try:
                kr.delete_password(KEYRING_SERVICE, provider)
            except Exception:
                pass
        data = self._file_keys()
        if data.pop(provider, None) is not None:
            self._write_file_keys(data)

    def storage_note(self) -> str:
        if self._keyring():
            return "Keys are stored in your operating system's secure keyring."
        return (f"Keys are stored in {AI_KEYS_FILE} (plain text, your user folder only). "
                "Run 'pip install keyring' to use the OS secure keyring instead.")
