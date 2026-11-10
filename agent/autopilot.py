"""Autopilot — give it your CV, and it runs the job search.

Every piece existed and joining them up was left to the person: paste the CV,
fill in what the profile was still missing, work out which job titles to
search for, find boards and check each one, set where you can work, switch
auto-apply on, pick a schedule, press Run. Eight steps across five screens
before the first role appeared, and a wrong guess at any of them (no target
roles; no boards) meant a run that found nothing and said so politely.

`setup` does all of it from the CV, in order, and says what it did at each
step. Nothing is sent by it: the level stays where you put it, and a new
install stays in rehearsal until you have read what it would send.

`status` is the one answer the window and the phone show: is it running,
when next, what did it do, and what — if anything — is waiting for you.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Asked of the engine once, with the CV: what jobs to look for. The profile
# extraction copies facts; this is the one place a judgement is asked for,
# and it is about titles to search, never about what you have done.
_TARGETS_SYSTEM = (
    "You read a candidate's CV and say which job titles they should search for. "
    "Return ONLY raw JSON: {\"target_roles\": [str], \"education\": [str], "
    "\"country\": str}.\n"
    "target_roles: 5 to 8 job titles as employers write them in adverts, most "
    "fitting first. Start with the title they hold now and the one a step up. "
    "Then the other names the same work goes by (\"BI Developer\" and "
    "\"Business Intelligence Developer\"; \"Data Engineer\" and \"Analytics "
    "Engineer\"), and titles built on their main tools when adverts use them "
    "(\"Azure Data Engineer\"). Only titles their CV shows they could do now. "
    "No seniority words unless the CV earns them. Short: two to four words "
    "each.\n"
    "education: each qualification as the CV states it (\"BSc Computer "
    "Science, University of X, 2015\"). Copy; never add.\n"
    "country: the country they live in, from the CV's address or most recent "
    "job. '' if the CV doesn't say.")


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _titles_from_cv_text(cv: str) -> list:
    """Job titles the CV itself states, for when no engine can be asked:
    the lines that read "Title — Employer" or "Title at Employer"."""
    import re
    out = []
    head = re.compile(
        r"^\s*([A-Z][A-Za-z/&+ .-]{3,48}?(?:Engineer|Developer|Analyst|Scientist|Manager|Architect|"
        r"Designer|Consultant|Administrator|Specialist|Lead|Officer|Accountant|Technician|Director|"
        r"Coordinator|Programmer|Tester|Nurse|Teacher|Writer|Recruiter))\s*(?:[—–|@,-]|\bat\b|$)", re.M)
    for m in head.finditer(cv or ""):
        t = " ".join(m.group(1).split())
        t = re.sub(r"^(Senior|Junior|Lead|Principal|Staff|Snr|Jnr|Sr|Jr)\.?\s+", "", t)
        if t.lower() not in [x.lower() for x in out]:
            out.append(t)
    return out[:6]


def setup(cv_text: str = "", name: str = "", brain=None, model=None, memory=None,
          scheduler=None, every_hours: int = 4, boards_wanted: int = 8,
          start: bool = True) -> dict:
    """From a CV to a running job search. Returns {'ok', 'steps': [{what,
    ok, detail}], 'ready', 'needs'}: every step that ran and what it did,
    and anything still only you can supply."""
    from . import jobscout, cvstore, boards, geo
    steps, needs = [], []

    def step(what, ok, detail=""):
        steps.append({"what": what, "ok": bool(ok), "detail": str(detail)[:300]})
        return ok

    # 1. the CV
    if cv_text and cv_text.strip():
        res = cvstore.save(cv_text, name)
        if not step("Read your CV", res.get("ok"),
                    res.get("error") or f"{len(cv_text.split())} words, kept and indexed"):
            return {"ok": False, "steps": steps, "error": res.get("error", "")}
    elif not cvstore.text():
        step("Read your CV", False, "No CV yet: paste or upload one.")
        return {"ok": False, "steps": steps, "error": "Autopilot starts from your CV."}
    cv = cvstore.text()

    # 2. the profile, from what the CV says
    if brain is not None:
        r = cvstore.to_profile(brain, model=model)
        step("Built your profile from it", r.get("ok"),
             r.get("error") or ("filled in " + ", ".join(r.get("filled") or [])
                                if r.get("filled") else "your profile already had everything in it"))
    else:
        step("Built your profile from it", False,
             "No AI engine is set up yet, so only what could be read directly was filled in.")
        needs.append({"what": "An AI engine", "where": "engines",
                      "why": "It scores each role and writes each letter. A free local "
                             "model (Ollama) works, or add a key for a cloud engine."})
    p = jobscout.profile()

    # 3. which jobs to look for, the qualifications, where you live
    targets, education, country = list(p.get("target_roles") or []), list(p.get("education") or []), ""
    if brain is not None and (not targets or not education):
        try:
            d = jobscout._engine_json(brain, cv[:20000], _TARGETS_SYSTEM, model)
            if not targets:
                targets = [str(t).strip() for t in (d.get("target_roles") or []) if str(t).strip()][:8]
            if not education:
                education = [str(t).strip() for t in (d.get("education") or []) if str(t).strip()][:6]
            country = str(d.get("country") or "").strip()
        except Exception as exc:
            step("Worked out which jobs to look for", False,
                 jobscout._explain_engine_error(f"{type(exc).__name__}: {exc}"))
    if not targets:
        targets = _titles_from_cv_text(cv)
    changes = {}
    if targets and targets != list(p.get("target_roles") or []):
        changes["target_roles"] = targets
    if education and not p.get("education"):
        changes["education"] = education
    # where you can work: remote, and the country you live in. Never wider
    # than that by itself: more is yours to add.
    home = geo.read_place(str(p.get("location") or ""))["countries"] \
        or geo.read_place(country)["countries"]
    if not p.get("location") and country:
        changes["location"] = country
    if not p.get("locations_ok"):
        changes["locations_ok"] = ["Remote"] + sorted(geo.country_name(c) for c in home)
    if changes:
        p = jobscout.save_profile(changes)
    if targets:
        step("Worked out which jobs to look for", True, ", ".join(targets))
    else:
        step("Worked out which jobs to look for", False,
             "Couldn't tell from the CV. Add the job titles you want under Your profile.")
        needs.append({"what": "The job titles you want", "where": "profile",
                      "why": "They are what every board is searched for."})
    where = [x for x in (p.get("locations_ok") or [])]
    step("Set where you can work", bool(where), ", ".join(where) if where else
         "Couldn't tell where you live. Add it under Your profile.")

    # 4. boards that suit you, each one checked before it's added
    have = len([s for s in jobscout.job_sources() if s.get("on", True)])
    if targets:
        try:
            r = boards.auto_add(p, limit=max(0, boards_wanted - have)) if have < boards_wanted \
                else {"ok": True, "added": []}
            names = [a["name"] for a in r.get("added") or []]
            total = have + len(names)
            step("Found job boards that suit you", total > 0,
                 (f"added {', '.join(names)}" if names else "kept the boards you already had")
                 + (f"; {len(r.get('rejected') or [])} didn't answer and were left out"
                    if r.get("rejected") else ""))
            if not total:
                needs.append({"what": "A job board that works", "where": "sources",
                              "why": "None of the suggested boards could be read from this "
                                     "computer just now. Check your connection, or add one."})
        except Exception as exc:
            step("Found job boards that suit you", False, f"{type(exc).__name__}: {exc}")

    # 5. what applications need from you that a CV can't give
    missing = [label for key, label in (("full_name", "your name"), ("email", "your email address"),
                                        ("phone", "a phone number"))
               if not str(p.get(key) or "").strip()]
    if missing:
        needs.append({"what": "Contact details: " + ", ".join(missing), "where": "profile",
                      "why": "Every application form asks for them."})
    try:
        from . import outreach
        if not outreach.is_configured():
            needs.append({"what": "Your email account (optional)", "where": "results",
                          "why": "Only for adverts that ask for applications by email, and "
                                 "for reading replies. Applications through company forms "
                                 "don't need it."})
    except Exception:
        pass

    # 6. on, on a schedule, and the first run started
    cfg = jobscout.auto_config()
    jobscout.save_auto_config({"enabled": True})
    on = False
    if memory is not None and scheduler is not None:
        try:
            on = jobscout.set_schedule(memory, scheduler, True, every_hours)
        except Exception as exc:
            step("Switched on the schedule", False, f"{type(exc).__name__}: {exc}")
    if on:
        step("Switched on the schedule", True, f"it runs every {every_hours} hours while this computer is on")
    level = jobscout.autonomy_of(jobscout.auto_config())
    step("Left sending as you set it", True,
         jobscout.AUTONOMY_SAYS.get(level, "Your own combination of settings.")
         + (" Nothing is sent while Rehearsal is on." if cfg.get("dry_run", True) else ""))
    started = False
    ready = bool(targets) and brain is not None and jobscout.profile_ready()[0] \
        and bool([s for s in jobscout.job_sources() if s.get("on", True)])
    if start and ready:
        r = jobscout.start_run("cycle", brain, model=model)
        started = bool(r.get("ok") or r.get("already"))
        step("Started the first run", started,
             "finding, scoring and drafting now; watch it under Auto-apply" if started
             else r.get("error", ""))
    cfgs = jobscout.load_config()
    jobscout.save_config({**cfgs, "autopilot": {"set_up_at": _iso()}})
    jobscout._audit("autopilot", f"set up: {len(targets)} titles, "
                                 f"{len(jobscout.job_sources())} boards, started={started}")
    return {"ok": True, "steps": steps, "ready": ready, "started": started, "needs": needs,
            "targets": targets}


def status(memory=None) -> dict:
    """What the Overview and the phone show first: is Autopilot running, when
    next, what the last run did, how many applications went out, and what is
    waiting for you. Built only from what the app already holds."""
    from . import jobscout
    cfg = jobscout.auto_config()
    sched = jobscout.schedule_info(memory) if memory is not None else {}
    rs = jobscout.roles()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week = sorted({r.get("sent_at", "")[:10] for r in rs if r.get("sent_at")})[-7:]
    sent = [r for r in rs if r.get("sent_at") and not r.get("sent_dry_run")]
    sent_today = [r for r in sent if r["sent_at"].startswith(today)]
    replied = [r for r in rs if r.get("stage") in ("responded", "interview", "offer")]
    interviews = [r for r in rs if r.get("stage") in ("interview", "offer")]
    waiting = []
    for r in rs:
        st = (r.get("portal") or {}).get("state")
        if r.get("stage") in ("found", "drafted") and st in ("needs_answer", "needs_login",
                                                              "needs_captcha", "filled"):
            waiting.append({"key": r["key"], "title": r.get("title", ""),
                            "company": r.get("company", ""), "why": {
                                "needs_answer": "a question only you can answer",
                                "needs_login": "the site wants you signed in",
                                "needs_captcha": "a captcha",
                                "filled": "filled in, waiting for you to submit"}[st]})
    held = [r for r in rs if r.get("stage") == "drafted"
            and ((r.get("draft") or {}).get("check") or {}).get("ok") is False]
    ready_ok, why = jobscout.profile_ready()
    on = bool(cfg.get("enabled")) and bool(sched.get("on"))
    last = (jobscout.run_reports(1) or [{}])[0]
    # the time it would have taken by hand: finding and reading an advert,
    # tailoring a CV, writing a letter and filling a form is about 25 minutes
    hours = round(len(sent) * 25 / 60, 1)
    if not ready_ok:
        say = "Autopilot needs your CV to start."
    elif not on:
        say = "Autopilot is off."
    elif waiting or held:
        say = f"Autopilot is running. {len(waiting) + len(held)} thing(s) need you."
    else:
        say = "Autopilot is running. Nothing needs you."
    return {"on": on, "says": say, "set_up": bool((jobscout.load_config().get("autopilot") or {})),
            "profile_ready": ready_ok, "why_not": "" if ready_ok else why,
            "level": cfg.get("level"), "rehearsal": bool(cfg.get("dry_run", True)),
            "schedule": sched, "last_run": {"at": last.get("at", ""), "summary": last.get("summary", "")},
            "tracked": len(rs), "sent": len(sent), "sent_today": len(sent_today),
            "active_days": len(week), "replies": len(replied), "interviews": len(interviews),
            "hours_saved": hours, "needs_you": waiting[:20], "held": len(held),
            "running": jobscout.run_status().get("state") == "running"}
