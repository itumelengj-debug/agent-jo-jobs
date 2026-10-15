"""When the interview is, and a calendar entry for it.

An invitation that arrived by email moved the role to "interview" — and then
the time was still only in the email. This reads the proposed time and the
meeting link out of the invitation (locally, no engine: the formats people
actually write — "Tuesday 14 October at 10:00", "14/10/2026 at 10h00",
"2026-10-14 14:30", "Oct 14, 2pm") and makes an .ics file any calendar opens,
with your prep in the notes.

It only takes a time it's sure of. An email that offers "Tuesday or
Wednesday" or no time at all gives none, and you can set it by hand. Times
are read as your local time (the app's machine) — the invitation's own time
zone, when it names one other than SAST, is noted rather than converted.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_TIME = r"(\d{1,2})(?:[:h.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"
_AT = r"(?:,?\s*(?:at|@|from|,)?\s*)"
_PATTERNS = [
    # 14 October 2026 at 10:00 / Tuesday, 14 Oct at 10h00
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r"(?:\s+(\d{4}))?" + _AT + _TIME, re.I),
    # October 14(, 2026) at 2pm
    re.compile(r"\b" + _MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?" + _AT + _TIME, re.I),
    # 2026-10-14 14:30
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:T|\s+(?:at\s+)?)" + _TIME, re.I),
    # 14/10/2026 at 10h00 (day first, as written in South Africa)
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})" + _AT + _TIME, re.I),
]
_LINK = re.compile(r"https://(?:[\w-]+\.)?(?:teams\.microsoft\.com|teams\.live\.com|zoom\.us|"
                   r"meet\.google\.com|[\w-]+\.webex\.com|whereby\.com|calendly\.com)[^\s<>\"')\]]*", re.I)
_OTHER_TZ = re.compile(r"\b(GMT|BST|CET|CEST|EST|EDT|PST|PDT|IST|UTC[+-]\d+)\b")


def _hm(h, m, ap):
    h, m = int(h), int(m or 0)
    ap = (ap or "").lower().replace(".", "")
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if not ap and not m and h < 7:       # "at 2" in office hours means 14:00
        h += 12
    if h > 23 or m > 59:
        raise ValueError
    return h, m


def _year_for(month: int, day: int, now: datetime) -> int:
    y = now.year
    # a date already well past this year means next year's
    if datetime(y, month, day) < now - timedelta(days=30):
        y += 1
    return y


def find_time(text: str, now: datetime | None = None) -> dict:
    """{'at': 'YYYY-MM-DD HH:MM', 'said': the words it came from, 'tz_note'}
    or {} when the email doesn't give exactly one time."""
    now = now or datetime.now()
    text = re.sub(r"\s+", " ", text or "")
    found = {}
    for i, rx in enumerate(_PATTERNS):
        for m in rx.finditer(text):
            g = m.groups()
            try:
                if i == 0:
                    d, mon, y = int(g[0]), _MONTHS[g[1][:3].lower()], g[2]
                    h, mi = _hm(g[3], g[4], g[5])
                elif i == 1:
                    mon, d, y = _MONTHS[g[0][:3].lower()], int(g[1]), g[2]
                    h, mi = _hm(g[3], g[4], g[5])
                elif i == 2:
                    y, mon, d = g[0], int(g[1]), int(g[2])
                    h, mi = _hm(g[3], g[4], g[5])
                else:
                    d, mon, y = int(g[0]), int(g[1]), g[2]
                    h, mi = _hm(g[3], g[4], g[5])
                y = int(y) if y else _year_for(mon, d, now)
                when = datetime(y, mon, d, h, mi)
            except (ValueError, KeyError):
                continue
            if when < now - timedelta(days=1):
                continue
            found.setdefault(when.strftime("%Y-%m-%d %H:%M"), m.group(0).strip())
    if len(found) != 1:
        return {}
    at, said = next(iter(found.items()))
    tz = _OTHER_TZ.search(text)
    return {"at": at, "said": said,
            "tz_note": f"The email mentions {tz.group(1)} — check the time is yours." if tz else ""}


def find_link(text: str) -> str:
    m = _LINK.search(text or "")
    return m.group(0).rstrip(".,;") if m else ""


def _esc(s: str) -> str:
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r", "").replace("\n", "\\n"))


def _fold(line: str) -> str:
    out = []
    while len(line.encode("utf-8")) > 74:
        cut = 74
        while len(line[:cut].encode("utf-8")) > 74:
            cut -= 1
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return "\r\n".join(out)


def ics(role: dict, minutes: int = 60) -> str:
    """An .ics calendar entry for the role's interview. Floating local time,
    so it lands at the time written in the email whatever the calendar's zone."""
    at = datetime.strptime(role["interview_at"], "%Y-%m-%d %H:%M")
    end = at + timedelta(minutes=minutes)
    title = f"Interview — {role.get('title', '')} @ {role.get('company', '')}".strip(" @—")
    notes = []
    if role.get("interview_link"):
        notes.append("Join: " + role["interview_link"])
    if role.get("url"):
        notes.append("Advert: " + role["url"])
    prep = role.get("interview") or {}
    qs = prep.get("questions") or []
    if qs:
        notes.append("")
        notes.append("Likely questions:")
        for q in qs[:8]:
            notes.append("- " + q.get("question", ""))
            if (q.get("gap") or "").strip():
                notes.append("  Gap: " + q["gap"])
    if prep.get("ask_them"):
        notes.append("")
        notes.append("Ask them:")
        notes += ["- " + a for a in prep["ask_them"][:5]]
    uid = f"{role.get('key', 'role')}-{at:%Y%m%dT%H%M}@agent-jo-jobs"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Symbolic Synapse//Agent Jo Jobs//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "BEGIN:VEVENT",
             f"UID:{uid}", f"DTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}",
             f"DTSTART:{at:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}",
             "SUMMARY:" + _esc(title), "DESCRIPTION:" + _esc("\n".join(notes))]
    if role.get("interview_link"):
        lines.append("LOCATION:" + _esc(role["interview_link"]))
    lines += ["BEGIN:VALARM", "TRIGGER:-PT1H", "ACTION:DISPLAY",
              "DESCRIPTION:" + _esc(title), "END:VALARM", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def upcoming(roles: list, now: datetime | None = None) -> list:
    """Interviews from now on, soonest first."""
    now = now or datetime.now()
    out = []
    for r in roles:
        try:
            at = datetime.strptime(r.get("interview_at") or "", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if at >= now - timedelta(hours=2) and r.get("stage") in ("interview", "responded", "offer"):
            out.append({"key": r["key"], "title": r.get("title", ""), "company": r.get("company", ""),
                        "at": r["interview_at"], "link": r.get("interview_link", "")})
    return sorted(out, key=lambda x: x["at"])
