# Agent Jo Jobs

**A job search that runs on your own machine** — and won't send an application
that says something about you that isn't true.

It finds roles on the boards you choose, scores each one against your profile,
drafts the application, and **holds any draft that claims a tool, an employer
or a number of years your profile can't support**. Then it learns which
sources actually produce replies.

*by Symbolic Synapse*

---

## What it does

**Finds** — your boards, careers pages, RSS feeds, and the alert emails from
boards that block scraping. Paste a company's careers page and it finds the
hiring system behind it (Greenhouse, Lever, Workday and seven more), so every
role that company lists comes in. It checks a board returns roles before
adding it.

**Scores** — each role against what you've actually done, with a free keyword
check before any engine is called.

**Drafts** — a covering note, a tailored CV, interview preparation. Every
claim in a draft is checked against your profile; anything unsupported is
held with the exact claim shown.

**Applies** — by email, or through a company's own site: it finds the form
behind the advert (a new tab, a form inside the page, several pages of it),
fills it, and stops for you to submit unless your level submits forms.
Auto-apply runs unattended within limits you set, and rehearsal keeps
everything local until you're sure.

**Learns** — every form it fills teaches it that site, so the next
application there needs the engine less (often not at all). Letters that got
replies shape the tone of the next ones. And it learns which boards reply,
whether your fit score predicts anything, and whether email beats a portal.
Every rate carries the range it could really be.

## Install

Windows — double-click **`install.bat`**. It finds or installs Python, sets
up an isolated environment, checks the app loads, and puts an **Agent Jo Jobs**
shortcut on your desktop.

macOS — double-click `install.command`. Linux — `./install.sh`.

It opens at **http://127.0.0.1:8766**. Point it at a local Ollama model and
nothing leaves your machine; or add a cloud engine with its own key.

## From your phone

Engines → **Phone companion** → Turn on, then scan the code with your phone's
camera. On your phone you can answer the questions applications are waiting
on, approve or skip drafts, see interviews coming up and what the last run
did, and pause everything in one tap. It can't see your CV or profile or
change any setting.

It's off until you turn it on, and runs on its own port (8767). The key in
the link is the password — **New key** makes the old link stop working. On
home Wi-Fi the traffic isn't encrypted, so don't use it on shared Wi-Fi; to
use it away from home, install Tailscale (free) on the PC and the phone and
scan the Tailscale code instead. Windows may ask to let Python through the
firewall on private networks: allow it, or the phone can't connect.

## Your data

Everything lives in `~/.agent_jo_jobs` (`C:\Users\<you>\.agent_jo_jobs` on
Windows), never in the app folder — so upgrading is replacing the folder.

Agent Jo, if you also run it, has its own folder: the two apps share
nothing. Coming from Agent Jo? See *Its own app* below.

## Licence

Free for personal, research and non-commercial use under the
[PolyForm Noncommercial License 1.0.0](LICENSE). Commercial use needs a
licence — see [COMMERCIAL.md](COMMERCIAL.md).

---

### Updates in one click

Each app checks for, verifies and installs its own updates — and installs
nothing it can't prove you signed.

**Once, on the machine you build releases on:**

1. Make a signing key — Agent Jo: `python tools/sign.py --make-key`;
   Agent Jo Jobs: `python tools/make_release.py --make-key`. Keep
   `signing-key.private` secret and out of git; `signing-key.pub` ships
   with the app.
2. Build a release (`python tools/make_release.py`). It signs exactly the
   files in the zip and writes `dist/latest.json` beside it.
3. Install that first signed release by hand, so your copy carries the key.

**Each new version after that:** build, then upload the zip and
`latest.json` to the same place (a GitHub release works). In the app — Agent
Jo: Settings → Updates; Agent Jo Jobs: Engines → Updates — paste
latest.json's address once, then **Check for updates → Install update**, and
restart. **Roll back** puts the previous version back exactly.

Refused, with the reason: anything not signed by the key in your copy, a
file changed after signing, a checksum mismatch, an older build, a release
carrying a different key, and any file outside the app folder or in its
Python environment. Your data is never touched.

### Windows installer (.exe)

**Build it** (on a Windows PC): double-click **Build Windows Installer.bat** in
this folder. It installs Inno Setup with winget if you don't have it, and
writes `dist\AgentJoJobs-Setup-<version>.exe` a minute later. No Windows PC to hand?
Put the folder on GitHub and run **Actions → Windows installer → Run
workflow**: the .exe is attached to the run.

**What the .exe does:** installs into your own user folder
(`%LOCALAPPDATA%\Programs\Agent Jo Jobs`) with no administrator prompt; finds
Python 3.10+, or downloads the official one from python.org and installs it
for you alone; sets up the app's packages and the browser portal applications drive; and adds Start menu and
desktop shortcuts. Uninstall it from Settings → Apps. Your data, in
`%USERPROFILE%\.agent_jo_jobs`, is never touched, so reinstalling or upgrading keeps
everything.

**Windows will warn the first time** ("Windows protected your PC"), because
the .exe isn't code-signed: click **More info → Run anyway**. Removing that
warning needs a code-signing certificate, which is a paid, separate step.

### Your CV and your answers

**Paste your full CV, or upload it** (PDF or Word) under *Your profile*. It's split into sections and
searched whenever it's needed: a letter draws on the parts of the CV that fit
the advert, a form question on the parts that answer it. Empty profile fields
are filled from it, and a tool or employer named in the CV counts as yours in
the claims check.

**Every answer you type into an application form is saved** with its
question (by the helper in the form, when you leave a field) and filled in
for you on the next form that asks it, in any close wording. See and edit
them under *Answers*. Passwords and card numbers are never kept; answers to
sensitive questions (gender, race, disability, ID number) are kept but only
reused once you switch them on.

**Questions nothing could answer wait for you in one place:** *Answers →
Waiting on you* lists each one with the applications it's holding up. Answer
it once and every one of those forms, and every later one, gets it.

### Company sites it has never seen

Most adverts send you to a company's own site, and every site is different.
Applying works the way you would: it reads the page (every frame, every box
with its question, every button), presses the way in, declines the cookie
banner, follows a new tab, and works through each page of the form.

- **What it knows first.** The way to the form, the names of a site's
  buttons and what its unfamiliar boxes mean ("Current CTC" is your salary
  expectation) are kept from earlier applications, for that site and for
  every site on the same hiring system.
- **The engine for what's new.** When it doesn't know, the engine looks at
  the page and acts through a few tools: press a button, say which of your
  details goes in a box, have a question answered from your profile, attach
  your CV. It never types your details itself, and it's only shown whether a
  box is filled, not what's in it.
- **Rails it can't cross.** It never submits unless your level submits forms
  and nothing needs you; never signs in or creates an account; never uses
  "Apply with LinkedIn" or touches LinkedIn or Indeed; never ticks a consent
  box or presses "I agree"; never answers gender, race, disability and the
  other sensitive questions; never accepts cookies. A sign-in or a captcha is
  handed to you.
- **You can see it.** Each application lists what it did, step by step, and
  what it learned. *Auto-apply → Getting better with every application*
  shows each site it knows, the engine steps each application took, and the
  share of forms it finished without you. You can make it forget a site, or
  stop the engine working out sites it doesn't know.

### Replies, read for you

Under *Results*, switch on **Read my inbox** (it uses the login you set up
for sending; Gmail and Outlook need an app password and IMAP turned on). Each
full cycle, and **Check for replies now**, reads replies to your
applications: an interview or an offer moves that role on, a turn-down
closes it, and "we've received your application" is noted but not counted.
The mailbox is only read — nothing is marked read, moved or sent. Rather not
connect it? Save reply emails as `.eml` files in `jobscout/replies` in the
data folder.

### A weekly digest

Under *Results → Weekly digest*, switch on one email a week to yourself:
applications sent, who answered and how, what's waiting on you, and what the
results so far support. It goes out with the morning run on the day you
pick; a week with nothing to say sends nothing. Preview it there first.

### Its own app

Agent Jo Jobs used to live inside Agent Jo, share its data folder, and have
its code copied across from there. Since the split (CHANGELOG.md, entry 1) it
is fully independent: its own download, its own folder, its own code. Change
it here; nothing is synced in from Agent Jo any more.

**Coming from Agent Jo?** On its first start this app copies your job data
across from Agent Jo's folder (`~/.local_agent`): roles, profile and CVs,
auto-apply settings, the browser logins for job sites, your engines and their
keys, and the daily run. It only copies; Agent Jo's folder is left as it was.
To keep the data somewhere else, set `AGENT_JOBS_HOME` before the first start.

### Checks

```
python tests/run_tests.py     # the app, the window, and the job logic
python tests/test_logic.py    # just the job logic
python tools/check_layout.py  # the window, measured in a real browser
python tools/check_helper.py  # the in-form helper, in a real browser
python tools/check_answers.py # typed answers saved and reused, in a real browser
python tools/check_navigator.py # a whole application on an awkward site, in a real browser
```
