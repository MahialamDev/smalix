#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_actions.py - the action protocol between the AI chat and the open SmaliX project.

The model is told (SYSTEM_PROMPT) to emit fenced ```smalix blocks holding JSON objects.
This module parses them (parse_actions) and executes them (ProjectActions) on the
open project.  It is provider-independent and contains no GUI code: the few things that
must touch the editor go through hooks on the `app` object:

    app.backend.proj / .busy / .search_text(q, limit)
    app.open_file(path, line)
    app.ai_before_edit(path)      save unsaved editor text before the file is changed on disk
    app.ai_after_edit(path)       reload the editor / refresh the tree afterwards
    app.ai_run_command(name)      'rebuild' | 'sign' | 'rebuild_sign'

Safety: every path is resolved inside the project folder, and anything that changes
files or starts a build (NEEDS_APPROVAL) is shown to the person for approval by the chat
panel first unless they switched on "auto-apply".
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from smali_utils import is_binary, parse_method_header, read_text, return_patch_body

ACTION_RE = re.compile(r"```smalix[ \t]*\r?\n(.*?)```", re.S)

READ_ONLY = {"list_dir", "read_file", "search", "open_file"}
NEEDS_APPROVAL = {"replace_in_file", "write_file", "patch_return", "rebuild", "sign", "rebuild_sign"}
KNOWN = READ_ONLY | NEEDS_APPROVAL

MAX_RESULT_CHARS = 12000
MAX_READ_LINES = 400
MAX_WRITE_BYTES = 2 * 1024 * 1024
MAX_LIST = 200
MAX_HITS = 80

SYSTEM_PROMPT = """\
You are the built-in assistant of SmaliX Desktop, an APK decompiler and smali editor (apktool + JADX). \
The person has decompiled an Android app they own or are authorised to analyse and works in that project \
folder. Help them understand and modify it.

You can act on the open project by emitting action blocks. An action block is a fenced code block with the \
language tag `smalix` that contains one JSON object (or a JSON list of objects). The app runs them and sends \
the results back as the next message; then you continue. Emit actions only when you need them. When the task \
is finished, answer normally with no action block.

Actions (paths are relative to the project root, forward slashes):
{"action":"list_dir","path":"smali/com/example"}
{"action":"read_file","path":"smali/com/example/Foo.smali","start_line":1,"end_line":200}   (max 400 lines per call)
{"action":"search","query":"isPremium"}      (case-insensitive text search in smali / xml / yml / json / txt)
{"action":"open_file","path":"smali/com/example/Foo.smali","line":42}      (shows the file in the editor)
{"action":"replace_in_file","path":"...","old":"exact existing text","new":"replacement","all":false}
{"action":"write_file","path":"...","content":"complete new file content"}
{"action":"patch_return","path":"smali/com/example/Foo.smali","method":"isPremium()Z","kind":"true"}
    (kind = true | false | null | void; method = name, or name + descriptor to pick one overload)
{"action":"rebuild"}   {"action":"sign"}   {"action":"rebuild_sign"}      (these start a build; watch the Console tab)

Rules:
- read_file output lines start with "N| ". That prefix is not part of the file: never put it in "old" or "new".
- Read a file before editing it. Make "old" long enough to be unique. Keep edits minimal and valid smali \
(balanced .method/.end method, correct .locals/.registers, labels intact).
- Edits, patches and builds are shown to the person for approval first. A declined action comes back as \
"declined by user".
- Do not guess whether a class or method exists: search for it. Do not repeat an identical action.
- The <context> block at the start of a user message describes the open file and may be stale after your \
edits; re-read the file if unsure.
- Be concise. Answer in the language the person writes in (Bangla / English mix is fine).
"""


class ActionError(Exception):
    """An action could not be carried out (bad path, text not found, ...)."""


# --------------------------------------------------------------------------- #
#  Parsing
# --------------------------------------------------------------------------- #
def _one_line(value: Any, limit: int = 140) -> str:
    s = str(value if value is not None else "").replace("\r", "").replace("\n", " ⏎ ")
    return s if len(s) <= limit else s[:limit] + "..."


def _clip_lines(value: Any, prefix: str, max_lines: int = 8) -> str:
    lines = str(value if value is not None else "").replace("\r", "").split("\n")
    shown = lines[:max_lines]
    out = [f"{prefix} {l[:160]}" for l in shown]
    if len(lines) > max_lines:
        out.append(f"{prefix} ... (+{len(lines) - max_lines} more lines)")
    return "\n".join(out)


@dataclass
class Action:
    name: str
    args: dict = field(default_factory=dict)
    error: str = ""

    def summary(self) -> str:
        a, n = self.args, self.name
        if n == "replace_in_file":
            return f"replace_in_file {a.get('path', '?')}"
        if n == "write_file":
            return f"write_file {a.get('path', '?')} ({len(str(a.get('content', '')))} chars)"
        if n == "patch_return":
            return f"patch_return {a.get('path', '?')} :: {a.get('method', '?')} -> {a.get('kind', '?')}"
        if n in ("read_file", "list_dir", "open_file"):
            extra = f":{a['line']}" if n == "open_file" and a.get("line") else ""
            return f"{n} {a.get('path', '') or '/'}{extra}"
        if n == "search":
            return f"search '{_one_line(a.get('query', ''), 60)}'"
        return n

    def preview(self) -> str:
        """Multi-line description shown on the approval card."""
        a, n = self.args, self.name
        if n == "replace_in_file":
            return (f"Edit {a.get('path', '?')}" + (" (all occurrences)" if a.get("all") else "") + "\n"
                    + _clip_lines(a.get("old"), "-") + "\n" + _clip_lines(a.get("new"), "+"))
        if n == "write_file":
            return f"Write {a.get('path', '?')}\n" + _clip_lines(a.get("content"), "+", 6)
        if n == "patch_return":
            return f"Patch {a.get('path', '?')}\n  method {a.get('method', '?')} -> return {a.get('kind', '?')}"
        return {"rebuild": "Rebuild the APK", "sign": "Sign + align the rebuilt APK",
                "rebuild_sign": "Rebuild, then sign + align"}.get(n, self.summary())


def parse_actions(text: str) -> tuple:
    """Split an AI reply into (text without action blocks, [Action, ...])."""
    actions: list = []
    for m in ACTION_RE.finditer(text or ""):
        raw = m.group(1).strip()
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            actions.append(Action("invalid", {}, f"action block is not valid JSON ({e.msg} at char {e.pos})"))
            continue
        for item in obj if isinstance(obj, list) else [obj]:
            if not isinstance(item, dict) or item.get("action") not in KNOWN:
                label = item.get("action") if isinstance(item, dict) else str(item)[:30]
                actions.append(Action(str(label), {}, "unknown action"))
                continue
            actions.append(Action(item["action"], {k: v for k, v in item.items() if k != "action"}))
    return ACTION_RE.sub("", text or "").strip(), actions


# --------------------------------------------------------------------------- #
#  Running something on the Tk thread from the worker thread
# --------------------------------------------------------------------------- #
def call_on_ui(post: Callable, fn: Callable, timeout: float = 90.0) -> Any:
    box: dict = {}
    done = threading.Event()

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = e
        finally:
            done.set()

    post(run)
    if not done.wait(timeout):
        raise ActionError("The UI did not respond in time.")
    if "error" in box:
        raise box["error"]
    return box.get("result")


# --------------------------------------------------------------------------- #
#  Executor
# --------------------------------------------------------------------------- #
class ProjectActions:
    def __init__(self, app) -> None:
        self.app = app

    # -- helpers ---------------------------------------------------------------
    @property
    def root(self) -> Path:
        proj = self.app.backend.proj
        if not proj or not Path(proj).exists():
            raise ActionError("No project is open. Ask the person to open an APK or a decompiled folder.")
        return Path(proj).resolve()

    def _path(self, args: dict, must_exist: bool = True, key: str = "path") -> Path:
        root = self.root
        rel = str(args.get(key) or "").replace("\\", "/").strip().lstrip("/")
        p = (root / rel).resolve()
        try:
            p.relative_to(root)
        except ValueError:
            raise ActionError("Path is outside the project folder.") from None
        if must_exist and not p.exists():
            raise ActionError(f"Not found: {rel or '/'}")
        return p

    def _rel(self, p: Path) -> str:
        try:
            return p.resolve().relative_to(self.root).as_posix() or "/"
        except ValueError:
            return str(p)

    @staticmethod
    def _str(args: dict, key: str, allow_empty: bool = False) -> str:
        v = args.get(key)
        if not isinstance(v, str) or (not v and not allow_empty):
            raise ActionError(f"Missing or invalid '{key}'.")
        return v

    @staticmethod
    def _clip(text: str) -> str:
        if len(text) <= MAX_RESULT_CHARS:
            return text
        return text[:MAX_RESULT_CHARS] + f"\n... (output cut at {MAX_RESULT_CHARS} characters)"

    def _write(self, p: Path, text: str) -> None:
        if len(text.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ActionError("File would be larger than 2 MB.")
        self.app.ai_before_edit(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        self.app.ai_after_edit(p)

    def _read_editable(self, p: Path) -> str:
        if not p.is_file():
            raise ActionError(f"Not a file: {self._rel(p)}")
        if is_binary(p):
            raise ActionError("Binary file - cannot be edited as text.")
        return read_text(p)

    # -- dispatch ----------------------------------------------------------------
    def execute(self, action: Action, post: Callable) -> str:
        fn = getattr(self, "_a_" + action.name, None)
        if fn is None:
            raise ActionError(f"Unsupported action '{action.name}'.")
        if action.name in NEEDS_APPROVAL:
            out = call_on_ui(post, lambda: fn(action.args))     # edits / builds run on the Tk thread
        else:
            out = fn(action.args, post) if action.name == "open_file" else fn(action.args)
        return self._clip(out)

    # -- read-only actions ---------------------------------------------------------
    def _a_list_dir(self, args: dict) -> str:
        p = self._path(args)
        if not p.is_dir():
            raise ActionError(f"Not a folder: {self._rel(p)}")
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = [f"# {self._rel(p)}  ({len(entries)} entries)"]
        for e in entries[:MAX_LIST]:
            lines.append(e.name + "/" if e.is_dir() else f"{e.name}  ({e.stat().st_size} bytes)")
        if len(entries) > MAX_LIST:
            lines.append(f"... {len(entries) - MAX_LIST} more not shown")
        return "\n".join(lines)

    def _a_read_file(self, args: dict) -> str:
        p = self._path(args)
        text = self._read_editable(p)
        lines = text.split("\n")
        try:
            start = max(1, int(args.get("start_line") or 1))
            end = int(args.get("end_line") or (start + MAX_READ_LINES - 1))
        except (TypeError, ValueError):
            raise ActionError("start_line / end_line must be numbers.") from None
        end = min(len(lines), end, start + MAX_READ_LINES - 1)
        if start > len(lines):
            raise ActionError(f"File has only {len(lines)} lines.")
        body = "\n".join(f"{n}| {lines[n - 1]}" for n in range(start, end + 1))
        return f"# {self._rel(p)}  (lines {start}-{end} of {len(lines)})\n{body}"

    def _a_search(self, args: dict) -> str:
        q = self._str(args, "query")
        root = self.root
        hits = self.app.backend.search_text(q, limit=MAX_HITS + 1)
        if not hits:
            return f"No matches for '{q}'."
        lines = []
        for p, n, text in hits[:MAX_HITS]:
            try:
                rel = Path(p).resolve().relative_to(root).as_posix()
            except ValueError:
                rel = str(p)
            lines.append(f"{rel}:{n}: {text[:200]}")
        if len(hits) > MAX_HITS:
            lines.append(f"... more than {MAX_HITS} matches - refine the query")
        return "\n".join(lines)

    def _a_open_file(self, args: dict, post: Callable) -> str:
        p = self._path(args)
        if not p.is_file():
            raise ActionError(f"Not a file: {self._rel(p)}")
        try:
            line = int(args["line"]) if args.get("line") else None
        except (TypeError, ValueError):
            line = None
        call_on_ui(post, lambda: self.app.open_file(p, line=line))
        return f"Opened {self._rel(p)}" + (f" at line {line}" if line else "")

    # -- actions that change things (run on the Tk thread) ---------------------------
    def _a_replace_in_file(self, args: dict) -> str:
        p = self._path(args)
        old, new = self._str(args, "old"), self._str(args, "new", allow_empty=True)
        text = self._read_editable(p)
        count = text.count(old)
        if count == 0:
            raise ActionError("'old' text was not found. Copy it exactly from read_file output "
                              "(without the 'N| ' prefix) and keep the original indentation.")
        if count > 1 and not args.get("all"):
            raise ActionError(f"'old' text occurs {count} times. Add more surrounding lines to make it "
                              "unique, or set \"all\": true.")
        self._write(p, text.replace(old, new) if args.get("all") else text.replace(old, new, 1))
        return f"OK - replaced {count if args.get('all') else 1} occurrence(s) in {self._rel(p)}"

    def _a_write_file(self, args: dict) -> str:
        p = self._path(args, must_exist=False)
        content = self._str(args, "content", allow_empty=True)
        rel = self._rel(p)
        if p == self.root or rel.split("/")[0] in ("build", "dist"):
            raise ActionError("Refusing to write there (build / dist are generated folders).")
        if p.is_dir():
            raise ActionError(f"{rel} is a folder.")
        existed = p.exists()
        self._write(p, content)
        return f"OK - {'overwrote' if existed else 'created'} {rel} ({len(content)} chars)"

    def _a_patch_return(self, args: dict) -> str:
        p = self._path(args)
        spec, kind = self._str(args, "method"), self._str(args, "kind").lower()
        lines = self._read_editable(p).split("\n")
        found = []
        for i, l in enumerate(lines):
            if not l.startswith(".method"):
                continue
            try:
                flags, name, params, ret = parse_method_header(l.strip())
            except Exception:
                continue
            if (f"{name}({params}){ret}" == spec) if "(" in spec else (name == spec):
                found.append((i, flags, ret, l.strip()))
        if not found:
            raise ActionError(f"Method '{spec}' not found in {self._rel(p)}.")
        if len(found) > 1:
            raise ActionError("Several overloads match; give the full signature, e.g. one of:\n"
                              + "\n".join("  " + f[3] for f in found))
        i, flags, ret, header = found[0]
        if "abstract" in flags or "native" in flags:
            raise ActionError("Abstract / native methods have no body to patch.")
        end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith(".end method")), None)
        if end is None:
            raise ActionError("Could not find '.end method'.")
        try:
            body = return_patch_body(kind, ret)
        except ValueError as e:
            raise ActionError(str(e)) from None
        self._write(p, "\n".join(lines[:i + 1] + body + lines[end:]))
        return f"OK - {header} now returns {kind} ({self._rel(p)})"

    def _build(self, name: str) -> str:
        if self.app.backend.busy:
            raise ActionError("Another task is still running - try again in a moment.")
        self.root  # noqa: B018 - raises if no project is open
        self.app.ai_run_command(name)
        return "Started. Progress and the result appear in the Console tab (the build runs in the background)."

    def _a_rebuild(self, args: dict) -> str:
        return self._build("rebuild")

    def _a_sign(self, args: dict) -> str:
        return self._build("sign")

    def _a_rebuild_sign(self, args: dict) -> str:
        return self._build("rebuild_sign")
