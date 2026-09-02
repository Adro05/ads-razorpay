/* Employee activity tracker - the merchant-facing surface.
 *
 * Deliberately plain: no framework, no CDN, no build step. A monitoring tool
 * that accuses people should be readable end to end by whoever deploys it.
 */

const state = {
  employees: [],
  statusFilter: "",
  roleFilter: "",
  storeFilter: "",
  riskFilter: "",
  search: "",
  flagState: "",
  flagSort: "risk_desc",
  auditKind: "",
  auditEntries: [],
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
  analytics: "Analytics",
  metrics: "Honest metrics",
  simlab: "Simulation lab",
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

function riskColor(score) {
  if (score >= 70) return "var(--flag)";
  if (score >= 50) return "var(--watch)";
  return "var(--clear)";
}

/* --------------------------------------------------------------- charts */
function buildBarChart(rows, { wide = false } = {}) {
  const bars = el("div", "chart-bars");
  rows.forEach(({ label, display, pct, color }) => {
    const row = el("div", `chart-row${wide ? " chart-row--wide" : ""}`);
    row.append(el("div", "chart-label", label));
    const track = el("div", "chart-track");
    const fill = el("span", "chart-fill");
    fill.style.width = `${Math.max(2, pct)}%`;
    fill.style.background = color;
    track.append(fill);
    row.append(track);
    row.append(el("div", "chart-count", display));
    bars.append(row);
  });
  return bars;
}

function sparkline(points, { width = 168, height = 38 } = {}) {
  if (!points.length) return "";
  const pad = 4;
  const vals = points.map((p) => Number(p.risk_score));
  const min = Math.min(...vals, 0);
  const max = Math.max(...vals, 100);
  const span = Math.max(max - min, 1);
  const stepX = points.length > 1 ? (width - pad * 2) / (points.length - 1) : 0;
  const coords = points.map((p, i) => {
    const x = pad + i * stepX;
    const y = height - pad - ((Number(p.risk_score) - min) / span) * (height - pad * 2);
    return [x, y];
  });
  const path = coords.map((c) => c.join(",")).join(" ");
  const last = coords[coords.length - 1];
  const color = riskColor(vals[vals.length - 1]);
  return (
    `<svg class="trend-spark" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">` +
    `<polyline points="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>` +
    `<circle cx="${last[0]}" cy="${last[1]}" r="3" fill="${color}"/></svg>`
  );
}

/* ------------------------------------------------------------- datasets */
async function loadDatasets() {
  const data = await api("/api/datasets");
  const sel = $("#dataset-select");
  sel.innerHTML = "";
  data.datasets.forEach((d) => {
    const label = d.label + (d.events_ready ? "" : " (not generated)");
    const opt = new Option(label, d.id, d.is_active, d.is_active);
    sel.append(opt);
  });
  const active = data.datasets.find((d) => d.is_active);
  $("#dataset-hint").textContent = active
    ? `${active.description}${active.planted_actors != null ? ` · ${active.planted_actors} planted actor(s)` : ""}`
    : "";
}

async function activateDataset(id) {
  const sel = $("#dataset-select");
  sel.disabled = true;
  try {
    await api(`/api/datasets/${encodeURIComponent(id)}/activate`, { method: "POST" });
    closeDrawer();
    await loadDatasets();
    await refreshForActiveTab();
  } catch (err) {
    alert(`Could not switch dataset: ${err.message}`);
    await loadDatasets();
  } finally {
    sel.disabled = false;
  }
}

async function refreshForActiveTab() {
  await Promise.all([loadOverview(), loadEmployees(), loadRecentActivity()]);
  const activeTab = document.querySelector(".side-tab.active")?.dataset.tab;
  if (activeTab === "audit") await loadAudit();
  if (activeTab === "flags") await loadFlags();
  if (activeTab === "metrics") await loadMetrics();
  if (activeTab === "analytics") await loadAnalytics();
  if (activeTab === "simlab") await loadSimCompare();
}

/* ------------------------------------------------------------- overview */
async function loadOverview() {
  const data = await api("/api/overview");
  const meta = $("#scan-meta");
  if (!data.scan) {
    meta.textContent = "No scans yet - run a scan to populate the tracker.";
    $("#tiles").innerHTML = "";
    $("#status-chart").innerHTML = "";
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

function renderStatusChart(c) {
  const wrap = $("#status-chart");
  wrap.innerHTML = "";
  if (!c.employees) {
    wrap.append(el("p", "empty", "No scan yet."));
    return;
  }
  const total = Math.max(1, c.employees);
  const rows = [
    ["Flagged", c.flagged, "var(--flag)"],
    ["Watch", c.watch, "var(--watch)"],
    ["Clear", c.clear, "var(--clear)"],
    ["Not scored", c.insufficient_data, "var(--idle)"],
  ].map(([label, value, color]) => ({
    label, color, display: String(value || 0), pct: ((value || 0) / total) * 100,
  }));
  wrap.append(buildBarChart(rows));
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

function populateEmployeeFilterOptions() {
  const fillSelect = (select, values) => {
    const current = select.value;
    select.innerHTML = "";
    select.append(new Option(select.dataset.allLabel, ""));
    values.forEach((v) => select.append(new Option(v, v)));
    if (values.includes(current)) select.value = current;
  };
  const roles = [...new Set(state.employees.map((e) => e.role))].sort();
  const stores = [...new Set(state.employees.map((e) => e.store_id))].sort();
  $("#role-filter").dataset.allLabel = "All roles";
  $("#store-filter").dataset.allLabel = "All stores";
  fillSelect($("#role-filter"), roles);
  fillSelect($("#store-filter"), stores);
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
  populateEmployeeFilterOptions();
  renderEmployees();
  renderTopFlags();
  renderActiveList();
}

function renderEmployees() {
  const grid = $("#employee-grid");
  grid.innerHTML = "";
  const term = state.search.trim().toLowerCase();
  const [riskMin, riskMax] = state.riskFilter
    ? state.riskFilter.split("-").map(Number)
    : [null, null];
  const rows = state.employees.filter((e) => {
    if (state.statusFilter && e.status !== state.statusFilter) return false;
    if (state.roleFilter && e.role !== state.roleFilter) return false;
    if (state.storeFilter && e.store_id !== state.storeFilter) return false;
    if (riskMin !== null && !(e.risk_score >= riskMin && e.risk_score <= riskMax)) return false;
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
function renderComponentBars(components) {
  const LABELS = { peer: "Peer deviation", self: "Self deviation", isolation_forest: "Isolation Forest" };
  const COLORS = { peer: "var(--accent)", self: "var(--watch)", isolation_forest: "var(--flag)" };
  const wrap = el("div", "component-bars");
  Object.entries(LABELS).forEach(([key, label]) => {
    const value = components ? components[key] : null;
    const row = el("div", "component-row");
    row.append(el("div", "component-label", label));
    const track = el("div", "component-track");
    const fill = el("span", "component-fill");
    fill.style.width = `${value == null ? 0 : Math.max(2, value)}%`;
    fill.style.background = COLORS[key];
    track.append(fill);
    row.append(track);
    row.append(el("div", "component-value", value == null ? "n/a" : value.toFixed(0)));
    wrap.append(row);
  });
  return wrap;
}

function renderReasonBox(r) {
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
    `observed ${fmtNum(r.observed)} vs ${fmtNum(r.comparison)}${r.z ? ` · z = ${Number(r.z).toFixed(2)}` : ""}`));
  return box;
}

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

  /* trend ------------------------------------------------------------- */
  const history = [...(d.history || [])].reverse();
  if (history.length > 1) {
    body.append(el("h3", null, "Risk trend"));
    const trendRow = el("div", "trend-row");
    const sparkWrap = el("div");
    sparkWrap.innerHTML = sparkline(history);
    trendRow.append(sparkWrap);
    trendRow.append(el("div", "trend-caption",
      `${history.length} scans · ${history[0].risk_score.toFixed(0)} → ${history[history.length - 1].risk_score.toFixed(0)}`));
    body.append(trendRow);
  }

  /* composite score ---------------------------------------------------- */
  body.append(el("h3", null, "Composite score components"));
  body.append(renderComponentBars(d.components));

  /* why ------------------------------------------------------------- */
  body.append(el("h3", null, "Why this score"));
  if (!d.reasons || d.reasons.length === 0) {
    body.append(el("p", "caveats",
      d.status === "insufficient_data"
        ? d.summary
        : "No individually reportable deviation. Nothing here is evidence of anything."));
  } else {
    const groups = { peer: [], self: [], model: [] };
    d.reasons.forEach((r) => { (groups[r.basis] || groups.model).push(r); });
    const groupLabels = {
      peer: "Peer comparison",
      self: "Self baseline (own recent history)",
      model: "Model cross-check",
    };
    ["peer", "self", "model"].forEach((basis) => {
      if (!groups[basis].length) return;
      body.append(el("div", "reason-group-label", groupLabels[basis]));
      groups[basis].forEach((r) => body.append(renderReasonBox(r)));
    });
  }

  /* components table --------------------------------------------------- */
  body.append(el("h3", null, "Score components (raw)"));
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
  body.append(el("h3", null, "Current window vs. baseline"));
  body.append(el("p", "caveats",
    "Baseline is shown only for features that produced an individually reportable deviation above; " +
    "the rest are this window's raw values with nothing unusual to compare them to."));
  const selfByFeature = {};
  (d.reasons || []).filter((r) => r.basis === "self").forEach((r) => { selfByFeature[r.feature] = r; });
  const ft = el("table", "table");
  ft.innerHTML = "<thead><tr><th>feature</th><th class='num'>current (7d)</th>" +
    "<th class='num'>baseline (28d)</th><th class='num'>z</th></tr></thead>";
  const ftb = el("tbody");
  Object.entries(d.features || {}).forEach(([k, v]) => {
    const tr = el("tr");
    tr.append(el("td", null, state.featureLabels[k] || titleCase(k)));
    const isPct = !["avg_refund_amount", "avg_discount_pct"].includes(k);
    tr.append(el("td", "num", isPct ? fmtPct(v) : fmtNum(v)));
    const match = selfByFeature[k];
    tr.append(el("td", "num", match ? (isPct ? fmtPct(match.comparison) : fmtNum(match.comparison)) : "—"));
    tr.append(el("td", "num", match ? match.z.toFixed(2) : "—"));
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
  let flags = data.flags || [];
  if (state.flagSort === "risk_desc") flags = [...flags].sort((a, b) => b.risk_score - a.risk_score);
  else if (state.flagSort === "risk_asc") flags = [...flags].sort((a, b) => a.risk_score - b.risk_score);

  const list = $("#flag-list");
  list.innerHTML = "";
  if (!flags.length) {
    list.append(el("p", "empty", "No flags recorded."));
    return;
  }
  flags.forEach((f) => {
    const card = renderFlagCard(f);
    const head = el("div");
    const link = el("strong", null, f.employee_name);
    link.style.cursor = "pointer";
    link.style.color = "var(--accent)";
    link.addEventListener("click", () => openDrawer(f.employee_id));
    head.append(link);
    head.append(document.createTextNode(" · "));
    head.append(el("span", `pill ${f.state === "open" ? "flagged" : "clear"}`, f.state));
    card.prepend(head);
    list.append(card);
  });
}

/* ---------------------------------------------------------------- audit */
function auditKind(action) {
  if (action.startsWith("scan.")) return "scan";
  if (action === "flag.raised") return "flag";
  if (action === "flag.reviewed") return "review";
  return "other";
}

function renderAuditVerification(v) {
  const banner = $("#audit-verification");
  banner.className = `verify-banner ${v.ok ? "ok" : "bad"}`;
  $("#audit-verify-icon").innerHTML = v.ok ? ICONS.check : ICONS.alert;
  $("#audit-verify-state").textContent = v.ok ? "Chain verified" : `Chain INVALID at entry #${v.broken_at}`;
  $("#audit-verify-detail").textContent = v.ok
    ? `${v.entries} entries, head ${String(v.head).slice(0, 16)}… Each entry commits to the one before it, ` +
      "so a deleted or edited record breaks every link after it."
    : `${v.problem}`;
}

function renderAuditTable() {
  const tbody = $("#audit-table tbody");
  tbody.innerHTML = "";
  const rows = state.auditEntries.filter((e) => !state.auditKind || auditKind(e.action) === state.auditKind);
  if (!rows.length) {
    const tr = el("tr");
    const td = el("td", "empty", "No matching audit entries.");
    td.colSpan = 6;
    tr.append(td);
    tbody.append(tr);
    return;
  }
  rows.forEach((e) => {
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

async function loadAudit() {
  const data = await api("/api/audit?limit=250");
  renderAuditVerification(data.verification);
  state.auditEntries = data.entries || [];
  renderAuditTable();
}

/* ----------------------------------------------------------- analytics */
async function loadAnalytics() {
  renderRiskByGroup("#chart-role", "role");
  renderRiskByGroup("#chart-store", "store_id");
  renderTxnSummary();
  await renderAnomalyTypes();
}

function renderRiskByGroup(selector, key) {
  const wrap = $(selector);
  wrap.innerHTML = "";
  const scoreable = state.employees.filter((e) => e.status !== "insufficient_data");
  if (!scoreable.length) {
    wrap.append(el("p", "empty", "No scored employees yet."));
    return;
  }
  const groups = {};
  scoreable.forEach((e) => {
    const k = e[key] || "unknown";
    (groups[k] = groups[k] || []).push(e.risk_score);
  });
  const rows = Object.entries(groups)
    .map(([label, scores]) => ({
      label, scores, avg: scores.reduce((s, v) => s + v, 0) / scores.length,
    }))
    .sort((a, b) => b.avg - a.avg)
    .map((g) => ({
      label: g.label,
      color: riskColor(g.avg),
      display: `${g.avg.toFixed(0)} (${g.scores.length})`,
      pct: g.avg,
    }));
  wrap.append(buildBarChart(rows, { wide: true }));
}

function renderTxnSummary() {
  const wrap = $("#txn-summary");
  wrap.innerHTML = "";
  if (!state.employees.length) {
    wrap.append(el("p", "empty", "No scan yet."));
    return;
  }
  const totals = {};
  state.employees.forEach((e) => {
    Object.entries(e.counts || {}).forEach(([k, v]) => { totals[k] = (totals[k] || 0) + Number(v); });
  });
  [
    ["Total sales", fmtNum(totals.sale_count || 0)],
    ["Sales value", fmtNum(totals.sale_amount || 0)],
    ["Total refunds", fmtNum(totals.refund_count || 0)],
    ["Refund value", fmtNum(totals.refund_amount || 0)],
    ["Voids", fmtNum(totals.void_count || 0)],
    ["Discounts applied", fmtNum(totals.discount_count || 0)],
    ["Manual overrides", fmtNum(totals.override_count || 0)],
    ["Off-hours actions", fmtNum(totals.off_hours_count || 0)],
  ].forEach(([label, value]) => {
    const row = el("div", "summary-row");
    row.append(el("div", "summary-label", label));
    row.append(el("div", "summary-value", value));
    wrap.append(row);
  });
}

async function renderAnomalyTypes() {
  const wrap = $("#chart-anomaly");
  wrap.innerHTML = "";
  let data;
  try {
    data = await api("/api/flags?limit=300");
  } catch (_) {
    wrap.append(el("p", "empty", "Could not load flags."));
    return;
  }
  const counts = {};
  (data.flags || []).forEach((f) => (f.reasons || []).forEach((r) => {
    const label = state.featureLabels[r.feature] || titleCase(r.feature);
    counts[label] = (counts[label] || 0) + 1;
  }));
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  if (!entries.length) {
    wrap.append(el("p", "empty", "No flags raised yet on this dataset."));
    return;
  }
  const max = entries[0][1];
  const rows = entries.map(([label, count]) => ({
    label, color: "var(--accent)", display: String(count), pct: (count / max) * 100,
  }));
  wrap.append(buildBarChart(rows, { wide: true }));
}

/* --------------------------------------------------------- simulation lab */
async function loadSimCompare() {
  const wrap = $("#sim-compare");
  wrap.innerHTML = "";
  let data;
  try {
    data = await api("/api/simulations");
  } catch (_) {
    wrap.append(el("p", "empty", "Could not load simulations."));
    return;
  }
  const rows = data.simulations || [];
  if (!rows.length) {
    wrap.append(el("p", "empty", "No simulations generated yet."));
    return;
  }
  const table = el("table", "table");
  table.innerHTML = "<thead><tr><th>name</th><th class='num'>flag precision</th>" +
    "<th class='num'>flag recall</th><th class='num'>avg precision</th><th>planted patterns</th></tr></thead>";
  const tbody = el("tbody");
  rows.slice().reverse().forEach((s) => {
    const tr = el("tr");
    tr.append(el("td", null, s.name));
    tr.append(el("td", "num", s.metrics.flagged.precision.toFixed(2)));
    tr.append(el("td", "num", s.metrics.flagged.recall.toFixed(2)));
    tr.append(el("td", "num", s.metrics.average_precision.toFixed(2)));
    const td = el("td");
    Object.entries(s.metrics.per_pattern || {}).forEach(([pattern, m]) => {
      td.append(el("span", `sim-pattern ${m.caught ? "caught" : "missed"}`,
        `${titleCase(pattern)}${m.caught ? "" : " (missed)"}`));
      td.append(document.createTextNode(" "));
    });
    tr.append(td);
    tbody.append(tr);
  });
  table.append(tbody);
  wrap.append(table);
}

function wireSimLab() {
  $("#simlab-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const status = $("#sim-status");
    const submit = $("#sim-submit");
    submit.disabled = true;
    submit.textContent = "Generating…";
    status.hidden = true;
    try {
      const payload = {
        name: $("#sim-name").value.trim(),
        employees: Number($("#sim-employees").value),
        days: Number($("#sim-days").value),
        bad_actors: Number($("#sim-bad").value),
        seed: Number($("#sim-seed").value),
      };
      const result = await api("/api/simulations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      status.hidden = false;
      status.className = "empty ok";
      status.textContent = `Generated "${result.name}": ${result.scan.employees_seen} employees, ` +
        `${result.scan.flags_raised} flags raised. It's now selectable in the dataset switcher.`;
      $("#sim-name").value = "";
      await loadDatasets();
      await loadSimCompare();
    } catch (err) {
      status.hidden = false;
      status.className = "empty bad";
      status.textContent = `Could not generate: ${err.message}`;
    } finally {
      submit.disabled = false;
      submit.textContent = "Generate & scan";
    }
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
      if (tab.dataset.tab === "analytics") loadAnalytics();
      if (tab.dataset.tab === "simlab") loadSimCompare();
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
  $("#role-filter").addEventListener("change", (ev) => {
    state.roleFilter = ev.target.value;
    renderEmployees();
  });
  $("#store-filter").addEventListener("change", (ev) => {
    state.storeFilter = ev.target.value;
    renderEmployees();
  });
  $("#risk-filter").addEventListener("change", (ev) => {
    state.riskFilter = ev.target.value;
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
  $("#flag-sort").addEventListener("change", (ev) => {
    state.flagSort = ev.target.value;
    loadFlags();
  });
  $("#audit-filters").addEventListener("click", (ev) => {
    const chip = ev.target.closest(".chip");
    if (!chip) return;
    $("#audit-filters").querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    state.auditKind = chip.dataset.kind;
    renderAuditTable();
  });
  $("#audit-verify-btn").addEventListener("click", async () => {
    const btn = $("#audit-verify-btn");
    btn.disabled = true;
    btn.textContent = "Verifying…";
    try {
      const v = await api("/api/audit/verify");
      renderAuditVerification(v);
    } finally {
      btn.disabled = false;
      btn.textContent = "Verify now";
    }
  });
  $("#search").addEventListener("input", (ev) => {
    state.search = ev.target.value;
    renderEmployees();
  });
  $("#dataset-select").addEventListener("change", (ev) => activateDataset(ev.target.value));
}

async function init() {
  wireTabs();
  wireFilters();
  wireSimLab();
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

  await loadDatasets();
  await loadOverview();
  await loadEmployees();
  await loadRecentActivity();
}

init();
