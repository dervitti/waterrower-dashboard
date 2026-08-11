const $ = (id) => document.getElementById(id);

const MAX_POINTS = 360; // ~6 min at 1 Hz

const state = {
  users: [],
  selectedUserId: null,
  editingUserId: null,
  maxHr: null,
  active: false,
  timerRunning: false,
  timerAnchorElapsed: 0,
  timerAnchorAt: null,
  chart: null,
  replayChart: null,
  lastElapsed: null,
};

const BPM_COLOR = "#e35d6a";
const BPM_HOT = "#ff6b7c"; // helleres Rot über Max-HF
const BPM_WIDTH = 3.5;
const BPM_HOT_WIDTH = 6.5;
const INT_COLOR = "#2fbfa8";
const PACE_COLOR = "#f0b429";
const SPM_COLOR = "#7aa2ff";

function chartDatasets() {
  return [
    {
      label: "BPM",
      data: [],
      borderColor: BPM_COLOR,
      backgroundColor: "rgba(227, 93, 106, 0.12)",
      yAxisID: "yHr",
      tension: 0.25,
      pointRadius: 0,
      borderWidth: BPM_WIDTH,
      segment: {
        borderColor: (ctx) => {
          const y = ctx.p1.parsed.y;
          if (state.maxHr != null && y != null && y > state.maxHr) return BPM_HOT;
          return BPM_COLOR;
        },
        borderWidth: (ctx) => {
          const y = ctx.p1.parsed.y;
          if (state.maxHr != null && y != null && y > state.maxHr) return BPM_HOT_WIDTH;
          return BPM_WIDTH;
        },
      },
    },
    {
      label: "Intensity m/s",
      data: [],
      borderColor: INT_COLOR,
      backgroundColor: "rgba(47, 191, 168, 0.08)",
      yAxisID: "yInt",
      tension: 0.25,
      pointRadius: 0,
      borderWidth: 2.5,
    },
    {
      label: "Ø Pace /500m",
      data: [],
      borderColor: PACE_COLOR,
      backgroundColor: "transparent",
      yAxisID: "yPace",
      tension: 0.25,
      pointRadius: 0,
      borderWidth: 2.5,
    },
    {
      label: "SPM",
      data: [],
      borderColor: SPM_COLOR,
      backgroundColor: "transparent",
      yAxisID: "ySpm",
      tension: 0.25,
      pointRadius: 0,
      borderWidth: 2.5,
      borderDash: [4, 3],
    },
  ];
}

function chartOptions() {
  const grid = "rgba(164, 214, 232, 0.12)";
  const tick = "#8fb3c3";
  const axisTitle = { size: 28, weight: "600" };
  const tickFont = { size: 22 };
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    layout: { padding: { top: 4, right: 6, bottom: 2, left: 2 } },
    plugins: {
      legend: {
        labels: {
          color: tick,
          boxWidth: 22,
          boxHeight: 4,
          padding: 16,
          font: { size: 22, weight: "600" },
          usePointStyle: true,
          pointStyle: "line",
          generateLabels(chart) {
            const items = Chart.defaults.plugins.legend.labels.generateLabels(chart);
            return items.map((item) => {
              const ds = chart.data.datasets[item.datasetIndex];
              const c = typeof ds.borderColor === "string" ? ds.borderColor : tick;
              item.fillStyle = c;
              item.strokeStyle = c;
              item.fontColor = c;
              item.color = c;
              return item;
            });
          },
        },
      },
      tooltip: {
        titleFont: { size: 16 },
        bodyFont: { size: 16 },
        callbacks: {
          labelColor(ctx) {
            const c =
              typeof ctx.dataset.borderColor === "string"
                ? ctx.dataset.borderColor
                : "#fff";
            return { borderColor: c, backgroundColor: c };
          },
          label(ctx) {
            const v = ctx.parsed.y;
            if (v == null) return `${ctx.dataset.label}: —`;
            if (ctx.dataset.label.startsWith("Intensity")) {
              return `Intensity: ${Number(v).toFixed(2)} m/s`;
            }
            if (ctx.dataset.label.includes("Pace")) {
              return `Pace: ${formatPace(v)}`;
            }
            return `${ctx.dataset.label}: ${Math.round(v * 10) / 10}`;
          },
        },
      },
    },
    scales: {
      x: {
        ticks: { color: tick, maxTicksLimit: 8, font: tickFont },
        grid: { color: grid },
      },
      yHr: {
        type: "linear",
        position: "left",
        title: {
          display: true,
          text: "BPM",
          color: "#e35d6a",
          font: axisTitle,
        },
        ticks: { color: "#e35d6a", font: tickFont },
        grid: { color: grid },
        suggestedMin: 80,
        suggestedMax: 180,
      },
      yInt: {
        type: "linear",
        position: "right",
        title: {
          display: true,
          text: "m/s",
          color: "#2fbfa8",
          font: axisTitle,
        },
        ticks: {
          color: "#2fbfa8",
          font: tickFont,
          callback: (v) => Number(v).toFixed(1),
        },
        grid: { drawOnChartArea: false },
        suggestedMin: 0,
        suggestedMax: 5,
      },
      yPace: {
        type: "linear",
        position: "right",
        reverse: true,
        display: false,
        suggestedMin: 90,
        suggestedMax: 180,
      },
      ySpm: {
        type: "linear",
        position: "right",
        display: false,
        suggestedMin: 0,
        suggestedMax: 40,
      },
    },
  };
}

function initChart() {
  const ctx = $("liveChart").getContext("2d");
  state.chart = new Chart(ctx, {
    type: "line",
    data: { labels: [], datasets: chartDatasets() },
    options: chartOptions(),
  });
}

function ensureReplayChart() {
  if (state.replayChart) return state.replayChart;
  const ctx = $("replayChart").getContext("2d");
  state.replayChart = new Chart(ctx, {
    type: "line",
    data: { labels: [], datasets: chartDatasets() },
    options: chartOptions(),
  });
  return state.replayChart;
}

function fillChartFromSamples(chart, samples) {
  chart.data.labels = [];
  for (const ds of chart.data.datasets) ds.data = [];

  let step = 1;
  if (samples.length > 1800) step = Math.ceil(samples.length / 1800);

  for (let i = 0; i < samples.length; i += step) {
    const s = samples[i];
    const label =
      s.elapsed_s != null
        ? formatDuration(s.elapsed_s)
        : formatDuration(Math.floor(s.t_offset_s));
    chart.data.labels.push(label);
    chart.data.datasets[0].data.push(s.heart_rate ?? null);
    chart.data.datasets[1].data.push(s.avg_intensity_mps ?? null);
    chart.data.datasets[2].data.push(s.pace_s ?? null);
    chart.data.datasets[3].data.push(s.stroke_rate ?? null);
  }
  chart.update("none");
}

function formatPace(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "—:—";
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function formatDuration(seconds) {
  if (seconds == null) return "0:00";
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function resetChart() {
  if (!state.chart) return;
  state.chart.data.labels = [];
  for (const ds of state.chart.data.datasets) ds.data = [];
  state.chart.update("none");
  state.lastElapsed = null;
  state.lastChartSec = null;
}

function pushChartPoint(m) {
  if (!state.chart || !state.active) return;

  // ~1 Hz, unabhängig vom Stoppuhr-Status
  const nowSec = Math.floor(Date.now() / 1000);
  if (nowSec === state.lastChartSec) return;
  state.lastChartSec = nowSec;

  const label =
    state.timerRunning && m.elapsed_s != null
      ? formatDuration(m.elapsed_s)
      : new Date().toLocaleTimeString("de-DE", { minute: "2-digit", second: "2-digit" });

  const chart = state.chart;
  chart.data.labels.push(label);
  chart.data.datasets[0].data.push(m.heart_rate ?? null);
  chart.data.datasets[1].data.push(m.avg_intensity_mps ?? null);
  chart.data.datasets[2].data.push(m.pace_s ?? null);
  chart.data.datasets[3].data.push(m.stroke_rate ?? null);

  while (chart.data.labels.length > MAX_POINTS) {
    chart.data.labels.shift();
    for (const ds of chart.data.datasets) ds.data.shift();
  }
  chart.update("none");
}

function renderLocalTime() {
  let s = state.timerAnchorElapsed;
  if (state.timerRunning && state.timerAnchorAt != null) {
    s += (Date.now() - state.timerAnchorAt) / 1000;
  }
  $("mTime").textContent = formatDuration(s);
}

function syncTimer(statusOrMetrics, timerRunning) {
  if (typeof timerRunning === "boolean") state.timerRunning = timerRunning;
  const elapsed =
    statusOrMetrics?.elapsed_s != null
      ? statusOrMetrics.elapsed_s
      : statusOrMetrics?.metrics?.elapsed_s;
  if (elapsed != null) {
    state.timerAnchorElapsed = elapsed;
    state.timerAnchorAt = Date.now();
  }
  const startBtn = $("btnTimerStart");
  const pauseBtn = $("btnTimerPause");
  if (startBtn && pauseBtn) {
    startBtn.classList.toggle("active-timer", state.timerRunning);
    pauseBtn.classList.toggle("active-timer", !state.timerRunning && state.timerAnchorElapsed > 0);
  }
  renderLocalTime();
}

function setMetrics(m = {}) {
  $("mSpm").textContent = m.stroke_rate != null ? Number(m.stroke_rate).toFixed(0) : "—";
  $("mHr").textContent = m.heart_rate != null ? m.heart_rate : "—";
  const over = state.maxHr != null && m.heart_rate != null && m.heart_rate > state.maxHr;
  $("mHr").classList.toggle("hr-over", !!over);
  $("mHr").closest(".metric")?.classList.toggle("hr-over", !!over);
  updateHrZoneLive(m.heart_rate);
  $("mDist").textContent = m.distance_m != null ? Math.round(m.distance_m) : "—";
  if (m.elapsed_s != null) syncTimer(m, state.timerRunning);
  $("mStrokes").textContent = m.stroke_count != null ? m.stroke_count : "—";
  $("mAvgInt").textContent =
    m.avg_intensity_mps != null ? Number(m.avg_intensity_mps).toFixed(2) : "—";
  $("mPace").textContent = formatPace(m.pace_s);
  pushChartPoint(m);
}

function selectedUser() {
  return state.users.find((x) => String(x.id) === String(state.selectedUserId)) || null;
}

function userMaxHr(u) {
  if (!u) return null;
  if (u.effective_max_hr != null) return u.effective_max_hr;
  if (u.max_hr != null) return u.max_hr;
  return u.estimated_max_hr ?? null;
}

function renderHrZones() {
  const panel = $("hrZonesPanel");
  const bar = $("hrZonesBar");
  const info = $("hrMaxInfo");
  const u = selectedUser();
  const maxHr = userMaxHr(u);
  const zones = u?.hr_zones || [];
  if (!u || !maxHr || !zones.length) {
    panel.hidden = true;
    bar.innerHTML = "";
    info.textContent = "";
    updateHrZoneLive(null);
    return;
  }
  panel.hidden = false;
  const src =
    u.max_hr != null
      ? `Max HF ${maxHr} (manuell)`
      : `Max HF ${maxHr} (geschätzt)`;
  info.textContent = src;
  bar.innerHTML = "";
  for (const z of zones) {
    const el = document.createElement("div");
    el.className = "hr-zone";
    el.dataset.key = z.key;
    el.style.color = z.color;
    el.style.borderColor = z.color;
    el.style.background = `linear-gradient(160deg, color-mix(in srgb, ${z.color} 22%, transparent), rgba(7,19,28,0.85))`;
    el.setAttribute("role", "listitem");
    el.innerHTML =
      `<span class="z-name">${z.name}</span>` +
      `<span class="z-pct">${z.pct_lo}–${z.pct_hi} %</span>` +
      `<span class="z-bpm">${z.bpm_lo}–${z.bpm_hi} BPM</span>`;
    bar.appendChild(el);
  }
}

function updateHrZoneLive(hr) {
  const label = $("hrZoneLabel");
  const metric = $("mHr")?.closest(".metric");
  const u = selectedUser();
  const maxHr = state.maxHr ?? userMaxHr(u);
  document.querySelectorAll(".hr-zone.active").forEach((el) => el.classList.remove("active"));
  if (hr == null || maxHr == null || maxHr <= 0) {
    if (label) label.textContent = "";
    if (metric) metric.style.setProperty("--zone-color", "var(--series-bpm)");
    return;
  }
  const pct = hr / maxHr;
  let key = "warmup";
  let name = "Aufwärmen / Erholung";
  let color = "#6a8a9a";
  const zones = u?.hr_zones || [];
  if (pct >= 0.9) {
    const z = zones.find((x) => x.key === "race") || { name: "Wettkampf-Zone", color: "#ff2a3c" };
    key = "race";
    name = z.name;
    color = z.color || "#ff2a3c";
  } else if (pct >= 0.5) {
    const z = zones.find((x) => hr >= x.bpm_lo && hr < x.bpm_hi) ||
      zones.find((x) => pct >= x.pct_lo / 100 && pct < x.pct_hi / 100);
    if (z) {
      key = z.key;
      name = z.name;
      color = z.color;
    }
  }
  if (label) {
    label.textContent = `${name} · ${Math.round(pct * 100)} %`;
    label.style.color = color;
  }
  if (metric && !metric.classList.contains("hr-over")) {
    metric.style.setProperty("--zone-color", color);
    const strong = $("mHr");
    if (strong) strong.style.color = color;
    const lab = metric.querySelector(".label");
    if (lab) lab.style.color = color;
  }
  const active = document.querySelector(`.hr-zone[data-key="${key}"]`);
  if (active) active.classList.add("active");
}

function setActiveUi(active) {
  const wasActive = state.active;
  state.active = active;
  $("btnStart").disabled = active;
  $("btnDemo").disabled = active;
  $("btnUsb").disabled = active;
  $("btnStop").disabled = !active;
  $("btnScan").disabled = active;
  $("btnTimerStart").disabled = !active;
  $("btnTimerPause").disabled = !active;
  $("btnTimerReset").disabled = !active;
  if (active && !wasActive) resetChart();
  setWakeLock(active);
}

/** Bildschirm wach halten (Browser Wake Lock), solange Training läuft. */
let wakeLock = null;

async function setWakeLock(on) {
  if (!on) {
    try {
      await wakeLock?.release();
    } catch (_) {
      /* ignore */
    }
    wakeLock = null;
    return;
  }
  if (!("wakeLock" in navigator)) return;
  try {
    wakeLock = await navigator.wakeLock.request("screen");
    wakeLock.addEventListener("release", () => {
      wakeLock = null;
    });
  } catch (err) {
    console.warn("Wake Lock nicht verfügbar:", err);
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && state.active && !wakeLock) {
    setWakeLock(true);
  }
});

function applyStatus(status) {
  $("statusMsg").textContent = status.message || "";
  const badge = $("connBadge");
  if (status.active) {
    badge.textContent = status.connected ? "LIVE" : "VERBINDET…";
    badge.className = "badge live";
  } else {
    badge.textContent = "BEREIT";
    badge.className = "badge ok";
  }
  if (status.user_max_hr != null) state.maxHr = status.user_max_hr;
  else if (state.selectedUserId) {
    const u = state.users.find((x) => String(x.id) === String(state.selectedUserId));
    state.maxHr = userMaxHr(u);
  }
  setActiveUi(!!status.active);
  syncTimer(status, !!status.timer_running);
  if (status.metrics) setMetrics(status.metrics);
  if (status.user_id) {
    state.selectedUserId = status.user_id;
    $("userSelect").value = String(status.user_id);
  }
  renderHrZones();
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    let msg = res.statusText;
    if (typeof data.detail === "string") msg = data.detail;
    else if (Array.isArray(data.detail)) {
      msg = data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    }
    throw new Error(msg || "Anfrage fehlgeschlagen");
  }
  return data;
}

function openUserForm(user = null) {
  const form = $("userForm");
  form.classList.remove("hidden");
  if (user) {
    state.editingUserId = user.id;
    $("newUserName").value = user.name || "";
    $("newUserSex").value = user.sex || "";
    $("newUserBirthYear").value = user.birth_year ?? "";
    $("newUserWeight").value = user.weight_kg ?? "";
    $("newUserMaxHr").value = user.max_hr ?? "";
    $("userFormSubmit").textContent = "Änderungen übernehmen";
  } else {
    state.editingUserId = null;
    form.reset();
    $("userFormSubmit").textContent = "Anlegen";
  }
  $("newUserName").focus();
}

function closeUserForm() {
  state.editingUserId = null;
  $("userForm").reset();
  $("userFormSubmit").textContent = "Anlegen";
  $("userForm").classList.add("hidden");
}

function highlightSelectedUser() {
  const select = $("userSelect");
  if (state.selectedUserId != null) {
    select.value = String(state.selectedUserId);
  }
  for (const li of $("userList").querySelectorAll("li")) {
    li.classList.toggle("active", li.dataset.userId === String(state.selectedUserId));
  }
}

async function selectUser(userId, { reloadList = false } = {}) {
  state.selectedUserId = userId != null ? Number(userId) : null;
  const u = selectedUser();
  state.maxHr = userMaxHr(u);
  if (reloadList) renderUsers();
  else highlightSelectedUser();
  renderHrZones();
  await loadSessions();
}

function renderUsers() {
  const select = $("userSelect");
  const list = $("userList");
  select.innerHTML = "";
  list.innerHTML = "";

  if (!state.users.length) {
    select.innerHTML = `<option value="">Kein User</option>`;
    list.innerHTML = `<li>Noch keine User — lege einen an.</li>`;
    return;
  }

  for (const u of state.users) {
    const opt = document.createElement("option");
    opt.value = u.id;
    opt.textContent = `${u.name}${u.session_count ? ` (${u.session_count})` : ""}`;
    select.appendChild(opt);

    const li = document.createElement("li");
    li.dataset.userId = String(u.id);
    if (String(u.id) === String(state.selectedUserId)) li.classList.add("active");
    const meta = [
      u.sex === "f" ? "♀" : u.sex === "m" ? "♂" : null,
      u.birth_year != null ? `*${u.birth_year}` : null,
      u.weight_kg != null ? `${u.weight_kg} kg` : null,
      userMaxHr(u) != null
        ? `Max ${userMaxHr(u)}${u.max_hr != null ? "" : "≈"}`
        : "Max —",
      `${u.session_count} Sessions`,
    ]
      .filter(Boolean)
      .join(" · ");
    li.innerHTML = `<span>${u.name}<br><small style="color:var(--muted)">${meta}</small></span>`;

    const actions = document.createElement("div");
    actions.className = "row-actions";

    const edit = document.createElement("button");
    edit.className = "edit";
    edit.type = "button";
    edit.textContent = "✎";
    edit.title = "Bearbeiten";
    edit.onclick = (e) => {
      e.stopPropagation();
      openUserForm(u);
    };

    const del = document.createElement("button");
    del.className = "delete";
    del.type = "button";
    del.textContent = "✕";
    del.title = "Löschen";
    del.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`${u.name} wirklich löschen?`)) return;
      try {
        await api(`/api/users/${u.id}`, { method: "DELETE" });
        if (state.editingUserId === u.id) closeUserForm();
        await loadUsers();
        await loadSessions();
      } catch (err) {
        $("statusMsg").textContent = err.message || "Löschen fehlgeschlagen";
      }
    };

    actions.appendChild(edit);
    actions.appendChild(del);
    li.appendChild(actions);
    li.onclick = (e) => {
      if (e.target === del || e.target === edit || actions.contains(e.target)) return;
      selectUser(u.id);
    };
    list.appendChild(li);
  }

  if (state.selectedUserId) select.value = String(state.selectedUserId);
  else {
    state.selectedUserId = state.users[0].id;
    select.value = String(state.selectedUserId);
  }
  const u = state.users.find((x) => String(x.id) === String(state.selectedUserId));
  if (u) state.maxHr = userMaxHr(u);
  renderHrZones();
}

async function loadUsers() {
  state.users = await api("/api/users");
  renderUsers();
}

async function loadSessions() {
  const q = state.selectedUserId ? `?user_id=${state.selectedUserId}` : "";
  const sessions = await api(`/api/sessions${q}`);
  const tbody = $("sessionRows");
  tbody.innerHTML = "";
  const selectAll = $("sessionSelectAll");
  if (selectAll) selectAll.checked = false;

  for (const s of sessions) {
    const tr = document.createElement("tr");
    tr.className = "session-row";
    tr.dataset.id = String(s.id);
    tr.title = "Klicken zum Ansehen";
    tr.innerHTML = `
      <td class="col-check"><input type="checkbox" class="session-check" data-id="${s.id}" /></td>
      <td>${formatDate(s.started_at)}</td>
      <td>${s.user_name || s.user_id}</td>
      <td class="mono">${Math.round(s.distance_m)} m</td>
      <td class="mono">${formatDuration(s.duration_s)}</td>
      <td class="mono">${s.avg_spm != null ? s.avg_spm.toFixed(1) : "—"}</td>
      <td class="mono">${s.avg_power_w != null ? Math.round(s.avg_power_w) : "—"}</td>
      <td class="mono">${s.avg_hr != null ? Math.round(s.avg_hr) : "—"}</td>
      <td><button type="button" class="btn tiny ghost session-del" data-id="${s.id}">Löschen</button></td>
    `;
    const check = tr.querySelector(".session-check");
    check.onclick = (e) => e.stopPropagation();
    check.onchange = () => {
      tr.classList.toggle("selected", check.checked);
      updateSessionSelectionUi();
    };
    const del = tr.querySelector(".session-del");
    del.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm("Session löschen?")) return;
      await api(`/api/sessions/${s.id}`, { method: "DELETE" });
      closeSessionDetail();
      await loadSessions();
      await loadUsers();
    };
    tr.onclick = (e) => {
      if (e.target.closest("input, button")) return;
      openSessionDetail(s.id);
    };
    tbody.appendChild(tr);
  }
  if (!sessions.length) {
    tbody.innerHTML = `<tr><td colspan="9" style="color:var(--muted)">Keine Sessions</td></tr>`;
  }
  updateSessionSelectionUi();
}

function selectedSessionIds() {
  return [...document.querySelectorAll(".session-check:checked")].map((el) =>
    Number(el.dataset.id)
  );
}

function updateSessionSelectionUi() {
  const ids = selectedSessionIds();
  const btn = $("btnDeleteSelected");
  if (btn) {
    btn.disabled = ids.length === 0;
    btn.textContent = ids.length ? `Auswahl löschen (${ids.length})` : "Auswahl löschen";
  }
  const boxes = [...document.querySelectorAll(".session-check")];
  const selectAll = $("sessionSelectAll");
  if (selectAll && boxes.length) {
    selectAll.checked = boxes.every((b) => b.checked);
    selectAll.indeterminate = boxes.some((b) => b.checked) && !selectAll.checked;
  } else if (selectAll) {
    selectAll.checked = false;
    selectAll.indeterminate = false;
  }
}

async function deleteSelectedSessions() {
  const ids = selectedSessionIds();
  if (!ids.length) return;
  if (!confirm(`${ids.length} Session(s) wirklich löschen?`)) return;
  await api("/api/sessions/bulk-delete", {
    method: "POST",
    body: JSON.stringify({ ids }),
  });
  closeSessionDetail();
  await loadSessions();
  await loadUsers();
}

function closeSessionDetail() {
  $("sessionDetail").classList.add("hidden");
}

async function openSessionDetail(sessionId) {
  const detail = await api(`/api/sessions/${sessionId}`);
  const panel = $("sessionDetail");
  panel.classList.remove("hidden");
  $("sessionDetailTitle").textContent =
    `Session · ${formatDate(detail.started_at)} · ${detail.user_name || detail.user_id}`;
  const pace = detail.avg_pace_s != null ? formatPace(detail.avg_pace_s) : "—";
  $("sessionDetailMeta").textContent = [
    `${Math.round(detail.distance_m)} m`,
    formatDuration(detail.duration_s),
    `${detail.stroke_count} strokes`,
    detail.avg_spm != null ? `Ø SPM ${detail.avg_spm.toFixed(1)}` : null,
    `Ø Pace ${pace}`,
    detail.avg_hr != null ? `Ø HF ${Math.round(detail.avg_hr)}` : null,
    detail.max_hr != null ? `Max HF ${detail.max_hr}` : null,
    `${detail.samples.length} Samples`,
    detail.source,
  ]
    .filter(Boolean)
    .join(" · ");

  const chart = ensureReplayChart();
  if (!detail.samples.length) {
    chart.data.labels = [];
    for (const ds of chart.data.datasets) ds.data = [];
    chart.update("none");
    $("sessionDetailMeta").textContent += " — keine Verlaufsdaten";
  } else {
    fillChartFromSamples(chart, detail.samples);
  }
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    $("connBadge").textContent = "WS OK";
    $("connBadge").className = "badge ok";
  };
  ws.onclose = () => {
    $("connBadge").textContent = "WS OFF";
    $("connBadge").className = "badge";
    setTimeout(connectWs, 1500);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "status") {
      applyStatus(msg.payload);
      if (!msg.payload.active) {
        loadSessions();
        loadUsers();
      }
    }
    if (msg.type === "metrics") setMetrics(msg.payload);
  };
  setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 20000);
}

async function startWorkout(mode, { quiet = false } = {}) {
  if (!state.selectedUserId) {
    if (!quiet) alert("Bitte zuerst einen User anlegen/auswählen.");
    else $("statusMsg").textContent = "USB bereit — bitte User wählen, dann USB";
    return null;
  }
  const device = $("deviceSelect").value || null;
  try {
    const status = await api("/api/workout/start", {
      method: "POST",
      body: JSON.stringify({
        user_id: Number(state.selectedUserId),
        mode,
        device_address: device,
      }),
    });
    applyStatus(status);
    return status;
  } catch (err) {
    if (quiet) $("statusMsg").textContent = err.message;
    else alert(err.message);
    return null;
  }
}

async function autoConnectUsbIfPresent(alreadyActive) {
  if (alreadyActive) return;
  $("statusMsg").textContent = "Prüfe USB…";
  try {
    const usb = await api("/api/workout/usb-status");
    if (!usb.available) {
      $("statusMsg").textContent = "";
      return;
    }
    $("btnUsb").classList.add("active-timer");
    $("statusMsg").textContent = `S4 USB erkannt (${usb.port}) — starte…`;
    const status = await startWorkout("usb", { quiet: true });
    if (status) {
      $("statusMsg").textContent = status.message || `USB live (${usb.port})`;
    }
  } catch (err) {
    $("statusMsg").textContent = err.message || "USB-Prüfung fehlgeschlagen";
  }
}

$("userSelect").addEventListener("change", () => {
  const id = $("userSelect").value;
  selectUser(id ? Number(id) : null);
});

$("btnAddUser").onclick = () => openUserForm();
$("btnCancelUser").onclick = () => closeUserForm();

$("userForm").onsubmit = async (e) => {
  e.preventDefault();
  const name = $("newUserName").value.trim();
  const sex = $("newUserSex").value || null;
  const birthYear = $("newUserBirthYear").value;
  const weight = $("newUserWeight").value;
  const maxHr = $("newUserMaxHr").value;
  const editId = state.editingUserId;
  const body = {
    name,
    sex,
    birth_year: birthYear ? Number(birthYear) : null,
    weight_kg: weight ? Number(weight) : null,
    max_hr: maxHr ? Number(maxHr) : null,
  };
  try {
    if (editId) {
      await api(`/api/users/${editId}`, { method: "PATCH", body: JSON.stringify(body) });
      state.selectedUserId = Number(editId);
      $("statusMsg").textContent = "User aktualisiert";
    } else {
      const created = await api("/api/users", {
        method: "POST",
        body: JSON.stringify(body),
      });
      state.selectedUserId = created.id;
      $("statusMsg").textContent = "User angelegt";
    }
    closeUserForm();
    await loadUsers();
    await loadSessions();
    renderHrZones();
  } catch (err) {
    const detail = err.message || "Speichern fehlgeschlagen";
    $("statusMsg").textContent = typeof detail === "string" ? detail : "Speichern fehlgeschlagen";
  }
};

$("btnScan").onclick = async () => {
  $("btnScan").disabled = true;
  $("statusMsg").textContent = "Scanne BLE…";
  try {
    const { devices } = await api("/api/workout/scan", { method: "POST", body: "{}" });
    const sel = $("deviceSelect");
    sel.innerHTML = `<option value="">Automatisch (erstes FTMS)</option>`;
    for (const d of devices) {
      const opt = document.createElement("option");
      opt.value = d.address;
      opt.textContent = `${d.name || "Unbekannt"} (${d.address})${d.rssi != null ? ` · ${d.rssi} dBm` : ""}`;
      sel.appendChild(opt);
    }
    $("statusMsg").textContent = devices.length
      ? `${devices.length} Gerät(e) gefunden`
      : "Kein ComModule gefunden — einschalten und erneut scannen";
  } catch (err) {
    $("statusMsg").textContent = err.message;
  } finally {
    $("btnScan").disabled = state.active;
  }
};

$("btnStart").onclick = () => startWorkout("ble");
$("btnDemo").onclick = () => startWorkout("demo");
$("btnUsb").onclick = () => startWorkout("usb");
$("btnStop").onclick = async () => {
  try {
    const status = await api("/api/workout/stop", { method: "POST", body: "{}" });
    applyStatus(status);
    await loadSessions();
    await loadUsers();
  } catch (err) {
    alert(err.message);
  }
};

async function timerAction(path) {
  try {
    const status = await api(path, { method: "POST", body: "{}" });
    applyStatus(status);
  } catch (err) {
    $("statusMsg").textContent = err.message;
  }
}
$("btnTimerStart").onclick = () => timerAction("/api/workout/timer/start");
$("btnTimerPause").onclick = () => timerAction("/api/workout/timer/pause");
$("btnTimerReset").onclick = () => timerAction("/api/workout/timer/reset");

setInterval(renderLocalTime, 250);
$("btnRefreshSessions").onclick = () => loadSessions();
$("btnCloseSession").onclick = () => closeSessionDetail();
$("btnDeleteSelected").onclick = () => deleteSelectedSessions();
$("sessionSelectAll").onchange = () => {
  const on = $("sessionSelectAll").checked;
  for (const box of document.querySelectorAll(".session-check")) {
    box.checked = on;
    box.closest("tr")?.classList.toggle("selected", on);
  }
  updateSessionSelectionUi();
};

(async function init() {
  initChart();
  try {
    const v = await api("/api/version");
    $("appVersion").textContent = `v${v.version}`;
    document.title = `WaterRower Dashboard v${v.version}`;
  } catch (_) {
    $("appVersion").textContent = "v?";
  }
  await loadUsers();
  await loadSessions();
  let alreadyActive = false;
  try {
    const status = await api("/api/workout/status");
    applyStatus(status);
    alreadyActive = !!status.active;
  } catch (_) {
    /* ignore */
  }
  connectWs();
  await autoConnectUsbIfPresent(alreadyActive);
})();
