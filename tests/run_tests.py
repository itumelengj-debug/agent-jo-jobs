"""Agent Jo Jobs — checks that run without Agent Jo.

The point of a separate project is that it stands up on its own, so these
never reach outside this folder. Run from the project root:

    python tests/run_tests.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["AGENT_HOME"] = tempfile.mkdtemp(prefix="ajj-test-")
# The server answers only to this machine's own names (agent/localguard.py),
# and the in-process test client calls itself "testserver".
os.environ.setdefault("AGENT_ALLOWED_HOSTS", "testserver")

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append((name, detail))
    if not cond:
        print(f"FAIL  {name}  {detail}")


def main() -> int:
    # --- it must not need the main app ------------------------------------
    import agent.config as config
    config.AGENT_HOME = Path(os.environ["AGENT_HOME"])
    config.DB_PATH = config.AGENT_HOME / "agent.db"
    import jobs.server as js
    outside = [m for m, mod in sys.modules.items()
               if (getattr(mod, "__file__", "") or "").startswith(str(ROOT)) is False
               and m.startswith(("agent.", "jobs."))]
    check("standalone.every_module_comes_from_this_project", not outside,
          f"{outside}")
    check("standalone.the_heavy_agent_modules_are_absent",
          not any(m in sys.modules for m in
                  ("agent.main", "agent.tools", "agent.blenderlab",
                   "agent.finetune", "agent.crew")))

    # --- the API serves -------------------------------------------------
    from fastapi.testclient import TestClient
    from agent.memory import MemoryStore
    js.memory = MemoryStore(db_path=config.DB_PATH, check_same_thread=False)
    c = TestClient(js.app, raise_server_exceptions=False)
    for p in ("/", "/api/meta", "/api/jobs", "/api/jobs/pipeline",
              "/api/jobs/claims", "/api/jobs/outcomes", "/api/jobs/archive",
              "/api/jobs/auto/preview", "/api/jobs/search/config",
              "/api/jobs/auto/status"):
        check(f"api.{p}", c.get(p).status_code == 200)

    # --- a stranger starts with an empty profile, not the author's -------
    meta = c.get("/api/meta").json()
    check("profile.a_fresh_install_is_not_ready", meta["profile_ready"] is False)
    p = c.get("/api/jobs").json()["profile"]
    check("profile.no_inherited_targets",
          not p.get("target_roles") and not p.get("locations_ok"))

    # --- a real round trip ----------------------------------------------
    c.post("/api/jobs/add", json={"roles": [
        {"title": "Data Engineer", "company": "Acme", "url": "https://x/1",
         "summary": "Python SQL"}]})
    check("flow.a_role_can_be_added_and_read_back",
          [r["title"] for r in c.get("/api/jobs").json()["roles"]]
          == ["Data Engineer"])

    # --- only this app's own page can change anything --------------------
    # Any web page open in your browser can send requests to this port, and
    # the app has no password: a form post from another site was enough to
    # start an auto-apply run.
    r = c.post("/api/jobs/auto/run", headers={
        "origin": "https://evil.example", "sec-fetch-site": "cross-site"})
    check("guard.another_site_cannot_start_auto_apply", r.status_code == 403,
          f"{r.status_code}")
    check("guard.a_name_that_isnt_this_machine_is_refused",
          c.get("/api/meta", headers={"host": "evil.example:8766"}).status_code
          == 403)
    check("guard.the_apps_own_page_still_works",
          c.post("/api/jobs/add", json={"roles": []}, headers={
              "origin": "http://testserver", "sec-fetch-site": "same-origin"})
          .status_code == 200)

    # --- every user-facing endpoint has a way in --------------------------
    srv = (ROOT / "jobs" / "server.py").read_text("utf-8")
    js_ = (ROOT / "web_jobs" / "jobs.js").read_text("utf-8")
    routes = set(re.findall(r'@app\.(?:get|post|delete)\("(/api/jobs[^"]*)"', srv))
    used = set(re.findall(r'"(/api/jobs[a-z0-9/_-]*)"', js_))
    # a route with a path parameter is called as a template literal, so match
    # it by its fixed prefix rather than the literal "{key}"
    missing = set()
    for r in routes:
        if r in used:
            continue
        if "{" in r and r.split("{")[0] in js_:
            continue
        missing.add(r)
    check("ui.every_user_facing_endpoint_has_a_ui",
          missing <= {"/api/jobs/alerts/ingest"}, f"{sorted(missing)}")
    check("ui.reads_never_carry_a_body", 'verb === "GET" ? { method: "GET" }' in js_)

    # --- the icon travels with it ---------------------------------------
    html = (ROOT / "web_jobs" / "index.html").read_text("utf-8")
    check("brand.the_agent_jo_icon_is_used",
          "icons/icon-192.png" in html
          and (ROOT / "web_jobs" / "icons" / "icon-192.png").exists()
          and (ROOT / "agent-jo-jobs.ico").exists())

    # --- windows launchers survive a folder called "x (1)" ---------------
    for bat in ("start.bat", "install.bat"):
        t = (ROOT / bat).read_text("utf-8")
        depth, bad = 0, []
        for i, line in enumerate(t.splitlines(), 1):
            s = line.split("REM")[0]
            if "%~dp0" in s and depth > 0:
                bad.append(i)
            depth += s.count("(") - s.count(")")
        check(f"windows.{bat}_survives_brackets_in_the_path",
              not bad and depth == 0)

    # --- its own app: its own folder, nothing synced from Agent Jo -------
    check("split.nothing_is_vendored_any_more",
          not (ROOT / "VENDORED.json").exists())
    check("split.its_own_data_folder",
          '".agent_jo_jobs"' in (ROOT / "agent" / "config.py").read_text("utf-8"))
    # the first start copies the job data across from Agent Jo's folder —
    # and only copies: Agent Jo's folder is left exactly as it was
    from agent import migrate
    from agent.memory import MemoryStore
    old = Path(tempfile.mkdtemp(prefix="aj-old-")); new = Path(tempfile.mkdtemp(prefix="ajj-new-")) / "home"
    (old / "jobscout").mkdir(parents=True)
    (old / "jobscout" / "roles.json").write_text('[{"key": "r"}]', "utf-8")
    prof = old / "portal" / "browser" / "Default"
    (prof / "Cache").mkdir(parents=True)
    (prof / "Cookies").write_bytes(b"logins")
    (prof / "Cache" / "big").write_bytes(b"x" * 1000)
    (old / "engines.json").write_text("{}", "utf-8")
    (old / "secret.key").write_text("k", "utf-8")
    om = MemoryStore(db_path=old / "agent.db", check_same_thread=False)
    om.create_schedule(name="Job scout — daily", prompt="find and apply",
                       spec_json="{}", action="jobscout", payload="{}")
    om.create_schedule(name="Morning brief", prompt="brief", spec_json="{}")
    om.conn.close()
    r1 = migrate.run(old=old, new=new)
    check("split.the_first_start_copies_the_job_data",
          r1["ran"] and (new / "jobscout" / "roles.json").exists()
          and (new / "portal" / "browser" / "Default" / "Cookies").exists()
          and (new / "secret.key").exists() and (new / "engines.json").exists(),
          f"{r1}")
    check("split.browser_caches_are_left_behind",
          not (new / "portal" / "browser" / "Default" / "Cache").exists())
    nm = MemoryStore(db_path=new / "agent.db", check_same_thread=False)
    runs = [x for x in nm.list_schedules()]
    check("split.the_daily_run_comes_too_and_nothing_else",
          [x["name"] for x in runs] == ["Job scout — daily"]
          and runs[0].get("action") == "jobscout", f"{runs}")
    nm.conn.close()
    check("split.agent_jos_folder_is_left_as_it_was",
          (old / "jobscout" / "roles.json").exists()
          and (old / "portal" / "browser" / "Default" / "Cache" / "big").exists())
    check("split.it_runs_once", migrate.run(old=old, new=new)["ran"] is False)

    # --- the window renders what the server sends -------------------------
    if shutil.which("node"):
        out = subprocess.run(["node", "tests/jobsapp_views.js"], cwd=ROOT,
                             capture_output=True, text=True, timeout=90)
        txt = out.stdout + out.stderr
        for line in ("pipeline draws every stage: true", "roles render: true",
                     "held drafts render: true",
                     "every call hits a known endpoint: true"):
            check("ui." + line.split(":")[0].replace(" ", "_"), line in txt)

    # --- the Windows installer: what it copies, runs and leaves ------------
    iss = (ROOT / "installer" / "AgentJoJobs.iss").read_text("utf-8")
    bat = (ROOT / "installer" / "build_installer.bat").read_text("utf-8")
    check("installer.everything_it_names_exists",
          all((ROOT / f).exists() for f in ("agent-jo-jobs.ico", "LICENSE",
                                            "start.bat", "setup_jobs.py")))
    check("installer.no_administrator_prompt", "PrivilegesRequired=lowest" in iss)
    check("installer.finds_python_without_path",
          "Software\\Python\\PythonCore\\3." in iss and "DownloadTemporaryFile(" in iss)
    check("installer.runs_setup_jobs", "setup_jobs.py'))" in iss)
    check("installer.its_own_identity",
          "24254c5a-0e63-4070-85d4-a6544eb85d8a" in iss and "agent-jo.ico" not in iss
          and "AgentJoJobs-Setup-" in iss and "installer\\AgentJoJobs.iss" in bat)
    dry = subprocess.run([sys.executable, "setup_jobs.py", "--dry-run"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60).stdout
    check("installer.setup_installs_packages_and_the_browser",
          "requirements.txt" in dry and "playwright install chromium" in dry
          and "import jobs.server" in dry)

    # --- the job logic: drafting, sources, portals, auto-apply ------------
    # moved here from Agent Jo's suite when the apps were split
    lg = subprocess.run([sys.executable, "tests/test_logic.py"], cwd=ROOT,
                        capture_output=True, text=True, timeout=1800)
    last = ((lg.stdout or "") + (lg.stderr or "")).strip().splitlines()[-1:]
    check("logic.the_job_logic_checks_pass", lg.returncode == 0, f"{last}")

    print(f"\n{len(PASSED)} checks passed" + (" OK" if not FAILED
                                              else f", {len(FAILED)} failed"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
