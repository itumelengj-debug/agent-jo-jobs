"""The navigator: finding the form on a site it has never seen, and getting
through it.

The form filler used to open the advert's address and fill whatever boxes
were on that page. Most adverts aren't the form: there's an "Apply" button,
sometimes a new tab, a cookie banner over everything, a form inside an
iframe, two or three pages behind "Continue". On a Lever advert it found no
boxes at all and reported the form "filled". This works the way a person
does instead:

  READ THE PAGE. Every frame, open shadow roots included: the boxes with
  their questions (from <label>, aria attributes, or the text written above
  them), radio groups and drop-downs with their options, file uploads,
  buttons and links, error messages, and the signs of a sign-in or a captcha.

  WHAT IT ALREADY KNOWS FIRST. A site's playbook (agent/playbooks.py) says
  which button led to the form last time, what its "next" button is called,
  and which of your details its unfamiliar labels meant. Then the rules
  every site shares: "Apply now", "Next", a label that says "Email".

  THE ENGINE FOR WHAT'S NEW, WITH A SMALL SET OF TOOLS. When neither knows,
  the engine sees the page and acts through tools: click, type one of your
  details, answer a question from your profile, upload your CV, scroll, go
  back, leave a note for next time, or say it's done. It never writes your
  details or answers itself; it says which detail belongs where and the app
  types it, from your profile, from answers you gave before, or through the
  same claims check every drafted answer passes.

  RAILS IT CAN'T CROSS. It never presses submit unless your level submits
  forms and nothing needs you; never signs in, creates an account or uses
  "apply with LinkedIn/Indeed"; never ticks a terms, privacy or consent box;
  never answers gender, race, disability and the other sensitive questions;
  never accepts cookies (it declines them). A captcha or a sign-in is handed
  to you. LinkedIn and Indeed are never automated.

  IT LEARNS. Whatever worked is written to the site's playbook, so the next
  application through the same site, or any site on the same hiring system,
  starts from it and needs the engine less. What it did and what it learned
  are listed with the result.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import playbooks

MAX_LOOPS = 34            # page reads per application
MAX_FORM_PAGES = 14       # pages of one form
TIME_BUDGET_S = 420       # not counting time spent waiting for you
DEFAULT_TURNS = 12        # engine steps per application
MAX_ENGINE_TURNS = 30     # with refunds for turns that got somewhere
RESCUES_PER_PAGE = 1      # a fresh look by the engine before giving up on a page
INTERSTITIAL_WAIT_S = 25  # "checking your browser" screens usually clear themselves
ACTIONS_PER_TURN = 5

CLOSED = "closed"
APPLY_BY_EMAIL = "apply_by_email"

# sites whose applications are never automated
NEVER_AUTOMATE = ("linkedin.com", "indeed.com", "indeed.co.za", "seek.com.au",
                  "glassdoor.com")


# --------------------------------------------------------------------------- #
#  reading a page: run in every frame
# --------------------------------------------------------------------------- #
SNAPSHOT_JS = r"""
(arg) => {
  const FI = arg && arg.fi !== undefined ? arg.fi : 0;
  const out = {url: location.href, title: document.title || "", controls: [], buttons: [],
               headings: [], errors: [], text: "", password: false, captcha: false,
               captcha_badge: false, cookie: false, frames: []};
  let n = 0;
  /* the app is working in this page: the in-page helper keeps out of the way
     until it's handed back (portal._COMPANION_JS) */
  try {
    window.__agentJoQuiet = Date.now();
    document.querySelectorAll('[data-agent-jo="box"], [data-agent-jo="badge"]')
      .forEach((b) => { b.style.display = "none"; });
  } catch (e) { /* not this page */ }
  const clean = (s) => String(s == null ? "" : s).replace(/\s+/g, " ").trim();
  const ref = (el) => { const r = FI + ":" + (n++); try { el.setAttribute("data-jo-ref", r); } catch (e) {} return r; };
  const textOf = (el) => {
    if (!el) return "";
    let t = "";
    try { t = el.innerText; } catch (e) { t = ""; }
    if (!t) t = el.textContent || "";
    return clean(t);
  };
  const shown = (el) => {
    if (!el || !el.isConnected) return false;
    try {
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return false;
      const s = getComputedStyle(el);
      return s.visibility !== "hidden" && s.display !== "none" && parseFloat(s.opacity || "1") > 0.05;
    } catch (e) { return false; }
  };
  /* every element, open shadow roots included; Agent Jo's own helper skipped */
  const els = [];
  const stack = document.documentElement ? [document.documentElement] : [];
  while (stack.length && els.length < 25000) {
    const node = stack.pop();
    if (!node || node.nodeType !== 1) continue;
    if (node.hasAttribute("data-agent-jo")) continue;
    if (node.hasAttribute("data-jo-ref")) node.removeAttribute("data-jo-ref");
    els.push(node);
    const kids = node.children ? Array.from(node.children) : [];
    for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
    if (node.shadowRoot) {
      const sk = Array.from(node.shadowRoot.children);
      for (let i = sk.length - 1; i >= 0; i--) stack.push(sk[i]);
    }
  }
  const rootOf = (el) => (el.getRootNode ? el.getRootNode() : document);
  const byId = (el, id) => {
    const r = rootOf(el);
    try { return (r.getElementById ? r.getElementById(id) : null) || document.getElementById(id); } catch (e) { return null; }
  };
  const labelTag = (el) => {
    if (!el.id) return null;
    try { return rootOf(el).querySelector('label[for="' + CSS.escape(el.id) + '"]'); } catch (e) { return null; }
  };
  const ownText = (box) => clean(Array.from(box.childNodes).filter((c) =>
      !(c.nodeType === 1 && c.matches("select, textarea, input, ul, ol, [role=listbox], [role=option], button")))
    .map((c) => (c.nodeType === 3 ? c.textContent : textOf(c))).join(" "));
  const FIELDS = "input:not([type=hidden]), select, textarea";
  /* the question written just before the box. It stops at the first earlier
     element that holds another field: past that is someone else's question,
     and a section heading further up is not this box's label */
  const prevText = (start, el) => {
    const box = el || start;
    const other = (c) => c !== box && !(box.name && c.name === box.name && /^(radio|checkbox)$/i.test(c.type || ""));
    const others = (n) => n.matches(FIELDS) ? other(n) : Array.from(n.querySelectorAll(FIELDS)).some(other);
    let node = start;
    for (let up = 0; up < 4 && node; up++) {
      let sib = node.previousElementSibling, hops = 0;
      while (sib && hops < 4) {
        if (others(sib)) return "";
        if (!sib.matches("script, style, svg, button, img, br, hr")) {
          const t = textOf(sib);
          if (t && t.length <= 250) return t;
        }
        sib = sib.previousElementSibling; hops++;
      }
      node = node.parentElement;
      if (!node || node === document.body) break;
      if (others(node)) break;
    }
    return "";
  };
  const labelFor = (el) => {
    const lb = el.getAttribute("aria-labelledby");
    if (lb) { const t = clean(lb.split(/\s+/).map((i) => textOf(byId(el, i))).join(" ")); if (t) return t; }
    const l = labelTag(el);
    if (l) { const t = ownText(l) || textOf(l); if (t) return t; }
    const w = el.closest("label");
    if (w) { const t = ownText(w); if (t) return t; }
    const al = clean(el.getAttribute("aria-label"));
    if (al) return al;
    const near = prevText(el, el);
    if (near) return near;
    return clean(el.getAttribute("placeholder") || el.getAttribute("title") || "");
  };
  const hintOf = (el) => clean([el.getAttribute("name"), el.id, el.getAttribute("autocomplete"),
    el.getAttribute("placeholder"), el.getAttribute("data-qa"), el.getAttribute("data-automation-id")]
    .filter(Boolean).join(" "));
  const STAR = /\*\s*$|^\s*\*|\*\s*\(|\(required\)/i;
  const req = (el, label) => !!(el.required || el.getAttribute("aria-required") === "true" || STAR.test(label || ""));
  const PLACE = /^(select|choose|please (select|choose)|--+|—|-|none selected|pick one)\b|^\s*$/i;
  const optionText = (el) => {
    const l = labelTag(el);
    if (l && textOf(l)) return textOf(l);
    const w = el.closest("label");
    if (w && textOf(w)) return textOf(w);
    const al = clean(el.getAttribute("aria-label"));
    if (al) return al;
    let s = el.nextSibling, hops = 0;
    while (s && hops < 4) {
      const t = s.nodeType === 3 ? clean(s.textContent) : (s.nodeType === 1 ? textOf(s) : "");
      if (t) return t.slice(0, 200);
      s = s.nextSibling; hops++;
    }
    return clean(el.value || "");
  };
  const fsIds = new WeakMap(); let fsN = 0;
  const fsKey = (fs) => { if (!fsIds.has(fs)) fsIds.set(fs, "g" + (fsN++)); return fsIds.get(fs); };
  const groupQuestion = (fs, first) => {
    if (fs) {
      const lg = fs.querySelector("legend");
      if (lg && textOf(lg)) return textOf(lg);
      const lb = fs.getAttribute("aria-labelledby");
      if (lb) { const t = clean(lb.split(/\s+/).map((i) => textOf(byId(fs, i))).join(" ")); if (t) return t; }
      const al = clean(fs.getAttribute("aria-label"));
      if (al) return al;
      for (const c of Array.from(fs.children)) {
        if (!c.querySelector("input, [role=radio], [role=checkbox]") && textOf(c)) return textOf(c).slice(0, 250);
      }
    }
    return prevText(first.closest("label") || first, first);
  };
  const comboValue = (el) => {
    const v = el.tagName === "INPUT" ? clean(el.value) : textOf(el);
    if (v && !PLACE.test(v)) return v;
    const box = el.closest('[class*="control" i], [class*="select" i], [class*="combo" i]');
    if (box) {
      const sv = box.querySelector('[class*="single-value" i], [class*="singleValue" i], [class*="selected" i]');
      if (sv && textOf(sv) && !PLACE.test(textOf(sv))) return textOf(sv);
    }
    return "";
  };
  const isCombo = (el) => el.getAttribute("role") === "combobox" || !!el.getAttribute("aria-autocomplete")
    || (el.tagName === "BUTTON" && el.getAttribute("aria-haspopup") === "listbox");
  const groups = {};
  const areaOf = (el) => {
    const f = el.closest("form, [role=form], aside, section");
    const head = f ? f.querySelector("h1, h2, h3, h4, legend, [role=heading]") : null;
    const bits = f ? [f.id, typeof f.className === "string" ? f.className : "", f.getAttribute("aria-label"),
                      head ? textOf(head) : ""] : [];
    if (el.closest("footer, [role=contentinfo]")) bits.push("footer");
    return clean(bits.filter(Boolean).join(" ")).slice(0, 160);
  };
  const push = (c, el) => { if (el) c.area = areaOf(el); out.controls.push(c); return c; };
  for (const el of els) {
    const tag = el.tagName;
    try {
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        const type = (tag === "INPUT" ? (el.getAttribute("type") || "text") : tag.toLowerCase()).toLowerCase();
        if (type === "hidden" || el.disabled) continue;
        if (["submit", "button", "reset", "image"].includes(type)) continue;
        if (type === "password") { if (shown(el)) out.password = true; continue; }
        if (type === "radio" || type === "checkbox") {
          const lt = labelTag(el);
          const seen = shown(el) || shown(el.closest("label")) || shown(lt) || shown(el.parentElement);
          if (!seen) continue;
          const fs = el.closest("fieldset, [role=radiogroup], [role=group]");
          const key = type + ":" + (el.name ? "n:" + el.name : (fs ? fsKey(fs) : "solo" + n));
          let g = groups[key];
          if (!g) {
            g = groups[key] = push({kind: type === "radio" ? "radio" : "checkgroup", label: groupQuestion(fs, el),
                                    hint: hintOf(el), required: false, options: [], value: "", ref: ""}, el);
          }
          const r = ref(el);
          if (!g.ref) g.ref = r;
          const ot = optionText(el);
          g.options.push({text: ot, ref: r, checked: !!el.checked});
          if (req(el, "")) g.required = true;
          continue;
        }
        if (type === "file") {
          const lab = labelFor(el) || clean((el.closest("[class*=upload], [class*=file], [class*=field]") || {}).innerText || "");
          push({ref: ref(el), kind: "file", type, label: lab, hint: hintOf(el), required: req(el, lab),
                value: el.files && el.files.length ? el.files[0].name : "",
                accept: el.getAttribute("accept") || "", multiple: !!el.multiple}, el);
          continue;
        }
        if (!shown(el)) continue;
        if (el.readOnly && !isCombo(el)) continue;
        const lab = labelFor(el);
        if (tag === "SELECT") {
          const opts = Array.from(el.options).slice(0, 400).map((o) => clean(o.text));
          const cur = el.selectedIndex >= 0 && el.options[el.selectedIndex] ? clean(el.options[el.selectedIndex].text) : "";
          push({ref: ref(el), kind: "select", type, label: lab, hint: hintOf(el), required: req(el, lab),
                value: PLACE.test(cur) ? "" : cur, options: opts, multiple: !!el.multiple,
                invalid: el.getAttribute("aria-invalid") === "true"}, el);
          continue;
        }
        const combo = isCombo(el);
        push({ref: ref(el), kind: combo ? "combo" : (tag === "TEXTAREA" ? "textarea" : "text"), type,
              label: lab, hint: hintOf(el), required: req(el, lab),
              value: combo ? comboValue(el) : (el.value || ""), max: el.maxLength > 0 ? el.maxLength : 0,
              invalid: el.getAttribute("aria-invalid") === "true"}, el);
        continue;
      }
      const role = el.getAttribute("role");
      if ((role === "combobox" || (tag === "BUTTON" && el.getAttribute("aria-haspopup") === "listbox")) && shown(el)) {
        if (el.querySelector("input")) continue;           // its own input is read instead
        const lab = labelFor(el);
        push({ref: ref(el), kind: "combo", type: "custom", label: lab, hint: hintOf(el),
              required: req(el, lab), value: comboValue(el)}, el);
        continue;
      }
      if ((role === "radio" || role === "checkbox") && shown(el)) {
        const fs = el.closest("[role=radiogroup], [role=group], fieldset");
        const key = role + ":" + (fs ? fsKey(fs) : "solo" + n);
        let g = groups[key];
        if (!g) g = groups[key] = push({kind: role === "radio" ? "radio" : "checkgroup", label: groupQuestion(fs, el),
                                         hint: hintOf(el), required: false, options: [], value: "", ref: ""}, el);
        const r = ref(el);
        if (!g.ref) g.ref = r;
        g.options.push({text: clean(el.getAttribute("aria-label")) || textOf(el), ref: r,
                        checked: el.getAttribute("aria-checked") === "true"});
        if (fs && fs.getAttribute("aria-required") === "true") g.required = true;
        continue;
      }
      if (el.isContentEditable && el.getAttribute("contenteditable") !== null && shown(el)
          && !(el.parentElement && el.parentElement.isContentEditable)) {
        const lab = labelFor(el);
        push({ref: ref(el), kind: "textarea", type: "editable", label: lab, hint: hintOf(el),
              required: req(el, lab), value: textOf(el)}, el);
      }
    } catch (e) { /* one odd element never loses the page */ }
  }
  for (const g of Object.values(groups)) {
    const on = g.options.filter((o) => o.checked).map((o) => o.text);
    if (g.kind === "radio") g.value = on[0] || "";
    else if (g.options.length === 1) {
      g.kind = "checkbox"; g.label = g.options[0].text || g.label; g.value = on.length ? "on" : "";
      g.ref = g.options[0].ref; g.options = [];
    } else g.value = on.join("; ");
  }
  const BANNER = /cookie|consent|onetrust|cookiebot|gdpr|cc-window|cmp-|truste|usercentrics|didomi|privacy-banner/i;
  const inBanner = (el) => {
    let p = el;
    for (let i = 0; i < 9 && p; i++, p = p.parentElement) {
      const id = (p.id || "") + " " + (typeof p.className === "string" ? p.className : "")
        + " " + (p.getAttribute("aria-label") || "");
      if (BANNER.test(id)) return true;
    }
    return false;
  };
  const BTN = 'a[href], button, [role="button"], [role="link"], [role="tab"], input[type="submit"], input[type="button"], input[type="image"]';
  for (const el of els) {
    try {
      if (!el.matches(BTN)) continue;
      if (el.disabled || el.getAttribute("aria-disabled") === "true") continue;
      if (el.getAttribute("aria-haspopup") === "listbox") continue;
      if (!shown(el)) continue;
      let t = el.tagName === "INPUT" ? clean(el.value || el.getAttribute("aria-label") || el.getAttribute("alt"))
              : (textOf(el) || clean(el.getAttribute("aria-label") || el.getAttribute("title")));
      if (!t) continue;
      if (t.length > 120) t = t.slice(0, 120);
      const form = el.closest("form");
      const type = (el.getAttribute("type") || (el.tagName === "BUTTON" && form ? "submit" : "")).toLowerCase();
      const b = {ref: ref(el), kind: el.tagName === "A" ? "link" : (el.getAttribute("role") === "tab" ? "tab" : "button"),
                 text: t, href: el.tagName === "A" ? (el.href || "") : "", target: el.getAttribute("target") || "",
                 type, in_form: !!form, nav: !!el.closest("nav, header, footer, [role=navigation], [role=banner], [role=contentinfo]"),
                 banner: inBanner(el), label: clean(el.getAttribute("aria-label"))};
      if (b.banner) out.cookie = true;
      out.buttons.push(b);
      if (out.buttons.length >= 220) break;
    } catch (e) { /* skip it */ }
  }
  const hs = [];
  for (const el of els) {
    if (hs.length >= 10) break;
    if (/^H[1-3]$/.test(el.tagName) || el.getAttribute("role") === "heading") {
      if (shown(el)) { const t = textOf(el).slice(0, 160); if (t) hs.push(t); }
    }
  }
  out.headings = hs;
  const ERR = '[role="alert"], [aria-live="assertive"], .error, .errors, .field-error, .error-message, .invalid-feedback, [class*="error" i], [class*="invalid" i], [id*="error" i]';
  const errs = new Set();
  for (const el of els) {
    if (errs.size >= 8) break;
    try {
      if (!el.matches(ERR) || !shown(el)) continue;
      if (el.querySelector(FIELDS)) continue;
      const t = textOf(el);
      if (t && t.length >= 3 && t.length <= 220) errs.add(t);
    } catch (e) { /* skip it */ }
  }
  out.errors = Array.from(errs);
  const main = document.querySelector("main, [role=main], article") || document.body;
  out.text = textOf(main).slice(0, 6000);
  if (main !== document.body && document.body) {
    const all = textOf(document.body);
    if (all.length > out.text.length) out.text = (out.text + " … " + all.slice(0, 3000)).slice(0, 7000);
  }
  for (const f of Array.from(document.querySelectorAll("iframe"))) {
    try {
      const src = (f.getAttribute("src") || "") + " " + (f.getAttribute("title") || "");
      out.frames.push(clean(src).slice(0, 200));
      if (/recaptcha|hcaptcha|turnstile|challenges\.cloudflare|captcha/i.test(src)) {
        const r = f.getBoundingClientRect();
        if (f.closest(".grecaptcha-badge")) out.captcha_badge = true;
        else if (r.width > 60 && r.height > 40 && shown(f)) out.captcha = true;
      }
    } catch (e) { /* skip it */ }
  }
  const low = out.text.toLowerCase();
  if (/verify (that )?you are (a )?human|checking (if )?(the site connection|your browser)|i'?m not a robot/.test(low)
      && out.controls.length < 3) out.captcha = true;
  return out;
}
"""


_SNAPSHOT_ON_ROOT = "(root, arg) => (" + SNAPSHOT_JS.strip() + ")(arg)"


def browser_snapshot(page, cache: dict) -> dict:
    """Read every frame of the page. The frames are kept in `cache` so a
    later action can find the element a ref names."""
    frames, merged = [], {"url": "", "title": "", "controls": [], "buttons": [],
                          "headings": [], "errors": [], "text": "", "password": False,
                          "captcha": False, "captcha_badge": False, "cookie": False,
                          "frames": []}
    try:
        all_frames = list(page.frames)
    except Exception:
        all_frames = [page.main_frame]
    texts = []
    bad = cache.setdefault("_silent", set())
    for i, fr in enumerate(all_frames):
        try:
            if fr.is_detached():
                continue
        except Exception:
            pass
        url = ""
        try:
            url = fr.url or ""
        except Exception:
            pass
        if i and (id(fr) in bad or re.search(r"recaptcha|hcaptcha|turnstile|challenges\.cloudflare|doubleclick|"
                                              r"googletagmanager|google-analytics|facebook\.com/tr|"
                                              r"youtube\.com/embed|vimeo\.com|hotjar|intercom", url, re.I)):
            continue
        try:
            # through a locator, which can time out: a frame that never gets
            # going ("about:blank#…") would hang a plain evaluate for ever
            data = fr.locator(":root").evaluate(_SNAPSHOT_ON_ROOT, {"fi": len(frames)},
                                                timeout=10000 if not i else 2500)
        except Exception:
            if i:
                bad.add(id(fr))
            continue
        frames.append(fr)
        if not merged["url"]:
            merged["url"], merged["title"] = data.get("url", ""), data.get("title", "")
        for k in ("controls", "buttons"):
            merged[k].extend(data.get(k) or [])
        for k in ("headings", "errors", "frames"):
            for v in data.get(k) or []:
                if v not in merged[k]:
                    merged[k].append(v)
        for k in ("password", "captcha", "captcha_badge", "cookie"):
            merged[k] = merged[k] or bool(data.get(k))
        if data.get("text"):
            texts.append(data["text"])
    merged["text"] = " ‖ ".join(texts)[:9000]
    try:
        merged["url"] = page.url or merged["url"]
    except Exception:
        pass
    cache[id(page)] = frames
    return merged


def _locate(page, cache: dict, ref: str):
    frames = cache.get(id(page)) or []
    if not isinstance(frames, list):
        frames = []
    fi, _, _n = str(ref or "").partition(":")
    fr = frames[int(fi)] if fi.isdigit() and int(fi) < len(frames) else page.main_frame
    return fr, fr.locator(f'[data-jo-ref="{ref}"]').first


def _settle(page, ms: int = 4000) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass
    try:
        page.wait_for_timeout(250)
    except Exception:
        pass


def browser_act(page, cache: dict, action: dict) -> dict:
    """Do one thing to the page. Returns {ok, error, page, new_tab,
    navigated, chosen}: `page` is the page to carry on in, which is a new tab
    when the click opened one."""
    do = str(action.get("do") or "")
    ref = str(action.get("ref") or "")
    value = action.get("value")
    out = {"ok": False, "error": "", "page": page, "new_tab": False,
           "navigated": False, "chosen": ""}
    ctx = getattr(page, "context", None)
    before_pages = list(getattr(ctx, "pages", None) or [page])
    try:
        before_url = page.url
    except Exception:
        before_url = ""
    try:
        fr, loc = _locate(page, cache, ref) if ref else (page.main_frame, None)
        if do == "click":
            try:
                loc.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            try:
                loc.click(timeout=7000)
            except Exception:
                loc.click(timeout=5000, force=True)
        elif do == "fill":
            text = str(value or "")
            try:
                editable = loc.evaluate("(e) => !!e.isContentEditable && !/^(INPUT|TEXTAREA)$/.test(e.tagName)")
            except Exception:
                editable = False
            if editable:
                loc.click(timeout=5000)
                page.keyboard.press("Control+A")
                page.keyboard.insert_text(text)
            else:
                loc.fill(text, timeout=7000)
                try:
                    got = loc.input_value(timeout=2000)
                except Exception:
                    got = text
                if text and not str(got).strip():
                    loc.fill("", timeout=3000)
                    loc.press_sequentially(text, delay=8, timeout=30000)
            try:
                loc.dispatch_event("change")
                loc.evaluate("(e) => e.blur && e.blur()")
            except Exception:
                pass
        elif do == "select":
            try:
                loc.select_option(label=str(value), timeout=5000)
            except Exception:
                idx = action.get("index")
                if idx is None:
                    raise
                loc.select_option(index=int(idx), timeout=5000)
            out["chosen"] = str(value)
        elif do == "check":
            try:
                loc.check(timeout=5000, force=True)
            except Exception:
                loc.click(timeout=5000, force=True)
        elif do == "upload":
            loc.set_input_files(str(value), timeout=15000)
        elif do == "combo":
            wanted = [w for w in (action.get("wanted") or [value]) if w]
            loc.click(timeout=6000)
            is_input = False
            try:
                is_input = bool(loc.evaluate("(e) => e.tagName === 'INPUT'"))
            except Exception:
                pass
            typed = str(action.get("type_text") or (wanted[0] if wanted else ""))[:40]
            if is_input and typed:
                loc.fill("", timeout=3000)
                loc.press_sequentially(typed, delay=25, timeout=15000)
            opts = fr.locator('[role="option"]:visible')
            texts = []
            for _ in range(14):
                try:
                    texts = [t.strip() for t in opts.all_inner_texts()]
                except Exception:
                    texts = []
                if texts:
                    break
                page.wait_for_timeout(250)
            i = best_option(wanted, texts)
            if i < 0:
                page.keyboard.press("Escape")
                out["options"] = texts[:30]
                raise ValueError("none of the options matched")
            opts.nth(i).click(timeout=5000)
            out["chosen"] = texts[i]
        elif do == "scroll":
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(400)
        elif do == "back":
            page.go_back(wait_until="domcontentloaded", timeout=15000)
        elif do == "press":
            page.keyboard.press(str(value or "Enter"))
        else:
            raise ValueError(f"unknown action {do!r}")
        out["ok"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}"
    if do in ("click", "back", "press"):
        try:
            page.wait_for_timeout(600)
        except Exception:
            pass
        fresh = [p for p in (getattr(ctx, "pages", None) or []) if p not in before_pages]
        fresh = [p for p in fresh if not p.is_closed()]
        if fresh:
            newp = fresh[-1]
            try:
                newp.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            out["page"], out["new_tab"] = newp, True
        _settle(out["page"])
    try:
        out["navigated"] = out["new_tab"] or out["page"].url != before_url
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------- #
#  what things are: pure, so they can be checked without a browser
# --------------------------------------------------------------------------- #
def norm(text: str) -> str:
    return playbooks.norm(text)


_APPLY_EXACT = re.compile(
    r"^(apply|apply now|apply here|apply online|apply today|apply for (this|the) (job|role|position|vacancy|"
    r"opportunity|post)|apply to (this|the) (job|role|position)|i'?m interested|i am interested|"
    r"start( your| my| an)? application|begin( your| my| an)? application|apply manually|"
    r"continue as( a)? guest|apply as( a)? guest|apply without( an)? account|"
    r"continue without( an)? account|submit (your|a|my) (cv|resume)|send (your|a|my) (cv|resume))$", re.I)
_APPLY_WORDS = re.compile(r"\bapply\b|\binterested\b|\bstart (your |my |an )?application\b|"
                          r"\bbegin (your |my |an )?application\b|\bas (a )?guest\b|\bwithout (an )?account\b",
                          re.I)
_NOT_A_CTA = re.compile(r"linkedin|indeed|\bseek\b|glassdoor|google|facebook|\bapple\b|microsoft|github|"
                        r"\bxing\b|\bsign ?(in|up)\b|\blog ?in\b|register|create (an |your )?account|easy apply|"
                        r"apply with|apply using|similar jobs|job alert|newsletter|refer a friend|\bshare\b|"
                        r"how to apply|more jobs|other jobs|save (this )?job", re.I)
_SUBMIT = re.compile(r"^(submit|send|finish|complete|confirm|done)\b|\bsubmit\b|\bsend (my |your |the )?application\b|"
                     r"\bcomplete (my |your |the )?application\b|\bfinish (my |your |the )?application\b", re.I)
# a button that agrees to something on your behalf
_CONSENT_BUTTON = re.compile(r"^(i )?(agree|accept|consent|acknowledge)\b|\bi (agree|accept|consent)\b|"
                             r"\baccept (the |all )?(terms|policy|privacy|conditions)", re.I)
_NEXT = re.compile(r"^(next|continue|proceed|save (and|&) (continue|next|proceed)|next (step|page|section)|"
                   r"continue to (the )?(next|review)( step| page| section)?|go to (the )?next( step| page)?|"
                   r"review|review (my |your |the )?application|review and submit|[›»→>]|next [›»→>])$", re.I)
_LOGIN = re.compile(r"\b(sign ?in|log ?in|sign ?up|register|create (an |your )?account|forgot (your )?password|"
                    r"continue with (google|linkedin|apple|facebook|microsoft|github|email)|"
                    r"apply with (linkedin|indeed|seek|xing|google))\b", re.I)
_DANGER = re.compile(r"\b(delete|remove|withdraw|cancel (my |your )?application|unsubscribe|subscribe|pay|buy|"
                     r"purchase|checkout|donate|upgrade|report (this )?job|share|print|download|notify me|"
                     r"get (job )?alerts|create (a |an )?(job )?alert|join (our |the )?(talent )?"
                     r"(community|network|pool|mailing list))\b", re.I)
_COOKIE_REJECT = re.compile(r"\b(reject|decline|deny|refuse|disagree)\b|only (necessary|essential|required)|"
                            r"(necessary|essential|required) (cookies )?only|continue without (accepting|agreeing)|"
                            r"use (only )?necessary", re.I)
_CLOSE = re.compile(r"^(close|dismiss|×|x|✕|no thanks|not now|maybe later)$", re.I)
_FILE_LINK = re.compile(r"\.(pdf|docx?|zip|rtf|xlsx?|pptx?)(\?|#|$)", re.I)

_CONSENT = re.compile(r"\b(i agree|i accept|i acknowledge|i consent|i confirm|i declare|i certify|i understand|"
                      r"agree|accept|acknowledge|consent|terms|privacy|declar\w*|certify|attest|gdpr|popia|"
                      r"data protection|processing of (my )?(personal )?(data|information)|retain my|store my)\b",
                      re.I)
_MARKETING = re.compile(r"newsletter|job alerts?|marketing|subscribe|keep me (informed|updated|posted)|"
                        r"future (opportunities|openings|roles|vacancies|positions)|talent (pool|community|network)|"
                        r"send me|notify me|text messages|\bsms\b|whatsapp", re.I)
_SENSITIVE_EXTRA = ("pronoun", "salutation", "nationality", "citizen", "equity", "designated group",
                    "bee status", "b-bbee", "bbbee", "how old", "your age", "age group", "medical",
                    "health condition", "dependant", "union member", "political", "caste", "maiden name",
                    "sexual", "transgender", "trans ", "lgbt")

_CLOSED_TEXT = re.compile(
    r"no longer accepting applications|no longer available|(this|the) (job|position|role|vacancy|posting|"
    r"advert) (is|has been) (closed|filled|removed|expired|taken down)|applications (are|have) (now )?closed|"
    r"position has been filled|(job|posting|advert|vacancy) (has )?expired|closed for applications|"
    r"we are no longer hiring|this role is no longer|job not found|vacancy no longer|"
    r"the (job|page) you('re| are) looking for (is|was|has|could not|cannot|can't|no longer)", re.I)
_SUCCESS_TEXT = re.compile(
    r"thank(s| you) for (applying|your application|submitting)|application (has been |was )?"
    r"(received|submitted|sent|complete)|we('ve| have) received your application|"
    r"your application (has been|was) (received|submitted|sent)|successfully (applied|submitted)", re.I)
# a holding screen in front of the site (bot check, redirect, loader). It is
# waited out, never worked around: if it turns into a challenge, that's a
# captcha and it's handed to you.
_INTERSTITIAL = re.compile(
    r"just a moment|checking (if the site connection is secure|your browser)|verifying (that )?you are "
    r"(a )?human|please wait while (we|you are)|ddos protection|enable javascript and cookies to continue|"
    r"one more step|redirecting( you)?\b|you are being redirected|loading\.\.\.|please stand by", re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_APPLY_BY_MAIL = re.compile(r"\b(apply|applications?|cv|c\.v\.|resume|résumé|curriculum vitae|send|e-?mail)\b",
                            re.I)
_PLACEHOLDER = re.compile(r"^(select|choose|please (select|choose)|--+|—|-|none selected|pick one)\b|^\s*$",
                          re.I)


def site_of(url: str) -> str:
    return playbooks.site_of(url)


def never_automated(url: str) -> str:
    """The name of a site whose applications are never automated, or ''."""
    host = site_of(url)
    for s in NEVER_AUTOMATE:
        if host == s or host.endswith("." + s):
            return "LinkedIn" if "linkedin" in s else ("Indeed" if "indeed" in s else s)
    return ""


def cta_kind(b: dict, form_page: bool = False) -> str:
    """What pressing this button would do: apply, next, submit, login,
    cookie_reject, cookie_accept, close, danger, file, away (another site we
    never automate), or '' for anything else."""
    text = norm(b.get("text") or b.get("label") or "")
    raw = str(b.get("text") or "")
    href = str(b.get("href") or "")
    if never_automated(href):
        return "away"
    if href.lower().startswith(("mailto:", "tel:", "javascript:void")) and not text:
        return ""
    if b.get("banner"):
        if _COOKIE_REJECT.search(text):
            return "cookie_reject"
        if _CLOSE.match(raw.strip()) or _CLOSE.match(text):
            return "close"
        return "cookie_accept"
    if _LOGIN.search(text):
        return "login"
    if _FILE_LINK.search(href):
        return "file"
    if _DANGER.search(text):
        return "danger"
    if _SUBMIT.search(text):
        return "submit"
    if form_page and not b.get("nav") and re.search(r"\bapply\b", text):
        return "submit"                    # "Apply" on the form itself sends it
    if _CONSENT_BUTTON.search(text):
        return "consent"
    if _NEXT.match(text):
        return "next"
    if _APPLY_EXACT.match(text) or (_APPLY_WORDS.search(text) and not _NOT_A_CTA.search(text)
                                    and len(text.split()) <= 7):
        return "apply"
    if _CLOSE.match(raw.strip()):
        return "close"
    return ""


def consent_label(label: str) -> bool:
    return bool(_CONSENT.search(label or "")) or bool(_MARKETING.search(label or ""))


def sensitive_label(label: str, options: list | None = None) -> bool:
    from . import portal
    low = " ".join(str(label or "").lower().split())
    if portal.classify_field(low) == "sensitive" or any(s in f" {low} " for s in _SENSITIVE_EXTRA):
        return True
    opts = {norm(o) for o in options or []}
    if {"mr", "mrs"} <= opts or {"mr", "ms"} <= opts or {"male", "female"} & opts:
        return True                        # a salutation or a gender question, whatever its label
    return False


def is_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER.match(str(text or "").strip()))


def has_value(c: dict) -> bool:
    v = c.get("value")
    if c.get("kind") == "checkbox":
        return v == "on"
    return bool(str(v or "").strip()) and not is_placeholder(str(v))


_AUTOCOMPLETE = {"given-name": "first_name", "family-name": "last_name", "name": "full_name",
                 "email": "email", "tel": "phone", "tel-national": "phone_local", "url": "website",
                 "country": "country", "country-name": "country", "address-level2": "city"}
_EXTRA_KINDS = [
    ("phone_code", r"country[\s_-]*code|dial(l?ing)?[\s_-]*code|phone[\s_-]*code|calling[\s_-]*code"),
    ("phone_type", r"phone[\s_-]*(device[\s_-]*)?type|type of (phone|number)|device[\s_-]*type"),
    ("source", r"how did you (hear|find|learn|come across)|where did you (hear|find|see)|"
               r"referr?al[\s_-]*source|source of (application|applicant|hire)|^\s*source\s*$|"
               r"how did you get to know"),
    ("country", r"\bcountry\b|country of residence"),
    ("city", r"\bcity\b|\btown\b"),
]
FIELD_NAMES = {"phone_local": "phone number (local format)", "phone_digits": "phone number (digits only)",
               "phone": "phone number", "phone_code": "dialling code", "phone_type": "phone type",
               "salary": "salary expectation", "notice": "notice period", "cover_letter": "covering letter",
               "full_name": "full name", "first_name": "first name", "last_name": "last name",
               "linkedin": "LinkedIn profile", "github": "GitHub profile", "source": "where you heard of it",
               "location": "location", "city": "city", "country": "country", "email": "email",
               "website": "website"}


def field_name(kind: str) -> str:
    return FIELD_NAMES.get(kind, str(kind or "").replace("_", " "))


def pretty(label: str) -> str:
    """A label as a person would read it: no required-stars, no "(required)"."""
    t = re.sub(r"\(\s*(required|optional)\s*\)|\*+", " ", str(label or ""), flags=re.I)
    return " ".join(t.split()).strip(" :")[:80]


FIELDS_THE_ENGINE_CAN_NAME = ("first_name", "last_name", "full_name", "email", "phone", "phone_local",
                              "phone_digits", "location", "city", "country", "linkedin", "github",
                              "website", "notice", "salary", "cover_letter")


def classify(label: str, hint: str = "", url: str = "", ats: str = "") -> str:
    """Which of your details a field asks for: a FIELD_PATTERNS kind, one of
    the extra kinds above, 'sensitive', or a kind this site taught it."""
    from . import portal
    lab = " ".join(str(label or "").split())
    for kind, pat in _EXTRA_KINDS[:3]:             # before "phone" and "location" claim them
        if re.search(pat, lab, re.I):
            return kind
    if re.search(r"\b(city|town)\b", lab, re.I) and not re.search(r"location|address|based|where", lab, re.I) \
            and portal.classify_field(lab) != "sensitive":
        return "city"                              # a city box wants the city, not the whole location
    k = portal.classify_field(lab)
    if k:
        return k
    for kind, pat in _EXTRA_KINDS[3:]:
        if re.search(pat, lab, re.I):
            return kind
    for tok in str(hint or "").lower().split():
        if tok in _AUTOCOMPLETE:
            return _AUTOCOMPLETE[tok]
    learned = playbooks.label_kind(lab, url, ats) if lab else ""
    if learned:
        return learned
    h = re.sub(r"[_\-]+", " ", str(hint or ""))
    k = portal.classify_field(h) if h else ""
    return k if k not in ("sensitive",) else ""


# country codes for the phone, and the countries' names, for the common ones
_DIAL = {"27": "South Africa", "44": "United Kingdom", "1": "United States", "61": "Australia",
         "64": "New Zealand", "91": "India", "234": "Nigeria", "254": "Kenya", "49": "Germany",
         "33": "France", "31": "Netherlands", "353": "Ireland", "263": "Zimbabwe", "260": "Zambia",
         "267": "Botswana", "255": "Tanzania", "256": "Uganda", "233": "Ghana", "20": "Egypt",
         "971": "United Arab Emirates", "65": "Singapore", "34": "Spain", "39": "Italy",
         "351": "Portugal", "48": "Poland", "46": "Sweden", "41": "Switzerland", "32": "Belgium",
         "264": "Namibia", "258": "Mozambique", "266": "Lesotho", "268": "Eswatini", "230": "Mauritius"}


def phone_parts(phone: str) -> dict:
    raw = str(phone or "").strip()
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    code = ""
    if digits.startswith("+"):
        for n in (3, 2, 1):
            if digits[1:1 + n] in _DIAL:
                code = digits[1:1 + n]
                break
    rest = digits[1 + len(code):] if code else digits.lstrip("+")
    local = (rest if code == "1" else ("0" + rest if code and not rest.startswith("0") else rest)) \
        if code else digits
    return {"phone": raw, "phone_digits": digits, "phone_local": local,
            "phone_code": ("+" + code) if code else "", "country": _DIAL.get(code, "")}


def country_of(profile: dict) -> str:
    p = profile or {}
    if p.get("country"):
        return str(p["country"])
    loc = str(p.get("location") or "")
    if "," in loc:
        return loc.split(",")[-1].strip()
    return phone_parts(p.get("phone", ""))["country"]


def value_for(kind: str, profile: dict, role: dict) -> str:
    """What to type for a kind of field, or '' when your profile doesn't say."""
    from . import portal
    p = profile or {}
    if kind in ("phone_local", "phone_digits", "phone_code"):
        return phone_parts(p.get("phone", ""))[kind]
    if kind == "city":
        loc = str(p.get("location") or "")
        return loc.split(",")[0].strip()
    if kind == "country":
        return country_of(p)
    return portal.answer_for(kind, p, role)


def wanted_for(kind: str, label: str, profile: dict, role: dict) -> list:
    """The options worth choosing for a drop-down or radio group, best first.
    Only things your profile or the role settle; anything else is a
    question."""
    p = profile or {}
    if kind == "country":
        return [w for w in [country_of(p)] if w]
    if kind in ("city", "location"):
        loc = str(p.get("location") or "")
        return [w for w in [loc.split(",")[0].strip(), loc] if w]
    if kind == "phone_code":
        pp = phone_parts(p.get("phone", ""))
        return [w for w in [pp["phone_code"], pp["country"]] if w]
    if kind == "phone_type":
        return ["Mobile", "Cell", "Cellular", "Mobile phone"]
    if kind == "source":
        # where the advert was found, said the way these lists put it
        src = str((role or {}).get("source") or "").lower()
        if "linkedin" in src:
            return ["LinkedIn"]
        company_feed = re.search(r"\((greenhouse|lever|ashby|workable|smartrecruiters|recruitee|workday|"
                                 r"bamboohr|personio)\)", src)
        if company_feed or (not src and re.search(r"greenhouse\.io|lever\.co|ashbyhq|workable\.com|"
                                                  r"smartrecruiters|myworkdayjobs",
                                                  str((role or {}).get("url") or ""), re.I)):
            return ["Company website", "Company careers site", "Careers page", "Website", "Other"]
        return ["Job board", "Online job board", "Job site", "Job website", "Internet", "Website", "Other"]
    if kind == "notice":
        a = str(p.get("availability") or "")
        return [a] if a else []
    return []


def best_option(wanted: list, options: list) -> int:
    """Index of the option that best matches what's wanted, or -1. Exact,
    then starts-with, then whole-word containment either way. A placeholder
    ("Select...") is never chosen."""
    opts = [norm(o) for o in options or []]
    for w in [norm(x) for x in wanted or [] if str(x or "").strip()]:
        if not w:
            continue
        tests = (lambda o: o == w,
                 lambda o: o.startswith(w + " ") or o.startswith(w + ",") or o.startswith(w + "("),
                 lambda o: re.search(r"(^|\W)" + re.escape(w) + r"(\W|$)", o) is not None,
                 lambda o: len(o) >= 3 and re.search(r"(^|\W)" + re.escape(o) + r"(\W|$)", w) is not None)
        for t in tests:
            for i, o in enumerate(opts):
                if o and not is_placeholder(options[i]) and t(o):
                    return i
    return -1


def yes_no(answer: str) -> str:
    a = str(answer or "").strip().lower()
    if re.match(r"^(yes|y|true)\b", a):
        return "Yes"
    if re.match(r"^(no|n|false)\b", a):
        return "No"
    return ""


_NOT_THE_FORM = re.compile(r"\bsearch\b|keyword|newsletter|subscri|job alert|mailing list|filter|sort by|"
                           r"talent (community|network|pool)|\bfooter\b", re.I)


def is_application_control(c: dict) -> bool:
    lab = f"{c.get('label', '')} {c.get('hint', '')}".lower()
    if _NOT_THE_FORM.search(lab) or _NOT_THE_FORM.search(str(c.get("area") or "")):
        return False
    return c.get("kind") in ("text", "textarea", "select", "radio", "combo", "file", "checkgroup")


def page_kind(snap: dict) -> str:
    """captcha, login, closed, success, form or advert."""
    if snap.get("captcha"):
        return "captcha"
    controls = [c for c in snap.get("controls") or [] if is_application_control(c)]
    known = 0
    for c in controls:
        if classify(c.get("label", ""), c.get("hint", "")) in (
                "first_name", "last_name", "full_name", "email", "phone", "resume", "linkedin",
                "location", "cover_letter"):
            known += 1
    files = [c for c in controls if c.get("kind") == "file"]
    form = known >= 2 or (files and known >= 1) or len([c for c in controls if c.get("required")]) >= 3
    if snap.get("password") and not form:
        return "login"
    if not form and is_interstitial(snap):
        return "interstitial"
    head = " ".join(snap.get("headings") or [])
    text = f"{head} {snap.get('title', '')} {str(snap.get('text') or '')[:3000]}"
    if _SUCCESS_TEXT.search(text) and not form:
        return "success"
    if _CLOSED_TEXT.search(text) and not form:
        return "closed"
    if form:
        return "form"
    if snap.get("password"):
        return "login"
    return "advert"


def is_interstitial(snap: dict) -> bool:
    """A holding page: little on it but a 'checking your browser' or
    'redirecting' line, and nothing to press."""
    text = f"{snap.get('title', '')} {str(snap.get('text') or '')[:1500]}"
    real = [b for b in snap.get("buttons") or [] if not b.get("banner")]
    return bool(_INTERSTITIAL.search(text)) and len(text) < 1600 and len(real) <= 2


def looks_unrendered(snap: dict) -> bool:
    """A page read before its script drew it: no buttons, no boxes, no words."""
    return not (snap.get("buttons") or snap.get("controls")) and len(str(snap.get("text") or "")) < 80


def describe_action(a: dict) -> str:
    t = str(a.get("tool") or "?")
    bits = [t] + [f"{k}={str(a[k])[:40]}" for k in ("ref", "field", "result") if a.get(k)]
    return " ".join(bits)


def apply_email(snap: dict) -> str:
    """An address the advert asks applications to be sent to, or ''."""
    from . import jobscout
    text = str(snap.get("text") or "")
    for m in _EMAIL.finditer(text):
        addr = m.group(0).strip(".").lower()
        if any(bad in addr for bad in jobscout._NOT_APPLY):
            continue
        around = text[max(0, m.start() - 140):m.end() + 60]
        if _APPLY_BY_MAIL.search(around) and re.search(r"\b(cv|c\.v\.|resume|résumé|applications?|apply)\b",
                                                     around, re.I):
            return addr
    return ""


def fingerprint(snap: dict) -> str:
    labels = sorted(norm(c.get("label", ""))[:40] for c in (snap.get("controls") or [])[:40])
    path = re.sub(r"[?#].*$", "", str(snap.get("url") or ""))
    return path + "|" + "|".join(labels) + "|" + str(len(snap.get("buttons") or []) // 5)


def required_empty(snap: dict) -> list:
    return [c for c in snap.get("controls") or []
            if c.get("required") and not has_value(c) and is_application_control(c)]


def compact(snap: dict) -> dict:
    """The page as the engine sees it: no values of yours, only whether a box
    is filled; options and buttons trimmed to what matters."""
    controls = []
    for c in (snap.get("controls") or [])[:45]:
        item = {"ref": c.get("ref"), "kind": c.get("kind"), "label": str(c.get("label") or "")[:140]}
        if c.get("required"):
            item["required"] = True
        if has_value(c):
            item["filled"] = True
        if c.get("kind") in ("radio", "checkgroup"):
            item["options"] = [{"ref": o.get("ref"), "text": str(o.get("text") or "")[:60]}
                               for o in (c.get("options") or [])[:14]]
        elif c.get("options"):
            opts = [o for o in c["options"] if not is_placeholder(o)]
            item["options"] = [str(o)[:60] for o in opts[:18]] + (
                [f"… {len(opts) - 18} more"] if len(opts) > 18 else [])
        if c.get("invalid"):
            item["invalid"] = True
        controls.append(item)

    def rank(b):
        k = cta_kind(b, bool(snap.get("_form")))
        s = {"apply": 0, "next": 0, "submit": 1, "": 3}.get(k, 4)
        s += (0 if b.get("in_form") else 1) + (2 if b.get("nav") else 0)
        return s
    buttons = []
    for b in sorted([b for b in snap.get("buttons") or [] if not b.get("banner")], key=rank)[:40]:
        item = {"ref": b.get("ref"), "kind": b.get("kind"), "text": str(b.get("text") or "")[:80]}
        if b.get("href") and not str(b["href"]).startswith("javascript"):
            item["to"] = re.sub(r"^https?://(www\.)?", "", str(b["href"]))[:90]
        if b.get("target") == "_blank":
            item["new_tab"] = True
        buttons.append(item)
    return {"url": str(snap.get("url") or "")[:200], "title": str(snap.get("title") or "")[:120],
            "headings": (snap.get("headings") or [])[:6], "errors": (snap.get("errors") or [])[:6],
            "text": str(snap.get("text") or "")[:1600], "controls": controls, "buttons": buttons,
            "signals": {k: True for k in ("cookie", "captcha", "password") if snap.get(k)}}


# --------------------------------------------------------------------------- #
#  the fill plan: what can be done on this page without asking anyone
# --------------------------------------------------------------------------- #
def fill_plan(snap: dict, profile: dict, role: dict, *, url: str = "", ats: str = "",
              cv_path: str = "", cover_path: str = "") -> dict:
    """{acts: [...], questions: [...], left: [...]}. acts are actions for the
    driver with the label and kind they're for; questions are what only your
    profile (through the checked answer engine) can settle; left is what's
    yours, with why."""
    from . import portal
    acts, questions, left = [], [], []
    for c in snap.get("controls") or []:
        label = str(c.get("label") or "").strip()
        kindctl = c.get("kind")
        if not is_application_control(c) and kindctl != "checkbox":
            continue
        if kindctl == "checkbox":
            if c.get("required") and not has_value(c):
                left.append(f"{label or 'a tick box'} (yours to tick)")
            continue                       # nothing is ever ticked for you
        options = [o.get("text", "") for o in c.get("options") or []] if kindctl in ("radio", "checkgroup") \
            else list(c.get("options") or [])
        if has_value(c):
            continue
        if sensitive_label(label, options):
            saved = portal._saved_answer(label)           # only if you switched reuse on
            if saved and kindctl in ("text", "textarea"):
                acts.append({"do": "fill", "ref": c["ref"], "value": saved, "label": label,
                             "kind": "saved", "by": "saved"})
            elif saved and options:
                i = best_option([yes_no(saved) or saved, saved], options)
                if i >= 0:
                    acts.append(_choose(c, i, options, label, "saved"))
                elif c.get("required"):
                    left.append(f"{label} (yours to answer)")
            elif c.get("required"):
                left.append(f"{label} (yours to answer)")
            continue
        if kindctl == "checkgroup":
            if c.get("required"):
                questions.append({"ref": c["ref"], "label": label, "options": options, "control": c})
            continue
        kind = classify(label, c.get("hint", ""), url, ats)
        if kindctl == "file":
            low = f"{label} {c.get('hint', '')}".lower()
            if kind == "cover_letter" or "cover" in low:
                if cover_path and _accepts(c, cover_path):
                    acts.append({"do": "upload", "ref": c["ref"], "value": cover_path, "label": label,
                                 "kind": "cover_letter", "by": "rule"})
                elif c.get("required"):
                    left.append(f"{label or 'a file'} (attach your covering letter)")
            elif kind == "resume" or re.search(r"\b(cv|resume|résumé|curriculum)\b", low) or not label \
                    or len([x for x in snap.get("controls") or [] if x.get("kind") == "file"]) == 1:
                if cv_path:
                    acts.append({"do": "upload", "ref": c["ref"], "value": cv_path, "label": label or "CV",
                                 "kind": "resume", "by": "rule"})
                elif c.get("required"):
                    left.append(f"{label or 'CV'} (no CV file to attach)")
            elif c.get("required"):
                left.append(f"{label or 'a file'} (a file only you have)")
            continue
        saved = portal._saved_answer(label)
        if kindctl in ("text", "textarea"):
            value = value_for(kind, profile, role) if kind and kind != "sensitive" else ""
            value = value or saved
            if value and not _fits(c, value):
                value = ""
            if value:
                acts.append({"do": "fill", "ref": c["ref"], "value": value, "label": label,
                             "kind": kind or "saved", "by": "saved" if value == saved and saved else "rule"})
            elif c.get("required"):
                questions.append({"ref": c["ref"], "label": label, "options": [], "control": c, "kind": kind})
            continue
        wanted = ([yes_no(saved) or saved, saved] if saved else []) + wanted_for(kind, label, profile, role)
        if kindctl == "combo":
            if wanted:
                acts.append({"do": "combo", "ref": c["ref"], "wanted": wanted,
                             "type_text": _combo_typing(kind, wanted), "label": label,
                             "kind": kind or "saved", "by": "saved" if saved else "rule",
                             "required": bool(c.get("required"))})
            elif c.get("required"):
                questions.append({"ref": c["ref"], "label": label, "options": [], "control": c, "kind": kind})
            continue
        i = best_option(wanted, options) if wanted else -1
        if i >= 0:
            acts.append(_choose(c, i, options, label, "saved" if saved else "rule", kind))
        elif c.get("required"):
            questions.append({"ref": c["ref"], "label": label, "options": [o for o in options
                                                                         if not is_placeholder(o)],
                              "control": c, "kind": kind})
    return {"acts": acts, "questions": questions, "left": left}


def _choose(c: dict, i: int, options: list, label: str, by: str, kind: str = "") -> dict:
    if c.get("kind") == "radio":
        o = (c.get("options") or [])[i]
        return {"do": "check", "ref": o.get("ref"), "value": o.get("text"), "label": label,
                "kind": kind or "saved", "by": by}
    return {"do": "select", "ref": c["ref"], "value": options[i], "index": i, "label": label,
            "kind": kind or "saved", "by": by}


def _combo_typing(kind: str, wanted: list) -> str:
    w = str(wanted[0] if wanted else "")
    if kind in ("city", "location"):
        return w.split(",")[0].strip()[:30]
    return w[:30]


def _fits(c: dict, value: str) -> bool:
    """A date box doesn't take "30 days"; a number box doesn't take "R85k pm"."""
    t = str(c.get("type") or "").lower()
    v = str(value or "").strip()
    if t == "date":
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", v))
    if t == "number":
        return bool(re.match(r"^-?\d+(\.\d+)?$", v))
    if t == "email":
        return "@" in v
    if t in ("url",):
        return bool(re.match(r"^https?://", v))
    mx = int(c.get("max") or 0)
    return not mx or len(v) <= mx


def _accepts(c: dict, path: str) -> bool:
    acc = str(c.get("accept") or "").lower()
    if not acc:
        return True
    ext = Path(path).suffix.lower()
    return ext in acc or ("text/plain" in acc and ext == ".txt") or ("pdf" in acc and ext == ".pdf")


# --------------------------------------------------------------------------- #
#  the engine's side: one page at a time, actions through tools
# --------------------------------------------------------------------------- #
ENGINE_SYSTEM = (
    "You are the navigator for one job application. You are shown one web page at a time as JSON "
    "and act on it through the tools below. Your goal: get from the job advert to the application "
    "form and through every page of it, so the form is completely filled for the candidate to "
    "review.\n\n"
    "Absolute rules:\n"
    "- Never submit. When only a final submit/send button is left, finish with "
    "done(result=\"form_ready\").\n"
    "- Never sign in, create an account, or use \"apply with LinkedIn/Indeed/Google\". If the "
    "page needs that, finish with done(result=\"needs_you\").\n"
    "- Never tick a box that accepts terms, privacy, consent or a declaration, and never answer "
    "questions about gender, race, ethnicity, disability, veteran status, sexual orientation, "
    "religion, age, date of birth, nationality, ID numbers, criminal record or salary history. "
    "Leave them: they are the candidate's.\n"
    "- You never write the candidate's details or answers yourself. Say which of the candidate's "
    "details goes in a box (type) or ask for a question to be answered from the candidate's own "
    "profile (answer); the app does the typing.\n"
    "- Only use refs that appear in the page JSON. Don't repeat an action that failed.\n"
    "\nHow to work, every turn:\n"
    "1. Read LAST_TURNS first: each action you took and what actually happened. If something "
    "didn't work, work out why from the page before trying anything else, and choose a different "
    "route rather than repeating it.\n"
    "2. Say what this page is (advert, form page N, a chooser, a modal, an error) and what stands "
    "between it and the next step.\n"
    "3. Plan the fewest actions that clear it, and say what you expect to see afterwards.\n"
    "4. Prefer, in order: the box or button the PROBLEM names; visible error messages; required "
    "boxes still empty; a tab, accordion or 'show more' that hides the rest; scrolling. A modal or "
    "overlay sits in front of the page: deal with it (close or continue) first.\n"
    "5. When you're unsure what a button does, don't press it: a wrong press can lose the form.\n"
    "- If the page says the job is closed, finish with done(result=\"closed\"). If this site has "
    "no form and asks for applications another way (an email address, say), finish with "
    "done(result=\"no_form\") and say how in \"why\".\n\n"
    "Tools, one JSON object each:\n"
    "  {\"tool\":\"click\",\"ref\":\"…\"}  press a button, link or tab\n"
    "  {\"tool\":\"type\",\"ref\":\"…\",\"field\":\"<one of CANDIDATE_HAS>\"}\n"
    "  {\"tool\":\"answer\",\"ref\":\"…\"}  a question the candidate's own profile answers "
    "(free text or a choice)\n"
    "  {\"tool\":\"upload\",\"ref\":\"…\",\"what\":\"cv\"}\n"
    "  {\"tool\":\"scroll\"}  {\"tool\":\"back\"}\n"
    "  {\"tool\":\"note\",\"text\":\"…\"}  one sentence worth knowing the next time this site is "
    "used (how to reach the form, what it wants)\n"
    "  {\"tool\":\"done\",\"result\":\"form_ready|needs_you|no_form|closed\",\"why\":\"…\"}\n\n"
    "Reply with JSON only: {\"thinking\":\"what this page is, what blocks it, your plan\","
    "\"expect\":\"what the page should show after your actions\",\"actions\":[ …at most "
    f"{ACTIONS_PER_TURN}… ]}}. A click that changes the page ends your turn; you'll see the new page."
)


class Stop(Exception):
    """The run is over; carries the state and message."""

    def __init__(self, state: str, message: str, ok: bool | None = None):
        super().__init__(message)
        self.state, self.message, self.ok = state, message, ok


class _Workday(Exception):
    """The application moved onto Workday: its own walker takes it."""


def _same_page(a: dict, b: dict) -> bool:
    """Still the same page of the form? A tab or "enter manually" adds a box
    or two; the next page changes most of them."""
    la = {norm(c.get("label", "")) for c in a.get("controls") or [] if c.get("label")}
    lb = {norm(c.get("label", "")) for c in b.get("controls") or [] if c.get("label")}
    if re.sub(r"[?#].*$", "", str(a.get("url") or "")) != re.sub(r"[?#].*$", "", str(b.get("url") or "")) \
            and not (la and la == lb):
        return False
    if not la and not lb:
        return True
    return len(la & lb) / max(1, len(la | lb)) >= 0.5


class Navigator:
    def __init__(self, driver, page, role: dict, profile: dict, result: dict, *, submit: bool = False,
                 brain=None, model=None, wait: bool = False, session_key: str = "",
                 turns: int = DEFAULT_TURNS, budget_s: float = TIME_BUDGET_S):
        self.d, self.page, self.first_page = driver, page, page
        self.role, self.p = dict(role or {}), dict(profile or {})
        self.result = result
        self.submit, self.brain, self.model = bool(submit), brain, model
        self.wait, self.key = bool(wait), str(session_key or "")
        self.turns_left = max(0, int(turns or 0)) if brain is not None else 0
        self.engine_turns = 0
        self.engine_log: list = []         # what the engine did, and what really happened
        self.rescued: dict = {}            # page fingerprint -> fresh looks spent on it
        self.engine_errors = 0
        self.budget_s = budget_s
        self.start = time.time()
        self.waited = 0.0
        self.steps: list = []
        self.learned: list = []
        self.answers: list = []
        self.filled: list = []
        self.left: list = []
        self.pages = 0
        self.ats0 = ""
        self.pending: dict | None = None
        self.stuck = 0
        self.seen: dict = {}
        self.failed: set = set()
        self.cookie_done = False
        self.scrolled: set = set()
        self.payloads: list = []           # what the engine was shown
        self.cv_path = str(self.p.get("cv_path") or "")
        self.cover_path = ""
        self.snap: dict = {}
        self.on_form = False
        self.form_url = ""
        self.advert_url = str(result.get("url") or "")
        self.submitted_click = False
        self.unanswered: dict = {}         # questions nothing answered yet, by label

    # --- small things ------------------------------------------------------
    def say(self, text: str, by: str = "rule", ok: bool = True) -> None:
        self.steps.append({"say": text, "by": by, "ok": ok})
        if self.key:
            try:
                from . import portal
                if (portal.session(self.key) or {}).get("state") == portal.RUNNING:
                    portal._set_session(self.key, message=text)
            except Exception:
                pass

    def learn(self, sentence: str) -> None:
        if sentence and sentence not in self.learned:
            self.learned.append(sentence)

    def url(self) -> str:
        return str(self.snap.get("url") or "")

    def look(self) -> dict:
        snap = self.d.snapshot(self.page) or {}
        for _ in range(2):                 # read too early: give its script a moment, once or twice
            if not looks_unrendered(snap):
                break
            self._pause(1.5)
            snap = self.d.snapshot(self.page) or {}
        snap["_form"] = page_kind(snap) == "form"
        self.snap = snap
        return snap

    def act(self, action: dict) -> dict:
        from . import portal
        if action.get("do") == "fill":
            portal.note_app_typed(action.get("value"))
        res = self.d.act(self.page, action) or {}
        newp = res.get("page")
        if newp is not None and newp is not self.page:
            self.page = newp
        return res

    def _pause(self, seconds: float) -> None:
        try:
            _settle(self.page, int(seconds * 1000))
        except Exception:
            pass
        try:
            self.page.wait_for_timeout(int(seconds * 1000))
        except Exception:
            time.sleep(min(seconds, 0.05))

    def _sit_out_interstitial(self) -> bool:
        """Wait for a holding screen to clear by itself. True when it did."""
        self.say("The site is checking the browser; waiting for it")
        t0 = time.time()
        while time.time() - t0 < INTERSTITIAL_WAIT_S:
            self._pause(2.5)
            snap = self.look()
            if page_kind(snap) != "interstitial":
                self.say("The check cleared by itself")
                return True
            if time.time() - t0 > 60:      # a fake clock in tests
                break
        return False

    def _rescue(self, snap: dict, problem: str) -> bool:
        """One more look by the engine at a page about to be given up on,
        with everything already tried in front of it."""
        fp = fingerprint(snap)
        if self.brain is None or self.engine_errors >= 2 or self.rescued.get(fp, 0) >= RESCUES_PER_PAGE:
            return False
        if self.engine_turns >= MAX_ENGINE_TURNS:
            return False
        self.rescued[fp] = self.rescued.get(fp, 0) + 1
        self.turns_left = max(self.turns_left, 1)
        self.say("Stuck here, so it's taking a careful second look", "engine")
        return self._engine(snap, "RESCUE: " + problem + " Everything tried so far is in LAST_TURNS and "
                                  "DONE_SO_FAR and none of it worked. Look again at the whole page: a hidden "
                                  "tab or section, a modal in front, a different button, a link lower down. "
                                  "Pick something not yet tried, or finish with done(needs_you) and say why.")

    def ats_here(self) -> str:
        """The hiring system behind this page: its address, or the address of
        a form it embeds (a company's careers page with Greenhouse inside), so
        what this form teaches is shared with every company that uses it."""
        from . import portal
        for u in [self.url()] + [str(f).split(" ")[0] for f in self.snap.get("frames") or []]:
            a = portal.detect_ats(u, "") if u.startswith("http") else "unknown"
            if a != "unknown":
                return a
        return ""

    def _where(self) -> str:
        return f"It's open at {self.url()[:120]}." if self.url() else ""

    def _missing(self, snap: dict) -> list:
        out = []
        for c in required_empty(snap):
            opts = [o.get("text") if isinstance(o, dict) else o for o in c.get("options") or []]
            if sensitive_label(c.get("label", ""), opts):
                continue
            out.append(c)
        return out

    def _needs_answers_message(self) -> str:
        """Which boxes, for which job, and the two ways to deal with them."""
        job = " at ".join(x for x in (str(self.role.get("title") or ""), str(self.role.get("company") or ""))
                          if x.strip())
        items = [x.replace(" (needs an answer)", "") for x in self.left[:6]]
        listed = "\n".join(f"  • {x}" for x in items)
        more = f"\n  …and {len(self.left) - 6} more" if len(self.left) > 6 else ""
        return (f"Your answers are needed{' for ' + job if job else ''}. It filled everything else, "
                f"and stopped at {'this question' if len(items) == 1 else 'these questions'}:\n"
                f"{listed}{more}\n"
                "Either answer them in the open browser window and submit it yourself, or answer them "
                "once under Answers → Waiting on you: then this form, and every later one that asks, "
                "is filled for you. Nothing was submitted.")

    def _over_budget(self) -> bool:
        return time.time() - self.start - self.waited > self.budget_s

    # --- the run -----------------------------------------------------------
    def run(self) -> dict:
        from . import portal
        try:
            self._loop()
            raise Stop(portal.UNKNOWN_FORM, "It went round more times than any application should "
                                            "take, so it stopped. Nothing was submitted.")
        except Stop as s:
            return self.finish(s.state, s.message, s.ok)
        except _Workday:
            raise
        except Exception as exc:                 # a browser fault: say it, keep what was learned
            return self.finish(portal.FAILED, portal._explain_portal_error(exc), False)

    def _loop(self) -> None:
        from . import portal
        self.say("Opened the advert")
        for _ in range(MAX_LOOPS):
            if self._over_budget():
                raise Stop(portal.UNKNOWN_FORM, "It took longer than an application should, so it "
                                                "stopped where it was. Nothing was submitted.")
            snap = self.look()
            kind = page_kind(snap)
            if not self.ats0:
                self.ats0 = self.ats_here() or "-"
            self._resolve_pending(kind)
            fp = fingerprint(snap)
            self.seen[fp] = self.seen.get(fp, 0) + 1
            if kind in ("captcha", "login"):
                state = portal.NEEDS_CAPTCHA if kind == "captcha" else portal.NEEDS_LOGIN
                self.learn(playbooks.block(self.url(), state))
                self.say("A captcha needs you" if kind == "captcha" else "This site wants you signed in",
                         "rule", False)
                if not self._wait_for_you(state):
                    raise Stop(state, portal.handover_message(state))
                self.say("Carrying on after you")
                continue
            if kind == "interstitial":
                if self._sit_out_interstitial():
                    continue
                self.learn(playbooks.block(self.url(), portal.NEEDS_CAPTCHA))
                self.say("The site's check didn't clear by itself, so it needs you", "rule", False)
                if not self._wait_for_you(portal.NEEDS_CAPTCHA):
                    raise Stop(portal.NEEDS_CAPTCHA, portal.handover_message(portal.NEEDS_CAPTCHA))
                continue
            if kind == "closed":
                raise Stop(CLOSED, "The advert says the role is closed, so there's nothing to apply to.")
            if kind == "success":
                if self.submitted_click:
                    raise Stop(portal.SUBMITTED, "Submitted.", True)
                raise Stop(portal.UNKNOWN_FORM, "The page says an application was received, but this "
                                                "run didn't send one. Check the site before applying again.")
            away = never_automated(self.url())
            if away:
                raise Stop(portal.UNKNOWN_FORM, f"This advert sends applications to {away}, which are yours to "
                                                f"make: automating them breaks {away}'s terms. Nothing was "
                                                f"filled there.")
            if snap.get("cookie") and not self.cookie_done and self._cookies(snap):
                continue
            if re.search(r"myworkdayjobs\.com|myworkday\.com|\.workday\.com", self.url(), re.I):
                raise _Workday()
            if self.seen[fp] >= 4 and self._rescue(snap, "The run keeps arriving back at this same page."):
                continue
            if self.seen[fp] >= 4:
                raise Stop(portal.UNKNOWN_FORM, "It kept arriving back at the same page, so it stopped "
                                                "rather than loop. " + self._where())
            if kind == "form":
                if not self.on_form:
                    self.on_form = True
                    self.say("Reached the application form")
                self._form_page(snap)
                continue
            self._advert(snap)

    # --- waiting for you ---------------------------------------------------
    def _wait_for_you(self, state: str) -> bool:
        from . import portal
        if not (self.wait and self.key):
            return False
        t0 = time.time()

        def cleared() -> bool:
            try:
                return page_kind(self.d.snapshot(self.page) or {}) not in ("captcha", "login", "interstitial")
            except Exception:
                return False
        try:
            ok = portal._wait_for_person(self.key, self.d, self.page, state, cleared=cleared,
                                          role=self.role)
        finally:
            self.waited += time.time() - t0
        if ok:
            portal._set_session(self.key, state=portal.RUNNING, message="Thanks — carrying on.")
            self.result["waited_for_you"] = state
        return ok

    # --- cookie banners: declined, never accepted ----------------------------
    def _cookies(self, snap: dict) -> bool:
        self.cookie_done = True
        btns = [b for b in snap.get("buttons") or [] if b.get("banner")]
        pick = next((b for b in btns if cta_kind(b) == "cookie_reject"), None) \
            or next((b for b in btns if cta_kind(b) == "close"), None)
        if pick is None:
            return False
        res = self.act({"do": "click", "ref": pick["ref"]})
        if res.get("ok"):
            self.say(f"Declined the cookie banner (“{pick['text'][:40]}”)")
            return True
        return False

    # --- from the advert to the form ----------------------------------------
    def _advert(self, snap: dict) -> None:
        from . import portal
        if self.stuck >= 4 and self._rescue(snap, "None of the buttons tried so far led to the form."):
            return
        if self.stuck >= 4:
            raise Stop(portal.UNKNOWN_FORM, "None of the buttons it tried led to the form. " + self._where())
        btns = [b for b in snap.get("buttons") or [] if not b.get("banner") and b["ref"] not in self.failed]
        # 1. what worked on this site (or this hiring system) before
        for st in playbooks.route(self.url(), self.ats_here()):
            b = next((b for b in btns if norm(b.get("text")) == st["text"]
                      and cta_kind(b) not in ("login", "submit", "danger", "away", "file", "consent")), None)
            if b is not None and self._click_to_form(
                    b, "playbook", f"Pressed “{b['text'][:50]}” (learned on an earlier application)"):
                return
        # 2. a button that sends an email is the advert telling you how to apply
        for b in btns:
            href = str(b.get("href") or "")
            if href.lower().startswith("mailto:") and (cta_kind({**b, "href": ""}) == "apply"
                                                       or _APPLY_BY_MAIL.search(b.get("text", ""))):
                addr = apply_email({"text": "apply cv " + href[7:].split("?")[0]})
                if addr:
                    self._by_email(addr)
        # 3. the buttons every site shares
        cands = [b for b in btns if cta_kind(b) == "apply"
                 and not str(b.get("href") or "").lower().startswith("mailto:")]
        cands.sort(key=self._cta_rank)
        if cands and self._click_to_form(cands[0], "rule", f"Pressed “{cands[0]['text'][:50]}”"):
            return
        # 4. an advert that asks for an email instead of a form
        addr = apply_email(snap)
        if addr and not cands:
            self._by_email(addr)
        # 5. the engine, for a site that doesn't use the usual words
        if self.turns_left:
            self._engine(snap, "This looks like the job advert, and none of the usual apply buttons led "
                               "to a form. Find the way to the application form.")
            return
        if "advert" not in self.scrolled:
            self.scrolled.add("advert")
            self.act({"do": "scroll"})
            return
        if self._rescue(snap, "No way from this advert to the application form has been found."):
            return
        raise Stop(portal.UNKNOWN_FORM, "It couldn't find a way from the advert to the form"
                   + ("" if self.brain is not None else " (and there's no engine to work it out)")
                   + ". " + self._where())

    def _by_email(self, addr: str) -> None:
        self.result["apply_email"] = addr
        raise Stop(APPLY_BY_EMAIL, f"This advert asks for applications by email, to {addr}, and has no "
                                   f"form. It's been moved to the email path, where the usual checks apply.")

    @staticmethod
    def _cta_rank(b: dict):
        text = norm(b.get("text"))
        href = str(b.get("href") or "").lower()
        score = 0 if _APPLY_EXACT.match(text) else 2
        if re.search(r"greenhouse|lever\.co|ashbyhq|workable|smartrecruiters|recruitee|teamtailor|bamboohr|"
                     r"myworkdayjobs|/apply", href):
            score -= 1
        if b.get("nav"):
            score += 2
        if b.get("kind") == "tab":
            score += 1
        return score

    def _click_to_form(self, b: dict, by: str, say: str) -> bool:
        before = self.url()
        ats = self.ats_here()
        res = self.act({"do": "click", "ref": b["ref"]})
        if not res.get("ok"):
            self.failed.add(b["ref"])
            self.say(f"Couldn't press “{b['text'][:40]}”", by, False)
            return False
        self.say(say + (": it opened a new tab" if res.get("new_tab") else ""), by)
        self.pending = {"site": before, "ats": ats, "text": b.get("text", ""), "by": by,
                        "url": before, "ref": b["ref"], "new_tab": bool(res.get("new_tab"))}
        return True

    def _resolve_pending(self, kind: str) -> None:
        pend, self.pending = self.pending, None
        if not pend:
            return
        moved = kind == "form" or pend.get("new_tab") or \
            re.sub(r"#.*$", "", self.url()) != re.sub(r"#.*$", "", pend["url"])
        said = playbooks.learn_route(pend["site"], pend.get("ats", ""), "apply", pend["text"],
                                     ok=bool(moved), by=pend["by"])
        if said and (pend["by"] == "engine" or not _APPLY_EXACT.match(norm(pend["text"])) or not moved):
            self.learn(said)
        if not moved:
            self.failed.add(pend["ref"])
            self.stuck += 1
            self.say(f"“{pend['text'][:40]}” didn't lead anywhere", pend["by"], False)

    # --- one page of the form --------------------------------------------------
    def _form_page(self, snap: dict) -> None:
        from . import portal
        self.form_url = self.url()
        plan = fill_plan(snap, self.p, self.role, url=self.url(), ats=self.ats_here(),
                         cv_path=self.cv_path, cover_path=self._cover_file())
        done_now = []
        for a in plan["acts"]:
            if a["ref"] in self.failed:
                continue
            res = self.act({k: v for k, v in a.items() if k in ("do", "ref", "value", "index",
                                                                 "wanted", "type_text")})
            if res.get("ok"):
                value = res.get("chosen") or a.get("value") or ""
                self.filled.append({"kind": a.get("kind"), "label": a.get("label"),
                                    "value": value if a["do"] != "upload" else Path(str(value)).name,
                                    "by": a.get("by")})
                done_now.append(a)
            else:
                self.failed.add(a["ref"])
                if a.get("do") == "combo" and a.get("required"):
                    plan["questions"].append({"ref": a["ref"], "label": a.get("label", ""),
                                              "options": res.get("options") or [],
                                              "control": {"kind": "combo"}, "kind": a.get("kind")})
        if done_now:
            self.say(_describe_fills(done_now), "rule" if all(a.get("by") != "saved" for a in done_now)
                     else "saved")
        if plan["questions"]:
            self._answer(plan["questions"])
        for x in plan["left"]:
            if x not in self.left:
                self.left.append(x)
        snap = self.look()
        missing = [c for c in self._missing(snap) if c.get("ref") not in self.failed]
        if missing and self.turns_left and not self.left:
            names = "; ".join(str(c.get("label") or c.get("kind"))[:60] for c in missing[:8])
            if self._engine(snap, f"These required boxes are still empty and the app couldn't place them: "
                                  f"{names}. Say which of the candidate's details goes in each (type), or "
                                  f"have it answered from the profile (answer). Leave sensitive and consent "
                                  f"ones alone."):
                return                       # the engine moved the page on
            snap = self.look()
            missing = self._missing(snap)
        for c in missing:
            what = str(c.get("label") or c.get("kind") or "a box")[:80]
            if not any(x.startswith(what) for x in self.left):
                self.left.append(what + " (needs an answer)")
        if self.left:
            raise Stop(portal.NEEDS_ANSWER, self._needs_answers_message())
        self._forward(snap)

    def _forward(self, snap: dict) -> None:
        """The next page, or the end of the form."""
        from . import portal
        btns = [b for b in snap.get("buttons") or [] if not b.get("banner") and b["ref"] not in self.failed]
        nxt, by = None, "rule"
        for t in playbooks.texts(self.url(), self.ats_here(), "next"):
            nxt = next((b for b in btns if norm(b.get("text")) == t
                        and cta_kind(b, True) not in ("submit", "login", "danger", "away", "file", "consent")),
                       None)
            if nxt is not None:
                by = "playbook"
                break
        if nxt is None:
            nxt = next((b for b in btns if cta_kind(b, True) == "next"), None)
        subs = [b for b in btns if cta_kind(b, True) == "submit" and not b.get("nav")]
        subs.sort(key=lambda b: (not b.get("in_form"), b.get("kind") == "link"))
        sub = subs[0] if subs else None
        if nxt is not None:
            if self.pages >= MAX_FORM_PAGES:
                raise Stop(portal.UNKNOWN_FORM, "The form went on for more pages than any should, so it "
                                                "stopped. " + self._where())
            res = self.act({"do": "click", "ref": nxt["ref"]})
            if not res.get("ok"):
                self.failed.add(nxt["ref"])
                return
            after = self.look()
            if _same_page(snap, after) and not res.get("new_tab"):
                errs = after.get("errors") or []
                self.say(f"“{nxt['text'][:30]}” didn't move on" + (": " + "; ".join(errs[:3]) if errs else ""),
                         by, False)
                if self.turns_left:
                    self._engine(after, "The form didn't move on to its next page. Its messages: "
                                        + ("; ".join(errs[:6]) or "(none shown)")
                                        + ". Fix what it complains about with your tools, then press its "
                                          "next button again.")
                    return
                raise Stop(portal.UNKNOWN_FORM, "The form didn't accept a page: "
                           + ("; ".join(errs[:4]) or "it wants something it didn't say")
                           + ". It's open for you to finish.")
            self.pages += 1
            self.learn(playbooks.learn_button(self.form_url or self.url(), self.ats_here(), "next",
                                              nxt.get("text", "")))
            self.say(f"Pressed “{nxt['text'][:40]}” to the next page", by)
            return
        if sub is not None:
            self._finish_form(sub)
            return
        if self.turns_left:
            errs = snap.get("errors") or []
            self._engine(snap, ("The form shows these messages: " + "; ".join(errs[:6]) + ". Fix what they "
                                "complain about with your tools, then press the button that goes on."
                                if errs else
                                "Everything the app could fill is filled, and it can't see the button to "
                                "the next page. Find it (it may be lower down or under a tab), or say done "
                                "if the form is complete."))
            return
        if "form" not in self.scrolled:
            self.scrolled.add("form")
            self.act({"do": "scroll"})
            return
        if self._rescue(snap, "Everything fillable is filled but no button to go on has been found."):
            return
        raise Stop(portal.UNKNOWN_FORM, "Filled in what's on this page, but it couldn't tell how to go on: "
                                        "there's no next or submit button it recognises"
                   + ("" if self.brain is not None else " (and no engine to work it out)")
                   + ". Finish it in the open browser.")

    def _finish_form(self, sub: dict) -> None:
        """Every box that can be filled is: stop for you, or submit."""
        from . import portal
        snap = self.look()
        missing = self._missing(snap)
        for c in missing:
            what = str(c.get("label") or c.get("kind") or "a box")[:80]
            if not any(x.startswith(what) for x in self.left):
                self.left.append(what + " (needs an answer)")
        if self.left:
            raise Stop(portal.NEEDS_ANSWER, self._needs_answers_message())
        if not self.submit:
            raise Stop(portal.FILLED, "Filled in and left for you to read. Press "
                                      f"“{str(sub.get('text') or 'Submit')[:30]}” in the browser when "
                                      "you're happy with it.", True)
        if snap.get("captcha") and not self._wait_for_you(portal.NEEDS_CAPTCHA):
            raise Stop(portal.NEEDS_CAPTCHA, portal.handover_message(portal.NEEDS_CAPTCHA))
        res = self.act({"do": "click", "ref": sub["ref"]})
        if not res.get("ok"):
            raise Stop(portal.UNKNOWN_FORM, portal.handover_message(
                portal.UNKNOWN_FORM, "everything is filled but the submit button didn't respond: "
                                     "press it yourself"))
        self.submitted_click = True
        self.say(f"Pressed “{str(sub.get('text') or 'Submit')[:30]}”")
        self.learn(playbooks.learn_button(self.url(), self.ats_here(), "submit", sub.get("text", "")))
        after = self.look()
        k = page_kind(after)
        if k == "success":
            raise Stop(portal.SUBMITTED, "Submitted.", True)
        if k not in ("form", "captcha", "login") and not after.get("errors"):
            # sent: pressing it again would be a second application
            raise Stop(portal.SUBMITTED, "Submitted: the form went away without an error, though the page "
                                         "didn't say it was received. Look out for the acknowledgement "
                                         "email.", True)
        if k in ("captcha", "login"):
            state = portal.NEEDS_CAPTCHA if k == "captcha" else portal.NEEDS_LOGIN
            if self._wait_for_you(state):
                return                       # the loop reads the page that follows
            raise Stop(state, portal.handover_message(state) + " It was about to be submitted.")
        errs = after.get("errors") or []
        raise Stop(portal.UNKNOWN_FORM, "It pressed submit and the form answered: "
                   + ("; ".join(errs[:4]) or "nothing it could read") + ". Check it in the open browser.")

    # --- questions only your profile answers ------------------------------------
    def _answer(self, questions: list) -> None:
        from . import portal
        if not questions:
            return
        items = []
        for q in questions:
            opts = [o for o in q.get("options") or [] if o and not is_placeholder(o)]
            text = q["label"] + (f" (choose one: {' / '.join(str(o) for o in opts[:12])})" if opts else "")
            items.append((q, text, opts))
        # an answer that is one of the form's own options claims nothing the
        # form didn't offer: those words are fair, like the advert's
        offered = " ".join(str(o) for _, _, opts in items for o in opts)
        role = {**self.role, "summary": (str(self.role.get("summary") or "") + " " + offered).strip()}
        got = portal._answer_questions(role, self.p, [t for _, t, _ in items], self.brain, self.model)
        by_q = {a.get("question"): a for a in got}
        n = 0
        for q, text, opts in items:
            a = dict(by_q.get(text) or {"question": text, "answer": "", "source": "blank"})
            a["question"] = q["label"]
            self.answers.append(a)
            if not a.get("answer") or a.get("source") != "engine":
                self.unanswered[q["label"]] = True
                continue
            if self._put_answer(q, a["answer"]):
                n += 1
                self.unanswered.pop(q["label"], None)
                self.filled.append({"kind": "answer", "label": q["label"], "value": a["answer"],
                                    "by": "saved" if a.get("saved") else "engine"})
            else:
                self.failed.add(q["ref"])
        if n:
            self.say(f"Answered {n} question(s) from your profile", "engine")

    def _ask_you(self, label: str) -> None:
        try:
            from . import answerbank
            r = self.role
            answerbank.ask(label, " @ ".join(str(x) for x in (r.get("title"), r.get("company")) if x),
                           str(r.get("key", "")))
        except Exception:
            pass

    def _put_answer(self, q: dict, answer: str) -> bool:
        c = q.get("control") or {}
        kind = c.get("kind") or "text"
        if kind in ("text", "textarea"):
            if not _fits(c, answer):
                return False
            return bool(self.act({"do": "fill", "ref": q["ref"], "value": answer}).get("ok"))
        wanted = [yes_no(answer) or answer, answer]
        if kind == "combo":
            return bool(self.act({"do": "combo", "ref": q["ref"], "wanted": wanted,
                                  "type_text": wanted[0][:30]}).get("ok"))
        if kind == "checkgroup":
            parts = [p.strip() for p in re.split(r"[,;]|\band\b", answer) if p.strip()]
            ok = False
            for o in c.get("options") or []:
                if consent_label(o.get("text", "")):
                    continue
                if best_option(parts, [o.get("text", "")]) == 0:
                    ok = bool(self.act({"do": "check", "ref": o["ref"]}).get("ok")) or ok
            return ok
        options = [o.get("text", "") for o in c.get("options") or []] if kind == "radio" \
            else list(c.get("options") or [])
        i = best_option(wanted, options)
        if i < 0:
            return False
        act = _choose(c, i, options, q["label"], "engine")
        return bool(self.act({k: v for k, v in act.items() if k in ("do", "ref", "value", "index")}).get("ok"))

    def _cover_file(self) -> str:
        if self.cover_path:
            return self.cover_path
        body = str(((self.role or {}).get("draft") or {}).get("body") or "").strip()
        if not body:
            return ""
        try:
            from . import portal
            name = re.sub(r"[^a-z0-9]+", "-", str(self.role.get("key") or "role").lower())[:60] or "role"
            p = portal._dir() / "cover-letters" / f"{name}.txt"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body + "\n", "utf-8")
            self.cover_path = str(p)
        except Exception:
            self.cover_path = ""
        return self.cover_path

    # --- the engine ----------------------------------------------------------
    def _engine(self, snap: dict, problem: str) -> bool:
        """One engine turn: show the page, carry out the actions it chooses,
        refusing anything over the rails. True when the page moved on."""
        from . import jobscout
        if not self.turns_left or self.engine_turns >= MAX_ENGINE_TURNS:
            return False
        self.turns_left -= 1
        self.engine_turns += 1
        has = [f for f in FIELDS_THE_ENGINE_CAN_NAME if value_for(f, self.p, self.role)]
        if self.cv_path:
            has.append("cv")
        payload = {"ROLE": {k: self.role.get(k) for k in ("title", "company") if self.role.get(k)},
                   "CANDIDATE_HAS": has,
                   "SITE_NOTES": playbooks.notes(self.url())[-4:],
                   "DONE_SO_FAR": [s["say"] for s in self.steps][-10:],
                   "LAST_TURNS": self.engine_log[-8:],
                   "PROBLEM": problem,
                   "PAGE": compact(snap)}
        text = json.dumps(payload, ensure_ascii=False, default=str)
        self.payloads.append(text)
        try:
            reply = jobscout._engine_json(self.brain, text, ENGINE_SYSTEM, self.model)
            self.engine_errors = 0
        except Exception as exc:
            self.engine_errors += 1
            self.say(f"The engine couldn't help ({type(exc).__name__})", "engine", False)
            self.result["engine_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            if self.engine_errors >= 2:
                self.turns_left = 0
            return False
        actions = reply.get("actions") if isinstance(reply, dict) else None
        if actions is None and isinstance(reply, dict) and reply.get("tool"):
            actions = [reply]
        if not isinstance(actions, list) or not actions:
            self.say("The engine had no suggestion", "engine", False)
            self.turns_left = min(self.turns_left, 1)
            return False
        thought = str(reply.get("thinking") or "").strip() if isinstance(reply, dict) else ""
        expect = str(reply.get("expect") or "").strip() if isinstance(reply, dict) else ""
        if thought:
            self.say("Thinking: " + thought[:220], "engine")
        filled0 = len(self.filled)
        moved = False
        for a in actions[:ACTIONS_PER_TURN]:
            if not isinstance(a, dict):
                continue
            n0 = len(self.steps)
            try:
                moved = self._engine_action(a, snap)
            except Stop:
                self.engine_log.append({"did": describe_action(a), "outcome": "ended the run"})
                raise
            said = [st["say"] for st in self.steps[n0:]]
            outcome = "; ".join(said) or "nothing visible happened"
            if moved:
                outcome += " — the page changed"
            self.engine_log.append({"did": describe_action(a), "outcome": outcome[:240]})
            if moved:
                break                        # the page changed: the rest of its refs are stale
        if not moved and len(self.filled) == filled0:
            errs = (self.look().get("errors") or [])[:4]
            self.engine_log.append({"did": "(end of turn)", "outcome": (
                "nothing changed" + (f" — expected: {expect[:120]}" if expect else "")
                + (". The page now says: " + "; ".join(errs) if errs else ""))[:300]})
        elif self.engine_turns < MAX_ENGINE_TURNS:
            self.turns_left += 1             # a turn that got somewhere doesn't count against the budget
        return moved

    def _engine_action(self, a: dict, snap: dict) -> bool:
        """One engine action, through the rails. True when the page changed."""
        from . import portal
        tool = str(a.get("tool") or "").lower()
        ref = str(a.get("ref") or "")
        controls = {}
        for c in snap.get("controls") or []:
            controls[c.get("ref")] = c
            for o in c.get("options") or []:
                if isinstance(o, dict) and o.get("ref"):
                    controls.setdefault(o["ref"], {**c, "_option": o})
        buttons = {b.get("ref"): b for b in snap.get("buttons") or []}
        if tool == "done":
            return self._engine_done(str(a.get("result") or ""), str(a.get("why") or "")[:300], snap)
        if tool == "note":
            self.learn(playbooks.add_note(self.url(), str(a.get("text") or "")))
            return False
        if tool == "scroll":
            self.act({"do": "scroll"})
            self.say("Scrolled to see more", "engine")
            return False
        if tool == "back":
            res = self.act({"do": "back"})
            self.say("Went back a page", "engine", bool(res.get("ok")))
            return True
        if tool == "click" and ref in buttons:
            return self._engine_click(buttons[ref], snap)
        c = controls.get(ref)
        if c is None:
            self.say(f"The engine pointed at something that isn't on the page ({ref or 'no ref'})",
                     "engine", False)
            return False
        label = str(c.get("label") or "")
        opts = [o.get("text") if isinstance(o, dict) else o for o in c.get("options") or []]
        if sensitive_label(label, opts):
            self.say(f"Left “{label[:40]}” alone: it's yours to answer", "engine", False)
            return False
        opt = c.get("_option") or {}
        if c.get("kind") == "checkbox" or (opt and consent_label(str(opt.get("text") or ""))):
            self.say(f"Left “{(label or opt.get('text') or '')[:40]}” unticked: ticking is yours",
                     "engine", False)
            return False
        if tool == "click" and opt:
            tool = "answer"                  # a radio option: answered from the profile, not chosen by it
        if tool == "type":
            return self._engine_type(c, str(a.get("field") or ""), snap)
        if tool == "answer":
            self._answer([{"ref": c.get("ref"), "label": label,
                           "options": [o for o in opts if o and not is_placeholder(o)], "control": c}])
            return False
        if tool == "upload":
            if c.get("kind") != "file" or not self.cv_path:
                self.say("There's no CV file to attach" if c.get("kind") == "file"
                         else "The engine tried to upload into something that isn't a file box", "engine", False)
                return False
            res = self.act({"do": "upload", "ref": ref, "value": self.cv_path})
            if res.get("ok"):
                self.filled.append({"kind": "resume", "label": label or "CV",
                                    "value": Path(self.cv_path).name, "by": "engine"})
                self.say("Attached your CV", "engine")
            return False
        self.say(f"The engine asked for something it can't do ({tool or 'nothing'})", "engine", False)
        return False

    def _engine_done(self, res: str, why: str, snap: dict) -> bool:
        from . import portal
        if res == "closed":
            raise Stop(CLOSED, "The advert says the role is closed" + (f": {why}" if why else "."))
        if res == "no_form":
            addr = apply_email({"text": why + " " + str(snap.get("text") or "")})
            if addr:
                self._by_email(addr)
            raise Stop(portal.UNKNOWN_FORM, "There's no form to fill on this site"
                       + (f": {why}" if why else ".") + " " + self._where())
        if res == "needs_you":
            raise Stop(portal.NEEDS_ANSWER if self.on_form else portal.UNKNOWN_FORM,
                       "It needs you here" + (f": {why}" if why else ".") + " " + self._where())
        if res == "form_ready" and self.on_form:
            subs = [b for b in self.look().get("buttons") or [] if cta_kind(b, True) == "submit"
                    and not b.get("nav")]
            subs.sort(key=lambda b: (not b.get("in_form"), b.get("kind") == "link"))
            sub = subs[0] if subs else None
            if sub is not None:
                self._finish_form(sub)
            if self._missing(self.snap) or self.left:
                self._finish_form({"text": "Submit"})
            raise Stop(portal.FILLED, "Filled in and left for you to read. Submit it in the browser when "
                                      "you're happy with it.", True)
        return False

    def _engine_click(self, b: dict, snap: dict) -> bool:
        k = cta_kind(b, self.on_form)
        if k in ("submit", "login", "danger", "away", "file", "cookie_accept", "consent"):
            why = {"submit": "it would submit the application",
                   "login": "it signs in or creates an account",
                   "danger": "it signs you up, pays, shares or removes something",
                   "away": "that site's applications are never automated",
                   "file": "it only downloads a file",
                   "cookie_accept": "it accepts cookies",
                   "consent": "agreeing to anything is yours"}[k]
            self.say(f"Refused to press “{str(b.get('text', ''))[:40]}”: {why}", "engine", False)
            if k == "submit" and self.on_form:
                self._finish_form(b)         # the engine thinks it's done: check, then stop or submit
            return False
        if b["ref"] in self.failed:
            return False
        if not self.on_form:
            return self._click_to_form(b, "engine", f"Pressed “{str(b.get('text', ''))[:50]}” "
                                                    f"(worked out by the engine)")
        res = self.act({"do": "click", "ref": b["ref"]})
        if not res.get("ok"):
            self.failed.add(b["ref"])
            self.say(f"Couldn't press “{str(b.get('text', ''))[:40]}”", "engine", False)
            return False
        after = self.look()
        moved = bool(res.get("new_tab")) or not _same_page(snap, after)
        errs = after.get("errors") or []
        self.say(f"Pressed “{str(b.get('text', ''))[:40]}”" + ("" if moved or not errs else
                 ": the form answered " + "; ".join(errs[:2])), "engine", moved or not errs)
        if moved:
            if page_kind(after) == "form":
                self.pages += 1
                self.learn(playbooks.learn_button(self.form_url or self.url(), self.ats_here(), "next",
                                                  b.get("text", "")))
            return True
        return False

    def _engine_type(self, c: dict, field: str, snap: dict) -> bool:
        label = str(c.get("label") or "")
        if field not in FIELDS_THE_ENGINE_CAN_NAME or c.get("kind") not in ("text", "textarea", "combo"):
            self.say(f"Refused to type “{field or '?'}” into “{label[:40]}”", "engine", False)
            return False
        value = value_for(field, self.p, self.role)
        if not value or not _fits(c, value):
            self.say(f"Your profile has nothing that fits “{label[:40]}”", "engine", False)
            return False
        if c.get("kind") == "combo":
            act = {"do": "combo", "ref": c["ref"], "wanted": wanted_for(field, label, self.p, self.role) or [value],
                   "type_text": _combo_typing(field, [value])}
        else:
            act = {"do": "fill", "ref": c["ref"], "value": value}
        res = self.act(act)
        if not res.get("ok"):
            self.failed.add(c["ref"])
            return False
        self.filled.append({"kind": field, "label": label, "value": res.get("chosen") or value, "by": "engine"})
        self.unanswered.pop(label, None)
        self.say(f"Typed your {field_name(field)} into “{pretty(label)[:40]}”", "engine")
        if classify(label, c.get("hint", "")) != field:
            self.learn(playbooks.learn_label(label, field, self.url(), self.ats_here()))
        return False

    # --- the end ---------------------------------------------------------------
    def finish(self, state: str, message: str, ok: bool | None) -> dict:
        from . import portal
        for label in list(self.unanswered):
            self._ask_you(label)             # under Answers → Waiting on you
        r = self.result
        r["state"] = state
        r["message"] = message
        r["ok"] = bool(ok) if ok is not None else state in (portal.FILLED, portal.SUBMITTED)
        r["explored"] = True
        r["engine_turns"] = self.engine_turns
        r["pages"] = self.pages + (1 if self.on_form else 0)
        r["filled"] = len(self.filled)
        r["filled_fields"] = [{"label": f.get("label"), "kind": f.get("kind"), "by": f.get("by")}
                              for f in self.filled][:60]
        r["left"] = self.left[:20]
        r["answers"] = self.answers
        items = [{"label": f.get("label"), "kind": f.get("kind"), "value": f.get("value")}
                 for f in self.filled if f.get("kind") != "answer"]
        r["paste_pack"] = portal.paste_pack(self.answers, items)
        try:
            r["form_url"] = self.page.url
        except Exception:
            r["form_url"] = self.form_url
        try:
            # one record per application, under the advert's site: that's
            # where the next application to this company starts
            for s in playbooks.finish(self.advert_url or self.url(), self.ats0 if self.ats0 != "-" else "", {
                    "state": state, "engine_turns": self.engine_turns, "pages": r["pages"],
                    "filled": len(self.filled), "left": self.left,
                    "seconds": int(time.time() - self.start - self.waited)}):
                self.learn(s)
        except Exception:
            pass
        r["learned"] = [x for x in self.learned if x][:12]
        r["steps"] = self.steps[-40:]
        try:
            r["screenshot"] = self.d.shot(self.page, {portal.SUBMITTED: "submitted",
                                                      portal.FILLED: "filled"}.get(state, "handover"))
        except Exception:
            pass
        if state in (portal.FILLED, portal.NEEDS_ANSWER, portal.UNKNOWN_FORM):
            fills = [{"label": f.get("label"), "kind": f.get("kind"), "value": f.get("value")}
                     for f in self.filled if f.get("value")]
            try:
                fields = [{"label": c.get("label")} for c in (self.snap.get("controls") or [])]
                r["companion"] = portal._offer_companion(self.d, self.page,
                                                         portal.companion_hints(fills, self.answers, fields))
            except Exception:
                pass
        # the form is what you need now; the advert it came from is closed,
        # and a tab of a failed attempt is no use to anyone
        if self.page is not self.first_page:
            try:
                self.d.close_page(self.page if state == portal.FAILED else self.first_page)
            except Exception:
                pass
        portal.log({k: v for k, v in r.items() if k not in ("paste_pack", "answers")})
        return r


def _describe_fills(acts: list) -> str:
    """"Filled in first name, last name, email and phone; attached your CV"."""
    typed, extra = [], []
    for a in acts:
        k = str(a.get("kind") or "")
        if a.get("do") == "upload":
            extra.append("attached your CV" if k == "resume" else "attached your covering letter")
        elif k == "saved":
            extra.append(f"used your saved answer to “{pretty(a.get('label'))[:40]}”")
        elif k == "cover_letter":
            typed.append("your covering letter")
        else:
            typed.append(field_name(k) if k else pretty(a.get("label") or "a box")[:30])
    uniq = []
    for n in typed:
        if n not in uniq:
            uniq.append(n)
    parts = []
    if uniq:
        head = uniq[:-1]
        parts.append("Filled in " + (", ".join(head) + " and " + uniq[-1] if head else uniq[0]))
    for x in extra:
        if x not in parts:
            parts.append(x)
    text = "; ".join(parts) or "Filled in the page"
    return text[0].upper() + text[1:]


# --------------------------------------------------------------------------- #
#  the entry point
# --------------------------------------------------------------------------- #
def apply(driver, page, role: dict, profile: dict, result: dict, *, submit: bool = False, brain=None,
          model=None, wait: bool = False, session_key: str = "", turns: int = DEFAULT_TURNS,
          budget_s: float = TIME_BUDGET_S) -> dict:
    """Find the form from the advert open in `page`, fill it, and stop or
    submit. Returns the portal result dict (state, message, steps, learned,
    engine_turns, ...)."""
    from . import portal
    nav = Navigator(driver, page, role, profile, result, submit=submit, brain=brain, model=model,
                    wait=wait, session_key=session_key, turns=turns, budget_s=budget_s)
    try:
        return nav.run()
    except _Workday:
        nav.say("It's a Workday application, so the Workday walker took over")
        result.update(ats="workday", steps=nav.steps, engine_turns=nav.engine_turns)
        out = portal._apply_workday(driver, nav.page, role, profile, result, submit=submit, brain=brain,
                                    model=model, wait=wait, session_key=session_key)
        try:
            for s in playbooks.finish(nav.advert_url or nav.url(), "workday", {
                    "state": out.get("state", ""), "engine_turns": nav.engine_turns,
                    "filled": out.get("filled", 0), "seconds": int(time.time() - nav.start - nav.waited)}):
                nav.learn(s)
        except Exception:
            pass
        out["learned"] = [x for x in nav.learned if x]
        out["explored"] = True
        return out
