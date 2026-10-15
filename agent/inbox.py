"""Replies to your applications, read from your inbox, so the app learns what works.

Results counted replies, interviews and offers from each role's stage — but
the stage only moved when you moved it, so mostly it didn't, and the numbers
said every source and every draft did equally nothing. This reads the
replies:

  * from your mailbox over IMAP, with the login you set up for sending
    (imap.<your provider> is worked out from the smtp.<…> address; override
    it in Results if yours differs), or from .eml files saved into
    jobscout/replies/ for anyone who'd rather not connect it;
  * read-only: the mailbox is opened for reading and messages are fetched
    with PEEK, so nothing is marked read, moved or deleted, and nothing is
    sent;
  * each message is matched to an application you made — the address you
    applied to, the company's name, the role's title, "Re:" your subject —
    and only a clear match counts;
  * and sorted: an interview invitation, an offer, a turn-down, a real reply,
    or just "we've received your application" (noted, but not counted as a
    response — it would make every source look like it gets answers).

A role's stage only moves forward (applied → responded → interview → offer);
a turn-down closes it with the reason. Each message is handled once.
"""
from __future__ import annotations

import email
import json
import re
import time
from datetime import datetime, timedelta, timezone
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from . import config

_ORDER = {"applied": 0, "responded": 1, "interview": 2, "offer": 3}
FREE_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com",
             "live.com", "yahoo.com", "icloud.com", "me.com", "proton.me",
             "protonmail.com", "aol.com", "mail.com", "gmx.com"}
# the hiring systems send on a company's behalf from their own domains
ATS_MAIL = ("greenhouse.io", "greenhouse-mail.io", "lever.co", "hire.lever.co",
            "ashbyhq.com", "workday.com", "myworkday.com", "smartrecruiters.com",
            "bamboohr.com", "workable.com", "recruitee.com", "teamtailor.com",
            "icims.com", "successfactors.com", "taleo.net")

_RULES = [
    ("offer", re.compile(r"offer of employment|pleased to (offer|extend)|"
                         r"formal offer|employment offer|offer letter", re.I)),
    ("interview", re.compile(r"\binterview\b|schedule (a|an) (call|chat|meeting)|"
                             r"your availability|next (round|stage|step)|"
                             r"book a (time|slot)|calendly\.com|would like to (meet|speak|chat)|"
                             r"assessment (link|invitation)|technical (test|assessment)", re.I)),
    ("rejection", re.compile(r"unfortunately|regret to (inform|advise)|not (be )?"
                             r"(moving|progressing|proceeding) forward|"
                             r"(decided|chosen) (not )?to (proceed|move forward) with other|"
                             r"other candidates|unsuccessful|position has been filled|"
                             r"not (been )?selected|will not be taking your application", re.I)),
    ("ack", re.compile(r"(received|receipt of) your application|thank(s| you) for "
                       r"(applying|your application|your interest)|application (has been|was) "
                       r"(received|submitted)|we('ll| will) (review|be in touch)", re.I)),
]


def _dir() -> Path:
    d = config.AGENT_HOME / "jobscout"
    d.mkdir(parents=True, exist_ok=True)
    return d


def replies_dir() -> Path:
    d = _dir() / "replies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _seen_path() -> Path:
    return _dir() / "inbox_seen.json"


def _seen() -> dict:
    try:
        return json.loads(_seen_path().read_text("utf-8"))
    except Exception:
        return {}


def _save_seen(d: dict) -> None:
    # bounded: the newest few thousand ids are enough to never double-count
    items = sorted(d.items(), key=lambda kv: kv[1].get("at", ""))[-4000:]
    _seen_path().write_text(json.dumps(dict(items), indent=0), "utf-8")


def settings() -> dict:
    from . import jobscout
    return {"enabled": False, "imap_host": "", "imap_port": 993,
            "folder": "INBOX", "days": 60,
            **(jobscout.load_config().get("inbox") or {})}


def save_settings(s: dict) -> dict:
    from . import jobscout
    cfg = jobscout.load_config()
    cfg["inbox"] = {**settings(), **{k: v for k, v in (s or {}).items()
                                     if k in ("enabled", "imap_host", "imap_port",
                                              "folder", "days")}}
    jobscout.save_config(cfg)
    return cfg["inbox"]


# --------------------------------------------------------------------------- #
#  reading messages
# --------------------------------------------------------------------------- #
def _text_of(msg) -> str:
    plain = html = ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        try:
            ctype = part.get_content_type()
            if ctype == "text/plain" and not plain:
                plain = part.get_content()
            elif ctype == "text/html" and not html:
                html = part.get_content()
        except Exception:
            continue
    if not plain and html:
        plain = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        plain = re.sub(r"<[^>]+>", " ", plain)
    # the quoted application under a reply would match its own words
    plain = re.split(r"\n(?:>|On .{5,80} wrote:|-----Original Message-----|From: )", str(plain))[0]
    return " ".join(plain.split())[:6000]


def parse(raw: bytes) -> dict:
    msg = email.message_from_bytes(raw, policy=policy.default)
    name, addr = parseaddr(str(msg.get("From", "")))
    try:
        when = parsedate_to_datetime(str(msg.get("Date"))).astimezone(timezone.utc)
        at = when.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        at = ""
    mid = str(msg.get("Message-ID", "")).strip() or f"{addr}|{msg.get('Subject', '')}|{at}"
    return {"id": mid, "from_name": name, "from": addr.lower(),
            "domain": addr.lower().rsplit("@", 1)[-1] if "@" in addr else "",
            "subject": str(msg.get("Subject", "")), "at": at, "text": _text_of(msg)}


def from_folder() -> list:
    out = []
    for f in sorted(replies_dir().glob("*.eml")):
        try:
            out.append(parse(f.read_bytes()))
        except Exception:
            continue
    return out


def imap_host_for(smtp_host: str) -> str:
    h = (smtp_host or "").strip().lower()
    if not h:
        return ""
    if h in ("smtp.office365.com", "smtp-mail.outlook.com"):
        return "outlook.office365.com"
    return re.sub(r"^(smtp|mail|smtps)\.", "imap.", h) if re.match(r"^(smtp|smtps)\.", h) else h


def from_imap(since_days: int = 60, limit: int = 300) -> dict:
    """Recent messages from the mailbox, read-only. {"messages": [...]} or
    {"error": "..."} saying what to fix."""
    import imaplib
    from . import outreach
    mail = outreach.load_config()
    s = settings()
    host = s.get("imap_host") or imap_host_for(mail.get("host", ""))
    user, pw = mail.get("username") or mail.get("from_addr", ""), mail.get("password", "")
    if not host or not user or not pw:
        return {"error": "Set up email sending first (it uses the same login), "
                         "or save replies as .eml files in " + str(replies_dir())}
    since = (datetime.now(timezone.utc) - timedelta(days=int(since_days or 60))).strftime("%d-%b-%Y")
    try:
        box = imaplib.IMAP4_SSL(host, int(s.get("imap_port") or 993), timeout=30)
    except TypeError:                                   # Python < 3.9
        box = imaplib.IMAP4_SSL(host, int(s.get("imap_port") or 993))
    except Exception as exc:
        return {"error": f"Couldn't reach {host}: {type(exc).__name__}. If your "
                         f"provider's IMAP address is different, set it in Results."}
    try:
        try:
            box.login(user, pw)
        except Exception:
            return {"error": "The mailbox refused the login. Gmail and Outlook need "
                             "an app password, and IMAP turned on in their settings."}
        box.select(s.get("folder") or "INBOX", readonly=True)
        typ, data = box.search(None, "SINCE", since)
        ids = (data[0].split() if data and data[0] else [])[-limit:]
        out = []
        for i in ids:
            typ, parts = box.fetch(i, "(BODY.PEEK[])")
            for p in parts or []:
                if isinstance(p, tuple) and len(p) > 1:
                    try:
                        out.append(parse(p[1]))
                    except Exception:
                        pass
        return {"messages": out, "host": host}
    finally:
        try:
            box.logout()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  matching and sorting
# --------------------------------------------------------------------------- #
def classify(m: dict) -> str:
    text = f"{m.get('subject', '')} {m.get('text', '')}"
    for kind, rx in _RULES:
        if rx.search(text):
            return kind
    return "reply"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _company_tokens(company: str) -> list:
    stop = {"the", "ltd", "limited", "pty", "inc", "llc", "plc", "group", "co",
            "company", "holdings", "sa", "gmbh", "bv", "and"}
    return [w for w in _norm(company).split() if len(w) > 2 and w not in stop]


def match(m: dict, roles: list):
    """(role, score, why) for the application this message answers, or None."""
    subj, body = _norm(m.get("subject")), _norm(m.get("text"))
    frm = _norm(f"{m.get('from_name', '')} {m.get('domain', '')}")
    best, second = None, 0
    for r in roles:
        score, why = 0, []
        email_to = str(r.get("apply_email") or "").lower()
        to_dom = email_to.rsplit("@", 1)[-1] if "@" in email_to else ""
        if email_to and m.get("from") == email_to:
            score += 5; why.append("from the address you applied to")
        elif to_dom and to_dom not in FREE_MAIL and m.get("domain", "").endswith(to_dom):
            score += 4; why.append("from the company's email domain")
        toks = _company_tokens(r.get("company"))
        if toks and all(t in frm for t in toks):
            score += 3; why.append("sent by the company")
        elif toks and all(t in f" {subj} {body} " for t in toks):
            score += 2; why.append("names the company")
        title = _norm(r.get("title"))
        if title and (title in subj or title in body):
            score += 2; why.append("names the role")
        sent_subj = _norm(((r.get("draft") or {}).get("subject")) or "")
        if sent_subj and len(sent_subj) > 8 and sent_subj in subj:
            score += 4; why.append("a reply to your email")
        if any(m.get("domain", "").endswith(a) for a in ATS_MAIL) and score:
            score += 1
        if score > (best[1] if best else 0):
            second = best[1] if best else 0
            best = (r, score, why)
        elif score > second:
            second = score
    # clear, and clearly this one: two companies tied is a guess
    if not best or best[1] < 4 or best[1] == second:
        return None
    return best


def check(messages: list = None, *, source: str = "") -> dict:
    """Match new replies to applications and move their stages. Never sends,
    never changes the mailbox. Returns what it found."""
    from . import jobscout
    got = {"messages": [], "host": ""}
    if messages is None:
        msgs = from_folder()
        s = settings()
        if s.get("enabled"):
            got = from_imap(int(s.get("days") or 60))
            if got.get("error") and not msgs:
                return {"ok": False, "error": got["error"]}
            msgs += got.get("messages") or []
    else:
        msgs = messages
    applied = [r for r in jobscout.roles()
               if r.get("stage") in ("applied", "responded", "interview", "offer")
               or (r.get("stage") == "closed" and r.get("sent_at"))]
    seen = _seen()
    found, new = [], 0
    for m in msgs:
        if not m.get("id") or m["id"] in seen:
            continue
        new += 1
        hit = match(m, applied)
        kind = classify(m) if hit else ""
        seen[m["id"]] = {"at": m.get("at") or jobscout._iso(),
                         "role": hit[0]["key"] if hit else "", "kind": kind}
        if not hit:
            continue
        r, score, why = hit
        # the role as it is now: an earlier message in this same batch may
        # have changed it, and writing back the copy read before the loop
        # threw that message's reply away
        r = jobscout.get_role(r["key"]) or r
        stage = r.get("stage", "applied")
        moved = ""
        note = f"{kind} by email: “{m.get('subject', '')[:120]}”"
        target = {"offer": "offer", "interview": "interview", "reply": "responded"}.get(kind)
        if target and _ORDER.get(target, -1) > _ORDER.get(stage, -1) and stage != "closed":
            jobscout.set_stage(r["key"], target, note)
            moved = target
        elif kind == "rejection" and stage in ("applied", "responded", "interview"):
            jobscout.set_stage(r["key"], "closed", note)
            moved = "closed"
        extra = {}
        if kind == "interview" and not r.get("interview_at_by_hand"):
            from . import interviews
            body = (m.get("subject") or "") + "\n" + (m.get("text") or "")
            t = interviews.find_time(body)
            if t:
                extra.update(interview_at=t["at"], interview_said=t["said"],
                             interview_tz_note=t["tz_note"])
            link = interviews.find_link(body)
            if link:
                extra["interview_link"] = link
        replies = list(r.get("replies") or [])
        replies.append({"at": m.get("at"), "kind": kind, "from": m.get("from"),
                        "from_name": (m.get("from_name") or "")[:120],
                        "subject": m.get("subject", "")[:200], "why": why})
        jobscout.update_role(r["key"], replies=replies[-20:],
                             **extra,
                             **({"responded_at": m.get("at")} if kind in ("reply", "interview", "offer") and not r.get("responded_at") else {}))
        found.append({"role": r["title"], "company": r.get("company", ""), "key": r["key"],
                      "kind": kind, "subject": m.get("subject", ""), "at": m.get("at"),
                      "moved_to": moved, "why": why,
                      **({"interview_at": extra["interview_at"]} if extra.get("interview_at") else {})})
    _save_seen(seen)
    jobscout._audit("inbox", f"{new} new message(s), {len(found)} about your applications")
    return {"ok": True, "checked": new, "found": found, "host": got.get("host", ""),
            "warning": got.get("error", ""), "at": jobscout._iso()}
