"""Build a release of Agent Jo Jobs: one zip, signed, plus latest.json.

    python tools/make_release.py

Writes dist/AgentJoJobs-<build>.zip and, when signing-key.private exists,
signs a manifest of exactly the files in the zip (MANIFEST.sha256,
MANIFEST.sig and signing-key.pub go inside it) and writes dist/latest.json
for the in-app updater (agent/updater.py). Upload both to the same place
and paste latest.json's address under Engines → Updates.

No key yet? Make one once:  python tools/make_release.py --make-key
Keep signing-key.private safe and out of the repository: anyone holding it
can sign an update as you.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST, SIGNATURE, PUBKEY = "MANIFEST.sha256", "MANIFEST.sig", "signing-key.pub"
KEYFILE = ROOT / "signing-key.private"
SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", "dist", "build",
             ".update", ".github", "installer", "node_modules", ".pytest_cache"}
SKIP_NAMES = {"signing-key.private", MANIFEST, SIGNATURE, "install.log",
              "install-report.json"}
SKIP_SUFFIX = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".zip"}
LEAK = [(re.compile(rb"sk-ant-[A-Za-z0-9_\-]{10,}"), "an Anthropic API key"),
        (re.compile(rb"sk-proj-[A-Za-z0-9_\-]{10,}"), "an OpenAI key"),
        # written so this file doesn't match itself: the plain marker here
        # once made every build of the release tool fail its own scan
        (re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "a private key")]


def build_id() -> str:
    m = re.search(r'BUILD_ID = "([^"]+)"', (ROOT / "agent" / "config.py").read_text("utf-8"))
    return m.group(1) if m else ""


def collect() -> list:
    out = []
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if not p.is_file() or any(x in SKIP_DIRS for x in rel.parts):
            continue
        if p.name in SKIP_NAMES or p.suffix.lower() in SKIP_SUFFIX:
            continue
        out.append(rel)
    return out


def make_key() -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    if KEYFILE.exists():
        print("signing-key.private already exists; a new key would orphan every "
              "copy that trusts the old one.")
        return 1
    k = ed25519.Ed25519PrivateKey.generate()
    KEYFILE.write_bytes(k.private_bytes(encoding=serialization.Encoding.PEM,
                                        format=serialization.PrivateFormat.PKCS8,
                                        encryption_algorithm=serialization.NoEncryption()))
    (ROOT / PUBKEY).write_bytes(k.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    print("Made signing-key.private (keep it secret, keep it out of git) and "
          "signing-key.pub (ships with the app).")
    return 0


def sign_files(files: list) -> dict:
    if not KEYFILE.exists():
        return {}
    from cryptography.hazmat.primitives import serialization
    entries = {str(r).replace("\\", "/"): hashlib.sha256((ROOT / r).read_bytes()).hexdigest()
               for r in files}
    man = json.dumps({"created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                      "build": build_id(), "files": len(entries), "entries": entries},
                     indent=2, sort_keys=True).encode("utf-8")
    key = serialization.load_pem_private_key(KEYFILE.read_bytes(), password=None)
    pub = key.public_key().public_bytes(encoding=serialization.Encoding.PEM,
                                        format=serialization.PublicFormat.SubjectPublicKeyInfo)
    return {MANIFEST: man, SIGNATURE: key.sign(man), PUBKEY: pub}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--make-key" in argv:
        return make_key()
    files = [f for f in collect() if str(f).replace("\\", "/") != PUBKEY]
    signed = sign_files(files)
    stamp = re.sub(r"[^0-9]", "", build_id())[:12] or datetime.now().strftime("%Y%m%d%H%M")
    out = ROOT / "dist"; out.mkdir(exist_ok=True)
    zp = out / f"AgentJoJobs-{stamp}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for r in files:
            data = (ROOT / r).read_bytes()
            for rx, what in LEAK:
                if rx.search(data):
                    z.close(); zp.unlink()
                    print(f"BUILD FAILED: {r} contains {what}.")
                    return 1
            z.writestr(str(r).replace("\\", "/"), data)
        for n, b in signed.items():
            z.writestr(n, b)
    print(f"Packaged {len(files)} files -> {zp.name}")
    if not signed:
        print("NOT signed (no signing-key.private): the in-app updater will refuse "
              "it. Run  python tools/make_release.py --make-key  once.")
        return 0
    base = os.environ.get("AGENT_JO_RELEASE_BASE", "").rstrip("/")
    latest = {"build": build_id(), "url": (base + "/" if base else "") + zp.name,
              "sha256": hashlib.sha256(zp.read_bytes()).hexdigest(),
              "size": zp.stat().st_size, "notes": "See CHANGELOG.md for what changed."}
    (out / "latest.json").write_text(json.dumps(latest, indent=2), "utf-8")
    print(f"Signed. Upload {zp.name} and latest.json to the same place.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
