"use strict";
/* Client-side data layer: the app talks to Jolpica-F1 and OpenF1 directly from the
   device, no own server needed. Returns the same JSON shapes as the optional backend
   (backend/app/main.py), so the UI does not care which one is used.
   Not yet run against the live services from the dev sandbox (no network there). */
(function () {
  const JOLPICA = "https://api.jolpi.ca/ergast/f1";
  const OPENF1 = "https://api.openf1.org/v1";
  const HOUR = 3600e3;
  const SESSION_KEYS = { FirstPractice: "fp1", SecondPractice: "fp2", ThirdPractice: "fp3",
    SprintQualifying: "sprint_qualifying", SprintShootout: "sprint_qualifying", Sprint: "sprint", Qualifying: "qualifying" };

  /* ---------- HTTP with offline cache (localStorage) ---------- */
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
    set(k, v) {
      try { localStorage.setItem(k, JSON.stringify(v)); }
      catch { try { Object.keys(localStorage).filter((x) => x.startsWith("mh:")).forEach((x) => localStorage.removeItem(x)); } catch { /* storage unavailable */ } }
    },
  };
  let offline = false;  // set when any request fell back to cache

  async function fetchJSON(url, headers = {}) {
    let r;
    for (let attempt = 0; attempt < 2; attempt++) {
      r = await fetch(url, { headers });
      if (r.status === 429 && attempt === 0) { await new Promise((res) => setTimeout(res, 2000)); continue; }
      break;
    }
    if (r.status === 404) return null;
    if (r.status === 401 || r.status === 403) {
      const e = new Error("Источник требует подписку: живые данные во время сессии доступны только с токеном OpenF1."); e.auth = true; throw e;
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  async function cached(url, ttl) {
    const key = "mh:" + url, hit = store.get(key);
    if (hit && Date.now() - hit.t < ttl) return hit.v;
    try {
      const v = await fetchJSON(url);
      store.set(key, { t: Date.now(), v });
      return v;
    } catch (e) {
      if (hit) { offline = true; return hit.v; }  // no network: last saved data
      throw e;
    }
  }
  const mr = async (path, ttl = 6 * HOUR) => (await cached(`${JOLPICA}/${path}`, ttl))?.MRData;

  /* ---------- Jolpica parsers (mirror backend/app/adapters/jolpica_f1.py) ---------- */
  const dt = (d, t) => (d && t ? new Date(`${d}T${t.replace("Z", "")}Z`).toISOString() : null);
  const driverName = (d) => `${d.givenName} ${d.familyName}`;

  function parseEvent(r) {
    const sessions = Object.entries(r).filter(([k]) => k in SESSION_KEYS)
      .map(([k, v]) => ({ kind: SESSION_KEYS[k], starts_at_utc: dt(v.date, v.time) }));
    sessions.push({ kind: "race", starts_at_utc: dt(r.date, r.time) });
    sessions.sort((a, b) => (a.starts_at_utc || "9") < (b.starts_at_utc || "9") ? -1 : 1);
    const dates = [r.date, ...Object.keys(r).filter((k) => k in SESSION_KEYS).map((k) => r[k].date)].sort();
    return { championship: "f1", year: +r.season, round: +r.round, name: r.raceName,
      circuit: r.Circuit?.circuitName, locality: r.Circuit?.Location?.locality, country: r.Circuit?.Location?.country,
      start_date: dates[0], end_date: dates[dates.length - 1], sessions };
  }

  async function season() {
    const y = new Date().getFullYear();
    const cur = await mr(`${y}.json?limit=100`);
    return cur && cur.RaceTable.Races.length ? y : y - 1;  // new season not published yet
  }

  async function events() {
    const y = await season();
    return (await mr(`${y}.json?limit=100`)).RaceTable.Races.map(parseEvent);
  }

  async function standings(year, kind) {
    const m = await mr(`${year}/${kind === "constructor" ? "constructorstandings" : "driverstandings"}.json`, 2 * HOUR);
    const lists = m?.StandingsTable?.StandingsLists || [];
    if (!lists.length) return { available: false, message: "Зачёт этого сезона ещё не опубликован.", rows: [] };
    const sl = lists[0];
    const rows = (kind === "constructor" ? sl.ConstructorStandings : sl.DriverStandings).map((x) => ({
      position: +x.position, points: +x.points, wins: +x.wins,
      driver: x.Driver ? driverName(x.Driver) : null,
      team: x.Constructor ? x.Constructor.name : x.Constructors?.[x.Constructors.length - 1]?.name,
      nationality: (x.Driver || x.Constructor)?.nationality }));
    return { available: true, after_round: +sl.round, possibly_outdated: offline, rows };
  }

  async function winners(year) {  // only P1 of every race: one small request
    const m = await mr(`${year}/results/1.json?limit=100`, 2 * HOUR);
    return (m?.RaceTable?.Races || []).map((r) => {
      const x = r.Results[0];
      return { round: +r.round, event: r.raceName, driver: driverName(x.Driver), team: x.Constructor.name, time: x.Time?.time };
    });
  }

  function resultRows(list, qual) {
    return (list || []).map((x) => ({
      position: qual ? +x.position : /^\d+$/.test(x.positionText || "") ? +x.position : null,
      status: qual ? (x.Q3 ? "Q3" : x.Q2 ? "Q2" : "Q1") : x.status,
      car_number: x.number, driver: driverName(x.Driver), driver_code: x.Driver.code, team: x.Constructor.name,
      grid: x.grid ? +x.grid : null, laps: x.laps ? +x.laps : null,
      time: qual ? (x.Q3 || x.Q2 || x.Q1 || null) : x.Time?.time || null, points: x.points ? +x.points : 0 }));
  }

  async function eventDetail(year, round) {
    const [sch, race, sprint, quali] = await Promise.all([
      mr(`${year}/${round}.json`), mr(`${year}/${round}/results.json`, HOUR),
      mr(`${year}/${round}/sprint.json`, HOUR), mr(`${year}/${round}/qualifying.json`, HOUR)]);
    const r = sch?.RaceTable?.Races?.[0];
    if (!r) throw new Error("Этап не найден");
    const ev = parseEvent(r);
    const res = { race: resultRows(race?.RaceTable?.Races?.[0]?.Results),
      sprint: resultRows(sprint?.RaceTable?.Races?.[0]?.SprintResults),
      qualifying: resultRows(quali?.RaceTable?.Races?.[0]?.QualifyingResults, true) };
    ev.sessions = ev.sessions.map((s) => ({ ...s, results: res[s.kind] || [] }));
    ev.live_timing_available = true;
    return ev;
  }

  /* ---------- OpenF1 live timing (mirror backend/app/live/openf1.py) ---------- */
  const INCREMENTAL = { intervals: "date", position: "date", laps: "date_start", pit: "date", race_control: "date", weather: "date" };
  const FULL = ["drivers", "stints"];
  const feeds = new Map();
  let latest = null;

  const token = () => { try { return localStorage.getItem("mh_openf1_token") || ""; } catch { return ""; } };
  const of1 = (ep, params) => {
    const q = Object.entries(params).map(([k, v]) => /[<>]$/.test(k)
      ? `${encodeURIComponent(k.slice(0, -1))}${k.slice(-1)}${encodeURIComponent(v)}`
      : `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
    const t = token();
    return fetchJSON(`${OPENF1}/${ep}?${q}`, t ? { Authorization: `Bearer ${t}` } : {}).then((x) => x || []);
  };

  async function resolveSession(key) {
    if (key === "latest") {
      if (latest && Date.now() - latest.t < 60e3) return latest.s;
      const s = (await of1("sessions", { session_key: "latest" }))[0];
      if (!s) throw new Error("OpenF1 не вернул текущую сессию");
      latest = { t: Date.now(), s };
      return s;
    }
    if (feeds.has(+key)) return feeds.get(+key).session;
    const s = (await of1("sessions", { session_key: key }))[0];
    if (!s) throw new Error("Сессия не найдена");
    return s;
  }

  async function poll(feed) {
    const sk = feed.session.session_key;
    const inc = Object.entries(INCREMENTAL).map(async ([ep, field]) => {
      const p = { session_key: sk };
      if (feed.cursor[ep]) p[`${field}>`] = feed.cursor[ep];
      const rows = (await of1(ep, p)).filter((r) => r[field]);
      if (rows.length) {
        feed.rows[ep].push(...rows);
        feed.cursor[ep] = rows.reduce((m, r) => (r[field] > m ? r[field] : m), feed.cursor[ep] || "");
      }
    });
    const full = FULL.map(async (ep) => { feed.rows[ep] = await of1(ep, { session_key: sk }); });
    await Promise.all([...inc, ...full]);
    feed.polledAt = new Date();
  }

  const status = (s, now = new Date()) =>
    s.date_start && now < new Date(s.date_start) ? "upcoming" : s.date_end && now > new Date(s.date_end) ? "finished" : "live";

  function latestBy(rows, f = "date") {
    const out = new Map();
    for (const r of rows) if (r.driver_number != null && (!out.has(r.driver_number) || (r[f] || "") >= (out.get(r.driver_number)[f] || ""))) out.set(r.driver_number, r);
    return out;
  }
  const gapVal = (v) => (v == null || typeof v === "string" ? v : Math.round(v * 1000) / 1000);

  function buildSnapshot(s, rows) {
    const drivers = new Map((rows.drivers || []).map((d) => [d.driver_number, d]));
    const pos = latestBy(rows.position || []), ints = latestBy(rows.intervals || []);
    const lapsBy = new Map(), stintsBy = new Map(), pits = new Map();
    for (const l of rows.laps || []) (lapsBy.get(l.driver_number) || lapsBy.set(l.driver_number, []).get(l.driver_number)).push(l);
    for (const x of rows.stints || []) (stintsBy.get(x.driver_number) || stintsBy.set(x.driver_number, []).get(x.driver_number)).push(x);
    for (const p of rows.pit || []) pits.set(p.driver_number, (pits.get(p.driver_number) || 0) + 1);
    const timed = (l) => l.lap_duration != null;
    const all = [...lapsBy.values()].flat().filter(timed);
    const ob = all.reduce((m, l) => (!m || l.lap_duration < m.lap_duration ? l : m), null);
    const bs = [1, 2, 3].map((i) => Math.min(...all.map((l) => l[`duration_sector_${i}`]).filter((x) => x != null)));
    const nums = new Set([...drivers.keys(), ...pos.keys(), ...lapsBy.keys()]);
    const tower = [...nums].map((n) => {
      const d = drivers.get(n) || {}, laps = (lapsBy.get(n) || []).sort((a, b) => a.lap_number - b.lap_number);
      const done = laps.filter(timed), last = done[done.length - 1] || null;
      const best = done.reduce((m, l) => (!m || l.lap_duration < m.lap_duration ? l : m), null);
      const stint = (stintsBy.get(n) || []).reduce((m, x) => (!m || (x.stint_number || 0) > (m.stint_number || 0) ? x : m), null);
      const cur = laps.length ? laps[laps.length - 1].lap_number : null;
      const iv = ints.get(n) || {};
      return {
        position: pos.get(n)?.position ?? null, driver_number: n, code: d.name_acronym,
        name: d.full_name || d.broadcast_name, team: d.team_name, team_colour: d.team_colour ? `#${d.team_colour}` : null,
        gap_to_leader: gapVal(iv.gap_to_leader), interval: gapVal(iv.interval), current_lap: cur, laps_completed: done.length,
        last_lap: last && { lap: last.lap_number, time: last.lap_duration,
          sectors: [1, 2, 3].map((i) => last[`duration_sector_${i}`] ?? null),
          personal_best: best === last, overall_best: ob === last,
          sector_overall_best: [1, 2, 3].map((i, j) => last[`duration_sector_${i}`] != null && last[`duration_sector_${i}`] === bs[j]),
          speed_trap_kph: last.st_speed, pit_out_lap: !!last.is_pit_out_lap },
        best_lap: best && { lap: best.lap_number, time: best.lap_duration },
        tyre: stint && { compound: stint.compound, stint: stint.stint_number,
          age_laps: (stint.tyre_age_at_start || 0) + (cur && stint.lap_start ? Math.max(cur - stint.lap_start, 0) : 0) },
        pit_stops: pits.get(n) || 0 };
    }).sort((a, b) => (a.position == null) - (b.position == null) || (a.position || 0) - (b.position || 0) || a.driver_number - b.driver_number);
    const w = (rows.weather || []).reduce((m, x) => (!m || (x.date || "") > (m.date || "") ? x : m), null);
    const rc = [...(rows.race_control || [])].sort((a, b) => ((b.date || "") > (a.date || "") ? 1 : -1)).slice(0, 30);
    const flag = rc.find((m) => m.flag && (m.scope || "Track") === "Track")?.flag || null;
    return {
      available: true,
      session: { session_key: s.session_key, name: s.session_name, type: s.session_type, circuit: s.circuit_short_name,
        country: s.country_name, location: s.location, date_start: s.date_start, date_end: s.date_end, status: status(s) },
      leader_lap: Math.max(0, ...tower.map((r) => r.current_lap || 0)) || null, track_flag: flag,
      fastest_lap: ob && { driver_number: ob.driver_number, code: drivers.get(ob.driver_number)?.name_acronym, lap: ob.lap_number, time: ob.lap_duration },
      weather: w, race_control: rc.map((m) => ({ date: m.date, lap: m.lap_number, category: m.category, flag: m.flag, driver_number: m.driver_number, message: m.message })),
      timing: tower };
  }

  async function liveSnapshot(key = "latest") {
    let s;
    try { s = await resolveSession(key); } catch (e) { return { available: false, message: e.message, timing: [] }; }
    let feed = feeds.get(s.session_key);
    if (!feed) {
      if (feeds.size >= 4) feeds.delete(feeds.keys().next().value);
      feed = { session: s, rows: Object.fromEntries([...Object.keys(INCREMENTAL), ...FULL].map((k) => [k, []])), cursor: {}, polledAt: null, error: null };
      feeds.set(s.session_key, feed);
    }
    const frozen = feed.polledAt && status(s) === "finished" && s.date_end && feed.polledAt > new Date(s.date_end);
    if (!frozen && (!feed.polledAt || Date.now() - feed.polledAt > 3500)) {
      try { await poll(feed); feed.error = null; } catch (e) { feed.error = e.message; }
    }
    if (!feed.polledAt) return { available: false, message: feed.error, timing: [] };
    return { ...buildSnapshot(s, feed.rows), retrieved_at: feed.polledAt.toISOString(),
      possibly_outdated: !!feed.error, last_error: feed.error };
  }

  async function liveLaps(key, n) {
    const s = await resolveSession(key);
    const feed = feeds.get(s.session_key);
    return (feed ? feed.rows.laps : []).filter((r) => r.driver_number === n).sort((a, b) => a.lap_number - b.lap_number)
      .map((r) => ({ lap: r.lap_number, time: r.lap_duration, sectors: [1, 2, 3].map((i) => r[`duration_sector_${i}`] ?? null),
        speeds_kph: { i1: r.i1_speed, i2: r.i2_speed, trap: r.st_speed }, pit_out_lap: !!r.is_pit_out_lap, started_at: r.date_start }));
  }

  async function liveSessions(year) {
    const list = await cached(`${OPENF1}/sessions?year=${year}`, HOUR).catch(() => []);
    return (list || []).filter((s) => new Date(s.date_start) < new Date()).map((s) => ({ session_key: s.session_key,
      name: s.session_name, type: s.session_type, circuit: s.circuit_short_name, country: s.country_name, date_start: s.date_start }));
  }

  /* ---------- router with the backend's URL shapes ---------- */
  async function get(path) {
    const u = new URL(path, "https://x");
    const p = u.pathname.split("/").filter(Boolean).slice(1);  // drop "api"
    const q = u.searchParams;
    switch (p[0]) {
      case "events": return p.length === 1 ? events() : eventDetail(+p[2], +p[3]);
      case "standings": return standings(+p[2], q.get("kind") || "driver");
      case "results": return winners(+p[2]);
      case "live":
        if (p[2] === "sessions") return liveSessions(q.get("year") || new Date().getFullYear());
        if (p[2] === "laps") return liveLaps(q.get("session_key") || "latest", +p[3]);
        return liveSnapshot(q.get("session_key") || "latest");
    }
    throw new Error("unknown path " + path);
  }

  window.MHData = { get, buildSnapshot, isOffline: () => offline };
})();
