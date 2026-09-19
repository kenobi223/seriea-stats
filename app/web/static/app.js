"use strict";

const REFRESH_MS = 30000;
const LIVE_REFRESH_MS = 10000;

const state = { data: null };
const tabs = document.querySelectorAll("#tabs button");

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function fmtTime(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("it-IT", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function fmtOdds(v) {
  return v ? v.toFixed(2) : "—";
}

function chipFrom(formChar) {
  const map = { V: "v", N: "n", P: "p" };
  return `<span class="chip ${map[formChar] || "gray"}">${esc(formChar)}</span>`;
}

function resultCharMap(r) {
  return { H: "V", D: "N", A: "P" }[r];
}

// ------------------------------------------------------------- header
function renderHeader() {
  const d = state.data;
  const upd = document.getElementById("last-updated");
  upd.textContent = "Aggiornato: " + fmtTime(d.updated);
  const cycle = document.getElementById("cycle-status");
  if (d.last_error) cycle.textContent = "⚠ " + d.last_error;
  else cycle.textContent = d.season ? `Stagione ${d.season.name}` : "";
}

// ------------------------------------------------------------- matches
function oddsTable(fx) {
  const groups = {};
  for (const o of fx.odds || []) {
    if (!o.odds || o.odds <= 1) continue;
    (groups[o.market] = groups[o.market] || []).push(o);
  }
  const markets = Object.keys(groups);
  if (!markets.length) return `<div class="muted">Nessuna quota disponibile.</div>`;

  const flagKey = new Set();
  const spreads = new Map();
  for (const f of fx.value_flags || []) {
    if (f.kind === "spread") flagKey.add(`${f.market}|${f.pick}`);
    spreads.set(`${f.market}|${f.pick}`, f);
  }

  let html = "";
  for (const m of markets) {
    html += `<div class="subpanel" style="margin-bottom:8px"><h3>${esc(m)}</h3>`;
    for (const o of groups[m]) {
      const key = `${m}|${o.pick}`;
      const flag = spreads.get(key);
      const cls = flag ? ` style="color:${flag.severity === "alert" ? "var(--alert)" : "var(--warn)"}"` : "";
      html += `<div class="odds-row"><span>${esc(o.pick)} ${flag ? "⚠" : ""}<span ${cls}></span></span>
        <span class="val"><span class="source-pill">${esc(o.source)}</span>${fmtOdds(o.odds)}</span></div>`;
    }
    html += "</div>";
  }
  return html;
}

function moraleBlock(fx, side) {
  const m = (fx.morale && fx.morale[side]) || {};
  const name = side === "home" ? fx.home : fx.away;
  if (!m.score) {
    return `<div class="muted">Morale non ancora calcolato.</div>`;
  }
  const w = Math.max(4, Math.min(100, m.score * 10));
  const notes = (m.notes || []).slice(0, 2)
    .map(n => `· ${esc(n.title)}`).join("\n");
  return `<div class="kv"><span class="muted">${esc(name)}:</span><b>${esc(m.label)} ${m.score}/10</b></div>
    <div class="ps-mid" style="margin-top:3px">
      <div class="ps-bar"><div class="ps-fill" style="width:${w}%"></div></div>
      <span class="ps-threat">${m.score}/10</span>
    </div>
    ${m.injuries ? `<div class="kv"><span class="muted">Assenti:</span><b>${m.injuries}</b></div>` : ""}
    ${notes ? `<div class="muted" style="font-size:11px;white-space:pre-line;margin-top:4px">💬 Mister:\n${notes}</div>` : ""}`;
}

function postMorale(home, away, sideHome) {
  const mine = sideHome ? home : away;
  const theirs = sideHome ? away : home;
  let delta = mine > theirs ? 2 : (mine === theirs ? 0 : -2);
  const diff = mine - theirs;
  if (diff >= 3) delta += 1; else if (diff <= -3) delta -= 1;
  if (mine >= 3) delta += 0.5;
  if (theirs === 0) delta += 0.5;
  delta = Math.max(-3, Math.min(3, delta));
  if (delta >= 2) return "▲ vola";
  if (delta > 0) return "▲ su";
  if (delta === 0) return "· stabile";
  if (delta > -2) return "▼ giù";
  return "▼ crisi";
}

function formBlock(fx, side) {
  const form = (side === "home" ? fx.form_home : fx.form_away) || {};
  const lasts = form.last_results || [];
  const chips = lasts.slice(-6).map(e => chipFrom(resultCharMap(e.result) || "?")).join("");
  const season = form.current_season;
  return `
    <div class="kv"><span class="muted">Ultimi:</span><span class="chips">${chips}</span></div>
    ${season ? `<div class="kv"><span class="muted">Stagione:</span><b>${season.giocate} g · ${season.v}V ${season.n}N ${season.p}P · GF ${season.gf} GA ${season.ga}</b></div>` : ""}
  `;
}

function predictionBlock(fx) {
  const p = fx.predictions || {};
  const prob = p["1x2"] || {};
  const ou = p.over_under || {};
  const btts = p.btts || {};
  const lambdas = p.lambdas || {};
  const bets = p.best_bets || [];
  const picks = p.model_picks || {};
  const es = p.exact_score || [];

  let html = "";
  if (Object.keys(prob).length) {
    const p1 = (prob["1"] * 100) || 0, px = (prob["x"] * 100) || 0, p2 = (prob["2"] * 100) || 0;
    html += `<div class="prob-bar">
      <div style="width:${p1}%;background:var(--accent)">${p1.toFixed(0)}%</div>
      <div style="width:${px}%;background:#6e7681">${px.toFixed(0)}%</div>
      <div style="width:${p2}%;background:var(--alert)">${p2.toFixed(0)}%</div>
    </div>`;
    html += `<div class="prob-line">
      <span><b>1</b> ${esc(fx.home)} ${p1.toFixed(1)}%</span>
      <span><b>X</b> ${px.toFixed(1)}%</span>
      <span><b>2</b> ${esc(fx.away)} ${p2.toFixed(1)}%</span>
    </div>`;
  }
  if (lambdas.home_goals != null) {
    html += `<div class="kv" style="margin-top:6px"><span class="muted">Gol attesi:</span>
      <b>${esc(fx.home)} ${lambdas.home_goals} — ${lambdas.away_goals} ${esc(fx.away)}</b></div>`;
  }
  if (ou["over_2.5"] != null) {
    html += `<div class="kv"><span class="muted">Over/Under 2.5:</span>
      <b>over ${(ou["over_2.5"] * 100).toFixed(0)}% · under ${(ou["under_2.5"] * 100).toFixed(0)}%</b></div>`;
  }
  if (btts.si != null) {
    html += `<div class="kv"><span class="muted">Gol da entrambe (BTTS):</span>
      <b>sì ${(btts.si * 100).toFixed(0)}% · no ${(btts.no * 100).toFixed(0)}%</b></div>`;
  }
  const pickRows = Object.keys(picks);
  if (pickRows.length) {
    html += `<div style="margin-top:8px"><b>Pronostico del modello:</b></div>`;
    for (const m of pickRows) {
      const mp = picks[m];
      if (!mp || !mp.key) continue;
      const odds = mp.odds ? ` @ ${fmtOdds(mp.odds)}`
        : (mp.fair ? ` @ ${fmtOdds(mp.fair)} (fair)` : "");
      html += `<div class="kv"><span><span class="chip v">${esc(mp.key.toUpperCase())}</span>
        ${esc(mp.conf || "")} · ${esc((mp.prob * 100).toFixed(0))}%${odds}</span>
        <b>${esc(m)}</b></div>`;
    }
  }
  if (es.length) {
    html += `<div class="kv"><span class="muted">Risultato esatto più probabile:</span>
      <b>${esc(es[0].score)} (${(es[0].prob * 100).toFixed(0)}%)</b></div>`;
  }
  const tm = p.tipster_mix;
  if (tm) {
    const rate = tm.rate != null ? ` · affid. ${(tm.rate * 100).toFixed(0)}%` : "";
    html += `<div class="kv"><span class="muted">🔁 Voce esterna ${esc(tm.source || "?")}:</span>
      <b>1X2 ${esc(tm.outcome || "?")} · gol ${esc(tm.goals || "?")} · ${esc(tm.score || "?")}${rate}</b></div>`;
  }
  if (bets.length) {
    html += `<div style="margin-top:8px"><b>Best bets (prob + quota ok):</b></div>`;
    for (const b of bets) {
      html += `<div class="kv"><span><span class="chip v">${esc(b.pick)}</span>
        @ ${fmtOdds(b.odds)} (prob ${(b.prob * 100).toFixed(0)}%)</span>
        <b style="color:var(--accent)">edge +${(b.edge * 100).toFixed(0)}%</b></div>`;
    }
  }
  if (p.motivation) {
    html += `<div class="motivation">${esc(p.motivation)}</div>`;
  }
  return html || `<div class="muted">Nessun pronostico.</div>`;
}

function renderMatches() {
  const el = document.getElementById("tab-matches");
  const fixtures = (state.data.fixtures || []).filter(f => f.status !== "finished" || true);
  if (!fixtures.length) {
    el.innerHTML = `<div class="muted">Nessuna partita in calendario.</div>`;
    return;
  }
  el.innerHTML = `<div class="section-title">Prossime giornate · ${fixtures.length} partite</div>`;
  for (const fx of fixtures) {
    el.insertAdjacentHTML("beforeend", `
      <div class="card">
        <div class="match-head">
          <div class="teams">${esc(fx.home)} <span class="muted">-</span> ${esc(fx.away)}</div>
          <div class="meta">${fmtTime(fx.start_ts)} · Giornata ${esc(fx.round || "?")}${fx.venue ? " · " + esc(fx.venue) : ""}</div>
        </div>
        <div class="grid2" style="margin-top:12px">
          <div class="subpanel"><h3>Pronostico modello</h3>${predictionBlock(fx)}</div>
          <div>
            <div class="subpanel"><h3>Quote confrontate</h3>${oddsTable(fx)}</div>
          </div>
        </div>
        <div class="grid3" style="margin-top:12px">
          <div class="subpanel"><h3>${esc(fx.home)}</h3>${formBlock(fx, "home")}</div>
          <div class="subpanel"><h3>${esc(fx.away)}</h3>${formBlock(fx, "away")}</div>
          <div class="subpanel"><h3>🎭 Morale & conferenze</h3>${moraleBlock(fx, "home")}${moraleBlock(fx, "away")}</div>
        </div>
      </div>`);
  }
}

// ------------------------------------------------------------- results & live
function renderLiveBlock(live) {
  const matches = (live && live.matches) || [];
  if (!matches.length) {
    return `<div class="card muted">Nessuna partita in corso ora. I risultati finiti li trovi qui sotto, per giornata.</div>`;
  }
  const cards = matches.map(m => `
    <div class="live-card">
      <div class="live-team">${esc(m.home)}</div>
      <div class="live-score">${m.hs ?? "-"} - ${m.as ?? "-"}</div>
      <div class="live-team">${esc(m.away)}</div>
      <div class="live-min">${m.minute != null ? m.minute + "'" : esc(m.period)}</div>
    </div>`).join("");
  return `<div class="section-title">🔴 Live · ${matches.length} partite</div>
    <div class="card"><div class="live-grid">${cards}</div>
      <div class="muted" style="margin-top:8px">Aggiornato ${fmtTime(live.updated)}</div></div>`;
}

function renderResults() {
  const el = document.getElementById("tab-results");
  const results = (state.data.results || []).slice().reverse();
  let html = renderLiveBlock(state.live);

  if (!results.length) {
    html += `<div class="card muted">Nessun risultato ancora disponibile.</div>`;
    el.innerHTML = html;
    return;
  }
  for (const rnd of results) {
    const row = rnd.matches.map(m => {
      const parts = String(m.score || "").split("-").map(s => parseInt(s.trim(), 10));
      let post = "";
      if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
        const h = postMorale(parts[0], parts[1], true);
        const a = postMorale(parts[0], parts[1], false);
        post = `<span class="post-chip">${esc(m.home)} ${h} · ${a} ${esc(m.away)}</span>`;
      }
      return `
      <div>
        <div class="result-row">
          <span>${esc(m.home)}</span>
          <span class="result-score">${esc(m.score)}</span>
          <span>${esc(m.away)}</span>
        </div>
        ${post}
      </div>`;
    }).join("");
    html += `<div class="card"><div class="section-title" style="margin-top:0">Giornata ${esc(rnd.round)}</div>${row}</div>`;
  }
  el.innerHTML = html;
}

async function refreshLive() {
  const active = document.querySelector("#tabs button.active");
  if (!active || active.dataset.tab !== "results") return;
  try {
    const r = await fetch("/api/live");
    const live = await r.json();
    state.live = live;
    const el = document.getElementById("tab-results");
    const results = (state.data.results || []).slice().reverse();
    let html = renderLiveBlock(live);
    if (!results.length) {
      html += `<div class="card muted">Nessun risultato ancora disponibile.</div>`;
    } else {
      for (const rnd of results) {
        const row = rnd.matches.map(m => `
          <div class="result-row">
            <span>${esc(m.home)}</span>
            <span class="result-score">${esc(m.score)}</span>
            <span>${esc(m.away)}</span>
          </div>`).join("");
        html += `<div class="card"><div class="section-title" style="margin-top:0">Giornata ${esc(rnd.round)}</div>${row}</div>`;
      }
    }
    el.innerHTML = html;
  } catch (e) { /* il prossimo giro */ }
}

// ------------------------------------------------------------- tracking
const MARKET_LABEL = { "1x2": "Risultato 1X2", over_under: "Over/Under 2.5", btts: "Entrambe a segno" };
const PICK_LABEL = { over_2_5: "over 2.5", under_2_5: "under 2.5", si: "sì", no: "no" };

function pickLabel(market, pick) {
  if (market === "1x2") {
    return { "1": "vittoria casa", x: "pareggio", "2": "vittoria trasferta" }[pick] || pick;
  }
  return PICK_LABEL[pick] || pick;
}

function renderTracking() {
  const el = document.getElementById("tab-tracking");
  const t = state.data.tracking || {};
  const cal = state.data.calibration || {};
  const rate = t.bets_rate != null ? (t.bets_rate * 100).toFixed(0) + "%" : "—";
  const brier = t.brier != null ? t.brier.toFixed(3) : "—";

  let html = `<div class="section-title">Onestà del modello · quanto i pronostici diventano realtà</div>
    <div class="grid3">
      <div class="card"><div class="big-num">${t.evaluated || 0}</div>
        <div class="muted">partite valutate a fine gara</div></div>
      <div class="card hit-card" onclick="toggleHits(this)"><div class="big-num">${t.bets_hit || 0}/${t.bets_total || 0}</div>
        <div class="muted">pronostici indovinati (${rate}) · clicca per i dettagli</div></div>
      <div class="card"><div class="big-num">${brier}</div>
        <div class="muted">Brier score · più basso = più onesto</div></div>
    </div>
    <div id="hit-detail"></div>`;

  // conteggio per PARTITA (una partita può avere più best-bet/vincere in + mercati)
  if (t.match_bets_total) {
    const mRate = t.match_bets_rate != null ? (t.match_bets_rate * 100).toFixed(0) + "%" : "—";
    const mCls = t.match_bets_rate >= 0.5 ? "v" : "warn";
    html += `<div class="card" style="margin-top:10px"><div class="kv">
        <span class="muted" style="min-width:150px">Partite con pronostico vinto</span>
        <span class="chip ${mCls}">${t.match_bets_hit || 0}/${t.match_bets_total} (${mRate})</span></div>
      <div class="muted" style="margin-top:6px">Conteggio per partita: azzeccata quando almeno un best-bet è stato centrato (il totale sopra è per singolo pronostico).</div></div>`;
  }

  const bins = t.calibration_bins || [];
  // calibrazione: predetto vs reale a fasce
  if (bins.some(b => b.count > 0)) {
    html += `<div class="card"><div class="section-title" style="margin-top:0">Calibrazione: che probabilità do vs cosa succede davvero</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">`;
    for (const b of bins) {
      if (!b.count) continue;
      const ok = b.pred != null && b.actual != null;
      const pct = b.pred * 100;
      const cls = !ok ? "" : b.actual >= b.pred - 0.06 ? "v" : "warn";
      html += `<div class="calib-card">
        <div style="display:flex;justify-content:space-between"><b>${(b.lo * 100).toFixed(0)}–${(b.hi * 100).toFixed(0)}%</b>
          <span class="chip ${cls}">n=${b.count}</span></div>
        <div class="prob-bar" style="margin-top:8px">
          <div style="width:${(b.pred * 100) || 0}%;background:var(--accent)" title="predetto"></div>
        </div>
        <div class="prob-bar" style="margin-top:3px">
          <div style="width:${(b.actual * 100) || 0}%;background:var(--alert)" title="reale"></div>
        </div>
        <div class="muted" style="margin-top:4px;font-size:11.5px">
          per fascia ${b.pred != null ? (b.pred * 100).toFixed(0) + "%" : "—"} predetto ·
          reale ${b.actual != null ? (b.actual * 100).toFixed(0) + "%" : "—"}
        </div>
      </div>`;
    }
    html += `</div><div class="muted" style="margin-top:8px">Barra <span style="color:var(--accent)">blu</span> = probabilità dichiarata,
      barra <span style="color:var(--alert)">rossa</span> = centratura reale. Se la rossa è più corta della blu, ero troppo ottimista.</div></div>`;
  }

  // correttori appresi
  const withCal = Object.keys(MARKET_LABEL).filter(m => cal[m] && Object.keys(cal[m]).length);
  if (withCal.length) {
    html += `<div class="card"><div class="section-title" style="margin-top:0">Cosa ho imparato (correttori attivi)</div>`;
    for (const m of withCal) {
      html += `<div class="kv"><span class="muted" style="min-width:150px">${MARKET_LABEL[m]}</span>`;
      for (const [k, f] of Object.entries(cal[m])) {
        const bad = f > 1 ? "v" : f < 1 ? "warn" : "gray";
        html += `<span class="chip ${bad}" title="probabilità reale / probabilità stimata">${pickLabel(m, k)} ×${f}</span>`;
      }
      html += `</div>`;
    }
    html += `<div class="muted" style="margin-top:6px">Le probabilità dei prossimi pronostici vengono moltiplicate per questi fattori (poi rinormalizzate).</div></div>`;
  }

  // fuori campione: backtest walk-forward (solo round precedenti)
  const oos = t.oos || {};
  const oosPicks = (oos.check || {}).picks || {};
  if (oos.brier_calibrated != null && oos.brier != null && oos.records >= 2) {
    const imp = oos.improvement != null ? `${oos.improvement >= 0 ? "+" : ""}${oos.improvement.toFixed(3)}` : "—";
    const arrow = oos.reliable ? "↘" : "↗";
    html += `<div class="card"><div class="section-title" style="margin-top:0">Fuori campione · vale anche senza vedere il futuro</div>
      <div class="grid3">
        <div class="card"><div class="big-num">${oos.brier.toFixed(3)}</div>
          <div class="muted">Brier as-pubblicato</div></div>
        <div class="card"><div class="big-num">${oos.brier_calibrated.toFixed(3)}</div>
          <div class="muted">Brier ri-calibrato OOS ${arrow}</div></div>
        <div class="card"><div class="big-num">${imp}</div>
          <div class="muted">miglioramento (negativo = più onesto)</div></div>
      </div>`;
    if (oos.rps != null) {
      const rc = oos.rps_calibrated != null ? oos.rps_calibrated : oos.rps;
      html += `<div class="kv" style="margin-top:6px"><span class="muted">RPS 1X2 (ordinale) OOS</span>
        <span class="chip">${oos.rps.toFixed(3)} → ${rc.toFixed(3)}</span></div>`;
    }
    if (oos.ci95) {
      const sig = oos.significant ? "✅ significativo" : "≈ non conclusivo";
      html += `<div class="kv" style="margin-top:6px"><span class="muted">CI95 miglioramento (bootstrap)</span>
        <span class="chip ${oos.significant ? "v" : "warn"}">${oos.ci95.lo >= 0 ? "+" : ""}${oos.ci95.lo.toFixed(3)}…${(oos.ci95.hi >= 0 ? "+" : "") + oos.ci95.hi.toFixed(3)} · p_better ${oos.ci95.p_better.toFixed(2)} · ${sig}</span></div>`;
    }
    if (oosPicks.total) {
      html += `<div class="kv" style="margin-top:6px"><span class="muted">Pronostici del modello OOS</span>
        <span class="chip ${oosPicks.rate >= 0.5 ? "v" : "warn"}">${oosPicks.hit}/${oosPicks.total} (${(oosPicks.rate * 100).toFixed(0)}%)</span></div>`;
    }
    html += `<div class="muted" style="margin-top:6px">La calibrazione in produzione usa solo i round già finiti: nessuna fuga di dati avanti.</div></div>`;
  }

  // errori clamorosi
  const misses = t.notable_misses || [];
  if (misses.length) {
    html += `<div class="card"><div class="section-title" style="margin-top:0">Dove ho sbagliato di più</div>`;
    for (const m of misses) {
      html += `<div class="kv"><span><b>${esc(m.home)} - ${esc(m.away)}</b>
        <span class="muted">(${esc(m.score)} · gj ${esc(m.round || "?")})</span></span>
        <span><span class="chip warn">${pickLabel(m.market, m.pick)}</span>
        lo davo al ${(m.prob * 100).toFixed(0)}% @ ${fmtOdds(m.odds)}</span></div>`;
    }
    html += `</div>`;
  }

  // cosa ho imparato
  const lessons = t.conclusions || [];
  if (lessons.length) {
    html += `<div class="card"><div class="section-title" style="margin-top:0">Riepilogo</div><ul style="margin:0;padding-left:18px">`;
    for (const c of lessons) html += `<li style="margin:3px 0">${esc(c)}</li>`;
    html += `</ul></div>`;
  }

  if (!lessons.length && !bins.length) {
    html = `<div class="section-title">Onestà del modello</div>
      <div class="card muted">Ancora nessun pronostico valutato: quando le prossime partite finiranno,
      confronto pronostico vs risultato reale qui, mostro il tasso di centratura e correggo il modello.</div>`;
  }
  el.innerHTML = html;
}

let hitsLoaded = false;
async function toggleHits(card) {
  card.classList.toggle("open");
  const box = document.getElementById("hit-detail");
  const wantOpen = card.classList.contains("open");
  box.innerHTML = wantOpen ? `<div class="muted">Carico i pronostici indovinati…</div>` : "";
  if (!wantOpen || hitsLoaded) return;
  hitsLoaded = true;
  try {
    const r = await fetch("/api/tracking-records");
    const data = await r.json();
    const rows = [];
    for (const rec of data.records || []) {
      for (const h of rec.hits || []) {
        if (!h.hit) continue;
        rows.push({ ...h, home: rec.home, away: rec.away, score: rec.score, round: rec.round });
      }
    }
    if (!rows.length) {
      box.innerHTML = `<div class="card muted">Nessun pronostico indovinato.</div>`;
      return;
    }
    box.innerHTML = `<div class="card"><div class="section-title" style="margin-top:0">✅ Pronostici indovinati (${rows.length})</div>` +
      rows.map(h => `<div class="kv"><span><b>${esc(h.home)} - ${esc(h.away)}</b>
        <span class="muted">(${esc(h.score)} · gj ${esc(h.round || "?")})</span></span>
        <span><span class="chip v">${pickLabel(h.market, h.pick)}</span>
        lo davo al ${((h.prob || 0) * 100).toFixed(0)}% @ ${fmtOdds(h.odds)}</span></div>`).join("") +
      `</div>`;
  } catch (e) {
    box.innerHTML = `<div class="card muted">Errore nel caricamento dei dettagli.</div>`;
  }
}

// ------------------------------------------------------------- standings
function renderStandings() {
  const el = document.getElementById("tab-standings");
  const rows = state.data.standings || [];
  if (!rows.length) {
    el.innerHTML = `<div class="muted">Nessun dato.</div>`;
    return;
  }
  const teams = new Map(rows.map(r => [r.team_id, r]));
  const fixtures = state.data.fixtures || [];
  const formByTeam = new Map();
  for (const fx of fixtures) {
    formByTeam.set(fx.home_id, fx.form_home);
    formByTeam.set(fx.away_id, fx.form_away);
  }
  el.innerHTML = `<div class="card"><table>
    <thead><tr><th>#</th><th>Squadra</th><th>G</th><th>V</th><th>N</th><th>P</th><th>GF</th><th>GA</th><th>Pt</th><th>Ultime 5</th></tr></thead><tbody>` +
    rows.map(r => {
      const f = formByTeam.get(r.team_id);
      const last = f ? (f.last_results || []).slice(-5).map(e => chipFrom(resultCharMap(e.result) || "?")).join("") : "";
      return `<tr><td class="pos-chip">${r.position}</td><td>${esc(r.name)}</td>
        <td>${r.played}</td><td>${r.wins}</td><td>${r.draws}</td><td>${r.losses}</td>
        <td>${r.gf}</td><td>${r.ga}</td><td><b>${r.points}</b></td>
        <td><span class="chips">${last}</span></td></tr>`;
    }).join("") +
    `</tbody></table></div>`;
}

// ------------------------------------------------------------- sources
function renderSources() {
  const el = document.getElementById("tab-sources");
  const s = state.data.sources || {};
  const rows = [
    ["Sofascore", "risultati, statistiche, quote 1X2", s.sofascore ? "attivo" : "inattivo", true],
    ["ESPn", "stagione, classifica, risultati, live, quote 1X2", (s.espn && s.espn.status) ? "attivo" : "inattivo", true],
    ["centroquote", "conferma calendario Serie A dall'Italia", s.centroquote ? "raggiungibile" : "non raggiungibile da questo IP (datacenter)", false],
    ["sogosport", "quote bookmaker italiane (best-effort)", s.sogosport ? "raggiungibile" : "non raggiungibile da questo IP (datacenter)", false],
  ];
  el.innerHTML = `<div class="card"><table>
    <thead><tr><th>Fonte</th><th>Cosa fornisce</th><th>Stato</th></tr></thead><tbody>` +
    rows.map(r => `<tr><td><b>${esc(r[0])}</b></td><td>${esc(r[1])}</td>
      <td style="color:${r[3] ? "var(--accent)" : "var(--muted)"}">${esc(r[2])}</td></tr>`).join("") +
    `</tbody></table></div>`;
}

// ------------------------------------------------------------- AI chat
let aiReady = false;

const AI_SUGGESTIONS = [
  "Ci sono errori di quota oggi?",
  "Qual è il pronostico della giornata?",
  "Analizza Juventus - Milan",
];

function initAI() {
  const el = document.getElementById("tab-ai");
  if (aiReady) return;
  if (!state.data) { setTimeout(renderAI, 800); return; }
  aiReady = true;
  try {
    const fixtures = state.data.fixtures || [];
    const suggestions = AI_SUGGESTIONS.concat(
      fixtures.slice(0, 3).map(f => `Analizza ${f.home} - ${f.away}`)
    );
    state.aiSuggestions = suggestions;
    el.innerHTML = `
    <div class="card ai-card">
      <div class="section-title">Chiedi all'AI · consigli sui dati reali raccolti</div>
      <p class="muted" style="margin-top:-6px">Chiedi in italiano: pronostici, errori di quota
      o un'analisi partita.</p>
      <div class="ai-suggest">${suggestions.map((s, i) =>
        `<button class="chip ai-chip" onclick="askAIByIndex(${i})">${esc(s)}</button>`).join(" ")}</div>
      <div id="ai-log" class="ai-log"></div>
      <div class="form-row compact">
        <input id="ai-input" placeholder="es. qual è il pronostico della giornata?"
          onkeydown="if(event.key==='Enter')askAI(this.value)">
        <button class="cta" onclick="askAI(document.getElementById('ai-input').value)">Chiedi</button>
      </div>
    </div>`;
  } catch (e) {
    aiReady = false;
    el.innerHTML = `<div class="card muted">Errore nel caricamento della chat. Ricarica la pagina.</div>`;
  }
}

function askAIByIndex(i) {
  askAI(state.aiSuggestions[i]);
}

function aiLine(cls, html) {
  const log = document.getElementById("ai-log");
  if (log) log.insertAdjacentHTML("beforeend", `<div class="ai-line ${cls}">${html}</div>`);
}

async function askAI(question) {
  question = (question || "").trim();
  if (!question) return;
  const input = document.getElementById("ai-input");
  if (input) input.value = "";
  initAI();
  aiLine("user", esc(question));
  aiLine("bot", `<div class="muted">Analizzo i dati…</div>`);
  try {
    const r = await fetch("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const res = await r.json();
    let html = `<b>${esc(res.intro || "")}</b>`;
    for (const l of res.lines || []) html += `<div style="margin-top:4px">${esc(l)}</div>`;
    for (const it of res.items || []) {
      const tag = it.tag || "info";
      const tagCls = tag === "alert" ? "alert" : tag === "warn" ? "warn" : tag === "value" ? "v" : "gray";
      html += `<div class="ai-item"><span class="chip ${tagCls}">${esc(tag.toUpperCase())}</span>
        <b>${esc(it.title)}</b><div class="muted">${esc(it.text)}</div></div>`;
    }
    const log = document.getElementById("ai-log");
    const nodes = log ? log.querySelectorAll(".ai-line") : [];
    if (nodes.length) nodes[nodes.length - 1].outerHTML = `<div class="ai-line bot">${html}</div>`;
  } catch (e) {
    aiLine("bot", `<span class="muted">Errore: impossibile interrogare il server.</span>`);
  }
}

function pickRow(p) {
  const st = p.result === "win" ? "✅" : p.result === "loss" ? "❌" : "⏳";
  const pct = ((p.prob || 0) * 100).toFixed(0) + "%";
  const score = p.score ? `  ${p.score}` : "";
  const lbl = ({1: "1", x: "X", 2: "2", "over_2.5": "Over 2.5",
                "under_2.5": "Under 2.5", si: "BTTS Sì", no: "BTTS No"})[p.pick] || p.pick;
  return `<div class="card"><div class="kv"><span>${esc(p.home)} - ${esc(p.away)}${score}</span>
      <span class="chip">${st}</span></div>
      <div class="muted">${esc(lbl)} @ ${fmtOdds(p.odds)} · prob. ${pct}${p.edge != null ? " · edge " + (p.edge * 100).toFixed(0) + "%" : ""}</div></div>`;
}

function renderSchedina() {
  const el = document.getElementById("tab-schedina");
  const s = state.data.schedina || {};
  if (!s.round || !s.picks || !s.picks.length) {
    el.innerHTML = `<div class="section-title">🎫 Schedina della giornata</div>
      <div class="card muted">Nessuna schedina disponibile: viene creata prima della prima partita della giornata con gli esiti più probabili del modello.</div>`;
    return;
  }
  const won = s.picks.filter(p => p.result === "win").length;
  const lost = s.picks.filter(p => p.result === "loss").length;
  const rows = s.picks.map(pickRow).join("");
  const hist = (s.history || []).slice().reverse().map(h =>
    `<div class="card history-card" onclick="this.classList.toggle('open')">
       <div class="kv"><span>Giornata ${h.round}</span>
       <span class="muted">${h.wins} vinti · ${h.losses} persi · ▼</span></div>
       <div class="history-picks">${(h.picks || []).map(pickRow).join("")}</div>
     </div>`).join("");
  el.innerHTML = `<div class="section-title">🎫 Schedina della giornata ${s.round || "?"}</div>
    <div class="grid3">
      <div class="card"><div class="big-num">${won}/${s.picks.length}</div>
        <div class="muted">eventi vinti</div></div>
      <div class="card"><div class="big-num">${lost}/${s.picks.length}</div>
        <div class="muted">eventi persi</div></div>
      <div class="card"><div class="big-num">${s.picks.length}</div>
        <div class="muted">esiti totali</div></div>
    </div>${rows}
    ${hist ? `<div class="section-title" style="margin-top:20px">📚 Schedine passate</div>${hist}` : ""}`;
}

function renderAI() {
  initAI();
}

// ------------------------------------------------------------- tunnel
async function renderTunnel() {
  const box = document.getElementById("tunnel-box");
  if (!box) return;
  try {
    const r = await fetch("/api/tunnel");
    const t = await r.json();
    if (t.url) {
      box.innerHTML = `Link pubblico (da fuori casa, anche Safari su dati mobili): 
        <a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.url)}</a>`;
    } else if (t.running || (t.available && t.available !== false)) {
      box.textContent = "Link pubblico: in preparazione…";
    } else if (!t.available) {
      box.textContent = "Link pubblico: non disponibile (cloudflared assente).";
    }
  } catch (e) {
    box.textContent = "Link pubblico: —";
  }
}

// ------------------------------------------------------------- tabs & poll
function switchTab(name) {
  tabs.forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  const all = document.querySelectorAll(".tab");
  all.forEach(s => {
    if (s.id === "tab-" + name) {
      s.classList.add("active");
      s.style.animation = "none";
      s.offsetHeight; // reflow
      s.style.animation = "";
    } else {
      s.classList.remove("active");
    }
  });
  renderActive();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

tabs.forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));

function renderActive() {
  const active = document.querySelector("#tabs button.active");
  const name = active ? active.dataset.tab : "matches";
  if (name === "matches") renderMatches();
  else if (name === "results") { renderResults(); refreshLive(); }
  else if (name === "tracking") renderTracking();
  else if (name === "schedina") renderSchedina();
  else if (name === "ai") renderAI();
  else if (name === "standings") renderStandings();
  else if (name === "sources") renderSources();
}

function showSkeleton() {
  const active = document.querySelector("#tabs button.active");
  const name = active ? active.dataset.tab : "matches";
  const el = document.getElementById("tab-" + name);
  if (el && !state.data) {
    el.innerHTML = `<div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card" style="height:120px"></div>`;
  }
}
async function poll() {
  try {
    const r = await fetch("/api/state");
    state.data = await r.json();
    renderHeader();
    renderActive();
  } catch (e) {
    document.getElementById("cycle-status").textContent = "connessione al server interrotta";
  }
}
showSkeleton();
poll();
setInterval(poll, REFRESH_MS);
setInterval(refreshLive, LIVE_REFRESH_MS);
renderTunnel();
setInterval(renderTunnel, 15000);