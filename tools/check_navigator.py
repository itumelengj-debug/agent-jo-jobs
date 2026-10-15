"""Walk applications through a real browser with the navigator, on this machine.

    python tools/check_navigator.py

A small, deliberately awkward website (tests/fixtures/nav) is served from this
computer only, on two addresses so the form sits in an iframe from another
origin, the way company careers sites embed their hiring system: a cookie
banner over the advert, an apply button the rules don't know ("Start my
journey") that opens a new tab, "Apply with LinkedIn" and "Sign in" beside it,
a box with only a placeholder, a question written above its box, a drop-down
inside a web component, a radio group, a form that rejects the phone format
and says so, step two in the same page, a hidden file input, a custom list,
gender and consent boxes. The engine is a scripted stand-in (no engine is
called and nothing leaves this computer); it's only asked what the rules and
the site's playbook can't answer.

It checks that the navigator reads all of that, gets through it, never
touches what it mustn't, learns the site, and needs no engine at all the
second time; that it submits only when told; and that a captcha, a closed
advert and an email-only advert are each recognised. Needs Playwright with
Chromium, as portal applications do.
"""
from __future__ import annotations

import functools
import os
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ["AGENT_JOBS_HOME"] = tempfile.mkdtemp(prefix="navigator-check-")
os.environ["AGENT_HOME"] = os.environ["AGENT_JOBS_HOME"]

EVENTS: list = []


class _Site(SimpleHTTPRequestHandler):
    """The fixture pages, and /log, where they report what was pressed."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/log?"):
            EVENTS.append(parse_qs(urlparse(self.path).query).get("e", [""])[0])
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
        _Site, directory=str(ROOT / "tests" / "fixtures" / "nav")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _policy(pl: dict) -> dict:
    """The stand-in engine: what a sensible one would do with each page."""
    from fakesite import ref_of
    page, prob = pl["PAGE"], pl["PROBLEM"]
    if "job advert" in prob:
        return {"thinking": "the way in", "actions": [{"tool": "click", "ref": ref_of(page, "journey")}]}
    if "10-digit" in prob:
        return {"actions": [{"tool": "type", "ref": ref_of(page, "number", "controls"), "field": "phone_local"},
                            {"tool": "click", "ref": ref_of(page, "proceed")}]}
    acts = []
    for c in page["controls"]:
        if c.get("required") and not c.get("filled"):
            lab = c["label"].lower()
            if "number" in lab:
                acts.append({"tool": "type", "ref": c["ref"], "field": "phone"})
            elif "ctc" in lab:
                acts.append({"tool": "type", "ref": c["ref"], "field": "salary"})
            elif "gender" not in lab and "privacy" not in lab:
                acts.append({"tool": "answer", "ref": c["ref"]})
    if not acts:
        acts = [{"tool": "click", "ref": ref_of(page, "proceed")}]
    return {"thinking": "fill what's left", "actions": acts + [
        {"tool": "note", "text": "The form is in an iframe, two steps, behind 'Start my journey'."}]}


def main() -> int:
    from playwright.sync_api import sync_playwright
    from agent import config
    config.AGENT_HOME = Path(os.environ["AGENT_JOBS_HOME"])
    import agent.jobscout as J
    import agent.navigator as N
    import agent.playbooks as PB
    import agent.portal as PO
    from fakesite import FakeBrain

    results = []

    def check(what, ok, detail=""):
        results.append(bool(ok))
        print(("  ✓ " if ok else "  ✗ ") + what + (f"  [{detail}]" if not ok and detail else ""))

    a, b = _serve(), _serve()
    site_a = f"http://127.0.0.1:{a.server_address[1]}"
    site_b = f"http://localhost:{b.server_address[1]}"      # another origin: the form's iframe
    advert = f"{site_a}/advert.html?form={quote(site_b, safe='')}"
    cv = config.AGENT_HOME / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4\n% test cv\n")
    prof = {"full_name": "Thandi Mokoena", "email": "thandi@example.com", "phone": "+27 82 000 0000",
            "location": "Johannesburg, Gauteng, South Africa", "rate": "R85k pm", "cv_path": str(cv),
            "summary": "Data engineer.", "achievements": ["Built data pipelines"]}
    J.save_profile(prof)
    role = {"key": "acme-de", "title": "Senior Data Engineer", "company": "Acme", "source": "Careers24",
            "draft": {"body": "I like the way your team works, and the work suits what I do."}}
    answers = {"preferred office": "Johannesburg"}

    # ---- reading a page: the questions as a person reads them ------------- #
    print("Reading a form")
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page()
        pg.goto(f"{site_b}/form.html")
        pg.wait_for_function("!!document.querySelector('jo-field').shadowRoot")
        snap = N.browser_snapshot(pg, {})
        labels = {c["label"]: c for c in snap["controls"]}
        check("a label tag, a wrapping label, a placeholder and the text above a box",
              {"First name *", "Surname *", "Email address", "Best number to reach you on *"} <= set(labels),
              sorted(labels))
        check("a drop-down inside a web component",
              labels.get("Country of residence", {}).get("options", [])[:3] == ["Select...", "Kenya", "South Africa"])
        radio = labels.get("How did you hear about us?", {})
        check("a radio group under its question",
              radio.get("kind") == "radio" and [o["text"] for o in radio.get("options", [])]
              == ["LinkedIn", "Job board", "Friend"])
        check("required boxes are known", labels["First name *"]["required"] and labels["Email address"]["required"]
              and not labels["Country of residence"]["required"])
        check("the next step's hidden boxes are not read yet",
              not any("CTC" in k for k in labels) and N.page_kind(snap) == "form")
        br.close()

    # ---- an application, start to finish -------------------------------- #
    def run(url, brain=None, submit=False):
        EVENTS.clear()
        return PO.apply_to_portal({**role, "url": url}, prof, submit=submit, headless=True,
                                  brain=brain, model=None)

    def form_state():
        d = PO._SHARED.get("driver")

        def look():
            for pg in d._real._ctx.pages:
                for fr in pg.frames:
                    if "form.html" in (fr.url or ""):
                        return fr.evaluate("joState()")
            return {}
        return d._call(look) if d else {}

    def open_urls():
        d = PO._SHARED.get("driver")
        return d._call(lambda: [pg.url for pg in d._real._ctx.pages]) if d else []

    print("Agent Jo Jobs — the navigator, in Chromium")
    try:
        b1 = FakeBrain(_policy, answers)
        r1 = run(advert, b1)
        ev = list(EVENTS)
        st = form_state()
        steps = " | ".join(s["say"] for s in r1.get("steps") or [])
        check("it finds a form behind an unusual button, in a new tab, in an iframe",
              r1["state"] == PO.FILLED and "start" in ev and st.get("step") == 2, f"{r1['state']}: {steps}")
        check("it declines the cookies, and never accepts them",
              "cookies-rejected" in ev and "cookies-accepted" not in ev, ev)
        check("it never presses Apply with LinkedIn or Sign in",
              "linkedin" not in ev and "signin" not in ev)
        filled1 = [e for e in ev if e.startswith("step1:")]
        check("step one: names, the placeholder email, the country in a web component, where you heard",
              filled1 and filled1[0] == "step1:Thandi|Mokoena|thandi@example.com|0820000000|South Africa|board",
              filled1)
        check("it read the form's complaint about the phone and fixed it",
              "step1-rejected" in ev and "10-digit" in steps)
        check("step two: your CV, your letter, your salary, an office from a custom list",
              st.get("cv") == "cv.pdf" and st.get("why", "").startswith("I like the way")
              and st.get("ctc") == "R85k pm" and st.get("office") == "Johannesburg", st)
        check("gender, privacy and job alerts are left for you; nothing is submitted",
              st.get("gender") == "Select" and not st.get("privacy") and not st.get("alerts")
              and not any(e.startswith("submitted") for e in ev), st)
        learned = " | ".join(r1.get("learned") or [])
        check("it says what it learned",
              "Start my journey" in learned and "Best number to reach you on" in learned
              and "Proceed to step 2" in learned and "Current CTC" in learned, learned)
        check("the advert's tab is closed; the form's is left open for you",
              not any("advert.html" in u for u in open_urls())
              and any("apply.html" in u for u in open_urls()))
        check("the engine only ever saw whether a box was filled, never your details",
              b1.nav_payloads and not any("thandi@example.com" in x or "82 000" in x for x in b1.nav_payloads))

        b2 = FakeBrain(_policy, answers)
        r2 = run(advert, b2)
        st2 = form_state()
        check("the second application through the site needs no engine at all",
              r2["state"] == PO.FILLED and r2.get("engine_turns") == 0 and b2.nav_calls == 0
              and st2.get("step") == 2 and st2.get("office") == "Johannesburg",
              f"{r2['state']} turns={r2.get('engine_turns')} {r2.get('message')}")
        check("and says so", any("Didn't need the engine at all" in x for x in r2.get("learned") or []),
              r2.get("learned"))

        r3 = run(advert, FakeBrain(_policy, answers), submit=True)
        sent = [e for e in EVENTS if e.startswith("submitted:")]
        check("it submits only when told to, and sees the thank-you",
              r3["state"] == PO.SUBMITTED and sent
              and sent[0] == "submitted:cv.pdf|R85k pm|Johannesburg|Select|false|false",
              f"{r3['state']} {r3.get('message')} {sent}")

        r4 = run(advert + "&captcha=1", FakeBrain(_policy, answers), submit=True)
        check("a captcha is handed to you, and nothing is typed",
              r4["state"] == PO.NEEDS_CAPTCHA and not any(e.startswith("step1:") for e in EVENTS),
              f"{r4['state']} {r4.get('message')}")
        r5 = run(advert + "&badge=1", FakeBrain(_policy, answers))
        check("the invisible reCAPTCHA badge is not a captcha", r5["state"] == PO.FILLED,
              f"{r5['state']} {r5.get('message')}")

        r6 = run(f"{site_a}/closed.html")
        check("a closed advert is called closed", r6["state"] == N.CLOSED, r6.get("message"))
        r7 = run(f"{site_a}/email.html")
        check("an advert that wants an email goes to the email path",
              r7["state"] == N.APPLY_BY_EMAIL and r7.get("apply_email") == "careers@globex.example",
              f"{r7['state']} {r7.get('apply_email')}")
        rep = PB.report()
        check("the playbook keeps the history the window shows",
              rep["totals"]["applications"] >= 5 and any(s["site"] == "127.0.0.1" for s in rep["sites"]))
    finally:
        try:
            PO.release_driver(close=True)
        except Exception:
            pass
        a.shutdown()
        b.shutdown()
    print(f"\n{sum(results)} of {len(results)} checks passed.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
