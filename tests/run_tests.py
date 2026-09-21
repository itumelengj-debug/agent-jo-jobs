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
              "/api/jobs/auto/preview", "/api/jobs/search/config"):
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

    # --- every user-facing endpoint has a way in --------------------------
    srv = (ROOT / "jobs" / "server.py").read_text("utf-8")
    js_ = (ROOT / "web_jobs" / "jobs.js").read_text("utf-8")
    routes = set(re.findall(r'@app\.(?:get|post|delete)\("(/api/jobs[^"]*)"', srv))
    used = set(re.findall(r'"(/api/jobs[a-z0-9/_-]*)"', js_))
    check("ui.every_user_facing_endpoint_has_a_ui",
          (routes - used) <= {"/api/jobs/alerts/ingest"}, f"{sorted(routes - used)}")
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

    # --- the vendored modules say where they came from --------------------
    v = json.loads((ROOT / "VENDORED.json").read_text("utf-8"))
    check("vendored.the_manifest_names_its_source_build",
          bool(v.get("from_build")) and len(v.get("files", {})) >= 10)

    # --- the window renders what the server sends -------------------------
    if shutil.which("node"):
        out = subprocess.run(["node", "tests/jobsapp_views.js"], cwd=ROOT,
                             capture_output=True, text=True, timeout=90)
        txt = out.stdout + out.stderr
        for line in ("pipeline draws every stage: true", "roles render: true",
                     "held drafts render: true",
                     "every call hits a known endpoint: true"):
            check("ui." + line.split(":")[0].replace(" ", "_"), line in txt)

    print(f"\n{len(PASSED)} checks passed" + (" OK" if not FAILED
                                              else f", {len(FAILED)} failed"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
