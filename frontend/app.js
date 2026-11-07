"use strict";
/* Motorsport Hub — no-build SPA. Talks to the FastAPI backend under /api. */
// Default: the app fetches data itself (data.js). Set window.MH_API = "https://host" to use the optional backend.
const API = window.MH_API;
const DIRECT = API === undefined;
const app = document.getElementById("app");
const SESSION_RU = { fp1: "Практика 1", fp2: "Практика 2", fp3: "Практика 3", qualifying: "Квалификация",
  sprint_qualifying: "Спринт-квалиф.", sprint: "Спринт", race: "Гонка" };
const FLAG_RU = { GREEN: "Зелёный флаг", YELLOW: "Жёлтый флаг", DOUBLE_YELLOW: "Двойной жёлтый", RED: "Красный флаг",
  CHEQUERED: "Финиш", CLEAR: "Трасса чиста" };
let cleanup = () => {};

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDate = (d, o = { day: "numeric", month: "short" }) => new Date(d).toLocaleDateString("ru-RU", o);
const fmtTime = (d) => new Date(d).toLocaleString("ru-RU", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const lapTime = (s) => {
  if (s == null) return "—";
  const m = Math.floor(s / 60), r = (s - m * 60).toFixed(3).padStart(6, "0");
  return m ? `${m}:${r}` : (+r).toFixed(3);
};
const gap = (v, leader) => leader ? "Лидер" : v == null ? "—" : typeof v === "string" ? esc(v) : `+${v.toFixed(3)}`;

async function api(path) {
  if (DIRECT) return window.MHData.get(path);
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}
const skeleton = (n = 6) => `<div class="card">${'<div class="skeleton"></div>'.repeat(n)}</div>`;
const errorBox = (e) => `<div class="card empty"><h2>Не удалось загрузить данные</h2><p>${esc(e.message)}</p>
  <p class="muted">${navigator.onLine ? "Источник данных не ответил. Попробуйте обновить позже." : "Нет подключения к интернету."}</p></div>`;

let eventsCache = null;
async function getEvents() {
  if (!eventsCache) eventsCache = await api("/api/events?championship=f1");
  return eventsCache;
}
const seasonYear = (events) => events.length ? Math.max(...events.map((e) => e.year)) : new Date().getFullYear();
const raceStart = (e) => e.sessions.find((s) => s.kind === "race")?.starts_at_utc || `${e.end_date}T23:59:00Z`;
const nextEvent = (events) => events.find((e) => new Date(raceStart(e)) > new Date());

/* ---------------- Home ---------------- */
async function home() {
  app.innerHTML = skeleton(10);
  const events = await getEvents();
  const year = seasonYear(events);
  const [drivers, teams, winners] = await Promise.all([
    api(`/api/standings/f1/${year}?kind=driver`), api(`/api/standings/f1/${year}?kind=constructor`),
    api(`/api/results/f1/${year}`).catch(() => [])]);
  const nx = nextEvent(events);
  const last = [...winners].pop();
  app.innerHTML = `
    <section class="grid">
      ${nx ? heroCard(nx) : `<div class="hero"><div class="eyebrow">Сезон ${year}</div><h1>Сезон завершён</h1>
        <p class="sub">Календарь следующего сезона появится, как только его опубликуют.</p></div>`}
      <div class="grid g-2">
        <div class="card">
          <div class="card-head"><h2>Личный зачёт</h2><a class="link" href="#/standings">Полностью →</a></div>
          ${standingsTable(drivers, "driver", 10)}
        </div>
        <div class="grid">
          ${last ? `<div class="card"><div class="card-head"><h2>Последняя гонка</h2>
            <a class="link" href="#/event/${year}/${last.round}">Результаты →</a></div>
            <div class="muted">Этап ${last.round} · ${esc(last.event)}</div>
            <div style="font-size:22px;font-weight:700;margin-top:8px">🏆 ${esc(last.driver)}</div>
            <div class="muted">${esc(last.team)} · <span class="mono">${esc(last.time || "")}</span></div></div>` : ""}
          <div class="card"><div class="card-head"><h2>Кубок конструкторов</h2><a class="link" href="#/standings?kind=constructor">Полностью →</a></div>
            ${standingsTable(teams, "constructor", 5)}</div>
          <a class="card" href="#/live" style="display:flex;align-items:center;justify-content:space-between">
            <div><h2 style="margin:0">Живой тайминг</h2><div class="muted">Круги, интервалы, шины, сектора</div></div>
            <span class="badge live"><span class="dot"></span>LIVE</span></a>
        </div>
      </div>
    </section>`;
  if (nx) startCountdown(raceStart(nx));
}

function heroCard(e) {
  const now = new Date();
  return `<div class="hero">
    <div class="eyebrow">Следующий этап · Раунд ${e.round}</div>
    <h1>${esc(e.name)}</h1>
    <div class="muted">${fmtDate(e.start_date)} – ${fmtDate(e.end_date, { day: "numeric", month: "long", year: "numeric" })}</div>
    <div class="countdown" id="cd"></div>
    <div class="sessions">${e.sessions.map((s) => `<div class="sess ${s.starts_at_utc && new Date(s.starts_at_utc) < now ? "past" : ""}">
      <small>${SESSION_RU[s.kind] || esc(s.kind)}</small>${s.starts_at_utc ? fmtTime(s.starts_at_utc) : "время уточняется"}</div>`).join("")}</div>
  </div>`;
}

function startCountdown(target) {
  const el = document.getElementById("cd");
  const tick = () => {
    let d = Math.max(0, (new Date(target) - new Date()) / 1000);
    const parts = [["дн", 86400], ["ч", 3600], ["мин", 60], ["сек", 1]].map(([l, s]) => { const v = Math.floor(d / s); d -= v * s; return [l, v]; });
    if (el) el.innerHTML = parts.map(([l, v]) => `<div class="cd"><b>${String(v).padStart(2, "0")}</b><span>${l}</span></div>`).join("");
  };
  tick();
  const id = setInterval(tick, 1000);
  cleanup = () => clearInterval(id);
}

function standingsTable(st, kind, limit = 99) {
  if (!st.available) return `<div class="empty">${esc(st.message)}</div>`;
  const rows = st.rows.slice(0, limit), max = Math.max(...st.rows.map((r) => r.points), 1);
  return `<div class="scroll-x"><table class="table"><thead><tr><th>#</th><th>${kind === "driver" ? "Пилот" : "Команда"}</th>
    <th class="num">Победы</th><th class="num">Очки</th></tr></thead><tbody>
    ${rows.map((r) => `<tr><td class="pos p${r.position}">${r.position}</td>
      <td class="who">${esc(kind === "driver" ? r.driver : r.team)}${kind === "driver" ? `<small>${esc(r.team || "")}</small>` : ""}
        <div class="bar"><i style="width:${(r.points / max) * 100}%"></i></div></td>
      <td class="num">${r.wins ?? 0}</td><td class="num"><b>${r.points}</b></td></tr>`).join("")}
    </tbody></table></div>
    ${st.possibly_outdated ? '<div class="notice" style="margin:12px 0 0">Источник временно недоступен — показаны последние сохранённые данные.</div>' : ""}
    <div class="muted" style="font-size:12px;margin-top:10px">После этапа ${st.after_round ?? "—"}</div>`;
}

/* ---------------- Standings ---------------- */
async function standings(params) {
  const kind = params.get("kind") === "constructor" ? "constructor" : "driver";
  app.innerHTML = skeleton(12);
  const year = seasonYear(await getEvents());
  const st = await api(`/api/standings/f1/${year}?kind=${kind}`);
  app.innerHTML = `<h1>Чемпионат ${year}</h1><p class="sub">Формула 1</p>
    <div class="tabs"><button data-k="driver" class="${kind === "driver" ? "active" : ""}">Пилоты</button>
    <button data-k="constructor" class="${kind === "constructor" ? "active" : ""}">Конструкторы</button></div>
    <div class="card">${standingsTable(st, kind)}</div>`;
  app.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => location.hash = `#/standings?kind=${b.dataset.k}`);
}

/* ---------------- Calendar ---------------- */
async function calendar() {
  app.innerHTML = skeleton(8);
  const events = await getEvents();
  const year = seasonYear(events);
  const winners = Object.fromEntries((await api(`/api/results/f1/${year}`).catch(() => [])).map((w) => [w.round, w]));
  const nx = nextEvent(events);
  const list = events.filter((e) => e.year === year);
  app.innerHTML = `<h1>Календарь ${year}</h1><p class="sub">${list.length} этапов · время показано в вашем часовом поясе</p>
    ${list.length ? `<div class="cal">${list.map((e) => {
      const done = new Date(raceStart(e)) < new Date(), w = winners[e.round];
      return `<a class="race ${nx && nx.round === e.round ? "next" : ""} ${done ? "done" : ""}" href="#/event/${e.year}/${e.round}">
        <div style="display:flex;justify-content:space-between"><span class="rnd">РАУНД ${String(e.round).padStart(2, "0")}</span>
        ${nx && nx.round === e.round ? '<span class="badge live">Далее</span>' : done ? '<span class="badge">Завершён</span>' : ""}</div>
        <h3>${esc(e.name)}</h3><div class="muted">${fmtDate(e.start_date)} – ${fmtDate(e.end_date)}</div>
        ${e.sessions.some((s) => s.kind === "sprint") ? '<span class="badge warn" style="margin-top:8px">Спринт</span>' : ""}
        ${w ? `<div class="winner">🏆 ${esc(w.driver)} · ${esc(w.team)}</div>` : ""}</a>`;
    }).join("")}</div>` : '<div class="card empty"><h2>Календарь пуст</h2><p>Запустите обновление данных на сервере.</p></div>'}`;
}

/* ---------------- Event ---------------- */
async function eventPage(year, round) {
  app.innerHTML = skeleton(12);
  const ev = await api(`/api/events/f1/${year}/${round}`);
  const withRes = ev.sessions.filter((s) => s.results.length);
  let active = (withRes.find((s) => s.kind === "race") || withRes[0] || {}).kind;
  const render = () => {
    const s = ev.sessions.find((x) => x.kind === active);
    app.innerHTML = `<a class="link" href="#/calendar">← Календарь</a>
      <h1 style="margin-top:10px">${esc(ev.name)}</h1>
      <p class="sub">Раунд ${ev.round} · ${fmtDate(ev.start_date)} – ${fmtDate(ev.end_date, { day: "numeric", month: "long", year: "numeric" })}</p>
      <div class="card" style="margin-bottom:18px"><h2>Расписание</h2><div class="sessions">
        ${ev.sessions.map((x) => `<div class="sess"><small>${SESSION_RU[x.kind] || esc(x.kind)}</small>${x.starts_at_utc ? fmtTime(x.starts_at_utc) : "время уточняется"}</div>`).join("")}
      </div></div>
      ${withRes.length ? `<div class="tabs">${withRes.map((x) => `<button data-k="${x.kind}" class="${x.kind === active ? "active" : ""}">${SESSION_RU[x.kind] || esc(x.kind)}</button>`).join("")}</div>
      <div class="card scroll-x">${resultsTable(s)}</div>`
      : `<div class="card empty"><h2>Результатов пока нет</h2><p>Они появятся после сессий.</p>
         ${ev.live_timing_available ? '<a class="badge live" href="#/live"><span class="dot"></span>Открыть живой тайминг</a>' : ""}</div>`}`;
    app.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => { active = b.dataset.k; render(); });
  };
  render();
}

function resultsTable(s) {
  const q = s.kind === "qualifying";
  return `<table class="table"><thead><tr><th>#</th><th>Пилот</th><th>Команда</th>
    ${q ? "<th>Сегмент</th><th class='num'>Лучшее время</th>" : "<th class='num'>Старт</th><th class='num'>Круги</th><th class='num'>Время / статус</th><th class='num'>Очки</th>"}
    </tr></thead><tbody>${s.results.map((r) => `<tr><td class="pos p${r.position}">${r.position ?? "—"}</td>
      <td class="who">${esc(r.driver)} <small>#${esc(r.car_number || "")} ${esc(r.driver_code || "")}</small></td><td class="muted">${esc(r.team)}</td>
      ${q ? `<td><span class="badge">${esc(r.status)}</span></td><td class="num">${esc(r.time || "—")}</td>`
          : `<td class="num">${r.grid ?? "—"}</td><td class="num">${r.laps ?? "—"}</td>
             <td class="num">${esc(r.time || r.status)}</td><td class="num"><b>${r.points || ""}</b></td>`}</tr>`).join("")}
    </tbody></table>`;
}

/* ---------------- Live timing ---------------- */
async function livePage(params) {
  const key = params.get("session") || "latest";
  let selected = null, es = null, lastSnap = null;
  app.innerHTML = `<div class="live-head"><div><h1>Живой тайминг</h1><p class="sub" id="lv-sub" style="margin:0">Подключение…</p></div>
    <div class="live-meta" id="lv-meta"></div></div><div id="lv-notice"></div>
    <div class="grid g-live"><div><div class="card scroll-x" id="lv-tower">${'<div class="skeleton"></div>'.repeat(12)}</div>
    <div id="lv-drawer"></div></div>
    <div class="grid" style="align-content:start"><div class="card" id="lv-wx"><h2>Погода</h2><div class="muted">—</div></div>
    <div class="card"><h2>Дирекция гонки</h2><ul class="side-list" id="lv-rc"><li class="muted">—</li></ul></div>
    <div class="card"><h2>Другая сессия</h2><select id="lv-sel"><option value="latest">Текущая / последняя</option></select></div>
    ${DIRECT ? `<details class="card"><summary style="cursor:pointer;font-weight:600">Подписка OpenF1</summary>
      <p class="muted" style="font-size:13px">Прошедшие сессии бесплатны. Для данных во время сессии вставьте токен доступа OpenF1 (хранится только на этом устройстве).</p>
      <input id="lv-token" type="password" placeholder="access token" style="width:100%;background:var(--card-2);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:8px 12px">
      <button id="lv-token-save" class="badge" style="margin-top:8px;border:0;cursor:pointer">Сохранить</button></details>` : ""}</div></div>`;
  const tok = document.getElementById("lv-token");
  if (tok) {
    try { tok.value = localStorage.getItem("mh_openf1_token") || ""; } catch { /* storage blocked */ }
    document.getElementById("lv-token-save").onclick = () => { try { localStorage.setItem("mh_openf1_token", tok.value.trim()); } catch { /* */ } route(); };
  }

  // session picker (past sessions can be replayed)
  api(`/api/live/f1/sessions?year=${new Date().getFullYear()}`).then((list) => {
    const sel = document.getElementById("lv-sel");
    if (!sel) return;
    sel.innerHTML += list.reverse().map((s) => `<option value="${s.session_key}" ${String(s.session_key) === key ? "selected" : ""}>
      ${esc(s.country || s.circuit)} · ${esc(s.name)}</option>`).join("");
    sel.onchange = () => location.hash = sel.value === "latest" ? "#/live" : `#/live?session=${sel.value}`;
  }).catch(() => {});

  const render = (snap) => {
    lastSnap = snap;
    const sub = document.getElementById("lv-sub");
    if (!sub) return;
    if (!snap.available) {
      sub.textContent = "Данные недоступны";
      document.getElementById("lv-tower").innerHTML = `<div class="empty"><h2>Тайминг недоступен</h2><p>${esc(snap.message || "Нет данных")}</p></div>`;
      return;
    }
    const s = snap.session;
    sub.innerHTML = `${esc(s.country)} · ${esc(s.circuit)} · <b>${esc(s.name)}</b>`;
    document.getElementById("lv-meta").innerHTML = `
      ${s.status === "live" ? '<span class="badge live"><span class="dot"></span>В эфире</span>' : `<span class="badge">${s.status === "finished" ? "Завершена" : "Скоро"}</span>`}
      ${snap.track_flag ? `<span class="flag ${esc(snap.track_flag)}">${FLAG_RU[snap.track_flag] || esc(snap.track_flag)}</span>` : ""}
      ${snap.leader_lap ? `<span class="badge">Круг ${snap.leader_lap}</span>` : ""}
      ${snap.fastest_lap ? `<span class="badge" style="color:var(--purple)">⏱ ${esc(snap.fastest_lap.code)} ${lapTime(snap.fastest_lap.time)}</span>` : ""}`;
    document.getElementById("lv-notice").innerHTML = snap.possibly_outdated
      ? `<div class="notice">Связь с источником потеряна, показаны последние данные. ${esc(snap.last_error || "")}</div>` : "";
    const race = /race|sprint/i.test(s.type || s.name || "");
    document.getElementById("lv-tower").innerHTML = `<table class="table tower"><thead><tr><th>#</th><th></th><th>Пилот</th>
      <th class="num">${race ? "Отрыв" : "От лучшего"}</th><th class="num">Интервал</th><th class="num">Последний</th><th>Сектора</th>
      <th class="num">Лучший</th><th>Шины</th><th class="num">Пит</th></tr></thead><tbody>
      ${snap.timing.map((r, i) => {
        const L = r.last_lap;
        const cls = L ? (L.overall_best ? "ob" : L.personal_best ? "pb" : "") : "";
        const bestGap = !race && r.best_lap && snap.fastest_lap ? r.best_lap.time - snap.fastest_lap.time : null;
        return `<tr class="clickable" data-n="${r.driver_number}" ${selected === r.driver_number ? 'style="background:#ffffff0a"' : ""}>
        <td class="pos p${r.position}">${r.position ?? "—"}</td>
        <td class="team"><i style="background:${esc(r.team_colour || "#555")}"></i></td>
        <td><span class="code">${esc(r.code || r.driver_number)}</span> <span class="muted" style="font-size:12px">${esc(r.team || "")}</span></td>
        <td class="num t">${race ? gap(r.gap_to_leader, i === 0) : i === 0 ? "—" : bestGap != null ? `+${bestGap.toFixed(3)}` : "—"}</td>
        <td class="num t">${race ? gap(r.interval, i === 0) : "—"}</td>
        <td class="num t ${cls}">${L ? lapTime(L.time) : "—"}${L && L.pit_out_lap ? ' <span class="badge">OUT</span>' : ""}</td>
        <td><div class="sectors">${(L ? L.sectors : [null, null, null]).map((x, j) =>
          `<span class="${x == null ? "none" : L.sector_overall_best[j] ? "ob" : ""}" title="${x ?? ""}"></span>`).join("")}</div></td>
        <td class="num t ${r.best_lap && snap.fastest_lap && r.best_lap.time === snap.fastest_lap.time ? "ob" : ""}">${r.best_lap ? lapTime(r.best_lap.time) : "—"}</td>
        <td>${r.tyre ? `<span class="tyre ${esc(r.tyre.compound)}"><i>${esc((r.tyre.compound || "?")[0])}</i><span>${r.tyre.age_laps}</span></span>` : "—"}</td>
        <td class="num t">${r.pit_stops}</td></tr>`;
      }).join("")}</tbody></table>`;
    document.querySelectorAll("#lv-tower tr[data-n]").forEach((tr) => tr.onclick = () => { selected = +tr.dataset.n; render(lastSnap); loadLaps(); });
    const w = snap.weather;
    document.getElementById("lv-wx").innerHTML = `<h2>Погода</h2>${w ? `<div class="wx">
      <div><b>${w.air_temperature ?? "—"}°</b><span>Воздух</span></div><div><b>${w.track_temperature ?? "—"}°</b><span>Трасса</span></div>
      <div><b>${w.humidity ?? "—"}%</b><span>Влажность</span></div><div><b>${w.rainfall ? "Да" : "Нет"}</b><span>Дождь</span></div></div>` : '<div class="muted">Нет данных</div>'}`;
    document.getElementById("lv-rc").innerHTML = snap.race_control.length ? snap.race_control.map((m) =>
      `<li><small>${m.lap ? `L${m.lap} · ` : ""}${m.date ? new Date(m.date).toLocaleTimeString("ru-RU") : ""}</small><br>${esc(m.message)}</li>`).join("")
      : '<li class="muted">Сообщений нет</li>';
  };

  async function loadLaps() {
    const box = document.getElementById("lv-drawer");
    if (!box || selected == null) return;
    const d = lastSnap.timing.find((r) => r.driver_number === selected) || {};
    const laps = await api(`/api/live/f1/laps/${selected}?session_key=${encodeURIComponent(key)}`).catch(() => []);
    const timed = laps.filter((l) => l.time != null);
    box.innerHTML = `<div class="card drawer"><div class="card-head"><h2><span style="color:${esc(d.team_colour)}">●</span> ${esc(d.name || d.code)} — круги</h2>
      <button class="link" style="background:none;border:0;cursor:pointer" id="lv-close">Закрыть ✕</button></div>
      ${timed.length > 1 ? lapChart(timed) : ""}
      <div class="scroll-x" style="max-height:360px;overflow:auto"><table class="table"><thead><tr><th>Круг</th><th class="num">Время</th>
      <th class="num">С1</th><th class="num">С2</th><th class="num">С3</th><th class="num">Спидтрап</th></tr></thead><tbody>
      ${laps.slice().reverse().map((l) => `<tr><td class="mono">${l.lap}${l.pit_out_lap ? ' <span class="badge">OUT</span>' : ""}</td>
        <td class="num ${d.best_lap && l.lap === d.best_lap.lap ? "pb" : ""}">${lapTime(l.time)}</td>
        ${l.sectors.map((x) => `<td class="num">${x != null ? x.toFixed(3) : "—"}</td>`).join("")}
        <td class="num">${l.speeds_kph.trap ?? "—"}</td></tr>`).join("")}</tbody></table></div></div>`;
    document.getElementById("lv-close").onclick = () => { selected = null; box.innerHTML = ""; render(lastSnap); };
  }

  // Server-Sent Events, falling back to polling if the stream breaks
  let pollId = null;
  const poll = async () => { try { render(await api(`/api/live/f1?session_key=${encodeURIComponent(key)}`)); } catch (e) { /* keep last */ } };
  if (!DIRECT && "EventSource" in window) {
    es = new EventSource(`${API}/api/live/f1/stream?session_key=${encodeURIComponent(key)}`);
    es.onmessage = (m) => { render(JSON.parse(m.data)); if (selected != null) loadLaps(); };
    es.onerror = () => { es.close(); es = null; if (!pollId) { poll(); pollId = setInterval(poll, 5000); } };
  } else {
    const tick = async () => { await poll(); if (selected != null) loadLaps(); };
    tick(); pollId = setInterval(tick, 4000);
  }
  cleanup = () => { es && es.close(); pollId && clearInterval(pollId); };
}

function lapChart(laps) {
  const W = 800, H = 160, p = 28;
  const ts = laps.map((l) => l.time), lo = Math.min(...ts), hi = Math.min(Math.max(...ts), lo * 1.12);
  const x = (i) => p + (i / (laps.length - 1)) * (W - 2 * p);
  const y = (t) => p / 2 + (1 - (Math.min(t, hi) - lo) / ((hi - lo) || 1)) * (H - p);
  const pts = laps.map((l, i) => `${x(i).toFixed(1)},${y(l.time).toFixed(1)}`).join(" ");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="График времени круга">
    <line x1="${p}" x2="${W - p}" y1="${y(lo)}" y2="${y(lo)}" stroke="#b14cff55" stroke-dasharray="4 4"/>
    <text x="${p}" y="${y(lo) - 4}" fill="#b14cff" font-size="11" font-family="JetBrains Mono">${lapTime(lo)}</text>
    <polyline points="${pts}" fill="none" stroke="#ff3b30" stroke-width="2" vector-effect="non-scaling-stroke"/>
    ${laps.map((l, i) => `<circle cx="${x(i)}" cy="${y(l.time)}" r="2.5" fill="${l.time === lo ? "#b14cff" : "#ff3b30"}"><title>Круг ${l.lap}: ${lapTime(l.time)}</title></circle>`).join("")}
  </svg>`;
}

/* ---------------- router ---------------- */
async function route() {
  cleanup(); cleanup = () => {};
  const [path, qs] = (location.hash.slice(1) || "/").split("?");
  const params = new URLSearchParams(qs || "");
  const parts = path.split("/").filter(Boolean);
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active",
    a.getAttribute("href") === "#/" + (parts[0] || "") || (parts[0] === "event" && a.getAttribute("href") === "#/calendar")));
  window.scrollTo(0, 0);
  try {
    if (!parts.length) await home();
    else if (parts[0] === "calendar") await calendar();
    else if (parts[0] === "standings") await standings(params);
    else if (parts[0] === "event") await eventPage(+parts[1], +parts[2]);
    else if (parts[0] === "live") await livePage(params);
    else app.innerHTML = '<div class="card empty"><h2>Страница не найдена</h2><a class="link" href="#/">На главную</a></div>';
  } catch (e) { app.innerHTML = errorBox(e); }
}
window.addEventListener("hashchange", route);
window.addEventListener("online", route);
route();
if ("serviceWorker" in navigator && location.protocol !== "file:") navigator.serviceWorker.register("sw.js").catch(() => {});
