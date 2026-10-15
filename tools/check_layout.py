"""Measure the Agent Jo Jobs window in a real browser, on this machine.

    python tools/check_layout.py

The window is drawn from this folder's own HTML, CSS and JavaScript with
made-up sample data — no server is started, nothing of yours is read, no site
is visited — and the things that went wrong once are measured where they went
wrong: a narrow window cut off at the right, the engine picker out of reach, a
blank drafts pane. Then the Symbolic Synapse look: its fonts come from the app,
the green logo is the one shown, the lattice on the overview is drawn and stops
when it can't be seen, and no view scrolls sideways at any width. Needs
Playwright with Chromium, as portal applications do.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

JOBS = {
    "/api/meta": {"app": "Agent Jo Jobs", "build": "x", "brand": "Sample",
                  "profile_ready": True, "engines": ["Local"], "default_engine": "Auto"},
    "/api/jobs/pipeline": {"stages": {"found": 4, "scored": 3, "drafted": 2, "held": 1,
                                      "applied": 1}, "total": 4, "blocked_at": "held",
                           "why": "1 draft claims more than your profile", "counts": {}},
    "/api/jobs": {"profile": {}, "auto": {"enabled": False}, "follow_ups": [], "daily": False,
                  "roles": [{"key": "r", "title": "Data Engineer", "company": "Sample Co",
                             "stage": "held", "fit": {"score": 80}}]},
    "/api/jobs/claims": {"held": [{"key": "r", "title": "Data Engineer",
                                   "company": "Sample Co", "problems": ["a claim"],
                                   "body": "Dear..."}], "claims": []},
    "/api/jobs/outcomes": {"sent": 0, "replied": 0, "overall": {"low": 0, "high": 0},
                           "findings": [], "by_source": []},
    "/api/jobs/search/config": {"sources": []},
    "/api/jobs/profile": {"profile": {}, "ready": True, "why": ""},
    "/api/jobs/auto/preview": {"sentence": "Nothing would be sent.", "dry_run": True},
    "/api/jobs/sources/suggested": {"suggested": []},
    "/api/jobs/auto/status": {"state": "idle"},
    "/api/jobs/autonomy": {"level": "draft", "levels": [
        {"id": "draft", "says": "Finds, scores and drafts; you send."},
        {"id": "prepare", "says": "Also fills forms, and stops before submit."},
        {"id": "email", "says": "Sends emailed applications that pass every check."},
        {"id": "full", "says": "Sends and submits what passes every check."}]},
    "/api/jobs/inbox": {"settings": {"enabled": False, "imap_host": ""}, "imap_guess": "",
                        "mail_ready": False, "folder": "replies", "recent": []},
    "/api/jobs/digest": {"settings": {"enabled": False, "to": "", "weekday": 0},
                         "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                                  "Saturday", "Sunday"],
                         "preview": {"subject": "Your week", "text": "Nothing yet."}},
    # what applying taught it (agent/playbooks.py): sample sites
    "/api/jobs/portal/learning": {
        "totals": {"applications": 14, "sites": 3, "routes": 2, "labels": 9, "systems": ["greenhouse"]},
        "recent": {"last": 10, "last_without_you": 7, "before": 4, "before_without_you": 1,
                   "last_turns": 1.4, "before_turns": 5.5},
        "explore": {"on": True, "turns": 12},
        "sites": [
            {"site": "careers.sample-company-with-a-long-name.example", "ats": "", "runs": 4,
             "last_outcome": "filled", "route": ["Start my journey", "Apply manually"],
             "next": ["proceed to step 2"], "labels": 3, "blocks": [],
             "notes": ["The form is two pages behind 'Start my journey'."], "turns": [5, 2, 0, 0]},
            {"site": "boards.greenhouse.io", "ats": "greenhouse", "runs": 8, "last_outcome": "submitted",
             "route": ["Apply for this job"], "next": [], "labels": 4, "blocks": [], "notes": [],
             "turns": [3, 1, 0, 0, 0, 0]},
            {"site": "jobs.sample.example", "ats": "", "runs": 2, "last_outcome": "needs_login",
             "route": [], "next": [], "labels": 2, "blocks": ["needs_login"], "notes": [],
             "turns": [4, 1]}]},
    "/api/jobs/sources/explore": {
        "ok": True, "url": "https://sample.example/careers",
        "message": "Found Sample — careers on Greenhouse (12 roles).",
        "boards": [{"name": "Sample — careers", "kind": "greenhouse", "system": "greenhouse",
                    "url": "https://boards-api.greenhouse.io/v1/boards/sample/jobs?content=true",
                    "found": 12, "sample": ["Data Engineer", "Analytics Engineer"], "added": False}],
        "looked_at": [{"url": "https://sample.example/careers"}, {"url": "https://sample.example/jobs"}]},
}
# a role whose form it has been through: what it did and what it learned
JOBS["/api/jobs"]["roles"][0]["portal"] = {
    "state": "filled", "message": "Filled in and left for you to read.", "explored": True,
    "engine_turns": 1, "pages": 2, "filled": 11,
    "steps": [{"say": "Opened the advert", "by": "rule", "ok": True},
              {"say": "Declined the cookie banner (“Reject all”)", "by": "rule", "ok": True},
              {"say": "Pressed “Start my journey” (learned on an earlier application): it opened a new tab",
               "by": "playbook", "ok": True},
              {"say": "Filled in first name, last name, email, phone number (local format) and country",
               "by": "rule", "ok": True},
              {"say": "Pressed “Proceed to step 2” to the next page", "by": "playbook", "ok": True},
              {"say": "Typed your salary expectation into “Current CTC”", "by": "engine", "ok": True},
              {"say": "Refused to press “Submit application”: it would submit the application",
               "by": "engine", "ok": False}],
    "learned": ["“Current CTC” means your salary expectation",
                "Needed the engine 1 time on careers.sample.example, down from 5 last time"]}
JOBS["/api/jobs"]["roles"][0]["portal_at"] = "2026-10-15 07:12 UTC"


def _router(static: Path, data: dict):
    def handle(route):
        path = "/" + route.request.url.split("://", 1)[1].split("/", 1)[1].split("?")[0]
        if path.startswith("/api/"):
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(data.get(path, {})))
        if path == "/avatar":
            av = ROOT / "agent_avatar.png"
            if av.exists():
                return route.fulfill(status=200, body=av.read_bytes(), content_type="image/png")
        f = static / ("index.html" if path == "/" else path.replace("/static/", "", 1).lstrip("/"))
        if f.is_file():
            return route.fulfill(status=200, body=f.read_bytes(), content_type=(
                mimetypes.guess_type(str(f))[0] or "application/octet-stream"))
        return route.fulfill(status=404, body=b"")
    return handle


def main() -> int:
    from playwright.sync_api import sync_playwright
    results = []

    def check(what, ok):
        results.append(bool(ok))
        print(("  \u2713 " if ok else "  \u2717 ") + what)

    with sync_playwright() as p:
        b = p.chromium.launch()

        def page(app, w, h, look=None):
            static = ROOT / "web_jobs"
            pg = b.new_page(viewport={"width": w, "height": h}, color_scheme="dark")
            if look:
                pg.add_init_script(f"localStorage.setItem('agentjo-look', '{look}')")
            pg.route("**/*", _router(static, JOBS))
            pg.goto("http://app.test/")
            pg.wait_for_function(
                "document.getElementById('track').children.length === 6", timeout=30000)
            pg.wait_for_timeout(1500)   # not time.sleep: the page only runs while Playwright does
            return pg

        print("Agent Jo Jobs")
        pg = page("jobs", 683, 768)
        m = pg.evaluate("""() => ({ overflow: document.scrollingElement.scrollWidth - innerWidth,
                                    mainLeft: document.querySelector('.main').getBoundingClientRect().left })""")
        check("a narrow window (half a laptop screen) reflows",
              m["overflow"] <= 1 and m["mainLeft"] < 40)
        check("the engine picker is reachable in a narrow window, and no Look switch", pg.evaluate(
            "() => document.getElementById('engine').getBoundingClientRect().width > 0"
            " && !document.getElementById('lookSel')"))
        pg.close()
        pg = page("jobs", 1024, 640)
        pg.evaluate("show('drafts')")
        # wait the Playwright way: a time.sleep() lets nothing happen, not
        # even the stubbed replies being served, so the pane was read before
        # its data arrived and the check passed or failed by luck
        try:
            pg.wait_for_function(
                "document.getElementById('draftDetail').innerText.trim().length > 0",
                timeout=10000)
        except Exception:
            pass
        check("the drafts pane is never blank", "Pick a draft" in pg.evaluate(
            "document.getElementById('draftDetail').innerText"))
        pg.close()

        # ---- what it did and what it learned ------------------------------- #
        print("Agent Jo Jobs — getting better with every application")
        for w, h in ((1440, 900), (390, 844)):
            pg = page("jobs", w, h)
            pg.evaluate("show('auto')")
            try:
                pg.wait_for_function("document.querySelectorAll('#learnSites .learn-site').length === 3",
                                     timeout=10000)
            except Exception:
                pass
            m = pg.evaluate("""() => ({
              stats: document.querySelectorAll('#learnStats .learn-stat').length,
              sites: document.querySelectorAll('#learnSites .learn-site').length,
              trend: (document.querySelector('#learnSites .learn-trend') || {}).textContent || '',
              explore: document.getElementById('exOn').checked && document.getElementById('exTurns').value,
              over: Math.max(document.scrollingElement.scrollWidth - innerWidth,
                ...[...document.querySelectorAll('#learnCard *')].map(e => {
                  const r = e.getBoundingClientRect(), c = document.getElementById('learnCard').getBoundingClientRect();
                  return r.width ? r.right - c.right : 0; })) })""")
            check(f"the learning card shows its numbers, its sites and its settings at {w}px",
                  m["stats"] == 4 and m["sites"] == 3 and "5 → 2 → 0 → 0" in m["trend"]
                  and m["explore"] == "12" and m["over"] <= 1)
            pg.evaluate("openRole(S.roles[0])")
            pg.wait_for_timeout(300)
            m = pg.evaluate("""() => { const b = document.querySelector('#roleDetail .portal-last');
              if (!b) return {};
              b.querySelector('details.trail').open = true;
              const r = b.getBoundingClientRect();
              return { steps: b.querySelectorAll('.trail-step').length,
                       learned: b.querySelectorAll('.learned-list li').length,
                       chips: [...b.querySelectorAll('.trail-by')].map(x => x.textContent).join(','),
                       refused: b.querySelectorAll('.trail-step.is-off').length,
                       over: Math.max(...[...b.querySelectorAll('*')].map(e => e.getBoundingClientRect().right - r.right)) }; }""")
            check(f"a role shows what its last form attempt did and learned at {w}px",
                  m.get("steps") == 7 and m.get("learned") == 2 and "learned" in m.get("chips", "")
                  and "engine" in m.get("chips", "") and m.get("refused") == 1 and m.get("over", 9) <= 1)
            pg.evaluate("show('sources')")
            pg.fill("#finderUrl", "sample.example/careers")
            pg.click("#finderGo")
            try:
                pg.wait_for_function("document.querySelectorAll('#finderOut .finder-row').length === 1",
                                     timeout=10000)
            except Exception:
                pass
            m = pg.evaluate("""() => ({ rows: document.querySelectorAll('#finderOut .finder-row').length,
              add: (document.querySelector('#finderOut .finder-row .btn') || {}).textContent || '',
              over: document.scrollingElement.scrollWidth - innerWidth })""")
            check(f"the board finder offers what it found at {w}px",
                  m["rows"] == 1 and m["add"] == "Add as a source" and m["over"] <= 1)
            shots_dir = os.environ.get("AGENT_JOBS_SHOTS", "")   # pictures only when asked for
            if w == 1440 and shots_dir:
                shots = Path(shots_dir)
                shots.mkdir(parents=True, exist_ok=True)
                pg.evaluate("show('auto')")
                pg.wait_for_timeout(400)
                pg.locator("#learnCard").screenshot(path=str(shots / "learning-card.png"))
                pg.evaluate("show('roles')")
                pg.wait_for_timeout(900)            # the view draws its list first
                pg.evaluate("openRole(S.roles[0])")
                pg.wait_for_selector("#roleDetail .portal-last details.trail", timeout=10000)
                pg.evaluate("document.querySelector('#roleDetail .portal-last details.trail').open = true")
                pg.wait_for_timeout(900)            # past the view's fade-in
                pg.locator("#roleDetail .portal-last").screenshot(path=str(shots / "role-last-attempt.png"))
            pg.close()

        # ---- the Symbolic Synapse look, in Jobs green ---------------------- #
        print("Agent Jo Jobs — Symbolic Synapse, in green")
        asked = []
        pg = b.new_page(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        pg.on("request", lambda r: asked.append(r.url))
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.route("**/*", _router(ROOT / "web_jobs", JOBS))
        pg.goto("http://app.test/")
        pg.wait_for_function("document.getElementById('track').children.length === 6", timeout=30000)
        pg.wait_for_timeout(1500)
        m = pg.evaluate("""async () => { await document.fonts.ready;
          const btn = document.getElementById('ovCycle');
          return { skin: document.documentElement.getAttribute('data-skin'),
                   fonts: [document.fonts.check('600 20px Archivo'),
                           document.fonts.check('400 14px "IBM Plex Sans"'),
                           document.fonts.check('400 12px "IBM Plex Mono"')],
                   accent: getComputedStyle(btn).backgroundColor,
                   ground: getComputedStyle(document.body).backgroundColor }; }""")
        woff = [u for u in asked if u.endswith(".woff")]
        check("the look is Symbolic Synapse, and its typefaces come from the app",
              m["skin"] == "synapse" and all(m["fonts"]) and woff
              and all(u.startswith("http://app.test/static/fonts/") for u in woff)
              and not any("fonts.g" in u for u in asked))
        check("the accent stays Jobs green on the site's abyss",
              m["accent"] == "rgb(70, 211, 154)" and m["ground"] == "rgb(3, 6, 11)")
        icons = [u for u in asked if "/icons/" in u]
        check("the green logo is the one in the window and the tab",
              icons and all("v=green1" in u for u in icons)
              and pg.evaluate("[...document.querySelectorAll('link[rel=icon]')].length") >= 3)
        m = pg.evaluate("""() => {
          const c = document.querySelector('#v-overview .syn-mark canvas');
          if (!c || !c.width) return { drawn: 0 };
          const px = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
          let n = 0; for (let i = 3; i < px.length; i += 4) if (px[i] > 8) n++;
          const logo = document.querySelector('#v-overview .syn-mark img').getBoundingClientRect();
          return { drawn: n, running: !!SYN.raf,
                   logoOnTop: document.elementFromPoint(logo.x + logo.width / 2,
                     logo.y + logo.height / 2) === document.querySelector('#v-overview .syn-mark img') }; }""")
        check("the overview's lattice is drawn round the logo, and turns",
              m["drawn"] > 2000 and m.get("logoOnTop") and m.get("running"))
        pg.evaluate("SYN.input = performance.now() - 10 * 60 * 1000")
        pg.wait_for_timeout(300)
        idle = pg.evaluate("SYN.raf")
        pg.mouse.move(700, 500)
        pg.mouse.move(720, 520)
        pg.wait_for_timeout(300)
        check("left alone it holds still, and a touch of the mouse wakes it",
              not idle and pg.evaluate("!!SYN.raf"))
        pg.evaluate("show('roles')")
        pg.wait_for_timeout(300)
        check("it stops when another view is open", not pg.evaluate("SYN.raf"))
        pg.close()

        # every view, phone-wide to desktop: nothing scrolls sideways
        wide = []
        views = ["overview", "roles", "search", "drafts", "auto", "sources", "engines",
                 "results", "archive", "people", "answers", "profile"]
        for w, h in ((1440, 900), (1024, 640), (683, 768), (390, 844)):
            pg = page("jobs", w, h)
            for v in views:
                pg.evaluate(f"show('{v}')")
                pg.wait_for_timeout(250)
                over = pg.evaluate("""() => Math.max(
                  document.scrollingElement.scrollWidth - innerWidth,
                  ...[...document.querySelectorAll('.view.is-on, .main')].map(e => e.scrollWidth - e.clientWidth))""")
                if over > 1:
                    wide.append(f"{v}@{w}")
            pg.close()
        check(f"no view scrolls sideways, from phone to desktop ({len(views)} views)", not wide)
        if wide:
            print("      ", ", ".join(wide))
        check("no script errors in any view", not errors)

        # less motion asked for: drawn once, then still
        pg = b.new_page(viewport={"width": 1280, "height": 800}, color_scheme="dark",
                        reduced_motion="reduce")
        pg.route("**/*", _router(ROOT / "web_jobs", JOBS))
        pg.goto("http://app.test/")
        pg.wait_for_function("document.getElementById('track').children.length === 6", timeout=30000)
        pg.wait_for_timeout(1200)
        m = pg.evaluate("""() => { const c = document.querySelector('#v-overview .syn-mark canvas');
          const px = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
          let n = 0; for (let i = 3; i < px.length; i += 4) if (px[i] > 8) n++;
          return { drawn: n, raf: SYN.raf }; }""")
        check("with reduced motion the lattice is drawn once and stays still",
              m["drawn"] > 2000 and not m["raf"])
        pg.close()
        b.close()
    print(f"\n{sum(results)} of {len(results)} checks passed.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
