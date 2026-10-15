"""Run a practice interview in a real browser, on this machine.

    python tools/check_mock.py

The window is this folder's own HTML, CSS and JavaScript; the practice
endpoints are answered by the real agent/mockinterview.py with a throwaway data
folder and no engine (the local checks score it). Nothing of yours is read and
no site is visited. Needs Playwright with Chromium.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["AGENT_JOBS_HOME"] = tempfile.mkdtemp(prefix="mock-check-")
os.environ["AGENT_HOME"] = os.environ["AGENT_JOBS_HOME"]


def main() -> int:
    from playwright.sync_api import sync_playwright
    import check_layout as CL
    from agent import config
    config.AGENT_HOME = Path(os.environ["AGENT_JOBS_HOME"])
    import agent.jobscout as J
    import agent.mockinterview as M
    import agent.style as ST
    import agent.contacts as CT

    J.add_roles([{"title": "Data Engineer", "company": "Sample Co", "url": "https://sample.test/1"}])
    key = J.roles()[0]["key"]
    J.update_role(key, stage="interview",
                  interview={"questions": [{"question": "Why streaming?"}]},
                  draft={"subject": "Application", "body": "Dear team,\n\nI am writing to express "
                         "my keen interest in this exciting opportunity at your company.\n\nRegards"})
    data = dict(CL.JOBS)
    data["/api/jobs"] = dict(data["/api/jobs"], roles=[dict(J.get_role(key), bucket="interview")])
    static = ROOT / "web_jobs"
    base = CL._router(static, data)

    def handle(route):
        req = route.request
        path = "/" + req.url.split("://", 1)[1].split("/", 1)[1].split("?")[0]
        body = json.loads(req.post_data or "{}") if req.method == "POST" else {}
        role = J.get_role(key)
        out = None
        if path == "/api/jobs/mock":
            out = M.status(key)
        elif path == "/api/jobs/mock/start":
            out = M.start(role)
        elif path == "/api/jobs/mock/answer":
            out = M.answer(role, body.get("text", ""))
        elif path == "/api/jobs/mock/finish":
            out = M.finish(role)
        elif path == "/api/jobs/draft/save":
            out = J.save_draft(body["key"], body.get("body", ""), body.get("subject", ""))
            data["/api/jobs"]["roles"] = [dict(J.get_role(key), bucket="interview")]
        elif path == "/api/jobs/people":
            out = {"ok": True, "people": CT.people(), "get_back_to": CT.get_back_to()}
        elif path == "/api/jobs/style":
            out = dict(ST.summary(), ok=True)
        if out is None:
            return base(route)
        return route.fulfill(status=200 if out.get("ok") else 400, content_type="application/json",
                             body=json.dumps(out if out.get("ok") else {"detail": out.get("error")}))

    results = []

    def check(what, ok):
        results.append(bool(ok))
        print(("  ✓ " if ok else "  ✗ ") + what)

    with sync_playwright() as p:
        b = p.chromium.launch()
        for w, h in ((1280, 800), (390, 760)):
            pg = b.new_page(viewport={"width": w, "height": h}, color_scheme="dark")
            pg.route("**/*", handle)
            pg.goto("http://app.test/")
            pg.wait_for_function("document.getElementById('track').children.length === 6", timeout=30000)
            pg.evaluate("openMock(S.roles[0])")
            pg.wait_for_selector(".mock button.btn.primary")
            pg.click(".mock button.btn.primary")
            pg.wait_for_selector(".mock-q")
            check(f"[{w}px] the first question is the opener",
                  "about yourself" in pg.inner_text(".mock-q"))
            pg.fill(".mock-a", "We did data things.")
            pg.click(".mock .actions .btn.primary")
            pg.wait_for_selector(".mock-score")
            txt = pg.inner_text(".mock")
            check(f"[{w}px] a thin answer gets a low score and says why",
                  "/5" in txt and "concrete example" in txt)
            pg.click(".mock .actions .btn.primary")          # next question
            pg.wait_for_selector(".mock-a")
            pg.fill(".mock-a", "When I joined Sample Bank I led the move to streaming; the "
                    "nightly batch fell from six hours to seconds and saved 10 hours a week of reruns. "
                    "I built the consumers, the monitoring and the runbook myself, and trained two "
                    "colleagues to run it.")
            pg.click(".mock .actions .btn.primary")
            pg.wait_for_selector(".mock-score")
            pg.click(".mock .actions .btn.primary")          # see how it went
            pg.wait_for_selector(".mock-score.big")
            txt = pg.inner_text(".mock")
            check(f"[{w}px] the summary shows the average and what to work on",
                  "/5" in txt and "Work on these" in txt)
            m = pg.evaluate("""() => { const r = document.querySelector('.mock').getBoundingClientRect();
                 return {fits: r.left >= 0 && r.right <= innerWidth + 1,
                         over: document.scrollingElement.scrollWidth - innerWidth}; }""")
            check(f"[{w}px] the practice window fits the screen", m["fits"] and m["over"] <= 1)
            pg.keyboard.press("Escape")
            check(f"[{w}px] Escape closes it", pg.evaluate("!document.querySelector('.mock-wrap')"))
            pg.close()
        # editing a draft, in the role's window
        pg = b.new_page(viewport={"width": 1280, "height": 900}, color_scheme="dark")
        pg.route("**/*", handle)
        pg.goto("http://app.test/")
        pg.wait_for_function("document.getElementById('track').children.length === 6", timeout=30000)
        pg.evaluate("show('roles')")
        pg.wait_for_timeout(1500)            # let the roles view draw first
        pg.evaluate("openRole(S.roles[0])")
        pg.wait_for_selector("button:text-is('Edit')")
        pg.click("button:text-is('Edit')")
        pg.wait_for_selector(".draft-edit")
        pg.fill(".draft-edit", "Hi team,\n\nI built streaming pipelines and would like to do it "
                "for you.\n\nKind regards,\nSample")
        pg.click("text=Save my version")
        pg.wait_for_function("document.body.innerText.includes('Your version.')", timeout=10000)
        d = J.get_role(key)["draft"]
        check("an edited draft is saved as yours", d.get("edited") and d["body"].startswith("Hi team"))
        check("the edit is kept to learn from", len(ST.edits()) == 1)
        pg.evaluate("show('profile')")
        pg.wait_for_function("document.getElementById('styleBody').innerText.length > 20", timeout=10000)
        check("the profile says how it learns your style",
              "Learned from 1 draft" in pg.inner_text("#styleBody"))
        pg.close()

        # people, and a role at a company where you know someone
        CT.add("Thandi Mokoena", "thandi@sample.co", "Sample Co", "met at a meetup")
        CT.flag_roles()
        data["/api/jobs"]["roles"] = [dict(J.get_role(key), bucket="interview")]
        pg = b.new_page(viewport={"width": 1280, "height": 900}, color_scheme="dark")
        pg.route("**/*", handle)
        pg.goto("http://app.test/")
        pg.wait_for_function("document.getElementById('track').children.length === 6", timeout=30000)
        pg.click(".nav[data-view=people]")
        pg.wait_for_selector("#peopleList .person")
        check("the People view lists who you know", "Thandi Mokoena" in pg.inner_text("#peopleList"))
        pg.evaluate("show('roles')")
        pg.wait_for_timeout(1500)
        pg.evaluate("openRole(S.roles[0])")
        pg.wait_for_selector(".know-box")
        check("a role says when you know someone there",
              "Thandi Mokoena" in pg.inner_text(".know-box"))
        pg.close()
        b.close()
    print(f"\n{sum(results)} of {len(results)} checks passed.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
