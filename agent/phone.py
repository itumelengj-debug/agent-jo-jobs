"""The phone companion: the decisions only you can make, from your phone.

The autonomous runs stall on you — a question only you can answer holds up
three forms, a draft waits for your yes — and you're not at the desk. This
serves a small page to your phone with exactly those decisions and nothing
else:

  * answer the questions applications are waiting on;
  * approve a draft (it may then go out on the next run, if your level sends)
    or skip the role;
  * see your interviews coming up and what the last run did;
  * pause everything — the level drops to "draft only" — in one tap.

It can't browse your roles, read your CV or profile, change settings, or
send anything itself. It is OFF until you turn it on.

How it's kept to you:

  * a separate small listener (port 8767), not the main app — the main app
    still answers only to this computer;
  * a 192-bit key in the address's #fragment, which browsers never send over
    the network or put in logs; the page sends it in a header on each call,
    compared in constant time. A wrong key ten times in ten minutes locks
    that address out for ten minutes;
  * no cookies, no CORS, so another website can't act through your phone's
    browser; strict content security policy, no framing;
  * every action is written to the audit log as "phone".

On your home Wi-Fi the traffic isn't encrypted (there's no certificate for a
home address), so anyone on the same network who can watch it could read a
question and answer in transit. For use away from home, or on shared Wi-Fi,
use Tailscale (free): your phone reaches the PC over an encrypted link, and
its address is listed here too. Change the key any time; the old one stops
working at once.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config

DEFAULT_PORT = 8767
MAX_BODY = 64 * 1024
LOCK_AFTER, LOCK_WINDOW = 10, 600
STATIC = Path(__file__).resolve().parents[1] / "web_phone"
_SERVER = {"httpd": None, "thread": None, "port": None, "error": ""}
_FAILS: dict = {}
_LOCK = threading.Lock()


# --- settings -------------------------------------------------------------- #
def _path() -> Path:
    d = config.AGENT_HOME / "jobscout"
    d.mkdir(parents=True, exist_ok=True)
    return d / "phone.json"


def settings() -> dict:
    try:
        s = json.loads(_path().read_text("utf-8"))
    except Exception:
        s = {}
    return {"enabled": False, "port": DEFAULT_PORT, "key": "", **s}


def _save(s: dict) -> None:
    p = _path()
    p.write_text(json.dumps(s, indent=1), "utf-8")
    try:
        os.chmod(p, 0o600)            # the key is a password
    except Exception:
        pass


def new_key() -> str:
    return secrets.token_urlsafe(24)


def addresses() -> list:
    """This computer's addresses a phone could reach: the LAN one, and a
    Tailscale one (100.x) when Tailscale is running."""
    out = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))      # no packet is sent
            out.append(s.getsockname()[0])
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    except Exception:
        pass
    ts = [ip for ip in out if ip.startswith("100.")]
    lan = [ip for ip in out if not ip.startswith("100.")]
    return [{"ip": ip, "kind": "tailscale"} for ip in ts] + [{"ip": ip, "kind": "wifi"} for ip in lan]


def status() -> dict:
    s = settings()
    running = _SERVER["httpd"] is not None
    port = _SERVER["port"] or s["port"]
    links = []
    if s["enabled"] and s["key"]:
        for a in addresses():
            url = f"http://{a['ip']}:{port}/#k={s['key']}"
            item = {"url": url, "kind": a["kind"], "ip": a["ip"]}
            try:
                from . import qr
                item["qr"] = qr.svg(url, scale=5)
            except Exception:
                item["qr"] = ""
            links.append(item)
    return {"enabled": s["enabled"], "running": running, "port": port,
            "links": links, "error": _SERVER["error"]}


def set_enabled(on: bool) -> dict:
    s = settings()
    s["enabled"] = bool(on)
    if on and not s["key"]:
        s["key"] = new_key()
    _save(s)
    _audit(f"phone companion turned {'on' if on else 'off'}")
    if on:
        start()
    else:
        stop()
    return status()


def rotate_key() -> dict:
    s = settings()
    s["key"] = new_key()
    _save(s)
    _audit("phone companion key changed — the old address no longer works")
    return status()


def _audit(text: str) -> None:
    try:
        from . import jobscout
        jobscout._audit("phone", text)
    except Exception:
        pass


# --- what the phone may see and do --------------------------------------- #
def state() -> dict:
    from . import jobscout, answerbank, interviews
    cfg = jobscout.auto_config()
    waiting = []
    for r in jobscout.roles():
        d = r.get("draft") or {}
        if r.get("stage") != "drafted" or not d.get("body") or r.get("sent_at"):
            continue
        held = (d.get("check") or {}).get("ok") is False
        waiting.append({"key": r["key"], "title": r.get("title", ""), "company": r.get("company", ""),
                        "fit": (r.get("fit") or {}).get("score"), "subject": d.get("subject", ""),
                        "body": d.get("body", "")[:6000], "approved": bool(r.get("approved")),
                        "held": held,
                        "problems": [p.get("detail", "") for p in (d.get("check") or {}).get("problems", [])][:5],
                        "how": "email" if (r.get("apply_email") or "").strip() else "form"})
    waiting.sort(key=lambda x: (x["approved"], x["held"], -(x["fit"] or 0)))
    runs = jobscout.run_reports(1)
    last = runs[0] if runs else None
    return {"questions": [{"question": q["question"], "roles": len(q.get("roles") or [])}
                          for q in answerbank.open_questions()[:20]],
            "drafts": waiting[:25],
            "interviews": interviews.upcoming(jobscout.roles())[:6],
            "last_run": ({"at": last.get("at", ""), "said": last.get("said") or last.get("summary", "")}
                         if last else None),
            "level": cfg.get("level"), "level_says": jobscout.AUTONOMY_SAYS.get(cfg.get("level"), ""),
            "sends": bool(cfg.get("enabled")) and cfg.get("level") in ("email", "full")}


def answer(question: str, text: str) -> dict:
    from . import answerbank
    question, text = (question or "").strip()[:500], (text or "").strip()[:4000]
    if not question or not text:
        return {"ok": False, "error": "Type an answer first."}
    if not any(q["question"] == question for q in answerbank.open_questions()):
        return {"ok": False, "error": "That question isn't waiting any more."}
    res = answerbank.answer_open(question, text)
    _audit(f"answered “{question[:80]}”")
    return {"ok": bool(res.get("ok")), **({"error": res.get("error")} if not res.get("ok") else {})}


def approve(key: str) -> dict:
    from . import jobscout
    r = jobscout.get_role(key)
    if r is None or r.get("stage") != "drafted" or not (r.get("draft") or {}).get("body"):
        return {"ok": False, "error": "That draft isn't waiting any more."}
    if ((r.get("draft") or {}).get("check") or {}).get("ok") is False:
        return {"ok": False, "error": "It claims something your profile can't back — fix that at "
                                      "your computer first."}
    jobscout.update_role(key, approved=True, approved_at=jobscout._iso(), approved_from="phone")
    _audit(f"approved {r.get('title', '')} @ {r.get('company', '')}")
    cfg = jobscout.auto_config()
    if (r.get("apply_email") or "").strip() and cfg.get("enabled") and cfg.get("level") in ("email", "full"):
        then = "It goes out on the next run."
    elif (r.get("apply_email") or "").strip():
        then = "Approved. At your current level nothing is sent automatically — send it from your computer."
    else:
        then = "Approved. It applies through a company form, which waits for you at your computer."
    return {"ok": True, "then": then}


def skip(key: str) -> dict:
    from . import jobscout
    r = jobscout.get_role(key)
    if r is None:
        return {"ok": False, "error": "No such role."}
    jobscout.set_stage(key, "closed", "skipped from your phone")
    _audit(f"skipped {r.get('title', '')} @ {r.get('company', '')}")
    return {"ok": True}


def pause() -> dict:
    from . import jobscout
    res = jobscout.set_autonomy("draft")
    _audit("paused from the phone: level set to draft only")
    return {"ok": bool(res.get("ok")), "level": "draft"}


# --- the listener ------------------------------------------------------------ #
def _locked_out(ip: str) -> bool:
    now = time.time()
    with _LOCK:
        recent = [t for t in _FAILS.get(ip, []) if now - t < LOCK_WINDOW]
        _FAILS[ip] = recent
        return len(recent) >= LOCK_AFTER


def _failed(ip: str) -> None:
    with _LOCK:
        _FAILS.setdefault(ip, []).append(time.time())


_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml",
          ".webmanifest": "application/manifest+json"}
_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                               "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY", "Cache-Control": "no-store",
}


class _Handler(BaseHTTPRequestHandler):
    server_version = "AgentJoPhone"
    sys_version = ""

    def log_message(self, *a):          # no request log: nothing to leak
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in _HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, data: dict) -> None:
        self._send(code, json.dumps(data).encode("utf-8"))

    def _authorised(self) -> bool:
        ip = self.client_address[0]
        if _locked_out(ip):
            self._json(429, {"error": "Too many wrong keys — try again in ten minutes."})
            return False
        key = settings()["key"]
        got = self.headers.get("X-Phone-Key", "")
        if not key or not got or not hmac.compare_digest(got.encode(), key.encode()):
            _failed(ip)
            self._json(401, {"error": "This link's key isn't valid any more. Scan the code "
                                      "again from Agent Jo Jobs on your computer."})
            return False
        return True

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            if not self._authorised():
                return
            if path == "/api/state":
                return self._json(200, state())
            return self._json(404, {"error": "not found"})
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        f = (STATIC / name).resolve()
        if not str(f).startswith(str(STATIC.resolve())) or not f.is_file() \
                or f.suffix not in _TYPES:
            return self._send(404, b"not found", "text/plain")
        self._send(200, f.read_bytes(), _TYPES[f.suffix])

    def do_POST(self):
        if not self._authorised():
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            return self._json(413, {"error": "too large"})
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self._json(415, {"error": "JSON only"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad request"})
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/answer":
                res = answer(body.get("question", ""), body.get("answer", ""))
            elif path == "/api/approve":
                res = approve(str(body.get("key", "")))
            elif path == "/api/skip":
                res = skip(str(body.get("key", "")))
            elif path == "/api/pause":
                res = pause()
            else:
                return self._json(404, {"error": "not found"})
        except Exception as exc:
            return self._json(500, {"error": f"{type(exc).__name__}"})
        self._json(200 if res.get("ok") else 400, res)


def start(port: int | None = None, host: str = "0.0.0.0") -> dict:
    """Start the listener if it's switched on. Safe to call twice."""
    s = settings()
    if not s["enabled"] or not s["key"]:
        return status()
    if _SERVER["httpd"] is not None:
        return status()
    p = int(port or s.get("port") or DEFAULT_PORT)
    try:
        httpd = ThreadingHTTPServer((host, p), _Handler)
    except OSError as exc:
        _SERVER["error"] = (f"Port {p} is in use or not allowed ({exc.strerror or exc}). "
                            "Close whatever uses it, or change the port in phone.json.")
        return status()
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    _SERVER.update(httpd=httpd, thread=t, port=httpd.server_address[1], error="")
    return status()


def stop() -> None:
    h = _SERVER.get("httpd")
    if h is not None:
        h.shutdown()
        h.server_close()
    _SERVER.update(httpd=None, thread=None, port=None)
