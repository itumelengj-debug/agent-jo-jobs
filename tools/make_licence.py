"""Issue licence keys for Agent Jo Jobs (the seller's tool).

    python tools/make_licence.py --make-key
        Once. Writes licence-key.private (KEEP SECRET, never ship or commit)
        and licence-key.pub (ships with the app). From the first release that
        carries licence-key.pub, copies without a key run on the free tier.

    python tools/make_licence.py --name "Thandi Mokoena" --email t@example.com
        Prints a Pro key valid for 365 days. --days 30, or --days 0 for a key
        that never expires. --tier names any tier in agent/tiers.json.

    python tools/make_licence.py --check AJJ1.xxxxx.yyyyy
        Says what a key is.

The buyer pastes the key under Engines -> Licence. Nothing is sent anywhere:
the app checks the signature against licence-key.pub on their computer.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PRIVATE, PUBLIC = ROOT / "licence-key.private", ROOT / "licence-key.pub"


def make_key() -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    if PRIVATE.exists():
        print("licence-key.private already exists. A new one would stop every key "
              "you've issued from working. Delete it by hand only if you mean that.")
        return 1
    k = ed25519.Ed25519PrivateKey.generate()
    PRIVATE.write_bytes(k.private_bytes(encoding=serialization.Encoding.PEM,
                                        format=serialization.PrivateFormat.PKCS8,
                                        encryption_algorithm=serialization.NoEncryption()))
    PUBLIC.write_bytes(k.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    print("Made licence-key.private (keep it secret and backed up; it is not in git) "
          "and licence-key.pub (ship this with the app).")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Issue Agent Jo Jobs licence keys.")
    ap.add_argument("--make-key", action="store_true")
    ap.add_argument("--name", default="")
    ap.add_argument("--email", default="")
    ap.add_argument("--tier", default="pro")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--check", default="")
    a = ap.parse_args(argv)
    from agent import license as lic
    if a.make_key:
        return make_key()
    if a.check:
        print(lic.read(a.check))
        return 0
    if not PRIVATE.exists():
        print("No licence-key.private here. Run  python tools/make_licence.py --make-key  first.")
        return 1
    if not (a.name or a.email):
        print("Say who the key is for: --name and/or --email.")
        return 1
    if a.tier not in lic.tiers():
        print(f"No tier called {a.tier!r} in agent/tiers.json ({', '.join(lic.tiers())}).")
        return 1
    print(lic.issue(PRIVATE.read_bytes(), a.name, a.email, a.tier, a.days or None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
