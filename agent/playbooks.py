"""Playbooks: what each site taught the app, used on the next application.

Every application through a company's website teaches something:

  * the way from the advert to the form: which button ("Apply now", "I'm
    interested", a tab called "Application"), whether it opens a new tab;
  * what that site calls its "next" and "submit" buttons;
  * which unfamiliar labels mean which of your details ("Current CTC" is your
    salary expectation, "Mobile number" is your phone);
  * what made it stop: a sign-in, a captcha;
  * notes the engine left for next time when it had to work something out.

The next application to the same site, or to any site on the same hiring
system, starts from that instead of discovering it again. The engine is only
asked about what's genuinely new, so each application through a site takes
fewer engine steps than the one before. Every run is recorded (how it ended,
how many engine steps, how long), so you can see that happen.

It corrects itself. A step that stops working is tried, fails, and is dropped
once it has failed more than it worked. Nothing here is guessed: every entry
is something that happened, with counts.

Kept in the job data folder as jobscout/playbooks.json. The Auto-apply view
shows what it knows about each site, and you can make it forget any site.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from . import config

_LOCK = threading.RLock()
HISTORY_KEPT = 12          # runs remembered per site
NOTES_KEPT = 8             # notes per site
LABELS_KEPT = 400          # labels learned across every site


def _path() -> Path:
    d = config.AGENT_HOME / "jobscout"
    d.mkdir(parents=True, exist_ok=True)
    return d / "playbooks.json"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


def _blank() -> dict:
    return {"version": 1, "sites": {}, "ats": {}, "labels": {}}


# The file is read on every lookup (a page of forty boxes asks forty
# times), so its text is kept until the file changes.
_CACHE: dict = {"key": None, "text": ""}


def _load() -> dict:
    p = _path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
        if _CACHE["key"] != key:
            _CACHE["text"], _CACHE["key"] = p.read_text("utf-8"), key
        data = json.loads(_CACHE["text"])
        if isinstance(data, dict):
            for k, v in _blank().items():
                data.setdefault(k, v)
            return data
    except Exception:
        pass
    return _blank()


def _save(data: dict) -> None:
    p = _path()
    text = json.dumps(data, indent=1, ensure_ascii=False)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(text, "utf-8")
    tmp.replace(p)
    try:
        st = p.stat()
        _CACHE["text"], _CACHE["key"] = text, (str(p), st.st_mtime_ns, st.st_size)
    except Exception:
        _CACHE["key"] = None


def site_of(url: str) -> str:
    """The host, which is what a form belongs to, without "www."."""
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        host = ""
    return host[4:] if host.startswith("www.") else host


def norm(text: str) -> str:
    """Button and label text as it's compared: lower case, no punctuation
    at the ends, no required-field stars, single spaces."""
    t = re.sub(r"\(\s*(required|optional)\s*\)|[*]+", " ", str(text or "").lower())
    t = re.sub(r"[\s ]+", " ", t)
    return t.strip(" .:?!›»>→-–—")


def _site(data: dict, url: str) -> dict:
    s = site_of(url)
    rec = data["sites"].get(s)
    if rec is None:
        rec = data["sites"][s] = {"site": s, "ats": "", "runs": 0, "completed": 0,
                                  "submitted": 0, "route": [], "next": {}, "submit": {},
                                  "labels": {}, "blocks": {}, "notes": [], "history": [],
                                  "first_at": _now(), "last_at": ""}
    return rec


def _ats(data: dict, ats: str) -> dict | None:
    if not ats or ats == "unknown":
        return None
    rec = data["ats"].get(ats)
    if rec is None:
        rec = data["ats"][ats] = {"ats": ats, "route": [], "next": {}, "submit": {},
                                  "labels": {}, "runs": 0}
    return rec


def _show(label: str, n: int = 60) -> str:
    t = re.sub(r"\(\s*(required|optional)\s*\)|\*+", " ", str(label or ""), flags=re.I)
    return " ".join(t.split()).strip(" :")[:n]


def _score(step: dict) -> int:
    return int(step.get("ok", 0)) - 2 * int(step.get("fail", 0))


# --------------------------------------------------------------------------- #
#  reading: what the navigator starts from
# --------------------------------------------------------------------------- #
def route(url: str, ats: str = "") -> list:
    """The steps that got from an advert to its form before, best first:
    this site's own, then ones that worked on other sites with the same
    hiring system. Each is {kind, text, label, ok, fail, by, scope}."""
    with _LOCK:
        data = _load()
    out, seen = [], set()
    srec = data["sites"].get(site_of(url)) or {}
    arec = data["ats"].get(ats) or {} if ats else {}
    for scope, rec in (("site", srec), ("ats", arec)):
        for st in sorted(rec.get("route") or [], key=lambda s: -_score(s)):
            key = (st.get("kind"), st.get("text"))
            if _score(st) <= 0 or key in seen:
                continue
            seen.add(key)
            out.append({**st, "scope": scope})
    return out


def texts(url: str, ats: str, what: str) -> list:
    """Button texts that worked as "next" (or "submit") here, most used first."""
    with _LOCK:
        data = _load()
    counts: dict = {}
    for rec in (data["sites"].get(site_of(url)) or {}, data["ats"].get(ats) or {} if ats else {}):
        for t, n in (rec.get(what) or {}).items():
            counts[t] = counts.get(t, 0) + int(n)
    return [t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1])]


def label_kind(label: str, url: str = "", ats: str = "") -> str:
    """Which of your details an unfamiliar label turned out to mean:
    this site's answer first, then the hiring system's, then any site's."""
    key = norm(label)
    if not key:
        return ""
    with _LOCK:
        data = _load()
    for rec in (data["sites"].get(site_of(url)) or {} if url else {},
                data["ats"].get(ats) or {} if ats else {}):
        k = (rec.get("labels") or {}).get(key)
        if k:
            return k
    g = data["labels"].get(key) or {}
    return g.get("kind", "") if int(g.get("ok", 0)) > int(g.get("fail", 0)) else ""


def notes(url: str) -> list:
    with _LOCK:
        rec = _load()["sites"].get(site_of(url)) or {}
    return [n.get("text", "") for n in rec.get("notes") or []]


def known(url: str) -> dict:
    """Everything about one site, for the window."""
    with _LOCK:
        return dict(_load()["sites"].get(site_of(url)) or {})


# --------------------------------------------------------------------------- #
#  learning: each returns a sentence when it learned something new, else ""
# --------------------------------------------------------------------------- #
def learn_route(url: str, ats: str, kind: str, text: str, ok: bool, by: str = "rule") -> str:
    """A click on the way to the form worked (or didn't)."""
    t = norm(text)
    if not t or not site_of(url):
        return ""
    said = ""
    with _LOCK:
        data = _load()
        for rec in [r for r in (_site(data, url), _ats(data, ats)) if r is not None]:
            steps = rec.setdefault("route", [])
            st = next((s for s in steps if s.get("kind") == kind and s.get("text") == t), None)
            if st is None:
                if not ok:
                    continue
                st = {"kind": kind, "text": t, "label": str(text).strip()[:80], "ok": 0,
                      "fail": 0, "by": by, "at": _now()}
                steps.append(st)
                if "site" in rec and not said:
                    said = (f"How to reach the form on {site_of(url)}: "
                            f"“{st['label']}”" + (" (worked out by the engine)" if by == "engine" else ""))
            st["ok" if ok else "fail"] = int(st.get("ok" if ok else "fail", 0)) + 1
            st["at"] = _now()
            # a step that has failed more than it worked goes
            if not ok and int(st.get("fail", 0)) >= 2 and _score(st) < 0:
                steps.remove(st)
                if "site" in rec:
                    said = f"Dropped a step that stopped working on {site_of(url)}: “{st['label']}”"
        _save(data)
    return said


def learn_button(url: str, ats: str, what: str, text: str) -> str:
    """The text of a "next" (what="next") or "submit" button that worked."""
    t = norm(text)
    if not t or what not in ("next", "submit") or not site_of(url):
        return ""
    with _LOCK:
        data = _load()
        srec = _site(data, url)
        new = t not in (srec.get(what) or {})
        for rec in [r for r in (srec, _ats(data, ats)) if r is not None]:
            rec.setdefault(what, {})[t] = int(rec[what].get(t, 0)) + 1
        _save(data)
    if new and what == "next" and not re.match(r"^(next|continue|save (and|&) continue)$", t):
        return f"On {site_of(url)} the next-page button is “{_show(text)}”"
    return ""


def learn_label(label: str, kind: str, url: str = "", ats: str = "", ok: bool = True) -> str:
    """An unfamiliar label meant this detail of yours (or didn't)."""
    key = norm(label)
    if not key or not kind or len(key) > 160:
        return ""
    said = ""
    with _LOCK:
        data = _load()
        g = data["labels"].get(key)
        if g is None:
            if not ok:
                return ""
            g = data["labels"][key] = {"kind": kind, "ok": 0, "fail": 0, "at": _now()}
            from .navigator import field_name
            said = f"“{_show(label)}” means your {field_name(kind)}"
        if g.get("kind") != kind and ok:
            from .navigator import field_name
            said = (f"“{_show(label)}” takes your {field_name(kind)}, not your "
                    f"{field_name(g.get('kind'))}: corrected")
            g.update(kind=kind, ok=0, fail=0)
        g["ok" if ok else "fail"] = int(g.get("ok" if ok else "fail", 0)) + 1
        g["at"] = _now()
        if url:
            srec = _site(data, url)
            if ok:
                srec.setdefault("labels", {})[key] = kind
            else:
                srec.setdefault("labels", {}).pop(key, None)
        arec = _ats(data, ats)
        if arec is not None and ok:
            arec.setdefault("labels", {})[key] = kind
        if len(data["labels"]) > LABELS_KEPT:
            oldest = sorted(data["labels"].items(), key=lambda kv: kv[1].get("at", ""))
            for k, _ in oldest[:len(data["labels"]) - LABELS_KEPT]:
                data["labels"].pop(k, None)
        _save(data)
    return said


def block(url: str, state: str) -> str:
    """This site stopped for a sign-in or a captcha."""
    if not state or not site_of(url):
        return ""
    with _LOCK:
        data = _load()
        rec = _site(data, url)
        first = state not in (rec.get("blocks") or {})
        rec.setdefault("blocks", {})[state] = int(rec["blocks"].get(state, 0)) + 1
        _save(data)
    if first:
        if state == "needs_login":
            return (f"{site_of(url)} asks for a sign-in: once you've signed in, the browser keeps you "
                    f"signed in for its next forms")
        if state == "needs_captcha":
            return f"{site_of(url)} shows a captcha: those are always handed to you"
        return f"{site_of(url)} stopped for {state}"
    return ""


def add_note(url: str, text: str, by: str = "engine") -> str:
    """Something worth knowing next time, in a sentence."""
    t = " ".join(str(text or "").split())[:200]
    if len(t) < 8 or not site_of(url):
        return ""
    with _LOCK:
        data = _load()
        rec = _site(data, url)
        have = rec.setdefault("notes", [])
        words = set(norm(t).split())
        for n in have:
            other = set(norm(n.get("text", "")).split())
            if words and other and len(words & other) / len(words | other) >= 0.6:
                n["at"] = _now()
                _save(data)
                return ""
        have.append({"text": t, "by": by, "at": _now()})
        rec["notes"] = have[-NOTES_KEPT:]
        _save(data)
    return f"Noted for {site_of(url)}: {t}"


def finish(url: str, ats: str, run: dict) -> list:
    """Record how an application went, and say how it compares with the
    last one through this site. Returns sentences for the window."""
    if not site_of(url):
        return []
    outcome = str(run.get("state") or "")
    turns = int(run.get("engine_turns") or 0)
    secs = int(run.get("seconds") or 0)
    with _LOCK:
        data = _load()
        rec = _site(data, url)
        prev = (rec.get("history") or [])[-1:] or [None]
        prev = prev[0]
        rec["runs"] = int(rec.get("runs", 0)) + 1
        if outcome in ("filled", "submitted"):
            rec["completed"] = int(rec.get("completed", 0)) + 1
        if outcome == "submitted":
            rec["submitted"] = int(rec.get("submitted", 0)) + 1
        if ats and ats != "unknown":
            rec["ats"] = ats
            arec = _ats(data, ats)
            if arec is not None:
                arec["runs"] = int(arec.get("runs", 0)) + 1
        rec["last_at"] = _now()
        rec.setdefault("history", []).append({
            "at": _now(), "outcome": outcome, "engine_turns": turns, "seconds": secs,
            "filled": int(run.get("filled") or 0), "left": len(run.get("left") or []),
            "pages": int(run.get("pages") or 0)})
        rec["history"] = rec["history"][-HISTORY_KEPT:]
        _save(data)
    said = []
    if prev is not None:
        was = int(prev.get("engine_turns", 0))
        if turns < was:
            said.append(f"Didn't need the engine at all on {site_of(url)} this time (last time: "
                        f"{was} step{'s' if was != 1 else ''})" if turns == 0 else
                        f"Needed the engine {turns} time{'s' if turns != 1 else ''} on {site_of(url)}, "
                        f"down from {was} last time")
        if outcome in ("filled", "submitted") and prev.get("outcome") not in ("filled", "submitted"):
            said.append(f"Got through {site_of(url)}'s form this time; last time it stopped")
    return said


def forget(site: str) -> dict:
    s = site_of(site) if "/" in str(site) else str(site or "").lower().removeprefix("www.")
    with _LOCK:
        data = _load()
        gone = data["sites"].pop(s, None) is not None
        _save(data)
    return {"ok": gone}


# --------------------------------------------------------------------------- #
#  the report: is it actually getting better?
# --------------------------------------------------------------------------- #
def report() -> dict:
    """What it knows, site by site, and whether applications are getting
    easier: of the last ten through company forms, how many it finished
    without you, against the ten before, and engine steps per application."""
    with _LOCK:
        data = _load()
    runs = []
    sites = []
    for s, rec in data["sites"].items():
        for h in rec.get("history") or []:
            runs.append({**h, "site": s})
        hist = rec.get("history") or []
        sites.append({
            "site": s, "ats": rec.get("ats", ""), "runs": rec.get("runs", 0),
            "completed": rec.get("completed", 0), "submitted": rec.get("submitted", 0),
            "route": [st.get("label") or st.get("text") for st in rec.get("route") or []
                      if _score(st) > 0][:4],
            "next": list((rec.get("next") or {}).keys())[:3],
            "labels": len(rec.get("labels") or {}),
            "blocks": sorted((rec.get("blocks") or {}).keys()),
            "notes": [n.get("text", "") for n in rec.get("notes") or []][-3:],
            "turns": [h.get("engine_turns", 0) for h in hist][-6:],
            "last_outcome": hist[-1]["outcome"] if hist else "",
            "last_at": rec.get("last_at", "")})
    sites.sort(key=lambda r: r.get("last_at", ""), reverse=True)
    runs.sort(key=lambda r: r.get("at", ""))
    last, before = runs[-10:], runs[-20:-10]

    def without_you(rs):
        return sum(1 for r in rs if r.get("outcome") in ("filled", "submitted"))

    def avg_turns(rs):
        return round(sum(r.get("engine_turns", 0) for r in rs) / len(rs), 1) if rs else 0.0
    return {"sites": sites,
            "totals": {"applications": len(runs), "sites": len(sites),
                       "routes": sum(1 for s in sites if s["route"]),
                       "labels": len(data["labels"]),
                       "systems": sorted(k for k, v in data["ats"].items() if v.get("runs"))},
            "recent": {"last": len(last), "last_without_you": without_you(last),
                       "before": len(before), "before_without_you": without_you(before),
                       "last_turns": avg_turns(last), "before_turns": avg_turns(before)}}
