/**
 * Serie A Stats — Cloudflare Worker (facciata read + community + bot Telegram).
 *
 * Legge lo stesso Upstash Redis del motore GitHub Actions (engine.py):
 *   seriea:state.json      -> /api/state, /api/health, /api/results, ...
 *   seriea:community.json  -> /api/community (GET/POST, stessa logica Flask)
 *   seriea:learning.json   -> /api/tracking-records
 *   seriea:tg:started      -> SADD chat id dei /start (broadcast futuri)
 *
 * Bot Telegram: POST /tg (webhook, protetta da X-Telegram-Bot-Api-Secret-Token)
 * -> bot.mjs handleUpdate: porta completa del bot Render (menu, comandi,
 * sezioni, community, donazioni, /capo), reply via Bot API.
 *
 * Il sito statico (index.html, app.js, ...) e' servito dagli Assets
 * bindings (wrangler.toml): le richieste non-statiche arrivano qui.
 *
 * NOTA: estensione .mjs (non .js) perche' il repo non ha package.json con
 * "type":"module": cosi' node puo' importare il modulo direttamente nei test.
 */

import { handleUpdate } from "./bot.mjs";

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

// (vinti, persi, pending) di una schedina community — come community.entry_counts
function entryCounts(entry) {
  const picks = (entry && entry.picks) || [];
  return [
    picks.filter((p) => p.result === "win").length,
    picks.filter((p) => p.result === "loss").length,
    picks.filter((p) => !p.result).length,
  ];
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

function communitySubmit(state, data, key, picks, rndIn, meta) {
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
  for (const [k, v] of Object.entries(meta || {})) if (v != null) entry[k] = v;
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

// ------------------------------------------------------------- telegram bot
const TG_LABELS = { "1": "1", "x": "x", "2": "2", "over_2.5": "over 2.5", "under_2.5": "under 2.5", "si": "btts si", "no": "btts no" };

function h(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function pyRaw(v) { return v == null ? "None" : String(v); }

function fmt0(x) {
  const v = Number(x) || 0;
  const f = Math.floor(v), d = v - f;
  if (d > 0.5) return String(f + 1);
  if (d < 0.5) return String(f);
  return String(f % 2 === 0 ? f : f + 1);
}

function pyNum(v) {
  if (v == null) return "None";
  if (typeof v !== "number") return String(v);
  return Number.isInteger(v) ? `${v}.0` : String(v);
}

function fmtOdds(v) {
  if (!v) return "0";
  return Number.isInteger(v) ? `${v}.0` : String(v);
}

function tgBar(p) {
  const v = (Number(p) || 0) * 10;
  const f = Math.floor(v), d = v - f;
  let full = Math.abs(d - 0.5) < 1e-9 ? (f % 2 === 0 ? f : f + 1) : Math.round(v);
  full = Math.max(0, Math.min(10, full));
  return "█".repeat(full) + "░".repeat(10 - full);
}

function utcDMHM(ts) {
  const d = new Date(Number(ts) * 1000);
  const p2 = (n) => String(n).padStart(2, "0");
  return `${p2(d.getUTCDate())}/${p2(d.getUTCMonth() + 1)} ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`;
}

function fmtClassifica(state) {
  const standings = state.standings || [];
  if (!standings.length) return "Nessun dato classifica.";
  const rows = [...standings]
    .sort((a, b) => (a.position || 99) - (b.position || 99))
    .slice(0, 20);
  const lines = ["<b>🏆 Classifica Serie A</b>", "", "<pre>"];
  for (const r of rows) {
    const pos = String(r.position || 0).padStart(2);
    const name = h(r.name || "").slice(0, 16).padEnd(16);
    const pts = String(Math.trunc(Number(r.points) || 0)).padStart(3);
    const pl = String(Math.trunc(Number(r.played) || 0)).padStart(2);
    const gf = String(Math.trunc(Number(r.gf) || 0)).padStart(3);
    const ga = String(Math.trunc(Number(r.ga) || 0)).padEnd(3);
    lines.push(`${pos}. ${name} ${pts}pt  ${pl}g  ${gf}-${ga}`);
  }
  lines.push("</pre>");
  return lines.join("\n");
}

function fmtSchedina(slip) {
  const picks = slip.picks || [];
  if (!picks.length) {
    return "Nessuna schedina ancora pronta: la creo prima della prima partita della giornata.";
  }
  const lines = [`<b>🎫 Schedina giornata ${slip.round || "?"}</b>`, ""];
  for (const p of picks) {
    const pick = TG_LABELS[p.pick || "?"] ?? (p.pick || "?");
    const odds = fmtOdds(p.odds || 0);
    const pct = (Number(p.prob) || 0) * 100;
    const score = p.score || "";
    lines.push(`<b>${h(p.home)} - ${h(p.away)}</b>`);
    if (p.result === "win") lines.push(`   ✔ ${pick} @ ${odds}  [${fmt0(pct)}%]  ${score} ✅`);
    else if (p.result === "loss") lines.push(`   ✘ ${pick} @ ${odds}  [${fmt0(pct)}%]  ${score} ❌`);
    else lines.push(`   ◻ ${pick} @ ${odds}  [${fmt0(pct)}%]  ⏳`);
  }
  let wins = 0, losses = 0;
  for (const p of picks) { if (p.result === "win") wins++; else if (p.result === "loss") losses++; }
  lines.push("");
  lines.push(`<b>Combinata: ${wins} vinti · ${losses} persi</b>`);
  const hist = slip.history || [];
  if (hist.length) {
    lines.push("");
    lines.push("<b>📚 Schedine passate:</b>");
    for (const hh of [...hist].reverse()) {
      lines.push(`Giornata ${hh.round}: ${hh.wins ?? 0} vinti · ${hh.losses ?? 0} persi`);
    }
  }
  return lines.join("\n");
}

function fmtPronostici(state) {
  const fxList = (state.fixtures || []).filter((f) => f.status !== "finished");
  fxList.sort((a, b) => (a.start_ts || 0) - (b.start_ts || 0));
  if (!fxList.length) return "Nessuna partita in calendario al momento.";
  const lines = ["<b>🎯 Pronostici</b>", ""];
  for (const fx of fxList.slice(0, 8)) {
    const p = fx.predictions || {};
    const probs = p["1x2"] || {};
    const when = fx.start_ts ? utcDMHM(fx.start_ts) : "";
    lines.push(`🕐 ${when}  <b>${h(fx.home)} - ${h(fx.away)}</b>`);
    if (Object.keys(probs).length) {
      lines.push(`   1X2  <b>${fmt0((probs["1"] || 0) * 100)}%</b> / ${fmt0((probs.x || 0) * 100)}% / ${fmt0((probs["2"] || 0) * 100)}%`);
    }
    const mp = (p.model_picks || {})["1x2"];
    if (mp) {
      const odds = mp.odds ? ` · quota ${Number(mp.odds).toFixed(2)}` : "";
      const key = String(mp.key || mp.pick || "?");
      let label = TG_LABELS[key] ?? key;
      if (["1", "x", "2"].includes(key.toLowerCase())) label = label.toUpperCase();
      const prob = Number(mp.prob) || 0;
      lines.push(`   🎯 <b>${h(label)}</b> ${tgBar(prob)} ${fmt0(prob * 100)}%${odds}`);
    }
    const es = p.exact_score || [];
    if (es.length) {
      lines.push(`   Risultato esatto: <b>${h(es[0].score)}</b> ${fmt0((Number(es[0].prob) || 0) * 100)}%`);
    }
    const best = p.best_bets || [];
    if (best.length) {
      const b = best[0];
      const edge = b.edge ? ` · +${fmt0(b.edge * 100)}%` : "";
      lines.push(`   💰 <b>${h(b.pick)}</b> @ ${pyNum(b.odds)} (${fmt0((Number(b.prob) || 0) * 100)}%)${edge}`);
    }
    lines.push("");
  }
  return lines.join("\n").replace(/\s+$/, "");
}

function fmtRisultati(state) {
  const results = state.results || [];
  if (!results.length) return "Nessun risultato disponibile.";
  const lines = ["<b>📋 Risultati Serie A</b>", ""];
  for (const rnd of results.slice(-4)) {
    lines.push(`<b>Giornata ${pyRaw(rnd.round)}</b>`);
    for (const m of rnd.matches || []) {
      lines.push(`  <b>${h(m.home)} ${h(m.score)} ${h(m.away)}</b>`);
    }
    lines.push("");
  }
  return lines.join("\n").replace(/\s+$/, "");
}

async function tgHandle(env, update) {
  // compat: i test/harness importano tgHandle da worker.mjs.
  // Il bot completo (menu, comandi, sezioni, community, /capo) vive in bot.mjs.
  return handleUpdate(update, env);
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

  if (path === "/tg") {
    if (request.method !== "POST") return err("metodo non supportato", 405);
    const sec = request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "";
    if (!env.TG_WEBHOOK_SECRET || sec !== env.TG_WEBHOOK_SECRET) return err("forbidden", 403);
    if (!env.TELEGRAM_BOT_TOKEN) return err("config: TELEGRAM_BOT_TOKEN mancante", 500);
    try {
      const update = await request.json();
      await tgHandle(env, update);
    } catch (e) {
      console.log("tg webhook error:", e && e.message ? e.message : e);
    }
    return new Response("ok");
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

export { matchOutcomes, currentRound, dedupeHistory, schedinaPayload, communitySnapshot, communitySubmit, communityLoad, evaluateCommunity, entryCounts, trackingRecords, redisGet, fmtClassifica, fmtSchedina, fmtPronostici, fmtRisultati, tgHandle, handleUpdate };
