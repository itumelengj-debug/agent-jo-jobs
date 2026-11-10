"""Start with the computer — so the job search runs whether or not you
remember to open it.

Autopilot only ran while the app was open, and the app only opened when you
double-clicked it: a job search that stops when you get busy, which is when
you need it. Switched on, this starts Agent Jo Jobs quietly when you sign in
to the computer (no browser window, no console), and the schedule takes it
from there; a run missed while the computer was off happens at the next
start.

It writes one small file in the place each system looks, for your user only,
and removes exactly that file when switched off:
  Windows  a script in your Startup folder
  macOS    a LaunchAgent in ~/Library/LaunchAgents
  Linux    a .desktop entry in ~/.config/autostart
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL = "com.symbolicsynapse.agentjojobs"
NAME = "Agent Jo Jobs"


def _python() -> Path:
    """The app's own Python; on Windows the one that opens no console."""
    exe = Path(sys.executable)
    if os.name == "nt":
        quiet = exe.with_name("pythonw.exe")
        if quiet.exists():
            return quiet
    return exe


def _target(platform: str | None = None, home: Path | None = None) -> Path:
    platform = platform or sys.platform
    home = home or Path.home()
    if platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"{NAME}.vbs"
    if platform == "darwin":
        return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    return Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "autostart" / "agent-jo-jobs.desktop"


def _content(platform: str | None = None) -> str:
    platform = platform or sys.platform
    py, script = str(_python()), str(ROOT / "run_jobs.py")
    if platform.startswith("win"):
        q = lambda s: s.replace('"', '""')
        return ("' Agent Jo Jobs: starts quietly when you sign in. Made by the app;\r\n"
                "' switch it off under Auto-apply, or delete this file.\r\n"
                'Set sh = CreateObject("WScript.Shell")\r\n'
                f'sh.CurrentDirectory = "{q(str(ROOT))}"\r\n'
                f'sh.Run """{q(py)}"" ""{q(script)}"" --no-browser", 0, False\r\n')
    if platform == "darwin":
        x = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0"><dict>\n'
                f'  <key>Label</key><string>{LABEL}</string>\n'
                '  <key>ProgramArguments</key><array>\n'
                f'    <string>{x(py)}</string><string>{x(script)}</string><string>--no-browser</string>\n'
                '  </array>\n'
                f'  <key>WorkingDirectory</key><string>{x(str(ROOT))}</string>\n'
                '  <key>RunAtLoad</key><true/>\n'
                '  <key>ProcessType</key><string>Background</string>\n'
                '</dict></plist>\n')
    return ("[Desktop Entry]\nType=Application\n"
            f"Name={NAME}\nComment=Runs your job search in the background\n"
            f'Exec="{py}" "{script}" --no-browser\n'
            f"Path={ROOT}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")


def status() -> dict:
    f = _target()
    on = f.exists()
    stale = False
    if on:
        try:
            stale = str(ROOT / "run_jobs.py") not in f.read_text("utf-8", errors="replace").replace('""', '"')
        except Exception:
            stale = False
    return {"on": on, "path": str(f), "moved": stale,
            "says": ("Starts when you sign in to this computer." if on and not stale
                     else "Set to start a copy in another folder; switch it off and on to fix it."
                     if stale else "Runs only while you have the app open.")}


def enable() -> dict:
    f = _target()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(_content(), "utf-8", newline="")
        if sys.platform != "win32" and sys.platform != "darwin":
            f.chmod(0o755)
    except Exception as exc:
        return {"ok": False, "error": f"Couldn't write {f}: {type(exc).__name__}: {exc}"}
    return {"ok": True, **status()}


def disable() -> dict:
    f = _target()
    try:
        if f.exists():
            f.unlink()
    except Exception as exc:
        return {"ok": False, "error": f"Couldn't remove {f}: {type(exc).__name__}: {exc}"}
    return {"ok": True, **status()}
