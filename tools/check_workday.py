"""Walk a Workday-style application in a real browser, on this machine.

    python tools/check_workday.py

A local imitation of a Workday application (tests/fixtures/workday_mock.html:
the same data-automation-id markers, button drop-downs that open a list, one
page per step, required-field errors, a Review page) is served from this
computer only, and agent/workday.py walks it. No real Workday site is
visited and nothing of yours is read. Needs Playwright with Chromium.
"""
from __future__ import annotations

import functools
import os
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AGENT_JOBS_HOME"] = tempfile.mkdtemp(prefix="workday-check-")
os.environ["AGENT_HOME"] = os.environ["AGENT_JOBS_HOME"]


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main() -> int:
    from playwright.sync_api import sync_playwright
    from agent import config
    config.AGENT_HOME = Path(os.environ["AGENT_JOBS_HOME"])
    import agent.answerbank as AB
    import agent.workday as WD

    srv = ThreadingHTTPServer(("127.0.0.1", 0),
                              functools.partial(_Quiet, directory=str(ROOT / "tests" / "fixtures")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/workday_mock.html"
    cv = Path(os.environ["AGENT_JOBS_HOME"]) / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4\n% test cv\n")
    profile = {"full_name": "Thandi Mokoena", "email": "thandi@example.com", "phone": "+27 82 000 0000",
               "location": "Johannesburg, Gauteng, South Africa", "availability": "30 days",
               "linkedin": "https://www.linkedin.com/in/thandi"}
    role = {"key": "r", "title": "Senior Data Engineer", "company": "Acme"}
    AB.remember("Are you legally authorised to work in South Africa?", "Yes", source="you")
    asked = []

    def answer_fn(qs):
        asked.extend(qs)
        return [{"question": q, "answer": "No" if "relocate" in q.lower() else ""} for q in qs]

    results = []

    def check(what, ok, detail=""):
        results.append(bool(ok))
        print(("  ✓ " if ok else "  ✗ ") + what + (f"  [{detail}]" if not ok and detail else ""))

    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            pg = b.new_page()
            pg.goto(base + "?terms=1")
            r = WD.run(pg, profile, role, cv_file=str(cv), answer_fn=answer_fn)
            titles = [s["title"] for s in r["steps"]]
            check("walks page by page", titles[:3] == ["My Information", "My Experience",
                                                       "Application Questions"], titles)
            check("stops at a terms box for you", r["state"] == WD.NEEDS_ANSWER
                  and any("terms" in x for x in r["left"]), r)
            check("never answers gender",
                  pg.inner_text('[data-automation-id="gender"]').strip() == "Select One")
            check("only the unknown question went to the engine", asked == ["Are you willing to relocate? *"]
                  or asked == ["Are you willing to relocate?"], asked)
            pg.close()

            pg = b.new_page()
            pg.goto(base + "?terms=0")
            r = WD.run(pg, profile, role, cv_file=str(cv), answer_fn=answer_fn)
            check("fills every page and stops at Review", r["state"] == WD.FILLED and r["ok"]
                  and r["steps"][-1]["title"] == "Review", r)
            data = pg.evaluate("JSON.parse(document.getElementById('review').textContent)")
            check("names and email typed", data.get("legalNameSection_firstName") == "Thandi"
                  and data.get("legalNameSection_lastName") == "Mokoena"
                  and data.get("email") == "thandi@example.com", data)
            check("button drop-downs chosen", data.get("phone-device-type") == "Mobile"
                  and data.get("countryDropdown") == "South Africa"
                  and data.get("sourceDropdown") == "Job Board", data)
            check("CV uploaded", data.get("file-upload-input-ref") == "cv.pdf", data)
            check("saved answer used for a yes/no question", data.get("auth") == "Yes", data)
            check("profile answer for the notice period", data.get("notice") == "30 days", data)
            check("engine answer chosen in a drop-down", data.get("relocate") == "No", data)
            check("nothing submitted without being asked",
                  pg.evaluate("window.__submitted === undefined"))
            pg.close()

            pg = b.new_page()
            pg.goto(base + "?terms=0")
            r = WD.run(pg, profile, role, cv_file=str(cv), answer_fn=answer_fn, submit=True)
            check("submits when told to", r["state"] == WD.SUBMITTED
                  and pg.evaluate("!!window.__submitted"), r)
            pg.close()

            pg = b.new_page()
            pg.goto(base + "?terms=0")
            r = WD.run(pg, profile, role, cv_file=str(cv), answer_fn=None)
            check("without an engine, an unknown question stops it and is named",
                  r["state"] == WD.NEEDS_ANSWER and any("relocate" in x.lower() for x in r["left"])
                  and r["steps"][-1]["title"] == "Application Questions", r)
            pg.close()

            pg = b.new_page()
            pg.goto(base + "?terms=0")
            r = WD.run(pg, profile, role, cv_file="", answer_fn=answer_fn)
            check("a required upload with no CV file stops it and says so",
                  r["state"] == WD.NEEDS_ANSWER and any("no CV file" in x for x in r["left"]), r)
            pg.close()

            pg = b.new_page()
            pg.goto(base + "?terms=0&sneaky=1")
            r = WD.run(pg, profile, role, cv_file=str(cv), answer_fn=answer_fn)
            check("Workday's own error is read and reported, not retried blind",
                  r["state"] == WD.UNKNOWN_FORM and any("Preferred Name" in e for e in r["errors"]), r)
            pg.close()
        finally:
            b.close()

    # through the app's own portal path: recognised as Workday and walked
    import agent.portal as PO
    AB.remember("Are you willing to relocate?", "No", source="you")
    full = dict(profile, cv_path=str(cv))
    try:
        res = PO.apply_to_portal(dict(role, url=base + "?terms=0"), full, submit=False, headless=True)
        check("the app sends a Workday advert down the Workday path",
              res.get("ats") == "workday" and "workday" in res, res.get("message"))
        check("and it ends at Review, filled", res.get("state") == PO.FILLED, res.get("message"))
    finally:
        try:
            PO.release_driver(close=True)
        except Exception:
            pass
        srv.shutdown()
    print(f"\n{sum(results)} of {len(results)} checks passed.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
