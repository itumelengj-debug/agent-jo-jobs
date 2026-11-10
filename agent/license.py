"""Licence keys — a free tier with limits, and a paid tier a key unlocks.

A key is a short signed statement: who it is for, which tier, until when. It
is signed with a private key only the seller holds and checked against the
public key that ships with the app (licence-key.pub), entirely on this
computer: no account, no server, nothing sent anywhere. A key can't be
forged or altered without the private key, and an expired one drops back to
the free tier without touching anyone's data.

What each tier allows is in agent/tiers.json, in plain numbers, for the
seller to edit.

Until the seller has made a key pair there is nothing to check keys against,
so a copy with no licence-key.pub is fully unlocked. Selling starts the day
that file ships, not before.

    python tools/make_licence.py --make-key           (once; keep the private half secret)
    python tools/make_licence.py --name "A Buyer" --email a@b.c --days 365
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

from . import config

ROOT = Path(__file__).resolve().parent.parent
PUBKEY = ROOT / "licence-key.pub"
PREFIX = "AJJ1"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def tiers() -> dict:
    try:
        d = json.loads((Path(__file__).parent / "tiers.json").read_text("utf-8"))
    except Exception:
        d = {}
    d.setdefault("free", {"label": "Free", "daily_cap": 5, "run_every_hours": [0],
                          "submit_forms": False, "follow_ups": False, "tailored_cv": False})
    d.setdefault("pro", {"label": "Pro"})
    return {k: v for k, v in d.items() if isinstance(v, dict)}


def enforced() -> bool:
    """Is this a copy keys are checked on? Only one that carries the
    seller's public key."""
    return PUBKEY.is_file()


def _path() -> Path:
    return config.AGENT_HOME / "licence.json"


def issue(private_pem: bytes, name: str, email: str = "", tier: str = "pro",
          days: int | None = 365, now: datetime | None = None) -> str:
    """Make a key (the seller's side; tools/make_licence.py calls this)."""
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(private_pem, password=None)
    now = now or datetime.now(timezone.utc)
    body = {"n": name.strip()[:80], "e": email.strip()[:120], "t": tier,
            "i": now.strftime("%Y-%m-%d")}
    if days:
        from datetime import timedelta
        body["x"] = (now + timedelta(days=int(days))).strftime("%Y-%m-%d")
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"{PREFIX}.{_b64(raw)}.{_b64(key.sign(raw))}"


def read(key: str, public_pem: bytes | None = None, now: datetime | None = None) -> dict:
    """Check one key: {'ok', 'tier', 'name', 'email', 'expires', 'error'}."""
    key = "".join(str(key or "").split())
    parts = key.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        return {"ok": False, "error": "That doesn't look like a licence key. Paste the whole key, "
                                      "starting AJJ1."}
    try:
        raw, sig = _unb64(parts[1]), _unb64(parts[2])
        from cryptography.hazmat.primitives import serialization
        pub = serialization.load_pem_public_key(public_pem or PUBKEY.read_bytes())
        pub.verify(sig, raw)
        body = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return {"ok": False, "error": "This copy has no licence-key.pub to check keys against."}
    except Exception:
        return {"ok": False, "error": "That key isn't valid for this app. Check it was pasted "
                                      "whole, with nothing added."}
    tier = str(body.get("t") or "pro")
    if tier not in tiers():
        return {"ok": False, "error": f"That key is for a tier this version doesn't have ({tier})."}
    exp = str(body.get("x") or "")
    today = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    out = {"ok": True, "tier": tier, "name": body.get("n", ""), "email": body.get("e", ""),
           "expires": exp, "issued": body.get("i", "")}
    if exp and exp < today:
        return {**out, "ok": False, "expired": True,
                "error": f"That key expired on {exp}. Your data and settings are untouched; "
                         f"the free limits apply until it's renewed."}
    return out


def activate(key: str) -> dict:
    r = read(key)
    if not r.get("ok"):
        return r
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"key": "".join(key.split())}), "utf-8")
    return {**r, **status()}


def deactivate() -> dict:
    try:
        _path().unlink()
    except FileNotFoundError:
        pass
    return status()


def status() -> dict:
    """The tier in force and what it allows."""
    t = tiers()
    if not enforced():
        return {"enforced": False, "tier": "pro", "label": "Unlocked",
                "says": "Every feature is unlocked in this copy.", "limits": t.get("pro", {})}
    try:
        key = json.loads(_path().read_text("utf-8")).get("key", "")
    except Exception:
        key = ""
    r = read(key) if key else {"ok": False}
    tier = r["tier"] if r.get("ok") else "free"
    lim = t.get(tier, {})
    if r.get("ok"):
        says = (f"{lim.get('label', tier.title())} licence for {r.get('name') or r.get('email') or 'you'}"
                + (f", until {r['expires']}." if r.get("expires") else "."))
    elif r.get("expired"):
        says = r["error"]
    else:
        cap = lim.get("daily_cap")
        says = (f"Free version: up to {cap} applications a day, one run a day. "
                f"A licence key removes the limits." if cap else "Free version.")
    return {"enforced": True, "tier": tier, "label": lim.get("label", tier.title()), "says": says,
            "limits": lim, "name": r.get("name", ""), "expires": r.get("expires", ""),
            "expired": bool(r.get("expired"))}


def limit(name: str, default=None):
    """One limit of the tier in force; None means unlimited/allowed."""
    try:
        st = status()
        if not st["enforced"]:
            return default
        v = st["limits"].get(name, default)
        return default if v is None else v
    except Exception:
        return default


def allows(feature: str) -> bool:
    v = limit(feature, True)
    return bool(v) if isinstance(v, bool) else True


def schedule_ok(every_hours: int) -> bool:
    allowed = limit("run_every_hours")
    return allowed is None or int(every_hours) in [int(x) for x in allowed]
