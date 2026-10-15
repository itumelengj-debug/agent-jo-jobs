/* The phone companion. The key comes in the address's #fragment (browsers
 * never send that part over the network), is kept on this phone, and is
 * removed from the address bar so a screenshot doesn't show it. */
"use strict";
const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
let KEY = "";
(function readKey() {
  const m = location.hash.match(/k=([A-Za-z0-9_-]{20,})/);
  if (m) {
    KEY = m[1];
    try { localStorage.setItem("jo-phone-key", KEY); } catch (e) {}
    history.replaceState(null, "", location.pathname);
  } else {
    try { KEY = localStorage.getItem("jo-phone-key") || ""; } catch (e) {}
  }
})();

async function api(path, body) {
  const opts = { headers: { "X-Phone-Key": KEY } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  let d = {};
  try { d = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(d.error || ("Error " + r.status));
  return d;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, 4200);
}

async function busy(btn, fn) {
  btn.disabled = true;
  try { await fn(); } catch (e) { toast(e.message); } finally { btn.disabled = false; }
}

function whenText(at) {
  const d = new Date(String(at || "").replace(" ", "T"));
  if (isNaN(d)) return at || "";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })
    + ", " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

async function load() {
  const main = $("#main");
  if (!KEY) {
    main.innerHTML = "";
    main.appendChild(el("p", "pad", "Open this page by scanning the code in Agent Jo Jobs on your " +
      "computer (Engines → Phone companion)."));
    return;
  }
  let s;
  try { s = await api("/api/state"); }
  catch (e) { main.innerHTML = ""; main.appendChild(el("p", "pad error", e.message)); return; }
  $("#level").textContent = s.level_says || "";
  main.innerHTML = "";

  if ((s.interviews || []).length) {
    main.appendChild(el("h2", "", "Interviews"));
    s.interviews.forEach((x) => {
      const c = el("div", "card");
      c.append(el("h3", "", `${x.title} @ ${x.company}`), el("p", "muted", whenText(x.at)));
      if (x.link) {
        const b = el("button", "", "Open the meeting link");
        b.addEventListener("click", () => window.open(x.link, "_blank", "noopener"));
        const row = el("div", "row"); row.appendChild(b); c.appendChild(row);
      }
      main.appendChild(c);
    });
  }

  main.appendChild(el("h2", "", `Questions only you can answer (${(s.questions || []).length})`));
  if (!(s.questions || []).length) main.appendChild(el("p", "empty", "None waiting."));
  (s.questions || []).forEach((q) => {
    const c = el("div", "card");
    c.appendChild(el("h3", "", q.question));
    if (q.roles) c.appendChild(el("p", "muted", `Holding up ${q.roles} application(s).`));
    const ta = el("textarea"); ta.placeholder = "Your answer — saved and reused on every form that asks.";
    const b = el("button", "primary", "Save answer");
    b.addEventListener("click", () => busy(b, async () => {
      await api("/api/answer", { question: q.question, answer: ta.value });
      toast("Saved. The next run uses it.");
      load();
    }));
    const row = el("div", "row"); row.appendChild(b);
    c.append(ta, row);
    main.appendChild(c);
  });

  main.appendChild(el("h2", "", `Drafts waiting for you (${(s.drafts || []).length})`));
  if (!(s.drafts || []).length) main.appendChild(el("p", "empty", "Nothing waiting."));
  (s.drafts || []).forEach((d) => {
    const c = el("div", "card");
    c.appendChild(el("h3", "", `${d.title} @ ${d.company}`));
    const tags = el("div");
    if (d.fit != null) tags.appendChild(el("span", "tag", `fit ${d.fit}`));
    tags.appendChild(el("span", "tag", d.how === "email" ? "by email" : "company form"));
    if (d.approved) tags.appendChild(el("span", "tag ok", "approved"));
    if (d.held) tags.appendChild(el("span", "tag warn", "held"));
    c.appendChild(tags);
    if (d.held) {
      const ul = el("ul", "problems");
      d.problems.forEach((p) => ul.appendChild(el("li", "", p)));
      c.appendChild(ul);
      c.appendChild(el("p", "muted", "Claims your profile can't back — fix it at your computer."));
    }
    const det = el("details");
    det.appendChild(el("summary", "", "Read the letter"));
    det.appendChild(el("p", "letter", (d.subject ? d.subject + "\n\n" : "") + d.body));
    c.appendChild(det);
    const row = el("div", "row");
    if (!d.held && !d.approved) {
      const ok = el("button", "primary", "Approve");
      ok.addEventListener("click", () => busy(ok, async () => {
        const x = await api("/api/approve", { key: d.key });
        toast(x.then || "Approved."); load();
      }));
      row.appendChild(ok);
    }
    const no = el("button", "danger", "Skip this role");
    no.addEventListener("click", () => busy(no, async () => {
      if (!confirm(`Skip ${d.title} @ ${d.company}? It won't be applied to.`)) return;
      await api("/api/skip", { key: d.key }); toast("Skipped."); load();
    }));
    row.appendChild(no);
    c.appendChild(row);
    main.appendChild(c);
  });

  if (s.last_run) {
    main.appendChild(el("h2", "", "Last run"));
    const c = el("div", "card");
    c.append(el("p", "muted", s.last_run.at), el("p", "", s.last_run.said || "—"));
    main.appendChild(c);
  }

  if (s.level !== "draft") {
    const p = el("button", "danger pause", "Pause — send nothing until I say");
    p.addEventListener("click", () => busy(p, async () => {
      if (!confirm("Pause? It will keep finding and drafting, but send and submit nothing.")) return;
      await api("/api/pause", {}); toast("Paused. Change it back at your computer."); load();
    }));
    main.appendChild(p);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#reload").addEventListener("click", load);
  load();
});
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
