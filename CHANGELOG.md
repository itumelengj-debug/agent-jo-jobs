# Agent Jo Jobs — build log

Entries before this one are in Agent Jo's CHANGELOG (up to its entry 154),
from when the job search lived inside Agent Jo.


### 1. Its own app

Asked for: separate Agent Jo Jobs from Agent Jo completely — no shared code.

It was already a separate window, but it shared Agent Jo's data folder and
its code was copied across from Agent Jo with a sync tool and a manifest of
hashes. Now nothing is shared:

- **Its own data folder**, `~/.agent_jo_jobs` (or `AGENT_JOBS_HOME`). On the
  first start, `agent/migrate.py` copies the job search's data across from
  Agent Jo's folder: `jobscout/` (roles, profile and CVs, settings, sources,
  alerts), `portal/` (the browser profile with your job-site logins, without
  its caches), `engines.json` with the `secret.key` that unseals its keys,
  `settings.json`, and the daily run from Agent Jo's database. It copies and
  never deletes, runs once, and leaves a note of what it copied.
- **Its own code.** The modules in `agent/` are this app's now; `VENDORED.json`
  and the hash checks are gone. Change them here.
- **Its own checks.** The job logic was tested from inside Agent Jo's suite;
  those checks moved here, to `tests/test_logic.py` (drafting and the
  fabrication guard, sources, portals and the browser, auto-apply, the
  window), and `tests/run_tests.py` runs them. Three checks of Agent Jo's
  dashboard stayed behind, with the dashboard. One check that had gone stale
  — the run summary was rebuilt in one place in Agent Jo's build 149 — was
  brought up to date on the way.
- **Its own build stamp**, in `agent/config.py`.


### 2. A Windows installer

Asked for: an .exe installation.

`installer\AgentJoJobs.iss` (Inno Setup) builds `AgentJoJobs-Setup-<version>.exe`:
it installs into your own folder with no administrator prompt, finds Python in
the registry or downloads the official installer and installs it for you
alone, then runs the new `setup_jobs.py` with that exact Python — the
environment, the packages, a check that the app loads, and the browser for
portal applications (a browser that won't download is a warning, not a
failure). Shortcuts and an uninstaller come with it; an upgrade keeps the
Python environment; `~/.agent_jo_jobs` is never touched.

Build it with `Build Windows Installer.bat`, or the GitHub workflow. Checks
cover what it names, what it runs, and what `setup_jobs.py` would do
(`--dry-run`). Not built or run here (that needs Windows), and not
code-signed, so Windows warns the first time.


### 3. The memory store, safe under load

The store behind schedules, the daily run and the audit trail shared one
SQLite connection between every thread — the server's workers, the scheduler,
background runs — and nothing serialised it: under load, writes were lost and
"bad parameter or other API misuse" errors surfaced (about 300 in 6,000 writes
with eight threads). Each thread now gets its own connection, as in Agent Jo
(its CHANGELOG, 157). A check in `tests/test_logic.py` runs that load and
fails against the old store every time.


### 4. Your full CV, and never typing an answer twice

Asked for: paste a full CV and search it (RAG); keep everything I type into
an application so I don't retype it; more autonomy.

**Your full CV** (`agent/cvstore.py`). Paste it once under *Your profile*. It
is split into sections under their headings and indexed (BM25: nothing to
install, nothing sent anywhere), and then:

- drafting a letter retrieves the CV sections that fit the advert, and
  answering a form question retrieves the ones that answer it — the engine
  sees `CV_EXCERPTS` beside the profile, so it can cite real work;
- the profile's empty fields are filled from the CV by the engine — lists
  added to, nothing you wrote overwritten;
- the claims check counts the CV as yours: a tool or employer named there
  isn't held as invented, and one named nowhere still is.

**Your answers** (`agent/answerbank.py`). The helper in the form sends back
what you type when you leave a field, and it's saved with its question. The
next form that asks it — "Notice period (required)" finds "What is your
notice period?" — is filled with it. Order everywhere: profile fields, then
saved answers, then the engine from your CV. A near match must agree on the
kind of field, so a notice period never fills a salary box.

- Never kept: passwords, codes, card and account numbers, file pickers, and
  anything that just repeats your profile.
- Sensitive questions (gender, race, disability, ID number…) are kept but
  not reused until you switch them on, one by one.
- A new *Answers* view lists them all: search, edit, delete, add your own.

**More autonomous** as a result: a form question you've answered once, or
that your CV answers, no longer stops an application for you — auto-apply's
prepared and submitted forms complete far more often.

Checks: 19 in `tests/test_logic.py` (search, the claims corpus, profile
filling, matching and its limits, secrets, sensitive reuse, form filling,
bank-before-engine) and `tools/check_answers.py`, which types into a real
form in Chromium and checks the next form is filled (5 of 5).


### 5. Upload the CV, and answer each question once

Asked for: further improvements.

**Upload your CV** as a PDF or Word file, beside the paste box. Word tables
are read too (CV templates are full of them). A scanned PDF has no text to
read, and says so — export it as a PDF from Word, or paste — rather than
saving an empty CV; an old `.doc` asks to be saved as `.docx`.

**Waiting on you.** A form question that nothing answered — not the
profile, a saved answer, or the engine from the CV — used to stop that
application and be asked again by the next form. Each one is now noted once,
with the applications it's holding up, under *Answers → Waiting on you*, and
counted on the nav. Answer it there once: it's saved and switched on for
reuse, and every form that asks it, in any close wording, is filled.
Passwords and codes are never asked for.

**Two checks that passed by luck.** `tools/check_layout.py` read the drafts
pane after a `time.sleep()`, during which Playwright serves nothing — not
even the stubbed replies — so it failed about half the time, in this build
and the one before. It waits for the pane's content now (6 of 6 runs), and
`tools/check_answers.py` waits the same way.

Checks: 9 more in `tests/test_logic.py` (a real Word file with a table, a
real PDF, a scan, an old .doc; a question noted once across reworded forms,
with both roles; secrets never asked; answering clears it and fills the next
form; a sensitive answer given there is reused), and the upload was sent
through the window in Chromium and arrived byte for byte.


### 6. How much it does without you, and what it did

Asked for: further improvements.

**One autonomy setting**, at the top of Auto-apply, in place of reading three
switches together to work out what would happen:

- **Draft only** — finds, scores and drafts; sends nothing, opens nothing.
  The drafts wait for you, each held with "drafted for you to review".
  (There was no way to say this before: rehearsal still "sent" to the log
  and opened company forms.)
- **Prepare** — also fills in company forms for you to finish; emails are
  rehearsed, never sent.
- **Send email** — emailed applications that clear every check go out;
  forms are filled for you to finish.
- **Full** — emails go out and company forms are submitted.

Each level is just the switches it stands for, so the rules below still
show the truth; set them by hand and it reads "Custom". Changing what's
delivered by hand lifts Draft only, so it can't go quietly on sending
nothing. Every level keeps the gates: minimum fit, no invented claims, the
daily cap.

**Run reports.** Every run — the scheduled 07:00 one included — leaves a
report: what was sent (and whether it was a rehearsal), which forms were
filled for you and what each still needs, what was held and why, errors
grouped by cause, and how many questions are waiting on you. The last 90 are
kept, under Auto-apply → Run reports. A full cycle is one report, not two.

Checks: 11 more — each level does exactly what it says (draft only touches
nothing; full submits), hand-set switches read as custom, an unknown level
is refused, a run and a cycle each leave one report, old reports are let go.


### 7. Replies, read from your inbox

Asked for: further improvements.

Results counted replies, interviews and offers from each role's stage — but
a stage only moved when you moved it, so mostly it didn't, and every source
and every draft looked equally unanswered. `agent/inbox.py` reads the
replies:

- **From your mailbox over IMAP**, with the login already set up for
  sending; the server is worked out from it (smtp.gmail.com → imap.gmail.com,
  Office 365 → outlook.office365.com) and can be set by hand. Or from `.eml`
  files saved in `jobscout/replies`, for anyone who'd rather not connect it.
- **Read-only.** The folder is selected read-only and messages are fetched
  with PEEK: nothing is marked read, moved, deleted or sent.
- **Matched to the application it answers** — the address you applied to,
  the company's domain or name (hiring systems like Greenhouse and Workday
  send on a company's behalf), the role's title, "Re:" your subject. A weak
  match, or two of your companies tied, counts as no match. The quoted
  application under a reply is ignored, so "unfortunately" in your own words
  can't read as a turn-down.
- **Sorted**: interview, offer, turn-down, reply, or just "we've received
  your application" — noted on the role, but not counted as a response.
- **Stages move forward only**; a turn-down closes the role (after an
  interview too) with the reason; each message is handled once.

Each full cycle reads replies first, so the 07:00 run picks up overnight
answers, and its report says how many. Results has the switch, a "check
now" button and the latest replies.

Checks: 12 more, with real emails — an interview reply with a quoted
"unfortunately" under it, a Greenhouse turn-down, a Workday acknowledgement,
a newsletter, a tie; forward-only; once only; and a stand-in mailbox that
records every call, to show it is only ever opened read-only and fetched
with PEEK, and that a refused login says what to do.


### 8. A weekly digest

Asked for: further improvements.

The app now finds, drafts, applies and reads replies on its own — which
makes it easy to stop looking. `agent/digest.py` sends one email a week, to
you, on the day you choose (Results → Weekly digest):

- the week in numbers — applications sent (rehearsals don't count), replies,
  interviews, offers;
- who answered, and how; what went out;
- what's waiting on you — questions only you can answer (and how many
  applications each is holding up), forms filled for you to finish, drafts
  held for a claim;
- what the results so far support, as Results states it, including "too few
  to conclude anything" when that's the truth.

It goes out with the morning run on that weekday, at most once in six days,
through the email login already set up — to your own address, never as an
unattended send to anyone else. A week with nothing to say sends nothing, and
isn't retried until the next week. Preview and Send now are beside the
switch, and each run's report notes when it went.

Checks: 13 — content, rehearsals not counted, your address only, off until
switched on, its day only, never twice in a week, silence when there's
nothing to say.


### 9. Updates in one click, and only ones you signed

Asked for: further improvements.

An updater is the most dangerous thing an agent that runs commands can
have: whoever can push it an "update" can run code on your machine. So
`agent/updater.py` installs nothing it can't prove you signed:

- **Check** reads `latest.json` from the address you set (Engines → Updates) and offers
  a newer build; nothing downloads until you say so.
- **Verify**: the zip must match latest.json's SHA-256, and its signature
  must verify against the public key **already in this copy** — never the
  one in the download, which an attacker would simply swap. Every file must
  match the signed manifest. Refused, with the reason: another key, a file
  changed after signing, a checksum mismatch, an older build, a release
  carrying a different key, a path outside the app folder or into its
  Python environment. A copy with no key refuses every update and says how
  to fix that; so does a packaged .exe, which can't patch itself.
- **Install** copies the files in, keeping every one it replaces, so **Roll
  back** puts the previous version back byte for byte. New packages are
  installed if requirements changed. Your data is never touched. Restart
  after.

**A release tool of its own.** The app was released from inside Agent Jo
before the split and had none. `tools/make_release.py` builds a zip of the
app, signs exactly what's in it (`--make-key` once), scans it for keys, and
writes `dist/latest.json`. Its scanner first flagged the tool itself — the
private-key marker was written plainly in its own source — so no release
could be built; the pattern no longer matches itself.

Tested end to end with the real tools on two copies of the app: a signed
release built, the older copy updated to match it, rolled back to all 65
files byte-identical, and an unsigned release refused.

Checks: 16 that attack it with real Ed25519 keys and real zips — someone
else's signature, a tampered file, a bad checksum, a key swap, a zip slip, a
write into `.venv`, an older build — each refused with nothing on disk
changed; a genuine update installs and rolls back exactly; and the release
tool's signatures pass the updater's check.

**Also:** `EngineEditBody` was defined twice in `jobs/server.py` (identical,
so harmless — but a copy that drifts is exactly how a route ends up with
the wrong model). The second is gone, and a check fails on any route whose
body model is defined below it, or any model defined twice.

### 10. Your CV reaches the CV tailoring and the interview prep

The CV you paste was read by the cover letters and the auto-apply drafts, but
"Tailor my CV" and "Interview prep" still only saw the short profile — so the
tailored CV left out work that was right there in your CV, and the fabrication
guard held claims your CV supports. Both now get the sections of your CV that
answer the advert (the same BM25 search), and the guard counts your CV as
yours.

**An interview invitation gets prepared for.** When a reply moves a role to
"interview" (or you do), the next cycle writes the prep: likely questions,
the answer your CV gives each one, and — where your CV has nothing — a gap to
think about rather than an invented answer, plus questions to ask them. Two
roles per run at most. It shows on the role, and the run report says so.

Fixed: the Interview prep button showed "[object Object]" for every question.

### 11. When the interview is, and a calendar entry for it

An invitation moved the role to "interview" — and the time stayed in the
email. The inbox reader now takes the proposed time and the meeting link
(Teams, Zoom, Meet, Webex, Whereby, Calendly) out of the invitation, locally,
in the ways people write it: "14 October at 10:00", "14/10/2026 at 10h00",
"October 14 at 2pm", "2026-10-14 14:30". It only takes a time it's sure of —
"14 or 15 October?" gives none — and notes when the email names a time zone
other than yours instead of guessing a conversion.

The role shows the time and the words it came from, **Add to calendar**
downloads an .ics entry (alarm an hour before; your prep questions and gaps
in the notes) and **Set the time** fixes it by hand — a time you set isn't
overwritten by a later email. The overview has an "Interviews coming up"
card, and the weekly digest an INTERVIEWS COMING UP section.

### 12. Practise the interview, and get told what to fix

Interview prep was a list to read. **Practise the interview** (on any role;
the suggested step once you're at interview) runs it: one question at a time,
starting with "tell me about yourself", answered by typing or dictating, with
the question read aloud if you like. After each answer: a 1–5 score, what
worked, the one thing to change, and a stronger version built only from your
CV — itself checked, so it can't put words in your mouth. Local checks run on
every answer with or without an engine: a concrete example, a result or a
number, a sensible length, "we" where it should be "I", and any tool,
employer or number your CV can't back — the claim an interviewer checks. The
summary gives the average, the answers to work on, and the change since your
last attempt for that role. Dictation uses the browser's speech service (in
Chrome and Edge that's Google's or Microsoft's, and the button says so); the
app keeps no audio. `python tools/check_mock.py` runs it in a real browser.

### 13. Edit a draft, and it learns how you write

There was no way to edit a draft in the app. Now there is (Edit on the
role's draft, or **Edit it myself** on a held one): your version becomes the
draft, is checked again by the fabrication guard, and is kept with what the
engine wrote. From two or more edits agreeing, rules are worked out locally:
the kind of sentence you keep cutting, the length you keep, your opening and
sign-off. New drafts and follow-ups follow them (a follow-up skips the
length rule). They're listed under Your profile → How you write, with
Forget on each. Phrases you *add* never become rules — what you add is
usually a fact for that role, and a rule must not carry it into the next
letter. Editing the same letter again counts once.

### 14. The phone companion

The autonomous runs stalled on decisions only you can make, while you were
away from the desk. Engines → **Phone companion** shows a QR code; scan it
and your phone has exactly those decisions: answer the questions forms are
waiting on, approve or skip drafts (reading the letter first), see your
interviews and the last run, and **Pause** — the level drops to draft-only.
It can't browse roles, read your CV or profile, change settings or send
anything itself.

An approval from the phone counts as your call on the fit threshold, and
nothing else: a draft that claims something your profile can't back can't be
approved there, editing a draft undoes its approval, and the phone says
plainly whether the approved draft will go out on the next run at your
current level or still waits for you.

How it's kept to you: off until turned on; its own small listener on port
8767 (the main app still answers only to this computer); a 192-bit key in the
link's #fragment, which browsers never send over the network, taken out of
the address bar on first load and sent in a header, compared in constant
time; ten wrong keys locks that address out for ten minutes; no cookies, no
CORS, strict CSP, no framing; JSON only; every action audited as "phone";
**New key** shuts out the old link at once. On home Wi-Fi it isn't
encrypted, and the window says so — a Tailscale address, listed when
Tailscale runs, is. The QR code is drawn by a small encoder in the app
(agent/qr.py), checked against OpenCV's decoder, so nothing is fetched to
make it. `python tools/check_phone.py` uses it in a real browser at phone
size.

### 15. People: who you know, and when a role is at their company

Every reply to an application had a person behind it, and the app forgot
them when the role closed. **People** (new in the rail) gathers them from
the replies the inbox reader matched — name, address, company, which roles,
what kind of answer, when — and you can add anyone by hand (someone you met,
a referral). No-reply addresses and the hiring systems' own mail aren't
people; a shared inbox (jobs@, careers@) is kept but marked; someone linked
to roles at two or more companies is labelled a recruiter.

When a role is found at a company where you know someone, the role says so —
"You know someone here: Thandi Mokoena" — with **Draft a note to them**: a
short note reminding them how you know each other (from the history only),
naming the role and asking if they'd pass it on, checked by the fabrication
guard like every draft. It's never sent from here: **Open in my mail app**
fills in your own mail app and you press send. People who answered with
something real and then went quiet for three weeks are listed under "Worth
getting back to" (and in the weekly digest), until you mark them done.

**Fixed:** two replies to the same application read in one inbox check — a
recruiter's and the no-reply confirmation, say — wrote back over each other,
and the first was lost. Each message now updates the role as it stands.

### 16. A designed CV, in other languages, from LinkedIn — and a brief for the call

Measured against AIApply, the gaps were presentation and reach, not the
engine. Closed here:

**Your CV, designed** (Your profile, and "Designed CV" on any role): your CV
laid out as a PDF or an editable Word file, in two looks — both one column,
real text, standard headings, no tables or images, so the software that
reads CVs before people do can read it. On a role it uses that role's
tailored CV; otherwise your own CV, restyled and not reworded (your name
becomes the title, the lines under it the headline and contact details,
bullets stay bullets). The PDF is drawn by the Chromium the app already has.

**In another language**: the CV, or a draft letter (Translate, on the
draft). The engine translates the wording and must leave names, employers,
tools, qualifications, numbers, dates, emails and links exactly as written —
checked before it's used, so a translation that turns "40" into "45" or an
employer into another is refused with what it changed.

**From LinkedIn**: upload your profile's "Save to PDF" as your CV. It's
recognised, its page footers removed, and the link, name, headline and
location it states fill your profile's empty fields.

**A one-page brief** (on a role at interview): when and where, who you know
there, what they want, your strongest stories, the gaps to think about, what
your last practice said to fix, and what to ask — built from what the app
already has, to read just before the call.

Left out on purpose: auto-applying through LinkedIn Easy Apply or Indeed
(against their terms; accounts get restricted) and a live "interview buddy"
that feeds answers during a real interview.

### 17. Workday applications, page by page

Workday was the one big system the form filler never finished: an
application there is five or six pages behind an Apply button, usually
behind a sign-in, and its drop-downs are buttons that open a list rather
than form controls. It saw a page of buttons and stopped.

A Workday advert (recognised by its address or its page) now goes down a
path of its own (agent/workday.py):

- Apply → "Autofill with Resume" when you have a CV file (your own, or a
  designed one made on the spot), so Workday reads your experience from it;
  otherwise "Apply Manually".
- A sign-in or account page is handed to you, as on any site; the browser
  keeps you signed in for next time.
- On each page every control is read with its label — text boxes, Workday's
  button drop-downs (opened, and the right option clicked: Mobile, your
  country, "Job Board"…), yes/no radio groups, the CV upload — and filled
  from your profile, then answers you've given before, then the engine,
  checked like every answer.
- It never answers the sensitive questions and never ticks a terms or
  consent box: those pages stop for you, with what's left listed (and the
  helper in the page).
- Save and Continue; if Workday shows errors they're read and reported, not
  retried blind.
- It stops at Review. Submitting is yours unless your level submits forms.

`python tools/check_workday.py` walks a local imitation of a Workday
application (tests/fixtures/workday_mock.html — same markers, button
drop-downs, a page per step, required-field errors, Review) in a real
browser, end to end through the app's own portal path: 18 checks. It hasn't
met a real company's Workday yet; the first ones you try will show what it
still misses, and each run is remembered per site like any other.

### 18. Good enough to send: a quality check on every draft

The fabrication guard asks whether a draft claims something you can't back.
A letter can pass that and still be the kind recruiters skip — "I am writing
to express my keen interest…", nothing about the company, nothing done,
nothing measured — which is the complaint about AI applications generally:
lots sent, few interviews. Every draft (the engine's and your edits) is now
scored 0–100 for quality, locally (agent/quality.py): does it name the
company, use the terms the advert asks for that you can back, say something
you did and what changed, avoid the stock phrases, run 120–300 words, open
with the work rather than "I am…", end with a next step, and avoid the
sentences you've taught it to stop writing. The score and the reasons show
on the draft.

In auto-apply, a draft under the bar (60, `min_quality`) is redrafted once
with its reasons as instructions; if it's still under, it's held for you
with the first reason. Your approval overrides the bar; nothing overrides
the claim check, which is still checked first.

**Fixed, found by the new checks:** the fabrication guard held a letter for
signing off with your own first name (your name wasn't in what it checked
against), and for "Dear Hiring Manager" ("Hiring", "Manager" read as
unsourced claims). Your name and location now count as yours, and the words
every letter uses around its claims are ignored.

### 19. Why a full cycle didn't finish — and the fixes

Asked why a full cycle didn't complete applications, the honest answer went
beyond the settings. Three things a fresh install couldn't get past:

- **No way to set up the email account here.** Since the apps split, the
  sending account could only be set up in Agent Jo — and the readiness check
  sent you there. Emailed applications could never go from a fresh Agent Jo
  Jobs. **Auto-apply → Sending email** now has it: your address, its password
  (stored encrypted; Gmail, Outlook, Yahoo and iCloud servers filled in for
  you, with the app-password note where it's needed), on/off, and **Send a
  test to myself**, which is the only real proof it works.
- **Company forms required a "path to your CV file"** that nothing in the
  window asked for, so every form application stopped there. The CV you
  pasted is enough now: a designed PDF of it is made and uploaded.
- **Your contact details had nowhere to go.** Forms ask for name, email,
  phone and location every time; the profile form didn't have them. **Your
  profile → Contact details** does now (email falls back to your sending
  address).

The readiness panel says all of this plainly, with **Fix it** buttons: what
stops anything being sent, that forms still work without email, that the
Prepare level fills forms and leaves them for you (Full submits), and how
many applications your unanswered questions are holding up.

**Settling in.** The first three days live run at most two applications a
day and two forms a run, so the first real ones are few enough to read. It
says so, and you can end it early.

Also: the layout check used time.sleep inside a Playwright session (the page
can't run during it), which made it fail now and then; it waits properly now.

### 20. One look

The New / Previous switch in the sidebar is gone: the two looked almost the
same. The window keeps one look, and what the "new" one fixed applies always
— the narrow window that reflows instead of cutting off at the right, the
brighter faint text, the engine picker reachable when narrow. A saved choice
from before is cleared.

### 21. Deal-breakers that count, freshest first, and a backup

**Deal-breakers and must-haves.** The profile had both fields from the start
and nothing read them, so auto-apply could apply to the very roles you'd
ruled out. Your profile now has them. A deal-breaker the advert states
("commission only", "night shift"), matched as a whole phrase, screens the
role out before any engine is asked, and the gate holds it too (your
approval overrides). Must-haves the advert doesn't mention are shown on the
role, "worth asking", rather than used to reject, because adverts leave
things out. Neither counts as something a draft may claim.

**Freshest first.** Among roles of about the same fit, the newest goes first:
the first few days are when an application is read.

**Backup & restore** (Engines). One zip of your roles, drafts, answers,
people, CV and learned style. The browser's sign-ins are left out, since
they're large and better redone. A weekly backup is made by the daily
cycle, and the last ten are kept. Restore checks the zip is a backup from
this app with no path leaving its folder, and keeps a copy of what's there
first. A file in use is put in place at the next start. On a different
computer, enter the email password again (it's encrypted for this one).

### 22. The Symbolic Synapse look, in Jobs green, and a logo of its own

**The look.** Jobs now wears the look of symbolicsynapse.co.za, the same
one Agent Jo uses, with Jobs' own green where Agent Jo has cyan. The two
read as one family and are still easy to tell apart.

- The site's very dark ground with its film grain, steel-blue light, and the
  green accent you had.
- The site's typefaces: Archivo for headlines and numbers, IBM Plex Sans for
  text, IBM Plex Mono for labels and counts. They replace Times New Roman.
  The fonts ship inside the app (`web_jobs/fonts`, with their SIL Open Font
  License files). No font service is contacted, so it works offline.
- Pill buttons: solid green for the one to press, outlined for the rest. The
  light still sweeps across a button while it's working.
- Frosted cards with a soft light that follows the mouse. "Where you are" in
  the sidebar is green, as on the site.
- On the overview, beside the headline, the Jobs logo sits inside the site's
  slowly turning lattice, with filaments of light. It runs only while the
  overview is open and the window is visible. Left alone for two minutes it
  holds still until you move the mouse or type. With reduced motion turned on
  in Windows it's drawn once and never moves. It's hidden in a narrow window.
- "by Symbolic Synapse" under the name is set as the site's two-tone
  wordmark.
- The phone companion has the same dark ground, green buttons and round
  corners.
- There's no switch: this replaces the old look. Layout is unchanged, so
  every narrow-window fix still applies.

**A logo of its own.** Jobs used the same square picture as Agent Jo, so in
the taskbar, on the desktop and in a browser tab there was no telling which
was which. The Jobs logo is now Agent Jo's portrait in a green ring, with a
green hexagon badge (the lattice's cell) carrying a briefcase. The small
sizes (16 to 64 px) are drawn separately, with a heavier ring and a bigger
badge, so they still read. It's used everywhere:

- the desktop shortcut and the installer (`agent-jo-jobs.ico`);
- the browser tab (with sizes for 16 and 32 px);
- the sidebar;
- the phone companion's home-screen icon;
- a new app manifest, so Jobs can be installed as its own window with its
  own taskbar icon (in Edge or Chrome, use the browser menu's option to
  install this site as an app).

The icon links carry `?v=green1` so a browser doesn't keep showing the old
picture. `tools/make_logo.py` rebuilds every size from the portrait in
`branding/`, and the full-size logo is `branding/agent-jo-jobs-logo-1024.png`.
Windows may keep showing the old picture on an existing desktop shortcut
until it refreshes its icon cache (signing out and in usually does it).
Running `install.bat` again recreates the shortcut. A rebuilt installer
carries the new icon too.

**Also.** On a window as narrow as a phone, the overview's three buttons ran
off the right edge. Below 600 px they now wrap.
`tools/check_layout.py` now also checks the fonts, the logo, the lattice
(drawn, stopping and staying still when it should) and every one of the 12
views for sideways scrolling, from phone width to desktop.


### 23. Smarter on company sites, and better with every application

Asked for: make Agent Jo Jobs a lot smarter at exploring websites and the
tools it can call, and let it improve itself with every application.

**It finds the form, wherever it is.** The form filler used to fill the boxes
on the advert's own page. Most adverts aren't the form: there's an "Apply"
button, often a new tab, a cookie banner, a form inside an iframe, two or
three pages behind "Continue". On a Lever advert it found no boxes and called
the form "filled". The new navigator (`agent/navigator.py`) works through a
site the way a person does:

- It reads the whole page: every frame (forms embedded from another site
  included), boxes inside web components, each box's question whether it
  comes from a label, a placeholder or the text above it, radio groups,
  drop-downs (native and custom lists), file uploads, buttons, error
  messages, and the signs of a sign-in or a captcha. The invisible reCAPTCHA
  badge that sits on half the forms on the web is no longer mistaken for a
  captcha.
- It declines cookie banners, follows a button into a new tab, and goes page
  by page through the form. When a form complains ("Enter a 10-digit number
  starting with 0"), it reads the complaint and fixes it: your phone number
  is offered in local, international and digits-only formats.
- What your profile settles is filled by rules: names, email, phone, CV,
  covering letter, country, city, where you heard about the role. Answers
  you gave before come next, then the engine answers questions from your
  profile and CV, through the same claims check as every draft.
- When it meets something new, the engine looks at the page and acts
  through a small set of tools: press a button, say which of your details
  goes in a box, have a question answered from your profile, attach your CV,
  scroll, go back, leave a note for next time, or say it's done. It never
  writes your details or answers itself, and it's shown only whether a box
  is filled, never what's in it. It has at most 12 steps per application (you
  can change that, or switch the engine off for sites it doesn't know).
- Workday applications still go to the Workday walker, now also when an
  advert on a company's own site leads there.

**Rails it can't cross,** whatever the engine suggests: it never submits
unless your level submits forms and nothing needs you, and on a form page it
treats "Apply", "Done" and "Send" as submit; never signs in, creates an
account or uses "Apply with LinkedIn/Indeed"; never automates LinkedIn or
Indeed, even after a redirect; never ticks a consent box or presses "I
agree"; never subscribes you to anything; never answers gender, race,
disability and the other sensitive questions (a salutation list counts);
never accepts cookies. A sign-in or a captcha is handed to you, as before.
An advert that says the role is closed is marked closed; one that asks for
an email instead of a form moves the role to the email path, where every
email check applies.

**It improves with every application.** What each application teaches is kept
in a playbook per site (`agent/playbooks.py`, stored as
`jobscout/playbooks.json`): the way from the advert to the form, what the
site's "next" button is called, which of your details its unfamiliar labels
mean, notes the engine left, and whether it asks for a sign-in. The next
application through the same site, or any site on the same hiring system,
starts from that. In the checks, the second application through an awkward
site needed the engine zero times, against several the first time. It
corrects itself: a step that stops working is dropped, and a label it got
wrong is corrected and says so.

Letters improve too: your own sent letters that got a reply, an interview or
an offer are given to the engine as examples of tone and structure for
similar roles (never as a source of facts; the claims check reads every word).
A draft says which letters it learned from.

**You can see it.** A role's result now lists what it did, step by step (each
marked as a rule, something learned, the engine, or your own answer), what's
left for you, and what it learned; the role keeps its last attempt. Run
reports say what each run's forms taught it. Auto-apply has a new card,
*Getting better with every application*: each site it knows, the engine
steps application by application, the share of forms finished without you
against the ones before, a Forget button per site, and the engine settings.

**More places to find roles.** Workable, SmartRecruiters, Recruitee, Workday,
BambooHR, Personio and Teamtailor are read directly, as Greenhouse, Lever and
Ashby already were. *Sources → Find a company's job board*: paste a careers
page and it finds the hiring system behind it (embedded, linked, or one
careers link away), checks the board returns roles, and offers it to add.
Forms it has been through reveal company boards too.

**Also.**
- What the app types into a form is no longer saved as if you'd typed it.
  The helper in the page saved answers on every change, the app's own typing
  included, so an engine's answer could have been reused later as yours,
  unchecked.
- The helper in the page keeps out of the way while the app is working (it
  popped up over a list and took the click meant for it), and is back the
  moment the form is handed to you.
- A frame that never finishes loading (an `about:blank#…` iframe, common in
  ads and captchas) used to hang the browser; it's skipped after a moment.
- The interview brief (`/api/jobs/brief`) was declared above its request
  model, so every call came back 422. Fixed.

**Checks.** `tests/test_logic.py` has three new groups: the navigator against a
site in memory (`tests/fakesite.py`), the playbook and the auto-apply run, and
discovery: 86 checks. `tools/check_navigator.py` walks whole applications in
Chromium on a deliberately awkward local site (`tests/fixtures/nav`): a
cookie banner, an unknown apply button, a new tab, the form in a
cross-origin iframe, a web component, a custom list, a form that rejects the
phone format, gender and consent boxes, a captcha, a closed and an
email-only advert: 23 checks. `tools/check_layout.py` measures the new card,
the role's last attempt and the board finder at phone and desktop widths.


### 24. install.bat no longer closes half-way

Reported: the installation dies while running the .bat file.

`install.bat`, `start.bat` and the other Windows scripts had been saved with
Unix line endings. With those, cmd.exe loses its place when it jumps to a
label (`call :try_py`, `goto have_py`); the jump fails, the script stops,
and a double-clicked window simply disappears. Every `.bat`, `.ps1` and
`.iss` file now has Windows line endings and plain ASCII text, and a
`.gitattributes` keeps them that way.

Two more fixes on the same path:
- When install.bat had to install Python for you, the new Python wasn't on
  the window's PATH, so making the environment failed and was reported as a
  package problem. It now reads the PATH afresh and looks where Python's
  installer puts it; if it still can't see it, it says to run install.bat
  again.
- If the environment (`.venv`) can't be made, it says so, with the likeliest
  cause (a folder inside OneDrive), instead of "installing packages failed".

A check in `tests/test_logic.py` fails if any Windows script loses its
Windows line endings or gains a non-ASCII character.


### 25. The installer can't close without saying why

Reported: the installation still dies.

install.bat did every step itself with its output hidden, and some failures
ended with the window closing. It's now small, like Agent Jo's: it finds a
Python, then runs `setup_jobs.py`, which records every step and its full
output in `install.log`. If a step fails, the window shows the last 30 lines
of that log and waits. It also says so if it's run from inside the zip
rather than an extracted folder. `start.bat` now stays open, with the error,
if the app stops. And `setup_jobs.py` reads each command's output as UTF-8,
so a character the Windows codepage can't decode no longer stops setup.
