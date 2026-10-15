"""Bring your job data over from Agent Jo, once.

Agent Jo Jobs used to live inside Agent Jo and keep its data in Agent Jo's
folder (~/.local_agent). It's its own app now, with its own folder
(~/.agent_jo_jobs, or AGENT_JOBS_HOME), and on its first start this copies
across what the job search needs:

    jobscout/      roles, profile and CVs, auto-apply settings, sources, alerts
    portal/        the browser profile with your job-site logins
    engines.json   your engines, and secret.key that unseals their keys
    settings.json  model and engine settings
    the daily run  the "Job scout — daily" schedule, enabled as it was

It copies. Nothing is moved or deleted, and Agent Jo's folder is left exactly
as it was. It runs once: a note in the new folder records what was copied.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from . import config

OLD_HOME = Path(os.environ.get("AGENT_JO_HOME") or (Path.home() / ".local_agent"))
NOTE = ".copied-from-agent-jo.json"
FOLDERS = ("jobscout", "portal")
FILES = ("engines.json", "secret.key", "settings.json")
# A browser profile carries hundreds of MB of caches and the lock files of
# its last run. The logins are in its cookies and Local State, not in these.
_SKIP = {"Cache", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache",
         "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache", "Service Worker",
         "Crashpad", "component_crx_cache", "SingletonLock", "SingletonCookie",
         "SingletonSocket", "lockfile"}


def _ignore(_dir, names):
    return [n for n in names if n in _SKIP]


def _daily_runs(old_db: Path) -> list:
    """The job schedules in Agent Jo's database, read without touching it."""
    if not old_db.exists():
        return []
    con = sqlite3.connect(f"file:{old_db.as_posix()}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM schedules").fetchall()
        return [dict(r) for r in rows
                if (dict(r).get("action") or "") == "jobscout"]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def run(old: Path | None = None, new: Path | None = None) -> dict:
    old = Path(old or OLD_HOME)
    new = Path(new or config.AGENT_HOME)
    note = new / NOTE
    if note.exists():
        return {"ran": False, "why": "already done", "copied": []}
    try:
        if old.resolve() == new.resolve():
            return {"ran": False, "why": "same folder", "copied": []}
    except OSError:
        pass
    new.mkdir(parents=True, exist_ok=True)
    copied, skipped = [], []
    if old.is_dir():
        for name in FOLDERS:
            src, dst = old / name, new / name
            if src.is_dir() and not dst.exists():
                try:
                    shutil.copytree(src, dst, ignore=_ignore)
                    copied.append(name + "/")
                except Exception as exc:        # a file another program holds
                    skipped.append(f"{name}/: {type(exc).__name__}")
        for name in FILES:
            src, dst = old / name, new / name
            if src.is_file() and not dst.exists():
                try:
                    shutil.copy2(src, dst)
                    copied.append(name)
                except Exception as exc:
                    skipped.append(f"{name}: {type(exc).__name__}")
        runs = _daily_runs(old / "agent.db")
        if runs:
            from .memory import MemoryStore
            mem = MemoryStore(db_path=new / "agent.db", check_same_thread=False)
            have = [s for s in mem.list_schedules()
                    if (s.get("action") or "") == "jobscout"]
            if not have:
                for r in runs:
                    sid = mem.create_schedule(
                        name=r.get("name") or "Job scout — daily",
                        prompt=r.get("prompt") or "find and apply",
                        spec_json=r.get("spec") or "{}",
                        engine=r.get("engine") or "Auto",
                        full_access=bool(r.get("full_access")),
                        next_run=r.get("next_run"),
                        action="jobscout", payload=r.get("payload") or "{}")
                    if not r.get("enabled", 1):
                        mem.set_schedule_enabled(sid, False)
                copied.append("the daily run")
    note.write_text(json.dumps({"from": str(old), "at": time.strftime(
        "%Y-%m-%d %H:%M UTC", time.gmtime()), "copied": copied,
        "skipped": skipped}, indent=2), "utf-8")
    return {"ran": True, "copied": copied, "skipped": skipped}
