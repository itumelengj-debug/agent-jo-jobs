"""Use the phone companion in a real browser, at phone size, on this machine.

    python tools/check_phone.py

Starts the real phone listener on this computer only (127.0.0.1) with a
throwaway data folder, opens its link the way a scanned code would, and
answers a question, approves a draft and skips one. Nothing of yours is read
and no site is visited. Needs Playwright with Chromium.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AGENT_JOBS_HOME"] = tempfile.mkdtemp(prefix="phone-check-")
os.environ["AGENT_HOME"] = os.environ["AGENT_JOBS_HOME"]


def main() -> int:
    from playwright.sync_api import sync_playwright
    from agent import config
    config.AGENT_HOME = Path(os.environ["AGENT_JOBS_HOME"])
    import agent.jobscout as J
    import agent.answerbank as AB
    import agent.phone as PH

    J.save_profile({"summary": "Data engineer", "employers": ["Nedbank"], "skills": ["SQL"],
                    "target_roles": ["Data Engineer"]})
    J.add_roles([{"title": "Data Engineer", "company": c, "url": f"https://x.test/{c}"}
                 for c in ("Acme", "Zeta")])
    k = {r["company"]: r["key"] for r in J.roles()}
    for c in ("Acme", "Zeta"):
        J.update_role(k[c], stage="drafted", fit={"score": 70}, apply_email=f"jobs@{c.lower()}.test",
                      draft={"subject": "Application", "body": "Hello,\n\nI built pipelines at Nedbank.",
                             "check": {"ok": True, "problems": []}})
    AB.ask("What is your notice period?", "Data Engineer @ Acme", k["Acme"])
    PH.set_enabled(True)
    PH.stop()
    PH.start(port=0, host="127.0.0.1")
    port, key = PH._SERVER["port"], PH.settings()["key"]
    results = []

    def check(what, ok):
        results.append(bool(ok))
        print(("  ✓ " if ok else "  ✗ ") + what)

    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            # bypass_csp only so the checks' own waits can run; the page's
            # policy is tested in tests/test_logic.py
            pg = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                               is_mobile=True, has_touch=True, color_scheme="dark",
                               bypass_csp=True).new_page()
            pg.on("dialog", lambda d: d.accept())
            pg.goto(f"http://127.0.0.1:{port}/#k={key}")
            pg.wait_for_selector("textarea")
            check("the key is taken out of the address bar", "#k=" not in pg.url)
            check("it shows the waiting question", "notice period" in pg.inner_text("main"))
            m = pg.evaluate("document.scrollingElement.scrollWidth - innerWidth")
            check("it fits a phone screen", m <= 1)
            pg.screenshot(path=str(Path(tempfile.gettempdir()) / "phone-check.png"), full_page=True)
            pg.fill("textarea", "30 days")
            pg.click("text=Save answer")
            pg.wait_for_function("!document.body.innerText.includes('Holding up')")
            check("an answer from the phone is saved", (AB.lookup("What is your notice period?") or {})
                  .get("answer") == "30 days")
            pg.click("button:text-is('Approve') >> nth=0")
            pg.wait_for_function("document.body.innerText.includes('approved')")
            check("a draft approved from the phone is approved",
                  sum(1 for r in J.roles() if r.get("approved")) == 1)
            pg.click("text=Skip this role >> nth=-1")
            pg.wait_for_function("document.querySelectorAll('.card h3').length < 3", timeout=10000)
            check("a role skipped from the phone is closed",
                  any(r.get("stage") == "closed" for r in J.roles()))
            pg.reload()
            pg.wait_for_selector("h2")
            check("it remembers the key after the address is cleaned",
                  "drafts waiting" in pg.inner_text("main").lower())
            b.close()
    finally:
        PH.stop()
    print(f"\n{sum(results)} of {len(results)} checks passed.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
