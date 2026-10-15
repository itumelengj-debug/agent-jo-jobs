"""A website in memory, for checking the navigator without a browser.

Each page is a dict: its boxes ("controls"), its buttons and what pressing
them does, its text, whether a cookie banner, a sign-in or a captcha is on
it. FakeSite speaks the driver protocol the navigator uses (open, snapshot,
act, shot, close_page, close, companion) and records what was clicked,
typed and submitted. FakeBrain plays the engine: a scripted policy for the
navigator's turns, and canned answers for questions from the profile.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace as _NS


class FakePage:
    def __init__(self, url: str):
        self.url = url
        self.closed = False

    def __repr__(self):
        return f"<FakePage {self.url}>"


class FakeSite:
    def __init__(self, pages: dict):
        self.pages = pages
        self.state: dict = {}
        self.submitted = False
        self.clicks: list = []           # (url, text)
        self.typed: dict = {}            # control id -> value
        self.chosen: dict = {}           # control id -> option
        self.uploaded: dict = {}         # control id -> file name
        self.ticked: list = []           # checkbox ids ticked
        self.banner_clicks: list = []
        self.open_pages: list = []
        self.closed: list = []
        self.snapshots = 0
        self.companion_data = None
        self.kept_open = None
        self._refs: dict = {}
        self._back: dict = {}

    # --- the driver protocol ---------------------------------------------
    def open(self, url):
        p = FakePage(url)
        self.open_pages.append(p)
        self._back[id(p)] = []
        return p

    def html(self, page):
        return (self.pages.get(page.url) or {}).get("html", "<html><body></body></html>")

    def fields(self, page):
        return []

    def settle(self, page, timeout_ms=0):
        return True

    def shot(self, page, name):
        return ""

    def close(self, keep_open=True):
        self.kept_open = keep_open

    def close_page(self, page):
        page.closed = True
        self.closed.append(page.url)

    def companion(self, page, data):
        self.companion_data = data
        return True

    # --- the site ---------------------------------------------------------
    def _st(self, url):
        return self.state.setdefault(url, {"values": {}, "errors": [], "revealed": set(),
                                           "scrolled": False, "banner": True})

    def _spec(self, page):
        spec = self.pages.get(page.url)
        if spec is None:
            spec = {"title": "Not found", "text": "The page you are looking for could not be found"}
        return spec

    def snapshot(self, page):
        self.snapshots += 1
        spec, st = self._spec(page), self._st(page.url)
        refs, n = {}, [0]

        def ref(kind, cid):
            r = f"0:{n[0]}"
            n[0] += 1
            refs[r] = (kind, cid)
            return r
        controls = []
        for c in spec.get("controls") or []:
            if c.get("hidden") and c["id"] not in st["revealed"]:
                continue
            k = c["kind"]
            item = {"kind": k, "label": c.get("label", ""), "hint": c.get("hint", ""),
                    "required": bool(c.get("required")), "type": c.get("type", "text")}
            v = st["values"].get(c["id"])
            if k in ("radio", "checkgroup"):
                item["options"] = [{"text": o, "ref": ref("opt", (c["id"], o)),
                                    "checked": (v == o) if k == "radio" else o in (v or [])}
                                   for o in c["options"]]
                item["ref"] = item["options"][0]["ref"]
                item["value"] = v if k == "radio" else "; ".join(v or [])
            else:
                item["ref"] = ref("ctl", c["id"])
                if k == "checkbox":
                    item["value"] = "on" if v else ""
                else:
                    item["value"] = v or ""
                if k == "select":
                    item["options"] = list(c["options"])
            controls.append(item)
        buttons = []
        for b in spec.get("buttons") or []:
            if b.get("lazy") and not st["scrolled"]:
                continue
            if b.get("hidden") and b.get("id") not in st["revealed"]:
                continue
            buttons.append({"ref": ref("btn", b.get("id") or b["text"]), "kind": b.get("kind", "button"),
                            "text": b["text"], "href": b.get("href", ""), "target": b.get("target", ""),
                            "type": b.get("type", ""), "in_form": bool(b.get("in_form")),
                            "nav": bool(b.get("nav")), "banner": False, "label": ""})
        if spec.get("banner") and st["banner"]:
            for t in spec["banner"]:
                buttons.append({"ref": ref("banner", t), "kind": "button", "text": t, "href": "",
                                "target": "", "type": "", "in_form": False, "nav": False,
                                "banner": True, "label": ""})
        self._refs[id(page)] = refs
        return {"url": page.url, "title": spec.get("title", ""), "controls": controls,
                "buttons": buttons, "headings": list(spec.get("headings") or []),
                "errors": list(st["errors"]), "text": spec.get("text", ""),
                "password": bool(spec.get("password")) and not st.get("signed_in"),
                "captcha": bool(spec.get("captcha")) and not st.get("solved"),
                "captcha_badge": False, "cookie": bool(spec.get("banner") and st["banner"]),
                "frames": []}

    def _control(self, spec, cid):
        return next(c for c in spec.get("controls") or [] if c["id"] == cid)

    def _validate(self, spec, st) -> list:
        errs = []
        for c in spec.get("controls") or []:
            if c.get("hidden") and c["id"] not in st["revealed"]:
                continue
            v = st["values"].get(c["id"])
            if c.get("required") and not v:
                errs.append(f"{c.get('label', c['id'])} is required")
            elif v and c.get("validate") and not re.match(c["validate"], str(v)):
                errs.append(c.get("error") or f"{c.get('label', c['id'])} is invalid")
        return errs

    def act(self, page, action):
        do, ref = action.get("do"), str(action.get("ref") or "")
        out = {"ok": False, "page": page, "new_tab": False, "navigated": False, "chosen": "", "error": ""}
        spec, st = self._spec(page), self._st(page.url)
        if do == "scroll":
            st["scrolled"] = True
            out["ok"] = True
            return out
        if do == "back":
            hist = self._back.get(id(page)) or []
            if hist:
                page.url = hist.pop()
                out.update(ok=True, navigated=True)
            return out
        refs = self._refs.get(id(page)) or {}
        if ref not in refs:
            out["error"] = "stale ref"
            return out
        kind, cid = refs[ref]
        if do == "click":
            if kind == "banner":
                self.banner_clicks.append(cid)
                st["banner"] = False
                out["ok"] = True
                return out
            if kind != "btn":
                out["error"] = "not a button"
                return out
            b = next(b for b in spec.get("buttons") or [] if (b.get("id") or b["text"]) == cid)
            self.clicks.append((page.url, b["text"]))
            out["ok"] = True
            if b.get("reveal"):
                st["revealed"].update(b["reveal"])
            if b.get("check"):
                errs = self._validate(spec, st)
                st["errors"] = errs
                if errs:
                    return out
            st["errors"] = []
            if b.get("submit"):
                self.submitted = True
            go = b.get("go")
            if go:
                if b.get("tab"):
                    newp = FakePage(go)
                    self.open_pages.append(newp)
                    self._back[id(newp)] = []
                    out.update(page=newp, new_tab=True, navigated=True)
                else:
                    self._back.setdefault(id(page), []).append(page.url)
                    page.url = go
                    out["navigated"] = True
            return out
        if kind == "opt":
            cid2, opt = cid
            c = self._control(spec, cid2)
            if do != "check":
                out["error"] = "an option is checked, not " + str(do)
                return out
            if c["kind"] == "radio":
                st["values"][cid2] = opt
            else:
                st["values"].setdefault(cid2, [])
                if opt not in st["values"][cid2]:
                    st["values"][cid2].append(opt)
            self.chosen[cid2] = opt
            out.update(ok=True, chosen=opt)
            return out
        c = self._control(spec, cid)
        if do == "fill":
            if c["kind"] not in ("text", "textarea"):
                out["error"] = "not a text box"
                return out
            st["values"][cid] = str(action.get("value") or "")
            self.typed[cid] = st["values"][cid]
            out["ok"] = True
        elif do == "select":
            if c["kind"] != "select" or action.get("value") not in c["options"]:
                out["error"] = "no such option"
                return out
            st["values"][cid] = action["value"]
            self.chosen[cid] = action["value"]
            out.update(ok=True, chosen=action["value"])
        elif do == "check":
            if c["kind"] != "checkbox":
                out["error"] = "not a tick box"
                return out
            st["values"][cid] = True
            self.ticked.append(cid)
            out["ok"] = True
        elif do == "upload":
            if c["kind"] != "file":
                out["error"] = "not a file box"
                return out
            name = re.split(r"[\\/]", str(action.get("value") or ""))[-1]
            st["values"][cid] = name
            self.uploaded[cid] = name
            out["ok"] = True
        elif do == "combo":
            if c["kind"] != "combo":
                out["error"] = "not a list"
                return out
            from agent import navigator
            i = navigator.best_option(action.get("wanted") or [], c.get("choices") or [])
            if i < 0:
                out["options"] = list(c.get("choices") or [])
                out["error"] = "none matched"
                return out
            st["values"][cid] = c["choices"][i]
            self.chosen[cid] = c["choices"][i]
            out.update(ok=True, chosen=c["choices"][i])
        else:
            out["error"] = f"unknown action {do}"
        return out


class FakeBrain:
    """The engine. `nav` is a function of the navigator's payload (a dict)
    returning its reply; `answers` maps a phrase in a question to the answer."""

    def __init__(self, nav=None, answers=None):
        self.nav = nav
        self.answers = dict(answers or {})
        self.nav_calls = 0
        self.answer_calls = 0
        self.nav_payloads: list = []
        self.asked: list = []

    def chat(self, messages, system, tools=None, model=None, **kw):
        sys_text = " ".join(system) if isinstance(system, (list, tuple)) else str(system)
        content = messages[-1]["content"]
        if "navigator for one job application" in sys_text:
            self.nav_calls += 1
            self.nav_payloads.append(content)
            reply = self.nav(json.loads(content)) if self.nav else {"actions": []}
        else:
            self.answer_calls += 1
            qs = json.loads(content).get("QUESTIONS") or []
            self.asked.extend(qs)
            reply = {"answers": [{"question": q, "answer": next(
                (v for k, v in self.answers.items() if k.lower() in q.lower()), "")} for q in qs]}
        return _NS(content=[_NS(type="text", text=json.dumps(reply))], stop_reason="end_turn")


def ref_of(page: dict, text: str, where: str = "buttons") -> str:
    """The ref of the first button (or box) on the engine's page whose text
    (or label) contains `text`."""
    for item in page.get(where) or []:
        hay = item.get("text") if where == "buttons" else item.get("label")
        if text.lower() in str(hay or "").lower():
            return item["ref"]
    return ""
