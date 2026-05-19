"""
AskAmerica MCP installer UI (Tkinter).

Invoked when the binary is run interactively (not piped by Claude Desktop).
Copies itself to ~/.askamerica/bin/ and writes the Claude Desktop config.
"""
import json
import os
import platform
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk


# ── paths ──────────────────────────────────────────────────────────────────

def _claude_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return (Path.home() / "Library" / "Application Support"
                / "Claude" / "claude_desktop_config.json")
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home())) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _install_path() -> Path:
    name = "askamerica-mcp.exe" if platform.system() == "Windows" else "askamerica-mcp"
    return Path.home() / ".askamerica" / "bin" / name


# ── install logic ──────────────────────────────────────────────────────────

def _do_install(api_key: str, on_status, on_done, on_error):
    try:
        install_path = _install_path()
        install_path.parent.mkdir(parents=True, exist_ok=True)

        on_status("Copying binary…")
        src = sys.executable
        shutil.copy2(src, install_path)
        if platform.system() != "Windows":
            os.chmod(install_path, 0o755)

        on_status("Updating Claude Desktop config…")
        config_path = _claude_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        except Exception:
            config = {}

        config.setdefault("mcpServers", {})["askamerica"] = {
            "command": str(install_path),
            "env": {"ASKAMERICA_API_KEY": api_key},
        }
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        on_done(install_path)
    except Exception as exc:
        on_error(str(exc))


# ── UI ──────────────────────────────────────────────────────────────────────

_BLUE   = "#1B6FE0"
_WHITE  = "#FFFFFF"
_BG     = "#F7F9FC"
_DARK   = "#1A1A2E"
_GRAY   = "#6B7280"
_GREEN  = "#16A34A"
_BORDER = "#D1D5DB"


def run_installer():
    root = tk.Tk()
    root.title("AskAmerica Setup")
    root.configure(bg=_BG)
    root.resizable(False, False)

    # ── centre window ──
    w, h = 500, 420
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # ── fonts ──
    try:
        f_title  = tkfont.Font(family="SF Pro Display", size=22, weight="bold")
        f_body   = tkfont.Font(family="SF Pro Text",    size=13)
        f_small  = tkfont.Font(family="SF Pro Text",    size=11)
        f_button = tkfont.Font(family="SF Pro Text",    size=13, weight="bold")
    except Exception:
        f_title  = tkfont.Font(size=22, weight="bold")
        f_body   = tkfont.Font(size=13)
        f_small  = tkfont.Font(size=11)
        f_button = tkfont.Font(size=13, weight="bold")

    # ── page container ──
    container = tk.Frame(root, bg=_BG)
    container.pack(fill="both", expand=True)

    pages: dict[str, tk.Frame] = {}

    def show(name):
        for p in pages.values():
            p.place_forget()
        pages[name].place(relx=0, rely=0, relwidth=1, relheight=1)

    # ══ PAGE 1 — welcome ══════════════════════════════════════════════════

    p1 = tk.Frame(container, bg=_BG)
    pages["welcome"] = p1

    # header strip
    hdr = tk.Frame(p1, bg=_BLUE, height=6)
    hdr.pack(fill="x")

    tk.Label(p1, text="🇺🇸", font=("", 48), bg=_BG).pack(pady=(28, 0))
    tk.Label(p1, text="AskAmerica", font=f_title, bg=_BG, fg=_DARK).pack()
    tk.Label(p1, text="Query US government data from Claude Desktop",
             font=f_body, bg=_BG, fg=_GRAY).pack(pady=(4, 24))

    # API key entry
    key_frame = tk.Frame(p1, bg=_BG)
    key_frame.pack(fill="x", padx=60)

    tk.Label(key_frame, text="Your API Key", font=f_small,
             bg=_BG, fg=_DARK, anchor="w").pack(fill="x")

    entry_wrap = tk.Frame(key_frame, bg=_BORDER, bd=0)
    entry_wrap.pack(fill="x", pady=(4, 0))

    api_key_var = tk.StringVar()
    api_entry = tk.Entry(entry_wrap, textvariable=api_key_var, font=f_body,
                         bd=0, relief="flat", bg=_WHITE, fg=_DARK,
                         insertbackground=_DARK)
    api_entry.pack(fill="x", padx=2, pady=8, ipady=2, ipadx=8)

    tk.Label(key_frame, text="Get a free key at askamerica.ai",
             font=f_small, bg=_BG, fg=_GRAY).pack(anchor="w", pady=(4, 0))

    error_label = tk.Label(p1, text="", font=f_small, bg=_BG, fg="#DC2626")
    error_label.pack(pady=(8, 0))

    def on_install_click():
        key = api_key_var.get().strip()
        if not key:
            error_label.config(text="Please enter your API key.")
            return
        if not key.startswith("aa_"):
            error_label.config(text="API keys start with aa_")
            return
        error_label.config(text="")
        install_btn.config(state="disabled", text="Installing…")
        progress.pack(pady=(8, 0))
        progress.start(10)

        def on_status(msg):
            root.after(0, lambda: status_var.set(msg))

        def on_done(path):
            root.after(0, lambda: _show_success(path))

        def on_error(msg):
            root.after(0, lambda: _show_error(msg))

        threading.Thread(
            target=_do_install,
            args=(key, on_status, on_done, on_error),
            daemon=True,
        ).start()

    status_var = tk.StringVar()
    tk.Label(p1, textvariable=status_var, font=f_small,
             bg=_BG, fg=_GRAY).pack(pady=(4, 0))

    progress = ttk.Progressbar(p1, mode="indeterminate", length=200)

    install_btn = tk.Button(
        p1, text="Install", font=f_button,
        bg=_BLUE, fg=_WHITE, activebackground="#1558C0", activeforeground=_WHITE,
        relief="flat", bd=0, cursor="hand2", padx=32, pady=10,
        command=on_install_click,
    )
    install_btn.pack(pady=(12, 0))

    # ══ PAGE 2 — success ══════════════════════════════════════════════════

    p2 = tk.Frame(container, bg=_BG)
    pages["success"] = p2

    tk.Frame(p2, bg=_GREEN, height=6).pack(fill="x")
    tk.Label(p2, text="✅", font=("", 52), bg=_BG).pack(pady=(36, 0))
    tk.Label(p2, text="AskAmerica is ready!", font=f_title,
             bg=_BG, fg=_DARK).pack(pady=(8, 0))

    success_detail = tk.Label(p2, text="", font=f_body, bg=_BG, fg=_GRAY,
                               wraplength=380, justify="center")
    success_detail.pack(pady=(8, 0))

    tk.Label(p2, text="Restart Claude Desktop to activate the new tools.",
             font=f_body, bg=_BG, fg=_GRAY, wraplength=380).pack(pady=(16, 0))

    tk.Button(
        p2, text="Done", font=f_button,
        bg=_BLUE, fg=_WHITE, activebackground="#1558C0", activeforeground=_WHITE,
        relief="flat", bd=0, cursor="hand2", padx=32, pady=10,
        command=root.destroy,
    ).pack(pady=(28, 0))

    # ══ PAGE 3 — error ════════════════════════════════════════════════════

    p3 = tk.Frame(container, bg=_BG)
    pages["error"] = p3

    tk.Frame(p3, bg="#DC2626", height=6).pack(fill="x")
    tk.Label(p3, text="❌", font=("", 52), bg=_BG).pack(pady=(36, 0))
    tk.Label(p3, text="Installation failed", font=f_title,
             bg=_BG, fg=_DARK).pack(pady=(8, 0))

    error_detail = tk.Label(p3, text="", font=f_small, bg=_BG, fg=_GRAY,
                             wraplength=400, justify="center")
    error_detail.pack(pady=(8, 0))

    tk.Button(
        p3, text="Try again", font=f_button,
        bg=_BLUE, fg=_WHITE, activebackground="#1558C0", activeforeground=_WHITE,
        relief="flat", bd=0, cursor="hand2", padx=32, pady=10,
        command=lambda: (install_btn.config(state="normal", text="Install"),
                         progress.stop(), progress.pack_forget(),
                         show("welcome")),
    ).pack(pady=(28, 0))

    # ── helpers ──
    def _show_success(path):
        progress.stop()
        success_detail.config(text=f"Installed to {path}")
        show("success")

    def _show_error(msg):
        progress.stop()
        install_btn.config(state="normal", text="Install")
        error_detail.config(text=msg)
        show("error")

    show("welcome")
    api_entry.focus_set()
    root.mainloop()
