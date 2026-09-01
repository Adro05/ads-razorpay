/* Employee activity tracker - the merchant-facing surface.
 *
 * Deliberately plain: no framework, no CDN, no build step. A monitoring tool
 * that accuses people should be readable end to end by whoever deploys it.
 */

const state = {
  employees: [],
  statusFilter: "",
  search: "",
  flagState: "",
  decisions: ["confirmed_issue", "cleared", "needs_more_info", "escalated"],
  featureLabels: {},
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${body}`);
  }
  return res.json();
}

const fmtPct = (v) => `${(Number(v) * 100).toFixed(1)}%`;
const fmtNum = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
const titleCase = (s) => String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const ICONS = {
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a1.5 1.5 0 0 0 1.29 2.25h17.78A1.5 1.5 0 0 0 22.18 18L13.71 3.86a1.5 1.5 0 0 0-2.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  eye: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M1.5 12S5 5 12 5s10.5 7 10.5 7-3.5 7-10.5 7S1.5 12 1.5 12Z"/><circle cx="12" cy="12" r="3"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9.5"/><path d="m7.5 12.5 3 3 6-6.5"/></svg>',
  bolt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/></svg>',
  inbox: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 13h4.5l2 3h5l2-3H21"/><path d="M5.5 5h13L21 13v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5L5.5 5Z"/></svg>',
  help: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9.5"/><path d="M9.5 9.2a2.5 2.5 0 0 1 4.8 1c0 1.7-2.3 2-2.3 3.6"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
};

const PAGE_TITLES = {
  activity: "Activity tracker",
  flags: "Review queue",
  audit: "Audit trail",
  metrics: "Honest metrics",
};

function initials(name) {
  return String(name || "?").trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
}

function goToTab(name) {
  const tab = document.querySelector(`.side-tab[data-tab="${name}"]`);
  if (tab) tab.click();
}

function when(iso) {
  if (!iso) return "never";
  const then = new Date(iso);
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (!Number.isFinite(mins)) return iso;
  if (Math.abs(mins) < 60) return `${mins} min ago`;
  if (Math.abs(mins) < 60 * 48) return `${Math.round(mins / 60)} h ago`;
  return then.toLocaleDateString();
}

/* ------------------------------------------------------------- overview */
async function loadOverview() {
  const data = await api("/api/overview");
  const meta = $("#scan-meta");
  if (!data.scan) {
    meta.textContent = "No scans yet - run a scan to populate the tracker.";
    return;
  }
  const t = data.thresholds || {};
  meta.textContent =
    `scan ${data.scan.scan_id} · window ends ${new Date(data.scan.as_of).toLocaleString()} · ` +
    `${Number(data.scan.events_ingested).toLocaleString()} actions over ` +
    `${t.window_days}d (baseline ${t.baseline_days}d) · model ${data.scan.model_version}`;

  const chain = $("#chain-status");
  const v = data.audit || {};
  chain.textContent = v.ok
    ? `audit chain intact · ${v.entries} entries`
    : `audit chain BROKEN at #${v.broken_at}`;
  chain.className = `chain ${v.ok ? "ok" : "bad"}`;

  const c = data.counts || {};
  const tiles = [
    ["kpi-flag", "alert", c.flagged, "Flagged for review"],
    ["kpi-watch", "eye", c.watch, "On watch"],
    ["kpi-clear", "check", c.clear, "Clear"],
    ["kpi-accent", "bolt", c.active_now, "Handling funds now"],
    ["kpi-accent", "inbox", c.open_flags, "Flags awaiting a reviewer"],
    ["kpi-idle", "help", c.insufficient_data, "Too little activity to score"],
  ];
  const wrap = $("#tiles");
  wrap.innerHTML = "";
  tiles.forEach(([cls, icon, value, label]) => {
    const tile = el("div", `kpi-card ${cls}`);
    const iconWrap = el("div", "kpi-icon");
    iconWrap.innerHTML = ICONS[icon];
    tile.append(iconWrap);
    tile.append(el("div", "kpi-value", value === undefined ? "-" : String(value)));
    tile.append(el("div", "kpi-label", label));
    wrap.append(tile);
  });

  const badgeText = c.open_flags ? String(c.open_flags) : "";
  const sideBadge = $("#side-flags-badge");
  sideBadge.hidden = !c.open_flags;
  sideBadge.textContent = badgeText;
  const bellBadge = $("#bell-badge");
  bellBadge.hidden = !c.open_flags;
  bellBadge.textContent = badgeText;

  renderStatusChart(c);
}

/* ------------------------------------------------------------ status chart */
function renderStatusChart(c) {
  const rows = [
    ["flagged", "Flagged", c.flagged, "var(--flag)"],
    ["watch", "Watch", c.watch, "var(--watch)"],
    ["clear", "Clear", c.clear, "var(--clear)"],
    ["insufficient_data", "Not scored", c.insufficient_data, "var(--idle)"],
  ];
  const total = Math.max(1, c.employees || rows.reduce((s, [, , v]) => s + (v || 0), 0));
  const wrap = $("#status-chart");
  wrap.innerHTML = "";
  if (!c.employees) {
    wrap.append(el("p", "empty", "No scan yet."));
    return;
  }
  const bars = el("div", "chart-bars");
  rows.forEach(([, label, value, color]) => {
    const row = el("div", "chart-row");
    row.append(el("div", "chart-label", label));
    const track = el("div", "chart-track");
    const fill = el("span", "chart-fill");
    fill.style.width = `${Math.max(2, ((value || 0) / total) * 100)}%`;
    fill.style.background = color;
    track.append(fill);
    row.append(track);
    row.append(el("div", "chart-count", String(value || 0)));
    bars.append(row);
  });
  wrap.append(bars);
}

/* -------------------------------------------------------- dashboard panels */
function renderTopFlags() {
  const wrap = $("#top-flags");
  wrap.innerHTML = "";
  const rows = state.employees
    .filter((e) => e.status === "flagged")
    .sort((a, b) => b.risk_score - a.risk_score)
    .slice(0, 4);
  if (!rows.length) {
    wrap.append(el("p", "empty", "Nothing flagged right now."));
    return;
  }
  rows.forEach((e) => {
    const card = el("div", "alert-card");
    const icon = el("div", "alert-icon");
    icon.innerHTML = ICONS.alert;
    card.append(icon);
    const main = el("div", "alert-main");
    main.append(el("div", "alert-name", e.employee_name));
    main.append(el("div", "alert-meta", e.summary || `${e.role} · ${e.store_id}`));
    card.append(main);
    const score = el("div", "alert-score", String(Math.round(e.risk_score)));
    score.append(el("small", null, " /100"));
    card.append(score);
    card.addEventListener("click", () => openDrawer(e.employee_id));
    wrap.append(card);
  });
}

function renderActiveList() {
  const wrap = $("#active-list");
  wrap.innerHTML = "";
  const rows = state.employees.filter((e) => e.presence === "active").slice(0, 6);
  if (!rows.length) {
    wrap.append(el("p", "empty", "No one is actively handling funds right now."));
    return;
  }
  rows.forEach((e) => {
    const row = el("div", "active-row");
    row.append(el("div", "avatar", initials(e.employee_name)));
    const main = el("div", "active-main");
    main.append(el("div", "active-name", e.employee_name));
    main.append(el("div", "active-role", `${e.role} · ${e.store_id}`));
    row.append(main);
    row.append(el("span", `pill ${e.status}`, titleCase(e.status)));
    row.addEventListener("click", () => openDrawer(e.employee_id));
    wrap.append(row);
  });
}

/* -------------------------------------------------------- recent activity */
async function loadRecentActivity() {
  let data;
  try {
    data = await api("/api/audit?limit=6");
  } catch (_) {
    return;
  }
  const wrap = $("#recent-feed");
  wrap.innerHTML = "";
  const entries = data.entries || [];
  if (!entries.length) {
    wrap.append(el("p", "empty", "No activity recorded yet."));
    return;
  }
  entries.forEach((e) => {
    const row = el("div", "feed-row");
    row.append(el("span", "feed-dot"));
    const main = el("div", "feed-main");
    const text = el("div", "feed-text");
    text.append(el("b", null, titleCase(e.action)));
    text.append(document.createTextNode(` by ${e.actor}`));
    main.append(text);
    main.append(el("div", "feed-time", when(e.ts)));
    row.append(main);
    wrap.append(row);
  });
}

/* ------------------------------------------------------------ employees */
async function loadEmployees() {
  const data = await api("/api/employees");
  state.employees = data.employees || [];
  renderEmployees();
  renderTopFlags();
  renderActiveList();
}

function renderEmployees() {
  const grid = $("#employee-grid");
  grid.innerHTML = "";
  const term = state.search.trim().toLowerCase();
  const rows = state.employees.filter((e) => {
    if (state.statusFilter && e.status !== state.statusFilter) return false;
    if (!term) return true;
    return [e.employee_name, e.role, e.store_id, e.employee_id]
      .join(" ").toLowerCase().includes(term);
  });

  $("#employee-empty").hidden = rows.length > 0;

  rows.forEach((e) => {
    const card = el("div", `card ${e.status}`);
    card.tabIndex = 0;

    const head = el("div", "card-head");
    const left = el("div");
    left.append(el("div", "card-name", e.employee_name));
    left.append(el("div", "card-meta", `${e.role} · ${e.store_id} · ${e.employee_id}`));
    const score = el("div", "score");
    score.append(document.createTextNode(
      e.status === "insufficient_data" ? "-" : Number(e.risk_score).toFixed(0)
    ));
    score.append(el("small", null, " /100"));
    head.append(left, score);
    card.append(head);

    const bar = el("div", "bar");
    const fill = el("span", e.status);
    fill.style.width = `${Math.max(2, Math.min(100, e.risk_score))}%`;
    bar.append(fill);
    card.append(bar);

    card.append(el("div", "card-summary", e.summary || ""));

    const row = el("div", "status-row");
    const presence = el("span", "pill");
    presence.append(el("span", `dot ${e.presence}`));
    presence.append(document.createTextNode(titleCase(e.presence)));
    row.append(presence);
    row.append(el("span", `pill ${e.status}`, titleCase(e.status)));
    row.append(el("span", "pill", `${e.event_count} actions`));
    card.append(row);

    card.addEventListener("click", () => openDrawer(e.employee_id));
    card.addEventListener("keypress", (ev) => {
      if (ev.key === "Enter") openDrawer(e.employee_id);
    });
    grid.append(card);
  });
}

/* --------------------------------------------------------------- drawer */
async function openDrawer(employeeId) {
  const body = $("#drawer-body");
  body.innerHTML = "<p class='empty'>Loading…</p>";
  $("#drawer").hidden = false;
  $("#drawer-backdrop").hidden = false;

  let d;
  try {
    d = await api(`/api/employees/${encodeURIComponent(employeeId)}`);
  } catch (err) {
    body.innerHTML = `<p class='empty'>${err.message}</p>`;
    return;
  }

  body.innerHTML = "";
  body.append(el("h2", null, d.employee_name));
  body.append(el("p", "sub",
    `${d.role} · ${d.store_id} · ${d.employee_id} · last action ${when(d.last_event_at)}`));

  const head = el("div", "status-row");
  head.append(el("span", `pill ${d.status}`, `${titleCase(d.status)} · ${Number(d.risk_score).toFixed(0)}/100`));
  head.append(el("span", "pill", `compared with: ${d.peer_group} (${d.peer_group_size})`));
  head.append(el("span", "pill", `${d.event_count} actions in window`));
  body.append(head);

  /* why ------------------------------------------------------------- */
  body.append(el("h3", null, "Why this score"));
  if (!d.reasons || d.reasons.length === 0) {
    body.append(el("p", "caveats",
      d.status === "insufficient_data"
        ? d.summary
        : "No individually reportable deviation. Nothing here is evidence of anything."));
  } else {
    d.reasons.forEach((r) => {
      const box = el("div", "reason");
      const rh = el("div", "reason-head");
      rh.append(el("strong", null, r.headline));
      rh.append(el("span", "basis", `${(r.contribution * 100).toFixed(0)}% of score`));
      box.append(rh);
      box.append(el("p", null, r.detail));
      const contrib = el("div", "contrib");
      const span = el("span");
      span.style.width = `${Math.min(100, r.contribution * 100)}%`;
      contrib.append(span);
      box.append(contrib);
      box.append(el("div", "basis",
        `basis: ${r.basis}${r.z ? ` · z = ${Number(r.z).toFixed(2)}` : ""}`));
      body.append(box);
    });
  }

  /* components ------------------------------------------------------- */
  body.append(el("h3", null, "Score components"));
  const comp = el("table", "table");
  comp.innerHTML = "<thead><tr><th>component</th><th class='num'>0-100</th></tr></thead>";
  const ctb = el("tbody");
  Object.entries(d.components || {}).forEach(([k, v]) => {
    const tr = el("tr");
    tr.append(el("td", null, titleCase(k)));
    tr.append(el("td", "num", v === null ? "not available" : Number(v).toFixed(1)));
    ctb.append(tr);
  });
  comp.append(ctb);
  body.append(comp);

  /* features --------------------------------------------------------- */
  body.append(el("h3", null, "Window features"));
  const ft = el("table", "table");
  ft.innerHTML = "<thead><tr><th>feature</th><th class='num'>value</th></tr></thead>";
  const ftb = el("tbody");
  Object.entries(d.features || {}).forEach(([k, v]) => {
    const tr = el("tr");
    tr.append(el("td", null, state.featureLabels[k] || titleCase(k)));
    const isPct = !["avg_refund_amount", "avg_discount_pct"].includes(k);
    tr.append(el("td", "num", isPct ? fmtPct(v) : fmtNum(v)));
    ftb.append(tr);
  });
  ft.append(ftb);
  body.append(ft);

  /* open flags + review ---------------------------------------------- */
  const openFlags = (d.flags || []).filter((f) => f.state === "open");
  if (d.flags && d.flags.length) {
    body.append(el("h3", null, "Flags and reviews"));
    d.flags.forEach((f) => body.append(renderFlagCard(f)));
  }
  if (openFlags.length === 0 && d.status === "flagged") {
    body.append(el("p", "caveats",
      "Flagged in this scan; the flag record appears here once the scan is persisted."));
  }

  /* timeline --------------------------------------------------------- */
  body.append(el("h3", null, "Recent actions"));
  const tl = el("table", "table");
  tl.innerHTML = "<thead><tr><th>when</th><th>action</th><th class='num'>amount</th>" +
    "<th>counterparty</th><th>original</th></tr></thead>";
  const tb = el("tbody");
  (d.timeline || []).forEach((t) => {
    const tr = el("tr", t.action_type === "refund" || t.action_type === "void" ? "high" : "");
    tr.append(el("td", null, new Date(t.timestamp).toLocaleString()));
    tr.append(el("td", null, titleCase(t.action_type)));
    tr.append(el("td", "num", fmtNum(t.amount)));
    tr.append(el("td", null, t.customer_ref || "-"));
    tr.append(el("td", "mono", t.original_txn_id || (t.action_type === "refund" ? "none" : "-")));
    tb.append(tr);
  });
  tl.append(tb);
  body.append(tl);
}

function renderFlagCard(f) {
  const card = el("div", "flag-card");
  card.append(el("div", null, `${f.flag_id} · raised ${when(f.created_at)} · score ${Number(f.risk_score).toFixed(0)}`));
  card.append(el("div", "muted", f.summary));

  (f.reviews || []).forEach((r) => {
    card.append(el("div", "muted",
      `reviewed by ${r.reviewer} - ${titleCase(r.decision)} (${when(r.created_at)})${r.notes ? `: ${r.notes}` : ""}`));
  });

  if (f.state === "open") {
    const form = el("form", "review");
    const row = el("div", "review-row");
    const reviewer = el("input");
    reviewer.placeholder = "Your name (recorded in the audit log)";
    reviewer.required = true;
    const decision = el("select");
    state.decisions.forEach((d) => {
      const opt = el("option", null, titleCase(d));
      opt.value = d;
      decision.append(opt);
    });
    row.append(reviewer, decision);
    const notes = el("textarea");
    notes.placeholder = "What did you check, and what did you find?";
    const submit = el("button", "btn primary", "Record decision");
    submit.type = "submit";
    form.append(row, notes, submit);

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      submit.disabled = true;
      try {
        await api(`/api/flags/${encodeURIComponent(f.flag_id)}/review`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            reviewer: reviewer.value, decision: decision.value, notes: notes.value,
          }),
        });
        form.replaceWith(el("div", "muted", "Decision recorded and written to the audit trail."));
        loadFlags();
        loadAudit();
        loadOverview();
        loadRecentActivity();
      } catch (err) {
        submit.disabled = false;
        form.append(el("div", "muted", `Could not record: ${err.message}`));
      }
    });
    card.append(form);
  }
  return card;
}

function closeDrawer() {
  $("#drawer").hidden = true;
  $("#drawer-backdrop").hidden = true;
}

/* ---------------------------------------------------------------- flags */
async function loadFlags() {
  const query = state.flagState ? `?state=${state.flagState}` : "";
  const data = await api(`/api/flags${query}`);
  const list = $("#flag-list");
  list.innerHTML = "";
  if (!data.flags.length) {
    list.append(el("p", "empty", "No flags recorded."));
    return;
  }
  data.flags.forEach((f) => {
    const card = renderFlagCard(f);
    const head = el("div");
    head.append(el("strong", null, f.employee_name));
    head.append(document.createTextNode(` · ${f.state}`));
    card.prepend(head);
    list.append(card);
  });
}

/* ---------------------------------------------------------------- audit */
async function loadAudit() {
  const data = await api("/api/audit?limit=250");
  const v = data.verification || {};
  const note = $("#audit-verification");
  note.className = `note ${v.ok ? "ok" : "bad"}`;
  note.textContent = v.ok
    ? `Hash chain verified over ${v.entries} entries. Head ${String(v.head).slice(0, 16)}…  ` +
      "Each entry commits to the one before it, so a deleted or edited record breaks every link after it."
    : `Chain verification FAILED at entry #${v.broken_at}: ${v.problem}`;

  const tbody = $("#audit-table tbody");
  tbody.innerHTML = "";
  (data.entries || []).forEach((e) => {
    const tr = el("tr");
    tr.append(el("td", "mono", `#${e.seq}`));
    tr.append(el("td", null, new Date(e.ts).toLocaleString()));
    tr.append(el("td", null, e.actor));
    tr.append(el("td", null, e.action));
    tr.append(el("td", "mono", e.entity_id));
    const detail = e.payload || {};
    const bits = [];
    if (detail.employee_id) bits.push(detail.employee_id);
    if (detail.risk_score !== undefined) bits.push(`score ${detail.risk_score}`);
    if (detail.decision) bits.push(`decision: ${detail.decision}`);
    if (detail.flags_raised !== undefined) bits.push(`${detail.flags_raised} flags`);
    if (detail.events !== undefined) bits.push(`${detail.events} events`);
    tr.append(el("td", "muted", bits.join(" · ")));
    tbody.append(tr);
  });
}

/* -------------------------------------------------------------- metrics */
async function loadMetrics() {
  const data = await api("/api/metrics");
  const body = $("#metrics-body");
  body.innerHTML = "";
  if (!data.available) {
    body.append(el("p", "empty", data.hint || "No evaluation has been run."));
    return;
  }
  const s = data.summary || {};
  const mean = (arr) => (arr && arr.length
    ? (arr.reduce((a, b) => a + b, 0) / arr.length) : 0);

  body.append(el("p", "caveats",
    `Measured on ${data.header}, at the thresholds actually configured ` +
    `(flag >= ${data.thresholds.flag_score}, watch >= ${data.thresholds.watch_score}).`));

  const grid = el("div", "metric-grid");
  [
    ["Precision (flagged)", mean(s.flagged_precision)],
    ["Recall (flagged)", mean(s.flagged_recall)],
    ["Precision (flag or watch)", mean(s.alert_precision)],
    ["Recall (flag or watch)", mean(s.alert_recall)],
    ["Average precision", mean(s.average_precision)],
    ["Naive rule precision", mean(s.naive_precision)],
  ].forEach(([label, value]) => {
    const tile = el("div", "tile");
    tile.append(el("div", "value", value.toFixed(2)));
    tile.append(el("div", "label", label));
    grid.append(tile);
  });
  body.append(grid);

  body.append(el("p", "caveats",
    `${s.caught} planted actors caught, ${s.false_alarms} false alarms, ` +
    `${s.missed} missed, out of ${s.planted} planted.`));

  body.append(el("h3", null, "By planted pattern (last trial)"));
  const table = el("table", "table");
  table.innerHTML = "<thead><tr><th>pattern</th><th class='num'>score</th>" +
    "<th>rank</th><th>outcome</th></tr></thead>";
  const tb = el("tbody");
  const last = data.trials[data.trials.length - 1];
  Object.entries(last.per_pattern || {}).forEach(([pattern, m]) => {
    const tr = el("tr", m.caught ? "" : "high");
    tr.append(el("td", null, titleCase(pattern)));
    tr.append(el("td", "num", m.risk_score === null ? "-" : m.risk_score));
    tr.append(el("td", null, `${m.rank} of ${m.of}`));
    tr.append(el("td", null, m.caught ? "caught" : `missed (${m.status})`));
    tb.append(tr);
  });
  table.append(tb);
  body.append(table);

  body.append(el("h3", null, "What these numbers are not"));
  const ul = el("ul", "caveats");
  [
    "Synthetic data with planted patterns this engine was designed around: an upper bound, not a forecast of real-world accuracy.",
    "A handful of planted actors is a small sample. One catch or miss moves recall by a large fraction.",
    "Thresholds were set by hand and were not tuned on held-out data.",
    "The 'slow burn' pattern sits near the detection limit on purpose. Catching it every time would mean the thresholds are too loose.",
    "No real employee was scored to produce any of this.",
  ].forEach((t) => ul.append(el("li", null, t)));
  body.append(ul);
}

/* ----------------------------------------------------------------- init */
function wireTabs() {
  document.querySelectorAll(".side-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".side-tab").forEach((t) => {
        t.classList.remove("active");
        t.setAttribute("aria-selected", "false");
      });
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      $(`#tab-${tab.dataset.tab}`).classList.add("active");
      $("#page-title").textContent = PAGE_TITLES[tab.dataset.tab] || "";
      if (tab.dataset.tab === "audit") loadAudit();
      if (tab.dataset.tab === "flags") loadFlags();
      if (tab.dataset.tab === "metrics") loadMetrics();
    });
  });
  $("#bell-btn").addEventListener("click", () => goToTab("flags"));
  document.querySelectorAll(".section-link[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => goToTab(btn.dataset.goto));
  });
}

function wireFilters() {
  $("#status-filters").addEventListener("click", (ev) => {
    const chip = ev.target.closest(".chip");
    if (!chip) return;
    $("#status-filters").querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    state.statusFilter = chip.dataset.status;
    renderEmployees();
  });
  $("#flag-filters").addEventListener("click", (ev) => {
    const chip = ev.target.closest(".chip");
    if (!chip) return;
    $("#flag-filters").querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    state.flagState = chip.dataset.state;
    loadFlags();
  });
  $("#search").addEventListener("input", (ev) => {
    state.search = ev.target.value;
    renderEmployees();
  });
}

async function init() {
  wireTabs();
  wireFilters();
  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  $("#run-scan").addEventListener("click", async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    btn.textContent = "Scanning…";
    try {
      await api("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: "dashboard" }),
      });
      await Promise.all([loadOverview(), loadEmployees(), loadFlags(), loadAudit(), loadRecentActivity()]);
    } catch (err) {
      alert(`Scan failed: ${err.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "Run scan";
    }
  });

  try {
    const cat = await api("/api/features");
    cat.features.forEach((f) => { state.featureLabels[f.name] = f.label; });
    if (cat.review_decisions && cat.review_decisions.length) {
      state.decisions = cat.review_decisions;
    }
  } catch (_) { /* labels are cosmetic */ }

  await loadOverview();
  await loadEmployees();
  await loadRecentActivity();
}

init();
