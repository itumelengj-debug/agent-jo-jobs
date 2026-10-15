"""Back up the job search, and put it back.

Months of roles, drafts, answers you've given forms, the people who replied,
your CV and what it learned about your writing — all in one folder, and
nothing kept a copy. A new laptop or a bad disk meant starting again. So:

  * Back up now makes one zip of it (the browser's sign-ins and caches are
    left out: they're large, and a site's sign-in is better redone than
    copied); a weekly one is made by the daily cycle, and the last ten are
    kept;
  * Restore takes a backup zip, checks it is one (made by this app, no path
    that climbs out of the folder), keeps a copy of what's there now first,
    and puts the backup's files in place. Restart afterwards.

Your email password is stored encrypted for this computer's account; on a
different computer it can't be read, so enter it again there.
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path, PurePosixPath

from . import config

KEEP = 10
WEEK_S = 7 * 86400
SKIP_DIRS = ("portal/browser", "backups", "__pycache__", ".tmp")
SKIP_SUFFIX = (".tmp", ".lock", ".log")
MARK = "AGENT_JO_JOBS_BACKUP.json"
MAX_BYTES = 500 * 1024 * 1024


def _home() -> Path:
    return config.AGENT_HOME


def _dir() -> Path:
    d = _home() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _skip(rel: str) -> bool:
    return (any(rel == s or rel.startswith(s + "/") for s in SKIP_DIRS)
            or rel.endswith(SKIP_SUFFIX))


def make(reason: str = "you asked") -> dict:
    home = _home()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = _dir() / f"agent-jo-jobs-backup-{stamp}.zip"
    files = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(home.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(home).as_posix()
            if _skip(rel):
                continue
            try:
                z.write(f, rel)
                files += 1
            except OSError:
                continue                   # a file in use is skipped, not fatal
        z.writestr(MARK, json.dumps({"app": "Agent Jo Jobs", "build": config.BUILD_ID,
                                     "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
                                     "files": files, "reason": reason}))
    _prune()
    return {"ok": True, "path": str(path), "filename": path.name, "files": files,
            "size": path.stat().st_size}


def _prune() -> None:
    zips = sorted(_dir().glob("agent-jo-jobs-backup-*.zip"))
    for old in zips[:-KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def backups() -> list:
    out = []
    for p in sorted(_dir().glob("agent-jo-jobs-backup-*.zip"), reverse=True):
        out.append({"filename": p.name, "size": p.stat().st_size,
                    "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
    return out


def weekly_due() -> bool:
    b = sorted(_dir().glob("agent-jo-jobs-backup-*.zip"))
    return not b or time.time() - b[-1].stat().st_mtime > WEEK_S


def restore(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        return {"ok": False, "error": "That file is larger than any backup should be."}
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return {"ok": False, "error": "That isn't a zip file."}
    with z:
        names = z.namelist()
        if MARK not in names:
            return {"ok": False, "error": "That zip isn't an Agent Jo Jobs backup."}
        try:
            info = json.loads(z.read(MARK))
        except Exception:
            return {"ok": False, "error": "The backup's label can't be read."}
        if info.get("app") != "Agent Jo Jobs":
            return {"ok": False, "error": "That backup is from a different app."}
        bad = [n for n in names if n.startswith("/") or ".." in PurePosixPath(n).parts
               or ":" in n.split("/")[0]]
        if bad:
            return {"ok": False, "error": f"The backup has a path outside its folder ({bad[0]}). Refused."}
        safety = make("before a restore")
        home = _home().resolve()
        n = pending = 0
        for name in names:
            if name == MARK or name.endswith("/") or _skip(name):
                continue
            target = (home / name).resolve()
            if not str(target).startswith(str(home)):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".restoring")
            tmp.write_bytes(z.read(name))
            try:
                tmp.replace(target)
            except OSError:
                pending += 1           # in use (Windows): put in place at the next start
            n += 1
    return {"ok": True, "restored": n, "pending": pending, "from": info.get("at", ""), "build": info.get("build", ""),
            "safety_copy": safety["filename"],
            "message": f"Restored {n} file(s) from the backup of {info.get('at', '?')}. "
                       f"What was here before is kept as {safety['filename']}. Restart the app. "
                       "If this is a different computer, enter your email password again."}


def apply_pending() -> int:
    """Files a restore couldn't replace because they were in use are put in
    place before anything opens them, at start-up."""
    n = 0
    for tmp in _home().rglob("*.restoring"):
        try:
            tmp.replace(tmp.with_name(tmp.name[: -len(".restoring")]))
            n += 1
        except OSError:
            pass
    return n
