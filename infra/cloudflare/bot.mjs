/**
 * Bot Telegram completo su Cloudflare Workers: porta fedele di
 * app/telegram.py (+ app/analysis/assistant.py, presagi di app/bot_digest.py,
 * post_morale di app/analysis/morale.py, subs/notify/donors/kv in Upstash).
 *
 * Stesso menu inline, stessi comandi, stessi testi italiani del bot Render.
 * Stato in Upstash Redis (seriea:<name>, stessi nomi del kv Python):
 *   state.json, follows.json, started.json, subs.json, donors.json,
 *   tg_users.json, coaches.json, community.json,
 *   tg:cm_draft:<chat_id> (bozze community, erano in memoria su Render).
 *
 * Export principale: handleUpdate(update, env) — non lancia mai eccezioni.
 */
import { T, DONATION_OPTIONS } from "./tg_strings.js";
import {
  communityLoad, communitySnapshot, communitySubmit, entryCounts,
} from "./worker.mjs";

export { T, DONATION_OPTIONS };

const MAX_MSG = 4096;
const DEFAULT_PUBLIC_URL = "https://seriea-stats.lucaziello8.workers.dev";
const DEFAULT_OWNER_IDS = [1694501243];
const UPDATE_INTERVAL_MIN = 10;
const NEW_MANAGER_WINDOW_DAYS = 30;
const NEW_MANAGER_ENABLED = true;
const LIFETIME_TS = 4102444800;
const PRESAGI_MIN_P = 0.6;
const PRESAGI_MAX_ROWS = 7;

const INTENTS = { pronostici: "pronostici" };
const MARKET_KEY = { "1x2": "market_1x2", over_under: "market_over_under", btts: "market_btts" };
const PICK_LABELS = {
  "1": "1", "x": "x", "2": "2",
  "over_2.5": "over 2.5", "under_2.5": "under 2.5",
  "si": "btts si", "no": "btts no",
};
const CM_OPTS = [
  ["1x2", [["1", "1"], ["x", "X"], ["2", "2"]]],
  ["over_under", [["over_2.5", "Over"], ["under_2.5", "Under"]]],
  ["btts", [["si", "Sì"], ["no", "No"]]],
];
const CM_VALID = {
  "1x2": new Set(["1", "x", "2"]),
  over_under: new Set(["over_2.5", "under_2.5"]),
  btts: new Set(["si", "no"]),
};
const MESES = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const GIORNI_ROME = { Mon: "lun", Tue: "mar", Wed: "mer", Thu: "gio", Fri: "ven", Sat: "sab", Sun: "dom" };
const DOW_EN = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// ------------------------------------------------------------------ utils
export function h(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function norm(s) {
  return String(s ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\x00-\x7F]/g, "")
    .toLowerCase();
}

export function fmt0(x) {
  const v = Number(x) || 0;
  const f = Math.floor(v), d = v - f;
  if (d > 0.5) return String(f + 1);
  if (d < 0.5) return String(f);
  return String(f % 2 === 0 ? f : f + 1);
}

export function fmtFixed(v, digits) {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(n);
  if (digits === 0) return fmt0(n);
  const neg = n < 0;
  const a = Math.abs(n);
  const s = a.toFixed(Math.min(100, digits + 25));
  const dot = s.indexOf(".");
  let head = s.slice(dot + 1, dot + 1 + digits);
  const rest = s.slice(dot + 1 + digits);
  const first = rest.charCodeAt(0) - 48;
  let up = first > 5 || (first === 5 && /[1-9]/.test(rest.slice(1)));
  if (first === 5 && !/[1-9]/.test(rest.slice(1))) {
    up = (head.charCodeAt(head.length - 1) - 48) % 2 === 1;
  }
  let intp = Number(s.slice(0, dot));
  if (up) {
    const arr = head.split("");
    let i = arr.length - 1;
    while (i >= 0) {
      if (arr[i] === "9") { arr[i] = "0"; i--; } else { arr[i] = String(Number(arr[i]) + 1); break; }
    }
    if (i < 0) { intp += 1; head = "0".repeat(digits); } else head = arr.join("");
  }
  return `${neg ? "-" : ""}${intp}.${head}`;
}

export function fmtOdds(v) {
  if (!v) return "0";
  return Number.isInteger(v) ? `${v}.0` : String(v);
}

export function pyNum(v) {
  if (v == null) return "None";
  if (typeof v !== "number") return String(v);
  return Number.isInteger(v) ? `${v}.0` : String(v);
}

export function pyDisp(v, dflt) {
  if (v === undefined) return dflt;
  if (v === null) return "None";
  return String(v);
}

export function pyGet(obj, key, dflt) {
  return obj && Object.prototype.hasOwnProperty.call(obj, key) ? obj[key] : dflt;
}

export function t(key, params) {
  const text = Object.prototype.hasOwnProperty.call(T, key) ? T[key] : key;
  if (!params) return text;
  let missing = false;
  const out = text.replace(/\{(\w+)(?::([+]?)[0-9]*(?:\.([0-9]+))?f)?\}/g, (m, name, sign, dec) => {
    if (!Object.prototype.hasOwnProperty.call(params, name)) { missing = true; return m; }
    const v = params[name];
    if (dec === undefined) return v === null || v === undefined ? "None" : String(v);
    const num = Number(v);
    if (Number.isNaN(num)) { missing = true; return m; }
    let s = fmtFixed(num, Number(dec));
    if (sign === "+" && num >= 0 && !s.startsWith("-")) s = `+${s}`;
    return s;
  });
  return missing ? text : out;
}

export function bar(p) {
  const clamped = Math.max(0, Math.min(1, Number(p) || 0));
  const full = Math.max(0, Math.min(10, fmt0(clamped * 10)));
  return "█".repeat(full) + "░".repeat(10 - full);
}

export function splitLong(text) {
  if (text.length <= MAX_MSG) return [text];
  const out = [];
  let rest = text;
  while (rest.length > MAX_MSG) {
    let cut = rest.lastIndexOf("\n", MAX_MSG - 1);
    if (cut <= 0) cut = MAX_MSG;
    out.push(rest.slice(0, cut));
    rest = rest.slice(cut).replace(/^\n+/, "");
  }
  if (rest) out.push(rest);
  return out;
}

export function utcDMHM(ts) {
  const d = new Date(Number(ts) * 1000);
  const p2 = (n) => String(n).padStart(2, "0");
  return `${p2(d.getUTCDate())}/${p2(d.getUTCMonth() + 1)} ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`;
}

function utcDMY(ts) {
  const d = new Date(Number(ts) * 1000);
  const p2 = (n) => String(n).padStart(2, "0");
  return `${p2(d.getUTCDate())}/${p2(d.getUTCMonth() + 1)}/${d.getUTCFullYear()}`;
}

function utcDowDMHM(ts) {
  const d = new Date(Number(ts) * 1000);
  const p2 = (n) => String(n).padStart(2, "0");
  return `${DOW_EN[d.getUTCDay()]} ${p2(d.getUTCDate())}/${p2(d.getUTCMonth() + 1)} ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`;
}

function romeWhen(ts) {
  const d = new Date(Number(ts) * 1000);
  const parts = {};
  for (const p of new Intl.DateTimeFormat("en-US", {
    timeZone: "Europe/Rome", weekday: "short", day: "2-digit",
    month: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(d)) parts[p.type] = p.value;
  return `${GIORNI_ROME[parts.weekday] || parts.weekday} ${parts.day}/${MESES[Number(parts.month) - 1]} · ${parts.hour}:${parts.minute}`;
}

export function marketLabel(market, key) {
  const k = typeof key === "string" ? key : String(key ?? "");
  return PICK_LABELS[k] ?? k;
}

function marketLabelT(market) {
  const key = MARKET_KEY[market];
  return key ? t(key) : market;
}

function isObj(x) { return x && typeof x === "object" && !Array.isArray(x); }
function nonEmpty(x) { return isObj(x) && Object.keys(x).length > 0; }
function parseIds(v) {
  return String(v || "").split(",").map((s) => s.trim()).filter((s) => /^\d+$/.test(s)).map(Number);
}

// --------------------------------------------------------------- testi dati
export function classificaText(standings) {
  if (!standings || !standings.length) return t("classifica_nodata");
  const rows = [...standings].sort((a, b) => ((a.position || 99) - (b.position || 99))).slice(0, 20);
  const lines = [t("classifica_title"), "", "<pre>"];
  for (const r of rows) {
    const pos = r.position || 0;
    const name = h(String(r.name || "")).slice(0, 16);
    const pts = String(Math.trunc(Number(r.points) || 0)).padStart(3);
    const pl = String(Math.trunc(Number(r.played) || 0)).padStart(2);
    const gf = String(Math.trunc(Number(r.gf) || 0)).padStart(3);
    const ga = String(Math.trunc(Number(r.ga) || 0)).padEnd(3);
    lines.push(`${String(pos).padStart(2)}. ${name.padEnd(16)} ${pts}pt  ${pl}g  ${gf}-${ga}`);
  }
  lines.push("</pre>");
  return lines.join("\n");
}

export function giornataText(fixtures) {
  if (!fixtures || !fixtures.length) return t("partite_nodata");
  const lines = [t("partite_title", { r: fixtures[0].round }), ""];
  for (const fx of fixtures.slice(0, 10)) {
    const p = fx.predictions || {};
    const probs = p["1x2"] || {};
    const when = fx.start_ts ? utcDMHM(fx.start_ts) : "";
    lines.push(`🕐 ${when}  <b>${h(fx.home)} - ${h(fx.away)}</b>`);
    if (Object.keys(probs).length) {
      lines.push(`   1X2  <b>${fmt0((probs["1"] || 0) * 100)}%</b> / ${fmt0((probs.x || 0) * 100)}% / ${fmt0((probs["2"] || 0) * 100)}%`);
    }
    const mp = (p.model_picks || {})["1x2"];
    if (nonEmpty(mp)) {
      const odds = mp.odds ? ` · quota ${fmtFixed(mp.odds, 2)}` : "";
      const key = String(mp.key || mp.pick || "?");
      let label = marketLabel("1x2", key);
      if (["1", "x", "2"].includes(key.toLowerCase())) label = label.toUpperCase();
      lines.push(`   🎯 <b>${h(label)}</b> ${bar(mp.prob || 0)} ${fmt0((mp.prob || 0) * 100)}%${odds}`);
    }
    const es = p.exact_score || [];
    if (es.length) {
      lines.push("   " + t("pronostico_exact", { score: es[0].score, pct: (Number(es[0].prob) || 0) * 100 }));
    }
    const tp = p.tipster_mix;
    if (nonEmpty(tp)) {
      const rate = tp.rate != null ? `${fmt0(tp.rate * 100)}%` : "n/d";
      lines.push("   " + h(t("pronostico_tipster", {
        src: tp.source || "?", rate, o: tp.outcome || "?", g: tp.goals || "?", s: tp.score || "?",
      })));
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

export function postMorale(homeScore, awayScore, sideHome = true) {
  const mine = sideHome ? homeScore : awayScore;
  const theirs = sideHome ? awayScore : homeScore;
  let delta = mine > theirs ? 2 : mine === theirs ? 0 : -2;
  const diff = mine - theirs;
  if (diff >= 3) delta += 1;
  else if (diff <= -3) delta -= 1;
  if (mine >= 3) delta += 0.5;
  if (theirs === 0) delta += 0.5;
  delta = Math.min(3, Math.max(-3, delta));
  delta = Number(delta.toFixed(1));
  let desc;
  if (delta >= 2) desc = "vola: vittoria convincente";
  else if (delta > 0) desc = "su, fiducia ritrovata";
  else if (delta === 0) desc = "stabile";
  else if (delta > -2) desc = "giù, fallimento";
  else desc = "crisi: sconfitta pesante";
  return [delta, desc];
}

export function risultatiText(results) {
  if (!results || !results.length) return t("risultati_nodata");
  const lines = [t("risultati_title"), ""];
  for (const rnd of results) {
    lines.push(t("giornata", { r: rnd.round }));
    for (const m of rnd.matches || []) {
      let base = `  <b>${h(m.home)} ${h(m.score)} ${h(m.away)}</b>`;
      const sc = String(m.score ?? "").split("-");
      if (sc.length === 2) {
        const hh = Number(sc[0].trim()), aa = Number(sc[1].trim());
        if (!Number.isNaN(hh) && !Number.isNaN(aa)) {
          const d1 = postMorale(hh, aa, true)[1];
          const d2 = postMorale(hh, aa, false)[1];
          base += `\n      ${h(m.home)}: ${d1} · ${h(m.away)}: ${d2}`;
        }
      }
      lines.push(base);
    }
    lines.push("");
  }
  return lines.join("\n").replace(/\s+$/, "");
}

export function liveText(live) {
  const matches = (live && live.matches) || [];
  if (!matches.length) return t("live_nodata");
  const lines = [t("live_title"), "", "<pre>"];
  for (const m of matches) {
    const minute = m.minute != null ? ` · ${m.minute}'` : "";
    const home = h(String(m.home || "")).slice(0, 18);
    lines.push(`${home.padEnd(18)} ${pyDisp(m.hs, "-")}-${pyDisp(m.as, "-")}  ${h(m.away)}${minute}`);
  }
  lines.push("</pre>");
  return lines.join("\n");
}

export function moraleText(fixtures) {
  if (!fixtures || !fixtures.length) return t("morale_nodata");
  const lines = [t("morale_title", { r: fixtures[0].round }), ""];
  for (const fx of fixtures.slice(0, 12)) {
    const mo = fx.morale || {};
    const hm = mo.home || {}, am = mo.away || {};
    if (!nonEmpty(hm) && !nonEmpty(am)) continue;
    lines.push(`<b>${h(fx.home)} - ${h(fx.away)}</b>`);
    for (const [name, m] of [[fx.home, hm], [fx.away, am]]) {
      const notes = (m.notes || []).slice(0, 1);
      const quote = notes.length ? "   💬 " + h(notes[0].title) : "";
      const inj = m.injuries ? ` · assenti ${m.injuries}` : "";
      const label = m.label === undefined ? "?" : m.label;
      lines.push(`  ${h(name)}: <b>${h(label)}</b> ${pyDisp(m.score, "?")}/10${h(inj)}`);
      if (m.coach_note) lines.push("   🔁 " + h(m.coach_note));
      if (quote) lines.push(quote);
    }
    lines.push("");
  }
  return lines.join("\n").replace(/\s+$/, "") || t("morale_nodata");
}

export function trackingText(tracking) {
  if (!nonEmpty(tracking)) return t("tracking_empty");
  const lines = [t("tracking_title"), ""];
  if (tracking.bets_total) {
    const rate = tracking.bets_rate;
    lines.push(t("tracking_evaluated", { n: tracking.evaluated }));
    lines.push(t("tracking_hit", { hit: tracking.bets_hit, tot: tracking.bets_total, pct: rate * 100 }));
    if (tracking.match_bets_total) {
      lines.push(t("tracking_match_hit", {
        hit: tracking.match_bets_hit, tot: tracking.match_bets_total, pct: tracking.match_bets_rate * 100,
      }));
    }
    const bym = tracking.by_market || {};
    for (const m of Object.keys(bym).sort()) {
      const st = bym[m];
      if (st.bets_total) {
        lines.push(`· Best-bet ${marketLabelT(m)}: ${st.bets_hit}/${st.bets_total} (${fmt0(st.bets_rate * 100)}%)`);
      }
    }
    if (tracking.picks_total) {
      lines.push(`· Pronostici modello (1X2/Over/BTTS): ${tracking.picks_hit}/${tracking.picks_total} (${fmt0(tracking.picks_rate * 100)}%)`);
    }
  }
  if (tracking.brier != null) lines.push(t("tracking_brier", { b: tracking.brier }));
  if (tracking.rps != null) lines.push(t("tracking_rps", { r: tracking.rps }));
  const oos = tracking.oos || {};
  const pod = (oos.check || {}).picks || {};
  if (oos.brier_calibrated != null && oos.brier != null && (oos.records || 0) >= 2) {
    lines.push(t("tracking_oos", { b: oos.brier, bc: oos.brier_calibrated, imp: oos.improvement || 0.0 }));
    if (oos.rps != null) lines.push(t("tracking_oos_rps", { r: oos.rps, rc: oos.rps_calibrated || oos.rps }));
    const ci = oos.ci95;
    if (ci) {
      const sig = oos.significant ? "✅" : "≈";
      lines.push(t("tracking_oos_ci", {
        imp: oos.improvement || 0.0, lo: ci.lo, hi: ci.hi, p: ci.p_better, sig,
      }));
    }
    if (pod.total) lines.push(t("tracking_oos_picks", { hit: pod.hit, tot: pod.total, pct: pod.rate * 100 }));
  }
  lines.push("");
  const lessons = tracking.conclusions || [];
  if (lessons.length) {
    lines.push(t("tracking_learned"));
    for (const l of lessons.slice(0, 6)) lines.push(h(l));
  }
  return lines.join("\n");
}

export function pronosticiNote(tracking) {
  const total = tracking && tracking.bets_total;
  if (!total) return null;
  return t("pronostici_note", { hit: tracking.bets_hit, tot: total, rate: tracking.bets_rate * 100 });
}

export function schedinaText(slip) {
  if (!slip || !(slip.picks || []).length) return t("schedina_nodata");
  const lines = [t("schedina_title", { r: pyDisp(slip.round, "?") }), ""];
  for (const p of slip.picks || []) {
    const pick = marketLabel(p.market || "1x2", p.pick || "?");
    const odds = fmtOdds(p.odds || 0);
    const pct = (Number(p.prob) || 0) * 100;
    const score = p.score || "";
    lines.push(t("schedina_match", { home: h(p.home), away: h(p.away) }));
    if (p.result === "win") lines.push("   " + t("schedina_win", { pick, odds, pct, score }));
    else if (p.result === "loss") lines.push("   " + t("schedina_loss", { pick, odds, pct, score }));
    else lines.push("   " + t("schedina_pending", { pick, odds, pct }));
  }
  let wins = 0, losses = 0;
  for (const p of slip.picks) { if (p.result === "win") wins++; else if (p.result === "loss") losses++; }
  lines.push("");
  lines.push(t("schedina_counter", { wins, losses }));
  const hist = slip.history || [];
  if (hist.length) {
    lines.push("");
    lines.push(t("schedina_history_title"));
    for (const hh of [...hist].reverse()) {
      lines.push(t("schedina_history_row", {
        r: hh.round, wins: pyGet(hh, "wins", 0), losses: pyGet(hh, "losses", 0),
      }));
    }
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------- presagi
function upcoming(store, withinDays = 14) {
  const now = Date.now() / 1000;
  const out = [];
  for (const f of store.fixtures || []) {
    const ts = f.start_ts || 0;
    if (f.status === "finished" || !ts) continue;
    if (ts >= now - 3 * 3600 && ts <= now + withinDays * 86400) out.push(f);
  }
  return out.sort((a, b) => ((a.start_ts || 0) - (b.start_ts || 0)));
}

function pickOf(fx) {
  const preds = fx.predictions || {};
  const bb = preds.best_bets;
  const best = Array.isArray(bb) && bb.length ? bb[0] : {};
  let label, prob, odds, fair, edge;
  if (best.pick) {
    const market = best.market || "1x2";
    label = marketLabel(market, best.pick);
    if (market === "1x2") label = label.toUpperCase();
    prob = Number(best.prob) || 0;
    odds = best.odds; fair = best.fair;
    edge = best.edge;
    if (edge == null && odds && fair) edge = (odds / fair) - 1;
  } else {
    const mp = (preds.model_picks || {})["1x2"] || {};
    if (!mp.pick) return null;
    const key = mp.key || mp.pick;
    label = ["1", "x", "2"].includes(String(key).toLowerCase())
      ? marketLabel("1x2", key).toUpperCase() : marketLabel("1x2", key);
    prob = Number(mp.prob) || 0;
    odds = mp.odds; fair = mp.fair; edge = null;
    if (odds && fair) edge = (odds / fair) - 1;
  }
  return (`   🎯 <b>${h(label)}</b> ${bar(prob)} ${fmt0(prob * 100)}%`
    + `  · quota ${odds ? fmtOdds(odds) : "n/d"}`
    + (fair ? `  · fair ${fmtFixed(fair, 2)}` : "")
    + (edge ? `  · <b>+${fmt0(edge * 100)}%</b>` : ""));
}

export function presagiText(store) {
  const now = Date.now() / 1000;
  const rows = [];
  for (const fx of upcoming(store)) {
    if ((fx.start_ts || 0) <= now) continue;
    const preds = fx.predictions || {};
    const cands = [];
    for (const b of preds.best_bets || []) if (b.pick && b.prob) cands.push(b);
    if (!cands.length) {
      for (const key of ["1x2", "over_under", "btts"]) {
        const mp = (preds.model_picks || {})[key] || {};
        if (mp.pick && (Number(mp.prob) || 0) >= PRESAGI_MIN_P) { cands.push(mp); break; }
      }
    }
    if (cands.length) {
      let top = cands[0];
      for (const b of cands) if ((Number(b.prob) || 0) > (Number(top.prob) || 0)) top = b;
      rows.push([Number(top.prob) || 0, fx]);
    }
  }
  rows.sort((a, b) => b[0] - a[0]);
  const lines = [t("presagi_title")];
  if (!rows.length) {
    lines.push(t("presagi_empty"));
    return lines.join("\n");
  }
  for (const [, fx] of rows.slice(0, PRESAGI_MAX_ROWS)) {
    const when = romeWhen(fx.start_ts || 0);
    lines.push(`🎯 <b>${h(fx.home)} - ${h(fx.away)}</b>  ·  ${when}`);
    const row = pickOf(fx);
    if (row) lines.push(row);
    lines.push("");
  }
  const tracking = store.tracking || {};
  if (tracking.bets_total) {
    lines.push(t("pronostici_note", {
      hit: tracking.bets_hit, tot: tracking.bets_total, rate: tracking.bets_rate * 100,
    }));
  }
  lines.push("");
  lines.push(t("disclaimer"));
  return lines.join("\n");
}

// --------------------------------------------------------------- assistant
function battutaMister(team, noteTitle) {
  if (!noteTitle) return null;
  const tl = noteTitle.toLowerCase();
  if (tl.includes("esonero") || tl.includes("addio")) return `Su ${team} gira voce di esonero... al bar dicono 'ogni cambio panchina è una scossa, vediamo se la scossa arriva!'`;
  if (tl.includes("vittoria") || tl.includes("vince") || tl.includes("tre punti")) return `Il mister di ${team} è carico... al bar dicono 'quando vinci, pure il caffè è più buono!'`;
  if (tl.includes("sconfitta") || tl.includes("ko") || tl.includes("perde")) return `${team} viene da un ko... al bar c'è chi dice 'dopo la pioggia, prima o poi esce il sole... o l'ombrello!'`;
  if (tl.includes("infortun") || tl.includes("assenz")) return `${team} con qualche cerotto... come dice il vecchio al bar: 'gioca chi c'è, non chi manca!'`;
  if (tl.includes("conferenza") || tl.includes("parla") || tl.includes("dice")) return `Il mister di ${team} ha parlato in conferenza... al bar traduciamo: 'tante parole, poi parla il campo!'`;
  return `Ultime dal quartier ${team}: '${noteTitle.slice(0, 60)}...' - al bar dicono 'staremo a vedere, il campo è giudice!'`;
}

function partitaLines(fixture) {
  const p = fixture.predictions || {};
  const home = fixture.home, away = fixture.away;
  const lines = [];
  lines.push(`Ah, ${home} - ${away} di giornata ${fixture.round ?? "?"}... bella partita, te lo dico io come la vedo.`);
  if (p["1x2"]) {
    const prob = p["1x2"];
    let top = null;
    for (const k of Object.keys(prob)) if (top === null || prob[k] > prob[top]) top = k;
    const top_pct = (Number(prob[top]) || 0) * 100;
    const label = { "1": home, "x": "pareggio", "2": away }[top];
    lines.push(`Secondo me qui ${label} è favorito al ${fmt0(top_pct)}% (1: ${fmt0((prob["1"] || 0) * 100)}% · X: ${fmt0((prob.x || 0) * 100)}% · 2: ${fmt0((prob["2"] || 0) * 100)}%).`);
    if (p.lambdas) {
      const lh = p.lambdas.home_goals, la = p.lambdas.away_goals;
      if (lh != null && la != null) {
        lines.push(`Mi aspetto più o meno ${fmtFixed(lh, 2)} gol per ${home} e ${fmtFixed(la, 2)} per ${away}... partita che si sblocca, non 0-0 da sbadiglio.`);
      }
    }
    if (p.exact_score && p.exact_score.length) {
      const es = p.exact_score[0];
      lines.push(`Se devo sparare un risultato, ti dico ${es.score} al ${fmt0((Number(es.prob) || 0) * 100)}%... da bar, eh, prendilo con le pinze.`);
    }
  }
  for (const b of (p.best_bets || []).slice(0, 1)) {
    lines.push(`E se proprio vuoi puntarci due spicci, il modello mi dice '${b.pick}' a ${pyNum(b.odds)} (prob ${fmt0((Number(b.prob) || 0) * 100)}%)... ma gioca leggero, che il pallone è strano.`);
  }
  if (p.motivation) {
    const mot = String(p.motivation);
    const parts = mot.split(". ");
    let short = parts.slice(0, 2).join(". ");
    if (short && !short.endsWith(".")) short += ".";
    lines.push(`Ti spiego perché: ${short} Insomma, al bar diremmo che chi sta meglio ora ha quel pizzico in più.`);
  } else {
    lines.push("Non ho ancora abbastanza dati per darti il perché preciso... ripassa più vicino al fischio.");
  }
  try {
    const morale = fixture.morale || {};
    for (const [side, team] of [["home", home], ["away", away]]) {
      const m = morale[side] || {};
      const notes = m.notes || [];
      if (notes.length) {
        const batt = battutaMister(team, notes[0].title || "");
        if (batt) { lines.push(batt); break; }
      }
    }
    const coach = fixture.coach || {};
    for (const [side, team] of [["home", home], ["away", away]]) {
      const c = coach[side] || {};
      if (c.is_new) {
        const mgr = c.manager || "nuovo mister";
        lines.push(`Occhio al nuovo ${mgr} sulla panchina di ${team}... nuova scopa scopa bene, dicono al bar!`);
        break;
      }
    }
  } catch {
    // come il bare except di _partita
  }
  return lines;
}

function assistantPronostici(fixtures, limit = 5) {
  const bets = [];
  for (const fx of fixtures || []) {
    for (const b of ((fx.predictions || {}).best_bets || []).slice(0, 2)) {
      bets.push({ match: `${fx.home} - ${fx.away}`, ...b });
    }
  }
  bets.sort((a, b) => ((Number(b.edge) || 0) - (Number(a.edge) || 0)));
  const items = [];
  for (const b of bets.slice(0, limit)) {
    items.push({
      title: `${b.match} → ${String(b.pick).toUpperCase()} @ ${pyNum(b.odds)}`,
      text: `Probabilità modello ${fmt0((Number(b.prob) || 0) * 100)}% (fair quota ${pyNum(b.fair)}), valore +${fmt0((Number(b.edge) || 0) * 100)}%`,
      tag: "value",
    });
  }
  if (!items.length) {
    items.push({ title: "Nessun pronostico", text: "Nessun valore rilevato.", tag: "info" });
  }
  return items;
}

function assistantErrori(fixtures, limit = 8) {
  const flags = [];
  for (const fx of fixtures || []) {
    for (const f of fx.value_flags || []) if (f.kind === "spread" || f.kind === "arb") flags.push(f);
  }
  return flags.slice(0, limit).map((f) => ({
    title: (f.fixture || "") + " · " + pyDisp(f.pick, ""),
    text: f.message || "",
    tag: f.severity === "alert" ? "alert" : "warn",
  }));
}

export function assistantAnswer(rawQuestion, fixtures) {
  const q = norm(rawQuestion);
  let items = [];
  let target = null;
  for (const fx of fixtures || []) {
    const hn = norm(fx.home), an = norm(fx.away);
    if ((hn && q.includes(hn)) || (an && q.includes(an))) { target = fx; break; }
    if (hn && an && q.includes(hn) && q.includes(an)) { target = fx; break; }
  }
  const KW = ["spiega", "perche", "motivo", "analizza", "pronostic", "quote", "probabilita", "gol attesi", "xg"];
  if (target && KW.some((k) => q.includes(k))) {
    return {
      intent: "partita",
      intro: `Oh, ${target.home} - ${target.away}? Siediti, te la racconto come al bar:`,
      lines: partitaLines(target),
      items: [],
    };
  }
  let intro, intent;
  if (["errore", "arbitrag", "disalline", "quota", "bookmaker"].some((k) => q.includes(k))) {
    items = assistantErrori(fixtures);
    intro = "Errori di quota (disallineamenti tra bookmaker) rilevati nell'ultimo refresh:";
    intent = "errori";
  } else if (["pronostic", "consigli", "suggerisci", "miglior", "punta", "value", "scelta", "giornata"].some((k) => q.includes(k))) {
    items = assistantPronostici(fixtures);
    intro = "I pronostici con valore migliore secondo il modello:";
    intent = "pronostici";
  } else {
    if (target) {
      return {
        intent: "partita",
        intro: `Ah, ${target.home} - ${target.away}? Te la leggo come la vedo io al bar:`,
        lines: partitaLines(target),
        items: [],
      };
    }
    items = assistantPronostici(fixtures).concat(assistantErrori(fixtures, 3));
    intro = ("Prova a chiedermi qualcosa come: \"pronostici della giornata\", "
      + "\"ci sono errori di quota?\" o nomina due squadre (es. \"analizza Juventus - Milan\"). Intanto: ");
    intent = "overview";
  }
  return { intent, intro, lines: [], items };
}

function cleanStr(s) {
  let x = String(s).replace(/⚠/g, "").replace(/\*\*/g, "");
  x = x.split("\n").filter((l) => l.trim()).join("\n");
  return x.trim();
}

export function renderAssistant(result) {
  const parts = [];
  const intro = String(result.intro || "");
  if (intro) parts.push(h(cleanStr(intro)));
  for (const l of result.lines || []) if (String(l).trim()) parts.push(h(cleanStr(String(l))));
  for (const it of result.items || []) {
    const title = h(cleanStr(String(it.title || "")));
    const text = h(cleanStr(String(it.text || "")));
    parts.push(text ? `• ${title}\n  ${text}` : `• ${title}`);
  }
  return parts.join("\n\n").trim() || "Nessun dato disponibile.";
}

// ---------------------------------------------------------------- tastiere
export function kb(rows) {
  const btn = ([txt, d]) => (String(d).startsWith("http") ? { text: txt, url: d } : { text: txt, callback_data: d });
  return { inline_keyboard: rows.map((row) => row.map(btn)) };
}

export function menuKb(section = null, publicUrl = DEFAULT_PUBLIC_URL) {
  const rows = [
    [[t("menu_classifica"), "p:classifica"], [t("menu_partite"), "p:partite"]],
    [[t("menu_risultati"), "p:risultati"], [t("menu_live"), "p:live"]],
    [[t("menu_presagi"), "p:presagi"], [t("menu_pronostici"), "p:pronostici"]],
    [[t("menu_schedina"), "p:schedina"], [t("menu_tracking"), "p:tracking"]],
    [[t("menu_morale"), "p:morale"], [t("menu_community"), "p:community"]],
    [[t("menu_segui"), "flw"], [t("menu_stopsegui"), "unf"]],
  ];
  if (section) {
    rows.push([[t("section_refresh"), `p:${section}`], [t("menu_menu"), "m"]]);
    return kb(rows);
  }
  const url = publicUrl || DEFAULT_PUBLIC_URL;
  if (url) rows.push([[t("menu_sito"), url]]);
  rows.push([[t("menu_donazioni"), "don"]]);
  return kb(rows);
}

export function donKb() {
  const buttons = [];
  for (let i = 0; i < DONATION_OPTIONS.length; i += 3) {
    buttons.push(DONATION_OPTIONS.slice(i, i + 3).map((s) => [`⭐ ${s}`, `don:${s}`]));
  }
  buttons.push([[t("menu_menu"), "m"]]);
  return kb(buttons);
}

export function menuText() {
  return `${t("menu_title")}\n\n${t("disclaimer")}`;
}

function parseTeams(store) {
  const out = {};
  const names = new Set();
  for (const r of store.standings || []) names.add(r.name);
  for (const rnd of store.results || []) for (const m of rnd.matches || []) { names.add(m.home); names.add(m.away); }
  for (const f of store.fixtures || []) { names.add(f.home); names.add(f.away); }
  for (const n of names) if (n) out[norm(n)] = n;
  return out;
}

export function teamsKb(store, prefix, teams = null) {
  let names = teams;
  if (names == null) {
    names = [...new Set((store.standings || []).map((r) => r.name).filter(Boolean))].sort();
  }
  const rows = [];
  for (let i = 0; i < names.length; i += 2) {
    rows.push(names.slice(i, i + 2).map((n) => [n, `${prefix}:${n}`]));
  }
  if (prefix === "unf") rows.push([[t("all"), "unf:all"]]);
  rows.push([[t("back"), "m"]]);
  return kb(rows);
}

// ------------------------------------------------------------------- redis
export async function redisGet(env, key) {
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

export async function redisSet(env, key, value) {
  const res = await fetch(env.UPSTASH_REDIS_REST_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.UPSTASH_REDIS_REST_TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(["SET", key, JSON.stringify(value)]),
  });
  if (!res.ok) throw new Error(`upstash SET ${key}: HTTP ${res.status}`);
}

async function redisSAdd(env, key, member) {
  const res = await fetch(env.UPSTASH_REDIS_REST_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.UPSTASH_REDIS_REST_TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(["SADD", key, member]),
  });
  if (!res.ok) throw new Error(`upstash SADD ${key}: HTTP ${res.status}`);
}

// -------------------------------------------------------------------- bot
export class Bot {
  constructor(env) {
    this.env = env;
    this.token = env.TELEGRAM_BOT_TOKEN;
    this.allowed = parseIds(env.TELEGRAM_ALLOWED_IDS);
    this.owners = parseIds(env.TELEGRAM_OWNER_IDS);
    if (!this.owners.length) this.owners = [...DEFAULT_OWNER_IDS];
    this.lastErr = "";
    this._state = null;
  }

  // ------------------------------------------------------------- api
  async call(method, payload) {
    this.lastErr = "";
    try {
      const res = await fetch(`https://api.telegram.org/bot${this.token}/${method}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!data.ok) {
        this.lastErr = String(data.description || "");
        console.warn(`Telegram ${method}: ${this.lastErr}`);
        return null;
      }
      return data.result;
    } catch (e) {
      this.lastErr = String((e && e.message) || e);
      console.warn(`Telegram ${method}: ${this.lastErr}`);
      return null;
    }
  }

  async send(chatId, text, replyMarkup) {
    const chunks = splitLong(text);
    for (let i = 0; i < chunks.length; i++) {
      const payload = {
        chat_id: chatId, text: chunks[i], parse_mode: "HTML", disable_web_page_preview: true,
      };
      if (i === 0 && replyMarkup !== undefined) payload.reply_markup = replyMarkup;
      let res = await this.call("sendMessage", payload);
      if (res === null && (this.lastErr || "").includes("parse")) {
        delete payload.parse_mode;
        res = await this.call("sendMessage", payload);
      }
      if (res === null) return false;
    }
    return true;
  }

  async sendMenu(chatId, text) {
    const body = text || menuText();
    await this.send(chatId, body, menuKb(null, this.env.PUBLIC_URL));
  }

  async edit(chatId, messageId, text, replyMarkup) {
    const payload = { chat_id: chatId, message_id: messageId, text, parse_mode: "HTML" };
    if (replyMarkup !== undefined) payload.reply_markup = replyMarkup;
    let res = await this.call("editMessageText", payload);
    if (res === null) {
      const err = this.lastErr || "";
      if (err.includes("not modified")) return true;
      if (err.includes("parse")) {
        delete payload.parse_mode;
        res = await this.call("editMessageText", payload);
      }
    }
    return res;
  }

  async editOrSend(chatId, messageId, text, replyMarkup) {
    if (messageId && await this.edit(chatId, messageId, text, replyMarkup)) return;
    await this.send(chatId, text, replyMarkup);
  }

  async answerCb(callbackId, toast) {
    const payload = { callback_query_id: callbackId };
    if (toast) payload.text = toast;
    await this.call("answerCallbackQuery", payload);
  }

  // -------------------------------------------------------------- kv
  async kvGet(name) {
    try { return await redisGet(this.env, `seriea:${name}`); } catch (e) { console.warn("kv get", name, e); return null; }
  }

  async kvSet(name, value) {
    try { await redisSet(this.env, `seriea:${name}`, value); } catch (e) { console.warn("kv set", name, e); }
  }

  async state() {
    if (this._state == null) {
      try { this._state = (await redisGet(this.env, "seriea:state.json")) || {}; } catch (e) { console.warn("state read", e); this._state = {}; }
    }
    return this._state;
  }

  // -------------------------------------------------------- autorizza
  authorized(chatId) {
    if (!this.allowed.length) return true;
    return this.allowed.includes(chatId);
  }

  isCapo(chatId) {
    return this.owners.includes(chatId);
  }

  // ----------------------------------------------------------- sezioni
  async sectionText(section) {
    const store = await this.state();
    if (section === "classifica") return classificaText(store.standings || []);
    if (section === "partite") return giornataText(store.fixtures || []);
    if (section === "risultati") return risultatiText(store.results || []);
    if (section === "live") return liveText(store.live || {});
    if (section === "morale") return moraleText(store.fixtures || []);
    if (section === "tracking") return trackingText(store.tracking || {});
    if (section === "schedina") return schedinaText(store.schedina || {});
    if (section === "presagi") return presagiText(store);
    if (section in INTENTS) return renderAssistant(assistantAnswer(INTENTS[section], store.fixtures || []));
    return t("menu_title");
  }

  async openSection(chatId, messageId, section) {
    const store = await this.state();
    if (section === "community") {
      const [text, snap] = await this.communityBody(chatId);
      const mk = snap ? this.communityKb(snap, await this.loadDraft(chatId)) : menuKb(section, this.env.PUBLIC_URL);
      await this.editOrSend(chatId, messageId, text, mk);
      return;
    }
    let text = await this.sectionText(section);
    const mk = menuKb(section, this.env.PUBLIC_URL);
    if (section === "pronostici") {
      const note = pronosticiNote(store.tracking || {});
      if (note && !text.includes("\n\n")) text += `\n\n${note}`;
      text += `\n\n${t("disclaimer")}`;
    }
    await this.editOrSend(chatId, messageId, text, mk);
  }

  // ------------------------------------------------- callback data
  async onCallback(chatId, callbackId, messageId, data) {
    const toast = data.startsWith("don:") ? "⭐ Invio la fattura…" : null;
    await this.answerCb(callbackId, toast);
    if (!this.authorized(chatId)) return;
    console.log("Telegram: callback", data, "da", chatId);
    try {
      if (data === "m") {
        await this.editOrSend(chatId, messageId, menuText(), menuKb(null, this.env.PUBLIC_URL));
      } else if (data.startsWith("p:")) {
        await this.openSection(chatId, messageId, data.slice(2));
      } else if (data === "flw") {
        const store = await this.state();
        await this.editOrSend(chatId, messageId, t("segui_prompt"), teamsKb(store, "flw"));
      } else if (data.startsWith("flw:")) {
        await this.follow(chatId, data.slice(4), messageId);
      } else if (data === "unf") {
        await this.showUnfollow(chatId, messageId);
      } else if (data.startsWith("unf:")) {
        await this.doUnfollow(chatId, data.slice(4), messageId);
      } else if (data === "don") {
        await this.editOrSend(chatId, messageId, t("don_title"), donKb());
      } else if (data.startsWith("don:")) {
        let stars = Number.parseInt(data.slice(4), 10);
        if (Number.isNaN(stars)) stars = 50;
        await this.sendInvoice(chatId, stars);
      } else if (data.startsWith("cmk:")) {
        await this.cmPick(chatId, messageId, data.slice(4));
      } else if (data.startsWith("cm:")) {
        await this.cmMatch(chatId, messageId, data.slice(3));
      } else if (data === "cmsub") {
        await this.cmSubmit(chatId, messageId);
      }
    } catch (e) {
      console.error("Telegram: callback", data, "fallita:", e);
    }
  }

  // ------------------------------------------------------------- follow
  async loadFollows() {
    const d = await this.kvGet("follows.json");
    return isObj(d) ? d : {};
  }

  async addFollow(chatId, teams) {
    const follows = await this.loadFollows();
    const key = String(chatId);
    if (!Array.isArray(follows[key])) follows[key] = [];
    const cur = follows[key];
    const added = [];
    for (const team of teams) if (team && !cur.includes(team)) { cur.push(team); added.push(team); }
    await this.kvSet("follows.json", follows);
    return added;
  }

  async removeFollow(chatId, teams) {
    const follows = await this.loadFollows();
    const key = String(chatId);
    const cur = follows[key] || [];
    let removed;
    if (!teams) { follows[key] = []; removed = cur; }
    else {
      removed = cur.filter((x) => teams.includes(x));
      follows[key] = cur.filter((x) => !teams.includes(x));
    }
    await this.kvSet("follows.json", follows);
    return removed;
  }

  async follow(chatId, team, messageId) {
    const store = await this.state();
    const candidates = parseTeams(store);
    const canon = candidates[norm(team)] || team;
    await this.addFollow(chatId, [canon]);
    const cur = (await this.loadFollows())[String(chatId)] || [];
    await this.editOrSend(chatId, messageId, t("segui_ok", { teams: h(cur.join(", ")) }), menuKb(null, this.env.PUBLIC_URL));
  }

  async showUnfollow(chatId, messageId) {
    const store = await this.state();
    const followed = (await this.loadFollows())[String(chatId)] || [];
    if (!followed.length) {
      await this.editOrSend(chatId, messageId, t("stop_none"), menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    await this.editOrSend(chatId, messageId, t("stop_prompt"), teamsKb(store, "unf", followed));
  }

  async doUnfollow(chatId, target, messageId) {
    let text;
    if (target === "all") {
      await this.removeFollow(chatId);
      text = t("stop_ok_all");
    } else {
      const removed = await this.removeFollow(chatId, [target]);
      text = removed.length ? t("stop_ok", { teams: h(removed.join(", ")) }) : t("stop_none");
    }
    await this.editOrSend(chatId, messageId, text, menuKb(null, this.env.PUBLIC_URL));
  }

  async segui(chatId, arg) {
    const store = await this.state();
    if (!arg) {
      await this.send(chatId, t("segui_prompt"), teamsKb(store, "flw"));
      return;
    }
    const candidates = parseTeams(store);
    const found = [];
    for (const raw of arg.split(",")) {
      const canon = candidates[norm(raw.trim())];
      if (canon && !found.includes(canon)) found.push(canon);
    }
    if (!found.length) {
      await this.send(chatId, t("segui_prompt"), teamsKb(store, "flw"));
      return;
    }
    await this.addFollow(chatId, found);
    const cur = (await this.loadFollows())[String(chatId)] || [];
    await this.send(chatId, t("segui_ok", { teams: h(cur.join(", ")) }), menuKb(null, this.env.PUBLIC_URL));
  }

  async stopsegui(chatId, arg) {
    const store = await this.state();
    const followed = (await this.loadFollows())[String(chatId)] || [];
    if (!arg) {
      await this.send(chatId, t("stop_prompt"), teamsKb(store, "unf", followed));
      return;
    }
    const candidates = parseTeams(store);
    const teams = arg.split(",").map((x) => candidates[norm(x.trim())]).filter(Boolean);
    const removed = await this.removeFollow(chatId, teams);
    const text = removed.length ? t("stop_ok", { teams: h(removed.join(", ")) }) : t("stop_none");
    await this.send(chatId, text, menuKb(null, this.env.PUBLIC_URL));
  }

  // ----------------------------------------------------------- community
  async loadDraft(chatId) {
    const d = await this.kvGet(`tg:cm_draft:${chatId}`);
    return isObj(d) ? d : {};
  }

  async saveDraft(chatId, draft) {
    await this.kvSet(`tg:cm_draft:${chatId}`, draft);
  }

  async communityData() {
    return communityLoad(await this.kvGet("community.json"));
  }

  async communityBody(chatId) {
    const store = await this.state();
    const snap = communitySnapshot(store, await this.communityData(), `tg:${chatId}`);
    if (!snap.round || !(snap.fixtures || []).length) return [t("community_nodata"), null];
    const lines = [t("community_title", { r: snap.round }), t("community_parts", { n: snap.participants }), ""];
    const my = snap.my;
    if (my) {
      const [w, l, pend] = entryCounts(my);
      lines.push(t("community_mine", { n: (my.picks || []).length, w, l, pend }));
      for (const pk of my.picks || []) {
        const label = marketLabel(pk.market, pk.pick);
        const score = pk.score || "";
        if (pk.result === "win") lines.push("  " + t("community_row_win", { label, score }));
        else if (pk.result === "loss") lines.push("  " + t("community_row_loss", { label, score }));
        else lines.push("  " + t("community_row_pend", { label }));
      }
      lines.push("");
    }
    lines.push(t("community_picks_title"));
    for (const fx of snap.fixtures) {
      lines.push(t("community_match", { home: h(fx.home), away: h(fx.away) }));
      const agg = (snap.aggregates || {})[fx.id] || {};
      if (!nonEmpty(agg)) { lines.push("  " + t("community_no_opts")); continue; }
      for (const [mkt] of CM_OPTS) {
        const per = agg[mkt] || {};
        if (!nonEmpty(per)) continue;
        let pick = null, n = -Infinity;
        for (const k of Object.keys(per)) if (per[k] > n) { n = per[k]; pick = k; }
        lines.push(t("community_top", { market: t(`community_market_${mkt}`), pick: marketLabel(mkt, pick), n }));
      }
    }
    return [lines.join("\n"), snap];
  }

  cmFidLabel(fx, n = 12) {
    return `${h(fx.home).slice(0, n)}–${h(fx.away).slice(0, n)}`;
  }

  communityKb(snap, draft) {
    if (snap.my) return menuKb("community", this.env.PUBLIC_URL);
    const fixtures = snap.fixtures || [];
    const valid = new Set(fixtures.map((f) => String(f.id)));
    const draftClean = {};
    for (const k of Object.keys(draft || {})) if (valid.has(k)) draftClean[k] = draft[k];
    const rows = [];
    for (let i = 0; i < fixtures.length; i += 2) {
      const row = [];
      for (const fx of fixtures.slice(i, i + 2)) {
        let label = this.cmFidLabel(fx);
        if (draftClean[String(fx.id)]) label = "✓ " + label;
        row.push([label, `cm:${fx.id}`]);
      }
      rows.push(row);
    }
    if (Object.keys(draftClean).length) {
      rows.push([[t("community_submit", { n: Object.keys(draftClean).length }), "cmsub"]]);
    }
    rows.push([[t("section_refresh"), "p:community"], [t("menu_menu"), "m"]]);
    return kb(rows);
  }

  async cmMatch(chatId, messageId, fid) {
    const store = await this.state();
    const [text, snap] = await this.communityBody(chatId);
    if (!snap) {
      await this.editOrSend(chatId, messageId, text, menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    const fixtures = {};
    for (const f of snap.fixtures) fixtures[String(f.id)] = f;
    const fx = fixtures[String(fid)];
    if (!fx) {
      await this.editOrSend(chatId, messageId, t("community_no_match"), this.communityKb(snap, await this.loadDraft(chatId)));
      return;
    }
    const draft = await this.loadDraft(chatId);
    const cur = draft[String(fid)];
    const lines = [text, "", t("community_pick_hint", { home: h(fx.home), away: h(fx.away) })];
    if (cur) {
      lines.push(t("community_current", { label: marketLabel(cur.market, cur.pick) }));
    }
    const rows = [];
    for (const [mkt, opts] of CM_OPTS) {
      const row = [];
      for (const [pk, lbl] of opts) {
        const on = cur && cur.market === mkt && cur.pick === pk;
        row.push([(on ? "✓ " + lbl : lbl), `cmk:${fid}:${mkt}:${pk}`]);
      }
      rows.push(row);
    }
    if (Object.keys(draft).length) {
      rows.push([[t("community_submit", { n: Object.keys(draft).length }), "cmsub"]]);
    }
    rows.push([[t("back"), "p:community"]]);
    await this.editOrSend(chatId, messageId, lines.join("\n"), kb(rows));
  }

  async cmPick(chatId, messageId, rest) {
    const store = await this.state();
    const parts = rest.split(":");
    if (parts.length < 3) return;
    const fid = parts[0];
    const mkt = parts[1];
    const pk = parts.slice(2).join(":");
    let ok = CM_VALID[mkt] ? CM_VALID[mkt].has(pk) : false;
    if (ok) {
      ok = new Set((store.fixtures || []).filter((f) => f.id != null).map((f) => String(f.id))).has(String(fid));
    }
    if (!ok) {
      await this.send(chatId, t("community_no_match"));
      return;
    }
    const draft = await this.loadDraft(chatId);
    const cur = draft[fid];
    if (cur && cur.market === mkt && cur.pick === pk) delete draft[fid];
    else draft[fid] = { market: mkt, pick: pk };
    await this.saveDraft(chatId, draft);
    await this.cmMatch(chatId, messageId, fid);
  }

  async cmSubmit(chatId, messageId) {
    const store = await this.state();
    const draft = await this.loadDraft(chatId);
    const picks = Object.entries(draft).map(([fid, v]) => ({
      fixture_id: fid, market: v.market, pick: v.pick,
    }));
    const [text, snap] = await this.communityBody(chatId);
    if (!picks.length) {
      const note = snap && snap.my ? t("community_already") : t("community_empty");
      await this.editOrSend(chatId, messageId, `${text}\n\n${note}`,
        snap ? this.communityKb(snap, draft) : menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    const cdata = await this.communityData();
    const res = communitySubmit(store, cdata, `tg:${chatId}`, picks, null, { source: "telegram" });
    const mk = menuKb(snap ? "community" : null, this.env.PUBLIC_URL);
    if (res.status === "ok") {
      await this.kvSet("community.json", cdata);
      await this.saveDraft(chatId, {});
      const note = t("community_sent", { n: picks.length, r: (snap && snap.round) || "?" });
      await this.editOrSend(chatId, messageId, `${text}\n\n${note}`, mk);
    } else if (res.status === "already") {
      await this.editOrSend(chatId, messageId, `${text}\n\n${t("community_already")}`, mk);
    } else {
      await this.editOrSend(chatId, messageId, `${text}\n\n❌ ${res.status}`,
        snap ? this.communityKb(snap, draft) : menuKb(null, this.env.PUBLIC_URL));
    }
  }

  // -------------------------------------------------------------- capo
  async capoAiuto(chatId) {
    const text = (
      "👑 Comandi da Capo (solo per @ziosapi):\n\n"
      + "/capo aiuto — questa guida\n"
      + "/capo stato — stato istantaneo (allenatori, quote, coupon)\n\n"
      + "🎯 PROBABILITÀ (esito più probabile per partita, NIENTE valore):\n"
      + "/capo migliori — l'esito vincente più probabile di OGNI partita\n"
      + "/capo migliori <N> — le N partite con l'esito più sicuro\n\n"
      + "🔁 ALLENATORI (new-manager bounce):\n"
      + "/capo coach — elenco registrati\n"
      + "/capo coach add <Squadra>|<Allenatore>|<GG/MM/AAAA>\n"
      + "  · parto dal nome squadra (opus anche senza diacritici)\n"
      + "  · <Allenatore> e <data> opzionali (default: oggi)\n"
      + "  es. /capo coach add Fiorentina|Mario Rossi|12/09/2026\n"
      + "/capo coach del <Squadra>\n\n"
      + "🎟️ ABBONAMENTI:\n"
      + "/capo coupon <CODICE> — crea un voucher\n"
      + "/capo regala <chat_id> — completo a VITA a quella chat\n\n"
      + "📜 SOSTENITORI:\n"
      + "/capo donatori — libro dei donatori (totale ⭐)"
    );
    await this.send(chatId, text, menuKb(null, this.env.PUBLIC_URL));
  }

  async coachLoad() {
    const d = await this.kvGet("coaches.json");
    return isObj(d) && isObj(d.teams) ? d : { teams: {}, updated: 0 };
  }

  async coachSave(reg) {
    await this.kvSet("coaches.json", { ...reg, updated: Math.floor(Date.now() / 1000) });
  }

  daysSince(entry) {
    const since = isObj(entry) ? entry.since : null;
    if (!since) return null;
    return (Date.now() / 1000 - since) / 86400;
  }

  isNew(entry) {
    if (!NEW_MANAGER_ENABLED) return false;
    const d = this.daysSince(entry);
    return d != null && d <= NEW_MANAGER_WINDOW_DAYS;
  }

  async capoStato(chatId) {
    const reg = await this.coachLoad();
    const teams = reg.teams || {};
    const lines = ["👑 Stato del bot:\n"];
    if (nonEmpty(teams)) {
      lines.push("🔁 Allenatori registrati:");
      for (const [name, e] of Object.entries(teams)) {
        const mgr = e.manager || "da rilevare";
        const d = this.daysSince(e);
        const when = d != null ? ` · in carica da ${fmt0(d)} giorni` : "";
        const era = this.isNew(e) ? " (NUOVA ERA ✔)" : "";
        lines.push(`  · ${name}: ${mgr}${when}${era}`);
      }
    } else {
      lines.push("🔁 Nessun allenatore registrato.");
    }
    const couponN = (await this.extraCoupons()).length;
    lines.push(`\n🎟️ Coupon del capo: ${couponN}`);
    lines.push(`\nNota: le modifiche valgono dal prossimo ciclo (ogni ${UPDATE_INTERVAL_MIN} min) e su Telegram Remote.`);
    await this.send(chatId, lines.join("\n"), menuKb(null, this.env.PUBLIC_URL));
  }

  async capoMigliori(chatId, limit = null) {
    const store = await this.state();
    const fixtures = (store.fixtures || []).filter(
      (f) => f.status !== "finished" && (f.predictions || {})["1x2"],
    );
    if (!fixtures.length) {
      await this.send(chatId, "Nessuna partita con pronostico disponibile.", menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    fixtures.sort((a, b) => ((a.start_ts || 0) - (b.start_ts || 0)));
    const rows = [];
    for (const fx of fixtures) {
      const probs = fx.predictions["1x2"];
      let pick = "1";
      for (const k of ["1", "x", "2"]) if ((probs[k] || 0) > (probs[pick] || 0)) pick = k;
      const p = probs[pick] || 0;
      const fair = p > 0 ? 1 / p : 0;
      let label;
      if (pick === "1") label = `1 · ${fx.home}`;
      else if (pick === "2") label = `2 · ${fx.away}`;
      else label = "X · Pareggio";
      const when = utcDowDMHM(fx.start_ts || 0);
      rows.push({
        sort: p,
        text: `🕐 ${when} · ${fx.home} - ${fx.away}\n`
          + `   🎯 ${label}  —  probabilità ${fmt0(p * 100)}%  (fair ${fmtFixed(fair, 2)})\n`
          + `   📊 1X2: ${fmt0((probs["1"] || 0) * 100)}/${fmt0((probs.x || 0) * 100)}/${fmt0((probs["2"] || 0) * 100)}%`,
      });
    }
    if (limit) { rows.sort((a, b) => b.sort - a.sort); rows.length = Math.min(rows.length, limit); }
    else rows.sort((a, b) => a.sort - b.sort);
    const head = "🎯 Miglior esito per PROBABILITÀ (modello, non valore):\n\n";
    await this.send(chatId, head + rows.map((r) => r.text).join("\n\n"), menuKb(null, this.env.PUBLIC_URL));
  }

  async capoCoach(chatId, arg) {
    await this.send(chatId, t("ai_thinking"));
    const action = arg.trim() ? norm(arg.trim().split(" ")[0]) : "";
    if (!arg.trim()) {
      await this.send(chatId, await this.capoCoachList(), menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    const store = await this.state();
    if (action === "del" || action === "remove" || action === "rimuovi") {
      const rest = arg.trim().includes(" ") ? arg.trim().split(" ").slice(1).join(" ").trim() : "";
      if (!rest) {
        await this.send(chatId, await this.capoCoachList(), menuKb(null, this.env.PUBLIC_URL));
        return;
      }
      const reg = await this.coachLoad();
      const teams = reg.teams;
      const namesMap = parseTeams(store);
      const canon = namesMap[norm(rest)] || rest;
      if (!(canon in teams)) {
        await this.send(chatId, `Se non vedo ${canon} nel registro, nulla da rimuovere.`, menuKb(null, this.env.PUBLIC_URL));
        return;
      }
      delete teams[canon];
      await this.coachSave(reg);
      await this.send(chatId, `✅ ${canon}: rimosso dal registro allenatori.`, menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    if (action === "add" || action === "set" || action === "adds") {
      const fields = arg.trim().includes(" ")
        ? arg.trim().split(" ").slice(1).join(" ").trim().split("|") : [];
      if (!fields.length || fields.length > 3) {
        await this.send(chatId, "Formato: /capo coach add Squadra|Allenatore|GG/MM/AAAA", menuKb(null, this.env.PUBLIC_URL));
        return;
      }
      const teamRaw = (fields[0] || "").trim();
      const namesMap = parseTeams(store);
      const canon = namesMap[norm(teamRaw)] || teamRaw;
      if (!canon) {
        await this.send(chatId, `❓ Squadra '${teamRaw}' non riconosciuta: usala con il nome esatto (es. AC Milan).`, menuKb(null, this.env.PUBLIC_URL));
        return;
      }
      let mgr = "";
      let sinceTs = null;
      if (fields.length >= 2 && fields[1].trim()) mgr = fields[1].trim();
      if (fields.length >= 3 && fields[2].trim()) {
        const date = fields[2].trim();
        const md = date.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
        if (md) {
          sinceTs = Math.floor(Date.UTC(Number(md[3]), Number(md[2]) - 1, Number(md[1])) / 1000);
        } else {
          await this.send(chatId, `⚠️ Data '${date}' non valida (user DD/MM/YYYY), uso oggi.`, menuKb(null, this.env.PUBLIC_URL));
        }
      }
      const reg = await this.coachLoad();
      if (!isObj(reg.teams)) reg.teams = {};
      const teams = reg.teams;
      const entry = teams[canon] || {};
      let tid = null;
      for (const r of store.standings || []) if (r.name === canon) { tid = r.team_id; break; }
      entry.team_id = tid || entry.team_id;
      entry.manager = mgr || entry.manager;
      entry.since = sinceTs != null ? sinceTs : Math.floor(Date.now() / 1000);
      entry.source = "capo";
      entry.note = "Registrato dal Capo via Telegram";
      teams[canon] = entry;
      await this.coachSave(reg);
      await this.send(chatId, `✅ ${canon}: nuovo allenatore registrato${mgr ? ` (${mgr})` : " (nome da rilevare)"} — nuova era attiva per 30 giorni.`, menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    await this.send(chatId, await this.capoCoachList(), menuKb(null, this.env.PUBLIC_URL));
  }

  async capoCoachList() {
    const reg = await this.coachLoad();
    const teams = reg.teams || {};
    if (!nonEmpty(teams)) return "Registro allenatori vuoto (nessuna nuova era).";
    const lines = ["Registro allenatori (new-manager bounce):"];
    for (const [name, e] of Object.entries(teams)) {
      const mgr = e.manager || "da rilevare";
      const d = this.daysSince(e);
      const when = d != null ? ` · era in carica da ${fmt0(d)} giorni` : "";
      const era = this.isNew(e) ? " · NUOVA ERA ✔" : "";
      lines.push(`  · ${name}: ${mgr}${when}${era}`);
    }
    return lines.join("\n");
  }

  async subsLoad() {
    const d = await this.kvGet("subs.json");
    return isObj(d) ? d : {};
  }

  async extraCoupons() {
    const d = await this.subsLoad();
    const extra = d._coupons || [];
    return extra.filter((c) => typeof c === "string").map((c) => c.toLowerCase());
  }

  async addCoupon(code) {
    code = String(code || "").trim();
    if (!code) return false;
    const d = await this.subsLoad();
    const extra = Array.isArray(d._coupons) ? d._coupons : [];
    d._coupons = extra;
    if (extra.map((c) => String(c).toLowerCase()).includes(code.toLowerCase())) return false;
    extra.push(code);
    await this.kvSet("subs.json", d);
    console.log("subs: coupon", code, "aggiunto dal Capo");
    return true;
  }

  async grantLifetime(chatId) {
    const d = await this.subsLoad();
    d[String(chatId)] = LIFETIME_TS;
    await this.kvSet("subs.json", d);
    console.log("subs: chat", chatId, "ha ricevuto il completo a vita dal Capo");
    return true;
  }

  async redeemCoupon(chatId, code) {
    code = String(code || "").trim().toLowerCase();
    const valid = String(this.env.SUBS_COUPONS || "").split(",")
      .map((x) => x.trim()).filter(Boolean).map((x) => x.toLowerCase());
    const extra = await this.extraCoupons();
    if (!code || !valid.concat(extra).includes(code)) return false;
    await this.grantLifetime(chatId);
    console.log("subs: voucher", code, "riscattato da chat", chatId, "(a vita)");
    return true;
  }

  async capoCoupon(chatId, arg) {
    const code = arg.trim();
    if (!code) {
      await this.send(chatId, "Uso: /capo coupon <CODICE>", menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    if (await this.addCoupon(code)) {
      await this.send(chatId, `🎟️ Coupon '${code}' creato: i fan possono scriverlo in chat (o /coupon CODICE) per il completo a VITA.`, menuKb(null, this.env.PUBLIC_URL));
    } else {
      await this.send(chatId, `ℹ️ '${code}' esiste già.`, menuKb(null, this.env.PUBLIC_URL));
    }
  }

  async capoRegala(chatId, arg) {
    const target = arg.trim();
    const targetId = /^\d+$/.test(target) ? Number(target) : NaN;
    if (Number.isNaN(targetId)) {
      await this.send(chatId, "Uso: /capo regala <chat_id numerico>", menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    if (targetId === chatId) {
      await this.send(chatId, "👑 Sei già il Capo, non serve.", menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    await this.grantLifetime(targetId);
    await this.send(chatId, `🎁 Chat ${targetId}: completo ⭐ a VITA regalato!`, menuKb(null, this.env.PUBLIC_URL));
  }

  async capoDonatori(chatId) {
    let donors = await this.kvGet("donors.json");
    donors = Array.isArray(donors) ? donors : [];
    if (!donors.length) {
      await this.send(chatId, "📜 Nessun donatore registrato per ora.", menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    const lines = ["📜 <b>Libro dei sostenitori</b>", ""];
    let total = 0;
    for (const d of [...donors].sort((a, b) => (((b && b.stars) || 0) - ((a && a.stars) || 0)))) {
      if (!isObj(d)) continue;
      total += Number(d.stars || 0);
      const when = utcDMY(d.last_ts || 0);
      lines.push(`  ${d.chat} — <b>${d.stars} ⭐</b> (${d.n} donazioni, ultima ${when})`);
    }
    lines.push(`\n<b>Totale: ${total} ⭐</b>`);
    await this.send(chatId, lines.join("\n"), menuKb(null, this.env.PUBLIC_URL));
  }

  async handleCapo(chatId, text) {
    if (!this.isCapo(chatId)) {
      await this.send(chatId, "🚫 Comando riservato al Capo.", menuKb(null, this.env.PUBLIC_URL));
      return;
    }
    const args = text.split(/\s+/);
    const rest = (args.length > 1 ? text.slice(args[0].length) : "").trim();
    const action = rest ? norm(rest.split(" ")[0]) : "";
    const nxtOf = () => (rest.includes(" ") ? rest.split(" ").slice(1).join(" ").trim() : "");
    if (!rest || action === "aiuto" || action === "help" || action === "?") {
      await this.capoAiuto(chatId);
    } else if (action === "stato") {
      await this.capoStato(chatId);
    } else if (action === "migliori") {
      const nxt = nxtOf();
      let limit = Number.parseInt(nxt, 10);
      if (!nxt || Number.isNaN(limit)) limit = null;
      await this.capoMigliori(chatId, limit);
    } else if (action === "coach") {
      await this.capoCoach(chatId, nxtOf());
    } else if (action === "coupon") {
      await this.capoCoupon(chatId, nxtOf());
    } else if (action === "regala") {
      await this.capoRegala(chatId, nxtOf());
    } else if (action === "donatori" || action === "donatore" || action === "sostenitori") {
      await this.capoDonatori(chatId);
    } else {
      await this.capoAiuto(chatId);
    }
  }

  // -------------------------------------------------------------- AI
  async ask(chatId, question) {
    const store = await this.state();
    await this.send(chatId, t("ai_thinking"));
    const result = assistantAnswer(question, store.fixtures || []);
    await this.send(chatId, renderAssistant(result), menuKb(null, this.env.PUBLIC_URL));
  }

  // ---------------------------------------------------------- donazioni
  async sendInvoice(chatId, stars) {
    const payload = {
      chat_id: chatId,
      title: t("don_invoice_title"),
      description: "Grazie per il supporto a Serie A Stats ❤️",
      payload: `don-${chatId}-${Math.floor(Date.now() / 1000)}`,
      provider_token: "",
      currency: "XTR",
      prices: [{ label: "⭐ Telegram Stars", amount: Math.trunc(Number(stars)) }],
      start_parameter: "seriea-stats",
    };
    if (await this.call("sendInvoice", payload) === null) {
      console.warn("Telegram: fattura", stars, "stelle rifiutata per", chatId, this.lastErr);
      await this.send(chatId, t("don_error", { err: h(this.lastErr || "errore sconosciuto") }), donKb());
    }
  }

  async onPrecheckout(queryId, payload) {
    console.log("Telegram: pre-checkout ricevuto (payload", payload || "?", ")");
    await this.call("answerPreCheckoutQuery", { pre_checkout_query_id: queryId, ok: true });
  }

  async onSuccessfulPayment(chatId, payment, payload) {
    const stars = payment.total_amount || 0;
    if (payload) console.log("Telegram: pagamento verificato payload", payload);
    try {
      let donors = await this.kvGet("donors.json");
      donors = Array.isArray(donors) ? donors : [];
      let entry = donors.find((d) => isObj(d) && d.chat === chatId);
      if (!entry) {
        entry = { chat: chatId, stars: 0, n: 0, last_ts: Math.floor(Date.now() / 1000) };
        donors.push(entry);
      }
      entry.stars = Number(entry.stars || 0) + Number(stars);
      entry.n = Number(entry.n || 0) + 1;
      entry.last_ts = Math.floor(Date.now() / 1000);
      await this.kvSet("donors.json", donors);
    } catch (e) {
      console.warn("registrazione donatore fallita:", e);
    }
    await this.send(chatId, t("don_thanks", { stars }), menuKb(null, this.env.PUBLIC_URL));
  }

  // ------------------------------------------------------------ notify
  async loadStarted() {
    const data = await this.kvGet("started.json");
    if (Array.isArray(data)) {
      return [...new Set(data.filter((c) => Number.isInteger(c)))].sort((a, b) => a - b);
    }
    return [];
  }

  async registerStarted(chatId) {
    const started = await this.loadStarted();
    if (started.includes(chatId)) return;
    started.push(chatId);
    await this.kvSet("started.json", started);
    console.log("chat", chatId, "registrata agli avvisi pronostici");
    try { await redisSAdd(this.env, "seriea:tg:started", String(chatId)); } catch (e) { console.warn("SADD tg:started", e); }
  }

  async touchUser(update) {
    try {
      const cbRaw = update && update.callback_query;
      const hasCb = isObj(cbRaw) && Object.keys(cbRaw).length > 0;
      const cb = hasCb ? cbRaw : {};
      const msg = (update && update.message) || {};
      const user = (hasCb ? cb : msg).from || {};
      const uid = user.id;
      if (!uid || user.is_bot) return;
      const chat = msg.chat || (cb.message || {}).chat || {};
      const chatId = chat.id || uid;
      if (this.owners.includes(chatId)) return;
      const kind = hasCb ? "tasto" : "messaggio";
      const now = Math.floor(Date.now() / 1000);
      let data = await this.kvGet("tg_users.json");
      let users = isObj(data) && isObj(data.users) ? data.users : null;
      if (!users) { users = {}; data = { users }; }
      if (!data.seeded) {
        try {
          const known = new Set(await this.loadStarted());
          if (!known.size) {
            const follows = await this.kvGet("follows.json");
            if (isObj(follows)) {
              for (const c of Object.keys(follows)) if (/^-?\d+$/.test(c)) known.add(Number(c));
            }
          }
          for (const cid of known) {
            const k = String(cid);
            if (!users[k]) users[k] = { uid: cid, name: String(cid), username: "", first_seen: 0, last_seen: 0 };
          }
          data.seeded = true;
          await this.kvSet("tg_users.json", data);
        } catch (e) {
          console.debug("seed utenti noti fallito:", e);
        }
      }
      const key = String(chatId);
      const entry = users[key];
      if (entry !== undefined) {
        if (now - Number(entry.last_seen || 0) >= 86400) {
          entry.last_seen = now;
          await this.kvSet("tg_users.json", data);
        }
        return;
      }
      const first = user.first_name || "";
      const last = user.last_name || "";
      const name = `${first} ${last}`.trim() || user.username || String(uid);
      users[key] = { uid, name, username: user.username || "", first_seen: now, last_seen: now };
      await this.kvSet("tg_users.json", data);
      const ctype = { private: "privato", group: "gruppo", supergroup: "gruppo" }[chat.type] || chat.type || "?";
      const auth = this.authorized(chatId) ? "✅ autorizzato" : "⛔ non autorizzato";
      const who = h(name) + (user.username ? ` (@${h(user.username)})` : "");
      const lines = [
        `👋 <b>Nuovo utente sul bot</b>: ${who}`,
        `id <code>${uid}</code>` + (chatId !== uid ? ` · chat <code>${chatId}</code>` : "") + ` · ${ctype} · primo accesso: ${kind}`,
        `${auth} · utenti totali: ${Object.keys(users).length}`,
      ];
      for (const owner of this.owners) if (owner !== chatId) await this.send(owner, lines.join("\n"));
      console.log("Telegram: nuovo utente", who, "(chat", chatId + "), capo avvisato");
    } catch (e) {
      console.debug("notifica nuovo utente fallita:", e);
    }
  }

  // ------------------------------------------------------------ comandi
  async handleCommand(chatId, text) {
    const store = await this.state();
    if (text.startsWith("/start") || text.startsWith("/help") || text.startsWith("/menu")) {
      if (text.startsWith("/start")) await this.registerStarted(chatId);
      await this.sendMenu(chatId);
    } else if (text.startsWith("/classifica")) {
      await this.send(chatId, classificaText(store.standings || []), menuKb("classifica", this.env.PUBLIC_URL));
    } else if (text.startsWith("/giornata") || text.startsWith("/partite")) {
      await this.send(chatId, giornataText(store.fixtures || []), menuKb("partite", this.env.PUBLIC_URL));
    } else if (text.startsWith("/risultati") || text.startsWith("/gare")) {
      await this.send(chatId, risultatiText(store.results || []), menuKb("risultati", this.env.PUBLIC_URL));
    } else if (text.startsWith("/live")) {
      await this.send(chatId, liveText(store.live || {}), menuKb("live", this.env.PUBLIC_URL));
    } else if (text.startsWith("/segui")) {
      await this.segui(chatId, text.slice(6).trim());
    } else if (text.startsWith("/stopsegui")) {
      await this.stopsegui(chatId, text.slice(10).trim());
    } else if (text.startsWith("/donazioni") || text.startsWith("/don")) {
      await this.send(chatId, t("don_title"), donKb());
    } else if (text.startsWith("/tracking") || text.startsWith("/onesta") || text.startsWith("/onestà") || text.startsWith("/statistiche")) {
      await this.send(chatId, trackingText(store.tracking || {}), menuKb("tracking", this.env.PUBLIC_URL));
    } else if (text.startsWith("/schedina")) {
      await this.send(chatId, schedinaText(store.schedina || {}), menuKb("schedina", this.env.PUBLIC_URL));
    } else if (text.startsWith("/presagi") || text.startsWith("/sicura") || text.startsWith("/best")) {
      await this.send(chatId, presagiText(store), menuKb("presagi", this.env.PUBLIC_URL));
    } else if (text.startsWith("/pronostici") || text.startsWith("/bet")) {
      let body = renderAssistant(assistantAnswer("pronostici", store.fixtures || []));
      const note = pronosticiNote(store.tracking || {});
      if (note) body += `\n\n${note}`;
      await this.send(chatId, body, menuKb("pronostici", this.env.PUBLIC_URL));
    } else if (text.startsWith("/ask")) {
      const question = text.slice(4).trim() || "pronostici della giornata";
      await this.ask(chatId, question);
    } else if (text.startsWith("/capo")) {
      await this.handleCapo(chatId, text);
    } else if (text.startsWith("/coupon")) {
      const code = text.slice(7).trim();
      if (await this.redeemCoupon(chatId, code)) {
        await this.send(chatId, t("subs_coupon_ok"), menuKb(null, this.env.PUBLIC_URL));
      } else {
        await this.send(chatId, t("subs_coupon_bad"), menuKb(null, this.env.PUBLIC_URL));
      }
    } else {
      await this.sendMenu(chatId);
    }
  }

  // ----------------------------------------------------------- process
  async processInner(update) {
    await this.touchUser(update);
    const cb = update && update.callback_query;
    if (cb) {
      const chat = (cb.message || {}).chat || {};
      const chatId = chat.id;
      if (chatId) {
        await this.onCallback(chatId, cb.id, (cb.message || {}).message_id, cb.data || "");
      }
      return;
    }
    const pck = update && update.pre_checkout_query;
    if (pck) {
      await this.onPrecheckout(pck.id, pck.invoice_payload || "");
      return;
    }
    const msg = (update && update.message) || {};
    const chat = msg.chat || {};
    const chatId = chat.id;
    if (!chatId) return;
    // il pagamento viene processato PRIMA del gate di autorizzazione
    const payment = msg.successful_payment;
    if (payment) {
      console.log("Telegram: pagamento", payment.invoice_payload, "da", chatId + ":", payment.total_amount, "stelle");
      await this.onSuccessfulPayment(chatId, payment, payment.invoice_payload || "");
      return;
    }
    if (!this.authorized(chatId)) {
      console.log("Telegram: chat", chatId, "non autorizzata");
      return;
    }
    const text = String(msg.text || "").trim();
    if (!text) return;
    console.log("Telegram: messaggio da", chatId + ":", JSON.stringify(text.slice(0, 120)));
    try {
      if (text.startsWith("/")) await this.handleCommand(chatId, text);
      else await this.ask(chatId, text);
    } catch (e) {
      console.error("Telegram: gestione messaggio fallita:", e);
    }
  }
}

export async function handleUpdate(update, env) {
  const bot = new Bot(env);
  try {
    await bot.processInner(update);
  } catch (e) {
    console.error("Telegram: update fallito:", e);
  }
  return { ok: true };
}

export default handleUpdate;
