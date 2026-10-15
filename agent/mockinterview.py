"""Mock interviews: practise the questions, and hear what to fix.

Interview prep told you the likely questions and where your CV is thin. That
is reading, not practice — and the gap between knowing an answer and saying
it well under pressure is where interviews are lost. This runs the interview:

  * one question at a time, from the role's prep (made first if there is
    none), typed or spoken — the window can dictate and read the questions
    aloud with the browser's own speech (dictation in Chrome and Edge goes
    through their online speech service; the app itself keeps no audio);
  * each answer gets feedback: a 1–5 score, what worked, the one thing to
    change, and a stronger version built ONLY from your CV and profile;
  * every answer is also checked locally, no engine needed: does it give a
    concrete example, a result or a number, is it a sensible length — and
    does it claim a tool, employer or number your CV can't back (the same
    guard the cover letters get; in an interview that's the claim they
    check);
  * at the end: the average, the two or three answers to work on, and how
    this attempt compares with your last one for the same role.

Sessions are kept per role (jobscout/mock/), the last ten, so you can see
yourself improve.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import config

KEEP = 10
_RESULT = re.compile(r"\b(\d+(?:[.,]\d+)?\s*(?:%|percent|x|times|hours?|days?|weeks?|months?|"
                     r"people|users|clients|customers|rand|R\s?\d|million|thousand|k\b))|"
                     r"\b(cut|reduced|increased|grew|saved|improved|doubled|halved|delivered|"
                     r"launched|shipped|won|resolved)\b", re.I)
_EXAMPLE = re.compile(r"\b(when I|at [A-Z]\w+|for example|for instance|in my (?:last|previous|current) "
                      r"(?:role|job|team)|one time|I (?:led|built|ran|designed|wrote|migrated|"
                      r"managed|owned|fixed|created|set up))\b")
_I = re.compile(r"\bI\b")
_WE = re.compile(r"\bwe\b", re.I)


def _dir() -> Path:
    d = config.AGENT_HOME / "jobscout" / "mock"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(key: str) -> Path:
    return _dir() / (re.sub(r"[^A-Za-z0-9_-]", "_", key)[:80] + ".json")


def _load(key: str) -> dict:
    try:
        return json.loads(_path(key).read_text("utf-8"))
    except Exception:
        return {"sessions": []}


def _save(key: str, d: dict) -> None:
    d["sessions"] = d.get("sessions", [])[-KEEP:]
    tmp = _path(key).with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), "utf-8")
    tmp.replace(_path(key))


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


def local_checks(answer: str, role: dict | None = None) -> dict:
    """What can be said about an answer without an engine."""
    from . import jobscout
    a = (answer or "").strip()
    words = len(a.split())
    notes = []
    example = bool(_EXAMPLE.search(a))
    result = bool(_RESULT.search(a))
    if words < 40:
        notes.append("Short — a good answer usually runs 60 to 200 words (about a minute spoken).")
    elif words > 320:
        notes.append("Long — past two minutes they stop listening. Cut to the example and the result.")
    if not example:
        notes.append("No concrete example — name the situation: where, when, what you did.")
    if not result:
        notes.append("No result — end with what changed, with a number if you have one.")
    if len(_WE.findall(a)) > 3 and len(_I.findall(a)) < 2:
        notes.append("All \"we\" — say what YOU did; that's what they're hiring.")
    claims = []
    try:
        chk = jobscout.check_draft(a, role)
        claims = [p.get("detail", "") for p in chk.get("problems", [])][:5]
    except Exception:
        pass
    return {"words": words, "example": example, "result": result,
            "notes": notes, "claims": claims}


def status(key: str) -> dict:
    d = _load(key)
    cur = d.get("current")
    hist = [{"at": s["at"], "average": s.get("average"), "answered": len(s.get("answers", []))}
            for s in d.get("sessions", [])]
    return {"ok": True, "current": cur, "history": hist}


def start(role: dict, brain=None, model=None) -> dict:
    """Begin a mock interview for the role. Uses its prep, or makes it."""
    prep = role.get("interview") or {}
    if not prep.get("questions"):
        if brain is None:
            return {"ok": False, "error": "No interview prep for this role yet — run Interview prep first."}
        from . import cv as cvmod, jobscout
        prep = cvmod.interview_prep(role, jobscout.profile(), brain, model=model)
        if not prep.get("ok"):
            return {"ok": False, "error": prep.get("error", "Couldn't prepare the questions.")}
        jobscout.update_role(role["key"], interview=prep)
    qs = [q["question"] for q in prep.get("questions", []) if q.get("question")]
    # an opener every interview has, first
    opener = "Tell me about yourself, and why this role."
    if not any("about yourself" in q.lower() for q in qs):
        qs.insert(0, opener)
    d = _load(role["key"])
    d["current"] = {"at": _now(), "questions": qs[:9], "answers": [], "i": 0}
    _save(role["key"], d)
    return {"ok": True, "question": qs[0], "number": 1, "of": len(d["current"]["questions"])}


_FEEDBACK_SYSTEM = (
    "You are an experienced interviewer giving honest, specific feedback on one "
    "answer in a practice interview for the ADVERT. Score 1-5 (5 = would clearly "
    "move them forward). Judge: does it answer the question asked; is there a "
    "concrete example with what THEY did and the result; is it relevant to what "
    "the advert emphasises; is it a sensible length. `better` is a stronger "
    "version of THEIR answer, first person, under 170 words, using ONLY facts in "
    "PROFILE, CV and their ANSWER — never add an employer, tool, number or "
    "achievement they didn't give; where they have nothing, say what kind of "
    "example to find instead. Return ONLY raw JSON: {\"score\": int, "
    "\"worked\": str, \"fix\": str, \"better\": str}. `fix` is the single most "
    "useful change, one sentence.")


def answer(role: dict, text: str, brain=None, model=None) -> dict:
    d = _load(role["key"])
    cur = d.get("current")
    if not cur:
        return {"ok": False, "error": "No practice interview running for this role — start one."}
    text = (text or "").strip()[:6000]
    if not text:
        return {"ok": False, "error": "Say or type your answer first."}
    q = cur["questions"][cur["i"]]
    local = local_checks(text, role)
    fb = {}
    if brain is not None:
        from . import cv as cvmod, jobscout
        payload = json.dumps({"ADVERT": {k: role.get(k) for k in ("title", "company", "summary", "description")},
                              "QUESTION": q, "ANSWER": text,
                              "PROFILE": jobscout.profile(), "CV": cvmod._cv_for(role, 3500)},
                             default=str)[:14000]
        try:
            kw = {"model": model} if model else {}
            resp = brain.chat([{"role": "user", "content": payload}], [_FEEDBACK_SYSTEM], None, **kw)
            raw = "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            data = cvmod._json_from(raw)
            score = data.get("score")
            fb = {"score": max(1, min(5, int(score))) if str(score).strip().lstrip("-").isdigit() else None,
                  "worked": str(data.get("worked", ""))[:500],
                  "fix": str(data.get("fix", ""))[:400],
                  "better": str(data.get("better", ""))[:1500]}
            if fb["better"]:
                # the stronger version mustn't invent either
                chk = jobscout.check_draft(fb["better"], role)
                bad = [p.get("detail", "") for p in chk.get("problems", [])]
                if bad:
                    fb["better_flags"] = bad[:4]
        except Exception as exc:
            fb = {"error": f"No engine feedback ({type(exc).__name__}) — the local checks still apply."}
    if fb.get("score") is None:
        # without an engine, a rough score from the local checks
        fb.setdefault("score", None)
        fb["local_score"] = 1 + local["example"] + local["result"] + (40 <= local["words"] <= 320) \
            + (not local["claims"])
    cur["answers"].append({"question": q, "answer": text, "local": local, "feedback": fb, "at": _now()})
    cur["i"] += 1
    done = cur["i"] >= len(cur["questions"])
    _save(role["key"], d)
    out = {"ok": True, "question_answered": q, "local": local, "feedback": fb, "done": done}
    if not done:
        out.update(question=cur["questions"][cur["i"]], number=cur["i"] + 1, of=len(cur["questions"]))
    return out


def _score(a: dict):
    fb = a.get("feedback") or {}
    return fb.get("score") if fb.get("score") is not None else fb.get("local_score")


def finish(role: dict) -> dict:
    """End the session: the summary, and how it compares with the last one."""
    d = _load(role["key"])
    cur = d.get("current")
    if not cur or not cur.get("answers"):
        d.pop("current", None)
        _save(role["key"], d)
        return {"ok": False, "error": "Nothing answered yet, so there's nothing to sum up."}
    scored = [(a, _score(a)) for a in cur["answers"] if _score(a) is not None]
    avg = round(sum(s for _, s in scored) / len(scored), 1) if scored else None
    weakest = sorted(scored, key=lambda x: x[1])[:3]
    work_on = [{"question": a["question"], "score": s,
                "fix": (a.get("feedback") or {}).get("fix") or "; ".join(a["local"]["notes"][:2])}
               for a, s in weakest if s < 4]
    claims = sorted({c for a in cur["answers"] for c in a["local"].get("claims", [])})
    prev = [s for s in d.get("sessions", []) if s.get("average") is not None]
    session = {**cur, "average": avg, "work_on": work_on, "ended": _now()}
    d.setdefault("sessions", []).append(session)
    d.pop("current", None)
    _save(role["key"], d)
    out = {"ok": True, "answered": len(cur["answers"]), "of": len(cur["questions"]),
           "average": avg, "work_on": work_on, "claims": claims,
           "scale": "engine" if any((a.get("feedback") or {}).get("score") is not None
                                    for a in cur["answers"]) else "local"}
    if prev and avg is not None:
        out["last_average"] = prev[-1]["average"]
        out["change"] = round(avg - prev[-1]["average"], 1)
    return out
