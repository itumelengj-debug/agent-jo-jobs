/* Agent Jo Jobs.
 *
 * Every endpoint the job search has is reachable from here. The first cut of
 * this window wired twelve of forty-seven and quietly dropped the rest —
 * scoring, drafting, CV tailoring, interview prep, portal applications,
 * claims, auto-apply controls, alerts, the archive. A redesign that removes
 * what people used is a regression wearing new clothes.
 *
 * Nothing here decides anything. The fabrication check, the fit score and the
 * auto-apply rules live on the server; this renders what they conclude.
 */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

const S = {
  // one definition of "profile ready", the server's. The window had three —
  // onboarding, the rail and the server — and they disagreed on a fresh
  // install: step one said done while the rail said empty.
  profileReady: false,
  view: "overview", roles: [], selected: null, ticked: new Set(),
  filter: "", chip: "", sort: "fit", data: null, engine: "",
};

/* --- plumbing ---------------------------------------------------------- */
async function api(path, body, method) {
  // A GET must not carry a body — the browser rejects the request outright,
  // before it's sent. The first version of this attached one to every call
  // that named a method, so every read silently failed: the pipeline showed
  // zeros under a headline counting eight roles, and the engine list was
  // empty. Reads and writes are different shapes, so build them separately.
  const verb = (method || (body === undefined ? "GET" : "POST")).toUpperCase();
  const opts = verb === "GET" ? { method: "GET" } : {
    method: verb,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  };
  const r = await fetch(path, opts);
  let d = null;
  try { d = await r.json(); } catch (e) { d = null; }
  if (!r.ok) {
    let m = d && (d.detail || d.error);
    if (Array.isArray(m)) m = m.map((x) => x.msg || x).join("; ");
    throw new Error(m || `${r.status}`);
  }
  return d || {};
}
const withEngine = (b) => Object.assign({ engine: S.engine }, b || {});

function toast(msg, kind) {
  const t = el("div", "toast" + (kind ? " " + kind : ""), msg);
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), 5600);
}

function empty(host, title, detail) {
  host.innerHTML = "";
  const e = el("div", "empty");
  e.appendChild(el("b", "", title));
  if (detail) e.appendChild(document.createTextNode(detail));
  host.appendChild(e);
}

async function busy(btn, label, fn) {
  const was = btn.textContent;
  btn.disabled = true; btn.textContent = label;
  btn.classList.add("is-busy");          // the chrome sweep, while it works
  try { return await fn(); }
  catch (e) { toast(e.message, "bad"); }
  finally {
    btn.disabled = false; btn.textContent = was;
    btn.classList.remove("is-busy");
  }
}

/* A run scores, drafts and fills forms — minutes of work. It runs on the
   server now and this follows it, showing where it has got to. Held open as
   one request, the window gave up first and reported an error while the run
   carried on: that was much of "hit and miss". */
async function followRun(btn, path) {
  const was = btn.textContent;
  btn.disabled = true;
  btn.classList.add("is-busy");
  try {
    // if a run is already going (the daily one, or another click), this
    // follows that one rather than starting a second
    let s = await api(path, withEngine({ background: true }));
    for (;;) {
      if (s.state === "done") return s.result || {};
      if (s.state === "failed") throw new Error(s.error || "The run failed.");
      const p = s.progress || {};
      btn.textContent = p.total ? `${p.phase} ${p.done}/${p.total}…`
                                : `${p.phase || "Working"}…`;
      btn.title = p.title || "";
      await new Promise((res) => setTimeout(res, 1500));
      s = await api("/api/jobs/auto/status", undefined, "GET");
    }
  } finally {
    btn.disabled = false; btn.textContent = was; btn.title = "";
    btn.classList.remove("is-busy");
  }
}

/* the same cause on twelve roles is one message, not twelve toasts */
function toastErrors(x) {
  if (x.common_error) { toast(String(x.common_error), "bad"); return; }
  const groups = Object.entries(x.error_groups || {});
  if (groups.length) {
    groups.slice(0, 3).forEach(([why, n]) =>
      toast(n > 1 ? `${n} roles: ${why}` : String(why), "bad"));
    return;
  }
  (x.errors || []).slice(0, 3).forEach((m) => toast(String(m), "bad"));
}

// restart a pane's entrance when what it shows changes
function enterView(node) {
  if (!node || !node.classList) return;
  node.classList.remove("view-enter");
  void node.offsetWidth;
  node.classList.add("view-enter");
}

const initial = (s) => ((s || "?").trim()[0] || "?").toUpperCase();
const fitOf = (r) => (r.fit || {}).score;

/* --- navigation -------------------------------------------------------- */
const LOADERS = {};
function show(view) {
  S.view = view;
  $$(".nav").forEach((b) => b.classList.toggle("is-on", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("is-on", v.id === "v-" + view));
  if (LOADERS[view]) LOADERS[view]();
}

/* --- the shared payload: one call feeds the rail and most views -------- */
async function refresh() {
  try {
    S.data = await api("/api/jobs");
    S.roles = S.data.roles || [];
  } catch (e) { S.data = { roles: [] }; S.roles = []; }
  railCounts();
  return S.data;
}

// What a draft leans on. Completeness is the share of these that are filled
// in — a number that means something, and a tooltip saying what's missing.
const PROFILE_PARTS = [
  ["target_roles", "roles you're after"], ["skills", "skills"],
  ["technologies", "tools"], ["employers", "where you've worked"],
  ["locations_ok", "where you'd work"], ["summary", "a summary"],
  ["achievements", "achievements"], ["full_name", "your name"],
];
function profileCompleteness(p) {
  p = p || {};
  const has = (v) => Array.isArray(v) ? v.length > 0 : !!String(v || "").trim();
  const missing = PROFILE_PARTS.filter(([k]) => !has(p[k])).map(([, label]) => label);
  return { pct: Math.round(100 * (PROFILE_PARTS.length - missing.length) / PROFILE_PARTS.length),
           missing };
}

function railCounts() {
  const set = (id, n) => { const e = $(id); if (e) e.textContent = n ? n : ""; };
  set("#nRoles", S.roles.length);
  set("#nDrafts", S.roles.filter((r) => r.stage === "held"
                                   || (r.bucket === "held")).length);
  const auto = (S.data || {}).auto || {};
  const pill = $("#railAuto");
  if (pill) {
    pill.classList.toggle("on", !!auto.enabled);
    pill.setAttribute("aria-checked", auto.enabled ? "true" : "false");
    // railCounts runs on nearly every view; a missing piece of the switch
    // must not take all of them down with it
    const txt = pill.querySelector(".pt-txt");
    if (txt) txt.textContent = auto.enabled ? (auto.dry_run ? "Test" : "On") : "Off";
    pill.title = auto.enabled
      ? (auto.dry_run ? "Auto-apply is rehearsing — nothing is sent. Click to turn off."
                      : "Auto-apply is on. Click to turn off.")
      : "Auto-apply is off. Click to turn on (rules in the Auto-apply view).";
  }
  const c = profileCompleteness((S.data || {}).profile);
  const b = $("#nProfile");
  if (b) { b.textContent = c.pct + "%"; b.classList.toggle("warn", c.pct < 60); }
  const f = $("#profileFill");
  if (f) f.style.width = c.pct + "%";
  const m = $("#profileMeter");
  if (m) m.title = c.missing.length ? "Missing: " + c.missing.join(", ") : "Complete";
}

/* --- overview ---------------------------------------------------------- */
const STEP_ART = [
  '<svg viewBox="0 0 48 48"><circle cx="17" cy="20" r="11" class="f"/><circle cx="17" cy="17" r="4"/><path d="M9.5 27a8 8 0 0 1 15 0"/><path d="M33 14h9M33 20h7M33 26h9"/><circle cx="30" cy="14" r="1.2"/><circle cx="30" cy="20" r="1.2"/><circle cx="30" cy="26" r="1.2"/></svg>',
  '<svg viewBox="0 0 48 48"><circle cx="20" cy="20" r="12" class="f"/><path d="M8 20h24M20 8c4 3.5 4 20.5 0 24M20 8c-4 3.5-4 20.5 0 24"/><ellipse cx="36" cy="28" rx="7" ry="2.5" class="f"/><path d="M29 28v8c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-8M29 32c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/></svg>',
  '<svg viewBox="0 0 48 48"><rect x="5" y="10" width="26" height="18" rx="3" class="f"/><path d="M10 16h10M10 21h14"/><rect x="21" y="18" width="22" height="16" rx="3" class="f"/><circle cx="30" cy="27" r="5"/><path d="m34 31 5 5"/></svg>',
];

const STAGES = [
  ["found", "Found"], ["scored", "Scored"], ["drafted", "Drafted"],
  ["held", "Held"], ["applied", "Sent"], ["responded", "Replied"],
];

LOADERS.overview = async function () {
  try { S.profileReady = !!(await api("/api/meta")).profile_ready; }
  catch (e) { /* keep the last answer */ }
  const now = new Date();
  $("#ovDate").textContent = now.toLocaleDateString(undefined,
    { weekday: "long", day: "numeric", month: "long" });
  await refresh();
  const p = (S.data || {}).profile || {};
  const hasProfile = S.profileReady;
  let sources = [];
  try { sources = (await api("/api/jobs/search/config", undefined, "GET")).sources || []; }
  catch (e) { /* the steps still render */ }
  $("#nSources").textContent = sources.length || "";

  // a first run is a checklist, not a row of zeros
  const steps = [
    ["Tell it who you are", "What you've done is the only thing a draft is allowed to claim.",
     !!hasProfile, "Fill in your profile", () => show("profile")],
    ["Tell it where to look", "Boards, careers pages, RSS — or let it find some.",
     sources.length > 0, "Add sources", () => show("sources")],
    ["Find roles", "It searches, scores against your profile, and drafts.",
     S.roles.length > 0, "Search now", () => show("search")],
  ];
  const ob = $("#onboard");
  ob.innerHTML = "";
  if (steps.some((s) => !s[2])) {
    const wrap = el("div", "steps");
    let nextMarked = false;
    steps.forEach(([title, why, done, cta, go], i) => {
      const isNext = !done && !nextMarked;
      if (isNext) nextMarked = true;
      const s = el("div", "step" + (done ? " done" : "") + (isNext ? " next" : ""));
      const art = el("div", "step-art");
      art.innerHTML = STEP_ART[i];
      s.appendChild(art);
      s.appendChild(el("div", "step-num", done ? "✓ done" : `step ${i + 1}`));
      s.appendChild(el("h4", "", title));
      s.appendChild(el("p", "", why));
      if (!done) {
        const b = el("button", "btn sm" + (isNext ? " primary" : ""), cta);
        b.addEventListener("click", go);
        s.appendChild(b);
      }
      wrap.appendChild(s);
    });
    ob.appendChild(wrap);
  }

  let pipe = {};
  try { pipe = await api("/api/jobs/pipeline", undefined, "GET"); } catch (e) { }
  const counts = pipe.stages || {};
  const total = pipe.total ?? S.roles.length;
  $("#ovHead").textContent = total
    ? `${total} role${total === 1 ? "" : "s"} in play.`
    : hasProfile ? "Nothing found yet." : "Let's get you set up.";
  $("#ovLede").textContent = pipe.why
    || (total ? "Here is where each one stands, and what's holding the rest up."
              : "Three steps and it can start looking on its own.");

  const track = $("#track");
  track.innerHTML = "";
  STAGES.forEach(([key, label]) => {
    const n = counts[key] || 0;
    const stop = el("div", "stop" + (n ? " lit" : "")
      + (pipe.blocked_at === key ? " blocked" : ""));
    const ring = el("div", "ring");
    ring.appendChild(el("div", "stop-n" + (n ? "" : " zero"), String(n)));
    stop.appendChild(ring);
    stop.appendChild(el("div", "stop-label", label));
    // No stage-to-stage percentage: "held" is a detour, not a step, so
    // "sent — 100% of held" was computed against the wrong thing. A number
    // that looks like analysis and isn't is worse than none.
    track.appendChild(stop);
  });

  const blk = $("#ovBlocked");
  blk.innerHTML = "";
  if (pipe.blocked_at) {
    blk.appendChild(el("p", "", pipe.why || `Stuck at ${pipe.blocked_at}.`));
  } else {
    blk.appendChild(el("p", "muted", total ? "Nothing is stuck."
                                             : "Nothing to do until roles come in."));
  }
  const extra = pipe.counts || {};
  [["screened", "screened out before any engine was called"],
   ["no_address", "portal-only — nothing can be sent automatically"],
   ["needs_redraft", "held drafts waiting on a rewrite"]]
    .filter(([k]) => extra[k])
    .forEach(([k, why]) => blk.appendChild(el("p", "muted", `${extra[k]} ${why}`)));

  const prevBox = $("#ovPreview");
  prevBox.innerHTML = "";
  try {
    const pv = await api("/api/jobs/auto/preview", undefined, "GET");
    prevBox.appendChild(el("p", "", pv.sentence || "Auto-apply is off."));
    if (pv.dry_run) prevBox.appendChild(el("p", "muted", "Rehearsal is on, so nothing leaves."));
    const go = el("button", "btn sm", "Open auto-apply");
    go.addEventListener("click", () => show("auto"));
    prevBox.appendChild(go);
  } catch (e) { prevBox.appendChild(el("p", "muted", "Couldn't read that.")); }

  drawNeeds(counts, pipe);
  drawWhereFrom();
  drawActivity();

  const iv = (S.data || {}).interviews || [];
  $("#ovInterviewCard").hidden = !iv.length;
  const ih = $("#ovInterviews");
  ih.innerHTML = "";
  iv.slice(0, 6).forEach((x) => {
    const row = el("div", "item");
    row.append(el("div", "mono", initial(x.company)), el("div"),
               el("span", "tag", whenText(x.at)));
    row.children[1].append(el("div", "item-t", x.title || ""),
                           el("div", "item-m", x.company || ""));
    row.addEventListener("click", () => {
      const r = (S.roles || []).find((y) => y.key === x.key);
      show("roles"); if (r) openRole(r);
    });
    ih.appendChild(row);
  });

  const fu = (S.data || {}).follow_ups || [];
  $("#ovFollowCard").hidden = !fu.length;
  const fh = $("#ovFollow");
  fh.innerHTML = "";
  fu.slice(0, 6).forEach((f) => {
    const row = el("div", "item static");
    row.append(el("div", "mono", initial(f.company)),
      Object.assign(el("div"), {}),
      el("span", "tag", `${f.days || "?"}d`));
    row.children[1].append(el("div", "item-t", f.title || ""),
                           el("div", "item-m", f.company || ""));
    fh.appendChild(row);
  });
};

// The overview used a third of the screen and left the rest empty. These three
// are built only from what the app already knows — no invented activity.
function needRow(host, label, n, where, why) {
  if (!n) return;
  const b = el("button", "need");
  b.type = "button";
  b.append(el("span", "need-n", String(n)),
           el("span", "need-t", label));
  if (why) b.appendChild(el("span", "need-why", why));
  b.addEventListener("click", () => show(where));
  host.appendChild(b);
}

function drawNeeds(counts, pipe) {
  const host = $("#ovNeeds");
  if (!host) return;
  host.innerHTML = "";
  const extra = (pipe || {}).counts || {};
  const scored = (counts || {}).scored || 0;
  needRow(host, "held draft(s) claiming too much", extra.held
    || (counts || {}).held || 0, "drafts", "read and redraft");
  needRow(host, "need rewriting since your profile changed",
          extra.needs_redraft || 0, "drafts", "");
  needRow(host, "scored, not drafted yet", scored, "roles", "draft them");
  needRow(host, "not scored yet", (counts || {}).found || 0, "roles",
          "score to rank them");
  needRow(host, "portal-only — no address to email", extra.no_address || 0,
          "roles", "apply through the site");
  if (!S.profileReady) {
    needRow(host, "your profile is too thin to draft from", 1, "profile",
            "fill it in");
  }
  if (!host.children.length) {
    host.appendChild(el("p", "muted", "Nothing waiting on you."));
  }
}

async function drawWhereFrom() {
  const host = $("#ovSources");
  if (!host) return;
  host.innerHTML = "";
  const bySource = {};
  S.roles.forEach((r) => {
    const s = r.source || "added by hand";
    bySource[s] = (bySource[s] || 0) + 1;
  });
  const rows = Object.entries(bySource).sort((a, b) => b[1] - a[1]).slice(0, 6);
  if (!rows.length) {
    host.appendChild(el("p", "muted", "No roles yet."));
    return;
  }
  const top = rows[0][1];
  rows.forEach(([name, n]) => {
    const row = el("div", "bar-row");
    row.appendChild(el("span", "bar-name", name));
    const track = el("span", "bar-track");
    const fill = el("span", "bar-fill");
    fill.style.width = Math.max(6, Math.round((n / top) * 100)) + "%";
    track.appendChild(fill);
    row.append(track, el("span", "bar-n", String(n)));
    host.appendChild(row);
  });
  // a source that returned nothing last time is worth knowing about here
  try {
    const cfg = await api("/api/jobs/search/config");
    const bad = (cfg.sources || []).filter((s) => s.status === "failing");
    if (bad.length) {
      const p = el("p", "muted");
      p.textContent = `${bad.length} source(s) returned nothing last check: `
        + bad.map((s) => s.name).join(", ");
      host.appendChild(p);
    }
  } catch (e) { /* the counts still stand */ }
}

function drawActivity() {
  const host = $("#ovActivity");
  if (!host) return;
  host.innerHTML = "";
  const events = [];
  S.roles.forEach((r) => {
    (r.events || []).forEach((e) => events.push({
      at: e.at || "", stage: e.stage || "", note: e.note || "",
      title: r.title, key: r.key,
    }));
  });
  events.sort((a, b) => String(b.at).localeCompare(String(a.at)));
  if (!events.length) {
    host.appendChild(el("p", "muted",
      "Nothing yet. Scoring, drafting and applying all show up here."));
    return;
  }
  const said = {
    applied: "applied to", drafted: "drafted for", held: "held a draft for",
    responded: "heard back from", interview: "interview for",
    offer: "offer from", closed: "closed",
  };
  events.slice(0, 6).forEach((e) => {
    const row = el("button", "act");
    row.type = "button";
    row.append(el("span", "act-dot act-" + (e.stage || "")),
               el("span", "act-t", `${said[e.stage] || e.stage} ${e.title}`),
               el("span", "act-at", (e.at || "").replace(" UTC", "")));
    row.addEventListener("click", () => { S.selected = e.key; show("roles"); });
    host.appendChild(row);
  });
}

/* --- roles: list and the role itself ----------------------------------- */
const CHIPS = [["", "All"], ["email", "Can email"], ["fit", "Fit 75+"],
               ["unscored", "Not scored"], ["open", "Still open"]];

LOADERS.roles = async function () {
  await refresh();
  drawRoleList();
  if (S.selected) {
    const r = S.roles.find((x) => x.key === S.selected);
    if (r) openRole(r); else placeholderRole();
  } else placeholderRole();
};

function placeholderRole() {
  const d = $("#roleDetail");
  d.innerHTML = "";
  const p = el("div", "placeholder");
  const inner = el("div");
  inner.appendChild(el("b", "", S.roles.length ? "Pick a role" : "No roles yet"));
  inner.appendChild(el("div", "", S.roles.length
    ? "Everything you can do with it opens here."
    : "Search, or add a source and let it look for you."));
  p.appendChild(inner);
  d.appendChild(p);
}

function drawRoleList() {
  const chips = $("#roleChips");
  chips.innerHTML = "";
  CHIPS.forEach(([k, label]) => {
    const c = el("button", "chip" + (S.chip === k ? " is-on" : ""), label);
    c.type = "button";
    c.addEventListener("click", () => { S.chip = k; drawRoleList(); });
    chips.appendChild(c);
  });

  const q = S.filter.toLowerCase();
  let rows = S.roles.filter((r) => {
    if (q && !`${r.title} ${r.company} ${r.source || ""}`.toLowerCase().includes(q)) return false;
    const f = fitOf(r);
    if (S.chip === "email" && !r.apply_email) return false;
    if (S.chip === "fit" && !(f >= 75)) return false;
    if (S.chip === "unscored" && f !== undefined && f !== null) return false;
    if (S.chip === "open" && (r.stale || r.stage === "closed")) return false;
    return true;
  });
  const sorters = {
    fit: (a, b) => (fitOf(b) || -1) - (fitOf(a) || -1),
    new: (a, b) => String(b.found_at || "").localeCompare(a.found_at || ""),
    company: (a, b) => String(a.company || "").localeCompare(b.company || ""),
    stage: (a, b) => String(a.stage || "").localeCompare(b.stage || ""),
  };
  rows = rows.slice().sort(sorters[S.sort]);

  const list = $("#roleList");
  list.innerHTML = "";
  if (!rows.length) {
    empty(list, S.roles.length ? "Nothing matches" : "No roles yet",
          S.roles.length ? "Try a different filter." : "Go to Search to find some.");
  }
  rows.forEach((r) => {
    const it = el("div", "item" + (r.key === S.selected ? " is-on" : ""));
    it.setAttribute("role", "button");
    // the badge IS the tick box: click it to select, and it shows a tick. An
    // invisible checkbox meant you could select rows and never see which.
    const on = S.ticked.has(r.key);
    const mono = el("div", "mono" + (on ? " ticked" : ""), on ? "✓" : initial(r.company));
    mono.title = "Select";
    mono.addEventListener("click", (e) => {
      e.stopPropagation();
      S.ticked.has(r.key) ? S.ticked.delete(r.key) : S.ticked.add(r.key);
      drawRoleList();
    });
    const body = el("div");
    const t = el("div", "item-t", r.title || "(untitled)");
    // the same state the detail shows: the list said "drafted" beside a
    // detail that said "held", which is one role described two ways
    const st = r.bucket || r.stage || "found";
    if (st !== "found") {
      t.appendChild(el("span", "tag"
        + (st === "held" || st === "needs_redraft" ? " held"
           : st === "applied" ? " sent"
           : st === "closed" || st === "expired" || st === "screened" ? " stop" : ""),
        st === "needs_redraft" ? "needs rewriting" : st));
    }
    body.append(t, el("div", "item-m",
      [r.company, r.location, r.source].filter(Boolean).join(" · ")));
    const f = fitOf(r);
    const fit = el("div", "fit" + (f >= 75 ? " hi" : f !== undefined && f !== null ? "" : " lo"),
                   f === undefined || f === null ? "—" : String(f));
    it.append(mono, body, fit);
    it.addEventListener("click", () => { S.selected = r.key; drawRoleList(); openRole(r); });
    list.appendChild(it);
  });
  drawBulk();
}

function drawBulk() {
  const b = $("#bulk");
  b.hidden = S.ticked.size === 0;
  $("#bulkN").textContent = `${S.ticked.size} selected`;
}

async function bulk(action, btn) {
  const keys = Array.from(S.ticked);
  if (action === "clear") { S.ticked.clear(); drawRoleList(); return; }
  await busy(btn, "Working…", async () => {
    if (action === "remove") {
      await api("/api/jobs/remove", { keys });
      toast(`Removed ${keys.length}.`);
    } else if (action === "score") {
      // one at a time so a failure is counted as a failure, not a success
      let ok = 0, bad = 0;
      for (const key of keys) {
        try { await api("/api/jobs/score", withEngine({ key })); ok++; }
        catch (e) { bad++; }
      }
      toast(bad ? `Scored ${ok}, ${bad} failed.` : `Scored ${ok}.`, bad ? "warn" : "");
    }
    S.ticked.clear();
    await LOADERS.roles();
  });
}

// What the rehearsal worked out, in a form you can paste. Automation gets
// some way into most forms and stops — an upload it can't reach, a question
// in a widget — and retyping what the app already worked out is the moment
// people give up.
async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    const was = btn.textContent;
    btn.textContent = "Copied";
    setTimeout(() => { btn.textContent = was; }, 1200);
  } catch (e) {
    // no clipboard permission: select it instead so ctrl-C works
    const ta = el("textarea", "copy-fallback");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    toast("Press Ctrl+C to copy.", "warn");
    setTimeout(() => ta.remove(), 8000);
  }
}

// It can stop mid-way and ask for you — a sign-in page, a captcha. The
// browser is open on this machine, so the useful thing is to say so and wait,
// then carry on from where it stopped.
function followPortal(r, key) {
  if (S._portalTimer) clearInterval(S._portalTimer);
  const id = key || r.key;
  const tick = async () => {
    let s;
    try { s = await api(`/api/jobs/portal/session/${encodeURIComponent(id)}`); }
    catch (e) { return; }
    if (s.state === "waiting_for_you") {
      showPortalWaiting(s, r);
      return;
    }
    if (s.state === "running") {
      clearNeedsYou();
      showPortalRunning(s, r);
      return;
    }
    if (s.state) {
      clearInterval(S._portalTimer);
      S._portalTimer = null;
      clearNeedsYou();
      showPortal(s, r);
      if (s.state === "needs_answer") toast("Your answers are needed to finish this application.", "warn");
      refresh().then(drawRoleList);
    }
  };
  tick();
  S._portalTimer = setInterval(tick, 2000);
}

function portalBox(title) {
  const box = el("div", "out portal-out");
  box.appendChild(el("h4", "", title));
  return box;
}

function showPortalRunning(s, r) {
  const box = portalBox("Working through the form…");
  box.appendChild(el("p", "muted", s.message || "The browser is open on this machine."));
  const d = $("#roleDetail");
  const was = d.querySelector(".portal-out");
  if (was) was.replaceWith(box); else d.appendChild(box);
}

function showPortalWaiting(s, r) {
  const ask = s.ask || {};
  const box = portalBox(ask.headline || (s.blocked_by === "needs_captcha"
    ? "Your help is needed: there's a captcha"
    : "Your help is needed: this site wants you signed in"));
  box.classList.add("portal-waiting");
  box.setAttribute("role", "alert");
  if (ask.steps && ask.steps.length) {
    box.appendChild(el("h5", "portal-h", "What to do"));
    const ol = el("ol", "ask-steps");
    ask.steps.forEach((t) => ol.appendChild(el("li", "", t)));
    box.appendChild(ol);
  } else {
    box.appendChild(el("p", "", s.message
      || "Handle it in the open browser window; it will carry on by itself."));
  }
  if (/^Still waiting/.test(s.message || "")) box.appendChild(el("p", "warn-text", s.message.split(". ")[0] + "."));
  box.appendChild(el("p", "muted", (ask.then || "It continues the moment the page clears.")
    + " Press “I've handled it” if it doesn't notice, or Stop to leave this one."));
  if (ask.why) box.appendChild(el("p", "muted small", "Why it can't do this itself: " + ask.why));
  const bar = el("div", "actions");
  const go = el("button", "btn primary sm", "I've handled it, continue");
  go.addEventListener("click", () => busy(go, "Carrying on…", async () => {
    await api("/api/jobs/portal/continue", { key: r.key });
  }));
  const stop = el("button", "btn sm ghost danger", "Stop");
  stop.addEventListener("click", () => busy(stop, "Stopping…", async () => {
    await api("/api/jobs/portal/cancel", { key: r.key });
  }));
  bar.append(go, stop);
  if (window.Notification && Notification.permission === "default") {
    const ping = el("button", "btn sm ghost", "Alert me on this computer next time");
    ping.addEventListener("click", () => Notification.requestPermission().then(() => ping.remove()));
    bar.appendChild(ping);
  }
  box.appendChild(bar);
  const d = $("#roleDetail");
  const was = d.querySelector(".portal-out");
  if (was) was.replaceWith(box); else d.appendChild(box);
  needsYouAlert(r.key, ask.headline || "Agent Jo Jobs needs you",
                (ask.steps || [])[1] || s.message || "");
}

/* Make sure a request for help is noticed: a toast, the tab title, and a
   system notification when you allowed them. Once per wait, not per refresh. */
function needsYouAlert(key, title, body) {
  const id = key + "|" + title;
  if (S._askedFor === id) return;
  S._askedFor = id;
  toast(title + ". The browser window is open.", "warn");
  if (!S._titleWas) S._titleWas = document.title;
  document.title = "(!) Needs you · " + S._titleWas;
  try {
    if (window.Notification && Notification.permission === "granted" && document.hidden !== false) {
      const n = new Notification(title, { body: body, tag: "agent-jo-jobs-needs-you" });
      n.onclick = () => { window.focus(); n.close(); };
    }
  } catch (e) { /* notifications are a nicety */ }
}

function clearNeedsYou() {
  S._askedFor = "";
  if (S._titleWas) { document.title = S._titleWas; S._titleWas = ""; }
}

// Who did each step of an application: a rule every site shares, something
// this site taught it before, the engine working it out, or your own answer.
const BY_SAYS = { rule: "rule", playbook: "learned", engine: "engine", saved: "yours" };

function portalTrail(host, x) {
  const steps = x.steps || [];
  if (steps.length) {
    const det = el("details", "trail");
    const n = steps.length;
    det.appendChild(el("summary", "", `What it did (${n} step${n === 1 ? "" : "s"})`));
    const ol = el("ol", "trail-steps");
    steps.forEach((s) => {
      const li = el("li", "trail-step" + (s.ok === false ? " is-off" : ""));
      li.append(el("span", "trail-by by-" + (s.by || "rule"), BY_SAYS[s.by] || s.by || "rule"),
                el("span", "", s.say || ""));
      ol.appendChild(li);
    });
    det.appendChild(ol);
    host.appendChild(det);
  }
  const learned = x.learned || [];
  if (learned.length) {
    const box = el("div", "learned");
    box.appendChild(el("h5", "portal-h", "What it learned for next time"));
    const ul = el("ul", "learned-list");
    learned.forEach((l) => ul.appendChild(el("li", "", l)));
    box.appendChild(ul);
    host.appendChild(box);
  }
}

function portalMeta(x) {
  const bits = [];
  if (x.explored) {
    const t = x.engine_turns || 0;
    bits.push(t ? `the engine was needed ${t} time${t === 1 ? "" : "s"}` : "no engine needed");
  }
  if (x.pages) bits.push(`${x.pages} page${x.pages === 1 ? "" : "s"} of form`);
  if (typeof x.filled === "number" && x.filled) bits.push(`${x.filled} box${x.filled === 1 ? "" : "es"} filled`);
  const s = bits.join(" · ");
  return s ? s[0].toUpperCase() + s.slice(1) : "";
}

function showPortal(x, r) {
  const d = $("#roleDetail");
  const out = el("div", "out portal-out");
  const state = x.state || (x.ok ? "filled" : "failed");
  const head = el("h4", "", {
    submitted: "Submitted through the portal",
    filled: "Filled in — check it and press submit yourself",
    needs_answer: "It needs answers it couldn't work out",
    unknown_form: "Part of this form is beyond it",
    needs_login: "This site wants you signed in",
    needs_captcha: "A captcha needs you",
    closed: "The advert says it's closed",
    apply_by_email: "This one wants an email, not a form",
    blocked: "The site blocked automation",
    failed: "Couldn't complete the form",
  }[state] || state);
  out.appendChild(head);
  if (x.message) out.appendChild(el("p", "muted", x.message));
  const meta = portalMeta(x);
  if (meta) out.appendChild(el("p", "portal-meta", meta));
  if (x.waited_for_you) {
    out.appendChild(el("p", "muted", x.waited_for_you === "needs_captcha"
      ? "Carried on after you solved the captcha."
      : "Carried on after you signed in."));
  }
  if (state === "apply_by_email" && x.apply_email) {
    out.appendChild(el("p", "", `The role now applies by email to ${x.apply_email}: the next run sends it, `
      + "through the same checks as every emailed application."));
  }
  if ((x.left || []).length) {
    out.appendChild(el("h5", "portal-h", "Left for you"));
    const ul = el("ul", "left-list");
    x.left.forEach((l) => ul.appendChild(el("li", "", l)));
    out.appendChild(ul);
  }
  portalTrail(out, x);
  S._portalNudged = false;

  const answers = x.answers || [];
  if (answers.length) {
    out.appendChild(el("h5", "portal-h", "Its answers"));
    answers.forEach((a) => {
      const row = el("div", "ans ans-" + (a.source || ""));
      const q = el("div", "ans-q", a.question);
      const tag = el("span", "tag " + (a.source === "engine" ? "sent"
        : a.source === "held" ? "held" : ""),
        a.source === "engine" ? "from your profile"
          : a.source === "held" ? "held — check this" : "blank");
      q.appendChild(tag);
      row.appendChild(q);
      if (a.answer) {
        row.appendChild(el("div", "ans-a", a.answer));
        const c = el("button", "btn sm ghost", "Copy");
        c.addEventListener("click", () => copyText(a.answer, c));
        row.appendChild(c);
      } else {
        row.appendChild(el("div", "muted", a.why || "you'll need to type this"));
      }
      out.appendChild(row);
    });
  }

  if (x.paste_pack) {
    const bar = el("div", "actions");
    const all = el("button", "btn primary sm", "Copy everything");
    all.title = "Every field and answer, ready to paste into the form";
    all.addEventListener("click", () => copyText(x.paste_pack, all));
    bar.appendChild(all);
    if (r && r.url) {
      const open = el("button", "btn sm", "Open the form");
      open.addEventListener("click", () => window.open(r.url, "_blank", "noopener"));
      bar.appendChild(open);
    }
    out.appendChild(bar);
    const pre = el("pre", "paste-pack");
    pre.textContent = x.paste_pack;
    out.appendChild(pre);
  }
  const host = d.querySelector(".portal-out");
  if (host) host.replaceWith(out); else d.appendChild(out);
}

function fact(k, v, hi) {
  const w = el("div");
  w.append(el("div", "fact-k", k), el("div", "fact-v" + (hi ? " hi" : ""), v));
  return w;
}

/* --- a designed CV: look, format, language --------------------------------- */
let RESUME_OPTS = null;
function resumePicker(key) {
  const box = el("div", "resume-pick");
  const tpl = el("select", "select"), fmt = el("select", "select"), lang = el("select", "select");
  [["pdf", "PDF"], ["docx", "Word (.docx)"]].forEach(([v, t]) => { const o = el("option", "", t); o.value = v; fmt.appendChild(o); });
  const fill = (o) => {
    Object.entries(o.templates || {}).forEach(([v, t]) => { const x = el("option", "", t); x.value = v; tpl.appendChild(x); });
    (o.languages || ["English"]).forEach((l) => { const x = el("option", "", l); x.value = l; lang.appendChild(x); });
  };
  if (RESUME_OPTS) fill(RESUME_OPTS);
  else api("/api/jobs/resume/options").then((o) => { RESUME_OPTS = o; fill(o); }).catch(() => {});
  const lab = (t, c) => { const l = el("label", "resume-field"); l.append(el("span", "muted", t), c); return l; };
  const go = el("button", "btn primary", "Make it");
  const note = el("p", "muted", key
    ? "Uses this role's tailored CV if you've made one, otherwise your own CV, restyled. One column, real text — safe for the software that reads CVs first."
    : "Your own CV, restyled — nothing reworded. One column, real text — safe for the software that reads CVs first.");
  go.addEventListener("click", () => busy(go, lang.value !== "English" ? "Translating…" : "Making…", async () => {
    const x = await api("/api/jobs/resume", withEngine({ key: key || "", template: tpl.value,
                                                         format: fmt.value, language: lang.value }));
    window.location.href = x.url;
    toast(`Made ${x.filename}` + (x.source ? ` from ${x.source}.` : "."));
  }));
  box.append(note, lab("Look", tpl), lab("Format", fmt), lab("Language", lang), go);
  return box;
}

/* --- people -------------------------------------------------------------- */
function personRow(c, compact) {
  const row = el("div", "item static person");
  const body = el("div");
  body.append(el("div", "item-t", c.name || c.email),
              el("div", "item-m", [c.kind === "person" ? "" : c.kind, (c.companies || []).join(", "),
                                   c.last ? `last heard ${c.last.slice(0, 10)}` : ""]
                                   .filter(Boolean).join(" · ")));
  if (!compact) {
    const what = Object.entries(c.kinds || {}).map(([k, n]) => `${n} ${k}`).join(", ");
    if (what) body.appendChild(el("div", "item-m", what +
      ((c.roles || []).length ? " — about " + c.roles.slice(0, 3).map((r) => r.title).join(", ") : "")));
    if (c.notes) body.appendChild(el("div", "item-m person-notes", c.notes));
  }
  const acts = el("div", "actions");
  acts.style.margin = "0";
  const mail = el("button", "btn sm", "Write");
  mail.title = "Opens your own mail app — nothing is sent from here";
  mail.addEventListener("click", async () => {
    window.location.href = "mailto:" + encodeURIComponent(c.email);
    try { await api("/api/jobs/people/update", { email: c.email, touched: true }); } catch (e) {}
  });
  const note = el("button", "btn sm ghost", "Notes");
  note.addEventListener("click", async () => {
    const v = prompt(`Notes on ${c.name || c.email}`, c.notes || "");
    if (v === null) return;
    await api("/api/jobs/people/update", { email: c.email, notes: v });
    LOADERS.people();
  });
  const done = el("button", "btn sm ghost", c.done ? "Remind me again" : "Done with them");
  done.title = "Stops them showing under 'worth getting back to'";
  done.addEventListener("click", async () => {
    await api("/api/jobs/people/update", { email: c.email, done: !c.done });
    LOADERS.people();
  });
  acts.append(mail, note, done);
  if (!compact) {
    const rm = el("button", "btn sm ghost danger", "Remove");
    rm.addEventListener("click", async () => {
      if (!confirm(`Remove ${c.name || c.email}?`)) return;
      await api("/api/jobs/people/remove", { email: c.email });
      LOADERS.people();
    });
    acts.appendChild(rm);
  }
  row.append(el("div", "mono", initial(c.name || c.email)), body, acts);
  return row;
}

LOADERS.people = async function () {
  let d = {};
  try { d = await api("/api/jobs/people"); }
  catch (e) { empty($("#peopleList"), "Couldn't load", e.message); return; }
  const ppl = d.people || [];
  $("#nPeople").textContent = ppl.length || "";
  const back = d.get_back_to || [];
  $("#peopleBackCard").hidden = !back.length;
  const bh = $("#peopleBack"); bh.innerHTML = "";
  back.slice(0, 6).forEach((c) => {
    const r = personRow(c, true);
    r.querySelector(".item-m").textContent += ` · ${c.days} days quiet`;
    bh.appendChild(r);
  });
  const host = $("#peopleList");
  host.innerHTML = "";
  if (!ppl.length) {
    empty(host, "No one yet", " When someone replies to an application (Results → inbox), " +
      "they appear here. You can also add someone you met or were referred to.");
    return;
  }
  ppl.forEach((c) => host.appendChild(personRow(c, false)));
};

function wirePeople() {
  const s = $("#pSync"), a = $("#pAdd");
  if (!s || s.dataset.wired) return;
  s.dataset.wired = "1";
  s.addEventListener("click", () => busy(s, "Gathering…", async () => {
    const r = await api("/api/jobs/people/sync", {});
    toast(`${r.people} people` + (r.added ? `, ${r.added} new` : "") +
          (r.flagged ? ` — ${r.flagged} role(s) at companies where you know someone.` : "."));
    await refresh(); LOADERS.people();
  }));
  a.addEventListener("click", async () => {
    const email = prompt("Their email address");
    if (!email) return;
    const name = prompt("Their name", "") || "";
    const company = prompt("Where they work (or recruit for)", "") || "";
    const notes = prompt("How you know them (optional)", "") || "";
    try {
      await api("/api/jobs/people", { email, name, company, notes });
      toast("Added."); await refresh(); LOADERS.people();
    } catch (e) { toast(e.message, "bad"); }
  });
}
document.addEventListener("DOMContentLoaded", wirePeople);

// on a role: who you know there, and a note to them
function knowBox(r) {
  const box = el("div", "out know-box");
  box.appendChild(el("h4", "", "You know someone here"));
  (r.know || []).forEach((k) => {
    const row = el("div", "know-row");
    row.appendChild(el("p", "", `${k.name} — ${k.kind}` + (k.about ? `, about ${k.about}` : "") +
                                (k.last ? ` (last heard ${k.last})` : "")));
    const b = el("button", "btn sm primary", "Draft a note to them");
    b.addEventListener("click", () => busy(b, "Drafting…", async () => {
      const x = await api("/api/jobs/people/note", withEngine({ key: r.key, email: k.email }));
      await refresh();
      openRole((S.roles || []).find((y) => y.key === r.key) || r);
      if ((x.note.check || {}).ok === false) toast("Drafted, but it claims something to check.", "bad");
    }));
    row.appendChild(b);
    box.appendChild(row);
  });
  const n = r.contact_note;
  if (n && n.body) {
    box.appendChild(el("h5", "", `Note to ${n.name || n.to}: ${n.subject || ""}`));
    if ((n.check || {}).ok === false) {
      const ul = el("ul");
      (n.check.problems || []).forEach((p) => ul.appendChild(el("li", "claim", p.detail || String(p))));
      box.appendChild(ul);
    }
    box.appendChild(el("pre", "", n.body));
    const send = el("button", "btn sm", "Open in my mail app");
    send.title = "Your mail app opens with this filled in; you press send";
    send.addEventListener("click", async () => {
      window.location.href = `mailto:${encodeURIComponent(n.to)}?subject=${encodeURIComponent(n.subject || "")}` +
        `&body=${encodeURIComponent(n.body)}`;
      try { await api("/api/jobs/people/update", { email: n.to, touched: true }); } catch (e) {}
    });
    box.appendChild(send);
  }
  return box;
}

/* --- editing a draft ---------------------------------------------------- */
// Your edit becomes the draft, is checked again, and is learned from: phrases
// you keep cutting stop being written (agent/style.py).
function draftEditor(host, key, dr, onSaved) {
  host.innerHTML = "";
  const subj = el("input", "input");
  subj.value = dr.subject || ""; subj.placeholder = "Subject";
  const ta = el("textarea", "input draft-edit");
  ta.value = dr.body || "";
  const meta = el("div", "muted mock-meta");
  const count = () => { meta.textContent = `${ta.value.trim().split(/\s+/).filter(Boolean).length} words`; };
  ta.addEventListener("input", count); count();
  const row = el("div", "actions");
  const save = el("button", "btn primary sm", "Save my version");
  save.addEventListener("click", () => busy(save, "Saving…", async () => {
    const x = await api("/api/jobs/draft/save", { key, subject: subj.value, body: ta.value });
    const ok = ((x.draft || {}).check || {}).ok !== false;
    toast(ok ? (x.learned ? "Saved — and noted how you changed it." : "Saved.")
             : "Saved, but it still claims something your profile can't back.", ok ? "" : "bad");
    await refresh(); railCounts();
    if (onSaved) onSaved(x.draft);
  }));
  const cancel = el("button", "btn sm ghost", "Cancel");
  cancel.addEventListener("click", () => onSaved && onSaved(null));
  row.append(save, cancel);
  host.append(subj, ta, meta, row);
  ta.focus();
}

async function drawStyle() {
  const host = $("#styleBody");
  if (!host) return;
  let s = {};
  try { s = await api("/api/jobs/style"); } catch (e) { host.textContent = "Couldn't read it."; return; }
  host.innerHTML = "";
  host.appendChild(el("p", "lede", s.edits
    ? `Learned from ${s.edits} draft(s) you edited. A rule needs ${s.needs} edits agreeing; ` +
      "new drafts and follow-ups follow these. They never let a draft claim more."
    : "Edit a draft before you send it (open a role → the draft → Edit) and the changes you " +
      "keep making become rules here — phrases you always cut, how long you like it, your sign-off."));
  (s.rules || []).forEach((r) => {
    const row = el("div", "item static style-rule");
    const t = el("div"); t.append(el("div", "item-t", r.text));
    const f = el("button", "btn sm ghost", "Forget");
    f.addEventListener("click", () => busy(f, "…", async () => {
      await api("/api/jobs/style/forget", { id: r.id }); drawStyle();
    }));
    row.append(el("span", "tag", r.kind), t, f);
    host.appendChild(row);
  });
  if (s.edits) {
    const reset = el("button", "btn sm ghost", "Forget all of it");
    reset.addEventListener("click", () => {
      if (!confirm("Forget every edit and rule it learned?")) return;
      busy(reset, "…", async () => { await api("/api/jobs/style/reset", {}); drawStyle(); });
    });
    host.appendChild(reset);
  }
}

/* --- practice interview ------------------------------------------------ */
// One question at a time, typed or dictated; feedback after each; a summary
// at the end. Speech is the browser's own: reading aloud happens on this
// machine; dictation in Chrome and Edge is turned into text by Google's or
// Microsoft's speech service, so the window says so. This app keeps no audio.
const SPEECH_REC = window.SpeechRecognition || window.webkitSpeechRecognition;

async function openMock(r) {
  const wrap = el("div", "mock-wrap");
  const box = el("div", "mock");
  wrap.appendChild(box);
  const close = () => { try { speechSynthesis.cancel(); } catch (e) {} stopDictation(); wrap.remove(); };
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  document.addEventListener("keydown", function esc(e) {
    if (e.key === "Escape" && document.body.contains(wrap)) { close(); document.removeEventListener("keydown", esc); }
  });
  document.body.appendChild(wrap);
  let speak = false, rec = null;
  function stopDictation() { try { rec && rec.stop(); } catch (e) {} rec = null; }
  const say = (t) => {
    if (!speak || !window.speechSynthesis) return;
    speechSynthesis.cancel();
    speechSynthesis.speak(new SpeechSynthesisUtterance(t));
  };

  const head = (sub) => {
    box.innerHTML = "";
    const h = el("div", "mock-head");
    h.append(el("div", "", ""), el("button", "btn sm ghost", "Close"));
    h.children[0].append(el("h3", "", "Practice interview"),
                         el("div", "muted", `${r.title || ""} @ ${r.company || ""}` + (sub ? " · " + sub : "")));
    h.children[1].addEventListener("click", close);
    box.appendChild(h);
  };

  // the start page: history, and what this is
  head("");
  let st = {};
  try { st = await api("/api/jobs/mock?key=" + encodeURIComponent(r.key)); } catch (e) {}
  box.appendChild(el("p", "", "One question at a time, as in the room. Answer out loud or type — " +
    "after each answer you get a score, the one thing to change, and a stronger version built " +
    "only from your CV. Claims your CV can't back are flagged: that's what they'll check."));
  const hist = (st.history || []).filter((h) => h.average != null);
  if (hist.length) box.appendChild(el("p", "muted", "Your last attempts: " +
    hist.slice(-5).map((h) => `${h.average}/5 (${h.at.slice(0, 10)})`).join(" → ")));
  const opts = el("label", "mock-opt");
  const cb = el("input"); cb.type = "checkbox";
  opts.append(cb, document.createTextNode(" Read the questions aloud"));
  if (window.speechSynthesis) box.appendChild(opts);
  const go = el("button", "btn primary", st.current ? "Start again" : "Start");
  box.appendChild(go);
  go.addEventListener("click", () => busy(go, "Preparing questions…", async () => {
    speak = cb.checked;
    const q = await api("/api/jobs/mock/start", withEngine({ key: r.key }));
    ask(q);
  }));

  function ask(q) {
    head(`question ${q.number} of ${q.of}`);
    const bar = el("div", "mock-bar"); const fill = el("i");
    fill.style.width = `${Math.round(100 * (q.number - 1) / q.of)}%`;
    bar.appendChild(fill); box.appendChild(bar);
    box.appendChild(el("div", "mock-q", q.question));
    say(q.question);
    const ta = el("textarea", "input mock-a");
    ta.placeholder = "Your answer — as you'd say it. About a minute.";
    box.appendChild(ta);
    const meta = el("div", "muted mock-meta", "0 words");
    ta.addEventListener("input", () => {
      const n = ta.value.trim() ? ta.value.trim().split(/\s+/).length : 0;
      meta.textContent = `${n} words · about ${Math.max(1, Math.round(n / 130 * 60))}s spoken`;
    });
    box.appendChild(meta);
    const row = el("div", "actions");
    if (SPEECH_REC) {
      const mic = el("button", "btn sm", "🎙 Dictate");
      mic.addEventListener("click", () => {
        if (rec) { stopDictation(); mic.textContent = "🎙 Dictate"; return; }
        rec = new SPEECH_REC(); rec.continuous = true; rec.interimResults = false;
        rec.lang = navigator.language || "en-ZA";
        rec.onresult = (e) => {
          for (let i = e.resultIndex; i < e.results.length; i++)
            if (e.results[i].isFinal) ta.value += (ta.value && !/\s$/.test(ta.value) ? " " : "") + e.results[i][0].transcript.trim();
          ta.dispatchEvent(new Event("input"));
        };
        rec.onend = () => { rec = null; mic.textContent = "🎙 Dictate"; };
        rec.onerror = (e) => toast("Dictation: " + (e.error || "stopped") +
          (e.error === "not-allowed" ? " — allow the microphone for this page." : ""), "bad");
        try { rec.start(); mic.textContent = "■ Stop"; } catch (e) { toast(e.message, "bad"); }
      });
      row.appendChild(mic);
      mic.title = "Your browser turns speech into text — in Chrome and Edge that goes through " +
        "Google's or Microsoft's speech service. Type instead if you'd rather it didn't.";
    }
    const send = el("button", "btn primary", "Done — feedback");
    send.addEventListener("click", () => busy(send, "Listening back…", async () => {
      stopDictation();
      const x = await api("/api/jobs/mock/answer", withEngine({ key: r.key, text: ta.value }));
      feedback(x);
    }));
    const end = el("button", "btn sm ghost", "End here");
    end.addEventListener("click", () => busy(end, "…", summary));
    row.append(send, end);
    box.appendChild(row);
    ta.focus();
  }

  function feedback(x) {
    head(x.done ? "last answer" : `next: ${x.number} of ${x.of}`);
    box.appendChild(el("div", "mock-q small", x.question_answered));
    const fb = x.feedback || {}, lc = x.local || {};
    const sc = fb.score != null ? fb.score : fb.local_score;
    const badge = el("div", "mock-score s" + (sc || 0), sc != null ? `${sc}/5` : "—");
    if (fb.score == null) badge.title = "A rough score from the checks below — connect an engine for a full read.";
    box.appendChild(badge);
    if (fb.error) box.appendChild(el("p", "muted", fb.error));
    else if (fb.score == null) box.appendChild(el("p", "muted",
      "A rough score from the checks below — choose an engine for a full read and a stronger version."));
    if (fb.worked) { box.appendChild(el("h5", "", "What worked")); box.appendChild(el("p", "", fb.worked)); }
    if (fb.fix) { box.appendChild(el("h5", "", "Change this")); box.appendChild(el("p", "mock-fix", fb.fix)); }
    const checks = el("ul", "mock-checks");
    [["A concrete example", lc.example], ["A result or a number", lc.result]].forEach(([t, ok]) =>
      checks.appendChild(el("li", ok ? "ok" : "no", (ok ? "✓ " : "✗ ") + t)));
    (lc.notes || []).filter((n) => !/^No (concrete|result)/.test(n))
      .forEach((n) => checks.appendChild(el("li", "no", "• " + n)));
    (lc.claims || []).forEach((c) => checks.appendChild(el("li", "claim", "⚠ " + c)));
    box.appendChild(checks);
    if (fb.better) {
      const d = el("details", "mock-better");
      d.appendChild(el("summary", "", "A stronger version, from your CV"));
      d.appendChild(el("p", "", fb.better));
      (fb.better_flags || []).forEach((f) => d.appendChild(el("p", "prep-gap", "Check: " + f)));
      box.appendChild(d);
    }
    const row = el("div", "actions");
    if (!x.done) {
      const nx = el("button", "btn primary", "Next question");
      nx.addEventListener("click", () => ask(x));
      row.appendChild(nx);
      const end = el("button", "btn sm ghost", "End here");
      end.addEventListener("click", () => busy(end, "…", summary));
      row.appendChild(end);
    } else {
      const sm = el("button", "btn primary", "See how it went");
      sm.addEventListener("click", () => busy(sm, "…", summary));
      row.appendChild(sm);
    }
    box.appendChild(row);
  }

  async function summary() {
    stopDictation();
    const s = await api("/api/jobs/mock/finish", { key: r.key });
    head("summary");
    box.appendChild(el("div", "mock-score big s" + Math.round(s.average || 0),
                       s.average != null ? `${s.average}/5` : "—"));
    let line = `${s.answered} of ${s.of} questions answered.`;
    if (s.change != null) line += s.change > 0 ? ` Up ${s.change} on last time (${s.last_average}).`
      : s.change < 0 ? ` Down ${-s.change} on last time (${s.last_average}).` : " Same as last time.";
    if (s.scale === "local") line += " Scored by the local checks only — connect an engine for full feedback.";
    box.appendChild(el("p", "", line));
    if ((s.work_on || []).length) {
      box.appendChild(el("h5", "", "Work on these"));
      const ul = el("ul");
      s.work_on.forEach((w) => {
        const li = el("li");
        li.append(el("b", "", `${w.score}/5 — ${w.question}`), el("div", "muted", w.fix || ""));
        ul.appendChild(li);
      });
      box.appendChild(ul);
    } else box.appendChild(el("p", "", "Nothing below a 4. Practise once more the day before."));
    if ((s.claims || []).length) {
      box.appendChild(el("h5", "", "Said, but not in your CV"));
      const ul = el("ul");
      s.claims.forEach((c) => ul.appendChild(el("li", "claim", c)));
      box.appendChild(ul);
    }
    const row = el("div", "actions");
    const again = el("button", "btn primary", "Practise again");
    again.addEventListener("click", () => busy(again, "Preparing…", async () =>
      ask(await api("/api/jobs/mock/start", withEngine({ key: r.key })))));
    const done = el("button", "btn sm ghost", "Close");
    done.addEventListener("click", close);
    row.append(again, done);
    box.appendChild(row);
  }
}

// "2026-10-14 10:00" → "Tue 14 Oct, 10:00"
function whenText(at) {
  const d = new Date(String(at || "").replace(" ", "T"));
  if (isNaN(d)) return at || "";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })
    + ", " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

// the interview's time — read from the invitation or set by you — and a
// calendar file with the prep in its notes
function interviewBox(r) {
  const box = el("div", "out interview-when");
  const at = r.interview_at;
  box.appendChild(el("h4", "", at ? "Interview: " + whenText(at) : "When is the interview?"));
  if (at && r.interview_said)
    box.appendChild(el("p", "muted", `Read from the invitation: “${r.interview_said}”`));
  if (r.interview_tz_note) box.appendChild(el("p", "prep-gap", r.interview_tz_note));
  if (!at) box.appendChild(el("p", "muted",
    "The invitation didn't give one clear time. Set it once it's agreed."));
  const a = el("div", "actions");
  if (r.interview_link) {
    const j = el("button", "btn sm", "Open the meeting link");
    j.addEventListener("click", () => window.open(r.interview_link, "_blank", "noopener"));
    a.appendChild(j);
  }
  if (at) {
    const c = el("button", "btn sm primary", "Add to calendar");
    c.addEventListener("click", () => {
      window.location.href = "/api/jobs/interview.ics?key=" + encodeURIComponent(r.key);
    });
    a.appendChild(c);
  }
  const brief = el("button", "btn sm", "One-page brief (PDF)");
  brief.title = "Your best stories, the gaps, who you know there and what to ask — to read before the call";
  brief.addEventListener("click", () => busy(brief, "Making…", async () => {
    const x = await api("/api/jobs/brief", { key: r.key });
    window.location.href = x.url;
  }));
  a.appendChild(brief);
  const set = el("button", "btn sm", at ? "Change the time" : "Set the time");
  set.addEventListener("click", async () => {
    const v = prompt("Interview time (YYYY-MM-DD HH:MM) — leave empty to clear",
                     at || new Date().toISOString().slice(0, 10) + " 10:00");
    if (v === null) return;
    const link = prompt("Meeting link (optional)", r.interview_link || "");
    try {
      await api("/api/jobs/interview-time", { key: r.key, at: v.trim(), link: (link || "").trim() });
      await refresh();
      openRole((S.roles || []).find((y) => y.key === r.key) || r);
    } catch (e) { toast(e.message || String(e)); }
  });
  a.appendChild(set);
  box.appendChild(a);
  return box;
}

// questions, the answer your CV gives, and the gaps to think about first
function prepView(x) {
  const box = el("div", "prep");
  const qs = (x && x.questions) || [];
  if (!qs.length) { box.appendChild(el("p", "muted", "No questions came back.")); return box; }
  const gaps = qs.filter((q) => (q.gap || "").trim()).length;
  box.appendChild(el("p", "muted", `${qs.length} likely question(s)` +
    (gaps ? ` — ${gaps} with nothing in your CV to draw on: think about those first.` : ".")));
  qs.forEach((q) => {
    const it = el("details", "prep-q");
    it.appendChild(el("summary", "", q.question || String(q)));
    if (q.answer_from_profile) it.appendChild(el("p", "", q.answer_from_profile));
    if ((q.gap || "").trim()) it.appendChild(el("p", "prep-gap", "Gap: " + q.gap));
    box.appendChild(it);
  });
  if ((x.ask_them || []).length) {
    box.appendChild(el("h5", "", "Ask them"));
    const ul = el("ul");
    x.ask_them.forEach((a) => ul.appendChild(el("li", "", String(a))));
    box.appendChild(ul);
  }
  return box;
}

function openRole(r) {
  const d = $("#roleDetail");
  d.innerHTML = "";
  enterView(d);
  d.appendChild(el("p", "doc-kicker",
    [r.source, r.days_listed ? `${r.days_listed} days listed` : ""]
      .filter(Boolean).join(" · ") || "role"));
  d.appendChild(el("h1", "doc-title", r.title || "(untitled)"));
  d.appendChild(el("p", "doc-by", [r.company, r.location].filter(Boolean).join(" — ")));

  const f = fitOf(r);
  const facts = el("div", "doc-facts");
  // the bucket, not the raw stage: a role could read "STAGE found" directly
  // above "scored, not drafted yet", which is the same thing said two ways
  const BUCKET = {
    found: "not scored", screened: "screened out", scored: "scored",
    drafted: "drafted", held: "held", needs_redraft: "needs rewriting",
    no_address: "portal only", applied: "applied", waiting: "waiting",
    responded: "replied", interview: "interview", offer: "offer",
    closed: "closed", expired: "expired",
  };
  facts.append(
    fact("Fit", f === undefined || f === null ? "not scored" : `${f}`, f >= 75),
    fact("Stage", BUCKET[r.bucket] || r.bucket || r.stage || "found"),
    fact("Apply by", r.apply_email ? "email" : "portal"));
  d.appendChild(facts);
  if (r.state_why) d.appendChild(el("p", "muted", r.state_why));
  if ((r.must_missing || []).length)
    d.appendChild(el("p", "prep-gap", "Doesn't mention your must-haves: " + r.must_missing.join(", ") + " — worth asking."));
  if (r.summary) d.appendChild(el("div", "doc-body", r.summary));

  const out = el("div");
  // Highlight the next sensible step, not always the first button. "Score
  // it" glowing on a role that's scored and already applied told you to do
  // something you'd done.
  // keyed on the state, not the raw stage — a held draft was being told to
  // mark itself applied
  const nextStep = {
    found: "Score it", screened: "Score it", scored: "Draft the application",
    drafted: r.apply_email ? "I applied myself" : "Apply via the portal (rehearse)",
    held: "Draft the application", needs_redraft: "Draft the application",
    no_address: "Apply via the portal (rehearse)",
    applied: "Draft a follow-up", waiting: "Draft a follow-up",
    responded: "Interview prep", interview: "Practise the interview",
  }[r.bucket || r.stage || "found"];
  const group = (title, buttons) => {
    const g = el("div", "actions-group");
    g.appendChild(el("h5", "", title));
    const a = el("div", "actions");
    buttons.forEach(([label, fn, cls]) => {
      const c2 = label === nextStep ? "primary"
        : (cls === "primary" ? "" : cls);
      const b = el("button", "btn sm" + (c2 ? " " + c2 : ""), label);
      b.addEventListener("click", () => fn(b));
      a.appendChild(b);
    });
    g.appendChild(a);
    d.appendChild(g);
  };
  const show = (title, content) => {
    out.innerHTML = "";
    const box = el("div", "out");
    box.appendChild(el("h4", "", title));
    if (typeof content === "string") box.appendChild(el("pre", "", content));
    else box.appendChild(content);
    out.appendChild(box);
  };
  const act = (path, label, render) => async (btn) => busy(btn, label, async () => {
    const res = await api(path, withEngine({ key: r.key }));
    render(res);
    await refresh(); railCounts(); drawRoleList();
  });

  group("Decide", [
    ["Score it", act("/api/jobs/score", "Scoring…", (x) =>
      show(`Fit ${((x.fit || x).score) ?? "—"}`,
           (x.fit || x).why || (x.fit || x).reason || "Scored.")), "primary"],
    ["ATS check", act("/api/jobs/ats", "Checking…", (x) => {
      const box = el("div");
      box.appendChild(el("p", "", `${x.score ?? "—"}% of the advert's terms appear in your profile.`));
      if ((x.missing || []).length) {
        box.appendChild(el("p", "muted", "Missing:"));
        const ul = el("ul");
        x.missing.slice(0, 12).forEach((m) => ul.appendChild(el("li", "", String(m))));
        box.appendChild(ul);
      }
      show("Keyword match", box);
    })],
    ["Open the posting", () => { if (r.url) window.open(r.url, "_blank", "noopener"); }],
  ]);

  group("Prepare", [
    ["Draft the application", act("/api/jobs/draft", "Drafting…", (x) => {
      const dr = x.draft || x;
      const ok = (dr.check || {}).ok !== false;
      show(ok ? (dr.subject || "Draft") : "Held — it claims too much",
           ok ? (dr.body || "") :
           ((dr.check || {}).problems || []).map((p) => "• " + (p.detail || p)).join("\n")
             + "\n\n" + (dr.body || ""));
    })],
    ["Tailor my CV", act("/api/jobs/cv", "Tailoring…", (x) =>
      show("Tailored CV", (x.text || x.cv || "") + (x.path ? `\n\nSaved to ${x.path}` : "")))],
    ["Interview prep", act("/api/jobs/interview", "Preparing…", (x) =>
      show("Interview prep", prepView(x)))],
    ["Practise the interview", () => openMock(r)],
    ["Designed CV (PDF / Word)", () => show("Designed CV", resumePicker(r.key))],
    ["Save to a file", act("/api/jobs/save-file", "Saving…", (x) =>
      show("Saved", x.path || "Written."))],
  ]);

  group("Apply", [
    // the companion lives in a window this app opens — it can't appear in
    // your own browser, which is the usual reason for "I can't see it"
    ["Open the form with help", async (btn) => busy(btn, "Opening…", async () => {
      const x = await api("/api/jobs/portal/helper",
                          withEngine({ key: r.key }));
      followPortal(r, "help:" + r.key);
      toast("Opening the form with the helper in it — hover any field.");
    })],
    ["Apply via the portal (rehearse)", async (btn) => busy(btn, "Opening…", async () => {
      await api("/api/jobs/portal", withEngine({ key: r.key, submit: false }));
      followPortal(r);
    })],
    ["…and submit", async (btn) => {
      if (!confirm("Submit this application through the portal for real?")) return;
      busy(btn, "Submitting…", async () => {
        await api("/api/jobs/portal", withEngine({ key: r.key, submit: true }));
        followPortal(r);
      });
    }, "danger"],
    ["I applied myself", async (btn) => busy(btn, "Saving…", async () => {
      const note = prompt("How did you apply? (optional)", "") || "";
      await api("/api/jobs/applied", { key: r.key, how: "by hand", note });
      toast("Marked as applied — the follow-up clock has started.");
      await refresh(); drawRoleList();
    })],
    ["Draft a follow-up", act("/api/jobs/follow-up", "Drafting…", (x) =>
      show("Follow-up", x.body || x.text || ""))],
  ]);

  group("Track", [
    ...["responded", "interview", "offer", "closed"].map((st) =>
      [st[0].toUpperCase() + st.slice(1), async (btn) => busy(btn, "…", async () => {
        await api("/api/jobs/stage", { key: r.key, stage: st, note: "" });
        toast(`Moved to ${st}.`);
        await refresh(); drawRoleList();
        openRole(S.roles.find((x) => x.key === r.key) || r);
      })]),
    ["Remove", async (btn) => {
      if (!confirm("Remove this role?")) return;
      busy(btn, "Removing…", async () => {
        await api("/api/jobs/remove", { key: r.key });
        S.selected = null;
        await LOADERS.roles();
      });
    }, "danger"],
  ]);

  if ((r.know || []).length) d.appendChild(knowBox(r));
  if (r.interview_at || r.stage === "interview") d.appendChild(interviewBox(r));

  // prep made earlier — by you, or by the cycle when an invitation arrived
  if ((r.interview || {}).questions && (r.interview.questions || []).length) {
    const box = el("div", "out");
    box.appendChild(el("h4", "", "Interview prep"));
    box.appendChild(prepView(r.interview));
    d.appendChild(box);
  }

  // what the app already knows about this role, rather than empty space:
  // why it scored, what the draft says, and what has happened to it
  const why = (r.fit || {}).why || (r.fit || {}).reason;
  if (why) {
    const box = el("div", "out");
    box.appendChild(el("h4", "", "Why this score"));
    box.appendChild(el("pre", "", why));
    d.appendChild(box);
  }
  // its last go at this role's form: what it did there and what it learned
  const lp = r.portal || {};
  if ((lp.steps || []).length || (lp.learned || []).length) {
    const box = el("div", "out portal-last");
    box.appendChild(el("h4", "", "Its last go at the form" + (r.portal_at ? ` · ${r.portal_at}` : "")));
    if (lp.message) box.appendChild(el("p", "muted", lp.message));
    const meta = portalMeta(lp);
    if (meta) box.appendChild(el("p", "portal-meta", meta));
    portalTrail(box, lp);
    d.appendChild(box);
  }
  const dr = r.draft || {};
  if (dr.body) {
    const box = el("div", "out");
    const held = (dr.check || {}).ok === false;
    box.appendChild(el("h4", "", held ? "Draft — held" : (dr.subject || "The draft")));
    if (held) {
      const ul = el("ul");
      ((dr.check || {}).problems || []).forEach((p) =>
        ul.appendChild(el("li", "", p.detail || String(p))));
      box.appendChild(ul);
    }
    const q = dr.quality || {};
    if (q.score != null) {
      const qb = el("div", "quality q-" + (q.grade || ""));
      qb.appendChild(el("b", "", `Quality ${q.score}/100 — ${q.grade}`));
      if ((q.reasons || []).length) {
        const ul = el("ul");
        q.reasons.forEach((x) => ul.appendChild(el("li", "", x)));
        qb.appendChild(ul);
      } else if ((q.good || []).length) qb.appendChild(el("p", "muted", q.good.join(" ")));
      box.appendChild(qb);
    }
    const pre = el("pre", "", dr.body);
    box.appendChild(pre);
    if (dr.edited) box.appendChild(el("p", "muted", "Your version."));
    else if ((dr.learned_from || []).length) {
      box.appendChild(el("p", "muted", "Its tone and shape learned from your letters that got replies: "
        + dr.learned_from.join("; ") + "."));
    }
    const ed = el("button", "btn sm", "Edit");
    ed.addEventListener("click", () => {
      const host = el("div");
      box.replaceChild(host, pre); ed.remove();
      draftEditor(host, r.key, dr, () =>
        openRole((S.roles || []).find((y) => y.key === r.key) || r));
    });
    box.appendChild(ed);
    const tr = el("button", "btn sm ghost", "Translate");
    tr.addEventListener("click", () => {
      const lang = prompt("Translate the letter into which language?", "Afrikaans");
      if (!lang) return;
      busy(tr, "Translating…", async () => {
        const x = await api("/api/jobs/translate-letter", withEngine({ key: r.key, language: lang }));
        const t = el("div", "out");
        t.append(el("h4", "", `${x.language}: ${x.subject || ""}`), el("pre", "", x.body));
        box.after(t);
      });
    });
    box.appendChild(tr);
    Object.entries(r.draft_translations || {}).forEach(([lang, t]) => {
      const det = el("details", "mock-better");
      det.append(el("summary", "", `In ${lang}`), el("pre", "", (t.subject ? t.subject + "\n\n" : "") + t.body));
      box.appendChild(det);
    });
    d.appendChild(box);
  }
  const ev = r.events || [];
  if (ev.length) {
    const box = el("div", "out");
    box.appendChild(el("h4", "", "History"));
    ev.slice().reverse().slice(0, 8).forEach((e) => {
      const row = el("div", "hist");
      row.append(el("span", "hist-at", (e.at || "").replace(" UTC", "")),
                 el("span", "hist-t", e.stage + (e.note ? " — " + e.note : "")));
      box.appendChild(row);
    });
    d.appendChild(box);
  }

  d.appendChild(out);
}

/* --- search ------------------------------------------------------------ */
LOADERS.search = function () {
  $("#q").focus && $("#q").focus();
  drawResults();
};

const SR = { results: [], filter: "all" };

// what a result's state looks like, and what you can do about it
function resultState(r) {
  if (r.already_tracked) return "tracked";
  if (r.removed_before) return "removed";
  return "new";
}

async function runSearch() {
  const q = $("#q").value.trim();
  if (!q) return;
  const isUrl = /^https?:\/\//i.test(q);
  await busy($("#qGo"), isUrl ? "Reading…" : "Searching…", async () => {
    const d = isUrl
      ? await api("/api/jobs/search/url", { url: q, use_browser: $("#qBrowser").checked })
      : await api("/api/jobs/search", { query: q });
    SR.results = d.results || [];
    SR.searched = true;
    SR.note = d.note || d.detail || "";
    SR.filter = "all";
    drawResults();
  });
}

async function track(items, restore, btn) {
  // Sent as "items" — the route's field. It once went as "roles", the server
  // quietly ignored it, answered ok with nothing added, and the window
  // showed every role as tracked.
  const run = async () => {
    const x = await api("/api/jobs/search/add", { items, restore: !!restore });
    const byKey = {};
    (x.outcomes || []).forEach((o) => { byKey[o.key] = o.status; });
    SR.results.forEach((r) => {
      const s = byKey[r.key];
      if (s === "added" || s === "already tracked") {
        r.already_tracked = true; r.removed_before = false;
      }
    });
    const n = (x.outcomes || []).reduce((a, o) => {
      a[o.status] = (a[o.status] || 0) + 1; return a; }, {});
    const parts = [];
    if (n["added"]) parts.push(`Now tracking ${n["added"]}`);
    if (n["already tracked"]) parts.push(`${n["already tracked"]} already tracked`);
    if (n["removed earlier"]) parts.push(`${n["removed earlier"]} removed earlier — use Restore`);
    if (n["not a role"]) parts.push(`${n["not a role"]} didn't look like a real role`);
    toast(parts.join(" · ") || "Nothing changed.", n["added"] ? "" : "warn");
    await refresh();
    drawResults();
  };
  return btn ? busy(btn, restore ? "Restoring…" : "Tracking…", run) : run();
}

function drawResults() {
  const host = $("#results");
  host.innerHTML = "";
  const all = SR.results;
  if (!all.length) {
    empty(host, SR.searched ? "Nothing found" : "Search your sources",
          SR.searched ? (SR.note || "Try broader words.")
                      : "Type what you're after above, or paste a posting's address.");
    return;
  }
  const count = { all: all.length, new: 0, tracked: 0, removed: 0 };
  all.forEach((r) => { count[resultState(r)]++; });

  const bar = el("div", "result-bar");
  const sum = el("div", "result-sum");
  sum.innerHTML = `<b>${all.length}</b> found · <span class="t-new">${count.new} new</span>`
    + ` · <span class="t-tracked">${count.tracked} tracked</span>`
    + (count.removed ? ` · <span class="t-removed">${count.removed} removed earlier</span>` : "");
  bar.appendChild(sum);
  const chips = el("div", "chips");
  [["all", "All"], ["new", "New"], ["tracked", "Tracked"], ["removed", "Removed"]]
    .filter(([k]) => k === "all" || count[k])
    .forEach(([k, label]) => {
      const c = el("button", "chip" + (SR.filter === k ? " is-on" : ""), `${label} ${count[k]}`);
      c.addEventListener("click", () => { SR.filter = k; drawResults(); });
      chips.appendChild(c);
    });
  bar.appendChild(chips);
  if (count.new) {
    const fresh = all.filter((r) => resultState(r) === "new");
    const b = el("button", "btn primary sm", `Track ${count.new} new`);
    b.addEventListener("click", () => track(fresh, false, b));
    bar.appendChild(b);
  }
  host.appendChild(bar);

  // a tracked role may already have a fit score; a fresh result never does,
  // and it says so rather than showing a number nobody computed
  const fitByKey = {};
  S.roles.forEach((r) => { if (r.fit && r.fit.score != null) fitByKey[r.key] = r.fit.score; });

  const grid = el("div", "role-grid");
  all.filter((r) => SR.filter === "all" || resultState(r) === SR.filter).forEach((r) => {
    const st = resultState(r);
    const card = el("article", "role-card is-" + st);
    const head = el("div", "rc-head");
    const logo = el("div", "rc-logo", initial(r.company));
    const who = el("div", "rc-who");
    who.append(el("div", "rc-title", r.title || "(untitled)"),
               el("div", "rc-co", [r.company, r.location].filter(Boolean).join(" · ")));
    head.append(logo, who);
    card.appendChild(head);

    const score = fitByKey[r.key];
    const line = el("div", "rc-line");
    const match = el("span", "rc-match" + (score == null ? " none" : score >= 75 ? " hi" : ""),
                     score == null ? "Not scored" : `${score}% Match`);
    const tag = el("span", "tag " + (st === "tracked" ? "sent" : st === "removed" ? "held" : "new"),
                   st === "tracked" ? "Tracked" : st === "removed" ? "Removed earlier" : "New");
    line.append(match, tag);
    card.appendChild(line);
    card.appendChild(el("p", "rc-desc", (r.summary || r.source || "").slice(0, 220)));

    const acts = el("div", "rc-acts");
    const add = (label, cls, fn) => {
      const b = el("button", "btn sm" + (cls ? " " + cls : ""), label);
      b.addEventListener("click", () => fn(b));
      acts.appendChild(b);
    };
    if (st === "new") {
      add("Track", "primary", (b) => track([r], false, b));
    } else if (st === "removed") {
      add("Restore", "", (b) => track([r], true, b));
    } else {
      add("Analyze", "primary", (b) => busy(b, "Scoring…", async () => {
        await api("/api/jobs/score", withEngine({ key: r.key }));
        await refresh(); drawResults();
        toast("Scored.");
      }));
      add("Open", "", () => { S.selected = r.key; show("roles"); });
    }
    if (r.url) add("Posting", "ghost", () => window.open(r.url, "_blank", "noopener"));
    card.appendChild(acts);
    grid.appendChild(card);
  });
  host.appendChild(grid);
}


/* --- drafts and claims ------------------------------------------------- */
LOADERS.drafts = async function () {
  let d = {};
  try { d = await api("/api/jobs/claims", undefined, "GET"); }
  catch (e) { empty($("#heldList"), "Couldn't load", e.message); return; }

  const held = d.held || [];
  $("#nDrafts").textContent = held.length || "";
  const hl = $("#heldList");
  hl.innerHTML = "";
  if (!held.length) empty(hl, "Nothing held", "Every draft so far stands on your profile.");
  held.forEach((h) => {
    const it = el("div", "item");
    const body = el("div");
    body.append(el("div", "item-t", h.title || "(untitled)"),
      el("div", "item-m", `${(h.problems || []).length} claim(s) — ${h.company || ""}`));
    it.append(el("div", "mono", initial(h.company)), body, el("span", "tag held", "held"));
    it.addEventListener("click", () => {
      $$("#heldList .item").forEach((x) => x.classList.remove("is-on"));
      it.classList.add("is-on");
      showDraft(h);
    });
    hl.appendChild(it);
  });

  const cl = $("#claimList");
  cl.innerHTML = "";
  const claims = d.claims || [];
  if (!claims.length) empty(cl, "No repeat claims", "");
  claims.forEach((c) => {
    const it = el("div", "item static");
    const body = el("div");
    body.append(el("div", "item-t", c.term || c.detail || "claim"),
      el("div", "item-m", `${(c.roles || []).length} draft(s) · ${c.kind || ""}`));
    const acts = el("div", "actions");
    acts.style.margin = "0";
    const yes = el("button", "btn sm", "It's true");
    yes.addEventListener("click", () => busy(yes, "…", async () => {
      await api("/api/jobs/claims/confirm", { term: c.term, where: c.kind || "skills" });
      toast(`Added "${c.term}" to your profile.`);
      LOADERS.drafts();
    }));
    const no = el("button", "btn sm ghost", "Dismiss");
    no.addEventListener("click", () => busy(no, "…", async () => {
      await api("/api/jobs/claims/dismiss", { term: c.term, where: c.kind || "" });
      toast(`Drafts will stop claiming "${c.term}".`);
      LOADERS.drafts();
    }));
    acts.append(yes, no);
    it.append(el("div", "mono", "?"), body, acts);
    cl.appendChild(it);
  });

  const dd = $("#draftDetail");
  // with drafts held and none open, the pane was simply blank
  if (!held.length || !dd.firstChild || dd.querySelector(".placeholder")) {
    dd.innerHTML = "";
    const p = el("div", "placeholder");
    const i = el("div");
    i.append(el("b", "", held.length ? "Pick a draft" : "Nothing to review"),
             el("div", "", held.length
               ? "Read what it claims, then redraft it or let it go."
               : "Held drafts open here."));
    p.appendChild(i);
    dd.appendChild(p);
  }
};

function showDraft(h) {
  const d = $("#draftDetail");
  d.innerHTML = "";
  enterView(d);
  d.appendChild(el("p", "doc-kicker", "held draft"));
  d.appendChild(el("h1", "doc-title", h.title || "Draft"));
  d.appendChild(el("p", "doc-by", h.company || ""));
  const why = el("div", "out");
  why.appendChild(el("h4", "", "Why it was held"));
  const ul = el("ul");
  // problems arrive as plain strings — reading them as objects showed nothing
  (h.problems || []).forEach((p) => ul.appendChild(el("li", "", String(p))));
  why.appendChild(ul);
  if (h.redraft_reason) why.appendChild(el("p", "muted", h.redraft_reason));
  d.appendChild(why);
  if (h.body) {
    const b = el("div", "out");
    b.appendChild(el("h4", "", h.subject || "The draft"));
    const pre = el("pre", "", h.body);
    b.appendChild(pre);
    const ed = el("button", "btn sm", "Edit it myself");
    ed.addEventListener("click", () => {
      const host = el("div");
      b.replaceChild(host, pre); ed.remove();
      draftEditor(host, h.key, h, (dr) => { if (dr) LOADERS.drafts(); else showDraft(h); });
    });
    b.appendChild(ed);
    d.appendChild(b);
  }
  const a = el("div", "actions");
  const redraft = el("button", "btn primary", "Redraft it");
  redraft.addEventListener("click", () => busy(redraft, "Redrafting…", async () => {
    await api("/api/jobs/draft", withEngine({ key: h.key }));
    toast("Redrafted.");
    LOADERS.drafts();
  }));
  const open = el("button", "btn", "Open the role");
  open.addEventListener("click", () => { S.selected = h.key; show("roles"); });
  a.append(redraft, open);
  d.appendChild(a);
}

/* --- auto-apply -------------------------------------------------------- */
LOADERS.auto = async function () {
  await refresh();
  drawReadiness();
  const a = (S.data || {}).auto || {};
  $("#aOn").checked = !!a.enabled;
  $("#aDry").checked = a.dry_run !== false;
  $("#aClean").checked = a.require_clean_check !== false;
  $("#aMin").value = a.min_score ?? 75;
  $("#aCap").value = a.daily_cap ?? 5;
  $("#aSig").value = a.signature || "";
  $("#aPortal").value = a.portal_mode || "prepare";
  $("#aDaily").checked = !!(S.data || {}).daily;
  drawAutoPreview();
};

// Why nothing will send, stated before you go looking. Auto-apply is guarded
// by several separate conditions, and when one was off the run just reported
// "0 sent" — which reads as a broken feature rather than a setting.
async function drawReadiness() {
  const host = $("#autoReady");
  if (!host) return null;
  host.innerHTML = "";
  let r;
  try { r = await api("/api/jobs/auto/readiness"); }
  catch (e) { return null; }
  const box = el("div", "ready " + (r.ok ? "is-ok" : "is-blocked"));
  const head = el("div", "ready-head");
  head.append(el("span", "ready-dot"), el("span", "ready-sum", r.summary));
  box.appendChild(head);
  (r.blockers || []).forEach((b) => {
    const row = el("div", "ready-row");
    row.append(el("span", "ready-what", b.what), el("span", "ready-fix", b.fix));
    if (b.where && b.where !== S.view) {
      const go = el("button", "btn sm", "Fix it");
      go.addEventListener("click", () => show(b.where));
      row.appendChild(go);
    } else if (b.where === "auto") {
      const go = el("button", "btn sm", "Fix it");
      go.addEventListener("click", () => { const c = $("#emailCard"); if (c) c.scrollIntoView({ behavior: "smooth" }); });
      row.appendChild(go);
    }
    box.appendChild(row);
  });
  (r.notes || []).forEach((n) => box.appendChild(el("div", "ready-note", n)));
  if ((r.settling_in || {}).on) {
    const end = el("button", "btn sm ghost", "End settling-in now");
    end.addEventListener("click", () => busy(end, "…", async () => {
      if (!confirm("Run at your full daily cap from now on?")) return;
      await api("/api/jobs/auto/settled", {}); drawReadiness();
    }));
    box.appendChild(end);
  }
  host.appendChild(box);
  return r;
}

// the account applications are emailed from (it lived in Agent Jo before the
// apps split, which left this app with no way to set it up)
async function drawEmail() {
  const host = $("#emailBody");
  if (!host) return;
  let st = {};
  try { st = await api("/api/jobs/email"); } catch (e) { return; }
  host.innerHTML = "";
  const f = (id, label, val, type, ph) => {
    const w = el("label", "resume-field");
    const i = el("input", "input"); i.id = id; i.value = val || ""; i.type = type || "text";
    if (ph) i.placeholder = ph;
    w.append(el("span", "muted", label), i);
    return w;
  };
  const grid = el("div", "email-grid");
  grid.append(f("mAddr", "Your email address", st.from_addr, "email", "you@example.com"),
              f("mName", "Your name as it appears", st.from_name, "text", "Thandi Mokoena"),
              f("mPass", st.has_password ? "Password (saved — leave blank to keep)" : "Password", "", "password",
                "an app password for Gmail"),
              f("mHost", "Mail server (SMTP)", st.host, "text", "smtp.gmail.com"),
              f("mPort", "Port", st.port || 587, "number"));
  host.appendChild(grid);
  const hint = el("p", "muted", "");
  host.appendChild(hint);
  $("#mAddr").addEventListener("change", async () => {
    const a = $("#mAddr").value.trim();
    try {
      const pr = await api("/api/jobs/email/preset?address=" + encodeURIComponent(a));
      if (pr.host && !$("#mHost").value) { $("#mHost").value = pr.host; $("#mPort").value = pr.port; }
      hint.textContent = pr.note || "";
    } catch (e) {}
  });
  const row = el("div", "actions");
  const on = el("label", "mock-opt");
  const cb = el("input"); cb.type = "checkbox"; cb.id = "mOn"; cb.checked = st.configured ? !!st.enabled : true;
  on.append(cb, document.createTextNode(" Send applications from this account"));
  const save = el("button", "btn primary", "Save");
  save.addEventListener("click", () => busy(save, "Saving…", async () => {
    await api("/api/jobs/email", { from_addr: $("#mAddr").value.trim(), from_name: $("#mName").value.trim(),
      password: $("#mPass").value, host: $("#mHost").value.trim(), port: +$("#mPort").value || 587,
      username: $("#mAddr").value.trim(), use_tls: true, enabled: cb.checked });
    toast("Saved. Send yourself a test to be sure it works.");
    drawEmail(); drawReadiness();
  }));
  const test = el("button", "btn", "Send a test to myself");
  test.addEventListener("click", () => busy(test, "Sending…", async () => {
    const x = await api("/api/jobs/email/test", {});
    toast(`Sent to ${x.to} — check your inbox.`);
  }));
  row.append(save, test);
  host.append(on, row);
  host.appendChild(el("p", "muted", st.configured
    ? `Set up: ${st.from_addr} via ${st.host}` + (st.enabled ? "." : " — but sending is switched off.")
    : "Not set up yet — emailed applications can't be sent until it is. The password is stored encrypted on this computer."));
}

async function drawAutoPreview() {
  const host = $("#autoPreview");
  host.innerHTML = "";
  try {
    const p = await api("/api/jobs/auto/preview", undefined, "GET");
    host.appendChild(el("p", "", p.sentence || "Auto-apply is off."));
    const rows = [
      ["would send", (p.would_send || []).length],
      ["held by the claims check", (p.would_hold || []).length],
      ["need scoring first", (p.needs_scoring || []).length],
      ["portal-only", (p.no_address || []).length],
    ].filter(([, n]) => n);
    rows.forEach(([what, n]) => host.appendChild(el("p", "muted", `${n} ${what}`)));
    if (p.dry_run) host.appendChild(el("p", "muted", "Rehearsal is on — nothing leaves."));
  } catch (e) { host.appendChild(el("p", "muted", e.message)); }
}

async function saveAuto(btn) {
  await busy(btn, "Saving…", async () => {
    const a = (S.data || {}).auto || {};
    // changing what's delivered by hand lifts "Draft only" — otherwise it
    // would keep sending nothing with no switch on the form to say why
    const handChanged = $("#aDry").checked !== (a.dry_run !== false)
      || $("#aPortal").value !== (a.portal_mode || "prepare");
    await api("/api/jobs/auto", {
      ...(a.level === "draft" && !handChanged ? {} : { deliver: true }),
      enabled: $("#aOn").checked, dry_run: $("#aDry").checked,
      require_clean_check: $("#aClean").checked,
      portal_mode: $("#aPortal").value,
      min_score: Number($("#aMin").value), daily_cap: Number($("#aCap").value),
      signature: $("#aSig").value,
    });
    toast("Rules saved.");
    await refresh(); railCounts(); drawAutoPreview(); drawReadiness(); drawLevels();
  });
}

/* --- sources and alerts ------------------------------------------------ */
LOADERS.sources = async function () {
  const host = $("#srcList");
  let cfg = {};
  try { cfg = await api("/api/jobs/search/config", undefined, "GET"); }
  catch (e) { empty(host, "Couldn't load", e.message); return; }
  const src = cfg.sources || [];
  $("#nSources").textContent = src.length || "";
  // freshness is when a search last actually asked the sources
  $("#srcFresh").textContent = cfg.checked_at
    ? `Last checked: ${cfg.checked_at}` : "Not checked yet — run a search to check every source.";
  host.innerHTML = "";
  if (!src.length) {
    empty(host, "No sources yet", "Add one, or let it find some that actually return roles.");
  }
  src.forEach((s) => {
    const row = el("div", "src-row" + (s.on === false ? " paused" : ""));
    row.appendChild(el("div", "rc-logo", initial(s.name || s.url)));
    const who = el("div", "src-who");
    who.append(el("div", "src-name", s.name || s.url), el("div", "src-url", s.url || ""));
    row.appendChild(who);
    const status = s.on === false ? "paused" : (s.status || "pending");
    const badge = el("span", "badge " + status,
      { verified: "Verified", pending: "Pending", failing: "Failing", paused: "Paused" }[status]);
    badge.title = status === "verified" ? `${s.last_count} role(s) on the last check, ${s.checked_at}`
      : status === "failing" ? (s.error || "Returned nothing on the last check") + (s.checked_at ? ` — ${s.checked_at}` : "")
      : status === "paused" ? "Skipped by searches until you resume it"
      : "Not checked yet";
    row.appendChild(badge);
    const acts = el("div", "src-acts");
    // sites that draw their listings with JavaScript, or only show them once
    // you're signed in, need a real browser — and a session
    if (s.kind !== "browser") {
      const conv = el("button", "btn sm", "Use a browser");
      conv.title = "Render this page like a real visit — needed when the "
        + "listings are drawn by JavaScript or only appear once you're signed in";
      conv.addEventListener("click", () => busy(conv, "Switching…", async () => {
        await api("/api/jobs/sources/kind", { name: s.name });
        toast(`${s.name} will be fetched with a real browser.`);
        LOADERS.sources();
      }));
      acts.appendChild(conv);
    } else {
      const si = el("button", "btn sm", "Sign in");
      si.title = "Open this site so you can sign in once — the browser keeps "
        + "the session for later fetches and applications";
      si.addEventListener("click", () => busy(si, "Opening…", async () => {
        await api("/api/jobs/sources/signin", { name: s.name });
        followSignIn(s);
      }));
      acts.appendChild(si);
    }
    const tog = el("button", "btn sm", s.on === false ? "Resume" : "Pause");
    tog.addEventListener("click", () => busy(tog, "…", async () => {
      await api("/api/jobs/sources", { name: s.name, on: s.on === false });
      LOADERS.sources();
    }));
    const view = el("button", "btn sm", "View");
    view.title = "Open this source";
    view.addEventListener("click", () => { if (s.url) window.open(s.url, "_blank", "noopener"); });
    const rm = el("button", "btn sm ghost danger", "Remove");
    rm.addEventListener("click", () => busy(rm, "…", async () => {
      await api("/api/jobs/sources/remove", { name: s.name, url: s.url });
      LOADERS.sources();
    }));
    acts.append(tog, view, rm);
    row.appendChild(acts);
    host.appendChild(row);
  });

  const sug = $("#srcSuggested");
  sug.innerHTML = "";
  try {
    const d = await api("/api/jobs/sources/suggested", undefined, "GET");
    const list = (d.suggested || []).slice(0, 6);
    if (!list.length) sug.appendChild(el("p", "muted", "Fill in your profile and suggestions appear."));
    list.forEach((s) => {
      const it = el("div", "item static");
      const body = el("div");
      body.append(el("div", "item-t", s.name || s.url),
                  el("div", "item-m", s.why || s.url || ""));
      const add = el("button", "btn sm", "Add");
      add.addEventListener("click", () => busy(add, "…", async () => {
        await api("/api/jobs/sources", { name: s.name, url: s.url, kind: s.kind || "" });
        LOADERS.sources();
      }));
      it.append(el("div", "mono", initial(s.name)), body, add);
      sug.appendChild(it);
    });
  } catch (e) { sug.appendChild(el("p", "muted", "Couldn't load suggestions.")); }
};

/* --- engines ----------------------------------------------------------- */
// Adding an engine here writes to the same place Agent Jo reads, so an engine
// added in either app appears in both. The presets exist because a base URL
// typed from memory is how a cloud engine ends up pointing at a local runner.
const ENGINE_PRESETS = [
  ["DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat", true],
  ["OpenAI", "https://api.openai.com/v1", "gpt-4o-mini", true],
  ["Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", true],
  ["Together", "https://api.together.xyz/v1", "meta-llama/Llama-3.3-70B-Instruct-Turbo", true],
  ["OpenRouter", "https://openrouter.ai/api/v1", "deepseek/deepseek-chat", true],
  ["Ollama (this machine)", "http://localhost:11434/v1", "qwen3:8b", false],
  ["LM Studio (this machine)", "http://localhost:1234/v1", "local-model", false],
];

function engField(id) { return ($("#" + id).value || "").trim(); }

function drawPresets() {
  const host = $("#engPresets");
  host.innerHTML = "";
  ENGINE_PRESETS.forEach(([name, url, model, cloud]) => {
    const b = el("button", "chip" + (cloud ? "" : " local"), name);
    b.type = "button";
    b.title = url;
    b.addEventListener("click", () => {
      $("#eName").value = name.split(" (")[0];
      $("#eUrl").value = url;
      $("#eModel").value = model;
      $("#eKey").placeholder = cloud ? "sk-…" : "not needed for a local model";
      $("#eOut").textContent = "";
    });
    host.appendChild(b);
  });
}

function engSay(msg, kind) {
  const out = $("#eOut");
  out.className = "eng-out " + (kind || "");
  out.textContent = msg;
}

LOADERS.engines = async function () {
  drawUpdates();
  drawPhone();
  drawBackups();
  drawPresets();
  const host = $("#engList");
  host.innerHTML = "";
  let list = [];
  try { list = (await api("/api/engines")).engines || []; }
  catch (e) { empty(host, "Couldn't load engines", e.message); return; }
  const mine = list.filter((e) => e.custom);
  $("#nEngines").textContent = mine.length || "";
  if (!list.length) empty(host, "No engines yet", "Add one above.");
  list.forEach((e) => {
    const row = el("div", "src-row");
    row.appendChild(el("div", "rc-logo", initial(e.label || e.id)));
    const who = el("div", "src-who");
    who.append(el("div", "src-name", e.label || e.id),
               el("div", "src-url", [e.model, e.base_url].filter(Boolean).join("  ·  ")));
    row.appendChild(who);
    // amber is for something wrong; where an engine runs is just a fact
    const kind = el("span", "badge " + (e.kind === "local" ? "verified" : "paused"));
    kind.textContent = e.kind === "local" ? "On this machine" : (e.kind || "cloud");
    kind.title = e.kind === "local"
      ? "Runs here — costs nothing and nothing leaves the machine"
      : "A cloud provider — needs a key, and calls leave this machine";
    row.appendChild(kind);
    const acts = el("div", "src-acts");
    if (e.custom) {
      const test = el("button", "btn sm", "Test");
      test.addEventListener("click", () => busy(test, "Testing…", async () => {
        const r = await api("/api/engines/test", { name: e.id, base_url: e.base_url, model: e.model });
        toast(r.ok ? `${e.id}: ${r.detail}` : `${e.id}: ${r.error} ${r.fix || ""}`,
              r.ok ? "" : "bad");
      }));
      const use = el("button", "btn sm", "Use");
      use.title = "Score and draft with this engine";
      use.addEventListener("click", () => {
        S.engine = e.id;
        const sel = $("#engine"); if (sel) sel.value = e.id;
        toast(`Scoring and drafting will use ${e.id}.`);
      });
      const rm = el("button", "btn sm ghost danger", "Remove");
      rm.addEventListener("click", () => {
        if (!confirm(`Remove the engine "${e.id}"?`)) return;
        busy(rm, "…", async () => {
          await api(`/api/engines/${encodeURIComponent(e.id)}`, undefined, "DELETE");
          LOADERS.engines(); refreshEnginePicker();
        });
      });
      acts.append(test, use, rm);
    } else {
      acts.appendChild(el("span", "muted", "built in"));
    }
    row.appendChild(acts);
    host.appendChild(row);
  });
};

async function refreshEnginePicker() {
  try {
    const m = await api("/api/meta");
    const sel = $("#engine");
    if (!sel) return;
    const was = sel.value;
    sel.innerHTML = "";
    ["Auto"].concat(m.engines || []).forEach((n) => {
      const o = el("option", "", n); o.value = n;
      sel.appendChild(o);
    });
    sel.value = (m.engines || []).includes(was) ? was : (m.default_engine || "Auto");
    S.engine = sel.value;
  } catch (e) { /* the picker keeps what it had */ }
}

// signing in is the same shape as a captcha: it opens, waits for you, and
// keeps what you did
function followSignIn(s) {
  const host = $("#srcList");
  const box = el("div", "ready is-blocked signin-box");
  box.appendChild(el("div", "ready-head", `Sign in to ${s.name}`));
  const msg = el("p", "", "A window is opening. Sign in there, then press Done.");
  box.appendChild(msg);
  const bar = el("div", "actions");
  const done = el("button", "btn primary sm", "Done — I'm signed in");
  const stop = el("button", "btn sm ghost", "Cancel");
  bar.append(done, stop);
  box.appendChild(bar);
  host.parentNode.insertBefore(box, host);
  const key = "signin:" + (s.url || "").replace(/^https?:\/\//, "")
    .replace("www.", "").split("/")[0];
  const finish = async (what) => {
    await api(`/api/jobs/portal/${what}`, { key });
    box.remove();
    if (what === "continue") toast(`Signed in to ${s.name} — the browser keeps it.`);
    LOADERS.sources();
  };
  done.addEventListener("click", () => busy(done, "Saving…", () => finish("continue")));
  stop.addEventListener("click", () => busy(stop, "…", () => finish("cancel")));
}

/* --- results ----------------------------------------------------------- */
LOADERS.results = async function () {
  drawInbox();
  drawDigest(false);
  let d = {};
  try { d = await api("/api/jobs/outcomes", undefined, "GET"); }
  catch (e) { empty($("#findings"), "Couldn't load", e.message); return; }
  $("#resHead").textContent = d.sent
    ? `${d.replied} ${d.replied === 1 ? "reply" : "replies"} from ${d.sent}.`
    : "Nothing sent yet.";
  $("#resLede").textContent = d.sent
    ? `Somewhere between ${d.overall.low}% and ${d.overall.high}% — the range matters more than the number while the sample is small.`
    : "There is nothing to learn from until applications go out.";
  const f = $("#findings");
  f.innerHTML = "";
  (d.findings || []).forEach((x) => {
    const row = el("div", "finding");
    row.appendChild(el("div", "finding-t", x.what));
    row.appendChild(el("p", "muted", x.why));
    if (x.do) row.appendChild(el("p", "", x.do));
    if (!x.confident) row.querySelector(".finding-t")
      .appendChild(el("span", "tag held", "not conclusive"));
    f.appendChild(row);
  });
  if (!(d.findings || []).length) empty(f, "Nothing conclusive yet", "");

  const b = $("#breakdown");
  b.innerHTML = "";
  b.appendChild(el("h3", "", "The detail"));
  [["By source", d.by_source, "source"], ["By fit", d.by_score, "band"],
   ["By route", d.by_method, "method"]].forEach(([title, rows, key]) => {
    if (!rows || !rows.length) return;
    b.appendChild(el("p", "muted", title));
    rows.forEach((r) => b.appendChild(el("p", "", `${r[key]} — ${r.reading}`)));
  });
  if (d.note) b.appendChild(el("p", "muted", d.note));
};

/* --- archive and tidy -------------------------------------------------- */
LOADERS.archive = async function () {
  const host = $("#archList");
  let d = {};
  try { d = await api("/api/jobs/archive", undefined, "GET"); }
  catch (e) { empty(host, "Couldn't load", e.message); return; }
  $("#nArchive").textContent = d.count || "";
  host.innerHTML = "";
  const rows = d.roles || [];
  if (!rows.length) empty(host, "The archive is empty", "Closed and old roles land here.");
  rows.forEach((r) => {
    const it = el("div", "item static");
    const body = el("div");
    body.append(el("div", "item-t", r.title || "(untitled)"),
      el("div", "item-m", [r.company, r.archived_why || r.reason].filter(Boolean).join(" · ")));
    const back = el("button", "btn sm", "Bring back");
    back.addEventListener("click", () => busy(back, "…", async () => {
      await api("/api/jobs/unarchive", { key: r.key });
      toast("Restored to your roles.");
      LOADERS.archive();
    }));
    it.append(el("div", "mono", initial(r.company)), body, back);
    host.appendChild(it);
  });
};

async function tidy(path, label, body, btn, say) {
  await busy(btn, label, async () => {
    const x = await api(path, body || {});
    toast(say(x));
    LOADERS.archive();
  });
}

/* --- profile ----------------------------------------------------------- */
const FIELDS = [
  ["target_roles", "Desired Roles", "Senior Data Engineer, BI Lead"],
  ["skills", "Core Skills", "Power BI dashboard development, DAX, data modelling"],
  ["technologies", "Tools", "Power BI, SQL Server, SSIS, Snowflake"],
  ["locations_ok", "Location Preferences", "Johannesburg, remote"],
  ["deal_breakers", "Deal-breakers — never apply if the advert says", "commission only, night shift, relocation required"],
  ["must_haves", "Must-haves — shown when an advert doesn't mention them", "remote, medical aid"],
];
// what every company form asks for — there was nowhere to enter these, so
// every portal application stopped asking for them
const CONTACT = [
  ["full_name", "Full name", "Thandi Mokoena"],
  ["email", "Email for applications", "you@example.com (blank: your sending address)"],
  ["phone", "Phone", "+27 82 000 0000"],
  ["location", "Where you live", "Johannesburg, Gauteng, South Africa"],
  ["linkedin", "LinkedIn", "https://www.linkedin.com/in/…"],
  ["availability", "Notice period / availability", "30 days"],
];
const TICK = '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="7"/><path d="m5 8.2 2 2L11 6"/></svg>';

/* --- your full CV (agent/cvstore.py) --------------------------------------- */
async function drawCvStatus() {
  let st = {};
  try { st = await api("/api/jobs/cvtext"); } catch (e) { return; }
  $("#cvStatus").textContent = st.present
    ? `CV saved ${st.at}: ${st.sections} sections, ${st.chars.toLocaleString()} characters. ` +
      "Drafts and form answers draw on it. Paste a newer one to replace it."
    : "Paste your whole CV once. Drafts and form answers draw on the parts that fit " +
      "each question, and empty profile fields below are filled from it.";
}
function wireCv() {
  $("#cvSave").addEventListener("click", (e) => busy(e.target, "Reading your CV…", async () => {
    const text = $("#cvText").value;
    const x = await api("/api/jobs/cvtext", { text, engine: S.engine });
    $("#cvText").value = "";
    const pf = x.profile || {};
    toast(`CV saved: ${x.sections} sections.` + (pf.ok
      ? (pf.filled && pf.filled.length ? ` Filled from it: ${pf.filled.join(", ")}.`
                                        : " Your profile already had everything it says.")
      : ` The profile wasn't filled: ${pf.error || "no engine"}.`), pf.ok ? "" : "warn");
    await drawCvStatus();
    LOADERS.profile();
  }));
  $("#cvUpload").addEventListener("click", () => $("#cvFile").click());
  $("#cvFile").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    busy($("#cvUpload"), "Reading " + file.name + "…", async () => {
      const data = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(r.result); r.onerror = () => rej(new Error("Couldn't read that file."));
        r.readAsDataURL(file);
      });
      const x = await api("/api/jobs/cvfile", { name: file.name, data, engine: S.engine });
      const pf = x.profile || {};
      const li = x.linkedin;
      toast(`${file.name} read: ${x.sections} sections.` +
        (li ? " Read as your LinkedIn profile" + ((li.filled || []).length
              ? ` — filled ${li.filled.join(", ")}.` : ".") : "") +
        (pf.ok && pf.filled && pf.filled.length ? ` Filled from it: ${pf.filled.join(", ")}.` : ""),
        pf.ok ? "" : "warn");
      await drawCvStatus();
      LOADERS.profile();
    });
  });
  $("#cvClear").addEventListener("click", async () => {
    if (!confirm("Remove the saved CV? Your profile stays as it is.")) return;
    await api("/api/jobs/cvtext", undefined, "DELETE");
    toast("CV removed."); drawCvStatus();
  });
}

/* --- your answers (agent/answerbank.py) ------------------------------------ */
let ANSWERS = [];
function drawAnswers() {
  const list = $("#ansList");
  list.innerHTML = "";
  const q = ($("#ansFilter").value || "").toLowerCase();
  const shown = ANSWERS.filter((a) => !q || (a.question + " " + a.answer).toLowerCase().includes(q));
  $("#nAnswers").textContent = ANSWERS.length || "";
  if (!shown.length) {
    list.appendChild(el("p", "lede", ANSWERS.length ? "Nothing matches."
      : "Nothing saved yet. Answers are saved as you fill in forms with the helper, or add one above."));
    return;
  }
  shown.forEach((a) => {
    const row = el("div", "ans-item");
    const head = el("div");
    head.append(el("div", "ans-q", a.question),
      el("div", "ans-meta", [a.site, a.role, a.uses ? `used ${a.uses}×` : "not reused yet", a.at]
        .filter(Boolean).join(" · ")));
    const acts = el("div", "ans-acts");
    if (a.sensitive) {
      const lab = el("label", "ans-sens");
      const cb = el("input"); cb.type = "checkbox"; cb.checked = !!a.reuse;
      cb.addEventListener("change", async () => {
        await api(`/api/jobs/answers/${a.id}`, { reuse: cb.checked });
        a.reuse = cb.checked;
        toast(cb.checked ? "This answer will be reused." : "This answer won't be reused.");
      });
      lab.append(cb, document.createTextNode("reuse"));
      lab.title = "A sensitive question: reused only if you switch it on";
      acts.appendChild(lab);
    }
    const del = el("button", "btn", "Delete");
    del.addEventListener("click", async () => {
      await api(`/api/jobs/answers/${a.id}`, undefined, "DELETE");
      ANSWERS = ANSWERS.filter((x) => x.id !== a.id); drawAnswers();
    });
    acts.appendChild(del);
    const ta = el("textarea", "input ans-a"); ta.rows = 2; ta.value = a.answer;
    ta.addEventListener("change", async () => {
      await api(`/api/jobs/answers/${a.id}`, { answer: ta.value });
      a.answer = ta.value; toast("Answer updated.");
    });
    row.append(head, acts, ta);
    list.appendChild(row);
  });
}
function drawOpen(open) {
  const box = $("#ansOpen");
  box.innerHTML = "";
  $("#ansOpenCard").hidden = !open.length;
  const badge = $("#nAnswers");
  badge.classList.toggle("warn", !!open.length);
  badge.title = open.length ? `${open.length} question(s) waiting on you` : "";
  if (open.length) badge.textContent = open.length;
  open.forEach((q) => {
    const it = el("div", "open-item");
    it.appendChild(el("div", "ans-q", q.question));
    it.appendChild(el("div", "ans-meta",
      (q.roles.length ? `holding up ${q.roles.length}: ${q.roles.slice(0, 3).join("; ")}`
                      : "asked by a form") + (q.sensitive ? " · sensitive: only ever used for this" : "")));
    const row = el("div", "open-row");
    const inp = el("input", "input"); inp.placeholder = "Your answer";
    const go = el("button", "btn primary", "Save");
    const save = () => busy(go, "Saving…", async () => {
      if (!inp.value.trim()) return;
      const x = await api("/api/jobs/answers/open", { question: q.question, answer: inp.value });
      toast("Saved. Forms that ask this will get your answer.");
      drawOpen(x.open || []);
      LOADERS.answers();
    });
    go.addEventListener("click", save);
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
    row.append(inp, go);
    it.appendChild(row);
    box.appendChild(it);
  });
}
async function refreshOpen() {
  try { drawOpen((await api("/api/jobs/answers/open")).open || []); }
  catch (e) { /* the badge just stays as it was */ }
}
LOADERS.answers = async function () {
  try { ANSWERS = (await api("/api/jobs/answers")).answers || []; }
  catch (e) { ANSWERS = []; }
  drawAnswers();
  await refreshOpen();
};
function wireAnswers() {
  $("#ansFilter").addEventListener("input", drawAnswers);
  $("#ansSave").addEventListener("click", (e) => busy(e.target, "Saving…", async () => {
    await api("/api/jobs/answers", { question: $("#ansQ").value, answer: $("#ansA").value });
    $("#ansQ").value = ""; $("#ansA").value = "";
    toast("Saved. Forms that ask this will get your answer.");
    LOADERS.answers();
  }));
}

LOADERS.profile = async function () {
  drawCvStatus();
  drawStyle();
  const rh = $("#resumeBody");
  if (rh && !rh.firstChild) rh.appendChild(resumePicker(""));
  let p = {};
  try { p = (await api("/api/jobs/profile", {})).profile || {}; }
  catch (e) { /* render an empty form */ }
  const f = $("#profileForm");
  f.innerHTML = "";
  const fieldRow = (key, label, hint, value) => {
    const w = el("div", "field");
    const l = el("label", "", label);
    w.appendChild(l);
    const box = el("div", "field-box");
    const i = el("input", "input");
    i.id = "p_" + key; i.placeholder = hint; i.value = value;
    const t = el("span", "field-tick" + (value.trim() ? " on" : ""));
    t.innerHTML = TICK;
    t.title = value.trim() ? "A draft may claim these" : "Empty — nothing here can be claimed";
    i.addEventListener("input", () => t.classList.toggle("on", !!i.value.trim()));
    box.append(i, t);
    w.appendChild(box);
    return w;
  };
  const join = (v) => Array.isArray(v) ? v.join(", ") : (v || "");
  const ch = el("div", "field"); ch.appendChild(el("label", "", "Contact details — company forms ask for these every time"));
  f.appendChild(ch);
  CONTACT.forEach(([k, label, hint]) => f.appendChild(fieldRow(k, label, hint, String(p[k] || ""))));
  FIELDS.slice(0, 3).forEach(([k, label, hint]) => f.appendChild(fieldRow(k, label, hint, join(p[k]))));

  // employment history: one card per employer, as in the design
  const emp = el("div", "field");
  emp.appendChild(el("label", "", "Employment History"));
  const cards = el("div", "emp-cards");
  let employers = Array.isArray(p.employers) ? p.employers.slice() : [];
  const drawEmp = () => {
    cards.innerHTML = "";
    employers.forEach((name, idx) => {
      const c = el("div", "emp-card");
      c.append(el("div", "rc-logo", initial(name)), el("div", "emp-name", name));
      const x = el("button", "emp-x", "×");
      x.title = "Remove";
      x.addEventListener("click", () => { employers.splice(idx, 1); drawEmp(); });
      c.appendChild(x);
      cards.appendChild(c);
    });
    const add = el("input", "input emp-add");
    add.placeholder = "Add an employer and press Enter";
    add.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && add.value.trim()) {
        employers.push(add.value.trim()); drawEmp();
        const next = cards.querySelector(".emp-add"); if (next) next.focus();
      }
    });
    cards.appendChild(add);
  };
  drawEmp();
  emp.appendChild(cards);
  f.appendChild(emp);

  f.appendChild(fieldRow("locations_ok", FIELDS[3][1], FIELDS[3][2], join(p.locations_ok)));
  FIELDS.slice(4).forEach(([k, label, hint]) => f.appendChild(fieldRow(k, label, hint, join(p[k]))));

  const save = el("button", "btn primary wide", "Save & Synchronize Profile");
  save.addEventListener("click", () => busy(save, "Saving…", async () => {
    const body = { employers };
    FIELDS.forEach(([k]) => {
      body[k] = ($("#p_" + k).value || "").split(",").map((s) => s.trim()).filter(Boolean);
    });
    CONTACT.forEach(([k]) => { body[k] = ($("#p_" + k).value || "").trim(); });
    await api("/api/jobs/profile", body);
    toast("Saved — drafts can now claim these.");
    await refresh(); railCounts(); LOADERS.profile();
  }));
  f.appendChild(save);

  // the coverage column: every claim a draft may make, grouped
  const side = $("#profileSide");
  side.innerHTML = "";
  const groups = [
    ["Desired roles", p.target_roles], ["Skills", p.skills], ["Tools", p.technologies],
    ["Employment history", p.employers], ["Location preferences", p.locations_ok],
    ["Achievements", p.achievements],
  ];
  let total = 0;
  groups.forEach(([title, items]) => {
    const list = Array.isArray(items) ? items.filter(Boolean) : [];
    total += list.length;
    const g = el("div", "cov-group");
    const h = el("div", "cov-head");
    h.append(el("span", "", title), el("span", "cov-n", String(list.length)));
    g.appendChild(h);
    if (!list.length) g.appendChild(el("div", "cov-empty", "Nothing yet — a draft can't mention any."));
    list.slice(0, 12).forEach((x) => g.appendChild(el("div", "cov-item", String(x))));
    if (list.length > 12) g.appendChild(el("div", "cov-empty", `and ${list.length - 12} more`));
    side.appendChild(g);
  });
  const c = profileCompleteness(p);
  const foot = el("div", "cov-foot");
  foot.innerHTML = `<b>${total}</b> claim${total === 1 ? "" : "s"} a draft may make · profile ${c.pct}% complete`
    + (c.missing.length ? `<br><span class="muted">Missing: ${c.missing.join(", ")}</span>` : "");
  side.appendChild(foot);
};

/* --- Symbolic Synapse ---------------------------------------------------- */
// The look's two moving parts, and nothing here may throw into the page:
//   - on the overview, a slowly turning lattice sphere with filaments of
//     light leaving it, after the hero of symbolicsynapse.co.za, with the
//     Jobs logo at its heart. Drawn in 2D on one small canvas (no WebGL, no
//     library), only while the overview is on screen and the window is
//     visible. Left alone for two minutes it holds still until you move the
//     mouse or type; with reduced motion it is drawn once and stays still;
//   - a soft light under the pointer on cards (mouse and pen, not touch).
const SYN = { canvas: null, ctx: null, raf: 0, last: 0, input: 0,
              lat: null, fils: null, seen: true, watching: false };
const SYN_IDLE_MS = 120000;
const SYN_RGB = { steel: [46, 111, 174], mint: [70, 211, 154], edge: [58, 132, 200] };

function synOn() {
  return document.documentElement.getAttribute("data-skin") === "synapse";
}
function synReduced() {
  try { return matchMedia("(prefers-reduced-motion: reduce)").matches; }
  catch (e) { return false; }
}
function synStart() {
  if (!synOn()) return;
  try { SYN.input = performance.now(); synWatch(); } catch (e) { return; }
  synKick();
}
function synWake() {
  SYN.input = performance.now();
  if (!SYN.raf) synKick();
}
function synWatch() {
  if (SYN.watching) return;
  SYN.watching = true;
  document.addEventListener("visibilitychange", synKick);
  window.addEventListener("resize", synKick);
  ["pointermove", "pointerdown", "keydown", "wheel"].forEach((ev) =>
    document.addEventListener(ev, synWake, { passive: true }));
  const ov = document.getElementById("v-overview");
  if (ov && typeof MutationObserver === "function") {
    new MutationObserver(synKick).observe(ov, { attributes: true, attributeFilter: ["class"] });
  }
  try {
    if (matchMedia("(hover: hover)").matches) {
      document.addEventListener("pointermove", synGlow, { passive: true });
    }
  } catch (e) { /* no media queries: no light */ }
}
function synGlow(e) {
  if (e.pointerType === "touch" || !e.target || !e.target.closest) return;
  try {
    const card = e.target.closest(".card, .role-card, .step");
    if (!card) return;
    const r = card.getBoundingClientRect();
    card.style.setProperty("--mx", Math.round(e.clientX - r.left) + "px");
    card.style.setProperty("--my", Math.round(e.clientY - r.top) + "px");
  } catch (err) { /* only a light: nothing depends on it */ }
}
function synMount() {
  if (SYN.canvas && SYN.canvas.isConnected) return SYN.canvas;
  const mark = document.querySelector("#v-overview .syn-mark");
  if (!mark || typeof mark.insertBefore !== "function") return null;
  const c = document.createElement("canvas");
  if (typeof c.getContext !== "function") return null;
  c.setAttribute("aria-hidden", "true");
  mark.insertBefore(c, mark.firstChild);
  SYN.canvas = c;
  SYN.ctx = c.getContext("2d");
  if (typeof IntersectionObserver === "function") {
    new IntersectionObserver((entries) => {
      SYN.seen = entries.some((x) => x.isIntersecting);
      synKick();
    }).observe(c);
  }
  return c;
}
function synRunnable() {
  const ov = document.getElementById("v-overview");
  return synOn() && !!SYN.ctx && !document.hidden && SYN.seen
    && !!ov && ov.classList.contains("is-on");
}
function synKick() {
  try { synKickNow(); } catch (e) { synStop(); }
}
function synKickNow() {
  if (!synMount() || !synRunnable()) { synStop(); return; }
  if (synReduced()) { synStop(); synFrame(0, true); return; }
  if (!SYN.raf) SYN.raf = requestAnimationFrame(synTick);
}
function synStop() {
  if (SYN.raf) cancelAnimationFrame(SYN.raf);
  SYN.raf = 0;
}
function synTick(now) {
  SYN.raf = 0;
  if (!synRunnable() || now - SYN.input > SYN_IDLE_MS) return;
  if (now - SYN.last >= 50) {              // it moves slowly: 20 frames a second is smooth
    SYN.last = now;
    try { synFrame(now, false); } catch (e) { return; }
  }
  SYN.raf = requestAnimationFrame(synTick);
}
function synUnit(p) {
  const l = Math.hypot(p[0], p[1], p[2]) || 1;
  return [p[0] / l, p[1] / l, p[2] / l];
}
// The site's lattice: hexagons (and twelve pentagons) on a sphere — the dual
// of an icosahedron split twice. 320 nodes, 480 edges, built once.
function synLattice() {
  const t = (1 + Math.sqrt(5)) / 2;
  const v = [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t],
             [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]].map(synUnit);
  let f = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4],
           [11, 10, 2], [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8],
           [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
  for (let s = 0; s < 2; s++) {
    const mid = new Map(), next = [];
    const m = (a, b) => {
      const k = a < b ? a + "," + b : b + "," + a;
      if (!mid.has(k)) {
        v.push(synUnit([(v[a][0] + v[b][0]) / 2, (v[a][1] + v[b][1]) / 2, (v[a][2] + v[b][2]) / 2]));
        mid.set(k, v.length - 1);
      }
      return mid.get(k);
    };
    f.forEach(([a, b, c]) => {
      const ab = m(a, b), bc = m(b, c), ca = m(c, a);
      next.push([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]);
    });
    f = next;
  }
  const nodes = f.map(([a, b, c]) => synUnit([v[a][0] + v[b][0] + v[c][0],
    v[a][1] + v[b][1] + v[c][1], v[a][2] + v[b][2] + v[c][2]]));
  const owner = new Map(), edges = [];
  f.forEach((tri, i) => {
    for (let k = 0; k < 3; k++) {
      const a = tri[k], b = tri[(k + 1) % 3], key = a < b ? a + "," + b : b + "," + a;
      if (owner.has(key)) edges.push([owner.get(key), i]); else owner.set(key, i);
    }
  });
  return { nodes, edges };
}
// filaments leave the sphere's sides and drift outwards; the same ones every
// time (a fixed seed), so the picture is steady between visits
function synFilaments(n) {
  let s = 20261015;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const out = [];
  for (let i = 0; i < n; i++) {
    const right = i % 2 === 0;
    const a = (right ? 0.32 : Math.PI - 0.32) + (rnd() - 0.5) * (right ? 1.1 : -1.1);
    out.push({ a, reach: 0.5 + rnd() * 0.5, droop: rnd() * 0.75 - 0.15,
               wave: rnd() * Math.PI * 2, speed: 0.05 + rnd() * 0.07, phase: rnd() });
  }
  return out;
}
function synBez(u, x0, y0, x1, y1, x2, y2, x3, y3) {
  const w = 1 - u, a = w * w * w, b = 3 * w * w * u, c = 3 * w * u * u, d = u * u * u;
  return [a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3];
}
function synFrame(now, still) {
  const c = SYN.canvas, ctx = SYN.ctx;
  if (!c || !ctx) return;
  const w = c.clientWidth, h = c.clientHeight;
  if (!w || !h) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!SYN.lat) SYN.lat = synLattice();
  if (!SYN.fils) SYN.fils = synFilaments(12);
  const t = still ? 3.1 : now / 1000;
  const mark = c.parentElement;
  const img = mark && mark.querySelector("img");
  let halo = 24;
  try { halo = parseFloat(getComputedStyle(mark).getPropertyValue("--syn-halo")) || 24; } catch (e) {}
  const cx = w / 2, cy = h / 2;
  const R = Math.max(20, Math.min(h / 2 - 3, (img ? img.clientWidth / 2 : 32) + halo));

  // a green glow under the sphere, as under the site's mark
  const glow = ctx.createRadialGradient(cx, cy + R * 0.2, R * 0.2, cx, cy + R * 0.2, R * 1.7);
  glow.addColorStop(0, "rgba(19, 120, 100, 0.22)");
  glow.addColorStop(1, "rgba(19, 120, 100, 0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);

  // filaments first: they run behind the sphere — light, then green, then steel
  ctx.lineCap = "round";
  SYN.fils.forEach((f) => {
    const sway = still ? 0 : Math.sin(t * 0.55 + f.wave) * 0.06;
    const a = f.a + sway;
    const x0 = cx + Math.cos(a) * R * 0.94, y0 = cy + Math.sin(a) * R * 0.94;
    const dir = Math.cos(a) >= 0 ? 1 : -1;
    const room = Math.max(10, (w / 2 - R - 8) * f.reach);
    const x3 = x0 + dir * room;
    const y3 = Math.max(6, Math.min(h - 6, y0 + (f.droop + sway) * (h / 2 - 8)));
    const x1 = x0 + dir * room * 0.32, y1 = y0 + Math.sin(a) * room * 0.18;
    const x2 = x0 + dir * room * 0.68, y2 = y3 - (f.droop + sway) * 14;
    const g = ctx.createLinearGradient(x0, y0, x3, y3);
    g.addColorStop(0, "rgba(230, 250, 255, 0.5)");
    g.addColorStop(0.4, "rgba(70, 211, 154, 0.32)");
    g.addColorStop(1, "rgba(46, 111, 174, 0)");
    ctx.strokeStyle = g;
    ctx.lineWidth = 1.1;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.bezierCurveTo(x1, y1, x2, y2, x3, y3);
    ctx.stroke();
    if (!still) {                           // a pulse travelling outwards
      const u = (t * f.speed + f.phase) % 1;
      const p = synBez(u, x0, y0, x1, y1, x2, y2, x3, y3);
      const k = Math.sin(Math.PI * u);
      const rg = ctx.createRadialGradient(p[0], p[1], 0, p[0], p[1], 7);
      rg.addColorStop(0, `rgba(230, 250, 255, ${(0.9 * k).toFixed(3)})`);
      rg.addColorStop(0.35, `rgba(70, 211, 154, ${(0.45 * k).toFixed(3)})`);
      rg.addColorStop(1, "rgba(70, 211, 154, 0)");
      ctx.fillStyle = rg;
      ctx.beginPath();
      ctx.arc(p[0], p[1], 7, 0, Math.PI * 2);
      ctx.fill();
    }
  });

  // the sphere, turning slowly and tipped towards you; the far side fades
  const ay = t * 0.16, ax = -0.38;
  const sy = Math.sin(ay), cyy = Math.cos(ay), sx = Math.sin(ax), cxx = Math.cos(ax);
  const P = SYN.lat.nodes.map(([x, y, z]) => {
    const x1 = x * cyy + z * sy, z1 = -x * sy + z * cyy;
    const y2 = y * cxx - z1 * sx, z2 = y * sx + z1 * cxx;
    const k = 1 + z2 * 0.1;
    return [cx + x1 * R * k, cy + y2 * R * k, z2];
  });
  const B = 5;
  const lines = Array.from({ length: B }, () => new Path2D());
  SYN.lat.edges.forEach(([i, j]) => {
    const p = P[i], q = P[j];
    const b = Math.min(B - 1, Math.floor((((p[2] + q[2]) / 2 + 1) / 2) * B));
    lines[b].moveTo(p[0], p[1]);
    lines[b].lineTo(q[0], q[1]);
  });
  ctx.lineWidth = 1;
  lines.forEach((path, b) => {
    const d = (b + 0.5) / B;
    ctx.strokeStyle = `rgba(${SYN_RGB.edge.join(",")}, ${(0.07 + 0.55 * d * d).toFixed(3)})`;
    ctx.stroke(path);
  });
  const dots = Array.from({ length: B }, () => new Path2D());
  P.forEach(([x, y, z]) => {
    const d = (z + 1) / 2;
    if (d < 0.3) return;                      // the back is lost in the fog
    const b = Math.min(B - 1, Math.floor(d * B));
    const r = 0.5 + d * 1.1;
    dots[b].moveTo(x + r, y);
    dots[b].arc(x, y, r, 0, Math.PI * 2);
  });
  dots.forEach((path, b) => {
    const d = (b + 0.5) / B;
    const col = SYN_RGB.steel.map((s, i) => Math.round(s + (SYN_RGB.mint[i] - s) * d));
    ctx.fillStyle = `rgba(${col.join(",")}, ${(0.2 + 0.8 * d * d).toFixed(3)})`;
    ctx.fill(path);
  });
}

/* "by Symbolic Synapse" as the site's two-tone wordmark: the first word in
   ice blue, the second in the accent (green here, cyan on the site) */
function brandLine(host, brand) {
  if (!host) return;
  const words = String(brand || "").trim().split(/\s+/).filter(Boolean);
  host.textContent = "";
  host.append(el("span", "rs-by", "by "));
  words.forEach((w, i) => {
    host.append(el("span", i % 2 ? "rs-b" : "rs-a", w));
    if (i < words.length - 1) host.append(" ");
  });
}

/* --- wiring ------------------------------------------------------------ */
/* The look. There were two, "new" and "previous", with a switch in the
   sidebar; they looked almost the same, so the switch went and the previous
   look is the only one. index.html carries it from the first paint. */
function currentLook() { return "previous"; }
function applyLook() {
  try { localStorage.removeItem("agentjo-look"); } catch (e) { /* nothing saved */ }
  document.documentElement.setAttribute("data-look", "previous");
}
function wireLook() { applyLook(); }

async function boot() {
  wireLook();
  synStart();
  wireCv();
  wireAnswers();
  wireInbox();
  wireDigest();
  wireUpdates();
  refreshOpen();
  $$(".nav").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

  $("#roleFilter").addEventListener("input", (e) => { S.filter = e.target.value; drawRoleList(); });
  $("#roleSort").addEventListener("change", (e) => { S.sort = e.target.value; drawRoleList(); });
  $$("[data-bulk]").forEach((b) => b.addEventListener("click", () => bulk(b.dataset.bulk, b)));

  const railAuto = $("#railAuto");
  if (railAuto) railAuto.addEventListener("click", async (e) => {
    e.stopPropagation();                       // the switch, not the view
    const on = !((S.data || {}).auto || {}).enabled;
    try {
      await api("/api/jobs/auto", { enabled: on });
      await refresh(); railCounts();
      toast(on ? "Auto-apply on — rehearsal settings still apply." : "Auto-apply off.");
    } catch (err) { toast(err.message, "bad"); }
  });

  $("#eTest").addEventListener("click", (e) => busy(e.target, "Testing…", async () => {
    const r = await api("/api/engines/test", {
      base_url: engField("eUrl"), api_key: engField("eKey"), model: engField("eModel"),
    });
    engSay(r.ok ? `${r.detail} It replied: "${r.reply}"` : `${r.error} ${r.fix || ""}`,
           r.ok ? "ok" : "bad");
  }));
  $("#eSave").addEventListener("click", (e) => busy(e.target, "Saving…", async () => {
    const name = engField("eName");
    if (!name) { engSay("Give the engine a name.", "bad"); return; }
    const r = await api("/api/engines", {
      name, base_url: engField("eUrl"), api_key: engField("eKey"),
      model: engField("eModel"),
    });
    // the server warns when the model id and the endpoint disagree — show it
    engSay(r.message || "Saved.", /looks like/.test(r.message || "") ? "warn" : "ok");
    $("#eKey").value = "";
    LOADERS.engines(); refreshEnginePicker();
  }));

  $("#qGo").addEventListener("click", runSearch);
  $("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });

  $("#aSave").addEventListener("click", (e) => saveAuto(e.target));
  $("#aRun").addEventListener("click", async (e) => {
    let x;
    try { x = await followRun(e.target, "/api/jobs/auto/run"); }
    catch (err) { toast(err.message, "bad"); return; }
    if (x.ok === false) { toast(x.error || "The run didn't start.", "bad"); return; }
    toast(x.summary || "Ran once.", (x.sent || []).length ? "" : "warn");
    // a run that sent nothing says why, rather than leaving you guessing
    if (x.why_nothing) await drawReadiness();
    const prepared = x.prepared || [];
    if (prepared.length) {
      const host = $("#autoReady");
      const box = el("div", "ready is-ok");
      box.appendChild(el("div", "ready-head",
        `${prepared.length} portal form(s) filled — finish them yourself`));
      prepared.forEach((p) => {
        const row = el("div", "ready-row");
        row.append(el("span", "ready-what", `${p.title} — ${p.company || ""}`),
                   el("span", "ready-fix", (p.rehearsal ? "rehearsal, not submitted — " : "")
                      + (p.needs_you && p.needs_you.length
                         ? "you answer: " + p.needs_you.join("; ")
                         : `${p.answered} answer(s) filled in`)));
        box.appendChild(row);
      });
      host.appendChild(box);
    }
    const held = x.held || [];
    if (held.length) {
      const host = $("#autoReady");
      const box = el("div", "ready is-blocked");
      box.appendChild(el("div", "ready-head", `${held.length} held this run`));
      held.slice(0, 6).forEach((hh) => {
        const row = el("div", "ready-row");
        row.append(el("span", "ready-what", `${hh.title} — ${hh.company || ""}`),
                   el("span", "ready-fix", hh.reason));
        box.appendChild(row);
      });
      host.appendChild(box);
    }
    toastErrors(x);
    await refresh(); drawAutoPreview();
  });
  $("#aPilot").addEventListener("click", (e) => busy(e.target, "Setting up…", async () => {
    const x = await api("/api/jobs/autopilot", {});
    toast(x.note || "The daily loop is set up.");
    LOADERS.auto();
  }));
  $("#aDaily").addEventListener("change", async (e) => {
    try {
      await api("/api/jobs/schedule", { enabled: e.target.checked });
      // it said "never sends by itself", which was never true: the daily run
      // sends whatever clears every gate, unless rehearsal is on
      toast(e.target.checked
        ? "Daily run on — it finds, scores and drafts, and sends only what clears every gate (nothing while Rehearsal is on)."
        : "Daily run off.");
    } catch (err) { e.target.checked = !e.target.checked; toast(err.message, "bad"); }
  });

  $("#srcAdd").addEventListener("click", (e) => busy(e.target, "Checking…", async () => {
    const url = $("#srcUrl").value.trim();
    if (!url) return;
    const name = $("#srcName").value.trim()
      || url.replace(/^https?:\/\//, "").split("/")[0];
    await api("/api/jobs/sources", { name, url });
    $("#srcUrl").value = ""; $("#srcName").value = "";
    LOADERS.sources();
  }));
  $("#srcAuto").addEventListener("click", (e) => busy(e.target, "Checking boards…", async () => {
    const x = await api("/api/jobs/boards/auto", {});
    // "added" is a list; read as a number it toasted "Added  board(s)" and
    // never said what was tried or why nothing new appeared
    toast(x.message || `Added ${(x.added || []).length} board(s).`,
          (x.added || []).length ? "" : "warn");
    LOADERS.sources();
  }));
  $("#alertPaste").addEventListener("click", (e) => busy(e.target, "Reading…", async () => {
    const raw = $("#alertRaw").value.trim();
    if (!raw) return;
    const x = await api("/api/jobs/alerts/paste", { raw, sender: "" });
    $("#alertOut").textContent = `Found ${x.added ?? (x.roles || []).length} role(s) in it.`;
    $("#alertRaw").value = "";
  }));
  $("#alertFolder").addEventListener("click", (e) => busy(e.target, "Reading…", async () => {
    const x = await api("/api/jobs/alerts/folder", {});
    $("#alertOut").textContent = x.summary || `Read ${x.files ?? 0} file(s), ${x.added ?? 0} role(s).`;
  }));
  $("#alertGuide").addEventListener("click", async () => {
    try {
      const x = await api("/api/jobs/alerts/guide", undefined, "GET");
      $("#alertOut").textContent = (x.guide || []).join ? x.guide.join("\n") : (x.guide || x.why || "");
    } catch (e) { toast(e.message, "bad"); }
  });

  $("#tArchive").addEventListener("click", (e) => tidy("/api/jobs/archive",
    "Archiving…", { applied_before_days: 45 }, e.target,
    (x) => `Archived ${x.archived ?? x.count ?? 0}.`));
  $("#tDedupe").addEventListener("click", (e) => tidy("/api/jobs/dedupe",
    "Merging…", {}, e.target, (x) => `Merged ${x.merged ?? x.removed ?? 0} duplicate(s).`));
  $("#tSweep").addEventListener("click", (e) => tidy("/api/jobs/sweep",
    "Checking…", {}, e.target, (x) => x.summary || `Checked ${x.checked ?? 0}.`));
  $("#tPrune").addEventListener("click", (e) => tidy("/api/jobs/prune",
    "Pruning…", {}, e.target, (x) => `Pruned ${x.pruned ?? x.removed ?? 0}.`));

  try {
    const m = await api("/api/meta", undefined, "GET");
    brandLine($("#railSub"), m.brand || "Symbolic Synapse");
    S.profileReady = !!m.profile_ready;
    // the build the SERVER is running, beside the one this page was built
    // from — when they differ, the page is a cached copy and says so
    $("#build").textContent = m.build ? `build ${m.build}` : "";
    const stamped = (document.querySelector("link[rel=stylesheet]")
      || {}).getAttribute
      ? (document.querySelector("link[rel=stylesheet]").getAttribute("href") || "")
      : "";
    const v = (stamped.split("v=")[1] || "").trim();
    const live = String(m.build || "").replace(/[ :]/g, "");
    if (v && live && v !== live) {
      toast("This page is an old copy — reload it (Ctrl+F5) to get "
            + `build ${m.build}.`, "warn");
    }
    const sel = $("#engine");
    sel.innerHTML = "";
    ["Auto"].concat(m.engines || []).forEach((n) => {
      const o = el("option", "", n); o.value = n;
      if (n === m.default_engine) o.selected = true;
      sel.appendChild(o);
    });
    S.engine = sel.value;
    sel.addEventListener("change", () => { S.engine = sel.value; });
  } catch (e) { /* the window still works */ }

  show("overview");
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();

/* --- the last few: nothing the job search can do is left without a door */
function wireRemaining() {
  wireLearning();
  wireFinder();
  $("#ovCycle").addEventListener("click", async (e) => {
    let x;
    try { x = await followRun(e.target, "/api/jobs/cycle"); }
    catch (err) { toast(err.message, "bad"); return; }
    toast(x.summary || "Cycle complete.", (x.sent || []).length ? "" : "warn");
    toastErrors(x);
    LOADERS.overview();
  });
  $("#ovDiscover").addEventListener("click", (e) => busy(e.target, "Looking…", async () => {
    const x = await api("/api/jobs/discover", {});
    toast(`Found ${x.added ?? x.found ?? 0} new role(s).`);
    LOADERS.overview();
  }));
  $("#ovAdd").addEventListener("click", async () => {
    const title = prompt("Role title?"); if (!title) return;
    const company = prompt("Company?") || "";
    const url = prompt("Link to the posting (optional)") || "";
    try {
      await api("/api/jobs/add", { roles: [{ title, company, url, summary: "" }] });
      toast("Added.");
      LOADERS.overview();
    } catch (e) { toast(e.message, "bad"); }
  });
  $("#tClear").addEventListener("click", (e) => {
    if (!confirm("Remove every role that was never scored?")) return;
    tidy("/api/jobs/clear", "Clearing…", { never_scored: true }, e.target,
         (x) => `Cleared ${x.removed ?? x.cleared ?? 0}.`);
  });
  $("#tUnignore").addEventListener("click", (e) => tidy("/api/jobs/unignore",
    "…", { keys: [] }, e.target,
    (x) => `${x.restored ?? x.count ?? 0} role(s) can reappear in searches.`));
  $("#srcMatch").addEventListener("click", (e) => busy(e.target, "Matching…", async () => {
    const x = await api("/api/jobs/boards/match", undefined, "GET");
    const names = (x.boards || x.matches || x.suggested || []).map((b) => b.name || b).slice(0, 8);
    $("#srcMatchOut").textContent = names.length ? names.join(" · ")
                                                 : (x.note || "Fill in your profile first.");
  }));
}

async function drawSites() {
  const host = $("#portalSites");
  if (!host) return;
  host.innerHTML = "";
  let sites = [];
  try { sites = (await api("/api/jobs/portal/sites")).sites || []; }
  catch (e) { return; }
  if (!sites.length) {
    host.appendChild(el("p", "muted",
      "Nothing yet — it learns a site the first time you apply through it."));
    return;
  }
  sites.slice(0, 6).forEach((s) => {
    const row = el("div", "site-row");
    const head = el("div", "site-head");
    head.append(el("span", "site-name", s.site),
                el("span", "muted", `${s.seen}×${s.ats ? " · " + s.ats : ""}`));
    row.appendChild(head);
    if (s.steps && s.steps.length) {
      row.appendChild(el("div", "site-steps", s.steps.join("  →  ")));
    }
    if (s.questions && s.questions.length) {
      row.appendChild(el("div", "muted",
        "asks: " + s.questions.slice(0, 3).join("; ")));
    }
    host.appendChild(row);
  });
}

/* --- getting better with every application (agent/playbooks.py) --------- */
const OUTCOME_SAYS = { filled: "filled", submitted: "submitted", needs_answer: "needed you",
                       unknown_form: "stopped", needs_login: "wanted a sign-in",
                       needs_captcha: "had a captcha", closed: "closed", apply_by_email: "email only",
                       failed: "failed" };
async function drawLearning() {
  const host = $("#learnSites");
  if (!host) return;
  let d;
  try { d = await api("/api/jobs/portal/learning"); } catch (e) { return; }
  const tot = d.totals || {}, rec = d.recent || {};
  const st = $("#learnStats");
  st.innerHTML = "";
  const stat = (big, label, sub) => {
    const b = el("div", "learn-stat");
    b.append(el("b", "", String(big)), el("span", "", label));
    if (sub) b.appendChild(el("small", "muted", sub));
    return b;
  };
  st.append(
    stat(tot.sites || 0, "sites it knows",
         tot.routes ? `${tot.routes} with a known way to the form` : "learned by applying"),
    stat(tot.labels || 0, "labels learned", "boxes it now recognises"),
    stat(rec.last ? `${rec.last_without_you}/${rec.last}` : "—", "forms finished without you",
         rec.before ? `the ${rec.before} before: ${rec.before_without_you}/${rec.before}` : "of the latest applications"),
    stat(rec.last ? rec.last_turns : "—", "engine steps per form",
         rec.before ? `the ${rec.before} before: ${rec.before_turns}` : "fewer as it learns"));
  host.innerHTML = "";
  const sites = d.sites || [];
  if (!sites.length) {
    host.appendChild(el("p", "muted",
      "Nothing yet. It learns a site the first time it fills a form there."));
  }
  sites.slice(0, 12).forEach((s) => {
    const row = el("div", "learn-site");
    const head = el("div", "learn-site-head");
    const name = el("span", "site-name", s.site);
    name.title = s.site;
    head.appendChild(name);
    const forget = el("button", "btn sm ghost", "Forget");
    forget.title = "Forget what this site taught it. The next application starts fresh.";
    forget.addEventListener("click", () => {
      if (!confirm(`Forget what ${s.site} taught it?`)) return;
      busy(forget, "…", async () => {
        await api("/api/jobs/portal/learning/forget", { site: s.site });
        toast(`Forgot ${s.site}.`);
        drawLearning();
      });
    });
    head.appendChild(forget);
    row.appendChild(head);
    const runs = s.runs ? `${s.runs} application${s.runs === 1 ? "" : "s"}` : "learned from another site's form";
    const last = OUTCOME_SAYS[s.last_outcome] || s.last_outcome || "";
    row.appendChild(el("div", "learn-meta", [runs, s.ats, last ? `last: ${last}` : ""].filter(Boolean).join(" · ")));
    const bits = [];
    if ((s.route || []).length) bits.push("to the form: " + s.route.map((x) => `“${x}”`).join(" → "));
    if ((s.next || []).length) bits.push("next: " + s.next.map((x) => `“${x}”`).join(", "));
    if (s.labels) bits.push(`${s.labels} label${s.labels === 1 ? "" : "s"}`);
    (s.blocks || []).forEach((b) => bits.push(b === "needs_login" ? "asks for a sign-in"
      : b === "needs_captcha" ? "shows a captcha" : b));
    if (bits.length) row.appendChild(el("div", "site-steps", bits.join(" · ")));
    if ((s.turns || []).length > 1) {
      row.appendChild(el("div", "learn-trend", "engine steps, application by application: "
        + s.turns.join(" → ")));
    }
    (s.notes || []).forEach((n) => row.appendChild(el("div", "learn-note", n)));
    host.appendChild(row);
  });
  const ex = d.explore || {};
  $("#exOn").checked = !!ex.on;
  $("#exTurns").value = ex.turns ?? 12;
  $("#exTurns").disabled = !ex.on;
}

function wireLearning() {
  const on = $("#exOn"), turns = $("#exTurns");
  if (!on || on.dataset.wired) return;
  on.dataset.wired = "1";
  const save = async () => {
    const n = Math.max(0, Math.min(40, parseInt(turns.value || "0", 10) || 0));
    turns.value = n;
    await api("/api/jobs/auto", { explore: on.checked, explore_turns: n });
    turns.disabled = !on.checked;
  };
  on.addEventListener("change", async () => {
    try {
      await save();
      toast(on.checked ? "The engine may work out sites it doesn't know."
                       : "Only what it already knows: a site it doesn't know is left to you.");
    } catch (e) { toast(e.message, "bad"); }
  });
  turns.addEventListener("change", () => save().catch((e) => toast(e.message, "bad")));
}

/* --- the job board behind a careers page (boards.find_boards) ------------- */
function drawFinder(x) {
  const host = $("#finderOut");
  host.innerHTML = "";
  host.appendChild(el("p", (x.boards || []).length ? "" : "muted", x.message || ""));
  (x.boards || []).forEach((b) => {
    const row = el("div", "finder-row");
    const body = el("div");
    const n = b.found || 0;
    body.append(el("div", "item-t", b.name),
      el("div", "item-m", `${b.system} · ${n} role${n === 1 ? "" : "s"} listed now`
        + ((b.sample || []).length ? ` · e.g. ${b.sample.slice(0, 2).join(", ")}` : "")));
    row.appendChild(body);
    const add = el("button", "btn sm" + (b.added ? " ghost" : " primary"),
                   b.added ? "Already a source" : "Add as a source");
    add.disabled = !!b.added;
    add.addEventListener("click", () => busy(add, "Adding…", async () => {
      await api("/api/jobs/sources", { name: b.name, url: b.url, kind: b.kind });
      add.textContent = "Added";
      add.disabled = true;
      toast(`Added ${b.name}. Its roles are read with every search.`);
      if (LOADERS.sources) LOADERS.sources();
    }));
    row.appendChild(add);
    host.appendChild(row);
  });
  const looked = x.looked_at || [];
  if (looked.length > 1) {
    host.appendChild(el("p", "muted", "Looked at: "
      + looked.map((l) => String(l.url || "").replace(/^https?:\/\//, "")).join(", ")));
  }
}

function wireFinder() {
  const go = $("#finderGo"), box = $("#finderUrl");
  if (!go || go.dataset.wired) return;
  go.dataset.wired = "1";
  const run = () => {
    const url = box.value.trim();
    if (!url) { toast("Paste a company's careers page first.", "warn"); return; }
    busy(go, "Looking…", async () => drawFinder(await api("/api/jobs/sources/explore", { url })));
  };
  go.addEventListener("click", run);
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
}

/* --- how much it does without you ----------------------------------------- */
const LEVEL_NAMES ={ draft: "Draft only", prepare: "Prepare", email: "Send email", full: "Full" };
async function drawLevels() {
  const host = $("#levels");
  if (!host) return;
  let d;
  try { d = await api("/api/jobs/autonomy"); } catch (e) { return; }
  host.innerHTML = "";
  d.levels.forEach((lv) => {
    const b = el("button", "level" + (lv.id === d.level ? " is-on" : ""));
    b.type = "button"; b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", lv.id === d.level ? "true" : "false");
    b.append(el("b", "", LEVEL_NAMES[lv.id] || lv.id), el("span", "", lv.says));
    b.addEventListener("click", () => busy(b, "Setting…", async () => {
      await api("/api/jobs/autonomy", { level: lv.id });
      toast(`${LEVEL_NAMES[lv.id]}: ${lv.says}`);
      await LOADERS.auto();
    }));
    host.appendChild(b);
  });
  $("#levelNote").textContent = d.level === "custom"
    ? "Custom: the rules below have been set by hand. Pick a level to go back to one."
    : "Every level keeps the checks: minimum fit, no invented claims, the daily cap.";
}

/* --- run reports ------------------------------------------------------------ */
async function drawRuns() {
  const host = $("#runReports");
  if (!host) return;
  let runs = [];
  try { runs = (await api("/api/jobs/runs")).runs || []; } catch (e) { return; }
  host.innerHTML = "";
  if (!runs.length) { host.appendChild(el("p", "muted", "No runs yet.")); return; }
  const list = (title, items, fmt) => {
    if (!items || !items.length) return null;
    const box = el("div"); box.appendChild(el("h5", "", `${title} (${items.length})`));
    const ul = el("ul"); items.forEach((x) => ul.appendChild(el("li", "", fmt(x)))); box.appendChild(ul);
    return box;
  };
  runs.slice(0, 20).forEach((r, i) => {
    const det = el("details", "run");
    if (i === 0) det.open = true;
    const sum = el("summary");
    sum.append(el("span", "run-when", `${r.at} · ${r.kind === "cycle" ? "full cycle" : "auto-apply"}` +
                 (r.level ? ` · ${LEVEL_NAMES[r.level] || r.level}` : "")),
               el("span", "run-sum", r.summary || r.error || "Nothing happened."));
    det.appendChild(sum);
    const body = el("div", "run-body");
    const who = (x) => [x.title, x.company].filter(Boolean).join(" @ ");
    [list("Sent" + (r.dry_run ? " (rehearsal, nothing left)" : ""), r.sent, (x) => `${who(x)} → ${x.to || ""}`),
     list("Forms filled for you to finish", r.prepared, (x) => who(x) +
       (x.needs_you && x.needs_you.length ? ` — you answer: ${x.needs_you.join("; ")}` : "")),
     list("What its forms taught it", r.learned, (x) => x),
     list("Held", r.held, (x) => `${who(x)}: ${x.reason}`),
     list("Errors", Object.entries(r.errors || {}), ([e, n]) => (n > 1 ? `${n}× ` : "") + e),
    ].forEach((b) => b && body.appendChild(b));
    if (r.waiting_questions) {
      const w = el("p", "", `${r.waiting_questions} question(s) waiting on you under Answers.`);
      w.style.cursor = "pointer"; w.addEventListener("click", () => show("answers"));
      body.appendChild(w);
    }
    if (!body.childNodes.length) body.appendChild(el("p", "muted", "Nothing to report."));
    det.appendChild(body);
    host.appendChild(det);
  });
}

/* --- replies from your inbox (agent/inbox.py) ------------------------------ */
const REPLY_KIND = { interview: "interview", offer: "offer", rejection: "turned down",
                     reply: "reply", ack: "received" };
async function drawInbox() {
  const host = $("#ibRecent");
  if (!host) return;
  let d;
  try { d = await api("/api/jobs/inbox"); } catch (e) { return; }
  $("#ibOn").checked = !!d.settings.enabled;
  $("#ibHost").value = d.settings.imap_host || "";
  $("#ibHost").placeholder = d.imap_guess ? `IMAP server (default ${d.imap_guess})` : "IMAP server, e.g. imap.gmail.com";
  $("#ibNote").textContent = d.mail_ready
    ? "Or save reply emails as .eml files in " + d.folder + " — they're read too."
    : "Set up email sending first: reading uses the same login. Or save reply emails as .eml files in " + d.folder + ".";
  host.innerHTML = "";
  if (!d.recent.length) { host.appendChild(el("p", "muted", "No replies matched to your applications yet.")); return; }
  d.recent.forEach((r) => {
    const row = el("div", "rep");
    row.append(el("span", "rep-kind " + r.kind, REPLY_KIND[r.kind] || r.kind),
               el("div", "", `${r.role} @ ${r.company} — ${r.subject || ""}`),
               el("span", "rep-when", r.at || ""));
    host.appendChild(row);
  });
}
/* --- the weekly digest (agent/digest.py) ------------------------------------ */
async function drawDigest(showPreview) {
  let d;
  try { d = await api("/api/jobs/digest"); } catch (e) { return; }
  $("#dgOn").checked = !!d.settings.enabled;
  $("#dgTo").value = d.settings.to || "";
  const sel = $("#dgDay");
  if (!sel.options.length) d.days.forEach((n, i) => { const o = el("option", "", "Every " + n); o.value = i; sel.appendChild(o); });
  sel.value = String(d.settings.weekday || 0);
  if (showPreview) {
    const pre = $("#dgText");
    pre.hidden = false;
    pre.textContent = `Subject: ${d.preview.subject}\n\n${d.preview.text}`;
  }
}
function wireDigest() {
  const save = () => api("/api/jobs/digest", { enabled: $("#dgOn").checked,
    to: $("#dgTo").value.trim(), weekday: Number($("#dgDay").value) });
  $("#dgOn").addEventListener("change", async () => { await save();
    toast($("#dgOn").checked ? `Weekly digest on: ${$("#dgDay").selectedOptions[0].text.toLowerCase()}, with the morning run.` : "Weekly digest off."); });
  $("#dgTo").addEventListener("change", save);
  $("#dgDay").addEventListener("change", save);
  $("#dgPreview").addEventListener("click", (e) => busy(e.target, "Building…", async () => { await save(); await drawDigest(true); }));
  $("#dgSend").addEventListener("click", (e) => busy(e.target, "Sending…", async () => {
    await save();
    const x = await api("/api/jobs/digest/send", {});
    toast(`Digest sent to ${x.to}.`);
  }));
}

/* --- updates (agent/updater.py) --------------------------------------------- */
async function drawBackups() {
  const host = $("#backupBody");
  if (!host) return;
  let st = {};
  try { st = await api("/api/jobs/backups"); } catch (e) { return; }
  host.innerHTML = "";
  const row = el("div", "actions");
  const make = el("button", "btn primary", "Back up now");
  make.addEventListener("click", () => busy(make, "Backing up…", async () => {
    const x = await api("/api/jobs/backups", {});
    window.location.href = x.url;
    toast(`Backed up ${x.files} file(s).`); drawBackups();
  }));
  const pick = el("input"); pick.type = "file"; pick.accept = ".zip"; pick.hidden = true;
  const rest = el("button", "btn", "Restore from a backup…");
  rest.addEventListener("click", () => pick.click());
  pick.addEventListener("change", () => {
    const file = pick.files && pick.files[0];
    pick.value = "";
    if (!file) return;
    if (!confirm(`Restore from ${file.name}? What's here now is backed up first.`)) return;
    busy(rest, "Restoring…", async () => {
      const data = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(r.result); r.onerror = () => rej(new Error("Couldn't read that file."));
        r.readAsDataURL(file);
      });
      const x = await api("/api/jobs/backups/restore", { data });
      alert(x.message);
    });
  });
  row.append(make, rest, pick);
  host.appendChild(row);
  (st.backups || []).slice(0, 5).forEach((b) => {
    const a = el("a", "muted backup-link", `${b.at} — ${(b.size / 1024).toFixed(0)} KB`);
    a.href = "/api/jobs/backups/file?name=" + encodeURIComponent(b.filename);
    host.appendChild(a);
  });
  if (!(st.backups || []).length) host.appendChild(el("p", "muted", "No backups yet."));
}

async function drawPhone() {
  const host = $("#phoneBody");
  if (!host) return;
  let st;
  try { st = await api("/api/phone"); } catch (e) { host.textContent = "Couldn't read it."; return; }
  host.innerHTML = "";
  const row = el("div", "actions");
  const tog = el("button", "btn" + (st.enabled ? "" : " primary"), st.enabled ? "Turn off" : "Turn on");
  tog.addEventListener("click", () => busy(tog, "…", async () => {
    await api("/api/phone", { enabled: !st.enabled }); drawPhone();
  }));
  row.appendChild(tog);
  if (st.enabled) {
    const rot = el("button", "btn sm ghost", "New key");
    rot.title = "The old link stops working at once — use it if the link was seen by anyone else.";
    rot.addEventListener("click", () => {
      if (!confirm("Make a new key? Your phone's current link stops working; scan again.")) return;
      busy(rot, "…", async () => { await api("/api/phone/rotate", {}); drawPhone(); });
    });
    row.appendChild(rot);
  }
  host.appendChild(row);
  if (st.error) host.appendChild(el("p", "prep-gap", st.error));
  if (!st.enabled) return;
  if (!(st.links || []).length) {
    host.appendChild(el("p", "muted", "This computer has no network address a phone can reach."));
    return;
  }
  const grid = el("div", "phone-links");
  st.links.forEach((l) => {
    const c = el("div", "phone-link");
    const q = el("div", "phone-qr");
    q.innerHTML = l.qr || "";                    // SVG from our own encoder (agent/qr.py)
    c.appendChild(q);
    c.appendChild(el("b", "", l.kind === "tailscale" ? "Anywhere, via Tailscale" : "On this Wi-Fi"));
    c.appendChild(el("p", "muted", l.kind === "tailscale"
      ? "Encrypted end to end — works away from home."
      : "Same network only, and not encrypted on it: fine at home, not on shared Wi-Fi."));
    const copy = el("button", "btn sm", "Copy link");
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(l.url); toast("Copied — it contains the key; send it only to yourself."); }
      catch (e) { prompt("Copy this link:", l.url); }
    });
    c.appendChild(copy);
    grid.appendChild(c);
  });
  host.appendChild(grid);
  host.appendChild(el("p", "muted", "Scan with your phone's camera. Windows may ask to let Python " +
    "through the firewall on private networks — allow it, or the phone can't connect."));
}

async function drawUpdates() {
  let st;
  try { st = await api("/api/updates"); } catch (e) { return; }
  $("#upSrc").value = st.source || "";
  $("#upBack").hidden = !st.can_roll_back;
  $("#upNote").textContent = `This copy: ${st.build}.` + (st.can_verify ? ""
    : " It has no signing key yet, so it can't install updates (see tools/make_release.py).") +
    (st.last_install && st.last_install.to ? ` Last update: ${st.last_install.from} → ${st.last_install.to}.` : "");
}
function wireUpdates() {
  const saveSrc = () => api("/api/updates/source", { source: $("#upSrc").value.trim() });
  $("#upSrc").addEventListener("change", saveSrc);
  $("#upCheck").addEventListener("click", (e) => busy(e.target, "Checking…", async () => {
    await saveSrc();
    const c = await api("/api/updates/check", {});
    $("#upGo").hidden = !c.newer;
    $("#upNote").textContent = c.newer ? `New: ${c.latest} (you have ${c.current}). ${c.notes || ""}`
                                       : `Up to date: ${c.current}.`;
  }));
  $("#upGo").addEventListener("click", (e) => {
    if (!confirm("Install the update? It's checked against your signing key first; the files it replaces are kept so you can roll back.")) return;
    busy(e.target, "Downloading and checking…", async () => {
      const x = await api("/api/updates/install", {});
      $("#upNote").textContent = `${x.message} (${x.from} → ${x.to}${x.packages ? "; " + x.packages : ""})`;
      $("#upGo").hidden = true; $("#upBack").hidden = false;
      toast("Updated. Restart Agent Jo Jobs to run the new version.");
    });
  });
  $("#upBack").addEventListener("click", (e) => {
    if (!confirm("Roll back the last update?")) return;
    busy(e.target, "Rolling back…", async () => {
      const x = await api("/api/updates/rollback", {});
      $("#upNote").textContent = x.message; $("#upBack").hidden = true;
      toast("Rolled back. Restart Agent Jo Jobs.");
    });
  });
}

function wireInbox() {
  const save = () => api("/api/jobs/inbox", { enabled: $("#ibOn").checked, imap_host: $("#ibHost").value.trim() });
  $("#ibOn").addEventListener("change", async () => { await save(); toast($("#ibOn").checked ? "Replies will be read with every full cycle." : "Inbox reading off."); });
  $("#ibHost").addEventListener("change", save);
  $("#ibCheck").addEventListener("click", (e) => busy(e.target, "Reading replies…", async () => {
    await save();
    const x = await api("/api/jobs/inbox/check", {});
    const n = (x.found || []).length;
    toast(n ? `${n} repl(y/ies) to your applications: ` + x.found.slice(0, 3).map((f) =>
      `${f.company} (${REPLY_KIND[f.kind] || f.kind}${f.moved_to ? " → " + f.moved_to : ""})`).join(", ")
      : `Checked ${x.checked} new message(s); none were about your applications.`, n ? "" : "warn");
    if (x.warning) toast(x.warning, "warn");
    await drawInbox(); await refresh();
  }));
}

const _prevAuto = LOADERS.auto;
LOADERS.auto = async function () {
  await _prevAuto();
  drawLevels();
  drawEmail();
  drawRuns();
  drawSites();
  drawLearning();
  const host = $("#portalHistory");
  host.innerHTML = "";
  try {
    const h = await api("/api/jobs/portal/history", undefined, "GET");
    const runs = h.runs || [];
    if (!runs.length) {
      host.appendChild(el("p", "muted", h.ready === false
        ? "The portal applier needs a browser: run  playwright install chromium"
        : "None yet."));
    }
    runs.slice(0, 10).forEach((r) => {
      const it = el("div", "item static");
      const body = el("div");
      body.append(el("div", "item-t", r.title || r.company || "application"),
        el("div", "item-m", [r.company, r.when || r.at].filter(Boolean).join(" · ")));
      it.append(el("div", "mono", initial(r.company)), body,
        el("span", "tag" + (r.submitted ? " sent" : ""), r.submitted ? "submitted" : "rehearsed"));
      host.appendChild(it);
    });
  } catch (e) { host.appendChild(el("p", "muted", "Couldn't read the history.")); }
};

document.addEventListener("DOMContentLoaded", wireRemaining);
if (document.readyState !== "loading") setTimeout(wireRemaining, 0);
