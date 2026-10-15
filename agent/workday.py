"""Workday applications: a multi-page form with its own controls.

A Workday application isn't one form. It's five or six pages — My
Information, My Experience, Application Questions, Voluntary Disclosures,
Self Identify, Review — behind an Apply button, usually behind a sign-in, and
its drop-downs aren't <select>s but buttons that open a list. The general
form filler saw a page of buttons it couldn't type into and gave up, which is
why Workday was the one big system it never finished (AIApply's users report
the same).

This walks it the way a person does:

  * Apply → "Autofill with Resume" when you have a CV file (Workday then reads
    your experience off it), otherwise "Apply Manually";
  * a sign-in or account page is handed to you, as with any site — the
    browser keeps you signed in for next time;
  * on each page, every control is read with its label: text boxes, Workday's
    button drop-downs (opened, and the matching option clicked), yes/no radio
    groups, file uploads. Values come from the same places as every form:
    your profile, answers you've given before, then the engine for anything
    else — checked like every answer;
  * it never answers the sensitive ones (gender, race, disability, veteran…)
    and never ticks a terms or consent box for you: those pages stop for you,
    with what's left listed;
  * Save and Continue, and if Workday shows errors, they're read and reported
    instead of retried blind;
  * it stops at Review. Submitting is yours unless your level submits forms
    and nothing on the way needed you.

Workday's markup carries stable data-automation-id attributes, so that's what
it reads; anything it doesn't recognise is left and listed, never guessed.
"""
from __future__ import annotations

import re

FILLED, NEEDS_ANSWER, UNKNOWN_FORM, SUBMITTED, NEEDS_LOGIN = (
    "filled", "needs_answer", "unknown_form", "submitted", "needs_login")
MAX_STEPS = 10
_CONSENT = re.compile(r"\b(i agree|i accept|i acknowledge|terms|consent|privacy (policy|notice)|"
                      r"certify|attest|declaration)\b", re.I)
_YES = re.compile(r"^\s*(yes|y|true)\b", re.I)
_NO = re.compile(r"^\s*(no|n|false)\b", re.I)

_SCAN = r"""() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const labelOf = (el) => {
    const id = el.getAttribute("aria-labelledby");
    if (id) { const t = id.split(" ").map(x => document.getElementById(x)).filter(Boolean)
                .map(x => x.innerText).join(" ").trim(); if (t) return t; }
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return l.innerText.trim(); }
    const box = el.closest('[data-automation-id^="formField"], .wd-field, fieldset');
    if (box) { const l = box.querySelector("label, legend"); if (l) return l.innerText.trim(); }
    return (el.getAttribute("aria-label") || el.name || "").trim();
  };
  let n = 0; const out = [];
  const tag = (el) => { const k = "jo" + (n++); el.setAttribute("data-jo", k); return `[data-jo="${k}"]`; };
  const step = (document.querySelector('[data-automation-id="progressBarActiveStep"]') || {}).innerText || "";
  const heading = (document.querySelector('h2, [data-automation-id="pageHeader"]') || {}).innerText || "";
  document.querySelectorAll("input, textarea").forEach(el => {
    const t = (el.type || "text").toLowerCase();
    if (["hidden", "submit", "button", "radio", "checkbox"].includes(t) || el.disabled) return;
    if (t !== "file" && !vis(el)) return;
    out.push({kind: t === "file" ? "file" : "text", sel: tag(el), label: labelOf(el),
              value: el.value || "", required: el.required || el.getAttribute("aria-required") === "true",
              aid: el.getAttribute("data-automation-id") || ""});
  });
  document.querySelectorAll('button[aria-haspopup="listbox"]').forEach(el => {
    if (!vis(el)) return;
    const v = (el.innerText || "").trim();
    out.push({kind: "dropdown", sel: tag(el), label: labelOf(el), value: /^select one$/i.test(v) ? "" : v,
              required: el.getAttribute("aria-required") === "true",
              aid: el.getAttribute("data-automation-id") || ""});
  });
  const groups = {};
  document.querySelectorAll('input[type="radio"]').forEach(el => {
    if (!vis(el) && !vis(el.parentElement)) return;
    const g = el.name || (el.closest("fieldset") || {}).id || "g";
    const fs = el.closest("fieldset");
    const q = fs ? ((fs.querySelector("legend") || {}).innerText || "").trim() : labelOf(el);
    const opt = (document.querySelector(`label[for="${CSS.escape(el.id || "")}"]`) || el.parentElement).innerText.trim();
    (groups[g] = groups[g] || {kind: "radio", label: q, options: [], value: "",
                               required: !!(fs && fs.getAttribute("aria-required") === "true")});
    groups[g].options.push({text: opt, sel: tag(el)});
    if (el.checked) groups[g].value = opt;
  });
  Object.values(groups).forEach(g => out.push(g));
  document.querySelectorAll('input[type="checkbox"]').forEach(el => {
    if (!vis(el) && !vis(el.parentElement)) return;
    out.push({kind: "checkbox", sel: tag(el), label: labelOf(el), value: el.checked ? "on" : "",
              required: el.required || el.getAttribute("aria-required") === "true"});
  });
  return {step: step.trim(), heading: heading.trim(), fields: out};
}"""


def _click_first(page, selectors, timeout=4000) -> bool:
    for s in selectors:
        try:
            loc = page.locator(s).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


def _settle(page, ms=8000):
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass
    page.wait_for_timeout(400)


def _pick_option(page, sel: str, wanted: list) -> str:
    """Open a Workday drop-down and click the first option matching any of
    `wanted` (exact, then starts-with, then contains). '' if none did."""
    try:
        page.locator(sel).click(timeout=4000)
        page.wait_for_selector('[role="listbox"] [role="option"]', timeout=4000)
    except Exception:
        return ""
    opts = page.locator('[role="listbox"] [role="option"]')
    texts = [t.strip() for t in opts.all_inner_texts()]
    choice = -1
    for w in [w for w in wanted if w]:
        wl = w.lower().strip()
        for test in (lambda t: t.lower() == wl, lambda t: t.lower().startswith(wl),
                     lambda t: wl in t.lower()):
            hits = [i for i, t in enumerate(texts) if test(t)]
            if hits:
                choice = hits[0]
                break
        if choice >= 0:
            break
    if choice < 0:
        page.keyboard.press("Escape")
        return ""
    opts.nth(choice).click(timeout=4000)
    page.wait_for_timeout(200)
    return texts[choice]


def _country(profile: dict) -> str:
    c = (profile or {}).get("country") or ""
    if c:
        return c
    loc = (profile or {}).get("location") or ""
    return loc.split(",")[-1].strip() if "," in loc else ""


def _dropdown_wants(label: str, profile: dict, saved: str) -> list:
    l = (label or "").lower()
    if saved:
        return [saved]
    if "device" in l or "phone type" in l:
        return ["Mobile", "Cell"]
    if "country" in l:
        return [_country(profile)]
    if "hear about" in l or "source" in l or "how did you" in l:
        return ["Job Board", "Website", "LinkedIn", "Internet", "Other"]
    if "state" in l or "province" in l or "region" in l:
        loc = (profile or {}).get("location") or ""
        parts = [p.strip() for p in loc.split(",")]
        return [parts[1]] if len(parts) >= 3 else []
    return []


def _yes_no(answer: str) -> str:
    if _YES.match(answer or ""):
        return "Yes"
    if _NO.match(answer or ""):
        return "No"
    return ""


def run(page, profile: dict, role: dict, *, cv_file: str = "", answer_fn=None,
        submit: bool = False, max_steps: int = MAX_STEPS) -> dict:
    """Walk a Workday application on an open page. Returns
    {ok, state, steps:[{title, filled, left}], left, errors, message}."""
    from . import portal
    out = {"ok": False, "state": UNKNOWN_FORM, "steps": [], "left": [], "errors": [], "message": ""}
    # from the advert: Apply → how to apply
    if _click_first(page, ['[data-automation-id="adventureButton"]',
                           'a:text-is("Apply")', 'button:text-is("Apply")']):
        _settle(page)
        how = (['[data-automation-id="autofillWithResume"]', 'a:has-text("Autofill with Resume")']
               if cv_file else []) + ['[data-automation-id="applyManually"]',
                                      'a:has-text("Apply Manually")', 'button:has-text("Apply Manually")']
        if _click_first(page, how):
            _settle(page)
            if cv_file:
                try:
                    up = page.locator('input[type="file"]').first
                    if up.count():
                        up.set_input_files(cv_file)
                        _click_first(page, ['[data-automation-id="pageFooterNextButton"]',
                                            'button:has-text("Continue")'])
                        _settle(page)
                except Exception:
                    pass
    if portal.page_state(page.content(), page.url) == portal.NEEDS_LOGIN or \
            page.locator('[data-automation-id="signInContent"], [data-automation-id="createAccountLink"]').count():
        out.update(state=NEEDS_LOGIN, message="Workday wants you signed in to this company's "
                   "careers site. Sign in (or create the account) in the browser window, then carry on.")
        return out

    seen_steps = []
    for _ in range(max_steps):
        scan = page.evaluate(_SCAN)
        title = scan.get("step") or scan.get("heading") or f"page {len(seen_steps) + 1}"
        if "review" in title.lower():
            out["steps"].append({"title": title, "filled": 0, "left": []})
            break
        if seen_steps and title == seen_steps[-1] and out["errors"]:
            break
        seen_steps.append(title)
        filled, left, questions = 0, [], []
        for f in scan["fields"]:
            label = f.get("label") or f.get("aid") or ""
            kind = portal.classify_field(label)
            if f["kind"] == "checkbox":
                if _CONSENT.search(label) and not f["value"]:
                    left.append(f"{label} (yours to tick)")
                continue
            if kind == "sensitive":
                if f.get("required") and not f.get("value"):
                    left.append(f"{label} (sensitive — yours to answer)")
                continue
            if f.get("value"):
                continue                               # Workday or you filled it already
            saved = portal._saved_answer(label)
            if f["kind"] == "file":
                if cv_file and (kind == "resume" or "resume" in label.lower() or "cv" in label.lower()
                                or "attach" in label.lower() or not label):
                    try:
                        page.locator(f["sel"]).set_input_files(cv_file)
                        filled += 1
                    except Exception:
                        left.append(label or "file upload")
                elif f.get("required"):
                    left.append(f"{label or 'file upload'} (no CV file to attach)")
                continue
            if f["kind"] == "text":
                value = (portal.answer_for(kind, profile, role) if kind else "") or saved
                if value:
                    try:
                        page.locator(f["sel"]).fill(value)
                        filled += 1
                    except Exception:
                        left.append(label)
                elif f.get("required"):
                    questions.append(("text", f, label))
                continue
            if f["kind"] == "dropdown":
                got = _pick_option(page, f["sel"], _dropdown_wants(label, profile, saved))
                if got:
                    filled += 1
                elif f.get("required"):
                    questions.append(("dropdown", f, label))
                continue
            if f["kind"] == "radio":
                ans = _yes_no(saved) or saved
                hit = next((o for o in f["options"] if ans and o["text"].lower() == ans.lower()), None)
                if hit:
                    page.locator(hit["sel"]).check()
                    filled += 1
                elif f.get("required"):
                    questions.append(("radio", f, label))
        # the questions only the engine (or you) can answer, in one go
        if questions and answer_fn is not None:
            got = {a["question"]: a for a in answer_fn([q[2] for q in questions])}
            still = []
            for typ, f, label in questions:
                a = (got.get(label) or {}).get("answer", "")
                done = False
                if a and typ == "text":
                    page.locator(f["sel"]).fill(a)
                    done = True
                elif a and typ == "dropdown":
                    done = bool(_pick_option(page, f["sel"], [_yes_no(a) or a]))
                elif a and typ == "radio":
                    yn = _yes_no(a) or a
                    hit = next((o for o in f["options"] if o["text"].lower() == yn.lower()), None)
                    if hit:
                        page.locator(hit["sel"]).check()
                        done = True
                if done:
                    filled += 1
                else:
                    still.append((typ, f, label))
            questions = still
        left += [q[2] for q in questions]
        out["steps"].append({"title": title, "filled": filled, "left": left})
        if left:
            out["left"] = left
            out.update(state=NEEDS_ANSWER,
                       message=f"Stopped at “{title}”: " + "; ".join(left[:6]) +
                               ". Answer these in the browser, then carry on from there.")
            return out
        if not _click_first(page, ['[data-automation-id="pageFooterNextButton"]',
                                   '[data-automation-id="bottom-navigation-next-button"]',
                                   'button:has-text("Save and Continue")', 'button:has-text("Next")']):
            out.update(state=UNKNOWN_FORM, message=f"Couldn't find Save and Continue on “{title}”.")
            return out
        _settle(page)
        errs = [t.strip() for t in page.locator(
            '[data-automation-id="errorMessage"], [data-automation-id="inputAlert"], [role="alert"]'
        ).all_inner_texts() if t.strip()]
        if errs:
            out["errors"] = errs[:8]
            out.update(state=UNKNOWN_FORM,
                       message=f"Workday didn't accept “{title}”: " + "; ".join(errs[:4]))
            return out
    else:
        out.update(state=UNKNOWN_FORM, message="The application went on longer than any Workday form "
                                               "should — stopped so it doesn't loop.")
        return out

    # at Review
    if submit:
        if _click_first(page, ['[data-automation-id="pageFooterNextButton"]', 'button:has-text("Submit")']):
            _settle(page)
            out.update(ok=True, state=SUBMITTED, message="Submitted through Workday.")
            return out
        out.update(state=UNKNOWN_FORM, message="At Review, but the Submit button wasn't there.")
        return out
    out.update(ok=True, state=FILLED, message="Filled every page and stopped at Review — read it "
                                              "and press Submit in the browser when you're happy.")
    return out
