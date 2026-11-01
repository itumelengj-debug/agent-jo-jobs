"""Agent Jo Jobs — the live check: your real boards, your engine, your mailbox.

    python tools/live_check.py                 # boards + engine
    python tools/live_check.py --email         # + one test application, to YOU
    python tools/live_check.py --inbox         # + read your inbox (read-only)
    python tools/live_check.py --all           # all of the above

The test suite proves the logic against stand-ins. This proves the outside
world is reachable from your machine with your settings: each source you've
added answers and lists roles, your engine scores and drafts a real advert,
your mail account accepts a login and delivers.

It changes nothing it doesn't have to:
  * boards are only read — no role is added, no source's status is updated;
  * the engine is asked twice (one score, one draft) about one live role;
  * --email sends ONE message, to your own sending address and never to an
    employer, with the CV an application would carry, so you can see exactly
    what an employer receives;
  * --inbox logs in and reads the last week, marking nothing as read.
Run it from the app folder with the app's Python (.venv). Your data folder is
the usual one (~/.agent_jo_jobs, or AGENT_JOBS_HOME).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK, BAD, WARN = "  ✓", "  ✗", "  !"
_failed = []


def say(mark: str, text: str) -> None:
    print(f"{mark} {text}")
    if mark == BAD:
        _failed.append(text)


def boards(limit: int, use_browser: bool) -> list:
    from agent import jobscout as J
    from agent import trust
    print("\nYour sources, read live")
    srcs = [s for s in J.job_sources() if s.get("on", True)]
    if not srcs:
        say(WARN, "No sources added yet, so these suggested ones are tried instead "
                  "(nothing is added). Add yours under Sources.")
        srcs = [dict(s) for s in J.SUGGESTED_SOURCES]
    found = []
    for s in srcs[:limit]:
        name, url, kind = s.get("name", "?"), s.get("url", ""), s.get("kind", "rss")
        if kind == "browser" and not use_browser:
            say(WARN, f"{name}: a browser source — skipped (add --browser to include it)")
            continue
        t0 = time.time()
        try:
            text = J.fetch_for_kind(url, kind)
            J._CURRENT_SOURCE_URL["url"] = url
            jobs = [j for j in J._PARSERS.get(kind, J._parse_jobs_rss)(text) if j.get("title")]
        except Exception as exc:
            say(BAD, f"{name}: {J._explain_fetch_error(f'{type(exc).__name__}: {exc}', url)[:200]}")
            continue
        secs = time.time() - t0
        if not jobs:
            say(BAD, f"{name}: answered in {secs:.1f}s but listed no roles"
                     + (" — it sent a web page; try the 'browser' kind" if J.looks_like_html(text) else ""))
            continue
        dated = sorted((j.get("posted_at") for j in jobs if j.get("posted_at")), reverse=True)
        mail = sum(1 for j in jobs if j.get("apply_email"))
        flags = [trust.assess(j)["verdict"] for j in jobs]
        say(OK, f"{name}: {len(jobs)} roles in {secs:.1f}s"
                + (f", newest posted {dated[0]}" if dated else ", no posting dates")
                + f", {mail} with an email address"
                + (f", {flags.count('scam')} look like scams" if "scam" in flags else "")
                + (f", {flags.count('likely_ghost')} likely ghost jobs" if "likely_ghost" in flags else ""))
        for j in jobs:
            j.setdefault("source", name)
        found += jobs
    return found


def engine(found: list) -> None:
    from agent import jobscout as J
    print("\nYour engine, on a live advert")
    try:
        import jobs.server as srv
        brain = srv.get_brain()
    except Exception as exc:
        say(BAD, f"No engine: {getattr(exc, 'message', exc)} {getattr(exc, 'fix', '')}".strip())
        return
    say(OK, f"engine: {type(brain).__name__}"
            + (f" ({getattr(brain, 'model', '')})" if getattr(brain, "model", "") else ""))
    ok, why = J.profile_ready()
    if not ok:
        say(BAD, why)
        return
    p = J.profile()
    pick = None
    for j in found:
        if J.matches_search(j, {**J.search_config(), "_use_profile_targets": True})[0] \
                and J._matches_profile(j, p):
            pick = j
            break
    pick = pick or (found[0] if found else
                    {"title": (J._as_list(p.get("target_roles")) or ["Data Engineer"])[0],
                     "company": "Example Co", "summary": "A role like the ones you want."})
    print(f"     role: {pick.get('title')} at {pick.get('company') or '?'}")
    t0 = time.time()
    try:
        s = J._engine_json(brain, json.dumps({"profile": p, "role": pick}, default=str)[:12000],
                           J._SCORE_SYSTEM)
        score = J._parse_score(s.get("score", s.get("fit")))
        if score is None:
            say(BAD, f"scored, but the reply had no score: {json.dumps(s)[:160]}")
        else:
            say(OK, f"scored it {score}/100 in {time.time() - t0:.1f}s ({s.get('verdict', '')})")
    except Exception as exc:
        say(BAD, f"scoring failed: {J._explain_engine_error(f'{type(exc).__name__}: {exc}')}")
        return
    t0 = time.time()
    try:
        d = J._engine_json(brain, json.dumps({"PROFILE": p, "ROLE": pick, "VOICE": p.get("voice_notes", "")},
                                             default=str)[:14000], J._DRAFT_SYSTEM + J._banned_clause())
        body = J._as_text(d.get("body")).strip()
        if not body:
            say(BAD, "the draft came back empty")
            return
        chk = J.check_draft(body, pick)
        q = J._quality(body, pick)
        say(OK, f"drafted a letter in {time.time() - t0:.1f}s: {len(body.split())} words, "
                f"quality {q.get('score', '?')}/100, "
                + ("claims check clean" if chk["ok"] else
                   f"claims check flags {len(chk['problems'])} (a run redrafts these once)"))
        print("     ---\n     " + body[:500].replace("\n", "\n     ") + ("…" if len(body) > 500 else "")
              + "\n     ---")
    except Exception as exc:
        say(BAD, f"drafting failed: {J._explain_engine_error(f'{type(exc).__name__}: {exc}')}")


def email_self() -> None:
    from agent import jobscout as J, outreach
    print("\nYour mail account: one test application, to yourself")
    cfg = outreach.load_config()
    if not outreach.is_configured():
        say(BAD, "Email isn't set up — Results → Email: your SMTP server, address and app password.")
        return
    me = cfg.get("from_addr", "")
    if not cfg.get("enabled"):
        say(BAD, "Email sending is switched off in the app; switch it on, then run this again.")
        return
    cvf = J.cv_file_for({"key": "", "title": "Live check", "company": ""}, J.profile())
    files = [cvf["path"]] if cvf.get("path") else []
    if files:
        say(OK, f"CV to attach: {Path(files[0]).name} ({cvf['kind']})")
    else:
        say(WARN, f"no CV to attach: {cvf.get('error')}")
    body = ("This is Agent Jo Jobs' live check. It is the shape of an emailed application: "
            "this text stands where the letter goes, and the attachment is the CV an "
            "employer would receive.\n\nIf it arrived, sending works from this machine.")
    t0 = time.time()
    res = outreach.send(me, "Agent Jo Jobs — live check", body, attachments=files)
    if res.get("ok"):
        say(OK, f"sent to {me} in {time.time() - t0:.1f}s"
                + (f" with {', '.join(res.get('attached') or [])}" if res.get("attached") else "")
                + " — check that inbox (and its spam folder)")
    else:
        say(BAD, f"not sent: {res.get('error')}")


def inbox_read() -> None:
    from agent import inbox
    print("\nYour inbox, read-only")
    try:
        r = inbox.from_imap(since_days=7, limit=20)
    except Exception as exc:
        say(BAD, f"{type(exc).__name__}: {exc}")
        return
    if r.get("error"):
        say(BAD, r["error"])
        return
    msgs = r.get("messages") or r.get("found") or []
    say(OK, f"logged in and read {len(msgs)} message(s) from the last week; nothing was marked read")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--email", action="store_true", help="send one test application to yourself")
    ap.add_argument("--inbox", action="store_true", help="log in to your inbox and read (read-only)")
    ap.add_argument("--all", action="store_true", help="boards, engine, email and inbox")
    ap.add_argument("--browser", action="store_true", help="include 'browser' sources")
    ap.add_argument("--sources", type=int, default=12, help="most sources to read (default 12)")
    a = ap.parse_args()
    from agent import config
    print(f"Agent Jo Jobs — live check (data: {config.AGENT_HOME})")
    found = boards(a.sources, a.browser)
    engine(found)
    if a.email or a.all:
        email_self()
    if a.inbox or a.all:
        inbox_read()
    print()
    if _failed:
        print(f"{len(_failed)} thing(s) didn't work — each says why above.")
        return 1
    print("Everything checked works from this machine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
