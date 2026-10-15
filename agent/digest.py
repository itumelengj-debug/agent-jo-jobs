"""A weekly email to you: what went out, who answered, what's waiting on you.

The app now runs on its own — finds, drafts, applies, reads replies — which
makes it easy to stop looking. Once a week, on the day you choose, this sends
one short email to your own address:

  * the week in numbers: applications sent, replies, interviews, offers;
  * who answered, and how (interview, offer, turn-down);
  * what went out, and to whom;
  * what's waiting on you: questions only you can answer, forms filled for you
    to finish, drafts held for a claim;
  * what the results so far say works — only where the numbers support it.

It's sent with the email login you set up, to you only. A week with nothing
to say sends nothing. It goes out from the full cycle (the daily 07:00 run)
on the chosen weekday, at most once in six days, or whenever you press Send
now.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def settings() -> dict:
    from . import jobscout, outreach
    mail = outreach.load_config()
    return {"enabled": False, "to": mail.get("from_addr") or mail.get("username") or "",
            "weekday": 0, "last_sent": "",
            **(jobscout.load_config().get("digest") or {})}


def save_settings(s: dict) -> dict:
    from . import jobscout
    cfg = jobscout.load_config()
    keep = {k: v for k, v in (s or {}).items() if k in ("enabled", "to", "weekday")}
    if "weekday" in keep:
        keep["weekday"] = max(0, min(6, int(keep["weekday"])))
    cfg["digest"] = {**settings(), **keep}
    jobscout.save_config(cfg)
    return cfg["digest"]


def _within(stamp: str, days: int) -> bool:
    from . import jobscout
    return bool(stamp) and jobscout._hours_since(stamp) <= days * 24


def build(days: int = 7) -> dict:
    """The digest as {subject, text, empty}. Nothing is sent."""
    from . import jobscout, answerbank, outcomes
    roles = jobscout.roles()
    sent = [r for r in roles if _within(r.get("sent_at", ""), days) and not r.get("sent_dry_run")]
    replies = []
    for r in roles:
        for rep in r.get("replies") or []:
            if _within(rep.get("at", ""), days) and rep.get("kind") != "ack":
                replies.append((r, rep))
    waiting_q = answerbank.open_questions()
    prepared = [r for r in roles if (r.get("portal") or {}).get("state") in
                ("filled", "needs_answer", "unknown_form", "needs_login", "needs_captcha")
                and r.get("stage") in ("found", "drafted")]
    held = [r for r in roles if r.get("stage") in ("found", "drafted")
            and ((r.get("draft") or {}).get("check") or {}).get("ok") is False]
    kinds = {}
    for _, rep in replies:
        kinds[rep["kind"]] = kinds.get(rep["kind"], 0) + 1

    def who(r):
        return f"{r.get('title', '')} @ {r.get('company', '')}".strip(" @")

    out = []
    head = (f"{len(sent)} application(s) sent, {len(replies)} repl(y/ies)"
            + (f" — {kinds['interview']} interview(s)" if kinds.get("interview") else "")
            + (f", {kinds['offer']} offer(s)" if kinds.get("offer") else ""))
    out.append(f"Your week in the job search: {head}.")
    from . import interviews
    coming = interviews.upcoming(roles)
    if coming:
        out.append("\nINTERVIEWS COMING UP")
        for x in coming[:6]:
            out.append(f"  • {x['at']} — {x['title']} @ {x['company']}"
                       + (f"  {x['link']}" if x.get("link") else ""))
    from . import contacts
    knows = [r for r in roles if r.get("know") and r.get("stage") not in ("closed",) and not r.get("sent_at")]
    if knows:
        out.append("\nYOU KNOW SOMEONE THERE")
        for r in knows[:6]:
            k = r["know"][0]
            out.append(f"  • {who(r)} — {k['name']} ({k['kind']}, last heard {k['last']})")
    back = contacts.get_back_to()
    if back:
        out.append("\nPEOPLE TO GET BACK TO")
        for c in back[:6]:
            out.append(f"  • {c.get('name') or c['email']} — {', '.join(c.get('companies') or [])} "
                       f"({c['days']} days quiet)")
    if replies:
        out.append("\nWHO ANSWERED")
        label = {"interview": "interview", "offer": "OFFER", "rejection": "turned down",
                 "reply": "replied"}
        for r, rep in sorted(replies, key=lambda x: x[1].get("at", ""), reverse=True)[:15]:
            out.append(f"  • {who(r)} — {label.get(rep['kind'], rep['kind'])} "
                       f"({rep.get('at', '')[:10]})")
    if sent:
        out.append("\nWHAT WENT OUT")
        for r in sorted(sent, key=lambda r: r.get("sent_at", ""), reverse=True)[:20]:
            out.append(f"  • {who(r)} — {r.get('sent_at', '')[:10]}")
    if waiting_q or prepared or held:
        out.append("\nWAITING ON YOU")
        if waiting_q:
            out.append(f"  • {len(waiting_q)} question(s) only you can answer (Answers → Waiting on you):")
            for q in waiting_q[:5]:
                n = len(q.get("roles") or [])
                out.append(f"      – {q['question']}" + (f"  [holding up {n}]" if n else ""))
        if prepared:
            out.append(f"  • {len(prepared)} form(s) filled in for you to finish: "
                       + "; ".join(who(r) for r in prepared[:5]))
        if held:
            out.append(f"  • {len(held)} draft(s) held for a claim your profile can't back (Drafts)")
    try:
        lessons = outcomes.findings()[:3]
    except Exception:
        lessons = []
    if lessons:
        out.append("\nWHAT THE RESULTS SAY SO FAR")
        for f in lessons:
            line = str(f.get("what") or "")[:220]
            if f.get("do"):
                line += f" {f['do']}"[:160]
            out.append("  • " + line)
    out.append("\n— Agent Jo Jobs. Change or stop this email under Results → Weekly digest.")
    empty = not (sent or replies or waiting_q or prepared or held or coming or knows or back)
    day = datetime.now(timezone.utc).strftime("%d %b")
    return {"subject": f"Job search, week to {day}: {head}", "text": "\n".join(out),
            "empty": empty}


def due(now: datetime | None = None) -> bool:
    from . import jobscout
    s = settings()
    now = now or datetime.now(timezone.utc)
    if not s.get("enabled") or not s.get("to"):
        return False
    if now.weekday() != int(s.get("weekday") or 0):
        return False
    return not s.get("last_sent") or jobscout._hours_since(s["last_sent"]) >= 6 * 24


def send(force: bool = False) -> dict:
    """Send the digest now (force) or only if it's due. Never to anyone but you."""
    from . import jobscout, outreach
    s = settings()
    if not force and not due():
        return {"ok": True, "sent": False, "why": "not due"}
    if not s.get("to"):
        return {"ok": False, "error": "No address to send it to — set up email first."}
    d = build()
    if d["empty"] and not force:
        # nothing to say this week: say nothing, and don't ask again till next
        cfg = jobscout.load_config()
        cfg["digest"] = {**settings(), "last_sent": jobscout._iso()}
        jobscout.save_config(cfg)
        return {"ok": True, "sent": False, "why": "nothing happened this week"}
    res = outreach.send(s["to"], d["subject"], d["text"])
    if res.get("ok"):
        cfg = jobscout.load_config()
        cfg.setdefault("digest", settings())["last_sent"] = jobscout._iso()
        jobscout.save_config(cfg)
        jobscout._audit("digest", f"weekly digest sent to {s['to']}")
        return {"ok": True, "sent": True, "to": s["to"], "subject": d["subject"]}
    return {"ok": False, "error": res.get("error", "the email didn't send")}


def next_day_name() -> str:
    return DAYS[int(settings().get("weekday") or 0)]
