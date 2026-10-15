"""The people you've dealt with, and when a new role is at a company you know.

Every reply to an application has a person behind it — a recruiter, a hiring
manager — and the app forgot them the moment the role closed. A turned-down
application at a company still means you know someone there; a recruiter who
answered once is the warmest route in next time. So:

  * people are gathered from the replies the inbox reader matched (name,
    address, company, which roles, what kind of answer, when), and you can
    add one by hand — someone you met, a referral;
  * system senders aren't people: no-reply addresses and the hiring systems'
    own mail (Greenhouse, Lever, Workday…) are left out; a shared inbox
    (jobs@, careers@) is kept but marked as one;
  * someone linked to roles at two or more companies is a recruiter (an
    agency, usually) and is labelled so;
  * when a role is found at a company where you know someone, the role says
    so — "you know Thandi Mokoena here" — so you can write to them instead of
    applying cold, and a short note to them can be drafted (held for you,
    checked like every draft; never sent by itself);
  * people you last heard from three weeks or more ago, on something that
    went somewhere (a reply, an interview, an offer), are listed to get back
    to, unless you've said you're done with them.

Only what the inbox reader already read is used; nothing is looked up about
anyone elsewhere.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config

GET_BACK_DAYS = 21
_NOT_PEOPLE = re.compile(r"^(no-?reply|do-?not-?reply|donotreply|notifications?|mailer-daemon|"
                         r"postmaster|bounce|alerts?|news(letter)?)\b", re.I)
_SHARED = re.compile(r"^(jobs?|careers?|hr|recruit(ment|ing)?|talent|hiring|apply|applications?|"
                     r"people|info|hello|contact|resumes?|cv)\b", re.I)
_LOCK = threading.RLock()


def _path() -> Path:
    d = config.AGENT_HOME / "jobscout"
    d.mkdir(parents=True, exist_ok=True)
    return d / "contacts.json"


def _load() -> dict:
    try:
        return json.loads(_path().read_text("utf-8"))
    except Exception:
        return {}


def _save(d: dict) -> None:
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), "utf-8")
    tmp.replace(p)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


def _days_since(stamp: str) -> float:
    try:
        t = datetime.strptime(stamp[:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except Exception:
        return 0.0
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


def is_person(addr: str) -> bool:
    from .inbox import ATS_MAIL
    addr = (addr or "").lower().strip()
    if "@" not in addr:
        return False
    local, dom = addr.split("@", 1)
    if _NOT_PEOPLE.match(local) or any(dom == a or dom.endswith("." + a) for a in ATS_MAIL):
        return False
    return True


def _company_tokens(company: str) -> list:
    from .inbox import _company_tokens as toks
    return toks(company or "")


def _same_company(a: str, b: str) -> bool:
    ta, tb = _company_tokens(a), _company_tokens(b)
    return bool(ta) and bool(tb) and (set(ta) <= set(tb) or set(tb) <= set(ta))


def sync() -> dict:
    """Gather people from the replies matched to your applications."""
    from . import jobscout
    with _LOCK:
        d = _load()
        added = 0
        for r in jobscout.roles():
            for rep in r.get("replies") or []:
                addr = (rep.get("from") or "").lower().strip()
                if not is_person(addr) or rep.get("kind") == "ack":
                    continue
                c = d.get(addr)
                if c is None:
                    c = d[addr] = {"email": addr, "name": "", "companies": [], "roles": [],
                                   "kinds": {}, "first": rep.get("at") or _now(), "last": "",
                                   "notes": "", "done": False, "source": "inbox", "seen": []}
                    added += 1
                mark = f"{r['key']}|{rep.get('at')}|{rep.get('kind')}"
                if mark in c.get("seen", []):
                    continue
                c.setdefault("seen", []).append(mark)
                c["seen"] = c["seen"][-200:]
                if rep.get("from_name") and not c["name"]:
                    c["name"] = rep["from_name"].strip().strip('"')
                comp = r.get("company", "")
                if comp and not any(_same_company(comp, x) for x in c["companies"]):
                    c["companies"].append(comp)
                if r["key"] not in [x["key"] for x in c["roles"]]:
                    c["roles"].append({"key": r["key"], "title": r.get("title", ""), "company": comp})
                k = rep.get("kind") or "reply"
                c["kinds"][k] = c["kinds"].get(k, 0) + 1
                if (rep.get("at") or "") > (c.get("last") or ""):
                    c["last"] = rep.get("at") or ""
        _save(d)
    return {"ok": True, "added": added, "people": len(d)}


def _kind(c: dict) -> str:
    local = c["email"].split("@", 1)[0]
    if _SHARED.match(local):
        return "team inbox"
    if len(c.get("companies") or []) >= 2:
        return "recruiter"
    return "person"


def people() -> list:
    out = []
    for c in _load().values():
        x = {k: v for k, v in c.items() if k != "seen"}
        x["kind"] = _kind(c)
        x["days"] = round(_days_since(c.get("last") or c.get("first") or ""))
        out.append(x)
    return sorted(out, key=lambda c: c.get("last") or c.get("first") or "", reverse=True)


def add(name: str, email: str, company: str = "", notes: str = "") -> dict:
    email = (email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return {"ok": False, "error": "That doesn't look like an email address."}
    with _LOCK:
        d = _load()
        c = d.get(email) or {"email": email, "companies": [], "roles": [], "kinds": {},
                             "first": _now(), "last": "", "done": False, "seen": [], "source": "you"}
        c["name"] = (name or c.get("name") or "").strip()[:120]
        comp = (company or "").strip()[:120]
        if comp and not any(_same_company(comp, x) for x in c["companies"]):
            c["companies"].append(comp)
        if notes:
            c["notes"] = notes.strip()[:2000]
        c.setdefault("notes", "")
        d[email] = c
        _save(d)
    return {"ok": True, "person": c}


def update(email: str, **fields) -> dict:
    with _LOCK:
        d = _load()
        c = d.get((email or "").lower())
        if c is None:
            return {"ok": False, "error": "No such person."}
        for k in ("name", "notes"):
            if k in fields and fields[k] is not None:
                c[k] = str(fields[k]).strip()[:2000]
        if "done" in fields and fields["done"] is not None:
            c["done"] = bool(fields["done"])
        if fields.get("touched"):
            c["last"] = _now()
            c["kinds"]["you wrote"] = c["kinds"].get("you wrote", 0) + 1
        _save(d)
    return {"ok": True, "person": c}


def remove(email: str) -> dict:
    with _LOCK:
        d = _load()
        d.pop((email or "").lower(), None)
        _save(d)
    return {"ok": True}


def at_company(company: str) -> list:
    """People you know at this company (recruiters linked to it count too)."""
    out = []
    for c in people():
        if c["kind"] == "team inbox":
            continue
        if any(_same_company(company, x) for x in c.get("companies") or []):
            out.append(c)
    return out


def flag_roles() -> int:
    """Mark roles at a company where you know someone. Returns how many changed."""
    from . import jobscout
    n = 0
    for r in jobscout.roles():
        if r.get("stage") in ("closed",) or r.get("sent_at"):
            continue
        known = [{"name": c.get("name") or c["email"], "email": c["email"], "kind": c["kind"],
                  "last": c.get("last", "")[:10],
                  "about": ", ".join(x["title"] for x in c.get("roles", [])[:2])}
                 for c in at_company(r.get("company", ""))
                 if r["key"] not in [x["key"] for x in c.get("roles", [])]]
        if known != (r.get("know") or []):
            jobscout.update_role(r["key"], know=known[:3])
            n += 1
    return n


def get_back_to(days: int = GET_BACK_DAYS) -> list:
    """People worth writing to again: it went somewhere, then went quiet."""
    out = []
    for c in people():
        if c.get("done") or c["kind"] == "team inbox":
            continue
        warm = any(c["kinds"].get(k) for k in ("reply", "interview", "offer"))
        if warm and c["days"] >= days:
            out.append(c)
    return sorted(out, key=lambda c: -c["days"])


_NOTE_SYSTEM = (
    "Write a short, warm note from the candidate to someone they've dealt with "
    "before, about a NEW role at that person's company (or one they recruit "
    "for). Four sentences at most: remind them how they know each other (from "
    "HISTORY only), name the new role, say in one line why the candidate fits "
    "using ONLY the PROFILE and CV, and ask if they'd pass it on or are the "
    "right person to speak to. No flattery, no invented history. Return ONLY "
    "raw JSON: {\"subject\": str, \"body\": str}.")


def draft_note(role_key: str, email: str, brain, model=None) -> dict:
    """A short note to someone you know about a role. Held for you; never sent here."""
    from . import jobscout, cv as cvmod
    r = jobscout.get_role(role_key)
    c = _load().get((email or "").lower())
    if r is None or c is None:
        return {"ok": False, "error": "No such role or person."}
    hist = {"name": c.get("name"), "companies": c.get("companies"),
            "earlier_roles": [x["title"] + " @ " + x["company"] for x in c.get("roles", [])][:5],
            "what_happened": c.get("kinds"), "last_heard": (c.get("last") or "")[:10],
            "your_notes": c.get("notes", "")}
    payload = json.dumps({"ROLE": {k: r.get(k) for k in ("title", "company", "summary", "url")},
                          "HISTORY": hist, "PROFILE": jobscout.profile(),
                          "CV": cvmod._cv_for(r, 2500)}, default=str)[:12000]
    try:
        kw = {"model": model} if model else {}
        resp = brain.chat([{"role": "user", "content": payload}],
                          [_NOTE_SYSTEM + jobscout._style_clause(("length",))], None, **kw)
        raw = "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        data = cvmod._json_from(raw)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    body = str(data.get("body", "")).strip()
    if not body:
        return {"ok": False, "error": "The engine returned an empty note."}
    note = {"to": c["email"], "name": c.get("name", ""), "subject": str(data.get("subject", ""))[:200],
            "body": body, "check": jobscout.check_draft(body, r), "at": _now()}
    jobscout.update_role(role_key, contact_note=note)
    return {"ok": True, "note": note}
