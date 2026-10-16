"""Start Agent Jo Jobs.

Its own port (8766) so it can run alongside the main app rather than instead
of it — they share the data, the engines and the audit trail, so having both
open is the normal case, not a conflict.
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_PORT = 8766
NEEDED = ("fastapi", "uvicorn", "httpx", "multipart", "pypdf", "docx", "bs4", "cryptography")


def inside_a_zip(path: Path) -> bool:
    """Opened straight from the zip: Windows ran it from a temporary copy,
    which it deletes. Nothing set up there lasts."""
    p = str(path).lower().replace("/", "\\")
    return "\\appdata\\local\\temp\\" in p and ".zip" in p


def _missing() -> list:
    import importlib
    gone = []
    for name in NEEDED:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            gone.append(getattr(exc, "name", None) or name)
    return gone


def _broken_dependencies() -> list:
    """`pip check` names a package another one needs that isn't there
    (fastapi without annotated-doc, after an install that was cut short)."""
    import re as _re
    import subprocess
    try:
        out = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120).stdout
    except Exception:
        return []
    return sorted(set(_re.findall(r"requires ([A-Za-z0-9_.\-]+), which is not installed", out)))


def repair() -> bool:
    """Put back missing packages, once, and say so. True when it worked."""
    import subprocess
    print("\n  Some of its packages are missing or incomplete. Putting them back")
    print("  (a minute or two; this only happens once)...\n", flush=True)
    cmds = [[sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"), "--quiet"]]
    extra = _broken_dependencies()
    if extra:
        cmds.append([sys.executable, "-m", "pip", "install", *extra, "--quiet"])
    for cmd in cmds:
        if subprocess.run(cmd, cwd=ROOT).returncode != 0:
            return False
    extra = _broken_dependencies()
    if extra:
        subprocess.run([sys.executable, "-m", "pip", "install", *extra, "--quiet"], cwd=ROOT)
    import importlib
    importlib.invalidate_caches()
    return not _missing() and not _broken_dependencies()


def _free_port(start: int, tries: int = 12) -> int:
    for p in range(start, start + tries):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent Jo Jobs")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if inside_a_zip(ROOT):
        print("\n  Agent Jo Jobs is running from inside the zip file, so Windows is using")
        print("  a temporary copy that it deletes later. Nothing set up there will last.")
        print("\n  To fix it:")
        print("    1. Close this window.")
        print("    2. Right-click the zip, choose Extract All, and pick a folder such as Documents.")
        print("    3. In the extracted folder, double-click install.bat.\n")
        return 3
    if _missing() or _broken_dependencies():
        if not repair():
            print("\n  It couldn't put its packages back by itself. Run install.bat again;")
            print("  if that fails too, send the last lines of install.log.\n")
            return 1
        print("  Packages repaired.\n")
    import uvicorn

    # its own data now: on the first start, copy the job search's data across
    # from Agent Jo's folder, where it used to live (agent/migrate.py)
    from agent import backup as _bk          # a restore finished at start-up
    if _bk.apply_pending():
        print("  Finished restoring your backup.")
    from agent import migrate
    _moved = migrate.run()
    if _moved.get("copied"):
        print("  Brought your job data over from Agent Jo: "
              + ", ".join(_moved["copied"]))
    from jobs.server import app, get_memory, start_scheduler
    get_memory()                       # same store the main app uses
    start_scheduler()                  # its own daily run, claimed so it
                                       # never doubles with the main app
    from agent import phone            # the phone companion, if you turned it on
    _ph = phone.start()
    if _ph.get("running"):
        print(f"  Phone companion on port {_ph['port']} (Engines → Phone companion)")
    elif _ph.get("error"):
        print("  Phone companion: " + _ph["error"])

    port = _free_port(args.port)
    url = f"http://127.0.0.1:{port}"
    print(f"  Agent Jo Jobs -> {url}")
    print("  (leave this window open; Ctrl+C to stop)")

    if not args.no_browser:
        def _open():
            # wait for the server rather than opening into a refused
            # connection, which looks like the app is broken
            for _ in range(40):
                with socket.socket() as s:
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        webbrowser.open(url)
                        return
                time.sleep(0.25)
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
