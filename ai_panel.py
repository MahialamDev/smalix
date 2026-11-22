#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_panel.py - right-hand icon toolbar, AI chat panel and AI settings dialog.

    SideBar            vertical icon toolbar (chat, open, save, build, search, tools, settings ...)
    ChatPanel          chat with Claude / Gemini / ChatGPT that can read and edit the open project
    AISettingsDialog   API keys, models and default provider

The widgets hold no project logic: file access goes through ai_actions.ProjectActions and
the hooks that main.py provides (ai_context, ai_before_edit, ai_after_edit, ...).
"""

from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

import ai_client
from ai_actions import NEEDS_APPROVAL, SYSTEM_PROMPT, ActionError, ProjectActions, parse_actions
from config import AI_PROVIDERS, C, IS_WIN, MONO, SMALL, UI_BOLD, UI_FONT, AISettings
from ui_components import make_code_text

ICON_FONT = ("Segoe UI Emoji", 16) if IS_WIN else (UI_FONT[0], 16)


# --------------------------------------------------------------------------- #
#  Tooltip
# --------------------------------------------------------------------------- #
class Tooltip:
    """Small hover label shown to the left of a widget (used by the right-hand sidebar)."""

    def __init__(self, widget, text: str) -> None:
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _e=None) -> None:
        if self.tip:
            return
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tk.Label(tw, text=self.text, bg="#0b0e15", fg=C["fg"], font=(UI_FONT[0], 9), padx=8, pady=4,
                 relief="solid", bd=1).pack()
        tw.update_idletasks()
        x = self.widget.winfo_rootx() - tw.winfo_reqwidth() - 8
        y = self.widget.winfo_rooty() + (self.widget.winfo_height() - tw.winfo_reqheight()) // 2
        tw.wm_geometry(f"+{x}+{y}")

    def _hide(self, _e=None) -> None:
        if self.tip:
            self.tip.destroy()
            self.tip = None


# --------------------------------------------------------------------------- #
#  Right-hand toolbar
# --------------------------------------------------------------------------- #
class SideBar(tk.Frame):
    """
    Vertical icon toolbar.  commands keys: chat open open_folder save rebuild sign rebuild_sign
    clean search tools settings about
    """
    TOP = (("chat", "\U0001F4AC", "AI chat  (Claude / Gemini / ChatGPT)", False),
           None,
           ("open", "\U0001F4E6", "Open APK", True),
           ("open_folder", "\U0001F4C1", "Open decompiled folder", True),
           ("save", "\U0001F4BE", "Save file  (Ctrl+S)", False),
           ("rebuild", "\U0001F528", "Rebuild", True),
           ("sign", "\U0001F50F", "Sign + align", True),
           ("rebuild_sign", "\U0001F680", "Rebuild + sign", True),
           ("clean", "\U0001F9F9", "Clean build / dist", True),
           None,
           ("search", "\U0001F50D", "Search project", False),
           ("tools", "\U0001F9F0", "Tool paths (apktool, jadx, SDK ...)", False))
    BOTTOM = (("settings", "⚙", "Settings - AI providers and API keys"),
              ("about", "ℹ", "About"))

    def __init__(self, parent, commands: dict) -> None:
        super().__init__(parent, bg=C["panel"], highlightbackground=C["border"], highlightthickness=1)
        self.buttons: dict = {}
        self._lock: list = []
        for key, glyph, tip in reversed(self.BOTTOM):          # first packed = lowest
            self._button(key, glyph, tip, commands[key], "bottom")
        for item in self.TOP:
            if item is None:
                tk.Frame(self, bg=C["border"], height=1).pack(side="top", fill="x", padx=10, pady=6)
                continue
            key, glyph, tip, lock = item
            b = self._button(key, glyph, tip, commands[key], "top")
            if lock:
                self._lock.append(b)

    def _button(self, key: str, glyph: str, tip: str, cmd: Callable, side: str) -> ctk.CTkButton:
        b = ctk.CTkButton(self, text=glyph, width=42, height=42, corner_radius=10, font=ICON_FONT,
                          fg_color="transparent", hover_color="#1b2230", text_color=C["fg"], command=cmd)
        b.pack(side=side, padx=7, pady=2)
        Tooltip(b, tip)
        self.buttons[key] = b
        return b

    def set_active(self, key: str, active: bool) -> None:
        self.buttons[key].configure(fg_color=C["sel"] if active else "transparent")

    def set_busy(self, busy: bool) -> None:
        for b in self._lock:
            b.configure(state="disabled" if busy else "normal")


# --------------------------------------------------------------------------- #
#  Chat panel
# --------------------------------------------------------------------------- #
class ChatPanel(tk.Frame):
    WIDTH = 420
    MAX_HISTORY_CHARS = 220_000

    def __init__(self, parent, app, settings: AISettings, actions: ProjectActions,
                 on_settings: Callable[[], None], on_close: Callable[[], None]) -> None:
        super().__init__(parent, bg=C["panel"], width=self.WIDTH,
                         highlightbackground=C["border"], highlightthickness=1)
        self.pack_propagate(False)
        self.app, self.settings, self.actions = app, settings, actions
        self.on_settings, self.on_close = on_settings, on_close
        self.post = app.post
        self.history: list = []
        self._running = False
        self._stop = threading.Event()
        self._attach = True          # plain flags: read from the worker thread
        self._auto = False
        self._labels = {k: v["label"] for k, v in AI_PROVIDERS.items()}
        self._build()
        self.refresh_header()
        self._welcome()

    # -- construction ------------------------------------------------------------
    def _build(self) -> None:
        head = tk.Frame(self, bg=C["panel"])
        head.pack(side="top", fill="x", padx=10, pady=(8, 2))
        tk.Label(head, text="AI ASSISTANT", fg="#c9d4e5", bg=C["panel"], font=SMALL).pack(side="left")
        for text, cmd in (("✕", self.on_close), ("⚙", self.on_settings), ("\U0001F5D1", self.clear)):
            ctk.CTkButton(head, text=text, width=28, height=24, corner_radius=6, font=(ICON_FONT[0], 11),
                          fg_color="#0b0e15", hover_color="#1b2230", text_color=C["fg"],
                          command=cmd).pack(side="right", padx=(4, 0))

        row = tk.Frame(self, bg=C["panel"])
        row.pack(side="top", fill="x", padx=10, pady=(2, 6))
        self.provider_menu = ctk.CTkOptionMenu(row, values=list(self._labels.values()), width=170, height=26,
                                               command=self._on_provider, fg_color="#0b0e15",
                                               button_color="#1b2230", button_hover_color="#243247",
                                               font=(UI_FONT[0], 9))
        self.provider_menu.pack(side="left")
        self.model_label = tk.Label(row, text="", fg=C["dim"], bg=C["panel"], font=(UI_FONT[0], 8))
        self.model_label.pack(side="left", padx=8)

        # bottom part first so the transcript gets whatever is left
        bottom = tk.Frame(self, bg=C["panel"])
        bottom.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        self.status = tk.Label(bottom, text="", fg=C["dim"], bg=C["panel"], font=(UI_FONT[0], 8), anchor="w")
        self.status.pack(fill="x")
        opts = tk.Frame(bottom, bg=C["panel"])
        opts.pack(fill="x", pady=(0, 4))
        self.attach_var = tk.BooleanVar(value=True)
        self.auto_var = tk.BooleanVar(value=False)
        for text, var, attr in (("attach current file", self.attach_var, "_attach"),
                                ("auto-apply edits", self.auto_var, "_auto")):
            ctk.CTkCheckBox(opts, text=text, variable=var, width=20, checkbox_width=15, checkbox_height=15,
                            border_width=1, corner_radius=3, fg_color=C["accent"], hover_color="#17a898",
                            text_color=C["dim"], font=(UI_FONT[0], 9),
                            command=lambda v=var, a=attr: setattr(self, a, bool(v.get()))
                            ).pack(side="left", padx=(0, 10))
        self.input = tk.Text(bottom, height=4, wrap="word", bg="#0b0e15", fg=C["fg"], insertbackground="#ffffff",
                             relief="flat", font=UI_FONT, padx=8, pady=6, highlightthickness=1,
                             highlightbackground=C["border"], highlightcolor=C["accent"], undo=True)
        self.input.pack(fill="x")
        self.input.bind("<Return>", self._on_return)
        btns = tk.Frame(bottom, bg=C["panel"])
        btns.pack(fill="x", pady=(6, 0))
        tk.Label(btns, text="Enter = send   Shift+Enter = new line", fg=C["dim"], bg=C["panel"],
                 font=(UI_FONT[0], 8)).pack(side="left")
        self.send_btn = ctk.CTkButton(btns, text="Send", width=70, height=28, fg_color=C["accent"],
                                      hover_color="#17a898", text_color="#05080f", font=UI_BOLD, command=self.send)
        self.send_btn.pack(side="right")
        self.stop_btn = ctk.CTkButton(btns, text="Stop", width=60, height=28, fg_color="#3b1d1d",
                                      hover_color="#5a2727", text_color=C["fg"], font=UI_BOLD,
                                      state="disabled", command=self.stop)
        self.stop_btn.pack(side="right", padx=(0, 6))

        frame, self.view = make_code_text(self, wrap="word")
        frame.pack(side="top", fill="both", expand=True, padx=6, pady=(0, 2))
        v = self.view
        v.configure(font=UI_FONT, state="disabled", undo=False, padx=8)
        v.bind("<Button-1>", lambda e: v.focus_set(), add="+")
        v.tag_configure("who_user", foreground=C["accent"], font=(UI_FONT[0], 9, "bold"), spacing1=10)
        v.tag_configure("who_ai", foreground=C["cyan"], font=(UI_FONT[0], 9, "bold"), spacing1=10)
        v.tag_configure("user", foreground="#ffffff", lmargin1=6, lmargin2=6)
        v.tag_configure("ai", foreground=C["fg"], lmargin1=6, lmargin2=6)
        v.tag_configure("code", font=MONO, background="#0b0e15", foreground="#e5e7eb",
                        lmargin1=14, lmargin2=14, rmargin=6, spacing1=2)
        v.tag_configure("icode", font=MONO, foreground=C["orange"])
        v.tag_configure("action", font=(MONO[0], 9), foreground=C["yellow"], lmargin1=6, lmargin2=6)
        v.tag_configure("sys", foreground=C["dim"], font=(UI_FONT[0], 9, "italic"), lmargin1=6, lmargin2=6)
        v.tag_configure("err", foreground=C["red"], lmargin1=6, lmargin2=6)
        v.tag_configure("ok", foreground=C["str"], lmargin1=6, lmargin2=6)

    def focus_input(self) -> None:
        self.input.focus_set()

    def refresh_header(self) -> None:
        prov = self.settings.provider
        self.provider_menu.set(self._labels[prov])
        has_key = bool(self.settings.get_key(prov))
        self.model_label.configure(text=self.settings.model(prov) if has_key else "no API key - open ⚙",
                                   fg=C["dim"] if has_key else C["red"])

    def _on_provider(self, label: str) -> None:
        for key, lab in self._labels.items():
            if lab == label:
                self.settings.provider = key
                break
        self.settings.save()
        self.refresh_header()

    def _welcome(self) -> None:
        self._append("Ask anything about the open project. I can read and search files, open them in the "
                     "editor, and - after you approve - edit smali, patch methods and start a rebuild.", "sys")
        if not self.settings.get_key(self.settings.provider):
            self._append("Open ⚙ Settings and paste your Claude / Gemini / ChatGPT API key first.", "sys")

    # -- transcript ------------------------------------------------------------------
    def _append(self, text: str, tag: str = "", newline: bool = True) -> None:
        v = self.view
        v.configure(state="normal")
        v.insert("end", text + ("\n" if newline else ""), tag or ())
        v.configure(state="disabled")
        v.see("end")

    def _show_ai(self, text: str) -> None:
        self._append("Assistant", "who_ai")
        for i, part in enumerate(re.split(r"```[^\n]*\n(.*?)```", text, flags=re.S)):
            if i % 2:                                                 # fenced code
                self._append(part.rstrip("\n"), "code")
                continue
            for j, seg in enumerate(re.split(r"`([^`\n]+)`", part)):   # inline `code`
                if seg:
                    self._append(seg, "icode" if j % 2 else "ai", newline=False)
            self._append("")

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def _welcome_reset(self) -> None:
        self.view.configure(state="normal")
        self.view.delete("1.0", "end")
        self.view.configure(state="disabled")
        self._welcome()

    def clear(self) -> None:
        if self._running:
            return
        self.history.clear()
        self._welcome_reset()

    # -- sending -----------------------------------------------------------------------
    def _on_return(self, e) -> str | None:
        if e.state & 0x1:          # Shift+Enter -> normal newline
            return None
        self.send()
        return "break"

    def _update_buttons(self) -> None:
        self.send_btn.configure(state="disabled" if self._running else "normal")
        self.stop_btn.configure(state="normal" if self._running else "disabled")

    def send(self) -> None:
        if self._running:
            return
        text = self.input.get("1.0", "end-1c").strip()
        if not text:
            return
        provider = self.settings.provider
        key = self.settings.get_key(provider)
        if not key:
            self._append(f"No API key for {AI_PROVIDERS[provider]['label']}. Opening Settings ...", "err")
            self.on_settings()
            return
        self.input.delete("1.0", "end")
        ctx = self.app.ai_context(self._attach)
        self._append("You", "who_user")
        self._append(text, "user")
        self._running = True
        self._stop.clear()
        self._update_buttons()
        threading.Thread(target=self._turn, args=(provider, key, self.settings.model(provider), ctx + text),
                         daemon=True, name="smalix-ai").start()

    def stop(self) -> None:
        if self._running:
            self._stop.set()
            self._set_status("stopping ...")

    def shutdown(self) -> None:
        self._stop.set()

    def _finish(self) -> None:
        self._running = False
        self._update_buttons()
        self._set_status("")
        self.refresh_header()

    def _trim(self) -> None:
        total = sum(len(m["content"]) for m in self.history)
        while total > self.MAX_HISTORY_CHARS and len(self.history) > 2:
            total -= len(self.history.pop(0)["content"])
        while self.history and self.history[0]["role"] != "user":
            self.history.pop(0)

    # -- worker thread -------------------------------------------------------------------
    def _turn(self, provider: str, key: str, model: str, user_msg: str) -> None:
        steps = max(1, int(self.settings.max_steps))
        label = AI_PROVIDERS[provider]["label"]
        try:
            self.history.append({"role": "user", "content": user_msg})
            for _ in range(steps):
                if self._stop.is_set():
                    break
                self._trim()
                self.post(self._set_status, f"{label} is working ...")
                reply = ai_client.chat(provider, key, model, SYSTEM_PROMPT, list(self.history))
                if self._stop.is_set():
                    break
                self.history.append({"role": "assistant", "content": reply or "(empty reply)"})
                clean, actions = parse_actions(reply)
                if clean:
                    self.post(self._show_ai, clean)
                elif not actions:
                    self.post(self._append, "(empty reply)", "sys")
                if not actions:
                    break
                results = self._run_actions(actions)
                if results is None:
                    break
                self.history.append({"role": "user", "content": "Action results:\n\n" + "\n\n".join(results)})
            else:
                self.post(self._append, f"(paused after {steps} steps - send a message to continue)", "sys")
            if self._stop.is_set():
                self.post(self._append, "(stopped)", "sys")
        except ai_client.AIError as e:
            self.post(self._append, f"AI error: {e}", "err")
        except Exception:
            import traceback
            self.post(self._append, traceback.format_exc(), "err")
        finally:
            self.post(self._finish)

    def _run_actions(self, actions: list):
        need = [a for a in actions if a.name in NEEDS_APPROVAL and not a.error]
        approved = True
        if need and not self._auto:
            approved = self._ask_approval(need)
            if self._stop.is_set():
                return None
            if not approved:
                self.post(self._append, "Skipped.", "sys")
        results: list = []
        for a in actions:
            if self._stop.is_set():
                return None
            if a.error:
                results.append(f"[{a.name}] ERROR: {a.error}")
                continue
            if a.name in NEEDS_APPROVAL and not approved:
                results.append(f"[{a.summary()}]\ndeclined by user")
                continue
            self.post(self._append, "▶ " + a.summary(), "action")
            try:
                out = self.actions.execute(a, self.post)
            except ActionError as e:
                out = f"ERROR: {e}"
            except Exception as e:  # noqa: BLE001 - reported back to the model and the person
                out = f"ERROR: {type(e).__name__}: {e}"
            if out.startswith("ERROR"):
                self.post(self._append, out, "err")
            elif a.name in NEEDS_APPROVAL:
                self.post(self._append, out.split("\n")[0], "ok")
            results.append(f"[{a.summary()}]\n{out}")
        return results

    def _ask_approval(self, actions: list) -> bool:
        done, box = threading.Event(), {"ok": False}
        self.post(self._show_approval, actions, done, box)
        while not done.wait(0.25):
            if self._stop.is_set():
                return False
        return box["ok"]

    # -- approval card -----------------------------------------------------------------------
    def _show_approval(self, actions: list, done: threading.Event, box: dict) -> None:
        card = tk.Frame(self.view, bg="#101a2b", highlightbackground=C["yellow"], highlightthickness=1)
        title = tk.Label(card, text="The assistant wants to:", fg=C["yellow"], bg="#101a2b",
                         font=(UI_FONT[0], 9, "bold"), anchor="w")
        title.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(card, text="\n\n".join(a.preview() for a in actions), fg=C["fg"], bg="#101a2b", font=(MONO[0], 9),
                 justify="left", anchor="w", wraplength=self.WIDTH - 90).pack(fill="x", padx=8)
        row = tk.Frame(card, bg="#101a2b")
        row.pack(fill="x", padx=8, pady=8)

        def decide(ok: bool) -> None:
            if done.is_set():
                return
            box["ok"] = ok
            for b in (apply_btn, skip_btn):
                b.configure(state="disabled")
            title.configure(text="Approved" if ok else "Skipped", fg=C["str"] if ok else C["dim"])
            card.configure(highlightbackground=C["str"] if ok else C["border"])
            done.set()

        apply_btn = ctk.CTkButton(row, text="Apply", width=80, height=28, fg_color=C["green"], hover_color="#1aa04d",
                                  text_color="#04140a", font=UI_BOLD, command=lambda: decide(True))
        apply_btn.pack(side="left")
        skip_btn = ctk.CTkButton(row, text="Skip", width=70, height=28, fg_color="#334155", hover_color="#475569",
                                 text_color="#ffffff", font=UI_BOLD, command=lambda: decide(False))
        skip_btn.pack(side="left", padx=(8, 0))
        v = self.view
        v.configure(state="normal")
        v.window_create("end", window=card)
        v.insert("end", "\n")
        v.configure(state="disabled")
        v.see("end")


# --------------------------------------------------------------------------- #
#  Settings dialog
# --------------------------------------------------------------------------- #
class AISettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, settings: AISettings, on_saved: Callable[[], None]) -> None:
        super().__init__(parent)
        self.s, self.on_saved = settings, on_saved
        self.title("Settings - AI providers")
        self.geometry("740x700")
        self.configure(fg_color=C["bg"])
        self.transient(parent)
        self.after(100, self.grab_set)
        self._q: queue.Queue = queue.Queue()
        self.key_entries: dict = {}
        self.model_entries: dict = {}
        self.status: dict = {}
        self._orig: dict = {}

        ctk.CTkLabel(self, text="AI assistant", font=(UI_FONT[0], 15, "bold")).pack(anchor="w", padx=16, pady=(14, 0))
        ctk.CTkLabel(self, text="Paste your own API keys. Requests go straight from this PC to the provider.",
                     text_color=C["dim"], font=(UI_FONT[0], 9)).pack(anchor="w", padx=16, pady=(0, 8))

        top = tk.Frame(self, bg=C["bg"])
        top.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkLabel(top, text="Default provider", width=130, anchor="w").pack(side="left")
        self._labels = {k: v["label"] for k, v in AI_PROVIDERS.items()}
        self.provider_menu = ctk.CTkOptionMenu(top, values=list(self._labels.values()), width=220,
                                               fg_color="#0b0e15", button_color="#1b2230")
        self.provider_menu.set(self._labels[settings.provider])
        self.provider_menu.pack(side="left")

        for prov, info in AI_PROVIDERS.items():
            self._provider_card(prov, info)

        steps = tk.Frame(self, bg=C["bg"])
        steps.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkLabel(steps, text="Max AI steps per request", width=170, anchor="w").pack(side="left")
        self.steps_entry = ctk.CTkEntry(steps, width=60, fg_color="#0b0e15", border_color=C["border"])
        self.steps_entry.insert(0, str(settings.max_steps))
        self.steps_entry.pack(side="left")
        ctk.CTkLabel(steps, text="(each read / edit round trip is one step)", text_color=C["dim"],
                     font=(UI_FONT[0], 9)).pack(side="left", padx=8)

        ctk.CTkLabel(self, text=settings.storage_note(), text_color=C["dim"], font=(UI_FONT[0], 9),
                     wraplength=700, justify="left").pack(anchor="w", padx=16, pady=(10, 0))

        bf = tk.Frame(self, bg=C["bg"])
        bf.pack(pady=14)
        ctk.CTkButton(bf, text="Save", fg_color=C["teal"], text_color="#05080f", command=self._save).pack(side="left", padx=6)
        ctk.CTkButton(bf, text="Cancel", fg_color="#334155", text_color="#ffffff",
                      command=self.destroy).pack(side="left", padx=6)
        self.after(150, self._poll)

    def _provider_card(self, prov: str, info: dict) -> None:
        card = ctk.CTkFrame(self, fg_color=C["panel"], border_width=1, border_color=C["border"])
        card.pack(fill="x", padx=16, pady=5)
        ctk.CTkLabel(card, text=info["label"], font=UI_BOLD, text_color=C["accent"]).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(8, 2))
        ctk.CTkLabel(card, text="API key", width=70, anchor="w").grid(row=1, column=0, padx=(12, 0), pady=4)
        key = ctk.CTkEntry(card, width=390, show="•", fg_color="#0b0e15", border_color=C["border"])
        current = self.s.get_key(prov)
        key.insert(0, current)
        key.grid(row=1, column=1, pady=4)
        self.key_entries[prov] = key
        self._orig[prov] = current

        def toggle(e=key) -> None:
            e.configure(show="" if e.cget("show") else "•")

        ctk.CTkButton(card, text="\U0001F441", width=32, font=ICON_FONT, fg_color="#0b0e15", hover_color="#1b2230",
                      command=toggle).grid(row=1, column=2, padx=6)
        ctk.CTkButton(card, text="Test", width=60, fg_color=C["blue"], text_color="#ffffff",
                      command=lambda p=prov: self._test(p)).grid(row=1, column=3, padx=(0, 12))
        ctk.CTkLabel(card, text="Model", width=70, anchor="w").grid(row=2, column=0, padx=(12, 0), pady=(0, 4))
        model = ctk.CTkEntry(card, width=390, fg_color="#0b0e15", border_color=C["border"],
                             placeholder_text=info["model"])
        if prov in self.s.models:
            model.insert(0, self.s.models[prov])
        model.grid(row=2, column=1, pady=(0, 4))
        self.model_entries[prov] = model
        st = ctk.CTkLabel(card, text="", text_color=C["dim"], font=(UI_FONT[0], 9), anchor="w", wraplength=640,
                          justify="left")
        st.grid(row=3, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 8))
        self.status[prov] = st

    # -- test connection ---------------------------------------------------------------------
    def _test(self, prov: str) -> None:
        key = self.key_entries[prov].get().strip().strip('"')
        model = self.model_entries[prov].get().strip() or AI_PROVIDERS[prov]["model"]
        if not key:
            self.status[prov].configure(text="Enter an API key first.", text_color=C["red"])
            return
        self.status[prov].configure(text="Testing ...", text_color=C["dim"])

        def work() -> None:
            try:
                ai_client.chat(prov, key, model, "Reply with the single word OK.",
                               [{"role": "user", "content": "ping"}], max_tokens=256, timeout=45)
                self._q.put((prov, True, f"Connection OK ({model})"))
            except ai_client.AIError as e:
                self._q.put((prov, False, str(e)))
            except Exception as e:  # noqa: BLE001
                self._q.put((prov, False, f"{type(e).__name__}: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                prov, ok, msg = self._q.get_nowait()
                self.status[prov].configure(text=msg, text_color=C["str"] if ok else C["red"])
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(150, self._poll)

    # -- save ------------------------------------------------------------------------------------
    def _save(self) -> None:
        s = self.s
        try:
            for prov in AI_PROVIDERS:
                new = self.key_entries[prov].get().strip().strip('"')
                if new != self._orig[prov]:
                    s.set_key(prov, new) if new else s.delete_key(prov)
                model = self.model_entries[prov].get().strip()
                if model and model != AI_PROVIDERS[prov]["model"]:
                    s.models[prov] = model
                else:
                    s.models.pop(prov, None)
            for key, label in self._labels.items():
                if label == self.provider_menu.get():
                    s.provider = key
            try:
                s.max_steps = max(1, min(30, int(self.steps_entry.get())))
            except ValueError:
                pass
            s.save()
        except OSError as e:
            messagebox.showerror("SmaliX", f"Cannot save settings:\n{e}", parent=self)
            return
        self.destroy()
        self.on_saved()
