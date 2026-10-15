"""A designed CV, as PDF or Word — and in another language — plus a one-page
brief to read before an interview.

"Tailor my CV" wrote a text file: right words, no layout, and a recruiter
opening a .txt is already unimpressed. This lays out the same content:

  * from the role's tailored CV when there is one, or else from your own CV
    (the one you pasted, section by section) — restyled, not rewritten;
  * two looks, both safe for applicant-tracking systems: one column, real
    text, standard headings, no tables, no text in images — the things that
    make a "designed" CV unreadable to the software that reads it first;
  * PDF (drawn by the same Chromium the portal applications use) or Word
    (.docx, editable);
  * translated, if you ask: the engine translates the wording and leaves
    names, employers, tools, numbers and dates alone, and the result is
    checked for exactly that before it's used.

Nothing here adds a fact. The tailored CV was already held to your profile;
your own CV is yours; a translation that drops or changes a number, a tool or
an employer is refused.
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from . import config

TEMPLATES = {"classic": "Classic", "modern": "Modern"}
LANGUAGES = ["English", "Afrikaans", "isiZulu", "isiXhosa", "Sesotho", "Setswana", "French",
             "Portuguese", "German", "Spanish", "Dutch", "Italian", "Arabic", "Swahili"]


def _dir() -> Path:
    d = config.AGENT_HOME / "jobscout" / "resumes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60] or "cv"


def _contact(p: dict) -> list:
    email = p.get("email") or ""
    if not email:
        try:
            from . import outreach
            email = outreach.load_config().get("from_addr", "")
        except Exception:
            email = ""
    bits = [p.get("location"), email, p.get("phone"), p.get("linkedin"), p.get("github"),
            p.get("website")]
    return [str(b).strip() for b in bits if b and str(b).strip()]


def _bullet(line: str) -> str:
    return re.sub(r"^\s*(?:[-•*·▪–]|\d+[.)])\s*", "", line).strip()


def model_for(role: dict | None, profile: dict) -> dict:
    """What goes on the page, as {name, contact, headline, summary, sections}."""
    tcv = (role or {}).get("tailored_cv") or {}
    m = {"name": profile.get("full_name") or "", "contact": _contact(profile),
         "headline": "", "summary": "", "sections": [], "source": ""}
    if tcv.get("experience") or tcv.get("summary"):
        m.update(headline=tcv.get("headline", ""), summary=tcv.get("summary", ""), source="tailored")
        if tcv.get("key_skills"):
            m["sections"].append({"heading": "Key skills",
                                  "items": [{"title": "", "lines": [" · ".join(tcv["key_skills"])]}]})
        exp = [{"title": " — ".join(x for x in (str(j.get("role", "")).strip(),
                                                  str(j.get("employer", "")).strip()) if x),
                "lines": [str(b) for b in (j.get("bullets") or [])], "bullets": True}
               for j in tcv.get("experience") or []]
        if exp:
            m["sections"].append({"heading": "Experience", "items": exp})
        certs = profile.get("certifications") or []
        if certs:
            m["sections"].append({"heading": "Certifications",
                                  "items": [{"title": "", "lines": list(certs), "bullets": True}]})
        return m
    try:
        from . import cvstore
        chunks = json.loads((cvstore._dir() / "chunks.json").read_text("utf-8"))["chunks"]
    except Exception:
        chunks = []
    if chunks:
        m["source"] = "your CV"
        m["headline"] = profile.get("headline", "")
        by = {}
        order = []
        for c in chunks:
            h = c.get("heading") or ""
            if h not in by:
                by[h] = []
                order.append(h)
            by[h].append(c["text"])
        for h in order:
            text = "\n".join(by[h])
            lines = [l.rstrip() for l in text.split("\n") if l.strip()]
            if not h and lines:
                # a CV starts with your name: it's the page's title, not a section
                if not m["name"]:
                    m["name"] = lines[0].strip()
                if lines[0].strip().lower() == (m["name"] or "").strip().lower():
                    lines = lines[1:]
                # the few short lines under the name are a headline and contact
                # details, not a section called "Details"
                if lines and len(lines) <= 4 and all(len(l) < 100 for l in lines) and h == "" \
                        and not any(re.match(r"^\s*(?:[-•*·▪–]|\d+[.)])\s+", l) for l in lines):
                    for l in lines:
                        l = l.strip()
                        contactish = "@" in l or "linkedin" in l.lower() or sum(ch.isdigit() for ch in l) >= 7
                        if not contactish and not m["headline"]:
                            m["headline"] = l
                        elif l not in m["contact"] and l != m["headline"]:
                            m["contact"].append(l)
                    continue
            if h.lower() in ("summary", "profile", "about", "about me", "personal statement",
                             "professional summary") and not m["summary"]:
                m["summary"] = " ".join(lines)
                continue
            items, cur = [], None
            for l in lines:
                is_b = bool(re.match(r"^\s*(?:[-•*·▪–]|\d+[.)])\s+", l))
                if is_b and cur is not None:
                    cur["lines"].append(_bullet(l))
                    cur["bullets"] = True
                else:
                    cur = {"title": l.strip(), "lines": [], "bullets": False}
                    items.append(cur)
            if items and not any(it["bullets"] for it in items):
                # no bullets anywhere (a skills list, an education line): plain
                # text, not a column of bold "titles"
                items = [{"title": "", "lines": [it["title"] for it in items], "bullets": False}]
            if items:
                m["sections"].append({"heading": h or "Details", "items": items})
        return m
    # only the profile: thin, but honest
    m["source"] = "your profile"
    m.update(headline=profile.get("headline", ""), summary=profile.get("summary", ""))
    skills = list(profile.get("skills") or []) + list(profile.get("technologies") or [])
    if skills:
        m["sections"].append({"heading": "Skills", "items": [{"title": "", "lines": [" · ".join(skills)]}]})
    if profile.get("employers"):
        m["sections"].append({"heading": "Experience",
                              "items": [{"title": e, "lines": []} for e in profile["employers"]]})
    if profile.get("achievements"):
        m["sections"].append({"heading": "Achievements",
                              "items": [{"title": "", "lines": list(profile["achievements"]), "bullets": True}]})
    if profile.get("certifications"):
        m["sections"].append({"heading": "Certifications",
                              "items": [{"title": "", "lines": list(profile["certifications"]), "bullets": True}]})
    return m


_CSS = {
    "classic": """
body{font:10.5pt/1.42 "Calibri","Segoe UI",Arial,sans-serif;color:#111;margin:0}
.page{padding:16mm 17mm}
h1{font-size:21pt;margin:0;letter-spacing:.01em}
.headline{font-size:11.5pt;color:#333;margin:2px 0 0}
.contact{font-size:9.5pt;color:#444;margin:6px 0 12px}
h2{font-size:10.5pt;text-transform:uppercase;letter-spacing:.09em;border-bottom:1px solid #999;
   padding-bottom:2px;margin:14px 0 6px}
.item{margin:0 0 7px;break-inside:avoid}
.item b{font-weight:700}
ul{margin:3px 0 0 16px;padding:0} li{margin:1px 0}
p{margin:2px 0}
""",
    "modern": """
body{font:10.5pt/1.45 "Segoe UI","Helvetica Neue",Arial,sans-serif;color:#1d2326;margin:0}
.page{padding:15mm 17mm}
h1{font-size:23pt;margin:0;color:#0f5132;letter-spacing:-.01em}
.headline{font-size:12pt;color:#2f3b40;margin:3px 0 0;font-weight:600}
.contact{font-size:9.5pt;color:#4a565c;margin:6px 0 10px;padding-bottom:8px;border-bottom:3px solid #3ecf8e}
h2{font-size:10pt;text-transform:uppercase;letter-spacing:.12em;color:#0f5132;margin:15px 0 6px}
.item{margin:0 0 8px;break-inside:avoid}
.item b{font-weight:650}
ul{margin:3px 0 0 16px;padding:0} li{margin:1.5px 0}
p{margin:2px 0}
""",
}


def to_html(m: dict, template: str = "classic", lang: str | None = None) -> str:
    e = html.escape
    lang = lang or m.get("lang") or "en"
    out = [f'<!doctype html><html lang="{e(lang)}"><head><meta charset="utf-8">'
           f'<title>{e(m.get("name") or "CV")}</title><style>@page{{size:A4;margin:0}}'
           f'{_CSS.get(template, _CSS["classic"])}</style></head><body><div class="page">']
    if m.get("name"):
        out.append(f"<h1>{e(m['name'])}</h1>")
    if m.get("headline"):
        out.append(f'<p class="headline">{e(m["headline"])}</p>')
    if m.get("contact"):
        out.append(f'<p class="contact">{" · ".join(e(c) for c in m["contact"])}</p>')
    labels = m.get("labels") or {}
    if m.get("summary"):
        out.append(f"<h2>{e(labels.get('Summary', 'Summary'))}</h2><p>{e(m['summary'])}</p>")
    for s in m.get("sections") or []:
        out.append(f"<h2>{e(s['heading'])}</h2>")
        for it in s.get("items") or []:
            out.append('<div class="item">')
            if it.get("title"):
                out.append(f"<b>{e(it['title'])}</b>")
            lines = it.get("lines") or []
            if lines and it.get("bullets"):
                out.append("<ul>" + "".join(f"<li>{e(l)}</li>" for l in lines) + "</ul>")
            else:
                out += [f"<p>{e(l)}</p>" for l in lines]
            out.append("</div>")
    out.append("</div></body></html>")
    return "".join(out)


def to_pdf(page_html: str, path: Path) -> Path:
    """Render with the Chromium the portal applications already use."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            pg = b.new_page()
            pg.set_content(page_html, wait_until="load")
            pg.pdf(path=str(path), format="A4", print_background=True,
                   margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        finally:
            b.close()
    return path


def to_docx(m: dict, path: Path, template: str = "classic") -> Path:
    import docx
    from docx.shared import Pt, RGBColor, Mm
    d = docx.Document()
    for s in d.sections:
        s.top_margin = s.bottom_margin = Mm(16)
        s.left_margin = s.right_margin = Mm(17)
    st = d.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    accent = RGBColor(0x0F, 0x51, 0x32) if template == "modern" else RGBColor(0x11, 0x11, 0x11)

    def para(text, size=None, bold=False, color=None, space=2):
        p = d.add_paragraph()
        r = p.add_run(text)
        r.bold = bold
        if size:
            r.font.size = Pt(size)
        if color is not None:
            r.font.color.rgb = color
        p.paragraph_format.space_after = Pt(space)
        return p
    if m.get("name"):
        para(m["name"], 20, True, accent, 0)
    if m.get("headline"):
        para(m["headline"], 11.5, template == "modern", None, 1)
    if m.get("contact"):
        para(" · ".join(m["contact"]), 9.5, False, RGBColor(0x44, 0x44, 0x44), 8)
    labels = m.get("labels") or {}

    def heading(t):
        para(t.upper(), 10.5, True, accent, 3).paragraph_format.space_before = Pt(10)
    if m.get("summary"):
        heading(labels.get("Summary", "Summary"))
        para(m["summary"])
    for s in m.get("sections") or []:
        heading(s["heading"])
        for it in s.get("items") or []:
            if it.get("title"):
                para(it["title"], bold=True, space=1)
            for l in it.get("lines") or []:
                if it.get("bullets"):
                    p = d.add_paragraph(l, style="List Bullet")
                    p.paragraph_format.space_after = Pt(1)
                else:
                    para(l, space=1)
    d.save(str(path))
    return path


def make(role: dict | None, profile: dict, *, template: str = "classic", fmt: str = "pdf",
         model: dict | None = None) -> dict:
    """Build the file. Returns {ok, path, filename, source}."""
    if template not in TEMPLATES:
        template = "classic"
    m = model or model_for(role, profile)
    if not (m.get("sections") or m.get("summary")):
        return {"ok": False, "error": "There's nothing to put on it yet — paste your CV under "
                                      "Your profile, or tailor one for a role."}
    who = _slug(m.get("name") or profile.get("full_name") or "cv")
    for_ = f"-{_slug((role or {}).get('company', ''))}" if role else ""
    lang = f"-{_slug(m.get('language', ''))}" if m.get("language") and m.get("language") != "English" else ""
    name = f"{who}-cv{for_}{lang}.{ 'docx' if fmt == 'docx' else 'pdf'}"
    path = _dir() / name
    try:
        if fmt == "docx":
            to_docx(m, path, template)
        else:
            to_pdf(to_html(m, template, m.get("lang", "en")), path)
    except Exception as exc:
        return {"ok": False, "error": f"Couldn't make the file: {type(exc).__name__}: {exc}"}
    return {"ok": True, "path": str(path), "filename": name, "source": m.get("source", "")}


# --- translation ------------------------------------------------------------ #
_TRANSLATE_SYSTEM = (
    "Translate this CV (JSON) into {lang}. Translate the wording only: headings, "
    "summary, bullet text and job titles. Keep EXACTLY as written: people's names, "
    "company and employer names, product and tool names (e.g. SQL, Power BI, Kafka), "
    "qualifications' official names, email addresses, URLs, phone numbers, every number, "
    "date and percentage. Do not add, drop or soften anything. Return ONLY the same JSON "
    "structure with the strings translated, plus \"lang\": the BCP-47 code, and "
    "\"labels\": {{\"Summary\": the word for Summary}}.")

_KEEP = re.compile(r"\b(?:\d[\d.,%/-]*|[A-Z][A-Za-z0-9+#.]*[A-Z0-9+#][A-Za-z0-9+#.]*|"
                   r"[A-Z]{2,}|https?://\S+|\S+@\S+)\b")


def _must_keep(m: dict, extra=()) -> set:
    blob = " ".join([m.get("name", ""), *m.get("contact", [])] +
                    [it.get("title", "") + " " + " ".join(it.get("lines") or [])
                     for s in m.get("sections") or [] for it in s.get("items") or []] +
                    [m.get("summary", ""), m.get("headline", "")])
    # numbers, ALL-CAPS and inner-capital words (SQL, PowerBI, iOS) — the
    # things a translation must never touch
    keep = {t for t in _KEEP.findall(blob) if len(t) >= 2}
    # and your employers, tools and qualifications, wherever the CV names them
    keep |= {t for t in extra if t and len(t) >= 2 and t in blob}
    return keep


def check_translation(orig: dict, new: dict, extra=()) -> list:
    """What the translation dropped or changed that it must keep."""
    want = _must_keep(orig, extra)
    have = json.dumps(new, ensure_ascii=False)
    return sorted(t for t in want if t not in have)


def keep_terms(profile: dict) -> list:
    return [str(x) for k in ("employers", "technologies", "certifications")
            for x in (profile.get(k) or [])]


def translate(m: dict, language: str, brain, model=None, keep=()) -> dict:
    if not language or language == "English":
        return {"ok": True, "model": m}
    from . import cv as cvmod
    payload = json.dumps({k: m.get(k) for k in ("name", "headline", "summary", "sections")},
                         ensure_ascii=False)[:20000]
    try:
        kw = {"model": model} if model else {}
        resp = brain.chat([{"role": "user", "content": payload}],
                          [_TRANSLATE_SYSTEM.format(lang=language)], None, **kw)
        raw = "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        data = cvmod._json_from(raw)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    new = {**m, "headline": str(data.get("headline", "")), "summary": str(data.get("summary", "")),
           "sections": data.get("sections") if isinstance(data.get("sections"), list) else [],
           "name": m.get("name", ""), "contact": m.get("contact", []),
           "lang": str(data.get("lang", ""))[:12] or "und", "language": language,
           "labels": data.get("labels") if isinstance(data.get("labels"), dict) else {}}
    lost = check_translation(m, new, keep)
    if lost:
        return {"ok": False, "error": "The translation changed or dropped things it must keep: "
                                      + ", ".join(lost[:8]) + ". Not used — try again.",
                "lost": lost}
    return {"ok": True, "model": new}


_LETTER_SYSTEM = (
    "Translate this cover letter into {lang}. Same meaning, natural and "
    "professional in {lang}; keep names, companies, tools, numbers, dates, "
    "emails and URLs exactly as written. Add nothing. Return ONLY raw JSON: "
    "{{\"subject\": str, \"body\": str}}.")


def translate_letter(subject: str, body: str, language: str, brain, model=None, keep=()) -> dict:
    from . import cv as cvmod
    try:
        kw = {"model": model} if model else {}
        resp = brain.chat([{"role": "user", "content": json.dumps({"subject": subject, "body": body},
                                                                   ensure_ascii=False)}],
                          [_LETTER_SYSTEM.format(lang=language)], None, **kw)
        raw = "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        data = cvmod._json_from(raw)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    orig = {"name": "", "contact": [], "summary": body, "headline": subject, "sections": []}
    lost = check_translation(orig, data, keep)
    if lost:
        return {"ok": False, "error": "The translation changed or dropped: " + ", ".join(lost[:8]),
                "lost": lost}
    return {"ok": True, "subject": str(data.get("subject", "")), "body": str(data.get("body", "")),
            "language": language}


# --- the page to read before the interview --------------------------------- #
def brief_html(role: dict) -> str:
    """One page: when, who, what they want, your best stories, the gaps, what to ask.
    Built from what the app already has — no engine, nothing new claimed."""
    e = html.escape
    prep = role.get("interview") or {}
    qs = prep.get("questions") or []
    stories = [q for q in qs if (q.get("answer_from_profile") or "").strip()][:4]
    gaps = [q for q in qs if (q.get("gap") or "").strip()][:4]
    mock_fix = []
    try:
        from . import mockinterview
        sessions = mockinterview._load(role["key"]).get("sessions") or []
        if sessions:
            mock_fix = sessions[-1].get("work_on") or []
    except Exception:
        pass
    out = ['<!doctype html><html><head><meta charset="utf-8"><title>Interview brief</title><style>'
           '@page{size:A4;margin:0}body{font:10.5pt/1.42 "Segoe UI",Arial,sans-serif;color:#111;margin:0}'
           '.page{padding:14mm 16mm}h1{font-size:17pt;margin:0}h2{font-size:10pt;text-transform:uppercase;'
           'letter-spacing:.1em;color:#0f5132;margin:13px 0 4px;border-bottom:1px solid #ccc}'
           'p{margin:2px 0}ul{margin:2px 0 0 16px;padding:0}li{margin:2px 0}.muted{color:#555}'
           '.q{font-weight:600}</style></head><body><div class="page">']
    out.append(f"<h1>{e(role.get('title', ''))} — {e(role.get('company', ''))}</h1>")
    when = [x for x in (role.get("interview_at"), role.get("interview_link")) if x]
    out.append(f'<p class="muted">{e(" · ".join(when)) if when else "Time not set yet"}</p>')
    if role.get("know"):
        out.append("<h2>Who you know there</h2><ul>" + "".join(
            f"<li>{e(k['name'])} — {e(k.get('kind', ''))}"
            + (f", last heard {e(k['last'])}" if k.get("last") else "") + "</li>"
            for k in role["know"]) + "</ul>")
    if role.get("summary"):
        out.append(f"<h2>What they want</h2><p>{e(str(role['summary'])[:900])}</p>")
    if stories:
        out.append("<h2>Your strongest stories</h2><ul>" + "".join(
            f"<li><span class='q'>{e(q['question'])}</span><br>{e(q['answer_from_profile'])}</li>"
            for q in stories) + "</ul>")
    if gaps:
        out.append("<h2>Think about these first</h2><ul>" + "".join(
            f"<li><span class='q'>{e(q['question'])}</span><br>{e(q['gap'])}</li>" for q in gaps) + "</ul>")
    if mock_fix:
        out.append("<h2>From your last practice</h2><ul>" + "".join(
            f"<li>{e(w['question'])}: {e(w.get('fix') or '')}</li>" for w in mock_fix) + "</ul>")
    if prep.get("ask_them"):
        out.append("<h2>Ask them</h2><ul>" + "".join(f"<li>{e(a)}</li>" for a in prep["ask_them"]) + "</ul>")
    if not (stories or gaps or prep.get("ask_them")):
        out.append("<p class='muted'>Run Interview prep for this role and the brief fills in.</p>")
    out.append(f'<p class="muted" style="margin-top:14px">Agent Jo Jobs · {time.strftime("%Y-%m-%d")}</p>')
    out.append("</div></body></html>")
    return "".join(out)


def brief_pdf(role: dict) -> dict:
    path = _dir() / f"brief-{_slug(role.get('company', ''))}-{_slug(role.get('title', ''))}.pdf"
    try:
        to_pdf(brief_html(role), path)
    except Exception as exc:
        return {"ok": False, "error": f"Couldn't make the brief: {type(exc).__name__}: {exc}"}
    return {"ok": True, "path": str(path), "filename": path.name}
