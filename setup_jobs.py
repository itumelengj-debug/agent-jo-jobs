"""Set up Agent Jo Jobs: its own Python environment, its packages, and the
browser that portal applications drive.

    python setup_jobs.py            set up, or bring an existing setup up to date
    python setup_jobs.py --dry-run  say what it would do, and do nothing

The Windows installer runs this with the Python it found or installed, so a
PATH that hasn't caught up with a fresh Python can't break it. install.bat
does the same steps by hand. Exit code 0 means the app can start; anything
else means look at install.log. A browser that won't download is a warning,
not a failure: everything but portal applications works without it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = HERE / ".venv"
LOG = HERE / "install.log"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def log(text: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")


def steps() -> list:
    """(what it says, the command, whether failing stops setup)."""
    py = venv_python()
    out = []
    if not py.exists():
        out.append(("Creating its Python environment",
                    [sys.executable, "-m", "venv", str(VENV)], True))
    out += [
        ("Updating pip", [str(py), "-m", "pip", "install", "--upgrade", "pip", "--quiet"], False),
        ("Installing its packages (a few minutes the first time)",
         [str(py), "-m", "pip", "install", "-r", str(HERE / "requirements.txt"), "--quiet"], True),
        ("Checking it loads", [str(py), "-c", "import jobs.server"], True),
        ("Downloading the browser for portal applications (about 150 MB)",
         [str(py), "-m", "playwright", "install", "chromium"], False),
    ]
    return out


def main(argv: list = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if sys.version_info < (3, 10):
        print("  Agent Jo Jobs needs Python 3.10 or newer.")
        return 2
    if "--dry-run" in argv:
        for what, cmd, needed in steps():
            print(f"  {what}: {' '.join(cmd)}" + ("" if needed else "  (optional)"))
        return 0
    LOG.write_text(f"Agent Jo Jobs setup - {time.strftime('%Y-%m-%d %H:%M')} - "
                   f"python {sys.version.split()[0]} at {sys.executable}\n", "utf-8")
    print("\n  Setting up Agent Jo Jobs\n")
    for what, cmd, needed in steps():
        print(f"  {what}...", flush=True)
        log(f"\n$ {' '.join(cmd)}")
        try:
            # read as UTF-8, never the Windows codepage: a character pip or
            # Playwright prints that cp1252 can't decode stopped setup here
            p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            rc, output = p.returncode, (p.stdout or "") + (p.stderr or "")
        except OSError as exc:
            rc, output = 1, f"{type(exc).__name__}: {exc}"
        log(output)
        log(f"exit {rc}")
        if rc == 0:
            continue
        if needed:
            print(f"\n  That step failed. What happened is in:\n    {LOG}")
            return 1
        print("    (didn't work - not needed to start; see install.log)")
    print("\n  Ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
