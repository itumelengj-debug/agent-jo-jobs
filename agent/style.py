"""Learning how you write, from the drafts you correct.

Every draft you edit before sending says something the engine couldn't know:
you cut the opening flattery, you always open and sign off the same way, you keep
letters to about 180 words. Correcting the same things every time is what
makes "autonomous" feel like supervising. So each edit is kept (before and
after), and rules are worked out from them — locally, no engine:

  * length: when your edits consistently shorten (or lengthen) drafts, the
    length you keep becomes the target;
  * sentences you cut: the kind of sentence you removed from two or more
    drafts (the "I am writing to express my keen interest…" kind) is not
    written again;
  * the opening and sign-off you keep using.

A rule needs two edits agreeing, so one odd edit teaches nothing. You can
see every rule, with how many edits back it, and forget any of them. The
rules go into the drafting prompt as YOUR STYLE; they never override the
fabrication guard — a sign-off can be added, a qualification can't.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from pathlib import Path

from . import config

KEEP = 60
MIN_EVIDENCE = 2
_W = re.compile(r"[A-Za-z0-9'’+#.-]+")
# common words a 3-word phrase may not consist only of
_FILLER = set("""a an and the of to in for on at with by is are was be i you we it this that
my your our as or from me us so if do have has had will would can could""".split())


def _dir() -> Path:
    d = config.AGENT_HOME / "jobscout" / "style"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(name: str, default):
    try:
        return json.loads((_dir() / name).read_text("utf-8"))
    except Exception:
        return default


def _write(name: str, data) -> None:
    p = _dir() / name
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), "utf-8")
    tmp.replace(p)


def _words(t: str) -> list:
    return [w.lower().strip(".’'") for w in _W.findall(t or "")]


def _grams(t: str, n: int = 3) -> set:
    w = _words(t)
    out = set()
    for i in range(len(w) - n + 1):
        g = w[i:i + n]
        if all(x in _FILLER for x in g):
            continue
        out.add(" ".join(g))
    return out


def _sentences(t: str) -> list:
    out = []
    for para in (t or "").replace("\r", "").split("\n"):
        out += [x.strip() for x in re.split(r"(?<=[.!?])\s+", para) if len(x.split()) >= 5]
    return out


def _lines(t: str) -> list:
    return [l.strip() for l in (t or "").replace("\r", "").split("\n") if l.strip()]


def edits() -> list:
    return _read("edits.json", [])


def record(before: str, after: str, *, key: str = "", subject_before: str = "",
           subject_after: str = "") -> dict:
    """Keep one edit. A change of nothing but whitespace isn't one."""
    if re.sub(r"\s+", " ", before or "").strip() == re.sub(r"\s+", " ", after or "").strip() \
            and (subject_before or "") == (subject_after or ""):
        return {"ok": True, "recorded": False}
    e = edits()
    # editing the same draft again replaces that edit: one letter worked on
    # three times is still one letter's evidence, not three
    e = [x for x in e if not (key and x.get("key") == key and x.get("before") == (before or "")[:8000])]
    e.append({"at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "key": key,
              "before": (before or "")[:8000], "after": (after or "")[:8000],
              "subject_before": subject_before[:300], "subject_after": subject_after[:300]})
    _write("edits.json", e[-KEEP:])
    return {"ok": True, "recorded": True, "edits": len(e[-KEEP:])}


def rules() -> list:
    """[{id, kind, text, evidence}] learned from the edits, minus forgotten ones."""
    e = edits()
    out = []
    if len(e) >= MIN_EVIDENCE:
        ratios, kept = [], []
        for x in e:
            b, a = len(_words(x["before"])), len(_words(x["after"]))
            if b >= 30 and a:
                ratios.append(a / b)
                kept.append(a)
        if len(ratios) >= MIN_EVIDENCE:
            r = statistics.median(ratios)
            target = int(round(statistics.median(kept), -1))
            shorter = sum(1 for x in ratios if x < 0.85)
            longer = sum(1 for x in ratios if x > 1.15)
            if r < 0.85 and shorter >= MIN_EVIDENCE:
                out.append({"id": "length", "kind": "length", "evidence": shorter,
                            "text": f"Keep the letter to about {target} words — you cut drafts "
                                    f"to roughly {int(r * 100)}% of their length."})
            elif r > 1.15 and longer >= MIN_EVIDENCE:
                out.append({"id": "length", "kind": "length", "evidence": longer,
                            "text": f"Write about {target} words — you lengthen short drafts."})

        # sentences you cut: a sentence of the draft that's gone from your
        # version, cut from two or more drafts (matched loosely, since the
        # engine words the same flattery a little differently each time)
        groups = []                       # [[sentence, grams, edits-set]]
        for i, x in enumerate(e):
            ga = _grams(x["after"])
            for sent in _sentences(x["before"]):
                g = _grams(sent)
                if len(g) < 3 or len(g & ga) > 0.3 * len(g):
                    continue
                for grp in groups:
                    if len(g & grp[1]) >= 0.5 * min(len(g), len(grp[1])):
                        grp[2].add(i)
                        break
                else:
                    groups.append([sent, g, {i}])
        groups.sort(key=lambda grp: -len(grp[2]))
        for sent, _, seen_in in groups[:5]:
            if len(seen_in) < MIN_EVIDENCE:
                break
            short = " ".join(sent.split()[:9]) + ("…" if len(sent.split()) > 9 else "")
            out.append({"id": "cut:" + " ".join(sent.lower().split()[:9]), "kind": "cut",
                        "evidence": len(seen_in),
                        "text": f"Don't write sentences like “{short}” — you cut one from "
                                f"{len(seen_in)} drafts."})
        # (phrases you ADD aren't turned into rules: what you add to a letter
        # is usually a fact about you for that role, and a rule must never
        # carry a claim from one letter into another. The opening and the
        # sign-off, below, are the exception.)

        for which, idx in (("open", 0), ("close", -1)):
            seen = {}
            for x in e:
                ls = _lines(x["after"])
                if not ls:
                    continue
                # a sign-off is usually two lines: "Kind regards," / "Name"
                line = ls[idx] if which == "open" else " / ".join(ls[-2:]) if len(ls) >= 2 else ls[-1]
                if len(line) <= 80:
                    seen[line] = seen.get(line, 0) + 1
            if seen:
                line, n = max(seen.items(), key=lambda x: x[1])
                if n >= MIN_EVIDENCE:
                    out.append({"id": which, "kind": which, "evidence": n,
                                "text": ("Open with" if which == "open" else "End with")
                                        + f" “{line}” — as in {n} of your edits."})
    gone = set(_read("forgotten.json", []))
    return [r for r in out if r["id"] not in gone]


def forget(rule_id: str) -> dict:
    gone = _read("forgotten.json", [])
    if rule_id not in gone:
        gone.append(rule_id)
    _write("forgotten.json", gone[-200:])
    return {"ok": True, "rules": rules()}


def reset() -> dict:
    """Forget every edit and rule."""
    for n in ("edits.json", "forgotten.json"):
        try:
            (_dir() / n).unlink()
        except FileNotFoundError:
            pass
    return {"ok": True}


def prompt_clause(skip: tuple = ()) -> str:
    """The learned rules, for the drafting prompt. "" when there are none.
    A follow-up skips the length rule: it's four sentences, not a letter."""
    rs = [r for r in rules() if r["kind"] not in skip]
    if not rs:
        return ""
    return ("\nYOUR STYLE — learned from how the candidate edits drafts; follow it, "
            "but never let it add a claim the PROFILE doesn't support:\n"
            + "\n".join("- " + r["text"].split(" — ")[0] for r in rs))


def summary() -> dict:
    return {"edits": len(edits()), "rules": rules(), "needs": MIN_EVIDENCE}
