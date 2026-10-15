"""Is this letter good enough to send? A quality check before anything goes out.

The fabrication guard answers one question — does the draft claim something
you can't back? — and a letter can pass it and still be the kind recruiters
bin in four seconds: "I am writing to express my keen interest…", nothing
about this company, nothing done, nothing measured. That is the complaint
people make about AI applications (AIApply's reviews say exactly this: lots
sent, few interviews). So every draft is also scored for quality, locally,
no engine:

  * specific to THIS role: names the company, uses the terms the advert
    asks for (the ones your profile can back);
  * evidence: something you did and a result or a number;
  * no filler: the stock phrases recruiters skim past;
  * a sensible length for an email application (about 120–300 words);
  * an opening that isn't a formula, and a clear close;
  * and none of the sentences you've taught it to stop writing.

0–100, with the reasons. In auto-apply a draft under your bar is redrafted
once with those reasons as instructions; if it's still under, it's held for
you with them — it never goes out weak just because it's honest.
"""
from __future__ import annotations

import re

DEFAULT_BAR = 60
FILLER = [
    "i am writing to express", "i am writing to apply", "keen interest", "passionate about",
    "team player", "fast-paced", "dynamic environment", "go-getter", "hard-working",
    "results-driven", "detail-oriented", "think outside the box", "synergy", "esteemed",
    "i believe i would be a great fit", "perfect fit", "dream job", "to whom it may concern",
    "i am confident that", "proven track record", "wealth of experience", "self-starter",
    "exciting opportunity", "leverage my skills", "excellent communication skills",
]
_RESULT = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|x\b|times|hours?|days?|weeks?|months?|"
                     r"people|users|clients|customers|branches|reports?|jobs|pipelines|"
                     r"million|thousand|k\b|m\b)|\bR\s?\d|\$\s?\d|\b(cut|reduced|increased|grew|saved|"
                     r"halved|doubled|improved|sped up|automated)\b", re.I)
_DID = re.compile(r"\bI\s+(built|led|ran|designed|wrote|migrated|moved|created|shipped|delivered|"
                  r"automated|rebuilt|launched|set up|owned|managed|fixed|introduced|replaced)\b", re.I)
_CLOSE = re.compile(r"\b(happy to|glad to|would welcome|available|call|chat|talk|speak|discuss|"
                    r"look forward|attached|portfolio|reach me)\b", re.I)


def _words(t: str) -> list:
    return re.findall(r"[A-Za-z0-9'’+#.-]+", t or "")


def score(body: str, role: dict | None = None, profile: dict | None = None) -> dict:
    """{score, grade, reasons:[what to fix], good:[what works]}"""
    from . import cv as cvmod
    text = body or ""
    low = text.lower()
    n = len(_words(text))
    pts, reasons, good = 100, [], []

    hits = [f for f in FILLER if f in low]
    if hits:
        pts -= min(30, 10 * len(hits))
        reasons.append("Cut the stock phrases: " + ", ".join(f"“{h}”" for h in hits[:4]) + ".")
    company = str((role or {}).get("company") or "").strip()
    if company:
        toks = [w for w in re.findall(r"[a-z0-9]+", company.lower()) if len(w) > 2
                and w not in ("pty", "ltd", "the", "inc", "group", "limited", "holdings")]
        if toks and not any(t in low for t in toks):
            pts -= 15
            reasons.append(f"Say why {company} — the letter never names them.")
        elif toks:
            good.append("Names the company.")
    advert = " ".join(str((role or {}).get(k) or "") for k in ("title", "summary", "description"))
    terms = cvmod.requirements(advert)["terms"] if advert.strip() else []
    if terms:
        have = cvmod._profile_text(profile or {}) if profile is not None else ""
        backed = [t for t in terms if not have or t in have]
        used = [t for t in backed if t in low]
        if backed and len(used) < min(2, len(backed)):
            pts -= 15
            reasons.append("Use what the advert asks for that you can back: "
                           + ", ".join(t for t in backed if t not in used)[:120] + ".")
        elif used:
            good.append(f"Uses the advert's terms ({', '.join(used[:3])}).")
    if not _DID.search(text):
        pts -= 15
        reasons.append("Say one thing you did, in the first person (“I built…”, “I led…”).")
    else:
        good.append("Leads with something you did.")
    if not _RESULT.search(text):
        pts -= 15
        reasons.append("Give a result — what changed, with a number if you have one.")
    else:
        good.append("Has a result.")
    if n < 90:
        pts -= 15
        reasons.append(f"Too short ({n} words) — 120 to 300 reads as considered.")
    elif n > 340:
        pts -= 15
        reasons.append(f"Too long ({n} words) — cut to the one example and the result.")
    first = re.sub(r"^(dear|hi|hello)[^\n,]*,?\s*", "", text.strip(), flags=re.I).strip()
    if re.match(r"^(i am|my name is|i'm)\b", first, re.I):
        pts -= 10
        reasons.append("Don't open with “I am…” / “My name is…” — open with the work.")
    if not _CLOSE.search(text[-300:]):
        pts -= 5
        reasons.append("End with a clear next step (a call, a chat, what's attached).")
    try:
        from . import style
        cuts = [r for r in style.rules() if r["kind"] == "cut"]
        for r in cuts:
            frag = r["id"].split(":", 1)[1][:40]
            if frag and frag in re.sub(r"\s+", " ", low):
                pts -= 10
                quoted = re.search(r"“([^”]+)”", r["text"])
                reasons.append("You've cut this kind of sentence before: “"
                               + (quoted.group(1) if quoted else frag) + "”.")
                break
    except Exception:
        pass
    s = max(0, min(100, pts))
    grade = "strong" if s >= 80 else "fair" if s >= DEFAULT_BAR else "weak"
    return {"score": s, "grade": grade, "reasons": reasons, "good": good, "words": n}


def instructions(q: dict) -> str:
    """The reasons, as a redraft instruction."""
    if not q.get("reasons"):
        return ""
    return ("\nYOUR LAST DRAFT FOR THIS ROLE FELL SHORT. Fix these, without "
            "adding any claim the PROFILE doesn't support:\n- " + "\n- ".join(q["reasons"]))
