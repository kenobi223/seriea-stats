/**
 * Serie A Stats — Cloudflare Worker (facciata read + community).
 *
 * Legge lo stesso Upstash Redis del motore GitHub Actions (engine.py):
 *   seriea:state.json      -> /api/state, /api/health, /api/results, ...
 *   seriea:community.json  -> /api/community (GET/POST, stessa logica Flask)
 *   seriea:learning.json   -> /api/tracking-records
 *
 * Il sito statico (index.html, app.js, ...) e' servito dagli Assets
 * bindings (wrangler.toml): le richieste non-statiche arrivano qui.
 *
 * NOTA: estensione .mjs (non .js) perche' il repo non ha package.json con
 * "type":"module": cosi' node puo' importare il modulo direttamente nei test.
 */

const API_TOKENS = { state: "seriea:state.json", learning: "seriea:learning.json", community: "seriea:community.json" };

async function redisGet(env, key) {
  const res = await fetch(env.UPSTASH_REDIS_REST_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.UPSTASH_REDIS_REST_TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(["GET", key]),
  });
  if (!res.ok) throw new Error(`upstash GET ${key}: HTTP ${res.status}`);
  const data = await res.json();
  if (data.result == null) return null;
  try { return JSON.parse(data.result); } catch { return null; }
}

async function redisSet(env, key, value) {
  const res = await fetch(env.UPSTASH_REDIS_REST_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.UPSTASH_REDIS_REST_TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(["SET", key, JSON.stringify(value)]),
  });
  if (!res.ok) throw new Error(`upstash SET ${key}: HTTP ${res.status}`);
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

function err(message, status) { return json({ error: message }, status); }

// ------------------------------------------------------------------ markets
function matchOutcomes(home, away) {
  const o3 = home > away ? "1" : home < away ? "2" : "x";
  const totals = home + away;
  return { "1x2": o3, over_under: totals > 2.5 ? "over_2.5" : "under_2.5", btts: home > 0 && away > 0 ? "si" : "no" };
}

// ------------------------------------------------------------------ schedina
function currentRound(state) {
  const played = (state.standings || []).map((r) => r.played || 0);
  if (!played.length) return null;
  const mn = Math.min(...played), mx = Math.max(...played);
  return mn !== mx ? mx : mx + 1;
}

function sig(picks) {
  const rows = (picks || []).map((p) => [String(p.fixture_id ?? ""), p.market, p.pick]);
  rows.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : 0));
  return JSON.stringify(rows);
}

function dedupeHistory(history) {
  const hist = history || [];
  const counts = new Map();
  for (const h of hist) counts.set(sig(h.picks), (counts.get(sig(h.picks)) || 0) + 1);
  const out = [], rounds = new Set();
  for (const h of hist) {
    if (counts.get(sig(h.picks)) > 1) continue;
    if (rounds.has(h.round)) continue;
    rounds.add(h.round);
    out.push(h);
  }
  return out;
}

function schedinaPayload(slip) {
  const picks = slip?.picks || [];
  return {
    round: slip?.round ?? null,
    created_at: slip?.created_at ?? null,
    wins: picks.filter((p) => p.result === "win").length,
    losses: picks.filter((p) => p.result === "loss").length,
    picks,
    history: dedupeHistory(slip?.history || []),
  };
}

// ------------------------------------------------------------------ community
const VALID = { "1x2": new Set(["1", "x", "2"]), over_under: new Set(["over_2.5", "under_2.5"]), btts: new Set(["si", "no"]) };
const MAX_ROUNDS = 4;

function communityLoad(data) {
  const d = data && typeof data === "object" ? data : {};
  if (!d.rounds || typeof d.rounds !== "object") d.rounds = {};
  return d;
}

function roundFixtures(state, rnd) {
  const out = new Map();
  for (const f of state.fixtures || []) {
    if (String(f.round) === String(rnd) && f.id != null) out.set(String(f.id), f);
  }
  return out;
}

function validatePicks(state, rnd, picks) {
  const fixtures = roundFixtures(state, rnd);
  if (!fixtures.size) return [null, "nessuna partita per questa giornata"];
  const valid = [], seen = new Set();
  for (const p of picks || []) {
    const fid = String(p.fixture_id ?? ""), mkt = p.market, pk = p.pick;
    if (!fixtures.has(fid)) return [null, `partita non valida: ${fid}`];
    if (seen.has(fid)) return [null, "più di un esito per la stessa partita"];
    if (!VALID[mkt] || !VALID[mkt].has(pk)) return [null, "mercato o esito non valido"];
    seen.add(fid);
    const fx = fixtures.get(fid);
    valid.push({ fixture_id: fid, home: fx.home, away: fx.away, market: mkt, pick: pk, result: null, score: null });
  }
  if (!valid.length) return [null, "nessun esito scelto"];
  return [valid, null];
}

function pruneRounds(data) {
  const keys = Object.keys(data.rounds);
  if (keys.length <= MAX_ROUNDS) return false;
  let keep;
  try { keep = new Set(keys.map(Number).sort((a, b) => b - a).slice(0, MAX_ROUNDS).map(String)); } catch { return false; }
  for (const k of keys) if (!keep.has(k)) delete data.rounds[k];
  return true;
}

function evaluateCommunity(data, state) {
  const scores = new Map();
  for (const rnd of state.results || []) {
    for (const mm of rnd.matches || []) {
      if (mm.hs != null && mm.as != null && mm.id != null) scores.set(String(mm.id), [mm.hs, mm.as]);
    }
  }
  let changed = false;
  for (const block of Object.values(data.rounds || {})) {
    for (const entry of Object.values(block.entries || {})) {
      for (const p of entry.picks || []) {
        if (p.result) continue;
        const s = scores.get(String(p.fixture_id));
        if (!s) continue;
        const actual = matchOutcomes(s[0], s[1]);
        p.score = `${s[0]}-${s[1]}`;
        p.result = actual[p.market] === p.pick ? "win" : "loss";
        changed = true;
      }
    }
  }
  if (pruneRounds(data)) changed = true;
  return changed;
}

function communitySnapshot(state, data, key) {
  const rnd = currentRound(state);
  if (rnd == null) return { round: null, participants: 0, fixtures: [], aggregates: {}, my: null };
  const block = data.rounds?.[String(rnd)] || {};
  const entries = block.entries || {};
  const fixtures = [...roundFixtures(state, rnd).values()].sort((a, b) => (a.start_ts || 0) - (b.start_ts || 0));
  const agg = {};
  for (const e of Object.values(entries)) {
    for (const p of e.picks || []) {
      const m = (agg[String(p.fixture_id)] = agg[String(p.fixture_id)] || {});
      const per = (m[p.market] = m[p.market] || {});
      per[p.pick] = (per[p.pick] || 0) + 1;
    }
  }
  return {
    round: rnd,
    participants: Object.keys(entries).length,
    fixtures: fixtures.map((f) => ({ id: String(f.id), home: f.home, away: f.away, start_ts: f.start_ts })),
    aggregates: agg,
    my: key ? entries[key] || null : null,
  };
}

function communitySubmit(state, data, key, picks, rndIn) {
  const cur = currentRound(state);
  if (cur == null) return { status: "giornata non disponibile", code: 400 };
  const rnd = rndIn == null ? cur : rndIn;
  if (String(rnd) !== String(cur)) return { status: "giornata non aggiornata: ricarica e riprova", code: 400 };
  const [valid, error] = validatePicks(state, rnd, picks);
  if (error) return { status: error, code: 400 };
  const block = (data.rounds[String(rnd)] = data.rounds[String(rnd)] || {});
  if (!block.entries || typeof block.entries !== "object") block.entries = {};
  if (block.entries[key]) return { status: "already", entry: block.entries[key], code: 409 };
  const entry = { picks: valid, ts: Math.floor(Date.now() / 1000) };
  block.entries[key] = entry;
  pruneRounds(data);
  return { status: "ok", entry, code: 200 };
}

// ------------------------------------------------------------------ tracking
function trackingRecords(learning) {
  const out = [];
  const fmtScore = (v) => (v == null ? "None" : String(v));
  for (const r of learning?.records || []) {
    if (!r.evaluated) continue;
    const res = r.result || {};
    const hits = [];
    for (const b of r.bets || []) {
      hits.push({ market: b.market, pick: b.pick, odds: b.odds, prob: b.prob, hit: b.pick === res[b.market] });
    }
    for (const pi of r.picks || []) {
      hits.push({ market: pi.market, pick: pi.pick, odds: pi.odds, prob: pi.prob, hit: pi.pick === res[pi.market], model: true });
    }
    out.push({
      id: r.id, home: r.home, away: r.away, round: r.round, start_ts: r.start_ts,
      score: `${fmtScore(res.home_score)}-${fmtScore(res.away_score)}`,
      result: res["1x2"] ?? null, hits,
    });
  }
  out.sort((a, b) => (b.start_ts || 0) - (a.start_ts || 0));
  return out;
}

// ------------------------------------------------------------------ handler
export default {
  async fetch(request, env) {
    try {
      return await route(request, env);
    } catch (e) {
      return err(`worker error: ${e && e.message ? e.message : e}`, 500);
    }
  },
};

async function route(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";

  if (!env.UPSTASH_REDIS_REST_URL || !env.UPSTASH_REDIS_REST_TOKEN) {
    return err("config: UPSTASH_REDIS_REST_URL/TOKEN mancanti", 500);
  }

  if (path === "/api/health" || path === "/healthz") {
    const state = (await redisGet(env, API_TOKENS.state)) || {};
    return json({ ok: true, updated: state.updated || 0, engine: state.engine || null });
  }

  if (path === "/api/state") {
    const state = (await redisGet(env, API_TOKENS.state)) || {};
    return json(state);
  }

  if (path === "/api/results") {
    const state = (await redisGet(env, API_TOKENS.state)) || {};
    return json({ updated: state.updated || 0, results: state.results || [] });
  }

  if (path === "/api/schedina") {
    const state = (await redisGet(env, API_TOKENS.state)) || {};
    return json(schedinaPayload(state.schedina || {}));
  }

  if (path === "/api/tracking-records") {
    const learning = (await redisGet(env, API_TOKENS.learning)) || { records: [] };
    const records = trackingRecords(learning);
    const tracked = (learning.records || []).length;
    return json({ tracked, evaluated: records.length, records });
  }

  if (path === "/api/tg-info") {
    return json({ link: env.TELEGRAM_LINK || null });
  }

  if (path === "/api/tunnel") {
    return json({ available: false, running: false, url: null });
  }

  if (path === "/api/community") {
    const ip = request.headers.get("CF-Connecting-IP") || "sconosciuto";
    const key = "ip:" + ip;
    const state = (await redisGet(env, API_TOKENS.state)) || {};

    if (request.method === "GET") {
      let data = communityLoad(await redisGet(env, API_TOKENS.community));
      if (evaluateCommunity(data, state)) await redisSet(env, API_TOKENS.community, data);
      return json(communitySnapshot(state, data, key));
    }

    if (request.method === "POST") {
      let body = {};
      try { body = await request.json(); } catch { body = {}; }
      const data = communityLoad(await redisGet(env, API_TOKENS.community));
      const res = communitySubmit(state, data, key, body.picks, body.round);
      if (res.status === "ok" || res.status === "already") await redisSet(env, API_TOKENS.community, data);
      if (res.status === "ok") return json({ ok: true, entry: res.entry });
      if (res.status === "already") return json({ error: "already", entry: res.entry }, 409);
      return err(res.status, res.code || 400);
    }

    return err("metodo non supportato", 405);
  }

  // il sito statico passa dagli Assets; qui arrivano solo URL sconosciuti
  return err("endpoint inesistente", 404);
}

export { matchOutcomes, currentRound, dedupeHistory, schedinaPayload, communitySnapshot, communitySubmit, communityLoad, evaluateCommunity, trackingRecords, redisGet };
