"""Every answer you give an application form, kept so you never type it twice.

Forms ask the same things over and over — notice period, "why this
company", "are you willing to relocate", "years with Power BI", "highest
qualification" — each worded a little differently. What you type into a form
is saved here with its question (the helper in the form sends it when you
leave a field), and the next form that asks the same thing, in any wording
close enough, gets your answer.

Order of use, everywhere an answer is needed: your profile's fields, then
answers saved here, then the engine answering from your CV and profile.

What is NOT kept:
  * passwords, one-time codes, card and account numbers — never stored;
  * empty answers, and answers that just repeat a profile field;
  * questions about you that the law treats as sensitive (gender, race,
    disability, ID number and the rest) are kept, but not reused until you
    say so: each has a "reuse" switch in the Answers view, off by default.

Stored in the job data folder as jobscout/answers.json. You can edit or
delete any answer, or add one, in the Answers view.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from . import config

_LOCK = threading.RLock()
MATCH = 0.6                    # how alike two questions must be to share an answer
_NEVER = re.compile(r"password|passcode|one[\s-]*time|\botp\b|verification code|"
                    r"\bpin\b|cvv|cvc|card number|security code|account number|"
                    r"captcha", re.I)
_CARDLIKE = re.compile(r"^[\d\s-]{13,23}$")
_STOP = set("""a an and are as at be by do does for from have how i if in is it
its me my of on or please our so that the their this to was we what when where
which who why will with would you your yes no""".split())


def _path() -> Path:
    d = config.AGENT_HOME / "jobscout"
    d.mkdir(parents=True, exist_ok=True)
    return d / "answers.json"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


def norm(question: str) -> str:
    q = re.sub(r"\(\s*(required|optional)\s*\)|[*:?]+", " ", str(question or "").lower())
    return " ".join(q.split())


def _words(q: str) -> set:
    return {w for w in re.findall(r"[a-z0-9+#]+", norm(q))
            if w not in _STOP and len(w) > 1}


def _load() -> list:
    try:
        return json.loads(_path().read_text("utf-8"))
    except Exception:
        return []


def _save(items: list) -> None:
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1), "utf-8")
    tmp.replace(p)


def _sensitive(question: str) -> bool:
    from .portal import SENSITIVE
    low = norm(question)
    return any(s in low for s in SENSITIVE)


def all_answers() -> list:
    with _LOCK:
        return sorted(_load(), key=lambda a: a.get("used_at") or a.get("at", ""),
                      reverse=True)


def remember(question: str, answer: str, *, source: str = "you",
             site: str = "", role: str = "") -> dict:
    """Save (or update) the answer to a question. Returns why if it wasn't."""
    q, a = str(question or "").strip(), str(answer or "").strip()
    if not q or not a:
        return {"ok": False, "why": "empty"}
    if _NEVER.search(q) or _CARDLIKE.match(a):
        return {"ok": False, "why": "never stored: looks like a secret"}
    key = norm(q)
    with _LOCK:
        items = _load()
        for it in items:
            if it["key"] == key:
                changed = it["answer"] != a
                it.update(answer=a, at=_now(), source=source,
                          site=site or it.get("site", ""),
                          role=role or it.get("role", ""))
                _save(items)
                return {"ok": True, "updated": changed, "id": it["id"]}
        nid = max([it.get("id", 0) for it in items] + [0]) + 1
        sens = _sensitive(q)
        items.append({"id": nid, "key": key, "question": q, "answer": a,
                      "source": source, "site": site, "role": role,
                      "at": _now(), "used_at": "", "uses": 0,
                      "sensitive": sens, "reuse": not sens})
        _save(items)
        return {"ok": True, "added": True, "id": nid}


def lookup(question: str, *, touch: bool = True) -> dict | None:
    """Your saved answer to this question, or one worded close enough to it.
    None when there isn't one, or it's sensitive and not switched on."""
    key, w = norm(question), _words(question)
    if not key:
        return None
    with _LOCK:
        items = [it for it in _load() if it.get("reuse", True)]
        best, score = None, 0.0
        for it in items:
            if it["key"] == key:
                best, score = it, 1.0
                break
            iw = _words(it["question"])
            if not w or not iw:
                continue
            j = len(w & iw) / len(w | iw)
            if j > score:
                best, score = it, j
        if best is None or score < MATCH:
            return None
        # a near match must agree on what kind of field it is: "notice
        # period" and "salary expectation" can share words but not answers
        if score < 1.0:
            from .portal import classify_field
            if classify_field(question) != classify_field(best["question"]):
                return None
        if touch:
            all_items = _load()
            for it in all_items:
                if it["id"] == best["id"]:
                    it["uses"] = int(it.get("uses") or 0) + 1
                    it["used_at"] = _now()
            _save(all_items)
        return {**best, "match": round(score, 2)}


def update(aid: int, **fields) -> dict:
    allowed = {k: v for k, v in fields.items()
               if k in ("question", "answer", "reuse") and v is not None}
    with _LOCK:
        items = _load()
        for it in items:
            if it["id"] == aid:
                it.update(allowed)
                if "question" in allowed:
                    it["key"] = norm(it["question"])
                    it["sensitive"] = _sensitive(it["question"])
                it["at"] = _now()
                _save(items)
                return {"ok": True, "answer": it}
    return {"ok": False, "error": "no such answer"}


def delete(aid: int) -> dict:
    with _LOCK:
        items = _load()
        kept = [it for it in items if it["id"] != aid]
        _save(kept)
    return {"ok": len(kept) != len(items)}


# --- questions waiting on you --------------------------------------------- #
# A form question nothing could answer — not your profile, not a saved answer,
# not the engine from your CV — stopped that application. Each one is kept
# here with the roles it's holding up, so you answer it once, in one place,
# and every one of those forms (and every later one) gets it.

def _open_path() -> Path:
    return _path().with_name("open_questions.json")


def _open_load() -> list:
    try:
        return json.loads(_open_path().read_text("utf-8"))
    except Exception:
        return []


def _open_save(items: list) -> None:
    p = _open_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1), "utf-8")
    tmp.replace(p)


def ask(question: str, role: str = "", role_key: str = "") -> None:
    """Note a question that stopped an application."""
    q = str(question or "").strip()
    if not q or _NEVER.search(q) or lookup(q, touch=False):
        return
    key = norm(q)
    with _LOCK:
        items = _open_load()
        for it in items:
            if it["key"] == key or _similar(it["question"], q):
                if role and role not in it["roles"]:
                    it["roles"].append(role)
                if role_key and role_key not in it.setdefault("role_keys", []):
                    it["role_keys"].append(role_key)
                it["last"] = _now()
                _open_save(items)
                return
        items.append({"key": key, "question": q, "roles": [role] if role else [],
                      "role_keys": [role_key] if role_key else [],
                      "first": _now(), "last": _now(),
                      "sensitive": _sensitive(q)})
        _open_save(items)


def _similar(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= MATCH


def open_questions() -> list:
    """Questions waiting on you, the ones holding up most applications first.
    Anything you've since answered is dropped."""
    with _LOCK:
        items = [it for it in _open_load() if not lookup(it["question"], touch=False)]
        _open_save(items)
    return sorted(items, key=lambda it: (-len(it["roles"]), it["first"]))


def answer_open(question: str, answer: str) -> dict:
    """Answer a waiting question: saved like any answer, and switched on for
    reuse — you gave it in answer to exactly this question."""
    res = remember(question, answer, source="you")
    if res.get("ok") and res.get("id"):
        update(res["id"], reuse=True)
    open_questions()
    return res


def hints() -> list:
    """Saved answers in the shape the in-form helper takes."""
    return [{"label": it["question"], "value": it["answer"], "source": "saved"}
            for it in all_answers() if it.get("reuse", True)]
