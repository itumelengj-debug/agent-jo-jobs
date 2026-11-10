"""Is this advert real, and is it what it says? — read from the advert alone.

Two different problems, kept apart because they deserve different answers:

  GHOST  — a real company, but no real vacancy: an advert left up for months,
           reposted to look fresh, a "talent pool" collecting CVs, the same
           title listed five times. Applying costs you a day's cap and gets
           silence. It's a likelihood (0-100), never a certainty, so it is
           only acted on above your bar (auto-apply → skip_ghosts / ghost_bar).
  SCAM   — not a job at all: a fee to start, a cheque to deposit, an
           interview on Telegram, "earn $900 a week from home, no experience".
           Applying hands your details to the person running it. Any one
           strong sign is enough: it is never applied to by itself.

Free and local: no engine call, nothing leaves the machine, and it runs
before scoring, so a run spends nothing on adverts that aren't worth it.
Salary is read out of the advert on the way past, because "no salary
anywhere" is one of the weaker ghost signs and a figure is worth showing.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

# --- scams ----------------------------------------------------------------- #
# Each is a sign on its own. Worded to catch the request, not the topic: an
# advert for a payments engineer mentions fees and banks all day.
_SCAM_STRONG = [
    (r"\b(pay|paying|payment of|deposit)\b[^.]{0,40}\b(registration|training|application|"
     r"starter[- ]kit|onboarding|processing|placement|certification)\s+fee",
     "asks you to pay a fee to start"),
    (r"\b(registration|training|application|starter[- ]kit|onboarding|placement)\s+fee\b[^.]{0,30}"
     r"\b(required|payable|of\s+[$€£R]|refundable)",
     "asks you to pay a fee to start"),
    (r"\b(cheque|check)\b[^.]{0,40}\b(deposit|cash)\b[^.]{0,60}\b(send|transfer|wire|return|buy)\b",
     "the deposit-a-cheque-and-send-money-back pattern"),
    (r"\b(western union|moneygram|gift ?cards?|itunes cards?|steam cards?)\b",
     "wants payment by wire transfer service or gift card"),
    (r"\b(interview|contact|reach|message)\b[^.]{0,40}\b(on|via|through|using)\s+(telegram|whatsapp|"
     r"signal|google ?hangouts|wickr)\b",
     "the interview happens over a messaging app"),
    (r"\b(reship|re-ship|package forwarding|parcel forwarding|receive and forward packages)\b",
     "reshipping parcels (a known fraud)"),
    (r"\b(send|provide|submit)\b[^.]{0,30}\b(bank (account )?details|banking details|"
     r"card (number|details)|social security number|ssn|id number)\b[^.]{0,30}\b(before|to (apply|start|"
     r"secure|reserve)|in advance)",
     "wants bank or ID details before any interview"),
    (r"\bcrypto(currency)?\b[^.]{0,40}\b(wallet|deposit|invest)\b[^.]{0,40}\b(you|your)\b",
     "wants you to deposit or invest crypto"),
]
_SCAM_WEAK = [
    (r"\b(earn|make)\s+(up to\s+)?[$€£R]\s?\d[\d,]*\+?\s*(per|a|/)\s*(day|week)\b",
     "promises a weekly or daily sum"),
    (r"\bno (experience|interview|cv|resume) (needed|necessary|required)\b",
     "no experience or interview needed"),
    (r"\b(work from home|from home|from your phone)\b[^.]{0,40}\b(earn|income|cash)\b",
     "work-from-home income pitch"),
    (r"\b(immediate start|start today|hired (today|immediately)|instant hire)\b",
     "hired on the spot"),
    (r"\b(limited (slots|spots)|act now|don'?t miss (out|this))\b",
     "pressure to act now"),
]
_FREE_MAIL = ("gmail.com", "yahoo.", "hotmail.", "outlook.com", "live.com", "aol.com",
              "proton.me", "protonmail.", "icloud.com", "mail.ru", "gmx.", "yandex.")

# --- ghosts ---------------------------------------------------------------- #
_EVERGREEN = re.compile(
    r"\b(talent (pool|community|network|pipeline)|future (opportunities|openings|roles|vacancies)|"
    r"always (looking|hiring|on the lookout)|general application|open application|"
    r"speculative application|evergreen|not an? (active|current|open) (opening|vacancy|position|role)|"
    r"build(ing)? (a|our) pipeline|for future consideration|keep your (cv|resume|details) on file)\b",
    re.I)

GHOST_BAR = 60          # at or above this, a ghost is "likely"

# --- salary ---------------------------------------------------------------- #
_CUR = r"(?:R|ZAR|US\$|USD|\$|€|EUR|£|GBP|CAD|AUD|A\$|C\$|INR|₹)"
_NUM = r"\d{1,3}(?:[ ,.]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?\s?[kK]|\d{2,7}"
_PER = (r"(?:\s*(?:per|/|a|p\.?)\s*(?:year|yr|annum|a\.?|month|mo|m|hour|hr|h|day|week|wk)\b"
        r"|\s*(?:pa|p\.a\.|pm|p\.m\.|ph|annually|monthly|hourly|daily)\b)?")
_SALARY = re.compile(
    rf"{_CUR}\s?(?:{_NUM})(?:\s?(?:-|–|—|to)\s?{_CUR}?\s?(?:{_NUM}))?{_PER}"
    rf"|(?:{_NUM})\s?(?:-|–|—|to)\s?(?:{_NUM})\s?(?:{_CUR}|ZAR|USD|EUR|GBP){_PER}",
    re.I)


def salary(text: str) -> str:
    """The first pay figure in the advert, as written ("$120k–$140k per year").
    '' when there isn't one. A bare number is never taken for pay."""
    for m in _SALARY.finditer(text or ""):
        s = " ".join(m.group(0).split()).strip(" ,.;")
        digits = re.sub(r"\D", "", s)
        # "$5" and "R1" are not salaries; years ("2026") have no currency
        if len(digits) >= 3 or re.search(r"\d\s?[kK]\b", s):
            return s[:60]
    return ""


def _text(role: dict) -> str:
    return " ".join(str((role or {}).get(k) or "") for k in
                    ("title", "summary", "description", "location"))


def _age_days(role: dict) -> float:
    for k in ("posted_at", "added_at", "found_at"):
        v = str((role or {}).get(k) or "")
        for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d"):
            try:
                when = datetime.strptime(v if "UTC" in fmt else v[:10], fmt)
                when = when.replace(tzinfo=timezone.utc)
                return max(0.0, (datetime.now(timezone.utc) - when).total_seconds() / 86400)
            except Exception:
                continue
    return 0.0


def assess(role: dict, others: list | None = None) -> dict:
    """{verdict: ok|likely_ghost|scam, ghost: 0-100, ghost_why: [..],
    scam_why: [..], salary: str, age_days: float}.

    `others` is every tracked role, for the one sign that needs them: the
    same title at the same company listed several times at once."""
    text = _text(role)
    low = text.lower()
    scam_why, weak = [], []
    for rx, why in _SCAM_STRONG:
        if re.search(rx, low, re.I) and why not in scam_why:
            scam_why.append(why)
    for rx, why in _SCAM_WEAK:
        if re.search(rx, low, re.I) and why not in weak:
            weak.append(why)
    mail = str((role or {}).get("apply_email") or "").lower()
    company = re.sub(r"[^a-z0-9]", "", str((role or {}).get("company") or "").lower())
    if mail and any(d in mail.split("@")[-1] for d in _FREE_MAIL) and len(company) > 3 \
            and company[:5] not in re.sub(r"[^a-z0-9]", "", mail):
        weak.append("a company advert that wants applications at a personal email address")
    # two of the weaker signs together are as telling as one strong one
    if len(weak) >= 2:
        scam_why += weak[:3]

    ghost, ghost_why = 0, []
    age = _age_days(role)
    if age >= 60:
        ghost += 45
        ghost_why.append(f"listed {int(age)} days ago")
    elif age >= 30:
        ghost += 30
        ghost_why.append(f"listed {int(age)} days ago")
    reposts = int((role or {}).get("reposted") or 0)
    if reposts:
        ghost += min(40, 25 * reposts)
        ghost_why.append(f"reposted {reposts} time{'s' if reposts != 1 else ''} while tracked")
    m = _EVERGREEN.search(text)
    if m:
        ghost += 45
        ghost_why.append(f"says “{m.group(0)}” — collecting CVs, not filling a role")
    if others:
        def norm(t):
            return re.sub(r"\b(senior|sr|junior|jr|lead|i{1,3}|[0-9]+)\b|[^a-z ]", " ",
                          str(t or "").lower()).split()
        me = (company, tuple(norm((role or {}).get("title"))))
        same = sum(1 for o in others
                   if (re.sub(r"[^a-z0-9]", "", str(o.get("company") or "").lower()),
                       tuple(norm(o.get("title")))) == me
                   and o.get("stage") not in ("closed",))
        if same >= 3:
            ghost += 20
            ghost_why.append(f"the same role is listed {same} times at once")
    pay = salary(text)
    summary_len = len(str((role or {}).get("summary") or ""))
    if ghost and not pay:
        ghost += 5                       # weak alone; adds to the others
    if 0 < summary_len < 120 and ghost:
        ghost += 10
        ghost_why.append("the advert says almost nothing about the work")
    ghost = min(100, ghost)
    verdict = "scam" if scam_why else ("likely_ghost" if ghost >= GHOST_BAR else "ok")
    return {"verdict": verdict, "ghost": ghost, "ghost_why": ghost_why,
            "scam_why": scam_why, "salary": pay, "age_days": round(age, 1)}


def says(t: dict) -> str:
    """One line for a run report or a held reason."""
    if not t:
        return ""
    if t.get("verdict") == "scam":
        return "looks like a scam — " + "; ".join(t.get("scam_why") or [])[:200]
    if t.get("verdict") == "likely_ghost":
        return (f"likely a ghost job ({t.get('ghost')}/100) — "
                + "; ".join(t.get("ghost_why") or [])[:200])
    return ""
