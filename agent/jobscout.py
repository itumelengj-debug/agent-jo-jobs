"""Job scout — find remote contract work, and apply as yourself.

The loop: keep a PROFILE of what you actually are and want; SCAN sources for
remote contracting roles; SCORE each honestly (including the reasons against);
DRAFT tailored application material; you REVIEW and send; TRACK what happened
and when to follow up.

Three design decisions worth stating, because they're what make this useful
rather than dangerous:

  GROUNDED, NOT INVENTED. The drafter may only use facts from your profile.
  Every draft then goes through a fabrication check that scans for specifics
  it can't source — technologies, employers, year-counts, certifications —
  and flags them. An application that quietly claims five years of something
  you've touched twice is worse than no application: it gets found out in
  the interview, and it is your name on it.

  YOU SEND, NOT THE AGENT. Everything up to the send is automated. The send
  is yours. Not a rule for its own sake — an autonomous sender that gets one
  fact wrong has misrepresented you to a real employer under your name, and
  there is no unsend. The cost of a wrong send is asymmetric, so the human
  goes exactly there. Same pattern as self-improve and trend adoption.

  HONEST SCORING. A scout that says every role is a great fit is a scout you
  stop reading. Fit scores carry their reasons AGAINST, and roles you don't
  qualify for are marked as such rather than quietly padded.
"""
from __future__ import annotations

import functools
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

MAX_ROLES = 25
STAGES = ["found", "drafted", "applied", "responded", "interview",
          "offer", "closed"]


def _dir() -> Path:
    d = config.AGENT_HOME / "jobscout"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60]


# --------------------------------------------------------------------------- #
#  profile — the only source of truth a draft may draw on
# --------------------------------------------------------------------------- #
DEFAULT_PROFILE = {
    # Portal forms ask for these every time; an email application never did,
    # which is why they weren't here before.
    "full_name": "",
    "email": "",
    "phone": "",
    "location": "",
    "linkedin": "",
    "github": "",
    "website": "",
    "cv_path": "",
    "headline": "",
    "summary": "",
    "skills": [],
    "technologies": [],
    "employers": [],
    "achievements": [],
    "certifications": [],
    "years_experience": {},
    # Empty by default. These used to hold the author's own targets — Data
    # Engineer, BI Consultant, remote contract, South Africa — which was
    # harmless in one person's app and wrong the moment anyone else
    # installed it: they'd start with someone else's job search, and the
    # onboarding would tell them step one was already done. Your saved
    # profile overrides these, so emptying them changes nothing for an
    # existing install.
    "target_roles": [],
    "arrangement": "",
    "rate": "",
    "availability": "",
    "locations_ok": [],
    "must_haves": [],
    "deal_breakers": [],
    "voice_notes": ("Write plainly and specifically. Short sentences. No "
                    "buzzwords, no 'passionate about', no superlatives. Lead "
                    "with a concrete thing built and what it changed."),
}


def _profile_path() -> Path:
    return _dir() / "profile.json"


def profile() -> dict:
    try:
        p = json.loads(_profile_path().read_text("utf-8"))
        return {**DEFAULT_PROFILE, **p}
    except Exception:
        return dict(DEFAULT_PROFILE)


def save_profile(p: dict) -> dict:
    merged = {**profile(), **(p or {})}
    _profile_path().write_text(json.dumps(merged, indent=2), "utf-8")
    return merged


def profile_ready() -> tuple[bool, str]:
    p = profile()
    if not (p.get("summary") or p.get("achievements")):
        return False, ("Your profile is empty. Fill it in first (or ask the "
                       "agent to build it from your CV) — drafts are only "
                       "allowed to use what's in there.")
    return True, ""


# --------------------------------------------------------------------------- #
#  roles
# --------------------------------------------------------------------------- #
def _roles_path() -> Path:
    return _dir() / "roles.json"


def roles() -> list:
    """Every tracked role.

    A file that won't parse used to read as "no roles". It was written in
    place, so a read that landed mid-write saw half a file — and the next
    save from that reader (discovery adding roles, say) wrote back only what
    it had, wiping the rest. Writes are atomic now; if the file still won't
    parse, the last good copy is used rather than nothing.
    """
    p = _roles_path()
    for _ in range(3):
        try:
            return json.loads(p.read_text("utf-8"))
        except FileNotFoundError:
            return []
        except Exception:
            time.sleep(0.05)
    try:
        return json.loads(p.with_name(p.name + ".bak").read_text("utf-8"))
    except Exception:
        return []


def save_roles(rs: list) -> None:
    """Write the whole list atomically, keeping the previous copy as .bak."""
    p = _roles_path()
    text = json.dumps(rs, indent=2)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, "utf-8")
    try:
        if p.exists():
            p.with_name(p.name + ".bak").write_text(p.read_text("utf-8"), "utf-8")
    except Exception:
        pass
    # Windows refuses to replace a file another process is reading at that
    # instant (both apps read this one); a moment later it's free
    for i in range(10):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    p.write_text(text, "utf-8")
    try:
        tmp.unlink()
    except Exception:
        pass


# Every read-modify-write of the roles happens under one lock. Runs now go on
# in the background while you use the window, and two writers interleaving —
# a run updating a role while you archive another — lost one of the changes.
_ROLES_LOCK = threading.RLock()


def _locked(fn):
    @functools.wraps(fn)
    def inner(*a, **k):
        with _ROLES_LOCK:
            return fn(*a, **k)
    return inner


def _looks_like_a_real_role(job: dict) -> bool:
    """A vacancy has a title AND something to identify it by. Without a
    company or a link there is nothing to apply to, and drafting against it
    produces a letter addressed to nobody."""
    title = " ".join(str(job.get("title") or "").split())
    if len(title) < 4 or _is_category_link(title, job.get("company", "")):
        return False
    return bool(str(job.get("company") or "").strip()
                or str(job.get("url") or "").strip())


@_locked
def add_roles(found: list) -> dict:
    """Merge newly-found roles.

    Skips ones already tracked, and ones the user has removed — otherwise
    deleting a role you've decided against just means seeing it again after
    the next scan."""
    rs = roles()
    have = {r.get("key") for r in rs}
    have |= {k.lower() for k in ignored_keys()}
    by_key = {r.get("key"): r for r in rs}
    # the same advert is the same role, whatever it's called this time
    have_urls = {normalise_url(_as_text(r.get("url"))) for r in rs if r.get("url")}
    added, touched = 0, False
    for f in found or []:
        title = _as_text(f.get("title")).strip()
        company = _as_text(f.get("company")).strip()
        if not title:
            continue
        # last line of defence: a category link or a title with nothing to
        # apply to must never become a tracked role, whatever route it took
        if not _looks_like_a_real_role({**f, "title": title,
                                        "company": company}):
            continue
        key = _key_for(company, title, _as_text(f.get("url")))
        url_n = normalise_url(_as_text(f.get("url"))) if f.get("url") else ""
        if not company and url_n and url_n in have_urls:
            continue
        if key in have or key.lower() in have:
            # seen again: an advert whose posting date moved forward while
            # we tracked it was reposted to look new — a ghost-job sign
            old = by_key.get(key)
            new_when = _posted(f.get("posted_at"))
            if old is not None and new_when:
                if old.get("posted_at") and new_when > old["posted_at"] \
                        and old.get("stage") in ("found", "drafted"):
                    old["reposted"] = int(old.get("reposted") or 0) + 1
                    old["first_posted_at"] = old.get("first_posted_at") or old["posted_at"]
                    old["posted_at"] = new_when
                    touched = True
                elif not old.get("posted_at"):
                    old["posted_at"] = new_when
                    touched = True
            continue
        rs.append({
            "key": key, "title": title[:160], "company": company[:120],
            "url": _as_text(f.get("url"))[:500],
            "location": _as_text(f.get("location"))[:120],
            "summary": _as_text(f.get("summary"))[:600],
            # the whole advert, for scoring, drafting and the checks: they all
            # read "description", which was never kept, so the engine judged
            # every role on its first 600 characters — usually the company blurb
            "description": _as_text(f.get("description"))[:ADVERT_CHARS],
            "source": _as_text(f.get("source"))[:60],
            "apply_email": _as_text(f.get("apply_email")
                                    or f.get("email"))[:200],
            "found_at": _iso(), "posted_at": _posted(f.get("posted_at")),
            # what the board itself said: remote or not, the countries a
            # remote role is open to, the country a one-country board serves,
            # when the advert closes, what it pays
            **({"remote": True} if f.get("remote") else {}),
            **({"countries": [str(c)[:40] for c in f["countries"]][:250]}
               if isinstance(f.get("countries"), (list, tuple)) and f.get("countries") else {}),
            **({"country": _as_text(f.get("country"))[:2].upper()} if f.get("country") else {}),
            **({"closes_at": _posted(f.get("closes_at"))} if _posted(f.get("closes_at")) else {}),
            **({"salary": _as_text(f.get("salary"))[:60]} if f.get("salary") else {}),
            "stage": "found",
            "fit": None, "draft": None, "events": [],
        })
        have.add(key)
        if url_n:
            have_urls.add(url_n)
        added += 1
    # every role is kept: trimming to the newest 200 here silently deleted
    # older ones, applications and replies included
    if added or touched:
        save_roles(rs)
    _audit("found", f"{added} new role(s)")
    return {"ok": True, "added": added, "total": len(roles())}


def get_role(key: str) -> dict | None:
    for r in roles():
        if r["key"] == key:
            return r
    return None


@_locked
def update_role(key: str, **fields) -> dict:
    rs = roles()
    for i, r in enumerate(rs):
        if r["key"] == key:
            rs[i] = {**r, **fields}
            save_roles(rs)
            return {"ok": True, "role": rs[i]}
    return {"ok": False, "error": "no such role"}


@_locked
def set_stage(key: str, stage: str, note: str = "") -> dict:
    if stage not in STAGES:
        return {"ok": False, "error": f"stage must be one of {STAGES}"}
    r = get_role(key)
    if r is None:
        return {"ok": False, "error": "no such role"}
    events = list(r.get("events") or [])
    events.append({"at": _iso(), "stage": stage, "note": note[:300]})
    res = update_role(key, stage=stage, events=events,
                      stage_at=_iso())
    _audit("stage", f"{r['title']} @ {r.get('company', '')} → {stage}")
    return res


def follow_ups(days: int = 7) -> list:
    """Applications that have gone quiet and are worth a nudge."""
    out = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for r in roles():
        if r.get("stage") != "applied":
            continue
        try:
            when = datetime.strptime(r.get("stage_at", ""), "%Y-%m-%d %H:%M UTC")
            when = when.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if when < cutoff:
            out.append({**r, "silent_days": (
                datetime.now(timezone.utc) - when).days})
    return out


# --------------------------------------------------------------------------- #
#  fabrication guard — the safeguard that makes autonomy safe
# --------------------------------------------------------------------------- #
_CLAIM_YEARS = re.compile(r"(\d+)\+?\s*(?:years?|yrs?)", re.I)

# Proper-noun detection misses lower-case tool names — and "dbt", "terraform"
# and friends are exactly what a draft is tempted to claim. A modest lexicon
# of the tools that actually come up in data/BI/AI contracting closes the gap
# the capitalisation rule leaves open.
_TECH_LEXICON = {
    "dbt", "airflow", "dagster", "prefect", "spark", "kafka", "flink",
    "snowflake", "databricks", "redshift", "bigquery", "synapse", "fabric",
    "terraform", "ansible", "kubernetes", "k8s", "docker", "helm",
    "postgres", "postgresql", "mysql", "mongodb", "cassandra", "clickhouse",
    "duckdb", "sqlite", "oracle", "sap", "salesforce", "tableau", "looker",
    "qlik", "superset", "metabase", "pandas", "numpy", "pytorch",
    "tensorflow", "sklearn", "langchain", "llamaindex", "pinecone", "faiss",
    "kubeflow", "mlflow", "sagemaker", "vertex", "bedrock", "azure", "aws",
    "gcp", "django", "flask", "fastapi", "react", "angular", "kotlin",
    "scala", "rust", "golang", "graphql", "grafana", "prometheus", "splunk",
    "informatica", "talend", "matillion", "fivetran", "stitch",
}
_STOP = {
    "I", "My", "The", "A", "An", "We", "Our", "This", "That", "As", "At",
    "In", "On", "For", "With", "And", "But", "You", "Your", "It", "If",
    "When", "While", "From", "To", "By", "Of", "Is", "Are", "Was", "Were",
    "Remote", "Contract", "Dear", "Hi", "Hello", "Regards", "Kind", "Best",
    "Sincerely", "Thanks", "Thank", "Team", "Role", "Position", "Company",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "January",
    "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
    # the words every letter uses around the claims, not claims themselves
    "Hiring", "Manager", "Recruiter", "Recruitment", "Sir", "Madam", "Mr", "Mrs", "Ms",
    "Yours", "Warm", "Cheers", "Please", "Attached", "Looking", "Happy", "Glad",
    "Also", "Since", "After", "Before", "Over", "Today", "Currently", "Recently",
    # words that open a sentence and can never be a claim — a follow-up that
    # began "Following up on…" was held for mentioning "Following"
    "Following", "Just", "Further", "Regarding", "Re", "Hope", "Wanted", "Writing",
    "Apologies", "Any", "Let", "Would", "Could", "Should", "Here", "There", "These",
    "Those", "What", "Which", "How", "Why", "Where", "Last", "Next", "Earlier",
    "Previously", "Additionally", "However", "Meanwhile", "Yes", "Either", "Both",
    "Having", "Given", "Ahead", "Separately", "Finally", "First", "Firstly",
}


def _profile_corpus(p: dict, role: dict | None = None) -> str:
    # your own name and town: a letter signed "Thandi" was held for
    # mentioning someone the profile didn't know
    bits = [_as_text(p.get("full_name")), _as_text(p.get("location")),
            _as_text(p.get("summary")), _as_text(p.get("headline")),
            " ".join(_as_list(p.get("skills"))),
            " ".join(_as_list(p.get("technologies"))),
            " ".join(_as_list(p.get("employers"))),
            " ".join(_as_list(p.get("achievements"))),
            " ".join(_as_list(p.get("certifications"))),
            json.dumps(p.get("years_experience") or {})]
    # the pasted CV is yours too: a tool or employer named there may be
    # claimed (agent/cvstore.py)
    try:
        from . import cvstore
        bits.append(cvstore.text())
    except Exception:
        pass
    if role:
        # terms lifted from the advert itself are fair to echo back
        bits += [_as_text(role.get("title")), _as_text(role.get("company")),
                 _as_text(role.get("summary")), _as_text(role.get("description"))]
    return " ".join(bits).lower()


def check_draft(text: str, role: dict | None = None) -> dict:
    """Flag specifics the draft asserts that the profile can't support.

    Deliberately conservative: it reports SUSPECTED unsupported claims for a
    human to glance at, rather than silently rewriting. A false flag costs
    you two seconds; a missed fabrication costs you an interview."""
    p = profile()
    corpus = _profile_corpus(p, role)
    text = _as_text(text)
    problems = []

    for m in _CLAIM_YEARS.finditer(text):
        span = text[max(0, m.start() - 60):m.end() + 20]
        n = m.group(1)
        stated = json.dumps(p.get("years_experience") or {})
        if n not in stated:
            problems.append({
                "kind": "year-claim",
                "detail": f"claims “{m.group(0)}” — not in your profile's "
                          f"years_experience",
                "context": span.strip()[:140]})

    # proper nouns / product names that don't appear anywhere in the profile
    for token in set(re.findall(r"\b([A-Z][A-Za-z0-9+.#/-]{2,})\b", text)):
        if token in _STOP or token.lower() in corpus:
            continue
        if len(token) < 3:
            continue
        problems.append({
            "kind": "unsourced-term",
            "detail": f"mentions “{token}”, which isn't in your profile or "
                      f"the advert",
            "context": ""})

    low = text.lower()
    for term in _TECH_LEXICON:
        if re.search(rf"\b{re.escape(term)}\b", low) and term not in corpus:
            problems.append({
                "kind": "unsourced-tool",
                "detail": f"mentions “{term}”, which isn't in your profile or "
                          f"the advert",
                "context": ""})

    seen, unique = set(), []
    for pr in problems:
        k = (pr["kind"], pr["detail"])
        if k not in seen:
            seen.add(k)
            unique.append(pr)
    return {"ok": not unique, "problems": unique[:12],
            "checked_chars": len(text)}


# --------------------------------------------------------------------------- #
#  scoring + drafting (engine-backed, strictly grounded)
# --------------------------------------------------------------------------- #
_SCORE_SYSTEM = (
    "You assess how well ONE candidate fits ONE role, to decide whether applying "
    "is worth their time. Be honest and useful, not encouraging and not harsh.\n"
    "Read PROFILE and CV_EXCERPTS together: both are the candidate's. Before you "
    "call anything missing, check both. Never list as missing a tool, a "
    "qualification or experience that appears in either.\n"
    "The score answers: should this person apply?\n"
    "  85-100  meets nearly every core requirement; a strong application.\n"
    "  70-84   meets most core requirements; gaps are learnable or are the same "
    "kind of tool from another vendor. Worth applying.\n"
    "  50-69   a stretch: a core requirement is genuinely absent (the main "
    "discipline, the seniority, a must-have domain).\n"
    "  0-49    a different job, or a hard requirement they cannot meet.\n"
    "Judge as a hiring manager would. Equivalent tools count as near-matches, "
    "not as gaps: Azure for AWS or GCP, Databricks or Synapse for Snowflake or "
    "BigQuery, Power BI for Tableau or Looker, one orchestrator or SQL database "
    "for another. A long list of 'nice to have' tools is not a list of "
    "requirements. Seniority one level either side is not a mismatch. Score "
    "low when the discipline differs, when years or level are far off, when "
    "the advert requires a location, language or right to work they lack, or "
    "when a must-have has no equivalent in their background.\n"
    "Return ONLY raw JSON: {\"score\": 0-100, \"verdict\": "
    "\"strong\"|\"possible\"|\"weak\", \"for\": [reasons this fits], "
    "\"against\": [honest reasons it may not], \"missing\": [requirements "
    "the candidate does NOT demonstrably meet, after checking PROFILE and "
    "CV_EXCERPTS]}.")

_DRAFT_SYSTEM = (
    "You draft a short application message for a candidate, in THEIR voice.\n"
    "ABSOLUTE RULE: use only facts present in the PROFILE or CV_EXCERPTS. Never invent an "
    "employer, technology, certification, metric or number of years. If the "
    "role wants something the profile doesn't show, either omit it or state "
    "plainly what the candidate has done that is adjacent — never imply "
    "experience they lack.\n"
    "Write plainly: short sentences, concrete specifics, no buzzwords, no "
    "'passionate about', no superlatives, no filler openings. Lead with one "
    "real thing they built and what changed because of it. 150-220 words.\n"
    "Return ONLY raw JSON: {\"subject\": str, \"body\": str, \"gaps\": "
    "[anything the role asked for that you could NOT support from the "
    "profile]}.")


def _json_from(resp) -> dict:
    text = "\n".join(b.text for b in resp.content
                     if getattr(b, "type", "") == "text").strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start == -1:
            raise ValueError(f"engine returned no JSON: {text[:200]}")
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
        raise ValueError("engine returned truncated JSON")


# Worth one more try: a local model that wrapped its JSON in prose, a provider
# that said "overloaded". Anything else (no credit, a bad key) won't change in
# two seconds, so it fails at once with the reason.
_TRANSIENT = ("no json", "truncated json", "jsondecodeerror", "expecting",
              "overloaded", "529", "503", "502", "rate", "timeout",
              "timed out", "temporarily", "connection reset")


def _engine_json(brain, payload: str, system: str, model=None) -> dict:
    kw = {"model": model} if model else {}
    last = None
    for attempt in range(2):
        prompt = system if not attempt else (
            system + "\nReply with the JSON object only: no prose, no code fence.")
        try:
            return _json_from(brain.chat([{"role": "user", "content": payload}],
                                         [prompt], None, **kw))
        except Exception as exc:
            last = exc
            low = f"{type(exc).__name__}: {exc}".lower()
            if not any(t in low for t in _TRANSIENT):
                break
            if any(t in low for t in ("overloaded", "529", "503", "rate")):
                time.sleep(3)
    raise last


def _parse_score(v):
    """82, "82", "82/100", "82%", "8.2/10" -> 82. None when there's no number.

    A reply with no usable score was recorded as 0 — so a local model that
    answered "score": "82/100", or called it "fit", wrote the role off as a
    poor match for good, and it was never looked at again."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        n = float(v)
    else:
        m = re.search(r"\d+(?:\.\d+)?", str(v))
        if not m:
            return None
        n = float(m.group())
        if re.search(r"/\s*10(?!\d)", str(v)) and n <= 10:
            n *= 10
    return max(0, min(100, int(round(n))))


def score_role(key: str, brain, model=None) -> dict:
    r = get_role(key)
    if r is None:
        return {"ok": False, "error": "no such role"}
    ok, why = profile_ready()
    if not ok:
        return {"ok": False, "error": why}
    # the CV too: scored on the short profile alone, a real engine reported a
    # degree and a tool as missing that were on the CV all along
    try:
        from . import cvstore
        cv = cvstore.excerpts(f"{r.get('title', '')} {r.get('description') or r.get('summary', '')}"[:1500],
                              k=5, limit=3500)
    except Exception:
        cv = ""
    slim = {k: r.get(k) for k in ("title", "company", "location", "salary", "summary", "description")
            if r.get(k)}
    payload = json.dumps({"PROFILE": profile(), "CV_EXCERPTS": cv, "ROLE": slim}, default=str)[:16000]
    try:
        data = _engine_json(brain, payload, _SCORE_SYSTEM, model)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    score = _parse_score(data.get("score", data.get("fit", data.get("rating"))))
    if score is None:
        # left unscored, so the next run asks again, rather than filed as 0
        return {"ok": False, "error": "the engine's reply had no score in it: "
                                      + json.dumps(data, default=str)[:160]}
    fit = {"score": score,
           "verdict": _as_text(data.get("verdict")) or "possible",
           "for": _as_list(data.get("for"))[:6],
           "against": _as_list(data.get("against"))[:6],
           "missing": _as_list(data.get("missing"))[:6],
           "at": _iso()}
    update_role(key, fit=fit)
    return {"ok": True, "fit": fit}


def _banned_clause() -> str:
    """A dismissed claim must not reappear in the next draft, or the same
    question gets asked forever."""
    b = banned_claims()
    if not b:
        return ""
    return ("\nNEVER mention any of these, in any form — the candidate has "
            "explicitly said they do not claim them: " + ", ".join(b) + ".")


def _style_clause(skip: tuple = ()) -> str:
    try:
        from . import style
        return style.prompt_clause(skip)
    except Exception:
        return ""


def save_draft(key: str, body: str, subject: str = "") -> dict:
    """Your edit of a draft: kept as the draft, re-checked, and learned from."""
    r = get_role(key)
    if r is None:
        return {"ok": False, "error": "no such role"}
    body = (body or "").strip()
    if len(body) < 20:
        return {"ok": False, "error": "That's too short to send — write the letter, or redraft it."}
    old = r.get("draft") or {}
    subject = (subject or old.get("subject") or f"Application: {r.get('title', '')}").strip()[:200]
    learned = {}
    if " ".join((old.get("body") or "").split()) == " ".join(body.split()) \
            and subject == (old.get("subject") or subject):
        return {"ok": True, "draft": old, "learned": False, "unchanged": True}
    if old.get("body"):
        from . import style
        learned = style.record(old.get("engine_body") or old["body"], body, key=key,
                               subject_before=old.get("subject", ""), subject_after=subject)
    draft = {**old, "subject": subject, "body": body, "check": check_draft(body, r),
             "quality": _quality(body, r),
             "edited": True, "edited_at": _iso(),
             # what the engine first wrote, so a second edit is compared with it
             "engine_body": old.get("engine_body") or old.get("body", "")}
    # an approval was of the old words; this text hasn't been approved
    fields = {"draft": draft, "approved": False}
    if r.get("stage") in ("found", "scored", "screened", None):
        fields["stage"] = "drafted"
    update_role(key, **fields)
    _audit("draft", f"you edited {r.get('title', '')} @ {r.get('company', '')}"
                    + ("" if draft["check"]["ok"] else " — still claims something to verify"))
    return {"ok": True, "draft": draft, "learned": bool(learned.get("recorded"))}


def _quality(body: str, r: dict) -> dict:
    try:
        from . import quality
        return quality.score(body, r, profile())
    except Exception:
        return {}


_REPLIED = {"offer": 3, "interview": 2, "responded": 1}
_EXAMPLES_CLAUSE = (
    "\nLETTERS_THAT_GOT_REPLIES, when given, are the candidate's own earlier "
    "letters that led to a reply, an interview or an offer. Learn from their "
    "tone, length and structure. Never copy their facts, employers, numbers or "
    "claims: every claim must still come from PROFILE and CV_EXCERPTS.")


def _title_words(r: dict) -> set:
    return {w for w in re.findall(r"[a-z0-9+#]+", str((r or {}).get("title") or "").lower())
            if len(w) > 2 and w not in ("senior", "junior", "lead", "the", "and", "for", "remote")}


def letters_that_worked(role: dict, limit: int = 2) -> list:
    """Your own sent letters that got a reply worth having — a reply, an
    interview, an offer — most like this role first.

    Every application's outcome is evidence about what works, and until now
    the next draft never saw it. These go to the engine as examples of tone
    and structure, never as a source of facts; the claims check still reads
    every word of the new letter."""
    want = _title_words(role)
    found = []
    for r in roles():
        if r.get("key") == (role or {}).get("key") or r.get("stage") not in _REPLIED:
            continue
        d = r.get("draft") or {}
        if not d.get("body") or (d.get("check") or {}).get("ok") is False:
            continue
        words = _title_words(r)
        alike = len(want & words) / max(1, len(want | words))
        found.append((alike, _REPLIED[r["stage"]], r))
    found.sort(key=lambda x: (-x[0], -x[1]))
    if any(alike > 0 for alike, _, _ in found):
        found = [f for f in found if f[0] > 0]   # similar roles, when there are any
    return [{"for": " @ ".join(x for x in (r.get("title"), r.get("company")) if x),
             "outcome": r["stage"], "letter": str((r.get("draft") or {}).get("body"))[:1800]}
            for _, _, r in found[:limit]]


def draft_application(key: str, brain, model=None, fix: str = "") -> dict:
    r = get_role(key)
    if r is None:
        return {"ok": False, "error": "no such role"}
    ok, why = profile_ready()
    if not ok:
        return {"ok": False, "error": why}
    p = profile()
    # the parts of the full CV that bear on this advert, so the letter can
    # cite real work, not only the profile's summary
    try:
        from . import cvstore
        cv = cvstore.excerpts(f"{r.get('title', '')} {r.get('summary', '')}", k=4)
    except Exception:
        cv = ""
    # what got replies before, for tone and shape only (last, so a long
    # profile never loses its own words to them)
    try:
        worked = letters_that_worked(r)
    except Exception:
        worked = []
    payload = json.dumps({"PROFILE": p, "CV_EXCERPTS": cv, "ROLE": r,
                          "VOICE": p.get("voice_notes", ""),
                          **({"LETTERS_THAT_GOT_REPLIES": worked} if worked else {})},
                         default=str)[:14000]
    try:
        data = _engine_json(brain, payload, _DRAFT_SYSTEM + _banned_clause()
                            + _style_clause() + (_EXAMPLES_CLAUSE if worked else "")
                            + (fix or ""), model)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    body = _as_text(data.get("body") or data.get("message")).strip()
    if not body:
        # saved as "drafted" with nothing in it, the role sat at "no draft
        # yet" looking finished; it stays undrafted so the next run tries
        return {"ok": False, "error": "the engine returned an empty draft"}
    check = check_draft(body, r)
    subject = _as_text(data.get("subject")).strip()
    draft = {"subject": (subject or f"Application: {r.get('title', '')}")[:200],
             "body": body,
             "gaps": _as_list(data.get("gaps"))[:8],
             "check": check, "quality": _quality(body, r), "at": _iso(),
             # which of your letters that got replies it learned from
             "learned_from": [f"{w['for']} ({w['outcome']})" for w in worked]}
    update_role(key, draft=draft, stage="drafted", approved=False)
    _audit("draft", f"{r['title']} @ {r.get('company', '')}"
                    + ("" if check["ok"]
                       else f" — {len(check['problems'])} claim(s) to verify"))
    return {"ok": True, "draft": draft}


def _as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return "\n".join(_as_text(x) for x in v if x is not None)
    if isinstance(v, dict):
        return "\n".join(f"{k}: {_as_text(x)}" for k, x in v.items())
    return str(v)


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [_as_text(x) for x in v if x is not None]
    return [_as_text(v)]


def summary() -> dict:
    rs = roles()
    by_stage = {s: 0 for s in STAGES}
    for r in rs:
        by_stage[r.get("stage", "found")] = by_stage.get(
            r.get("stage", "found"), 0) + 1
    return {"total": len(rs), "by_stage": by_stage,
            "follow_ups": len(follow_ups()),
            "profile_ready": profile_ready()[0]}


# --------------------------------------------------------------------------- #
#  auto-apply — fully automated, with the gates that make that survivable
# --------------------------------------------------------------------------- #
AUTO_DEFAULTS = {
    "enabled": False,
    "dry_run": True,        # starts in rehearsal: prepares and logs, sends
                            # nothing, so you can read a week of what it WOULD
                            # have sent before trusting it with your name
    "min_score": 70,        # below this it waits for you (70 = "worth applying" on the scoring scale)
    # a draft with unsourced claims never auto-sends
    "require_clean_check": True,
    # what to do with adverts that have no email address — most of them.
    # "prepare" fills the form and answers what it can, and leaves it to you;
    # "submit" finishes it too; "off" ignores portal-only roles.
    "portal_mode": "prepare",
    # A cap bounds the blast radius of any mistake. Five a day, and five forms
    # a run that couldn't be changed at all, made a job search that never got
    # going: every role cleared every gate and still waited a week. The caps
    # are yours to set now (Auto-apply), up to the limits below.
    "daily_cap": 25,
    # each prepared form is a page left open for you to finish; in "submit"
    # mode a form that clears every check is sent and closed instead
    "portal_per_run": 15,
    # how many newly found roles a run takes on; the rest wait for the next
    "discover_per_run": 150,
    # engine calls going at once while scoring and drafting
    "engine_workers": 4,
    # adverts that look like a ghost job (up for months, reposted, a "talent
    # pool") are set aside before any engine call, at or above this score
    # (agent/trust.py); scams are always set aside, whatever this says
    "skip_ghosts": True,
    "ghost_bar": 60,
    # every emailed application carries a CV: one made for the role (or
    # yours, as uploaded); and a CV reordered for each advert, checked like
    # the letters, when the engine can make one that invents nothing
    "attach_cv": True,
    "tailor_cv": True,
    # one short follow-up to an emailed application that has had no reply
    # after this many days — sent only where applications are (not in
    # rehearsal), checked like the letters, never a second time
    # read the advert page for roles that arrived with little text
    "read_adverts": True,
    "read_per_run": 40,
    "auto_follow_up": True,
    "follow_up_after_days": 7,
    "follow_ups_per_run": 10,
    "signature": "",
    # a draft below this quality score (agent/quality.py) is redrafted once,
    # then held for you — honest isn't the same as good enough to send
    "min_quality": 60,
    # a company site it doesn't know: may the engine work out the way to the
    # form, and how many steps may it take (agent/navigator.py)? What it
    # works out is kept, so the same site needs fewer next time.
    "explore": True,
    "explore_turns": 12,
}


def auto_config() -> dict:
    cfg = {**AUTO_DEFAULTS, **(load_config().get("auto") or {})}
    cfg["level"] = autonomy_of(cfg)
    return cfg


# --- how much it does without you --------------------------------------------- #
# One setting instead of three switches whose combinations were hard to read.
# Each level is the switches it stands for; set the switches by hand and the
# level reads "custom".
AUTONOMY = {
    "draft":   {"deliver": False, "dry_run": True,  "portal_mode": "off"},
    "prepare": {"deliver": True,  "dry_run": True,  "portal_mode": "prepare"},
    "email":   {"deliver": True,  "dry_run": False, "portal_mode": "prepare"},
    "full":    {"deliver": True,  "dry_run": False, "portal_mode": "submit"},
}
AUTONOMY_SAYS = {
    "draft": "Finds, scores and drafts. Sends nothing and opens nothing — you review.",
    "prepare": "Also fills in company forms for you to finish. Still sends nothing.",
    "email": "Sends emailed applications that clear every check; fills forms for you to finish.",
    "full": "Sends emailed applications and submits company forms that clear every check.",
}


def autonomy_of(cfg: dict) -> str:
    for name, sw in AUTONOMY.items():
        if all((cfg.get(k, True) if k == "deliver" else cfg.get(k)) == v
               for k, v in sw.items()):
            return name
    return "custom"


def set_autonomy(level: str) -> dict:
    if level not in AUTONOMY:
        return {"ok": False, "error": f"unknown level {level!r}"}
    cfg = save_auto_config(dict(AUTONOMY[level]))
    _audit("autonomy", f"set to {level}")
    return {"ok": True, "level": level, "auto": auto_config()}


# --- a report of every run ---------------------------------------------------- #
RUNS_KEPT = 90


def _runs_path() -> Path:
    return _dir() / "runs.json"


def run_reports(limit: int = 30) -> list:
    try:
        return json.loads(_runs_path().read_text("utf-8"))[:limit]
    except Exception:
        return []


def _record_run(res: dict, kind: str) -> dict:
    """Keep what a run did, so a scheduled run you weren't there for can be
    read afterwards: sent, prepared, held and why, errors, questions waiting."""
    try:
        from . import answerbank
        waiting = len(answerbank.open_questions())
    except Exception:
        waiting = 0
    pick = lambda xs, *ks: [{k: x.get(k) for k in ks if x.get(k) not in (None, "", [])}
                            for x in (xs or [])][:40]
    rep = {"at": _iso(), "kind": kind, "level": auto_config().get("level"),
           "summary": describe_run(res),
           "dry_run": bool(res.get("dry_run")),
           "discovered": res.get("discovered"),
           "replies": res.get("replies"),
           "sent": pick(res.get("sent"), "title", "company", "to", "dry_run"),
           "prepared": pick(res.get("prepared"), "title", "company", "url", "needs_you",
                            "learned", "engine_turns"),
           # what this run's forms taught it, in one place for the report
           "learned": [x for p in (res.get("prepared") or []) + (res.get("sent") or [])
                       for x in (p.get("learned") or [])][:20],
           "held": pick(res.get("held"), "title", "company", "reason"),
           "errors": (res.get("error_groups") or {}) if res.get("error_groups")
                     else {e: 1 for e in (res.get("errors") or [])[:10]},
           "waiting_questions": waiting,
           "error": res.get("error", "")}
    with _ROLES_LOCK:
        runs = [rep] + run_reports(RUNS_KEPT)
        p = _runs_path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(runs[:RUNS_KEPT], indent=1), "utf-8")
        tmp.replace(p)
    return rep


def save_auto_config(cfg: dict) -> dict:
    base = load_config()
    before = auto_config()
    new = {**before, **(cfg or {})}
    # the first time it goes live (really sending, or submitting forms), the
    # settling-in days start: a reduced pace while you watch the first ones
    live = not new.get("dry_run", True) and new.get("deliver", True)
    if live and not new.get("live_since"):
        new["live_since"] = _iso()
    new.pop("level", None)
    base["auto"] = new
    save_config(base)
    return base["auto"]


SETTLE_DAYS, SETTLE_CAP = 3, 2


def settling_in(cfg: dict | None = None) -> dict:
    """The first days live run at a reduced pace: at most SETTLE_CAP a day and
    SETTLE_CAP forms a run, so the first real applications are few enough to
    read. {'on', 'days_left'}"""
    cfg = cfg or auto_config()
    since = cfg.get("live_since") or ""
    if not since or cfg.get("dry_run", True) or cfg.get("settled"):
        return {"on": False, "days_left": 0}
    left = SETTLE_DAYS - _hours_since(since) / 24
    return {"on": left > 0, "days_left": max(0, round(left, 1))}


def end_settling_in() -> dict:
    save_auto_config({"settled": True})
    _audit("autonomy", "settling-in pace ended early")
    return {"ok": True}


def _explain_engine_error(err: str) -> str:
    """Say what actually went wrong.

    These were truncated to 80 characters, which cut every message off at
    exactly the point the reason began — a dozen identical lines reading
    "BadRequestError: Error code: 400 - {'type': 'error', 'error':
    {'type': 'invalid_" told nobody anything."""
    e = " ".join(str(err or "").split())
    low = e.lower()
    if "credit balance" in low or "billing" in low:
        return ("that engine has no credit. Pick a local engine in the Jobs "
                "panel — scoring and drafting then cost nothing.")
    if "rate" in low and "limit" in low:
        return "rate limited by the provider; it will work again shortly."
    if "401" in low or "unauthor" in low or "invalid x-api-key" in low:
        return "the API key was rejected — check it in Settings."
    if "connect" in low or "refused" in low or "timeout" in low:
        return ("could not reach the engine. If it's local, check Ollama is "
                "running.")
    if "text content blocks must be non-empty" in low:
        return "the advert had no text to score."
    if "max_tokens" in low or "too long" in low or "context" in low:
        return "the advert was too long for that engine's context."
    return e[:240]


def _sent_today() -> int:
    """Real applications today. A rehearsal sends nothing, so it uses none of
    the day's cap — it used to, and a morning of rehearsing left the real run
    with no room."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(1 for r in roles()
               if r.get("sent_at", "").startswith(today)
               and not r.get("sent_dry_run"))


def _undo_rehearsal_stages() -> int:
    """Put back roles an earlier rehearsal marked as applied.

    A rehearsal moved each role it "sent" to applied — so the roles that had
    cleared every gate, the best ones, were never sent once rehearsal was
    turned off. A rehearsal now leaves the role where it is; this repairs the
    ones it already moved. Idempotent.
    """
    n = 0
    for r in roles():
        if r.get("stage") == "applied" and r.get("sent_dry_run"):
            back = "drafted" if (r.get("draft") or {}).get("body") else "found"
            update_role(r["key"], sent_at="", sent_dry_run=False,
                        rehearsed_at=r.get("sent_at", ""))
            set_stage(r["key"], back, "rehearsal only; nothing was sent")
            n += 1
    return n


_NO_EMAIL = "no application email on the advert"


def check_trust(r: dict, others: list | None = None, save: bool = False) -> dict:
    """agent/trust.py's reading of one role; with save, kept on the role
    (trust, and salary when the advert gives one) for the window."""
    from . import trust as _trust
    try:
        t = _trust.assess(r, others)
    except Exception:
        return {"verdict": "ok", "ghost": 0, "ghost_why": [], "scam_why": [], "salary": ""}
    if save and r.get("key"):
        try:
            fields = {"trust": t}
            if t.get("salary") and not r.get("salary"):
                fields["salary"] = t["salary"]
            update_role(r["key"], **fields)
        except Exception:
            pass
    return t


def cv_file_for(r: dict, p: dict | None = None) -> dict:
    """The CV file that goes with this application: {path, kind, error}.

    kind is "tailored" (reordered for this advert, and checked), "yours" (the
    file you uploaded), or "designed" (a clean PDF made from your profile and
    pasted CV). An emailed application used to go with no CV at all: the
    letter said "attached" to nothing."""
    p = p or profile()
    tcv = r.get("tailored_cv") or {}
    tailored = bool((tcv.get("summary") or tcv.get("experience"))
                    and (tcv.get("check") or {}).get("ok", True))
    cached = str(r.get("cv_file") or "")
    if tailored and cached and Path(cached).is_file() \
            and r.get("cv_file_for") == tcv.get("at"):
        return {"path": cached, "kind": "tailored", "error": ""}
    if not tailored:
        own = str(p.get("cv_path") or "")
        if own and Path(own).is_file():
            return {"path": own, "kind": "yours", "error": ""}
        if cached and Path(cached).is_file() and not r.get("cv_file_for"):
            return {"path": cached, "kind": "designed", "error": ""}
    from . import resume
    err = ""
    for fmt in ("pdf", "docx"):          # a PDF needs the browser; Word doesn't
        try:
            made = resume.make(r if tailored else None, p, fmt=fmt)
        except Exception as exc:
            made = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if made.get("ok"):
            if tailored:
                # one file per role: the tailored CV is named for the company
                update_role(r["key"], cv_file=made["path"], cv_file_for=tcv.get("at"))
            return {"path": made["path"], "kind": "tailored" if tailored else "designed",
                    "error": ""}
        err = made.get("error", "")
    if tailored:
        own = str(p.get("cv_path") or "")
        if own and Path(own).is_file():
            return {"path": own, "kind": "yours", "error": ""}
    return {"path": "", "kind": "", "error": err or "there's no CV to attach yet"}


def _tailor_for(key: str, brain, model) -> None:
    """A CV reordered for this advert, kept only if it invents nothing
    (agent/cv.py verify_cv, the same strictness as the letters)."""
    from . import cv as _cv
    r = get_role(key) or {}
    if (r.get("tailored_cv") or {}).get("at"):
        return
    res = _cv.tailor_cv(r, profile(), brain, model=model)
    if not res.get("ok"):
        return
    cv = res["cv"]
    if not (cv.get("summary") or cv.get("experience")):
        return
    if (cv.get("check") or {}).get("ok") is False:
        update_role(key, tailored_cv_held=[x.get("detail", "") for x in
                                           (cv["check"].get("problems") or [])][:6])
        return
    update_role(key, tailored_cv=cv)


def _gate(r: dict, cfg: dict) -> str:
    """Return '' if this role may be auto-applied to, else why it can't.

    The address is checked last. It was checked first, and a role without one
    — most adverts — went straight to the portal path without ever meeting the
    fit threshold or the claim check: a 20% match, or a draft inventing a
    certification, had its form filled in, and submitted in submit mode.
    Every role now clears the same gates; only how it is delivered differs.
    """
    hit = deal_breaker(r)
    if hit and not r.get("approved"):
        return f"deal-breaker: “{hit}” is in the advert"
    # a scam is never applied to by itself, however it got onto the list —
    # added by hand, found before this check existed. Your approval is the
    # only way past it.
    t = check_trust(r)
    if t["verdict"] == "scam" and not r.get("approved"):
        from . import trust as _trust
        return _trust.says(t)
    fit = r.get("fit") or {}
    if fit.get("score") is None:
        return "not scored yet"
    # a draft you approved (from your phone, say) is your call on the fit;
    # every other gate below still applies
    if int(fit["score"]) < int(cfg["min_score"]) and not r.get("approved"):
        return f"fit {fit['score']} is below your threshold {cfg['min_score']}"
    d = r.get("draft") or {}
    if not d.get("body"):
        return "no draft yet"
    if d.get("needs_redraft"):
        # The app marks a draft for rewriting when what it says no longer
        # matches your profile. The gate never checked, so an unattended run
        # would have sent exactly the draft the app had flagged.
        return (d.get("redraft_reason")
                or "the draft needs rewriting since your profile changed")
    chk = d.get("check") or {}
    if cfg.get("require_clean_check", True) and chk.get("ok") is False:
        n = len(chk.get("problems") or [])
        return (f"draft makes {n} claim(s) I can't source from your profile "
                f"— needs your eyes")
    # after the claim check: a fabrication is the reason that matters most
    q = d.get("quality") or {}
    bar = int(cfg.get("min_quality", 60) or 0)
    if q and bar and q.get("score", 100) < bar and not r.get("approved"):
        first = (q.get("reasons") or ["it reads weak"])[0]
        return f"quality {q.get('score')}/100 is below your bar {bar} — {first}"
    if not _as_text(r.get("apply_email")).strip():
        return f"{_NO_EMAIL} — portal applications still need you"
    return ""


PORTAL_TRIES = 3


def _portal_brief(res: dict) -> dict:
    """What a role keeps of its last form attempt: enough to show what
    happened and what it learned, not every box it read."""
    keep = ("ok", "state", "message", "url", "form_url", "ats", "answers", "filled", "left",
            "paste_pack", "steps", "learned", "engine_turns", "pages", "explored",
            "waited_for_you", "apply_email", "site", "missing", "workday", "companion")
    return {k: res[k] for k in keep if k in res}
_PORTAL_WAITING = ("filled", "needs_answer", "unknown_form", "needs_login",
                   "needs_captcha")


def _hours_since(stamp: str) -> float:
    """Hours since one of _iso()'s stamps ("2026-10-01 20:40 UTC"); an ISO
    stamp is read too. Unreadable counts as long ago."""
    s = str(stamp or "").strip()
    for parse in (lambda: datetime.strptime(s, "%Y-%m-%d %H:%M UTC"),
                  lambda: datetime.fromisoformat(s.replace("Z", "+00:00"))):
        try:
            t = parse()
        except Exception:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600
    return 1e9


def _portal_wait(r: dict) -> str:
    """Why a portal role shouldn't be opened again this run, or ''.

    Every run reopened every portal form, prepared or not — another tab for
    the same advert each morning — and a form that failed was retried for
    ever."""
    p = r.get("portal") or {}
    state, at = p.get("state", ""), r.get("portal_at", "")
    if state in _PORTAL_WAITING and _hours_since(at) < 72:
        return ("its form was prepared and is waiting for you — use "
                "'Open the form with help' on the role to finish it")
    if state == "failed":
        tries = int(r.get("portal_attempts") or 0)
        if tries >= PORTAL_TRIES:
            return (f"its form failed {tries} times, so it is left to you — "
                    f"last time: {str(p.get('message', ''))[:140]}")
        if _hours_since(at) < 20:
            return "its form failed recently; it is tried again tomorrow"
    return ""


def auto_readiness() -> dict:
    """Everything that has to be true before an application can leave, and
    which of them isn't.

    The sending code was never broken. It is guarded by half a dozen separate
    conditions — rehearsal, an email account, observe mode, a scored role, a
    clean draft, an address on the advert — and when one of them was off,
    nothing said so: the run reported "0 sent" and looked like a failure. So
    the conditions are stated in one place, each with what to do about it.
    """
    from . import outreach
    cfg = auto_config()
    _undo_rehearsal_stages()
    roles_all = roles()
    ready, why = profile_ready()
    blockers, notes = [], []

    if not cfg.get("enabled"):
        blockers.append({"what": "Auto-apply is off",
                         "fix": "Turn it on — the switch in the sidebar, or here."})
    if cfg.get("dry_run", True):
        blockers.append({"what": "Rehearsal is on, so nothing is ever sent",
                         "fix": "Untick 'Rehearsal' once you've read a few drafts."})
    forms_on = str(cfg.get("portal_mode", "prepare")).lower() != "off" and cfg.get("deliver", True)
    mail = outreach.load_config()
    if not outreach.is_configured():
        item = {"what": "No email account is set up, so emailed applications can't be sent",
                "fix": "Auto-apply → Sending email: your address and its password (an app "
                       "password for Gmail). Then Send a test.", "where": "auto"}
        if forms_on:
            notes.append(item["what"] + " — company forms still work. " + item["fix"])
        else:
            blockers.append(item)
    elif not mail.get("enabled"):
        blockers.append({"what": "Sending from your email account is switched off",
                         "fix": "Auto-apply → Sending email → switch it on.", "where": "auto"})
    if forms_on:
        try:
            from . import portal
            pr = portal.readiness(portal.with_contact(profile()))
            if not pr["ready"]:
                blockers.append({"what": "Company forms need " + ", ".join(pr["missing"]),
                                 "fix": "Your profile → Contact details (forms ask for these every time).",
                                 "where": "profile"})
        except Exception:
            pass
        if str(cfg.get("portal_mode")) == "prepare":
            notes.append("Company forms are filled and left open for you to press Submit. "
                         "Choose the Full level to have them submitted.")
    try:
        from . import answerbank
        waiting = answerbank.open_questions()
        if waiting:
            held_up = len({k for q in waiting for k in (q.get("roles") or [])})
            notes.append(f"{len(waiting)} question(s) only you can answer are holding up "
                         f"{held_up} application(s) — Answers → Waiting on you.")
    except Exception:
        pass
    st = settling_in(cfg)
    if st["on"]:
        notes.append(f"Settling in: the first days live run at most {SETTLE_CAP} applications a day "
                     f"({st['days_left']} day(s) left) so you can read the first real ones.")
    try:
        if outreach._is_draft_only():
            blockers.append({"what": "Observe mode is on across the agent",
                             "fix": "It forces every send to a rehearsal. Turn "
                                    "it off in Agent Jo when you're ready."})
    except Exception:
        pass
    if not ready:
        blockers.append({"what": "Your profile isn't complete enough to draft",
                         "fix": why})

    # and the roles themselves: a run can only send what clears every gate
    reasons = {}
    sendable = 0
    for r in roles_all:
        if r.get("stage") == "applied":
            continue
        g = _gate(r, cfg)
        if g:
            reasons[g] = reasons.get(g, 0) + 1
        else:
            sendable += 1
    _cap = int(cfg.get("daily_cap", 25))
    if settling_in(cfg)["on"]:
        _cap = min(_cap, SETTLE_CAP)
    room = max(0, _cap - _sent_today())
    if not roles_all:
        blockers.append({"what": "No roles are being tracked",
                         "fix": "Search, or add a source and let it find some."})
    elif not sendable:
        top = sorted(reasons.items(), key=lambda kv: -kv[1])[:3]
        blockers.append({"what": "No tracked role currently clears the gates",
                         "fix": "; ".join(f"{n} — {w}" for w, n in top)})
    if sendable and room <= 0:
        notes.append(f"{sendable} would go, but today's cap of "
                     f"{cfg.get('daily_cap', 25)} is used up.")

    return {"ok": not blockers,
            "settling_in": st,
            "will_send": (0 if blockers else min(sendable, room)),
            "sendable": sendable, "room_today": room,
            "blockers": blockers, "notes": notes,
            "by_reason": reasons,
            "summary": ("Ready — the next run would send "
                        f"{min(sendable, room)} application(s)." if not blockers
                        else f"{len(blockers)} thing(s) stop anything being sent.")}


# One run at a time. Two at once — the daily schedule firing while you press
# Run, or a run started twice from two windows — could each pick the same role
# and send it twice.
_RUN_LOCK = threading.Lock()
# Consecutive failures with the same cause before a run stops asking the
# engine. With no credit, or Ollama stopped, every role failed in turn, each
# waiting out its own timeout, and the run took an age to say one thing.
ENGINE_TRIP = 3

_BG: dict = {"state": "idle", "kind": "", "started": "", "finished": "",
             "progress": {}, "result": None, "error": ""}
_BG_LOCK = threading.Lock()


def _note(phase: str, done: int = 0, total: int = 0, title: str = "") -> None:
    _BG["progress"] = {"phase": phase, "done": done, "total": total,
                       "title": str(title or "")[:120]}


def auto_apply(brain, model=None, limit: int | None = None) -> dict:
    """Score, draft and SEND applications that clear every gate. Anything
    that doesn't clear a gate is held for you with the reason — that's the
    'only involve me where I'm needed' part."""
    cfg = auto_config()
    if not cfg.get("enabled"):
        return {"ok": False, "error": "auto-apply is off. Turn it on in the "
                                      "Jobs panel."}
    ok, why = profile_ready()
    if not ok:
        return {"ok": False, "error": why}
    if not _RUN_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "An auto-apply run is already going. "
                                      "Wait for it to finish, then run again."}
    try:
        res = _auto_apply(brain, model, limit, cfg)
    finally:
        _RUN_LOCK.release()
    if not _IN_CYCLE.get("on"):
        try:
            _record_run(res, "apply")
        except Exception:
            pass
    return res


_IN_CYCLE: dict = {}


def _fit_of(r: dict) -> int:
    s = (r.get("fit") or {}).get("score")
    return int(s) if isinstance(s, (int, float)) else -1


# How many engine calls a run may have going at once. A local model serves
# them one after another anyway; a cloud engine answers them side by side.
ENGINE_WORKERS_MAX = 8


def _claims_instructions(check: dict) -> str:
    """The claims the check couldn't source, as a redraft instruction."""
    probs = [p.get("detail", "") for p in (check or {}).get("problems") or [] if p.get("detail")]
    if not probs:
        return ""
    return ("\nYOUR LAST DRAFT FOR THIS ROLE SAID THINGS THE PROFILE CAN'T SUPPORT. "
            "Write it again without them: drop each of these words or claims "
            "entirely (don't rephrase them into something similar), and add "
            "nothing in their place that the PROFILE or CV_EXCERPTS don't show:\n- "
            + "\n- ".join(probs[:12]))


def _repair_draft(key: str, draft: dict, brain, model, cfg: dict) -> dict:
    """One redraft for a draft that would otherwise be held: told exactly
    which claims couldn't be sourced and what read weak.

    Unattended, a single unexplained capital ("European", a product the
    engine guessed at) held the application for you, and at volume that was
    most of them: the run drafted everything and sent nothing. The check
    itself is unchanged and reads the new draft as strictly as the first;
    if the second is no better, the first is kept, and held as before."""
    from . import quality as _q
    chk = draft.get("check") or {}
    q = draft.get("quality") or {}
    bad_claims = cfg.get("require_clean_check", True) and chk.get("ok") is False
    weak = bool(q) and q.get("score", 100) < int(cfg.get("min_quality", 60) or 0)
    if not (bad_claims or weak):
        return draft
    fix = (_claims_instructions(chk) if bad_claims else "") + (_q.instructions(q) if weak else "")
    d2 = draft_application(key, brain, model=model, fix=fix)
    if not d2.get("ok"):
        update_role(key, draft=draft, stage="drafted")
        return draft
    new = d2.get("draft") or {}
    n_old = len(chk.get("problems") or [])
    n_new = len((new.get("check") or {}).get("problems") or [])
    q_old, q_new = q.get("score", 100), (new.get("quality") or {}).get("score", 100)
    # fewer unsourced claims wins; on a tie, the better-written one
    keep_new = (n_new, -q_new) <= (n_old, -q_old)
    fields = {}
    if weak:
        fields["redrafted_for_quality"] = {"before": q_old, "after": q_new}
    if bad_claims:
        fields["redrafted_for_claims"] = {"before": n_old, "after": n_new}
    if not keep_new:
        fields["draft"] = draft
    update_role(key, **fields)
    return new if keep_new else draft


def _auto_apply(brain, model, limit, cfg) -> dict:
    from . import outreach
    _undo_rehearsal_stages()
    dry = bool(cfg.get("dry_run", True))
    floor = int(cfg["min_score"])
    mode = str(cfg.get("portal_mode", "prepare")).lower()
    sent, held, errors, prepared = [], [], [], []
    cap = int(cfg.get("daily_cap", 25))
    portal_room = max(0, int(cfg.get("portal_per_run", 15) or 0))
    settle = settling_in(cfg)
    if settle["on"]:
        cap, portal_room = min(cap, SETTLE_CAP), min(portal_room, SETTLE_CAP)
    room = max(0, cap - _sent_today())
    todo = [r for r in roles() if r.get("stage") in ("found", "drafted")]
    if limit:
        todo = todo[:limit]

    # --- 1. bring every role up to date: score it, draft the good ones ------
    # Several roles at once. One engine call at a time meant a run of 150
    # roles, at ten seconds a call, took most of an hour before the first
    # application went anywhere. Each role is still done in order (score,
    # then draft, then one repair if needed); only different roles overlap.
    failed, skipped = set(), 0
    trip = {"down": "", "last": "", "streak": 0}
    trip_lock = threading.Lock()
    done_n = [0]

    def _engine_failed(r, err):
        why = _explain_engine_error(err)
        with trip_lock:
            errors.append(f"{r['title']}: {why}")
            failed.add(r["key"])
            trip["streak"] = trip["streak"] + 1 if why == trip["last"] else 1
            trip["last"] = why
            if trip["streak"] >= ENGINE_TRIP:
                trip["down"] = why

    def _engine_ok():
        with trip_lock:
            trip["streak"] = 0
            trip["answered"] = True

    def _bring_up_to_date(r):
        nonlocal skipped
        key = r["key"]
        needs_score = (r.get("fit") or {}).get("score") is None
        needs_draft = (not needs_score and _fit_of(r) >= floor
                       and not (r.get("draft") or {}).get("body"))
        if trip["down"]:
            if needs_score or needs_draft:
                with trip_lock:
                    skipped += 1
                    failed.add(key)
            return
        with trip_lock:
            done_n[0] += 1
            _note("Scoring and drafting", done_n[0], len(todo), r.get("title", ""))
        try:
            if needs_score:
                s = score_role(key, brain, model=model)
                if not s.get("ok"):
                    _engine_failed(r, s["error"])
                    return
                _engine_ok()
                r = get_role(key) or r
            if _fit_of(r) >= floor and not (r.get("draft") or {}).get("body"):
                d = draft_application(key, brain, model=model)
                if not d.get("ok"):
                    _engine_failed(r, d["error"])
                    return
                _engine_ok()
                fin = _repair_draft(key, d.get("draft") or {}, brain, model, cfg)
                # a CV made for this advert, once the letter is one that can go
                if cfg.get("tailor_cv", True) and (fin.get("check") or {}).get("ok", True):
                    try:
                        _tailor_for(key, brain, model)
                    except Exception as exc:
                        with trip_lock:
                            errors.append(f"{r.get('title', '?')}: tailoring the CV: "
                                          f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            with trip_lock:
                failed.add(key)
                errors.append(f"{r.get('title', '?')}: {type(exc).__name__}: {exc}")

    workers = max(1, min(ENGINE_WORKERS_MAX, int(cfg.get("engine_workers", 4) or 1)))
    # one at a time until the engine has answered once: a dead engine (no
    # credit, Ollama stopped) is then asked ENGINE_TRIP times, not once per
    # role already in flight when the third failure came back
    rest = list(todo)
    while rest and (workers == 1 or not trip.get("answered")) and not trip["down"]:
        _bring_up_to_date(rest.pop(0))
    if rest:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="jobs-engine") as pool:
            list(pool.map(_bring_up_to_date, rest))
    engine_down = trip["down"]
    if skipped:
        errors.append(f"{skipped} more role(s) left for the next run: "
                      f"{engine_down}")

    # --- 2. deliver, best fit first, so the day's cap goes to the strongest --
    ready = [get_role(r["key"]) for r in todo if r["key"] not in failed]
    if not cfg.get("deliver", True):
        # "Draft only": everything is scored and drafted for you to review;
        # nothing is sent, rehearsed or opened
        for r in ready:
            if r and r.get("stage") in ("found", "drafted") and _fit_of(r) >= floor \
                    and (r.get("draft") or {}).get("body"):
                held.append({"key": r["key"], "title": r["title"],
                             "company": r.get("company", ""),
                             "reason": "drafted for you to review (Draft only)"})
        ready = []
    ready = [r for r in ready if r and r.get("stage") in ("found", "drafted")]
    # best fit first; among roles of about the same fit, the freshest — an
    # application in the first days is read, one in week three often isn't
    ready.sort(key=lambda r: (-(_fit_of(r) // 5), days_listed(r)))
    for i, r in enumerate(ready, 1):
        key = r["key"]
        _note("Applying", i, len(ready), r.get("title", ""))
        row = {"key": key, "title": r["title"], "company": r.get("company", "")}
        try:
            reason = _gate(r, cfg)
            portal_ok = (reason.startswith(_NO_EMAIL) and mode != "off"
                         and str(r.get("url") or "").strip())
            if reason and not portal_ok:
                held.append({**row, "reason": reason})
                continue
            if portal_ok:
                # most adverts have no address: the form is opened and filled,
                # the engine answers what it can, and you finish it. Submitting
                # by itself stays off unless asked — and never in rehearsal.
                wait = _portal_wait(r)
                submit = mode == "submit" and not dry
                if not wait and portal_room <= 0:
                    wait = (f"this run's limit of {cfg.get('portal_per_run', 15)} "
                            f"portal form(s) was reached — it is next in line")
                if not wait and submit and room <= 0:
                    wait = f"daily cap of {cap} reached — queued for tomorrow"
                if wait:
                    held.append({**row, "reason": wait})
                    continue
                from . import portal as _portal
                prof = profile()
                if r.get("tailored_cv") and cfg.get("attach_cv", True):
                    cvf = cv_file_for(r, prof)
                    if cvf["kind"] == "tailored":
                        prof = {**prof, "cv_path": cvf["path"]}
                try:
                    res = _portal.apply_to_portal(r, prof, submit=submit,
                                                  brain=brain, model=model)
                except Exception as exc:
                    res = {"state": "failed",
                           "message": f"{type(exc).__name__}: {exc}"}
                portal_room -= 1
                state = res.get("state", "")
                update_role(key, portal=_portal_brief(res), portal_at=_iso(),
                            portal_attempts=(int(r.get("portal_attempts") or 0)
                                             + 1 if state == "failed" else 0))
                if state == "closed":
                    # the advert said so: closed with the reason, never retried.
                    # Nothing was left open for you, so it doesn't use up the
                    # run's room for forms
                    portal_room += 1
                    mark_closed(key, str(res.get("message") or "the advert says it's closed")[:200])
                    held.append({**row, "reason": "the advert says the role is closed — moved to closed"})
                    continue
                if state == "apply_by_email" and res.get("apply_email"):
                    # no form, an address: the next run applies by email, through
                    # every check an emailed application passes
                    portal_room += 1
                    update_role(key, apply_email=res["apply_email"], portal_at="")
                    held.append({**row, "reason": f"the advert asks for email to {res['apply_email']} "
                                                  f"— the next run sends it that way"})
                    continue
                if state == "submitted":
                    room -= 1
                    update_role(key, sent_at=_iso(), sent_dry_run=False)
                    set_stage(key, "applied", "submitted via portal")
                    sent.append({**row, "to": "portal", "dry_run": False,
                                 "learned": (res.get("learned") or [])[:4]})
                elif state == "failed":
                    errors.append(f"{r['title']}: portal: "
                                  + str(res.get("message") or "the form failed"))
                else:
                    answers = res.get("answers") or []
                    needs = [a["question"] for a in answers if a.get("source") != "engine"]
                    needs += [x for x in (res.get("left") or []) if x not in needs]
                    prepared.append({
                        **row, "state": state, "url": r.get("url", ""),
                        "answered": len([a for a in answers
                                         if a.get("source") == "engine"]),
                        "needs_you": needs[:12],
                        "learned": (res.get("learned") or [])[:4],
                        "engine_turns": res.get("engine_turns"),
                        "message": res.get("message", ""),
                        "rehearsal": dry and mode == "submit"})
                continue
            if room <= 0:
                held.append({**row, "reason": f"daily cap of {cap} reached — "
                                              f"queued for tomorrow"})
                continue
            d = r["draft"]
            subject = (_as_text(d.get("subject")).strip()
                       or f"Application: {r['title']}")
            body = d["body"] + ("\n\n" + cfg["signature"]
                                if cfg.get("signature") else "")
            files, cv_kind = [], ""
            if cfg.get("attach_cv", True) and not dry:
                cvf = cv_file_for(r)
                if cvf["path"]:
                    files, cv_kind = [cvf["path"]], cvf["kind"]
                else:
                    errors.append(f"{r['title']}: sent without a CV — {cvf['error']}")
            res = outreach.send(r["apply_email"], subject, body, dry_run=dry,
                                **({"attachments": files} if files else {}))
            if res.get("ok"):
                room -= 1
                if dry:
                    # rehearsed, not applied: the role stays where it is, so
                    # it really goes once rehearsal is off
                    update_role(key, rehearsed_at=_iso())
                else:
                    update_role(key, sent_at=_iso(), sent_dry_run=False)
                    set_stage(key, "applied", "auto-applied")
                sent.append({**row, "to": r["apply_email"], "dry_run": dry,
                             **({"cv": cv_kind} if cv_kind else {})})
            else:
                errors.append(f"{r['title']}: {res.get('error', 'send failed')}")
        except Exception as exc:
            errors.append(f"{r.get('title', '?')}: {type(exc).__name__}: {exc}")

    # twelve roles failing with the same message is one fault, not twelve
    common = engine_down
    if not common and errors and len(errors) >= 3:
        tails = [e.split(": ", 1)[-1] for e in errors]
        if len(set(tails)) == 1:
            common = tails[0]
    groups: dict = {}
    for e in errors:
        tail = e.split(": ", 1)[-1]
        groups[tail] = groups.get(tail, 0) + 1
    _note("Finished", len(ready), len(ready))
    _audit("auto-apply",
           f"{len(sent)} sent{' (rehearsal)' if dry else ''}, "
           f"{len(prepared)} prepared, {len(held)} held, {len(errors)} error(s)")
    return {"ok": True, "sent": sent, "held": held, "errors": errors,
            "prepared": prepared, "common_error": common,
            "error_groups": groups,
            "engine_stopped": bool(engine_down),
            "dry_run": dry, "remaining_today": room}


PREP_PER_RUN = 2


def prepare_interviews(brain, model=None, limit: int = PREP_PER_RUN) -> list:
    """Interview prep for every role at the interview stage that has none yet.

    Uses your CV and profile only; questions with nothing to draw on come back
    as gaps, never invented answers (agent/cv.py). A couple per run, so one
    good week doesn't spend the engine budget at once."""
    from . import cv as cvmod
    done = []
    for r in roles():
        if len(done) >= limit:
            break
        if r.get("stage") != "interview" or (r.get("interview") or {}).get("questions"):
            continue
        _note("Preparing for an interview", title=r.get("title", ""))
        res = cvmod.interview_prep(r, profile(), brain, model=model)
        if res.get("ok"):
            update_role(r["key"], interview=res)
            done.append({"key": r["key"], "title": r.get("title", ""),
                         "company": r.get("company", ""),
                         "questions": len(res.get("questions") or []),
                         "gaps": len(res.get("gaps") or [])})
    return done


def describe_run(r: dict) -> str:
    """One line saying what a run did, for the window and the log."""
    if not r.get("ok", True) and r.get("error"):
        return str(r["error"])
    bits = []
    if r.get("discovered") is not None:
        bits.append(f"{r.get('discovered') or 0} new role(s) found")
    if r.get("scams_skipped"):
        bits.append(f"{r['scams_skipped']} advert(s) that look like scams set aside")
    if r.get("not_eligible"):
        bits.append(f"{r['not_eligible']} skipped because the advert rules you out "
                    f"(where you must live, or no visa sponsorship)")
    if r.get("ghosts_skipped"):
        bits.append(f"{r['ghosts_skipped']} likely ghost job(s) skipped")
    if r.get("replies"):
        bits.append(f"{r['replies']} repl(y/ies) to your applications read")
    if r.get("adverts_read"):
        bits.append(f"{r['adverts_read']} advert(s) read in full"
                    + (f", {r['emails_found_in_adverts']} with an application address"
                       if r.get("emails_found_in_adverts") else ""))
    if r.get("followed_up"):
        bits.append(f"{r['followed_up']} follow-up(s) sent")
    elif r.get("follow_ups_drafted"):
        bits.append(f"{r['follow_ups_drafted']} follow-up(s) drafted for you")
    if r.get("interview_prep"):
        bits.append(f"interview prep ready for {len(r['interview_prep'])} role(s)")
    if r.get("digest"):
        bits.append(f"weekly digest sent to {r['digest']}")
    n_sent = len(r.get("sent") or [])
    bits.append(f"{n_sent} sent" + (" (rehearsal — nothing left this machine)"
                                    if r.get("dry_run") and n_sent else ""))
    if r.get("prepared"):
        bits.append(f"{len(r['prepared'])} portal form(s) filled for you to "
                    f"finish")
    if r.get("held"):
        bits.append(f"{len(r['held'])} held for you")
    if r.get("errors"):
        bits.append(f"{len(r['errors'])} error(s)")
    if r.get("engine_stopped"):
        bits.append("stopped asking the engine: " + str(r.get("common_error")))
    if r.get("error"):
        bits.append(str(r["error"]))
    return "; ".join(bits)


def run_status() -> dict:
    with _BG_LOCK:
        return json.loads(json.dumps(_BG, default=str))


def start_run(kind: str, brain, model=None, finish=None) -> dict:
    """Run auto-apply ("apply") or the whole cycle ("cycle") in the
    background, and return at once; run_status() follows it.

    A run scores, drafts and opens forms — minutes of work — and it was one
    request the window waited on. The window gave up first and reported an
    error while the run carried on, which is exactly "hit and miss"."""
    with _BG_LOCK:
        if _BG["state"] == "running":
            return {"ok": False, "already": True,
                    "error": "A run is already going.",
                    **json.loads(json.dumps(_BG, default=str))}
        _BG.update(state="running", kind=kind, started=_iso(), finished="",
                   result=None, error="",
                   progress={"phase": "Starting", "done": 0, "total": 0,
                             "title": ""})

    def _go():
        try:
            res = (auto_cycle(brain, model=model) if kind == "cycle"
                   else auto_apply(brain, model=model))
            res["summary"] = res.get("summary") or describe_run(res)
            if finish is not None:
                res = finish(res) or res
            with _BG_LOCK:
                _BG.update(state="done", result=res, finished=_iso())
        except Exception as exc:
            with _BG_LOCK:
                _BG.update(state="failed", finished=_iso(),
                           error=f"{type(exc).__name__}: {exc}")

    threading.Thread(target=_go, daemon=True, name=f"jobs-{kind}").start()
    return {"ok": True, **run_status()}


# --------------------------------------------------------------------------- #
#  weekly autopilot (opt-in)
# --------------------------------------------------------------------------- #
def _cfg_path() -> Path:
    return _dir() / "config.json"


def load_config() -> dict:
    try:
        return json.loads(_cfg_path().read_text("utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    _cfg_path().write_text(json.dumps(cfg), "utf-8")


# How often the cycle may run: once a day at 07:00, or every N hours. A run
# every few hours catches roles in their first hours, when an application is
# most likely to be read; the day's cap is shared by all of a day's runs.
EVERY_HOURS = (0, 2, 3, 4, 6, 8, 12)
_SCHED_NAME = "Job scout"
_SCHED_PROMPT = (
    # This said "Do not send anything", which was never what the scheduled
    # run does — it calls auto_cycle, and whether anything is sent depends on
    # your auto-apply settings. A description that contradicts the behaviour
    # is worse than none.
    "Search for new roles matching my profile, score each honestly, "
    "and draft applications for strong fits. Send only those that "
    "clear every auto-apply gate — and nothing at all while rehearsal "
    "is on.")


def _job_schedules(memory) -> list:
    try:
        return [s for s in memory.list_schedules()
                if (s.get("action") or "") == "jobscout"]
    except Exception:
        return []


def _our_schedule(memory) -> dict | None:
    """The cycle's schedule: the one recorded in config, else any jobscout
    schedule there is (the autopilot button made its own and never recorded
    it, so the Daily switch read off while one existed)."""
    sid = load_config().get("schedule_id")
    if sid:
        try:
            s = memory.get_schedule(int(sid))
            if s is not None:
                return s
        except Exception:
            pass
    js = _job_schedules(memory)
    return js[0] if js else None


def schedule_every_hours() -> int:
    try:
        n = int(load_config().get("every_hours") or 0)
    except Exception:
        n = 0
    return n if n in EVERY_HOURS else 0


def _spec_for(scheduler, every_hours: int) -> str:
    if every_hours:
        return scheduler.make_spec("minutes", n=every_hours * 60)
    return scheduler.make_spec("daily", time_str="07:00")


def schedule_enabled(memory) -> bool:
    s = _our_schedule(memory)
    return bool(s and s.get("enabled") and s.get("next_run") is not None)


def schedule_info(memory) -> dict:
    s = _our_schedule(memory)
    n = schedule_every_hours()
    return {"on": schedule_enabled(memory), "every_hours": n,
            "says": (f"every {n} hours" if n else "daily at 07:00"),
            "next_run": (s or {}).get("next_run"),
            "last_run": (s or {}).get("last_run"),
            "last_status": (s or {}).get("last_status") or "",
            "last_summary": (s or {}).get("last_summary") or ""}


def set_schedule(memory, scheduler, enabled: bool,
                 every_hours: int | None = None) -> bool:
    """Turn the scheduled cycle on or off, and set how often it runs.

    There was one schedule-maker here and a second, in the autopilot button,
    that wrote a schedule with no time and no next run: it was never due, so
    "Set up the daily loop" set up nothing, and pressing it again cleared the
    next run of a schedule that did work. Both go through here now, and an
    existing schedule is adopted and repaired rather than duplicated."""
    cfg = load_config()
    if every_hours is not None:
        every_hours = int(every_hours)
        if every_hours not in EVERY_HOURS:
            raise ValueError(f"every_hours must be one of {EVERY_HOURS}")
        cfg["every_hours"] = every_hours
        save_config(cfg)
    n = schedule_every_hours()
    mine = _our_schedule(memory)
    if enabled:
        spec = _spec_for(scheduler, n)
        if every_hours is not None or not mine or not mine.get("enabled") \
                or mine.get("next_run") is None or mine.get("spec") != spec:
            # a run every N hours starts within a few minutes of being
            # switched on, not N hours later
            nxt = (time.time() + 120 if n
                   else scheduler.next_run(scheduler.parse_spec(spec)))
        else:
            nxt = mine["next_run"]
        if mine:
            memory.update_schedule(
                mine["id"], name=_SCHED_NAME + (f" — every {n} hours" if n else " — daily"),
                prompt=_SCHED_PROMPT, spec_json=spec, next_run=nxt)
            sid = mine["id"]
        else:
            sid = memory.create_schedule(
                _SCHED_NAME + (f" — every {n} hours" if n else " — daily"),
                _SCHED_PROMPT, spec, "Auto", False, nxt,
                action="jobscout", payload="{}")
        # one cycle schedule; a second would run the cycle twice
        for s in _job_schedules(memory):
            if s["id"] != sid:
                try:
                    memory.delete_schedule(int(s["id"]))
                except Exception:
                    pass
        cfg = load_config()
        save_config({**cfg, "schedule_id": sid})
        _audit("schedule", f"on, {'every %d hours' % n if n else 'daily at 07:00'}")
        return schedule_enabled(memory)
    for s in _job_schedules(memory):
        try:
            memory.delete_schedule(int(s["id"]))
        except Exception:
            pass
    cfg = load_config()
    cfg.pop("schedule_id", None)
    save_config(cfg)
    return schedule_enabled(memory)


def repair_schedule(memory, scheduler) -> bool:
    """At start: an enabled cycle schedule that can never come due (no next
    run, or the autopilot's empty spec) is given its proper spec and time.
    True when one was repaired."""
    s = _our_schedule(memory)
    if not s or not s.get("enabled"):
        return False
    try:
        scheduler.parse_spec(s.get("spec") or "{}")
        ok_spec = True
    except Exception:
        ok_spec = False
    if ok_spec and s.get("next_run") is not None:
        return False
    set_schedule(memory, scheduler, True)
    return True


def _audit(name: str, summary_text: str) -> None:
    try:
        from . import audit
        audit.record("jobscout", name=name, summary=summary_text[:250])
    except Exception:
        pass


# =========================================================================== #
#  Sourcing — where the roles come from
#
#  Everything else here was already automatic: scoring, drafting, the
#  fabrication check, the gates, the send. What wasn't is SUPPLY. Roles had to
#  be handed to it, so "apply to many without intervention" was impossible for
#  a reason that had nothing to do with the applying.
#
#  These are boards that publish their listings openly for exactly this
#  purpose. Nothing is scraped from behind a login, and nothing here touches
#  LinkedIn: automating Easy Apply breaks their terms and gets accounts
#  restricted, which is a bad trade for a contractor whose profile is a
#  business asset.
# =========================================================================== #
# No default boards. Which sites are worth watching is a personal decision —
# the ones that suit a Johannesburg contractor are not the ones that suit a
# graduate in Berlin, and shipping three defaults quietly framed the feature
# as "these three, plus whatever you add". You add what you use.
JOB_SOURCES = []

# Offered as a starting point in the UI, added only if the user picks them.
SUGGESTED_SOURCES = [
    {"name": "Remotive", "kind": "remotive",
     "url": "https://remotive.com/api/remote-jobs?limit=80",
     "about": "Remote roles, worldwide"},
    {"name": "RemoteOK", "kind": "remoteok", "url": "https://remoteok.com/api",
     "about": "Remote roles, worldwide"},
    {"name": "We Work Remotely", "kind": "rss",
     "url": "https://weworkremotely.com/categories/"
            "remote-programming-jobs.rss",
     "about": "Remote programming roles"},
    {"name": "Careers24 (IT)", "kind": "html",
     "url": "https://www.careers24.com/jobs/kw-information-technology/",
     "about": "South African IT roles"},
    {"name": "CareerJunction (IT)", "kind": "html",
     "url": "https://www.careerjunction.co.za/jobs/it",
     "about": "South African IT roles"},
    {"name": "PNet (IT)", "kind": "html",
     "url": "https://www.pnet.co.za/jobs/information-technology",
     "about": "South African IT roles"},
]

JOB_FETCHER = None          # tests replace this


def job_sources() -> list:
    """Whatever the user has added. Empty until they add something."""
    try:
        data = json.loads((_dir() / "sources.json").read_text("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_job_sources(items: list) -> list:
    (_dir() / "sources.json").write_text(json.dumps(items, indent=2), "utf-8")
    return items


BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "application/json;q=0.8,*/*;q=0.7"),
    "Accept-Language": "en-ZA,en-GB;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


_LAST_HIT = {}
POLITE_GAP = 2.5          # seconds between requests to the same host


def _pace(url: str) -> None:
    """One request at a time per host, with a gap.

    This is not evasion — it is the difference between a reader and a load
    generator. Most "blocks" are rate limits, so pacing genuinely reduces
    them, and a site that has asked you to slow down has said something worth
    honouring."""
    try:
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url or "")
        now = time.time()
        last = _LAST_HIT.get(host, 0)
        wait = POLITE_GAP - (now - last)
        if wait > 0:
            time.sleep(min(wait, POLITE_GAP))
        _LAST_HIT[host] = time.time()
    except Exception:
        pass


def _fetch_source(url: str) -> str:
    """Fetch a page the way a browser would.

    The plain client announced itself as a script, and Careers24, Toptal and
    Catalant all answered 403. A normal browser header set is not a trick —
    it is what any person visiting the page sends — and it fixes most of
    them. Sites that still refuse, or that build their list in JavaScript,
    need the real browser below."""
    if JOB_FETCHER is not None:
        return JOB_FETCHER(url)
    _pace(url)
    import httpx
    url = normalise_url(url)
    last = None
    for kwargs in ({"http2": False}, {"http2": False, "verify": False}):
        try:
            with httpx.Client(follow_redirects=True, timeout=25.0,
                              headers=BROWSER_HEADERS, **kwargs) as c:
                r = c.get(url)
                r.raise_for_status()
                # Trusting the declared charset produced "CanÃ³vanas" and
                # "St Johnâ€™s": these boards serve UTF-8 while some declare
                # latin-1. Decode as UTF-8 first and only fall back if that
                # genuinely fails.
                try:
                    return r.content.decode("utf-8")
                except UnicodeDecodeError:
                    return r.text
        except Exception as exc:
            last = exc
    raise last


_BATCH: dict = {}


def open_fetch_batch() -> None:
    """Use one browser for a whole pass over the sources."""
    from . import portal
    if _BATCH.get("driver") is None and portal.DRIVER is None:
        _BATCH["driver"] = portal.acquire_driver(headless=True)


def close_fetch_batch() -> None:
    from . import portal
    d = _BATCH.pop("driver", None)
    if d is not None:
        # returned, not closed: an application or a sign-in may still be in
        # the same browser, and closing its profile is what made Chromium
        # refuse the next launch
        portal.release_driver(close=False)


def fetch_with_browser(url: str) -> str:
    """Load the page in the real browser and take what it renders.

    Two things this solves that headers can't: a site that fingerprints
    non-browser clients, and a listing that only exists after JavaScript has
    run — which is most modern job boards, PNet and Careers24 included."""
    from . import portal
    url = normalise_url(url)
    # One browser for the whole run, not one per source. Each fetch used to
    # start and stop its own, which is what filled the screen with windows.
    driver, ours = portal.DRIVER, False
    if driver is None:
        driver = _BATCH.get("driver")
    if driver is None:
        driver = portal.acquire_driver(headless=True)
        ours = True
    page = None
    try:
        page = driver.open(url)
        # Wait for the listing a script draws — through the driver, so it
        # runs on the browser's own thread. Calling the page directly from
        # here raised "cannot switch to a different thread", which this
        # swallowed as a slow tracker: the wait never happened, and a source
        # whose roles arrive by script came back with none.
        settle = getattr(driver, "settle", None)
        if settle is not None:
            try:
                settle(page)
            except Exception:
                pass                   # a slow tracker shouldn't lose the page
        return driver.html(page)
    finally:
        try:
            driver.close_page(page)
        except Exception:
            pass
        if ours:
            portal.release_driver(close=False)


def _explain_fetch_error(err: str, url: str = "") -> str:
    e = " ".join(str(err or "").split())
    low = e.lower()
    # A proxy between you and the site said no (a work or school network, a
    # VPN, a locked-down server). That read as "the site blocks automated
    # readers" and sent people to the browser option, which goes through the
    # same proxy and fails the same way.
    if "proxyerror" in low or "tunnel" in low or "proxy" in low:
        return ("your network's proxy refused the connection — the site itself "
                "was never reached. On a work or school network, or behind a VPN, "
                "ask for the site to be allowed, or try from another network.")
    if "403" in low or "forbidden" in low:
        return ("blocks automated readers (403). Try 'Use browser' — it loads "
                "the page properly, which most of these accept.")
    if "429" in low:
        return "asked us to slow down (429). Try again in a few minutes."
    if "404" in low:
        return "that page isn't there any more (404) — check the address."
    if "disconnected" in low or "remoteprotocol" in low:
        return ("dropped the connection, usually a bot check. Try 'Use "
                "browser'.")
    if "missing an 'http" in low or "unsupportedprotocol" in low:
        return "the address had no https:// — it has been repaired, try again."
    if "timeout" in low or "timed out" in low:
        return "took too long to answer."
    if "name or service not known" in low or "getaddrinfo" in low:
        return "that domain doesn't resolve — check the spelling."
    return e[:160]


_EMAIL_IN_TEXT = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# addresses that exist on a page but are not where an application goes
_NOT_APPLY = ("noreply", "no-reply", "donotreply", "privacy@",
              "legal@", "abuse@", "sentry", "example.com", "@remoteok",
              "@remotive", "@weworkremotely", "@jobicy", "@himalayas", "@workingnomads",
              "@jobspresso", "@pnet.co.za", "@ycombinator")
# Mailboxes that are never for applications, whatever the sentence says…
_NEVER_LOCAL = re.compile(
    r"^(?:no-?reply|do-?not-?reply|donotreply|privacy|dpo|global-?dpo|gdpr|dataprotection|"
    r"legal|compliance|security|abuse|fraud|phishing|press|media|pr|billing|accounts?|sales|"
    r"unsubscribe|webmaster|postmaster|mailer-daemon|feedback|ethics|eeo|investors?|ir|"
    r".*accommodat\w*|.*accessib\w*|ada(?:request)?|.*disabilit\w*|benefits)$")
# …and ones that usually are
_APPLY_LOCAL = re.compile(
    r"^(?:jobs?|careers?|hiring|hire|hr|recruit\w*|talent\w*|apply|applications?|cvs?|resumes?|"
    r"work|join(?:us)?|people|vacanc\w+|opportunit\w+|humanresources|staffing)(?:[._+-]\w+)?$")
# the advert asking for an application at the address that follows
_APPLY_ASK = re.compile(
    r"\b(?:to apply\b|apply(?:ing)?\s*(?:by|via|at|to|through|:|–|—|-)|apply\s+(?:now\s+)?(?:by\s+)?(?:e-?mail(?:ing)?|"
    r"sending|writing)|applications?\s+(?:to|at|via|by e-?mail|should be (?:sent|e-?mailed))|"
    r"(?:send|e-?mail|forward|submit|drop|shoot)\s+(?:us\s+|me\s+|in\s+|over\s+|through\s+)?(?:your|a|an|the)\s+"
    r"(?:\w+\s+){0,3}?(?:cv|c\.v\.|résumé|resume|application|cover letter|portfolio|profile|details)|"
    r"(?:cv|c\.v\.|résumé|resume)s?\s+(?:and\s+\w+\s+(?:\w+\s+)?)?(?:to|at|via)\b|"
    r"interested\b\??[^.!?]{0,60}?\b(?:e-?mail|contact|write|reach out|get in touch|send)|"
    r"(?:e-?mail|write to|reach out to|get in touch with|contact)\s+(?:us|me)\s+(?:directly\s+)?(?:at|on|via)\b[^.!?]{0,30}?"
    r"\b(?:apply|application|cv|résumé|resume)|how to apply)", re.I)
# the sentence being about something else: an adjustment, a question, a report
_OTHER_ASK = re.compile(
    r"\b(?:accommodat\w+|disabilit\w+|accessib\w+|reasonable adjustments?|adjustments? to|medical condition|"
    r"assistance|privacy|data protection|personal data|your data|gdpr|exercise (?:these|your) rights|"
    r"automated decision\w*|affirmative action|equal opportunity|eeo|suspicious|fraud\w*|scam\w*|phishing|"
    r"legitimate|claiming to be|impersonat\w+|report(?:ed|ing)?\b|complaints?|grievance|concerns?|"
    r"questions?|quer(?:y|ies)|enquir(?:y|ies)|inquir(?:y|ies)|more information|additional information|"
    r"further information|support completing|technical (?:issues?|difficult\w+|problems?)|trouble\b|"
    r"alternative selection|unsubscribe|press|media)\b", re.I)
# "Email careers@…", "contact us at jobs@…": told to write, with nothing else said
_WRITE_TO = re.compile(
    r"(?:\be-?mail|\bcontact|\bwrite(?: to)?|\breach(?: out)?(?: to)?|\bget in touch(?: with)?|\bping|"
    r"\bsend (?:an? )?(?:e-?mail|note|message) to)\s*(?:us|me)?\s*(?:directly)?\s*(?:at|on|via)?\s*[:\-–—]?\s*$",
    re.I)


def _apply_email(text: str) -> str:
    """An address to apply to, or '' when it's a portal application.

    Being wrong here is expensive in both directions: a missed address means a
    role that could have been applied to automatically isn't, and a wrong one
    sends your application where it has no business.

    It took the first address in the advert that wasn't on a short blocklist.
    Against live adverts that was, again and again, the address in the small
    print: the mailbox for disability accommodations, the data-protection
    officer, where to report a fake recruiter, who to ask for the
    affirmative-action plan. Most of those are called careers@ or
    recruiting@, so the name of a mailbox proves nothing by itself.

    An address is believed only when the advert asks for applications at it:
      * its own sentence says so ("Apply: …", "send your CV to …",
        "interested? reach out to …") and is not about something else; or
      * the advert simply says to write to a mailbox that exists for
        applications ("Email careers@…"), with no talk of accommodations,
        questions or reports anywhere near it."""
    text = str(text or "")
    best, best_score = "", 0
    for m in _EMAIL_IN_TEXT.finditer(text):
        addr = m.group(0).lower().rstrip(".-")
        if any(bad in addr for bad in _NOT_APPLY):
            continue
        local = addr.split("@", 1)[0]
        if _NEVER_LOCAL.match(local):
            continue
        before = text[max(0, m.start() - 260):m.start()]
        # the sentence the address is in, not the ones before it
        cut = max(before.rfind(". "), before.rfind("! "), before.rfind("? "), before.rfind(" • "))
        sentence = before[cut + 2:] if cut >= 0 else before
        after = re.split(r"[.!?]\s", text[m.end():m.end() + 60])[0]
        if _OTHER_ASK.search(sentence):
            continue                       # this sentence is about something else
        score = 0
        if _APPLY_ASK.search(sentence) or _APPLY_ASK.search(before[-70:]):
            score = 4
        elif _APPLY_ASK.search(after) and not _OTHER_ASK.search(before):
            score = 3                      # "jobs@acme.io — apply by email"
        elif _WRITE_TO.search(sentence) and _APPLY_LOCAL.match(local) \
                and not _OTHER_ASK.search(before):
            score = 2
        if score and _APPLY_LOCAL.match(local):
            score += 1
        if score > best_score:
            best, best_score = addr, score
    return best


def _strip_html(s: str) -> str:
    """Text of a piece of HTML: tags out, entities read (&amp;, &#8217;),
    and text a board decoded with the wrong alphabet put right. Adverts went
    into letters with "&amp;" and "donâ€™t" still in them."""
    import html as _html
    from . import geo
    t = s or ""
    if "mailto:" in t:
        # the address inside an "Apply here" link is the application address,
        # and it went out with the tag
        t = re.sub(r"""<a\b[^>]*href=["']mailto:([^"'?>\s]+)[^>]*>(.*?)</a>""",
                   lambda m: (m.group(2) if m.group(1).lower() in m.group(2).lower()
                              else f"{m.group(2)} {m.group(1)} "), t, flags=re.I | re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    if "&" in t:
        t = _html.unescape(t)
        if "<" in t and re.search(r"<[a-zA-Z/][^>]*>", t):   # markup that was escaped twice
            t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", geo.fix_text(t)).strip()


# Boards that list only remote work. A role from one is remote whatever its
# location field says; that field is where you may live.
_REMOTE_BOARDS = ("weworkremotely.com", "remoteok.com", "remotive.com", "jobicy.com",
                  "jobspresso.co", "workingnomads.com", "himalayas.app", "euremotejobs.com",
                  "remote.co", "nodesk.co", "dynamitejobs.com", "justremote.co", "4dayweek.io")


def _host(url: str) -> str:
    return re.sub(r"^https?://(www\.)?([^/:?#]+).*$", r"\2", str(url or "").strip().lower())


def _remote_board(url: str) -> bool:
    h = _host(url)
    return any(h == b or h.endswith("." + b) for b in _REMOTE_BOARDS)


def _money(lo, hi, cur="", per="") -> str:
    """"USD 90,000–120,000 per year" from a board's pay fields; '' without any."""
    def f(n):
        try:
            n = float(n)
        except Exception:
            return ""
        return f"{n:,.0f}" if n > 0 else ""
    a, b = f(lo), f(hi)
    span = f"{a}–{b}" if a and b and a != b else (a or b)
    if not span:
        return ""
    per = {"annual": "per year", "yearly": "per year", "year": "per year", "monthly": "per month",
           "month": "per month", "hourly": "per hour", "hour": "per hour", "weekly": "per week",
           "week": "per week", "daily": "per day", "day": "per day"}.get(str(per or "").lower(), "")
    return " ".join(x for x in (str(cur or "").upper(), span, per) if x)


def _clean_location(loc: str) -> str:
    """'Hobart, ' is what an empty country field looks like once joined."""
    return re.sub(r"[,\s]+$", "", str(loc or "").strip())


def _posted(v) -> str:
    """The advert's own posting date as YYYY-MM-DD, from whatever the board
    sends: ISO text, epoch seconds or milliseconds, an RSS date, or
    Workday's "Posted 3 Days Ago". '' when there is none.

    Every board sends one and every parser dropped it, so a role's age was
    the day this app first saw it — an advert up for three months looked
    brand new the day you added the board."""
    if v in (None, "", 0):
        return ""
    now = datetime.now(timezone.utc)
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
            n = float(v)
            n = n / 1000 if n > 1e11 else n
            return datetime.fromtimestamp(n, timezone.utc).strftime("%Y-%m-%d")
        t = str(v).strip()
        low = t.lower()
        if "today" in low or "just posted" in low:
            return now.strftime("%Y-%m-%d")
        if "yesterday" in low:
            return (now - timedelta(days=1)).strftime("%Y-%m-%d")
        m = re.search(r"(\d+)\+?\s*(day|week|month)s?\s+ago", low)
        if m:
            n = int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)]
            return (now - timedelta(days=n)).strftime("%Y-%m-%d")
        m = re.match(r"(\d{4}-\d{2}-\d{2})", t)
        if m:
            return m.group(1)
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(t).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _parse_remotive(text: str) -> list:
    out = []
    for j in (json.loads(text).get("jobs") or []):
        body = _strip_html(j.get("description", ""))
        out.append({"title": j.get("title", ""),
                    "company": j.get("company_name", ""),
                    "url": j.get("url", ""),
                    "location": _clean_location(j.get("candidate_required_location", "Remote")),
                    "summary": body[:600], "description": body[:ADVERT_CHARS],
                    "apply_email": _apply_email(body), "remote": True,
                    "salary": _as_text(j.get("salary"))[:60],
                    "posted_at": _posted(j.get("publication_date")),
                    "source": "Remotive"})
    return out


def _parse_remoteok(text: str) -> list:
    out = []
    data = json.loads(text)
    for j in (data if isinstance(data, list) else []):
        if not isinstance(j, dict) or not j.get("position"):
            continue                      # the first entry is a legal notice
        body = _strip_html(j.get("description", ""))
        out.append({"title": j.get("position", ""),
                    "company": j.get("company", ""),
                    "url": j.get("url", ""),
                    "location": _clean_location(j.get("location") or "Remote"),
                    "summary": body[:600], "description": body[:ADVERT_CHARS],
                    "apply_email": _apply_email(body), "remote": True,
                    "salary": _money(j.get("salary_min"), j.get("salary_max"), "USD", "year"),
                    "posted_at": _posted(j.get("date") or j.get("epoch")),
                    "source": "RemoteOK"})
    return out


def _xml_name(tag) -> tuple:
    """(namespace, local name) of an XML tag, both lower case."""
    t = str(tag)
    if t.startswith("{"):
        ns, _, name = t[1:].partition("}")
        return ns.lower(), name.lower()
    return "", t.lower()


def _parse_jobs_rss(text: str) -> list:
    """Any RSS or Atom feed of jobs.

    Job boards put the useful facts in tags of their own, and this read none
    of them: the company (job_listing:company), where a remote role is open
    to (We Work Remotely's <region>: "Anywhere in the World", "USA Only"),
    the whole advert (content:encoded), the pay, the closing date. Worse, a
    picture tag (media:content) that follows the description shares its name
    and wiped it. Against the live feeds that left Jobicy and Jobspresso with
    no company and no advert text, and every We Work Remotely role with the
    one word "Remote"."""
    from xml.etree import ElementTree as ET
    out = []
    try:
        root = ET.fromstring(text)
    except Exception:
        return out
    feed_remote = _remote_board(_CURRENT_SOURCE_URL.get("url") or "")
    for item in root.iter():
        if _xml_name(item.tag)[1] not in ("item", "entry"):
            continue
        f = {"title": "", "link": "", "body": "", "full": "", "company": "", "location": "",
             "region": "", "when": "", "closes": "", "salary": "", "lo": "", "hi": "",
             "cur": "", "per": ""}
        for c in item:
            ns, tag = _xml_name(c.tag)
            txt = (c.text or "").strip()
            if "mrss" in ns or "/media" in ns:
                continue                      # a picture, not the advert
            if tag == "title":
                f["title"] = f["title"] or txt
            elif tag == "link":
                f["link"] = f["link"] or (c.get("href") or txt).strip()
            elif tag == "encoded":
                f["full"] = _strip_html(txt)
            elif tag in ("description", "summary", "content"):
                if txt and not f["body"]:
                    f["body"] = _strip_html(txt)
            elif tag in ("pubdate", "published", "updated", "date"):
                f["when"] = f["when"] or _posted(txt)
            elif tag in ("expires_at", "expires", "expirationdate", "valid_through"):
                f["closes"] = _posted(txt)
            elif tag == "company":
                f["company"] = f["company"] or _strip_html(txt)
            elif tag == "region":
                f["region"] = f["region"] or _strip_html(txt)
            elif tag == "location":
                f["location"] = f["location"] or _strip_html(txt)
            elif tag == "salary":
                f["salary"] = _strip_html(txt)
            elif tag == "salary_min":
                f["lo"] = txt
            elif tag == "salary_max":
                f["hi"] = txt
            elif tag == "salary_currency":
                f["cur"] = txt
            elif tag == "salary_period":
                f["per"] = txt
        title = _strip_html(f["title"])
        if not title:
            continue
        company = f["company"]
        if not company and ":" in title:  # WWR uses "Company: Role"
            company, title = [p.strip() for p in title.split(":", 1)]
        body = f["full"] if len(f["full"]) > len(f["body"]) else f["body"]
        remote = feed_remote or _remote_board(f["link"])
        out.append({"title": title, "company": company, "url": f["link"],
                    # what the feed says about where; "Remote" when it says nothing
                    "location": _clean_location(f["region"] or f["location"]) or "Remote",
                    "remote": remote,
                    "summary": body[:600], "description": body[:ADVERT_CHARS],
                    "apply_email": _apply_email(body),
                    "posted_at": f["when"], "closes_at": f["closes"],
                    "salary": (f["salary"] or _money(f["lo"], f["hi"], f["cur"], f["per"]))[:60],
                    "source": "RSS"})
    return out


def _parse_html_kind(text: str) -> list:
    """A source of kind 'html': any ordinary careers page."""
    return _parse_html_listings(text, _CURRENT_SOURCE_URL.get("url", ""))


_CURRENT_SOURCE_URL = {"url": ""}

def _parse_browser_kind(text: str) -> list:
    """A page as the browser rendered it, using your own signed-in session.

    Most expert marketplaces — micro1, Outsized, Toptal — publish nothing
    machine-readable: the listings are drawn by JavaScript, often only after
    you sign in. Fetching the HTML gets a shell with no jobs in it, and an
    RSS parser handed that page returns an empty list without complaint,
    which is how a source sits on "pending" for ever. The same browser
    profile the portal applications use holds those sessions, so this sees
    what you would see.
    """
    return _parse_html_kind(text)


# --- company hiring systems ------------------------------------------------ #
# Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Workday,
# BambooHR, Personio and Teamtailor publish each company's open roles in a
# machine-readable form, for exactly this purpose: one documented address
# per company, nothing scraped, no login. A role you've tracked that links to
# one of them is a door to every role that company lists, and so is a
# company's careers page that embeds one (boards.find_boards) — which is
# where "find more sources" finds new ones once the fixed catalogue has been
# used up.
_ATS_ROLE_URL = (
    # a careers page's embed names the board by ?for=
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board(?:/js)?\?(?:[^\"'\s]*&)?for=([A-Za-z0-9_-]+)",
                              re.I)),
    ("greenhouse", re.compile(
        r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/"
        r"(?:embed/job_app\?for=)?([A-Za-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?:api/v\d/(?:widget/)?accounts/)?([A-Za-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"//(?!apply\.|www\.)([a-z0-9-]+)\.workable\.com", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I)),
    ("smartrecruiters", re.compile(r"api\.smartrecruiters\.com/v1/companies/([A-Za-z0-9_-]+)", re.I)),
    ("recruitee", re.compile(r"//([a-z0-9-]+)\.recruitee\.com", re.I)),
    ("bamboohr", re.compile(r"//([a-z0-9-]+)\.bamboohr\.com", re.I)),
    ("personio", re.compile(r"//([a-z0-9-]+)\.jobs\.personio\.(?:de|com)", re.I)),
    ("rss", re.compile(r"//([a-z0-9-]+)\.teamtailor\.com", re.I)),
)
_ATS_API = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{}",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{}/postings?limit=100",
    "recruitee": "https://{}.recruitee.com/api/offers/",
    "bamboohr": "https://{}.bamboohr.com/careers/list",
    "personio": "https://{}.jobs.personio.de/xml",
    "rss": "https://{}.teamtailor.com/jobs.rss",
}
_ATS_API_SLUG = {
    "greenhouse": re.compile(r"/boards/([^/?#]+)/jobs", re.I),
    "lever": re.compile(r"/postings/([^/?#]+)", re.I),
    "ashby": re.compile(r"/job-board/([^/?#]+)", re.I),
    "workable": re.compile(r"/accounts/([^/?#]+)", re.I),
    "smartrecruiters": re.compile(r"/companies/([^/?#]+)", re.I),
    "recruitee": re.compile(r"//([^./]+)\.recruitee\.com", re.I),
    "bamboohr": re.compile(r"//([^./]+)\.bamboohr\.com", re.I),
    "personio": re.compile(r"//([^./]+)\.jobs\.personio", re.I),
    "workday": re.compile(r"/wday/cxs/([^/?#]+)/", re.I),
}
_ATS_NOT_A_COMPANY = {"embed", "jobs", "job", "careers", "v1", "api", "j", "www", "apply", "app",
                      "static", "assets", "cdn", "help", "support", "en", "oneclick-ui"}
# Workday: https://<tenant>.wd<n>.myworkdayjobs.com/[<locale>/]<site>/job/...
_WORKDAY_URL = re.compile(r"//([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}(?:-[A-Za-z]{2})?/)?"
                          r"([A-Za-z0-9_-]+)", re.I)


def ats_board_for(url: str):
    """(kind, company slug, feed address) for a role or a careers page on a
    hiring system that publishes its roles; None for anything else."""
    u = str(url or "")
    m = _WORKDAY_URL.search(u)
    # the site's own name ("Careers", "External") is the board, not a word to skip
    if m and m.group(3).lower() not in {"wday", "job", "details", "login", "userhome"}:
        tenant, wd, site = m.group(1), m.group(2), m.group(3)
        return "workday", tenant, f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    for kind, rx in _ATS_ROLE_URL:
        m = rx.search(u)
        if m and m.group(1).lower() not in _ATS_NOT_A_COMPANY:
            slug = m.group(1)
            return kind, slug, _ATS_API[kind].format(slug)
    return None


def _ats_company(kind: str) -> str:
    rx = _ATS_API_SLUG.get(kind)
    m = rx.search(_CURRENT_SOURCE_URL.get("url") or "") if rx else None
    slug = m.group(1) if m else ""
    return " ".join(w.capitalize() for w in re.split(r"[-_.]+", slug) if w)


def _ats_job(kind, company, title, url, location, body, remote=False, posted="") -> dict:
    loc = _clean_location(location or ("Remote" if remote else ""))
    if remote and "remote" not in loc.lower():
        loc = (loc + " (remote)").strip()
    return {"title": title or "", "company": company, "url": url or "",
            "location": loc, "summary": body[:600], "description": body[:ADVERT_CHARS],
            "apply_email": _apply_email(body),
            "posted_at": _posted(posted),
            "source": f"{company} ({kind.capitalize()})"}


def _parse_greenhouse(text: str) -> list:
    import html as _html
    company = _ats_company("greenhouse")
    return [_ats_job("greenhouse", j.get("company_name") or company,
                     j.get("title"), j.get("absolute_url"),
                     (j.get("location") or {}).get("name", ""),
                     _strip_html(_html.unescape(j.get("content") or "")),
                     posted=j.get("first_published") or j.get("updated_at"))
            for j in (json.loads(text).get("jobs") or [])
            if isinstance(j, dict)]


def _parse_lever(text: str) -> list:
    data = json.loads(text)
    company = _ats_company("lever")
    return [_ats_job("lever", company, j.get("text"), j.get("hostedUrl"),
                     (j.get("categories") or {}).get("location", ""),
                     j.get("descriptionPlain")
                     or _strip_html(j.get("description") or ""),
                     remote=str(j.get("workplaceType", "")).lower() == "remote",
                     posted=j.get("createdAt"))
            for j in (data if isinstance(data, list) else [])
            if isinstance(j, dict)]


def _parse_ashby(text: str) -> list:
    company = _ats_company("ashby")
    return [_ats_job("ashby", company, j.get("title"),
                     j.get("jobUrl") or j.get("applyUrl"), j.get("location", ""),
                     j.get("descriptionPlain")
                     or _strip_html(j.get("descriptionHtml") or ""),
                     remote=bool(j.get("isRemote")), posted=j.get("publishedAt"))
            for j in (json.loads(text).get("jobs") or [])
            if isinstance(j, dict) and j.get("isListed", True)]


def _first(*vals) -> str:
    for v in vals:
        if v not in (None, "", [], {}):
            return str(v)
    return ""


def _parse_workable(text: str) -> list:
    data = json.loads(text)
    company = str(data.get("name") or "") or _ats_company("workable")
    out = []
    for j in data.get("jobs") or []:
        if not isinstance(j, dict):
            continue
        locs = j.get("locations") or []
        loc0 = locs[0] if locs and isinstance(locs[0], dict) else {}
        where = ", ".join(x for x in (_first(j.get("city"), loc0.get("city")),
                                      _first(j.get("country"), loc0.get("country"))) if x)
        out.append(_ats_job("workable", company, j.get("title"),
                            _first(j.get("url"), j.get("shortlink"), j.get("application_url")),
                            where, _strip_html(_first(j.get("description"), j.get("full_description"))),
                            remote=bool(j.get("telecommuting") or j.get("remote")),
                            posted=_first(j.get("published_on"), j.get("published"), j.get("created_at"))))
    return out


def _parse_smartrecruiters(text: str) -> list:
    data = json.loads(text)
    out = []
    for j in data.get("content") or []:
        if not isinstance(j, dict):
            continue
        comp = j.get("company") or {}
        ident = _first(comp.get("identifier"), _ats_company("smartrecruiters").replace(" ", ""))
        loc = j.get("location") or {}
        url = _first(j.get("postingUrl"), j.get("applyUrl"),
                     f"https://jobs.smartrecruiters.com/{ident}/{j.get('id', '')}" if j.get("id") else "")
        out.append(_ats_job("smartrecruiters", _first(comp.get("name"), ident), j.get("name"), url,
                            _first(loc.get("fullLocation"),
                                   ", ".join(x for x in (loc.get("city"), str(loc.get("country") or "").upper())
                                             if x)),
                            _strip_html(_first(j.get("jobAd"), "")), remote=bool(loc.get("remote")),
                            posted=j.get("releasedDate")))
    return out


def _parse_recruitee(text: str) -> list:
    data = json.loads(text)
    out = []
    for j in data.get("offers") or []:
        if not isinstance(j, dict):
            continue
        out.append(_ats_job("recruitee", _first(j.get("company_name"), _ats_company("recruitee")),
                            j.get("title"), _first(j.get("careers_url"), j.get("url")),
                            _first(j.get("location"), ", ".join(x for x in (j.get("city"), j.get("country")) if x)),
                            _strip_html(_first(j.get("description"), "") + " " + _first(j.get("requirements"), "")),
                            remote=bool(j.get("remote")),
                            posted=_first(j.get("published_at"), j.get("created_at"))))
    return out


def _parse_workday(text: str) -> list:
    data = json.loads(text)
    src = _CURRENT_SOURCE_URL.get("url") or ""
    m = re.search(r"https?://([^/]+)/wday/cxs/([^/]+)/([^/?#]+)", src)
    host, site = (m.group(1), m.group(3)) if m else ("", "")
    company = " ".join(w.capitalize() for w in re.split(r"[-_.]+", m.group(2)) if w) if m else ""
    out = []
    for j in data.get("jobPostings") or []:
        if not isinstance(j, dict) or not j.get("title"):
            continue
        path = str(j.get("externalPath") or "")
        url = f"https://{host}/{site}{path}" if host and path else ""
        out.append(_ats_job("workday", company, j.get("title"), url, _first(j.get("locationsText"), ""),
                            " ".join(str(x) for x in j.get("bulletFields") or []),
                            remote="remote" in str(j.get("locationsText") or "").lower(),
                            posted=j.get("postedOn")))
    return out


def _parse_bamboohr(text: str) -> list:
    data = json.loads(text)
    src = _CURRENT_SOURCE_URL.get("url") or ""
    m = re.search(r"https?://([^./]+)\.bamboohr\.com", src)
    sub = m.group(1) if m else ""
    company = _ats_company("bamboohr")
    out = []
    for j in data.get("result") or []:
        if not isinstance(j, dict):
            continue
        loc = j.get("location") or {}
        ats_loc = j.get("atsLocation") or {}
        where = ", ".join(x for x in (_first(loc.get("city"), ats_loc.get("city")),
                                      _first(ats_loc.get("country"), loc.get("state"))) if x)
        url = f"https://{sub}.bamboohr.com/careers/{j.get('id')}" if sub and j.get("id") else ""
        out.append(_ats_job("bamboohr", company, j.get("jobOpeningName"), url, where,
                            " ".join(x for x in (j.get("departmentLabel"), j.get("employmentStatusLabel")) if x),
                            remote=bool(j.get("isRemote")), posted=j.get("datePosted")))
    return out


def _parse_personio(text: str) -> list:
    from xml.etree import ElementTree as ET
    try:
        root = ET.fromstring(text)
    except Exception:
        return []
    src = _CURRENT_SOURCE_URL.get("url") or ""
    m = re.search(r"https?://([^/]+\.jobs\.personio\.(?:de|com))", src)
    host = m.group(1) if m else ""
    company = _ats_company("personio")
    out = []
    for pos in root.iter("position"):
        get = lambda tag: (pos.findtext(tag) or "").strip()
        body = " ".join((jd.findtext("value") or "") for jd in pos.iter("jobDescription"))
        url = f"https://{host}/job/{get('id')}" if host and get("id") else ""
        out.append(_ats_job("personio", _first(get("subcompany"), company), get("name"), url, get("office"),
                            _strip_html(body), remote="remote" in get("office").lower(),
                            posted=get("createdAt")))
    return out


def _parse_himalayas(text: str) -> list:
    """Himalayas' jobs API: remote roles, each with the countries it is open
    to (an empty list is worldwide), its pay and its closing date."""
    from . import geo
    out = []
    for j in (json.loads(text).get("jobs") or []):
        if not isinstance(j, dict) or not j.get("title"):
            continue
        body = _strip_html(j.get("description") or j.get("excerpt") or "")
        limits = [str(c) for c in (j.get("locationRestrictions") or []) if c]
        codes = sorted(set().union(*[geo.read_place(c)["countries"] for c in limits])) if limits else []
        where = ("Worldwide" if not limits else ", ".join(limits) if len(limits) <= 4
                 else f"Remote ({len(limits)} countries)")
        out.append({"title": _strip_html(j["title"]), "company": _strip_html(j.get("companyName") or ""),
                    "url": j.get("guid") or j.get("applicationLink") or "",
                    "location": where, "countries": codes or limits, "remote": True,
                    "summary": body[:600], "description": body[:ADVERT_CHARS],
                    "apply_email": _apply_email(body),
                    "posted_at": _posted(j.get("pubDate")), "closes_at": _posted(j.get("expiryDate")),
                    "salary": _money(j.get("minSalary"), j.get("maxSalary"), j.get("currency"),
                                     j.get("salaryPeriod")),
                    "source": "Himalayas"})
    return out


def _parse_workingnomads(text: str) -> list:
    data = json.loads(text)
    out = []
    for j in (data if isinstance(data, list) else []):
        if not isinstance(j, dict) or not j.get("title"):
            continue
        body = _strip_html(j.get("description") or "")
        out.append({"title": _strip_html(j["title"]), "company": _strip_html(j.get("company_name") or ""),
                    "url": j.get("url") or "",
                    "location": _clean_location(_strip_html(j.get("location") or "")) or "Remote",
                    "remote": True, "summary": body[:600], "description": body[:ADVERT_CHARS],
                    "apply_email": _apply_email(body), "posted_at": _posted(j.get("pub_date")),
                    "source": "Working Nomads"})
    return out


def _parse_jobicy(text: str) -> list:
    """Jobicy's API (v2): the company, the regions a role is open to and the
    whole advert, none of which its feed's first tags carry."""
    out = []
    for j in (json.loads(text).get("jobs") or []):
        if not isinstance(j, dict) or not j.get("jobTitle"):
            continue
        body = _strip_html(j.get("jobDescription") or j.get("jobExcerpt") or "")
        where = _clean_location(re.sub(r"\s{2,}", " ", _strip_html(str(j.get("jobGeo") or ""))))
        out.append({"title": _strip_html(j["jobTitle"]), "company": _strip_html(j.get("companyName") or ""),
                    "url": j.get("url") or "", "location": where or "Remote", "remote": True,
                    "summary": body[:600], "description": body[:ADVERT_CHARS],
                    "apply_email": _apply_email(body), "posted_at": _posted(j.get("pubDate")),
                    "salary": _money(j.get("annualSalaryMin") or j.get("salaryMin"),
                                     j.get("annualSalaryMax") or j.get("salaryMax"),
                                     j.get("salaryCurrency"), j.get("salaryPeriod") or "year"),
                    "source": "Jobicy"})
    return out


def _parse_arbeitnow(text: str) -> list:
    """Arbeitnow's job board API: roles in Germany and around Europe, each
    marked remote or not."""
    out = []
    for j in (json.loads(text).get("data") or []):
        if not isinstance(j, dict) or not j.get("title"):
            continue
        body = _strip_html(j.get("description") or "")
        out.append({"title": _strip_html(j["title"]), "company": _strip_html(j.get("company_name") or ""),
                    "url": j.get("url") or "",
                    "location": _clean_location(_strip_html(j.get("location") or "")),
                    "remote": bool(j.get("remote")), "country": "DE",
                    "summary": body[:600], "description": body[:ADVERT_CHARS],
                    "apply_email": _apply_email(body), "posted_at": _posted(j.get("created_at")),
                    "source": "Arbeitnow"})
    return out


_STEPSTONE_COUNTRY = {"pnet.co.za": "ZA", "stepstone.de": "DE", "stepstone.at": "AT",
                      "stepstone.be": "BE", "stepstone.nl": "NL", "stepstone.fr": "FR",
                      "totaljobs.com": "GB", "cwjobs.co.uk": "GB", "jobsite.co.uk": "GB",
                      "irishjobs.ie": "IE", "jobs.ie": "IE", "nijobs.com": "GB"}


def _parse_stepstone(text: str) -> list:
    """A results page on PNet, or any board on the same platform (StepStone,
    Totaljobs…): the page carries its results as data, with the company, the
    town, the posting date and the date the advert closes. Reading the
    links off the page instead produced its menu ("Johannesburg", "Cape
    Town") and none of that."""
    out = []
    i = (text or "").find('__PRELOADED_STATE__["app-unifiedResultlist"]')
    if i < 0:
        return out
    try:
        state, _ = json.JSONDecoder().raw_decode(text, text.index("{", i))
    except Exception:
        return out
    host = _host(_CURRENT_SOURCE_URL.get("url") or "")
    country = next((c for h, c in _STEPSTONE_COUNTRY.items() if host.endswith(h)), "")
    site = {"pnet.co.za": "PNet"}.get(host, host.split(".")[0].capitalize() if host else "StepStone")
    for j in ((state.get("searchResults") or {}).get("items") or []):
        if not isinstance(j, dict) or not j.get("title"):
            continue
        body = _strip_html(j.get("jobBenefitsHtml") or j.get("textSnippet") or "")
        out.append({"title": _strip_html(j["title"]), "company": _strip_html(j.get("companyName") or ""),
                    "url": j.get("url") or "",
                    "location": _clean_location(_strip_html(j.get("location") or "")),
                    "country": country, "remote": str(j.get("workFromHome")) == "2",
                    "summary": _strip_html(j.get("textSnippet") or body)[:600],
                    "description": body[:ADVERT_CHARS], "apply_email": _apply_email(body),
                    "posted_at": _posted(j.get("datePosted")),
                    "closes_at": _posted(j.get("publishToDate")),
                    "salary": _strip_html(_as_text(j.get("salary")))[:60],
                    "source": site})
    return out


_HN_ROLE = re.compile(
    r"\b(engineers?|developers?|programmers?|scientists?|designers?|architects?|analysts?|"
    r"researchers?|devops|sre|managers?|leads?|heads? of|directors?|specialists?|recruiters?|"
    r"marketers?|writers?|consultants?|administrators?|technicians?|interns?|"
    r"founding|full[- ]?stack|back[- ]?end|front[- ]?end)\b", re.I)
_HN_HEAD = re.compile(
    r"\b(engineers?|developers?|programmers?|scientists?|designers?|architects?|analysts?|"
    r"researchers?|managers?|leads?|directors?|specialists?|recruiters?|marketers?|writers?|"
    r"consultants?|administrators?|technicians?|interns?|devops|sre|mts|cto|heads? of \w+|"
    r"founding \w+|officers?|representatives?|executives?|strategists?|advocates?)\b", re.I)
_HN_NOT_ROLE = re.compile(
    r"https?://|@|\$\s?\d|€\s?\d|£\s?\d|\d+k\b|\b(remote|onsite|on-site|hybrid|full[- ]?time|"
    r"part[- ]?time|contract|equity|visa|salary|www\.)\b", re.I)
_HN_WHERE = re.compile(r"\b(remote|onsite|on-site|on site|hybrid|worldwide|anywhere|in[- ]person)\b", re.I)


def _hn_emails(text: str) -> str:
    """Addresses written to dodge harvesters: "jobs [at] acme [dot] com"."""
    t = re.sub(r"\s*(?:\[at\]|\(at\)|\{at\}|<at>)\s*", "@", text, flags=re.I)
    t = re.sub(r"\s*(?:\[dot\]|\(dot\)|\{dot\}|<dot>)\s*", ".", t, flags=re.I)
    return re.sub(r"\b([\w.+-]+) at ([\w-]+) dot (com|io|co|ai|org|net|dev|app)\b", r"\1@\2.\3", t, flags=re.I)


def _parse_hn(text: str) -> list:
    """Hacker News' monthly "Who is hiring?" thread. Each top-level comment is
    one company's post, by convention "Company | Roles | Where | …" on its
    first line. More than a third give an address to write to."""
    import html as _html
    from . import geo
    data = json.loads(text)
    story = str(data.get("story_id") or "")
    out = []
    for h in data.get("hits") or []:
        if story and str(h.get("parent_id")) != story:
            continue                      # a reply, not a post
        raw = h.get("comment_text") or ""
        paras = [_strip_html(x) for x in re.split(r"<p>|\n\n", raw) if _strip_html(x)]
        if not paras or "|" not in paras[0]:
            continue
        segs = [x.strip() for x in paras[0].split("|") if x.strip()]
        company = re.sub(r"\s*\(.*?\)\s*|https?://\S+", " ", segs[0]).strip(" -–:")[:80]
        if not company or len(company) > 60:
            continue
        titles = []

        def add(t):
            t = re.sub(r"\s+", " ", t).strip(" .-–:")
            if 4 <= len(t) <= 80 and t.lower() not in [x.lower() for x in titles]:
                titles.append(t)
        for seg in segs[1:]:
            if not _HN_HEAD.search(seg) or _HN_NOT_ROLE.search(seg) or len(seg) > 140:
                continue
            # "Data Engineer, ML Engineer" is two roles; "Founding MTS,
            # Full-Stack" is one. Split only where every piece is a role.
            parts = [x.strip() for x in re.split(r",|;|\band\b|&|\+", seg) if x.strip()]
            if len(parts) > 1 and all(_HN_HEAD.search(x) for x in parts):
                for x in parts:
                    add(x)
            else:
                add(seg)
        if not titles:
            # roles listed in the body, one to a line
            for line in paras[1:12]:
                line = line.strip(" -–•*·")
                if 6 <= len(line) <= 70 and _HN_HEAD.search(line) and not _HN_NOT_ROLE.search(line) \
                        and not line.endswith((".", ":", "?", "!")):
                    add(line)
        if not titles:
            continue
        where = [x for x in segs[1:] if _HN_WHERE.search(x) or geo.read_place(x)["countries"]]
        where = [x for x in where if not re.search(r"https?://|\$|€|£", x)][:3]
        body = _hn_emails(" ".join(paras))
        link = f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        for t in titles[:4]:
            out.append({"title": t, "company": company, "url": link,
                        "location": _clean_location(", ".join(where))[:120],
                        "summary": body[:600], "description": body[:ADVERT_CHARS],
                        "apply_email": _apply_email(body),
                        "posted_at": _posted(h.get("created_at")),
                        "source": "Hacker News"})
    return out


_PARSERS = {"remotive": _parse_remotive, "remoteok": _parse_remoteok,
            "rss": _parse_jobs_rss, "html": _parse_html_kind,
            "browser": _parse_browser_kind, "greenhouse": _parse_greenhouse,
            "lever": _parse_lever, "ashby": _parse_ashby,
            "workable": _parse_workable, "smartrecruiters": _parse_smartrecruiters,
            "recruitee": _parse_recruitee, "workday": _parse_workday,
            "bamboohr": _parse_bamboohr, "personio": _parse_personio,
            "himalayas": _parse_himalayas, "workingnomads": _parse_workingnomads,
            "jobicy": _parse_jobicy, "arbeitnow": _parse_arbeitnow,
            "stepstone": _parse_stepstone, "hn": _parse_hn}


def _fetch_workday(url: str, pages: int = 3) -> str:
    """Workday's careers sites answer a POST, twenty roles at a time; the
    first few pages are read and handed on as one."""
    if JOB_FETCHER is not None:
        return JOB_FETCHER(url)
    import httpx
    _pace(url)
    posts, total = [], 0
    headers = {**BROWSER_HEADERS, "Accept": "application/json", "Content-Type": "application/json",
               "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
    with httpx.Client(follow_redirects=True, timeout=25.0, headers=headers) as c:
        for n in range(pages):
            r = c.post(url, json={"appliedFacets": {}, "limit": 20, "offset": 20 * n, "searchText": ""})
            r.raise_for_status()
            data = r.json()
            total = int(data.get("total") or total or 0)
            got = data.get("jobPostings") or []
            posts.extend(got)
            if len(got) < 20 or len(posts) >= total:
                break
    return json.dumps({"total": total, "jobPostings": posts})


def fetch_for_kind(url: str, kind: str) -> str:
    """Fetch a source the way its kind needs: rendered in the browser, a
    Workday POST, or a plain request."""
    if kind == "browser":
        return fetch_with_browser(url)
    if kind == "workday":
        return _fetch_workday(url)
    if kind == "hn":
        return _fetch_hn(url)
    return _fetch_source(url)


def _fetch_hn(url: str) -> str:
    """The newest "Who is hiring?" thread and every post in it, as one
    document: the thread is found first, then its comments a page at a time."""
    stories = json.loads(_fetch_source(url))
    hit = next((h for h in (stories.get("hits") or [])
                if "who is hiring" in str(h.get("title", "")).lower()), None)
    if not hit:
        return json.dumps({"hits": []})
    sid, hits = str(hit.get("objectID")), []
    for page in range(5):
        d = json.loads(_fetch_source(
            "https://hn.algolia.com/api/v1/search_by_date?tags=comment,story_"
            f"{sid}&hitsPerPage=100&page={page}"))
        hits += d.get("hits") or []
        if page + 1 >= int(d.get("nbPages") or 1):
            break
    return json.dumps({"story_id": sid, "title": hit.get("title"), "hits": hits})


def looks_like_html(text: str) -> bool:
    head = (text or "")[:400].lstrip().lower()
    return head.startswith("<!doctype html") or head.startswith("<html") \
        or ("<head" in head and "<title" in head)


def _matches_profile(job: dict, p: dict) -> bool:
    """Keep what this person could plausibly do. A wider net means more
    applications and a worse hit rate; the scoring step is expensive, so
    filtering here is what keeps a daily run affordable."""
    blob = (job.get("title", "") + " " + job.get("summary", "")).lower()
    targets = [t.lower() for t in _as_list(p.get("target_roles"))]
    skills = [s.lower() for s in
              _as_list(p.get("skills")) + _as_list(p.get("technologies"))]
    if targets and any(t and (t in blob or _title_has(t, job.get("title", ""))) for t in targets):
        return True
    # "R", "Go" and "C" are skills, and letters in every advert
    hits = sum(1 for s in set(skills)
               if s and re.search(rf"(?<![\w+#]){re.escape(s)}(?![\w+#])", blob))
    return hits >= 2


_TITLE_NOISE = {"senior", "snr", "sr", "junior", "jnr", "jr", "lead", "principal", "staff", "mid",
                "level", "the", "of", "and", "a", "an", "for", "in", "to", "ii", "iii", "i",
                "remote", "contract", "permanent"}
_TITLE_FAMILY = ("engineer", "develop", "analy", "scien", "manag", "architect", "admin", "design",
                 "consult", "program", "test", "support", "market", "account", "operat", "secur",
                 "recruit", "research", "special", "techn", "account", "financ", "writ", "sell",
                 "sale", "lead", "direct", "coordinat", "assist", "teach", "train")
_TITLE_SAME = {"bi": "business intelligence", "ml": "machine learning", "ai": "artificial intelligence",
               "qa": "quality assurance", "sre": "site reliability", "ux": "user experience",
               "dba": "database admin", "pm": "product manag", "dev": "develop",
               "frontend": "front end", "backend": "back end", "fullstack": "full stack"}


def _title_tokens(text: str) -> set:
    t = re.sub(r"[-/]", " ", str(text or "").lower())
    for short, long_ in _TITLE_SAME.items():
        t = re.sub(rf"\b{short}\b", long_, t)
    out = set()
    for w in re.findall(r"[a-z0-9+#.]+", t):
        w = w.strip(".")
        if not w or w in _TITLE_NOISE:
            continue
        fam = next((f for f in _TITLE_FAMILY if w.startswith(f)), None)
        out.add(fam or (w[:-1] if len(w) > 3 and w.endswith("s") else w))
    return out


def _title_has(term: str, title: str) -> bool:
    """Does a job title say what a search term does, in whatever order and
    form? "Data Engineer" is in "Senior Engineer, Data Platform" and "Data
    Engineering Lead"; "BI Developer" is "Business Intelligence Developer".
    Matching the exact phrase missed all three."""
    want = _title_tokens(term)
    return bool(want) and want <= _title_tokens(title)


# The most each of the run's limits may be set to (jobs/server.py clamps to these)
LIMITS = {"daily_cap": 200, "portal_per_run": 100, "discover_per_run": 1000,
          "engine_workers": ENGINE_WORKERS_MAX}


def discover(limit: int | None = None) -> dict:
    """Pull fresh roles from the configured boards and record the new ones.

    It kept the first 40 matches and dropped the rest, every run, whatever
    the boards had: a search across six boards found hundreds and tracked 40.
    How many is your setting now (discover_per_run), and roles it already
    tracks no longer use up that room."""
    if limit is None:
        try:
            limit = int(auto_config().get("discover_per_run") or 150)
        except Exception:
            limit = 150
    p = profile()
    # One pass over the sources, done by one function. This had its own copy
    # of the loop — which fetched every source over plain HTTP whatever its
    # kind, so a "browser" source never rendered here, and it left the
    # browser it opened running. Two loops doing one job is how a fix lands
    # in the wrong one: the cycle kept its old behaviour after the search
    # path was fixed.
    raw, errors, _raw_per = _fetch_all()
    found, per_source = [], {}
    skipped, skipped_detail = {}, {}
    cfg = {**search_config(), "_use_profile_targets": True}
    for j in raw:
        name = j.pop("_src", None) or j.get("source", "?")
        per_source.setdefault(name, 0)
        try:
            if not j.get("title"):
                continue
            ok, why = matches_search(j, cfg)
            # search terms, when set, are a deliberate instruction and beat
            # the looser profile guess
            if ok and not (cfg.get("queries") or []) and not _matches_profile(j, p):
                ok, why = False, "not a match for your profile"
            if not ok:
                why = why.split(" \u201c")[0]
                skipped[why] = skipped.get(why, 0) + 1
                d = j.pop("_skip_detail", "")
                if d and why == "region excludes you":
                    skipped_detail[d] = skipped_detail.get(d, 0) + 1
                continue
            per_source[name] += 1
            found.append(j)
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    # the configured sources are the ones to report on: a role can carry a
    # source label of its own, which would otherwise appear as a seventh
    # "source" that nobody added
    per_source = {name: per_source.get(name, 0) for name in _raw_per}
    # roles already tracked don't use up the run's room: the room is for new
    # ones, and a board that lists the same 40 every day filled it with roles
    # add_roles was going to skip anyway
    try:
        have = {r.get("key") for r in roles()} | {k.lower() for k in ignored_keys()}
        found = [j for j in found if role_key(j) not in have] + \
                [j for j in found if role_key(j) in have]
    except Exception:
        pass
    # a turn each: taken in the order read, the first large board filled the
    # run's room and the others never got a role in
    try:
        by, order = {}, []
        for j in found:
            k = j.get("source") or "?"
            if k not in by:
                by[k] = []
                order.append(k)
            by[k].append(j)
        mixed = []
        while any(by.values()):
            for k in order:
                if by[k]:
                    mixed.append(by[k].pop(0))
        new_first = [j for j in mixed if role_key(j) not in have]
        found = new_first + [j for j in mixed if role_key(j) in have]
    except Exception:
        pass
    found = found[:max(1, int(limit))]
    res = add_roles(found)
    emails = sum(1 for j in found if j.get("apply_email"))
    _audit("discover", f"{res['added']} new of {len(found)} matched; "
                       f"{emails} have an application address")
    return {"ok": True, "added": res["added"], "matched": len(found),
            "with_email": emails, "per_source": per_source,
            "read": len(raw),
            # what was passed over, by reason, and for the commonest reason
            # (a remote role open only to people elsewhere) where that was
            "skipped": skipped,
            "skipped_where": sorted(skipped_detail.items(), key=lambda x: -x[1])[:6],
            "errors": errors,
            "note": ("Roles without an application address are portal "
                     "applications — they're tracked, but only you can "
                     "submit them.")}


# --------------------------------------------------------------------------- #
#  Follow-ups — the cheapest thing in the whole pipeline
# --------------------------------------------------------------------------- #
_FOLLOWUP_SYSTEM = (
    "Write a short follow-up to an application sent {days} days ago with no "
    "reply. Four sentences at most. Reference the specific role, add ONE "
    "concrete thing of value not in the original (a relevant piece of work, a "
    "question about their stack), and make it easy to say no. Do not guilt "
    "them, do not repeat the original letter, do not invent anything about "
    "the candidate that isn't in the PROFILE. Return ONLY raw JSON: "
    "{{\"subject\": str, \"body\": str}}.")


def draft_follow_up(key: str, brain, model=None, fix: str = "") -> dict:
    r = get_role(key)
    if r is None:
        return {"ok": False, "error": "no such role"}
    if r.get("stage") != "applied":
        return {"ok": False,
                "error": "only an application that was actually sent needs "
                         "chasing"}
    days = 7
    for f in follow_ups(0):
        if f["key"] == key:
            days = f.get("silent_days", 7)
    payload = json.dumps({"PROFILE": profile(), "ROLE": r,
                          "ORIGINAL": (r.get("draft") or {}).get("body", "")},
                         default=str)[:9000]
    try:
        kw = {"model": model} if model else {}
        data = _json_from(brain.chat(
            [{"role": "user", "content": payload}],
            [_FOLLOWUP_SYSTEM.format(days=days) + _style_clause(("length",)) + _banned_clause()
             + (fix or "")], None, **kw))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    body = _as_text(data.get("body"))
    check = check_draft(body, r)
    fu = {"subject": _as_text(data.get("subject"))[:200], "body": body,
          "check": check, "at": _iso(), "days": days}
    update_role(key, follow_up=fu)
    return {"ok": True, "follow_up": fu}


def send_follow_ups(brain, model=None, cfg: dict | None = None) -> dict:
    """One follow-up to each emailed application that has gone quiet.

    The app could draft a follow-up and never sent one: every application
    that got no answer simply waited. A short note a week later is the
    cheapest thing in the whole pipeline and one of the few that reliably
    raises the reply rate. The rails:

      * only applications that went by email, to the address they went to,
        and only once — a role that has had its follow-up never gets another;
      * only after replies are read (auto_cycle runs this after the inbox), so
        anyone who has answered — yes or no — has left "applied" and isn't
        chased;
      * the follow-up passes the same claims check as the letter, or it is
        kept for you instead of sent;
      * in rehearsal, or a level that doesn't send email, it is drafted for
        you and nothing goes."""
    from . import outreach
    cfg = cfg or auto_config()
    out = {"sent": [], "drafted": [], "held": [], "errors": []}
    if not cfg.get("auto_follow_up", True) or not cfg.get("enabled"):
        return out
    live = (not cfg.get("dry_run", True)) and cfg.get("deliver", True)
    days = max(2, int(cfg.get("follow_up_after_days", 7) or 7))
    room = max(0, int(cfg.get("follow_ups_per_run", 10) or 0))
    due = [r for r in follow_ups(days)
           if _as_text(r.get("apply_email")).strip() and not r.get("follow_up_sent_at")
           and not r.get("sent_dry_run")]
    due.sort(key=lambda r: -int(r.get("silent_days") or 0))
    for r in due[:room]:
        key = r["key"]
        row = {"key": key, "title": r.get("title", ""), "company": r.get("company", "")}
        fu = r.get("follow_up") or {}
        if not fu.get("body"):
            d = draft_follow_up(key, brain, model=model)
            if not d.get("ok"):
                out["errors"].append(f"{row['title']}: follow-up: {d.get('error', '')}")
                continue
            fu = d["follow_up"]
            if (fu.get("check") or {}).get("ok") is False:
                # once more, told what to drop — as the letters get
                d2 = draft_follow_up(key, brain, model=model,
                                     fix=_claims_instructions(fu.get("check")))
                if d2.get("ok"):
                    fu = d2["follow_up"]
        if (fu.get("check") or {}).get("ok") is False:
            out["held"].append({**row, "reason": "the follow-up claims something your "
                                                 "profile can't support — needs your eyes"})
            continue
        if not live:
            out["drafted"].append(row)
            continue
        orig = _as_text((r.get("draft") or {}).get("subject")).strip() or f"Application: {r.get('title', '')}"
        subject = _as_text(fu.get("subject")).strip() or ("Re: " + orig)
        body = fu["body"] + ("\n\n" + cfg["signature"] if cfg.get("signature") else "")
        res = outreach.send(r["apply_email"], subject, body)
        if res.get("ok"):
            update_role(key, follow_up_sent_at=_iso())
            events = list((get_role(key) or {}).get("events") or [])
            events.append({"at": _iso(), "stage": "applied",
                           "note": f"followed up after {r.get('silent_days')} days"})
            update_role(key, events=events)
            out["sent"].append({**row, "to": r["apply_email"]})
        else:
            out["errors"].append(f"{row['title']}: follow-up: {res.get('error', 'not sent')}")
    if out["sent"] or out["drafted"]:
        _audit("follow-up", f"{len(out['sent'])} sent, {len(out['drafted'])} drafted")
    return out


# --------------------------------------------------------------------------- #
#  A tailored letter per role, saved where you can attach it
# --------------------------------------------------------------------------- #
def application_dir() -> Path:
    d = _dir() / "applications"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_application_file(key: str) -> dict:
    """Write the drafted letter to disk so it can be attached, pasted into a
    portal form, or kept as a record of what was actually sent."""
    r = get_role(key)
    if r is None or not (r.get("draft") or {}).get("body"):
        return {"ok": False, "error": "nothing drafted for that role yet"}
    d = r["draft"]
    name = _slug(f"{r.get('company','')}-{r.get('title','')}") or key
    path = application_dir() / f"{name}.txt"
    lines = [f"Role: {r.get('title','')}", f"Company: {r.get('company','')}",
             f"Advert: {r.get('url','')}", f"Prepared: {_iso()}", "",
             f"Subject: {d.get('subject','')}", "", d.get("body", "")]
    if (d.get("check") or {}).get("ok") is False:
        lines += ["", "VERIFY BEFORE SENDING — claims not sourced from your "
                      "profile:"]
        lines += ["  - " + p["detail"] for p in d["check"].get("problems", [])]
    path.write_text("\n".join(lines), "utf-8")
    update_role(key, application_file=str(path))
    return {"ok": True, "path": str(path)}


# --------------------------------------------------------------------------- #
#  One unattended pass: find, score, draft, send what qualifies
# --------------------------------------------------------------------------- #
ATS_FLOOR = 25          # below this, a screener would drop it anyway


def _advert_text(role: dict) -> str:
    return " ".join(_as_text((role or {}).get(k)) for k in
                    ("title", "summary", "description", "location")).lower()


def deal_breaker(role: dict, p: dict = None) -> str:
    """The first of your deal-breakers the advert states, or ''.

    The profile had deal_breakers and must_haves from the start and nothing
    read them: "no commission-only", "no night shift" sat there while
    auto-apply applied to exactly those. Matched as whole words or phrases."""
    p = p if p is not None else profile()
    text = _advert_text(role)
    for d in _as_list(p.get("deal_breakers")):
        d = d.strip().lower()
        if d and re.search(r"(?<![a-z0-9])" + re.escape(d) + r"(?![a-z0-9])", text):
            return d
    return ""


def must_haves_missing(role: dict, p: dict = None) -> list:
    """Your must-haves the advert doesn't mention. Adverts leave things out,
    so this is shown, not used to reject."""
    p = p if p is not None else profile()
    text = _advert_text(role)
    return [m for m in _as_list(p.get("must_haves")) if m.strip() and m.strip().lower() not in text]


def prescreen(role: dict, p: dict = None) -> dict:
    """A free keyword check before any engine call.

    Scoring a role costs a request; the keyword comparison costs nothing and
    catches the obviously-wrong ones. On a scan that finds forty roles this is
    the difference between forty paid calls and a handful."""
    p = p if p is not None else profile()
    hit = deal_breaker(role, p)
    if hit:
        return {"pass": False, "score": None, "why": f"deal-breaker: “{hit}” is in the advert"}
    try:
        from . import cv as cvmod
        s = cvmod.ats_scan(role, p)
    except Exception:
        return {"pass": True, "score": None, "why": ""}
    if s.get("total_terms", 0) < 3:
        return {"pass": True, "score": s.get("score"),
                "why": "advert names too few specifics to screen on"}
    if s["score"] < ATS_FLOOR:
        return {"pass": False, "score": s["score"],
                "why": (f"only {s['score']}% keyword overlap — missing "
                        f"{', '.join(s['missing'][:5])}")}
    return {"pass": True, "score": s["score"], "why": ""}


def auto_cycle(brain, model=None) -> dict:
    """What the daily schedule runs. Sourcing is what turned this from
    'applies to the roles you gave it' into something that can genuinely run
    without you."""
    out = {"discovered": 0, "errors": []}
    _note("Looking for new roles")
    try:
        d = discover()
        out["discovered"] = d.get("added", 0)
        out["errors"] += d.get("errors", [])
        out["with_email"] = d.get("with_email", 0)
    except Exception as exc:
        out["errors"].append(f"discovery: {type(exc).__name__}: {exc}")
    # an advert whose board gave a closing date, and it has passed: closed,
    # before anything is read or spent on it
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        gone = 0
        for r in roles():
            if r.get("stage") in ("found", "drafted") and r.get("closes_at") \
                    and str(r["closes_at"]) < today:
                mark_closed(r["key"], f"the advert closed on {r['closes_at']}", expired=True)
                gone += 1
        if gone:
            out["closed_by_date"] = gone
    except Exception as exc:
        out["errors"].append(f"closing dates: {type(exc).__name__}: {exc}")
    # read the advert itself where the board gave little more than a title,
    # so the screens, the score and the letter have the requirements to go on
    acfg = auto_config()
    if acfg.get("read_adverts", True):
        _note("Reading the adverts")
        try:
            er = enrich_roles(limit=int(acfg.get("read_per_run", 40) or 0))
            out["adverts_read"] = er["read"]
            out["emails_found_in_adverts"] = er["emails"]
            out["closed_by_date"] = int(out.get("closed_by_date") or 0) + er["closed"]
        except Exception as exc:
            out["errors"].append(f"reading adverts: {type(exc).__name__}: {exc}")
    # collapse the same vacancy found on several boards before spending
    # anything on it (after reading the adverts, which names the companies)
    try:
        d2 = dedupe_roles()
        out["deduped"] = d2.get("removed", 0)
    except Exception:
        out["deduped"] = 0
    # then drop the obviously-wrong ones for free
    screened = 0
    p = profile()
    trust_out = {"scams": 0, "ghosts": 0}
    _geo_cfg = dict(search_config())
    everyone = roles()
    for r in everyone:
        if r.get("stage") != "found" or (r.get("fit") or {}).get("score"):
            continue
        # not a real vacancy, or not a real job: set aside before anything
        # is spent on it. You can bring one back from Closed.
        t = check_trust(r, everyone, save=True)
        if not r.get("approved") and (
                t["verdict"] == "scam"
                or (acfg.get("skip_ghosts", True)
                    and t["ghost"] >= int(acfg.get("ghost_bar", 60) or 60))):
            from . import trust as _trust
            update_role(r["key"], stage="closed",
                        closed_reason=f"screened out: {_trust.says(t) or 'likely a ghost job'}")
            trust_out["scams" if t["verdict"] == "scam" else "ghosts"] += 1
            screened += 1
            continue
        # the advert says who may apply, and it isn't you: "must be based in
        # the United States", "no visa sponsorship". Free, and before any
        # engine call. Approving the role yourself overrides it.
        try:
            from . import geo
            mine = _allowed(_geo_cfg)
            where = geo.read_place(_as_text(r.get("location")))["countries"]
            blocked = "" if r.get("approved") else geo.blocked_by_advert(
                _as_text(r.get("description") or r.get("summary")), mine, where)
        except Exception:
            blocked = ""
        if blocked:
            update_role(r["key"], stage="closed", closed_reason=f"screened out: {blocked}")
            trust_out["not_eligible"] = trust_out.get("not_eligible", 0) + 1
            screened += 1
            continue
        ps = prescreen(r, p)
        if not ps["pass"]:
            update_role(r["key"], stage="closed",
                        closed_reason=f"screened out: {ps['why']}",
                        ats=ps["score"])
            screened += 1
    out["screened_out"] = screened
    out["scams_skipped"], out["ghosts_skipped"] = trust_out["scams"], trust_out["ghosts"]
    out["not_eligible"] = trust_out.get("not_eligible", 0)
    # replies first: a role that has had an answer shouldn't be chased
    try:
        from . import inbox
        if inbox.settings().get("enabled") or any(inbox.replies_dir().glob("*.eml")):
            _note("Reading replies to your applications")
            ib = inbox.check()
            out["replies"] = len(ib.get("found") or [])
            if ib.get("error") or ib.get("warning"):
                out["errors"].append("inbox: " + (ib.get("error") or ib.get("warning")))
    except Exception as exc:
        out["errors"].append(f"inbox: {type(exc).__name__}: {exc}")
    # the people behind the replies, and roles at companies where you know one
    try:
        from . import contacts
        contacts.sync()
        out["known_people_roles"] = contacts.flag_roles()
    except Exception as exc:
        out["errors"].append(f"contacts: {type(exc).__name__}: {exc}")
    # a week of silence after an emailed application: one short follow-up.
    # After the inbox, so nobody who has answered is chased.
    try:
        fu = send_follow_ups(brain, model)
        out["followed_up"] = len(fu["sent"])
        out["follow_ups_drafted"] = len(fu["drafted"])
        out["errors"] += fu["errors"]
    except Exception as exc:
        out["errors"].append(f"follow-ups: {type(exc).__name__}: {exc}")
    # an interview invitation deserves preparation before you open the email
    try:
        out["interview_prep"] = prepare_interviews(brain, model)
    except Exception as exc:
        out["errors"].append(f"interview prep: {type(exc).__name__}: {exc}")
    # a weekly backup, so a dead disk doesn't take the job search with it
    try:
        from . import backup
        if backup.weekly_due():
            out["backup"] = backup.make("weekly")["filename"]
    except Exception as exc:
        out["errors"].append(f"backup: {type(exc).__name__}: {exc}")
    _note("Checking which adverts have closed")
    try:
        sw = sweep_expired(limit=8)
        out["expired"] = len(sw.get("closed") or [])
    except Exception:
        out["expired"] = 0
    _IN_CYCLE["on"] = True
    try:
        res = auto_apply(brain, model=model)
    finally:
        _IN_CYCLE["on"] = False
    # the prepared forms and the shared cause were dropped here, so a
    # scheduled run never reported the portal work it had done
    out.update({k: res.get(k) for k in
                ("ok", "sent", "held", "dry_run", "remaining_today",
                 "prepared", "common_error", "error_groups",
                 "engine_stopped")})
    out["errors"] += res.get("errors", [])
    if not res.get("ok"):
        out["error"] = res.get("error", "")
        out["ok"] = True              # the finding still happened
    try:
        from . import digest
        dg = digest.send()
        if dg.get("sent"):
            out["digest"] = dg.get("to")
        elif not dg.get("ok"):
            out["errors"].append("weekly digest: " + dg.get("error", ""))
    except Exception as exc:
        out["errors"].append(f"weekly digest: {type(exc).__name__}: {exc}")
    out["summary"] = describe_run(out)
    try:
        _record_run(out, "cycle")
    except Exception:
        pass
    return out


# =========================================================================== #
#  Search — what to look for, and where
#
#  discover() took whatever the boards happened to list and kept anything that
#  loosely matched the profile. That is fine for a daily trickle and useless
#  when you want contract BI work in a particular stack, or want to exclude
#  the agencies that repost the same role nine times.
#
#  Two separate ideas, deliberately not merged:
#    WHAT  — terms to match, terms to exclude, remote/location rules
#    WHERE — which boards are on, plus any you add yourself
# =========================================================================== #
SEARCH_DEFAULTS = {
    "queries": [],          # any-of; empty falls back to the profile
    "exclude": [],          # none-of, checked first
    "locations": [],        # any-of against the advert's location
    "remote_only": True,
    "require_email": False,  # only roles the email path can actually use
}


def search_config() -> dict:
    return {**SEARCH_DEFAULTS, **(load_config().get("search") or {})}


def save_search_config(cfg: dict) -> dict:
    base = load_config()
    # keys beginning "_" are a search's own working notes, never settings
    merged = {**search_config(), **{k: v for k, v in (cfg or {}).items()
                                    if not str(k).startswith("_")}}
    for k in ("queries", "exclude", "locations"):
        merged[k] = [s.strip() for s in _as_list(merged.get(k)) if s.strip()]
    base["search"] = merged
    save_config(base)
    return merged


def _blob(job: dict) -> str:
    return " ".join([str(job.get("title", "")), str(job.get("summary", "")),
                     str(job.get("company", ""))]).lower()


def _allowed(cfg: dict) -> dict:
    """Where this person can work (agent/geo.py): the search's own location
    list when one is set, else the profile's, plus the country they live in.
    Worked out once per search, not once per role."""
    got = cfg.get("_allowed")
    if got is None:
        from . import geo
        p = profile()
        places = cfg.get("locations") or _as_list(p.get("locations_ok"))
        got = geo.allowed_from(places, home=_as_text(p.get("location")))
        cfg["_allowed"] = got
    return got


def _is_region_constraint(loc: str) -> bool:
    """Is this a list of regions a remote candidate may live in, rather than
    an office address? Countries and groupings with no town among them."""
    from . import geo
    p = geo.read_place(str(loc or "").strip().strip(","))
    return bool(p["text"]) and (p["only_regions"] or (p["open"] and not p["unknown"]
                                                      and bool(geo._OPEN.search(p["text"]))))


def _region_includes_me(loc: str, cfg: dict) -> bool:
    """Does that region list cover where this person can work?"""
    from . import geo
    return geo.decide(loc, _allowed(dict(cfg or {})), remote_only=False, remote=True)[0]


def location_verdict(job: dict, cfg: dict) -> tuple:
    """(keep, category, detail) for a role's location against where you can
    work. category is what a report groups by ("not remote", "region excludes
    you", "location not in your list"); detail is the sentence to show ("open
    only to people in Canada, United States")."""
    from . import geo
    return geo.decide(
        _as_text(job.get("location")), _allowed(cfg),
        remote_only=bool(cfg.get("remote_only")),
        # what the board itself said, where it said it: remote or not, the
        # countries a remote role is open to, the one country a board serves
        remote=bool(job.get("remote")), countries=job.get("countries") or None,
        default_country=_as_text(job.get("country")))


def matches_search(job: dict, cfg: dict = None) -> tuple[bool, str]:
    """(keep, why_not). Exclusions are checked first — a term you've banned
    should win over a term you asked for, or 'senior' would drag back in the
    agency reposts you just excluded."""
    cfg = cfg if cfg is not None else search_config()
    blob = _blob(job)
    for bad in cfg.get("exclude") or []:
        if bad.lower() in blob:
            return False, f"excluded by \u201c{bad}\u201d"
    # WHERE: an office somewhere you can't be, or a remote role open only to
    # people elsewhere. Read by agent/geo.py, which knows the places; the old
    # word list threw out every plain "Remote" role for anyone who had said
    # where they can work, kept "Remote, US", and called EMEA not Africa.
    # NOTE: this only settles the LOCATION question. Returning True here
    # short-circuited the search-term and exclusion checks below, so a
    # worldwide-remote role matched every query.
    keep, category, detail = location_verdict(job, cfg)
    if not keep:
        job["_skip_detail"] = detail
        return False, category
    queries = cfg.get("queries") or []
    if not queries and cfg.get("_use_profile_targets"):
        # An unattended run should look for what your profile says you want,
        # rather than everything the boards have. An explicitly empty search
        # box means the opposite — "show me everything" — so this only
        # applies where nobody is typing.
        queries = cfg.get("_derived")
        if queries is None:
            queries = cfg["_derived"] = derive_queries()
    if queries and not any(q.lower() in blob or _title_has(q, job.get("title", ""))
                           for q in queries):
        return False, "no search term matched"
    if cfg.get("require_email") and not job.get("apply_email"):
        return False, "no application address"
    return True, ""


# How many of your search terms a searchable board is asked for, and the
# boards that take a page number.
MAX_QUERIES_PER_SOURCE = 6
_PAGED = {"stepstone": "page", "himalayas": "page", "arbeitnow": "page"}
_FEED_KINDS = ("rss", "remotive", "remoteok", "himalayas", "workingnomads", "jobicy",
               "arbeitnow", "hn")


def _source_urls(src: dict, query: str = "") -> list:
    """The addresses to read for one source: its own, or one for each of your
    search terms when the board can be searched ({query} in its address).

    A board that lists a hundred thousand roles shows a reader its newest
    twenty, of which none may be yours. Asked for "data engineer" in your
    country, the same board returns hundreds that are."""
    url = str(src.get("url") or "")
    if query and src.get("kind") == "remotive" and "{query" not in url:
        return [f"{url}{'&' if '?' in url else '?'}search={query.replace(' ', '+')}"]
    if "{query" not in url and "{country}" not in url:
        return [url]
    from urllib.parse import quote_plus
    from . import geo
    if query:
        terms = [q.strip() for q in re.split(r"[,;]| OR ", query) if q.strip()]
    else:
        terms = (search_config().get("queries") or []) or derive_queries()
    terms = terms[:MAX_QUERIES_PER_SOURCE] or [""]
    home = geo.read_place(_as_text(profile().get("location")))["countries"]
    cc = sorted(home)[0] if len(home) == 1 else ""
    out = []
    for t in terms:
        u = (url.replace("{query}", quote_plus(t))
             .replace("{query-slug}", re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-"))
             .replace("{country}", cc))
        if u not in out:
            out.append(u)
    return out


def _cache_dir() -> Path:
    d = _dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch_cached(url: str, kind: str, max_age_hours: float = 0) -> str:
    """Read a source — or, for a board that asks not to be read often, the
    copy read less than `max_age_hours` ago.

    Himalayas refreshes once a day and says so; Remotive asks for four reads
    a day at most. A run every two hours has no business asking them twelve
    times, and nothing to gain: the answer is the same."""
    if not max_age_hours:
        return fetch_for_kind(url, kind)
    import hashlib
    f = _cache_dir() / (hashlib.sha1(f"{kind}|{url}".encode("utf-8")).hexdigest()[:20] + ".txt")
    try:
        if f.exists() and time.time() - f.stat().st_mtime < float(max_age_hours) * 3600:
            return f.read_text("utf-8")
    except Exception:
        pass
    text = fetch_for_kind(url, kind)
    try:
        f.write_text(text, "utf-8")
        for old in f.parent.glob("*.txt"):          # nothing kept past three days
            if time.time() - old.stat().st_mtime > 3 * 86400:
                old.unlink()
    except Exception:
        pass
    return text


def read_source(src: dict, query: str = "") -> dict:
    """Read one source the way its kind needs: {'jobs', 'error', 'html'}.

    One function for a scheduled run, a search you type, and the check made
    before a board is added, so a fix to how a board is read lands in all
    three."""
    kind = src.get("kind", "rss")
    parser = _PARSERS.get(kind, _parse_jobs_rss)
    try:
        pages = max(1, min(5, int(src.get("pages") or 1)))
    except Exception:
        pages = 1
    age = float(src.get("min_hours") or 0)
    jobs, seen, err, html_seen = [], set(), "", False
    for url in _source_urls(src, query):
        for n in range(1, pages + 1):
            u = url
            if n > 1:
                if kind not in _PAGED:
                    break
                u = f"{url}{'&' if '?' in url else '?'}{_PAGED[kind]}={n}"
            try:
                _CURRENT_SOURCE_URL["url"] = u
                text = _fetch_cached(u, kind, age)
                got = [j for j in parser(text) if j.get("title")]
            except Exception as exc:
                err = err or _explain_fetch_error(f"{type(exc).__name__}: {exc}", u)
                break
            if not got and looks_like_html(text):
                html_seen = True
            fresh = 0
            for j in got:
                k = j.get("url") or (j.get("company"), j.get("title"))
                if k in seen:
                    continue
                seen.add(k)
                jobs.append(j)
                fresh += 1
            if not fresh:
                break                      # nothing new on this page: no deeper
    return {"jobs": jobs, "error": "" if jobs else err, "html": html_seen and not jobs}


def _fetch_all(query: str = "") -> tuple[list, list, dict]:
    if not [s for s in job_sources() if s.get("on", True)]:
        return [], ["No sites added yet — add one under Where & filters, or "
                    "paste a page into 'Search this page'."], {}
    """Pull every enabled source once. `query` is pushed into the URL where a
    board supports it, so the filtering happens at their end rather than ours
    where it can."""
    found, errors, per_source = [], [], {}
    # one browser for the whole pass, and only if a source needs it. Each
    # fetch used to start its own, so a cycle opened a browser per source —
    # a screen of blank tabs with one real page among them.
    if any(s.get("kind") == "browser" and s.get("on", True)
           for s in job_sources()):
        open_fetch_batch()
    for src in job_sources():
        if not src.get("on", True):
            continue
        name = src.get("name", "?")
        kind = src.get("kind", "rss")
        try:
            r = read_source(src, query)
        except Exception as exc:
            r = {"jobs": [], "html": False,
                 "error": _explain_fetch_error(f"{type(exc).__name__}: {exc}", src.get("url", ""))}
        jobs = r["jobs"]
        for j in jobs:
            # which of YOUR sources it came from: a parser's own label ("RSS",
            # "Acme (Greenhouse)") is not the name you gave the source, and
            # counting by it left most sources reporting nothing kept
            j["_src"] = name
            if j.get("source") in ("", "RSS", None):
                j["source"] = name
        if r["error"]:
            errors.append(f"{name}: {r['error']}")
            per_source[name] = 0
            continue
        # A feed parser handed a web page returns nothing and says
        # nothing — the source then sits on "pending" for ever. Say what
        # actually arrived, and what to do about it.
        if not jobs and kind in _FEED_KINDS and r["html"]:
            errors.append(
                f"{name}: that address returns a web page, not a "
                f"{kind} feed. Change this source to 'browser' so it is "
                f"rendered like a real visit — sites that draw their "
                f"listings with JavaScript, or only after you sign in, "
                f"need that.")
            per_source[name] = 0
            continue
        if not jobs and kind == "browser":
            errors.append(
                f"{name}: the page rendered but no roles were found in "
                f"it. If this site needs a sign-in, use 'Sign in to this "
                f"site' once — the browser keeps the session.")
        per_source[name] = len(jobs)
        found.extend(jobs)
    # recorded here, where every path passes. It used to be recorded only by
    # a keyword search, so a source only ever touched by the daily run stayed
    # "pending" — never checked, as far as the app could tell.
    close_fetch_batch()
    record_source_checks(per_source, errors)
    return found, errors, per_source


def record_source_checks(per_source: dict, errors: list) -> None:
    """Keep what each source did the last time it was asked.

    The Sources view marks a board Verified, Pending or Failing. Those words
    have to come from something that happened — a board is Verified because
    it returned roles on its last check, not because it's in a list.
    """
    try:
        cfg = load_config()
        checks = dict(cfg.get("source_checks") or {})
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        why = {}
        for e in errors or []:
            name, _, msg = str(e).partition(":")
            why[name.strip()] = msg.strip()[:200]
        for name, n in (per_source or {}).items():
            checks[name] = {"count": int(n or 0), "at": now,
                            "error": why.get(name, "")}
        cfg["source_checks"] = checks
        cfg["sources_checked_at"] = now
        save_config(cfg)
    except Exception:
        pass                                   # a status must never break a search


def source_status() -> dict:
    """Each source's standing, from its last real check."""
    cfg = load_config()
    checks = cfg.get("source_checks") or {}
    out = []
    for s in job_sources():
        c = checks.get(s.get("name")) or {}
        if not c:
            status = "pending"                 # never asked yet
        elif c.get("error") or not c.get("count"):
            status = "failing"
        else:
            status = "verified"
        out.append({**s, "status": status, "last_count": c.get("count"),
                    "checked_at": c.get("at", ""), "error": c.get("error", "")})
    return {"sources": out, "checked_at": cfg.get("sources_checked_at", "")}


def search(query: str = "", limit: int = 40) -> dict:
    """Look now, without recording anything. A preview matters: adding forty
    roles you didn't want is tedious to undo, and the scoring step that
    follows costs money."""
    cfg = search_config()
    if query:
        cfg = {**cfg, "queries": [q.strip() for q in
                                  re.split(r"[,;]| OR ", query) if q.strip()]}
    found, errors, per_source = _fetch_all(query)
    results, rejected = [], {}
    for j in found:
        keep, why = matches_search(j, cfg)
        if not keep:
            rejected[why] = rejected.get(why, 0) + 1
            continue
        results.append(j)
    results = mark_tracked(results)
    return {"ok": True, "query": query, "results": results[:limit],
            "total": len(results), "per_source": per_source,
            "rejected": rejected, "errors": errors}


def _key_for(company: str, title: str, url: str = "") -> str:
    """Company and title — or, with no company (a listings page gives a
    title and a link), the site and a fingerprint of the link. Keyed on the
    title alone, every "Data Engineer" on a listings page was the same role,
    and only the first was ever kept."""
    company, title, url = (company or "").strip(), (title or "").strip(), (url or "").strip()
    if company or not url:
        return _slug(f"{company}-{title}")
    import hashlib
    host = re.sub(r"^https?://(www\.)?([^/]+).*$", r"\2", url).split(".")[0]
    return _slug(f"{host}-{title}-{hashlib.sha1(url.encode('utf-8')).hexdigest()[:6]}")


def role_key(job: dict) -> str:
    """The key a role is stored under — the one definition of "same role"."""
    return _key_for(_as_text(job.get("company")), _as_text(job.get("title")),
                    _as_text(job.get("url")))


def mark_tracked(results: list) -> list:
    """Say, for each found role, whether it's already tracked or was removed.

    A search that doesn't say which results you already have makes you
    track the same role twice or wonder why nothing happened — and a role
    you removed is silently skipped by add_roles, so without this its Track
    button did nothing at all.
    """
    have = {r.get("key") for r in roles()}
    gone = {k.lower() for k in ignored_keys()}
    out = []
    for j in results or []:
        j = dict(j)
        k = role_key(j)
        j["key"] = k
        j["already_tracked"] = k in have
        j["removed_before"] = (not j["already_tracked"]) and k.lower() in gone
        out.append(j)
    return out


def add_from_search(items: list, restore: bool = False) -> dict:
    """Record roles chosen from a search preview, and say what happened to
    each one.

    It used to return only a count, and the window assumed success — so when
    nothing was added, nothing said so. Each item now gets its own outcome:
    added, already tracked, removed earlier, or not a real role.
    """
    items = items or []
    if restore:
        # tracking a role you removed earlier means you've changed your mind
        for i in items:
            unignore(role_key(i))          # takes one key at a time
    before = {r.get("key") for r in roles()}
    gone = {k.lower() for k in ignored_keys()}
    r = add_roles(items)
    after = {x.get("key") for x in roles()}
    outcomes = []
    for i in items:
        k = role_key(i)
        if not _as_text(i.get("title")).strip():
            status = "not a role"
        elif k in before:
            status = "already tracked"
        elif k in after:
            status = "added"
        elif k.lower() in gone:
            status = "removed earlier"
        else:
            status = "not a role"
        outcomes.append({"key": k, "title": _as_text(i.get("title")),
                         "status": status})
    return {**r, "outcomes": outcomes,
            "added": sum(o["status"] == "added" for o in outcomes)}


# --------------------------------------------------------------------------- #
#  where to look
# --------------------------------------------------------------------------- #
def normalise_url(url: str) -> str:
    """Make a pasted address usable.

    Two sources were saved as bare hostnames and every fetch failed with
    'Request URL is missing an http:// or https:// protocol'. People paste
    what they see in the address bar, which often has no scheme."""
    u = (url or "").strip().strip("<>\"' ")
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if not re.match(r"^https?://", u, re.I):
        if not re.match(r"^[\w.-]+\.[a-z]{2,}", u, re.I):
            return ""              # not an address at all
        u = "https://" + u
    return u


def repair_sources() -> int:
    """Fix sources already saved without a scheme, so an old mistake doesn't
    keep failing forever."""
    items = job_sources()
    fixed = 0
    for s in items:
        good = normalise_url(s.get("url", ""))
        if good and good != s.get("url"):
            s["url"] = good
            fixed += 1
        if (s.get("name") or "").startswith(("http://", "https://")):
            s["name"] = _site_of(s["url"])
            fixed += 1
    if fixed:
        save_job_sources(items)
    return fixed


def set_source_kind(name: str, kind: str) -> dict:
    """Change how a source is fetched, in place.

    Adding it again doesn't change an existing one, so a "switch to browser"
    that called add_job_source reported success and changed nothing — the
    worse half of that bug being the cheerful message.
    """
    srcs = job_sources()
    for s in srcs:
        if s.get("name") == name:
            s["kind"] = kind
            try:
                (_dir() / "sources.json").write_text(
                    json.dumps(srcs, indent=2), "utf-8")
            except Exception as exc:
                return {"ok": False, "error": str(exc)[:200]}
            return {"ok": True, "name": name, "kind": kind}
    return {"ok": False, "error": f"no source called {name!r}"}


def add_job_source(name: str, url: str, kind: str = "rss", pages=None, min_hours=None) -> dict:
    name = (name or "").strip()
    url = (url or "").strip()
    if not url and name.startswith(("http://", "https://")):
        url = name                       # only a url was given
        name = ""
    url = normalise_url(url)
    if not url:
        return {"ok": False, "error": "a source needs a URL"}
    if not name or name.startswith(("http://", "https://")):
        # a url makes a poor label and, until now, an unusable identifier
        name = _site_of(url)
    if kind not in _PARSERS:
        return {"ok": False,
                "error": f"kind must be one of: {', '.join(_PARSERS)}"}
    items = job_sources()
    if any(s.get("url") == url for s in items):
        return {"ok": False, "error": "that URL is already a source"}
    items.append({"name": name, "url": url, "kind": kind, "on": True,
                  # how deep to read it, and how long its answer is kept
                  # before it is asked again (its own terms decide both)
                  **({"pages": int(pages)} if pages else {}),
                  **({"min_hours": float(min_hours)} if min_hours else {})})
    save_job_sources(items)
    return {"ok": True, "sources": items}


def set_job_source(name: str, on: bool) -> dict:
    items = job_sources()
    hit = False
    name = (name or "").strip()
    for s in items:
        if (s.get("name") or "").strip() == name \
                or (s.get("url") or "").strip() == name:
            s["on"] = bool(on)
            hit = True
    if not hit:
        return {"ok": False, "error": "no such source"}
    save_job_sources(items)
    return {"ok": True, "sources": items}


def remove_job_source(ident: str) -> dict:
    """Remove by name OR url.

    Matching on name alone broke for sources whose name IS a url — which is
    what you get when a url is pasted into the name box, or when the agent
    adds one. The url is the stable identifier, so both are accepted."""
    ident = (ident or "").strip()
    items = job_sources()
    keep = [s for s in items
            if (s.get("name") or "").strip() != ident
            and (s.get("url") or "").strip() != ident]
    if len(keep) == len(items):
        return {"ok": False,
                "error": f"no source matching '{ident[:80]}'"}
    save_job_sources(keep)
    return {"ok": True, "sources": keep, "removed": ident}


# --------------------------------------------------------------------------- #
#  Any site at all
#
#  Three boards is not "search anywhere". Most careers pages aren't RSS and
#  don't have an API — they're a list of links on an HTML page. This reads
#  those, so any URL can be a source: a company's careers page, a niche SA
#  board, a Greenhouse listing page, a filtered search result you've already
#  set up on someone else's site.
#
#  It works on structure rather than any one site's markup: a link is a job if
#  its address or its text looks like one, and isn't navigation.
# --------------------------------------------------------------------------- #
_JOBBY_HREF = re.compile(
    r"/(jobs?|careers?|vacanc\w*|position|opening|opportunit\w*|role|"
    r"listing|apply|posting)[/\-_?=]|"
    r"(greenhouse|lever\.co|workable|ashbyhq|smartrecruiters|recruitee|"
    r"teamtailor|bamboohr|myworkdayjobs|pnet|careers24|jobmail|careerjunction)",
    re.I)

# Words that mean "this is the site's furniture", not a role.
# A listing page links to CATEGORIES as well as to roles, and they read like
# job titles: "Data analyst jobs", "Power BI specialists", "Data analysts".
# Those were tracked as vacancies and drafted against — nine junk applications
# with no company and no advert behind them.
_CATEGORY_TITLE = re.compile(
    r"("
    r"\bjobs?\b\s*$|"                     # "Data analyst jobs"
    r"\bvacanc(y|ies)\b|\bcareers?\b|\bopportunit(y|ies)\b|"
    r"^\s*(all|more|browse|view|see|search|find|latest|top|new)\b|"
    r"\bin\s+[A-Z][a-z]+\s*$|"            # "Data Analyst in Gauteng"
    r"\b(near me|remote jobs|full[- ]time|part[- ]time)\b"
    r")", re.I)

# a bare plural with no company is a category ("Data analysts"), whereas a
# real advert is singular and usually carries seniority or a company
_PLURAL_ONLY = re.compile(
    r"^[A-Za-z][A-Za-z /&+.-]{2,40}(s|ists|ers|eers|ians)\s*$")


def _is_category_link(title: str, company: str = "") -> bool:
    t = " ".join((title or "").split())
    if not t:
        return True
    if _CATEGORY_TITLE.search(t):
        return True
    # "Data analysts" with nothing else attached
    if not company and _PLURAL_ONLY.match(t) and len(t.split()) <= 4:
        return True
    return False


_NAV_WORDS = {
    "home", "about", "about us", "contact", "contact us", "login", "log in",
    "sign in", "sign up", "register", "privacy", "terms", "cookies", "blog",
    "news", "press", "search", "menu", "back", "next", "previous", "more",
    "all jobs", "view all", "browse jobs", "careers", "jobs", "apply now",
    "learn more", "read more", "see all", "faq", "help", "support",
    "our team", "culture", "benefits", "life at", "students", "graduates",
}
_TITLE_HINT = re.compile(
    r"\b(engineer|developer|analyst|scientist|architect|consultant|manager|"
    r"lead|specialist|administrator|designer|officer|director|head of|"
    r"技術|data|bi\b|etl|sql|python|cloud|devops|product|project|qa|test)\b",
    re.I)


def _abs_url(href: str, base: str) -> str:
    from urllib.parse import urljoin
    try:
        return urljoin(base, href)
    except Exception:
        return href


def _parse_html_listings(text: str, base_url: str = "") -> list:
    """Pull job links out of an ordinary web page."""
    out, seen = [], set()
    for m in re.finditer(
            r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>",
            text or "", re.I | re.S):
        href, inner = m.group(1).strip(), m.group(2)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
        if not title or len(title) < 6 or len(title) > 140:
            continue
        low = title.lower().strip(" ›»→|-")
        if low in _NAV_WORDS or any(low == w for w in _NAV_WORDS):
            continue
        looks_jobby = bool(_JOBBY_HREF.search(href))
        reads_jobby = bool(_TITLE_HINT.search(title))
        if not (looks_jobby or reads_jobby):
            continue
        # a link that only *reads* like a role still needs a plausible target
        if reads_jobby and not looks_jobby and href.count("/") < 2:
            continue
        if _is_category_link(title):
            continue                     # a link to more listings, not a role
        url = _abs_url(href, base_url)
        if url in seen:
            continue
        seen.add(url)
        out.append({"title": title, "company": "", "url": url,
                    "location": "", "summary": "",
                    "apply_email": "", "source": _site_of(base_url)})
    return out


def _site_of(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return (urlparse(url).hostname or "").replace("www.", "") or "web"
    except Exception:
        return "web"


def search_url(url: str, limit: int = 40, use_browser: bool = False) -> dict:
    """Search one page you name, without adding it as a permanent source.

    This is the 'anywhere' part: paste a careers page, a board's filtered
    results, anything — and see what's on it."""
    # normalise BEFORE validating: people paste what the address bar shows,
    # which usually has no scheme, and rejecting that was pedantry
    url = normalise_url(url)
    if not url:
        return {"ok": False,
                "error": "That doesn't look like a web address — paste "
                         "something like careers24.com/jobs or the full "
                         "https:// link."}
    text, how, err = "", "direct", ""
    if not use_browser:
        try:
            text = _fetch_source(url)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
    found = _parse_html_listings(text, url) if text else []
    # Escalate on our own: a refusal, or a page that rendered nothing, is
    # exactly what the browser is for. Doing it automatically means the user
    # isn't asked to understand why a site failed.
    if use_browser or (not found and (err or not text)):
        try:
            text = fetch_with_browser(url)
            how = "browser"
            found = _parse_html_listings(text, url)
            err = ""
        except Exception as exc:
            if err:
                return {"ok": False,
                        "error": f"Couldn't read that page. Directly it "
                                 f"{_explain_fetch_error(err, url)} "
                                 f"Through the browser: "
                                 f"{type(exc).__name__}. "
                                 f"If Playwright isn't installed, run: "
                                 f"pip install playwright && playwright "
                                 f"install chromium"}
            return {"ok": False,
                    "error": f"Couldn't read that page — "
                             f"{_explain_fetch_error(str(exc), url)}"}
    if not found:
        # it might still be a feed someone pasted
        found = _parse_jobs_rss(text)
        for f in found:
            f["source"] = _site_of(url)
    cfg = search_config()
    have = {r.get("key") for r in roles()}
    kept, rejected = [], {}
    for j in found:
        ok, why = matches_search(j, cfg)
        if not ok:
            rejected[why] = rejected.get(why, 0) + 1
            continue
        j = dict(j)
        j["already_tracked"] = _slug(
            f"{j.get('company','')}-{j.get('title','')}") in have
        kept.append(j)
    return {"ok": True, "url": url, "site": _site_of(url), "how": how,
            # reading one page said nothing about which roles you already
            # had; it goes through the same marker as keyword search now
            "results": mark_tracked(kept[:limit]), "total": len(kept),
            "rejected": rejected,
            "note": ("Titles come from the page's links, so company and "
                     "location are often blank until you open the advert."
                     if kept else
                     "Nothing job-shaped found on that page. If the list "
                     "only appears after the page loads in a browser, this "
                     "can't see it.")}


# --------------------------------------------------------------------------- #
#  Reviewing what the guard held back
#
#  The guard flags claims the profile can't support and refuses to send them.
#  That is right, but on its own it is a locked door with no handle: "9 drafts
#  make a claim I couldn't source" tells you nothing about WHICH claims, and
#  the fix is nearly always that the claim is true and simply isn't written
#  down anywhere yet.
#
#  So: gather every flagged claim across every held draft, and let each one be
#  either confirmed into the profile (it's true, record it) or rejected (it
#  isn't, redraft without it). Confirming is not loosening the guard — it is
#  giving the guard the evidence it was asking for.
# --------------------------------------------------------------------------- #
def held_claims() -> dict:
    """Every unsourced claim still awaiting your decision.

    Dismissed claims are left out: you've already answered. They keep their
    draft held — the wording still makes the claim — but the fix for those is
    a redraft, not another question."""
    banned = {b.lower() for b in banned_claims()}
    claims, held = {}, []
    for r in roles():
        # the same classifier the pipeline counts with — this pairing is what
        # produced "15 held" beside an empty tab
        if role_state(r)["bucket"] not in ("held", "needs_redraft"):
            continue
        d = r.get("draft") or {}
        c = d.get("check") or {}
        # carry the draft and its problems: the tab listed CLAIMS and never
        # the drafts themselves, so a draft held for a reason that names no
        # claim showed as nothing at all
        _d = r.get("draft") or {}
        _c = _d.get("check") or {}
        held.append({"key": r["key"], "title": r.get("title", ""),
                     "company": r.get("company", ""),
                     "subject": _d.get("subject", ""),
                     "body": (_d.get("body") or "")[:4000],
                     "problems": [p.get("detail", "")
                                  for p in (_c.get("problems") or [])],
                     "needs_redraft": bool(_d.get("needs_redraft")),
                     "redraft_reason": _d.get("redraft_reason", "")})
        for p in c.get("problems") or []:
            term = _claim_term(p)
            if not term:
                continue
            # the proper-noun check and the tool-lexicon check flag the same
            # word with different casing; showing "Databricks" and
            # "databricks" as two things to decide is just noise
            key = term.lower()
            if key in banned:
                continue                  # already decided against
            entry = claims.setdefault(key, {
                "term": term, "kind": p.get("kind", ""), "roles": [],
                "detail": p.get("detail", ""),
                "context": p.get("context", "")})
            if r.get("title") and r["title"] not in entry["roles"]:
                entry["roles"].append(r["title"])
            if p.get("context") and not entry["context"]:
                entry["context"] = p["context"]
            # prefer the capitalised spelling for display
            if term and term[:1].isupper():
                entry["term"] = term
    ordered = sorted(claims.values(), key=lambda c: (-len(c["roles"]),
                                                     c["term"].lower()))
    # With an empty profile NOTHING can be sourced, so every draft is held and
    # the list becomes dozens of terms to confirm one at a time. That is the
    # wrong instruction: the fix is to fill the profile once, not to approve
    # each word individually.
    p = profile()
    have = sum(len(_as_list(p.get(f))) for f in
               ("skills", "technologies", "employers", "achievements"))
    profile_empty = have < 3
    needs_redraft = [h for h in held if h["key"] in _redraft_keys(banned)]
    for h in held:
        h["needs_redraft"] = h["key"] in {n["key"] for n in needs_redraft}
    drafted_ok = sum(1 for r in roles()
                     if r.get("stage") == "drafted"
                     and ((r.get("draft") or {}).get("check") or {}
                          ).get("ok") is not False)
    return {"held": held, "drafted_ready": drafted_ok,
            "claims": [] if profile_empty else ordered,
            "count": len(held),
            "distinct": 0 if profile_empty else len(ordered),
            "profile_empty": profile_empty,
            "would_be_claims": len(ordered) if profile_empty else 0,
            "needs_redraft": needs_redraft,
            "banned": sorted(banned_claims())}


def _redraft_keys(banned: set) -> set:
    """Drafts that still mention something you said you don't claim. No
    amount of confirming will clear these; the wording has to change."""
    out = set()
    for r in roles():
        d = r.get("draft") or {}
        c = d.get("check") or {}
        if r.get("stage") != "drafted" or c.get("ok") is not False:
            continue
        terms = {_claim_term(p).lower() for p in (c.get("problems") or [])}
        terms.discard("")
        if terms and terms & banned:
            out.add(r["key"])
    return out


def _claim_term(p: dict) -> str:
    """The thing being claimed, pulled out of the message shown to the user."""
    # The quotes below are the curly ones the messages actually use.
    # Written as \u escapes inside a RAW string they matched a literal
    # backslash instead, so every term came back empty -- which is why
    # the tab said "9 held" and "0 claims to decide" at the same time.
    m = re.search("[“\"']([^”\"']+)[”\"']",
                  p.get("detail", "") or "")
    return m.group(1).strip() if m else ""


CLAIM_TARGETS = ("technologies", "skills", "achievements", "employers")


def confirm_claim(term: str, where: str = "technologies") -> dict:
    """Record a claim as true, then re-check every held draft.

    This is the honest half of the guard: most flags are things you have
    genuinely done that were never written into the profile."""
    term = (term or "").strip()
    if not term:
        return {"ok": False, "error": "nothing to confirm"}
    if where not in CLAIM_TARGETS:
        return {"ok": False,
                "error": f"where must be one of: {', '.join(CLAIM_TARGETS)}"}
    p = profile()
    items = _as_list(p.get(where))
    if not any(term.lower() == str(x).lower() for x in items):
        items.append(term)
        p[where] = items
        save_profile(p)
    _audit("claim-confirmed", f"{term} -> {where}")
    return {"ok": True, "profile_field": where, "term": term,
            **recheck_drafts()}


def recheck_drafts() -> dict:
    """Re-run the fabrication check on every drafted role.

    Without this, adding something to the profile would change nothing until
    each draft was regenerated — which costs an engine call per role for a
    check that is entirely local."""
    cleared, still_held = 0, 0
    for r in roles():
        d = r.get("draft") or {}
        if r.get("stage") != "drafted" or not d.get("body"):
            continue
        fresh = check_draft(d["body"], r)
        was = ((d.get("check") or {}).get("ok"))
        d["check"] = fresh
        update_role(r["key"], draft=d)
        if fresh["ok"] and was is False:
            cleared += 1
        elif not fresh["ok"]:
            still_held += 1
    return {"cleared": cleared, "still_held": still_held}


def dismiss_claim(term: str) -> dict:
    """Mark a claim as one you do NOT want to make, so drafts stop using it."""
    term = (term or "").strip()
    if not term:
        return {"ok": False, "error": "nothing to dismiss"}
    cfg = load_config()
    banned = [b for b in _as_list(cfg.get("banned_claims"))]
    if term.lower() not in [b.lower() for b in banned]:
        banned.append(term)
    cfg["banned_claims"] = banned
    save_config(cfg)
    affected = sorted(_redraft_keys({term.lower()}))
    for key in affected:
        r = get_role(key)
        d = (r or {}).get("draft") or {}
        if d:
            d["needs_redraft"] = True
            d["redraft_reason"] = (f"mentions “{term}”, which you said you "
                                   f"don't claim")
            update_role(key, draft=d)
    _audit("claim-dismissed", f"{term}; {len(affected)} draft(s) to rewrite")
    return {"ok": True, "banned": banned, "affected": affected,
            "note": (f"{len(affected)} draft(s) still say it — redraft them "
                     f"and it won't be used again."
                     if affected else
                     "Noted. Future drafts won't use it.")}


def banned_claims() -> list:
    return _as_list(load_config().get("banned_claims"))


# --------------------------------------------------------------------------- #
#  Removing roles
#
#  The subtlety: deleting a role you've decided against is pointless if the
#  next scan finds it again tomorrow. So removal remembers the key, and
#  discovery skips it. That memory is a short list of keys, not the role —
#  nothing of the advert is kept.
#
#  Removal that ISN'T a rejection (tidying up duplicates, clearing out old
#  closed roles) can opt out of being remembered.
# --------------------------------------------------------------------------- #
def ignored_keys() -> list:
    return _as_list(load_config().get("ignored_roles"))


def _remember_ignored(keys) -> None:
    cfg = load_config()
    have = {k.lower() for k in _as_list(cfg.get("ignored_roles"))}
    out = _as_list(cfg.get("ignored_roles"))
    for k in keys:
        if k and k.lower() not in have:
            out.append(k)
            have.add(k.lower())
    cfg["ignored_roles"] = out[-500:]        # bounded
    save_config(cfg)


def unignore(key: str) -> dict:
    cfg = load_config()
    keep = [k for k in _as_list(cfg.get("ignored_roles"))
            if k.lower() != (key or "").lower()]
    cfg["ignored_roles"] = keep
    save_config(cfg)
    return {"ok": True, "ignored": keep}


@_locked
def remove_role(key: str, forget: bool = True) -> dict:
    """Remove one tracked role. `forget` keeps it from coming back."""
    key = (key or "").strip()
    rs = roles()
    keep = [r for r in rs if r.get("key") != key]
    if len(keep) == len(rs):
        return {"ok": False, "error": "no such role"}
    gone = next(r for r in rs if r.get("key") == key)
    save_roles(keep)
    if forget:
        _remember_ignored([key])
    _audit("role-removed", f"{gone.get('title', key)}"
                           f"{' (won\'t return)' if forget else ''}")
    return {"ok": True, "removed": key, "title": gone.get("title", ""),
            "forgotten": bool(forget), "remaining": len(keep)}


@_locked
def remove_roles(keys: list, forget: bool = True) -> dict:
    wanted = {str(k).strip() for k in (keys or []) if str(k).strip()}
    rs = roles()
    keep = [r for r in rs if r.get("key") not in wanted]
    removed = len(rs) - len(keep)
    if not removed:
        return {"ok": False, "error": "none of those are tracked"}
    save_roles(keep)
    if forget:
        _remember_ignored(wanted)
    _audit("roles-removed", f"{removed} role(s)")
    return {"ok": True, "removed": removed, "remaining": len(keep)}


@_locked
def prune_junk(forget: bool = False) -> dict:
    """Remove roles that were never vacancies.

    Category links were tracked as jobs before the extractor could tell them
    apart, and each one generated a draft addressed to nobody. This clears
    them out; `forget` is off by default because these aren't decisions about
    a role, they're a mistake being corrected."""
    rs = roles()
    junk = [r for r in rs if not _looks_like_a_real_role(r)]
    if not junk:
        return {"ok": False, "error": "nothing junk-looking is tracked"}
    keep = [r for r in rs if r not in junk]
    save_roles(keep)
    if forget:
        _remember_ignored([r["key"] for r in junk])
    _audit("prune-junk", f"{len(junk)} non-vacancy entr(ies) removed")
    return {"ok": True, "removed": len(junk), "remaining": len(keep),
            "titles": [r.get("title", "") for r in junk][:20]}


@_locked
def clear_roles(stage: str = "", never_scored: bool = False,
                forget: bool = False) -> dict:
    """Bulk tidy-up. Defaults to NOT remembering, because clearing out old
    closed roles is housekeeping, not a decision about the role."""
    rs = roles()
    def drop(r):
        if stage and r.get("stage") != stage:
            return False
        if never_scored and (r.get("fit") or {}).get("score") is not None:
            return False
        if not stage and not never_scored:
            return False                  # refuse to wipe everything blindly
        return True
    doomed = [r for r in rs if drop(r)]
    if not doomed:
        return {"ok": False, "error": "nothing matched that"}
    keep = [r for r in rs if r not in doomed]
    save_roles(keep)
    if forget:
        _remember_ignored([r["key"] for r in doomed])
    _audit("roles-cleared", f"{len(doomed)} role(s), stage={stage or 'any'}")
    return {"ok": True, "removed": len(doomed), "remaining": len(keep)}


# =========================================================================== #
#  Running without you
#
#  The pieces were all here and none of them joined up: you had to type search
#  terms, press scan, press score, press draft, and set up a schedule by hand.
#  And every role got an engine call to score it — including ones a free local
#  keyword check would have rejected in a millisecond.
# =========================================================================== #
def derive_queries(p: dict = None) -> list:
    """Search terms from the profile, when you haven't set any.

    Asking someone to type search terms they already wrote into their profile
    is make-work, and an empty query list means the scan falls back to a loose
    profile match that pulls in noise."""
    p = p if p is not None else profile()
    out = []
    for t in _as_list(p.get("target_roles")):
        t = t.strip()
        if t and t.lower() not in [o.lower() for o in out]:
            out.append(t)
    if not out:
        # no stated targets: use the strongest tools as a proxy
        for s in (_as_list(p.get("technologies"))
                  + _as_list(p.get("skills")))[:4]:
            s = s.strip()
            if s and s.lower() not in [o.lower() for o in out]:
                out.append(s)
    return out[:6]


def _norm_title(s: str) -> str:
    """Strip the decoration boards add, so the same role from three sites
    collapses to one entry rather than three applications."""
    t = (s or "").lower()
    t = re.sub(r"\((remote|contract|hybrid|onsite|f/m/d|m/f/d)[^)]*\)", " ", t)
    t = re.sub(r"\b(senior|snr|jnr|junior|lead|principal|staff|iii|ii|i|"
               r"remote|contract|permanent|full[- ]time|part[- ]time)\b",
               " ", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())


@_locked
def dedupe_roles(forget: bool = False) -> dict:
    """Collapse the same vacancy listed on several boards.

    Keeps the one with an application address if there is one, since that is
    the copy the email path can actually use."""
    rs = roles()
    groups = {}
    for r in rs:
        company = (r.get("company") or "").strip().lower()
        # with no company the title says nothing about which vacancy it is:
        # every "Data Engineer" on a listings page had the same key, and a
        # page of thirty roles was merged down to one per title. Without a
        # company, only the same advert is the same role.
        key = (_norm_title(r.get("title", "")),
               company or "url:" + normalise_url(_as_text(r.get("url"))))
        if not key[0] or key[1] == "url:":
            continue
        groups.setdefault(key, []).append(r)
    dropped = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda r: (bool(r.get("apply_email")),
                                  r.get("stage") != "found",
                                  len(str(r.get("summary") or ""))),
                   reverse=True)
        for extra in items[1:]:
            dropped.append(extra)
    if not dropped:
        return {"ok": False, "error": "no duplicates found"}
    keep = [r for r in rs if r not in dropped]
    save_roles(keep)
    if forget:
        _remember_ignored([r["key"] for r in dropped])
    _audit("dedupe", f"{len(dropped)} duplicate listing(s) merged")
    return {"ok": True, "removed": len(dropped), "remaining": len(keep),
            "titles": [r.get("title", "") for r in dropped][:10]}


def pipeline() -> dict:
    """Where everything is, and where it has stopped.

    "70 held, 0 sent" is only useful if you can see WHICH step is blocking.
    """
    # counts come from role_state, so this cannot disagree with the tabs
    c = counts()
    stages = {
        "found": c["found"], "scored": c["scored"],
        "drafted": c["drafted"] + c["no_address"],
        "held": c["held"] + c["needs_redraft"],
        "applied": c["applied"], "responded": c["waiting"],
        "interview": 0, "offer": 0,
        "closed": c["closed"] + c["expired"] + c["screened"],
    }
    total = sum(c.values())
    # the blockage is the first stage holding more than half of everything
    block = ""
    if total >= 4:
        for name in ("found", "scored", "held", "drafted"):
            if stages[name] >= max(3, total * 0.5):
                block = name
                break
    reasons = {
        "found": "nothing has been scored yet — run auto-apply, or score one "
                 "to see how it reads",
        "scored": "scored but not drafted — drafting needs a profile it can "
                  "quote from",
        "held": "drafts are held because they claim things your profile "
                "can't support — Held drafts shows which",
        "drafted": "drafted and waiting: either no application address, or "
                   "auto-apply is off",
    }
    return {"stages": stages, "total": total, "blocked_at": block,
            "why": reasons.get(block, ""), "counts": c,
            "sent": c["applied"] + c["waiting"]}


# =========================================================================== #
#  Adverts that have closed
#
#  A vacancy is a perishable thing. Nothing here noticed, so a role found in
#  July sat in the list looking exactly like one found this morning, and an
#  application could be drafted for something that closed weeks ago.
#
#  The distinction that matters: a page SAYING it is closed is evidence, and a
#  page that will not load is not. Boards block automated readers all the time
#  — treating a 403 as "expired" would quietly delete live roles, which is a
#  worse fault than leaving a dead one on the list.
# =========================================================================== #
STALE_DAYS = 45          # after this, an unapplied advert is probably gone

_CLOSED_PHRASES = (
    "no longer accepting applications",
    "no longer available", "this job has closed", "position has been filled",
    "applications are closed", "advert has expired", "job has expired",
    "vacancy has closed", "closed for applications", "posting has expired",
    "we are no longer hiring", "this role is no longer",
    "the position is filled", "job not found", "vacancy no longer",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def mark_closed(key: str, reason: str, expired: bool = False) -> dict:
    """Close a role and record WHEN and WHY.

    A stage of "closed" with no date told you nothing three weeks later."""
    r = get_role(key)
    if r is None:
        return {"ok": False, "error": "no such role"}
    update_role(key, stage="closed", closed_at=_now_iso(),
                closed_reason=reason[:200], expired=bool(expired))
    _audit("closed", f"{r.get('title', key)}: {reason[:120]}")
    return {"ok": True, "key": key, "closed_at": _now_iso(),
            "reason": reason, "expired": bool(expired)}


ADVERT_CHARS = 4000        # enough for the requirements; the payloads stay small
ENRICH_BELOW = 400         # an advert shorter than this is read from its page
NEVER_READ = ("linkedin.com", "indeed.", "glassdoor.", "seek.com")


def _jsonld_postings(soup) -> list:
    """schema.org JobPosting blocks — what job pages publish for Google's job
    search: the full description, dates, pay and the employer, as data."""
    out = []
    for tag in soup.find_all("script", type=lambda t: t and "ld+json" in t.lower()):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except Exception:
            continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                t = x.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    out.append(x)
                stack.extend(v for k, v in x.items() if k == "@graph")
    return out


def _pay_of(jp: dict) -> str:
    bs = jp.get("baseSalary") or {}
    if not isinstance(bs, dict):
        return ""
    v = bs.get("value") or {}
    cur = bs.get("currency") or ""
    if isinstance(v, dict):
        lo, hi = v.get("minValue"), v.get("maxValue")
        amt = v.get("value")
        unit = str(v.get("unitText") or "").lower()
        def f(n):
            try:
                return f"{float(n):,.0f}"
            except Exception:
                return str(n)
        span = (f"{f(lo)}–{f(hi)}" if lo and hi and lo != hi else f(lo or hi or amt)) if (lo or hi or amt) else ""
        return " ".join(x for x in (cur, span, f"per {unit}" if unit else "") if x).strip()
    return ""


def read_advert(html: str) -> dict:
    """{text, posted_at, closes_at, salary, company} from an advert page."""
    from bs4 import BeautifulSoup
    import html as _h
    soup = BeautifulSoup(html or "", "html.parser")
    meta = {"posted_at": "", "closes_at": "", "salary": "", "company": ""}
    for jp in _jsonld_postings(soup):
        org = jp.get("hiringOrganization") or {}
        # the dates, pay and employer are worth keeping even when the block's
        # description is too thin to use: a five-month-old "talent pool"
        # advert lost its date with its description, and looked brand new
        meta = {"posted_at": _posted(jp.get("datePosted")),
                "closes_at": _posted(jp.get("validThrough")),
                "salary": _pay_of(jp),
                "company": (org.get("name") if isinstance(org, dict) else "") or ""}
        thin = _h.unescape(_strip_html(str(jp.get("description") or "")))
        if len(thin) > 80:
            return {"text": thin[:ADVERT_CHARS], **meta, "from": "jobposting"}
        break
    else:
        thin = ""
    for t in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "svg"]):
        t.decompose()
    main = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"}) or soup.body or soup
    text = " ".join(x for x in (thin, " ".join(main.get_text(" ").split())) if x)
    return {"text": text[:ADVERT_CHARS], **meta, "from": "page"}


def enrich_role(role: dict) -> dict:
    """Read the advert itself for a role that arrived with little or no text
    (a listings page gives a title and a link, an RSS feed a line or two).

    Scored on a title alone, a role was a guess; with no address in its
    snippet, it went to the portal path even when the advert said "email
    your CV to…". What the page says is kept: the text, its posting and
    closing dates, its pay, and an application address if it has one. An
    advert whose closing date has passed is closed. A page that can't be
    read changes nothing."""
    url = str((role or {}).get("url") or "")
    if not url or any(h in url.lower() for h in NEVER_READ):
        return {"state": "skipped"}
    try:
        html = _fetch_source(url)
    except Exception as exc:
        return {"state": "unreadable", "why": _explain_fetch_error(f"{type(exc).__name__}: {exc}", url)}
    a = read_advert(html)
    text = a["text"]
    fields = {"enriched_at": _iso()}
    if len(text) > len(_as_text(role.get("description"))):
        fields["description"] = text
        if not role.get("summary"):
            fields["summary"] = text[:600]
    if a["posted_at"] and not role.get("posted_at"):
        fields["posted_at"] = a["posted_at"]
    if a["salary"] and not role.get("salary"):
        fields["salary"] = a["salary"]
    if a["company"] and not _as_text(role.get("company")).strip():
        fields["company"] = a["company"][:120]
    mail = _apply_email(text)
    if mail and not role.get("apply_email"):
        fields["apply_email"] = mail
    update_role(role["key"], **fields)
    if a["closes_at"] and a["closes_at"] < datetime.now(timezone.utc).strftime("%Y-%m-%d"):
        mark_closed(role["key"], f"the advert closed on {a['closes_at']}", expired=True)
        return {"state": "closed", "fields": sorted(fields)}
    return {"state": "read", "fields": sorted(fields), "from": a["from"]}


def enrich_roles(limit: int = 40, workers: int = 4) -> dict:
    """enrich_role for the roles that need it most: new, unscored, short."""
    todo = [r for r in roles()
            if r.get("stage") == "found" and not (r.get("fit") or {}).get("score")
            and not r.get("enriched_at") and r.get("url")
            and len(_as_text(r.get("description")) or _as_text(r.get("summary"))) < ENRICH_BELOW]
    todo = todo[:max(0, int(limit))]
    out = {"read": 0, "closed": 0, "unreadable": 0, "emails": 0}
    if not todo:
        return out
    from concurrent.futures import ThreadPoolExecutor
    had = {r["key"]: bool(r.get("apply_email")) for r in todo}
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="jobs-read") as pool:
        res = list(pool.map(enrich_role, todo))
    for r, x in zip(todo, res):
        st = x.get("state")
        if st in ("read", "closed"):
            out["read"] += 1
        if st == "closed":
            out["closed"] += 1
        if st == "unreadable":
            out["unreadable"] += 1
            update_role(r["key"], enriched_at=_iso())   # tried; not again every run
        if st == "read" and not had[r["key"]] and "apply_email" in (x.get("fields") or []):
            out["emails"] += 1
    return out


def check_expiry(role: dict) -> dict:
    """Is this advert still open?

    Three answers, not two. "Closed" needs the page to say so. "Unknown" is
    what a blocked or unreachable page gets — and unknown must never close a
    role, or a board having a bad afternoon deletes your shortlist.
    """
    url = (role or {}).get("url") or ""
    if not url:
        return {"state": "unknown", "why": "no advert link to check"}
    try:
        text = _fetch_source(url)
    except Exception as exc:
        e = f"{type(exc).__name__}: {exc}".lower()
        if "404" in e or "not found" in e:
            return {"state": "closed",
                    "why": "the advert page is gone (404)"}
        return {"state": "unknown",
                "why": f"couldn't read the page — {_explain_fetch_error(e)}"}
    low = " ".join(_strip_html(text).lower().split())
    for phrase in _CLOSED_PHRASES:
        if phrase in low:
            return {"state": "closed", "why": f"the page says “{phrase}”"}
    if len(low) < 200:
        # an empty shell is usually a redirect to a "job not found" page, but
        # it is also what a JavaScript board looks like — so, unknown
        return {"state": "unknown",
                "why": "the page came back nearly empty"}
    return {"state": "open", "why": ""}


def days_listed(role: dict) -> float:
    """Days since the advert went up: its own posting date, else the day it
    was found. This read "added_at", which nothing ever wrote, so every role
    was 0 days old: "freshest first" ordered nothing, and no role was ever
    labelled stale."""
    for k in ("posted_at", "added_at", "found_at"):
        v = str((role or {}).get(k) or "")
        if not v:
            continue
        for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d"):
            try:
                when = datetime.strptime(v if "UTC" in fmt else v[:10], fmt)
                when = when.replace(tzinfo=timezone.utc)
                return max(0.0, (datetime.now(timezone.utc) - when).total_seconds() / 86400)
            except Exception:
                continue
    return 0.0


def looks_stale(role: dict) -> bool:
    """Old, and never acted on. Not proof, which is why it's only a label."""
    if role.get("stage") in ("applied", "responded", "interview", "offer",
                             "closed"):
        return False
    return days_listed(role) >= STALE_DAYS


def sweep_expired(limit: int = 12, include_applied: bool = False) -> dict:
    """Check the oldest open adverts and close the ones that say they're shut."""
    cands = [r for r in roles()
             if r.get("stage") not in ("closed", "offer")
             and (include_applied or r.get("stage") != "applied")
             and r.get("url")]
    cands.sort(key=lambda r: -days_listed(r))
    closed, unknown, still_open = [], [], 0
    for r in cands[:max(1, limit)]:
        res = check_expiry(r)
        if res["state"] == "closed":
            mark_closed(r["key"], res["why"], expired=True)
            closed.append({"title": r.get("title", ""), "why": res["why"]})
        elif res["state"] == "unknown":
            unknown.append({"title": r.get("title", ""), "why": res["why"]})
        else:
            still_open += 1
    return {"ok": True, "checked": len(cands[:max(1, limit)]),
            "closed": closed, "unknown": unknown, "still_open": still_open,
            "note": ("A page that wouldn't load is left alone — being blocked "
                     "is not the same as being closed.")}


# =========================================================================== #
#  What the next run would do
#
#  The auto-apply panel showed the gates and a Run button, which tells you the
#  rules but not the consequence. Deciding whether to turn rehearsal off is a
#  decision about THIS list, not about the settings in the abstract — so work
#  it out and show it, before anything is spent.
#
#  Entirely local: the screening is keyword work, the gates are arithmetic,
#  and where an engine call would be needed the answer is "it would score
#  this one", not a guess at the result.
# =========================================================================== #
def auto_preview() -> dict:
    """A dry walk through the cycle. No engine calls, no sending."""
    cfg = auto_config()
    p = profile()
    floor = int(cfg.get("min_score", 75) or 75)
    cap = int(cfg.get("daily_cap", 25) or 25)
    sent_today = _sent_today()
    room = max(0, cap - sent_today)

    would_send, would_hold, needs_score, screened, no_address, expired = \
        [], [], [], [], [], []
    # grouped by the same buckets the pipeline counts, so the preview and
    # the numbers above it can't tell different stories
    for r in roles():
        s = role_state(r, cfg)
        b, title = s["bucket"], s["title"]
        # The one question that decides a send is the gate the run itself
        # uses. Classifying by bucket alone let the preview say "nothing
        # clears the gates" about a role a run would have sent — two answers
        # to the same question.
        if not _gate(r, cfg) and s["bucket"] not in ("applied", "closed",
                                                     "expired", "waiting"):
            would_send.append({"title": title, "company": r.get("company", ""),
                               "fit": (r.get("fit") or {}).get("score"),
                               "to": r.get("apply_email", "")})
            continue
        if b == "expired":
            expired.append(title)
        elif b in ("closed", "applied", "waiting"):
            continue
        elif b == "found":
            ps = prescreen(r, p)
            if ps["pass"]:
                needs_score.append(title)
            else:
                screened.append({"title": title, "why": ps["why"]})
        elif b in ("screened",):
            screened.append({"title": title, "why": s["why"]})
        elif b in ("held", "needs_redraft"):
            would_hold.append({"title": title, "why": s["why"]})
        elif b == "no_address":
            no_address.append(title)
        elif b == "scored":
            needs_score.append(title)
        elif b == "drafted":
            would_send.append({"title": title, "company": s["company"],
                               "fit": s["fit"], "to": s["apply_email"]})

    capped = would_send[room:] if room < len(would_send) else []
    # One sentence saying what would happen. The window read a "sentence" key
    # that was never returned and fell back to "Auto-apply is off." — which
    # it then displayed while auto-apply was on.
    n = len(would_send[:room])
    if not cfg.get("enabled"):
        sentence = ("Auto-apply is off. Nothing runs on its own — this is what "
                    "it would do if you turned it on.")
    elif cfg.get("dry_run", True) is not False:
        sentence = (f"Rehearsing: {n} application(s) would be drafted and "
                    f"nothing would be sent.")
    elif n:
        sentence = f"{n} application(s) would be sent on the next run."
    else:
        sentence = ("Auto-apply is on, but nothing clears the gates right "
                    "now — see what's stopping it above.")
    return {
        "sentence": sentence,
        "enabled": bool(cfg.get("enabled")),
        "dry_run": cfg.get("dry_run", True) is not False,
        "min_score": floor, "daily_cap": cap,
        "sent_today": sent_today, "room_today": room,
        "would_send": would_send[:room], "capped": [c["title"] for c in capped],
        "needs_scoring": needs_score, "would_hold": would_hold,
        "screened_out": screened, "no_address": no_address,
        "expired": expired,
        "follow_ups": [f.get("title", "") for f in (follow_ups() or [])],
        "summary": _preview_sentence(len(would_send[:room]), len(needs_score),
                                     len(would_hold), len(no_address),
                                     len(screened), cfg),
    }


def _preview_sentence(send, score, hold, noaddr, screened, cfg) -> str:
    """One line that answers 'so what happens if I press it'."""
    if not cfg.get("enabled"):
        return ("Auto-apply is off. Nothing runs on its own — this is what it "
                "would do if you turned it on.")
    bits = []
    if send:
        bits.append(f"send {send}"
                    + (" (rehearsal, so nothing leaves)"
                       if cfg.get("dry_run", True) is not False else ""))
    if score:
        bits.append(f"score {score}")
    if hold:
        bits.append(f"hold {hold} back")
    if noaddr:
        bits.append(f"skip {noaddr} with no address")
    if screened:
        bits.append(f"ignore {screened} that don't match")
    return ("The next run would " + ", ".join(bits) + "."
            if bits else "There's nothing for the next run to do.")


def _sent_today() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = 0
    for r in roles():
        when = str(r.get("applied_at") or "")
        if when.startswith(today):
            n += 1
    return n


def recent_runs(limit: int = 8) -> list:
    """What the unattended runs have actually done."""
    out = []
    try:
        from . import audit
        for e in audit.recent(400):
            if e.get("kind") != "jobscout":
                continue
            if e.get("name") not in ("auto-apply", "discover", "alert-ingest"):
                continue
            out.append({"at": e.get("iso", ""), "what": e.get("name", ""),
                        "detail": (e.get("summary") or "")[:160]})
            if len(out) >= limit:
                break
    except Exception:
        pass
    return out


# =========================================================================== #
#  One answer to "what state is this role in"
#
#  This has been the same bug three times: the Held tab said 9 while the list
#  showed nothing; the dashboard reported "needs checking" for drafts whose
#  claims were already decided; the tab showed 15 held beside an empty panel.
#  Each time a COUNT was computed one way and a LIST another, and each fix
#  corrected one instance of a fault that could recur anywhere.
#
#  Four callers classify roles — the pipeline, held drafts, the auto-apply
#  preview, and the tracked list. Rather than keep them in step by discipline,
#  they read this. A disagreement stops being a bug that can be written.
# =========================================================================== #
BUCKETS = ("found", "screened", "scored", "drafted", "held", "needs_redraft",
           "no_address", "applied", "waiting", "closed", "expired")


def _st(bucket: str, why: str, r: dict) -> dict:
    return {"bucket": bucket, "why": why, "key": r.get("key", ""),
            "title": r.get("title", ""), "company": r.get("company", ""),
            "fit": (r.get("fit") or {}).get("score"),
            "apply_email": r.get("apply_email", ""),
            "can_send": bucket == "drafted"}


def role_state(r: dict, cfg: dict = None) -> dict:
    """The single answer. Everything that classifies a role calls this."""
    cfg = cfg if cfg is not None else auto_config()
    stage = r.get("stage", "found")
    fit = (r.get("fit") or {}).get("score")
    draft = r.get("draft") or {}
    check = draft.get("check") or {}
    floor = int(cfg.get("min_score", 75) or 75)

    if r.get("expired"):
        return _st("expired", "the advert has closed", r)
    if stage == "closed":
        return _st("closed", r.get("closed_reason", "closed"), r)
    if stage in ("responded", "interview", "offer"):
        return _st("waiting", f"they replied — {stage}", r)
    if stage == "applied":
        return _st("applied", "sent, waiting on them", r)
    if stage == "drafted":
        if draft.get("needs_redraft"):
            return _st("needs_redraft",
                       draft.get("redraft_reason", "needs rewriting"), r)
        if check.get("ok") is False:
            return _st("held", "the draft claims something your profile "
                               "can't support", r)
        if not r.get("apply_email"):
            return _st("no_address", "portal only — apply from Tracked", r)
        return _st("drafted", "ready to send", r)
    if fit is not None:
        if fit < floor:
            return _st("screened", f"fit {fit} is below your {floor}", r)
        return _st("scored", "scored, not drafted yet", r)
    return _st("found", "not scored yet", r)


def states(cfg: dict = None) -> list:
    cfg = cfg if cfg is not None else auto_config()
    return [role_state(r, cfg) for r in roles()]


def counts() -> dict:
    """Bucket totals. The one place a number comes from."""
    out = {b: 0 for b in BUCKETS}
    for s in states():
        out[s["bucket"]] = out.get(s["bucket"], 0) + 1
    return out


# =========================================================================== #
#  The archive, and applying by hand
#
#  Closed and expired roles cluttered the list they were no longer part of.
#  Deleting them would lose the record — you want to know you saw a role, and
#  what became of it, when the same company advertises again. So they move
#  rather than vanish, and can come back.
#
#  And the pipeline assumed it did the applying. Most applications are still
#  made by a person: a portal form, an email you wrote yourself, a referral.
#  Without a way to say so, a role you'd already applied to sat looking
#  untouched, and follow-ups never started.
# =========================================================================== #
def _archive_path() -> Path:
    return _dir() / "archive.json"


def archived() -> list:
    try:
        data = json.loads(_archive_path().read_text("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_archive(items: list) -> None:
    _archive_path().write_text(json.dumps(items, indent=2), "utf-8")


@_locked
def archive_closed(also_applied_before_days: int = 0) -> dict:
    """Move closed and expired roles out of the working list.

    They keep everything — the draft, the score, why they closed — so the
    record survives. `also_applied_before_days` sweeps old applications you
    never heard back about, which is the other thing that silts up a list."""
    keep, moved = [], []
    cutoff_days = int(also_applied_before_days or 0)
    for r in roles():
        st = role_state(r)["bucket"]
        # days since you applied, not since the advert went up: an advert a
        # month old that you applied to yesterday hasn't had its 30 days
        since = r.get("sent_at") or r.get("applied_at") or ""
        waited = days_listed({"added_at": since}) if since else days_listed(r)
        old_application = (cutoff_days and st == "applied"
                           and waited >= cutoff_days)
        if st in ("closed", "expired") or old_application:
            moved.append({**r, "archived_at": _now_iso(),
                          "archived_because": ("no reply after "
                                               f"{cutoff_days} days"
                                               if old_application
                                               else role_state(r)["why"])})
        else:
            keep.append(r)
    if not moved:
        return {"ok": False, "error": "nothing closed or expired to archive"}
    save_roles(keep)
    _save_archive(archived() + moved)
    _audit("archive", f"{len(moved)} role(s) archived")
    return {"ok": True, "moved": len(moved), "remaining": len(keep),
            "titles": [m.get("title", "") for m in moved][:20],
            "note": "They're kept in the archive — nothing was deleted."}


@_locked
def unarchive(key: str) -> dict:
    """Bring one back into the working list."""
    items = archived()
    hit = next((a for a in items if a.get("key") == key), None)
    if hit is None:
        return {"ok": False, "error": "not in the archive"}
    _save_archive([a for a in items if a.get("key") != key])
    r = {k: v for k, v in hit.items()
         if k not in ("archived_at", "archived_because")}
    r["stage"] = "found"
    r.pop("expired", None)
    r.pop("closed_at", None)
    r.pop("closed_reason", None)
    save_roles(roles() + [r])
    _audit("unarchive", r.get("title", key))
    return {"ok": True, "title": r.get("title", ""),
            "note": "Back in the list, as if newly found."}


def archive_summary() -> dict:
    items = archived()
    by = {}
    for a in items:
        why = (a.get("archived_because") or "closed")[:60]
        by[why] = by.get(why, 0) + 1
    return {"count": len(items), "by_reason": by,
            "roles": [{"key": a.get("key", ""), "title": a.get("title", ""),
                       "company": a.get("company", ""),
                       "when": a.get("archived_at", ""),
                       "why": a.get("archived_because", ""),
                       "was_applied": a.get("stage") == "applied"}
                      for a in items[-80:]][::-1]}


def mark_applied(key: str, how: str = "by hand", note: str = "") -> dict:
    """Record that an application went in — however it went in.

    The pipeline assumed it did the sending. Most applications are made by a
    person, and without this the role sat looking untouched: no follow-up
    clock, no count against the day, and a real chance of applying twice."""
    r = get_role(key)
    if r is None:
        return {"ok": False, "error": "no such role"}
    if role_state(r)["bucket"] in ("applied", "waiting"):
        return {"ok": False,
                "error": f"“{r.get('title', '')}” is already marked applied "
                         f"— nothing sent twice."}
    when = _now_iso()
    update_role(key, stage="applied", applied_at=when, applied_how=how,
                applied_note=note[:300])
    _audit("applied", f"{r.get('title', key)} — {how}")
    return {"ok": True, "title": r.get("title", ""), "at": when, "how": how,
            "note": ("Recorded. Follow-up is due in a week, and it won't be "
                     "applied to again.")}
