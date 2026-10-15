"""Check, in a real browser, that what you type into a form is saved and
reused on the next form.

    python tools/check_answers.py

It opens a small local application form with the helper in it, types
answers the way you would, and checks they reach your answer bank — and that
a password typed there does not. Then it opens a second form, worded
differently, and checks it is filled from those answers. A throwaway data
folder and browser profile are used; nothing of yours is touched and no site
is visited. Needs Playwright with Chromium, as portal applications do.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AGENT_JOBS_HOME"] = tempfile.mkdtemp(prefix="answers-check-")
os.environ["AGENT_HOME"] = os.environ["AGENT_JOBS_HOME"]

FORMS = {
    "/one": """<form>
 <p><label for="np">What is your notice period?</label> <input id="np"></p>
 <p><label for="why">Why do you want to join us?</label> <textarea id="why"></textarea></p>
 <p><label for="pw">Create a password</label> <input id="pw" type="password"></p>
 <p><label for="ed">Highest qualification</label>
   <select id="ed"><option>Select…</option><option>Matric</option><option>BSc Honours</option></select></p>
</form>""",
    "/two": """<form>
 <p><label for="a">Notice period (required)</label> <input id="a" required></p>
 <p><label for="b">Highest qualification *</label> <input id="b" required></p>
</form>""",
}


class _Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = ("<!doctype html><html><body>" + FORMS.get(self.path, "")
                + "</body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    import agent.portal as P
    import agent.answerbank as AB
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    results = []

    def check(what, ok):
        results.append(bool(ok))
        print(("  ✓ " if ok else "  ✗ ") + what)

    d = P.PlaywrightDriver(headless=True)
    try:
        page = d.open(base + "/one")
        d.companion(page, P.companion_payload([], {}, {"title": "Data Engineer",
                                                       "company": "Acme"}))
        page.fill("#np", "30 days")
        page.fill("#why", "Because of the data platform you're building.")
        page.fill("#pw", "s3cret-pass")
        page.select_option("#ed", "BSc Honours")
        page.click("body")
        # wait_for_timeout, not time.sleep: the page's calls back into Python
        # are only handled while Playwright is running
        page.wait_for_timeout(800)
        saved = {a["question"]: a["answer"] for a in AB.all_answers()}
        check("a typed answer is saved with its question",
              saved.get("What is your notice period?") == "30 days")
        check("a long answer is saved", "data platform" in
              saved.get("Why do you want to join us?", ""))
        check("a drop-down's choice is saved as its text",
              saved.get("Highest qualification") == "BSc Honours")
        check("a password is never saved",
              not any("s3cret" in v for v in saved.values())
              and "Create a password" not in saved)
        page2 = d.open(base + "/two")
        fields = d.fields(page2)
        pl = P.plan({}, {}, fields)
        got = {f["label"]: f["value"] for f in pl["fill"]}
        check("the next form, worded differently, is filled from them",
              "30 days" in got.values() and "BSc Honours" in got.values()
              and pl["can_complete"])
    except Exception as exc:
        print(f"  ✗ the check stopped: {type(exc).__name__}: {exc}")
        results.append(False)
    finally:
        try:
            d.close(keep_open=False)
        except Exception:
            pass
        srv.shutdown()
    print(f"\n{sum(results)} of {len(results)} checks passed.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
