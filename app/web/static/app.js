"use strict";

const REFRESH_MS = 30000;
const LIVE_REFRESH_MS = 10000;

const state = { data: null, favs: JSON.parse(localStorage.getItem("seriea_favs")||"[]"), filterText: "", filterRound: "", favOnly: false, sortBy: "time" };
const tabs = document.querySelectorAll("#tabs button");
function isFav(team){ return state.favs.includes(team); }
function toggleFav(team){
  const i = state.favs.indexOf(team);
  if(i>=0) state.favs.splice(i,1); else state.favs.push(team);
  localStorage.setItem("seriea_favs", JSON.stringify(state.favs));
  renderActive();
}
function shareText(text){
  if(navigator.share) navigator.share({title:"Serie A Stats", text}).catch(()=>{});
  else if(navigator.clipboard) { navigator.clipboard.writeText(text); alert("Copiato!"); }
  else prompt("Copia:", text);
}

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
    .map(n => `· ${esc(n.title)}`).join("\
");
  return `<div class="kv"><span class="muted">${esc(name)}:</span><b>${esc(m.label)} ${m.score}/10</b></div>
    <div class="ps-mid" style="margin-top:3px">
      <div class="ps-bar"><div class="ps-fill" style="width:${w}%"></div></div>
      <span class="ps-threat">${m.score}/10</span>
    </div>
    ${m.injuries ? `<div class="kv"><span class="muted">Assenti:</span><b>${m.injuries}</b></div>` : ""}
    ${notes ? `<div class="muted" style="font-size:11px;white-space:pre-line;margin-top:4px">💬 Mister:\
${notes}</div>` : ""}`;
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
    html += `<div class="prob-bar" title="Clicca per copiare">
      <div style="width:${p1}%;background:var(--accent); cursor:pointer;" onclick="shareText('Pronostico ${esc(fx.home)}-${esc(fx.away)}: 1 ${p1.toFixed(0)}% X ${px.toFixed(0)}% 2 ${p2.toFixed(0)}%')" title="Condividi">${p1.toFixed(0)}%</div>
      <div style="width:${px}%;background:#6e7681">${px.toFixed(0)}%</div>
      <div style="width:${p2}%;background:var(--alert)">${p2.toFixed(0)}%</div>
    </div>
    <div class="prob-line">
      <span>1: <b>${p1.toFixed(1)}%</b></span>
      <span>X: <b>${px.toFixed(1)}%</b></span>
      <span>2: <b>${p2.toFixed(1)}%</b></span>
      ${lambdas.home_xg != null ? `<span style="margin-left:auto" class="muted">xG: ${lambdas.home_xg.toFixed(2)} - ${lambdas.away_xg ? lambdas.away_xg.toFixed(2) : "?"}</span>` : ""}
    </div>`;
  }

  if (ou.over_2_5 != null || btts.yes != null) {
    html += `<div style="display:flex;gap:12px;margin-top:8px;font-size:12px;flex-wrap:wrap;">`;
    if (ou.over_2_5 != null) {
      const o = (ou.over_2_5 * 100).toFixed(0), u = (ou.under_2_5 * 100).toFixed(0);
      html += `<span class="muted">Over 2.5: <b>${o}%</b> (Under: ${u}%)</span>`;
    }
    if (btts.yes != null) {
      const y = (btts.yes * 100).toFixed(0);
      html += `<span class="muted">Goal/BTTS: <b>${y}%</b></span>`;
    }
    html += `</div>`;
  }

  if (picks.primary_pick) {
    html += `<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">
      <span class="chip v">🎯 ${esc(picks.primary_pick)}</span>
      ${picks.confidence ? `<span class="chip gray">Conf: ${esc(picks.confidence)}</span>` : ""}
      ${picks.risk ? `<span class="chip ${picks.risk === 'BASSO' ? 'v' : (picks.risk === 'ALTO' ? 'alert' : 'warn')}">Rischio: ${esc(picks.risk)}</span>` : ""}
    </div>`;
  }

  if (bets.length) {
    html += `<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">`;
    for (const b of bets.slice(0, 3)) {
      html += `<span class="chip warn" title="Valore atteso / Edge">💡 ${esc(b.market || b.pick)} (@${fmtOdds(b.odds)})</span>`;
    }
    html += `</div>`;
  }

  if (es.length) {
    const top3 = es.slice(0, 3).map(x => `${x.score} (${(x.prob * 100).toFixed(0)}%)`).join(", ");
    html += `<div class="kv" style="margin-top:6px"><span class="muted">Risultati esatti:</span><b>${top3}</b></div>`;
  }

  return html || `<div class="muted">Pronostico in elaborazione...</div>`;
}

function renderMatches() {
  const container = document.getElementById("tab-matches");
  const d = state.data;
  if (!d || !d.fixtures) {
    container.innerHTML = `<div class="card">Nessuna partita trovata.</div>`;
    return;
  }

  const list = d.fixtures.filter(fx => {
    if (state.filterRound && String(fx.round) !== String(state.filterRound)) return false;
    if (state.favOnly && !isFav(fx.home) && !isFav(fx.away)) return false;
    if (state.filterText) {
      const q = state.filterText.toLowerCase();
      const txt = `${fx.home} ${fx.away} ${fx.stadium} ${fx.referee}`.toLowerCase();
      if (!txt.includes(q)) return false;
    }
    return true;
  });

  if (!list.length) {
    container.innerHTML = `<div class="card">Nessuna partita corrisponde ai filtri impostati.</div>`;
    return;
  }

  let html = "";
  for (const fx of list) {
    const isLive = fx.status === "LIVE" || fx.status === "1H" || fx.status === "2H" || fx.status === "HT";
    const isFinished = fx.status === "FT" || fx.status === "AET" || fx.status === "PEN";
    const scoreStr = isLive || isFinished ? `${fx.home_goals ?? 0} - ${fx.away_goals ?? 0}` : "vs";
    const favH = isFav(fx.home) ? "★" : "☆";
    const favA = isFav(fx.away) ? "★" : "☆";

    html += `
      <div class="card" id="match-${fx.id}">
        <div class="match-head">
          <div class="teams">
            <span style="cursor:pointer" onclick="toggleFav('${esc(fx.home)}')" title="Preferito">${favH}</span>
            <span>${esc(fx.home)}</span>
            <span style="color:var(--muted); margin:0 6px; font-weight:400">${scoreStr}</span>
            <span>${esc(fx.away)}</span>
            <span style="cursor:pointer" onclick="toggleFav('${esc(fx.away)}')" title="Preferito">${favA}</span>
          </div>
          <div class="meta">
            ${isLive ? `<span class="live-dot"></span> LIVE ${esc(fx.minute || "")}'` : (isFinished ? "FINITA" : fmtTime(fx.timestamp))}
            · Giornata ${esc(fx.round)}
          </div>
        </div>

        ${fx.stadium ? `<div class="post-chip">🏟️ ${esc(fx.stadium)}${fx.referee ? ` · 🟨 Arbitro: ${esc(fx.referee)}` : ""}</div>` : ""}

        <div class="grid2" style="margin-top:16px">
          <div class="subpanel">
            <h3>${esc(fx.home)} (Casa)</h3>
            ${formBlock(fx, "home")}
            <div style="margin-top:10px">${moraleBlock(fx, "home")}</div>
          </div>
          <div class="subpanel">
            <h3>${esc(fx.away)} (Trasferta)</h3>
            ${formBlock(fx, "away")}
            <div style="margin-top:10px">${moraleBlock(fx, "away")}</div>
          </div>
        </div>

        <div class="subpanel" style="margin-top:12px">
          <h3>🔮 Pronostico & Valore</h3>
          ${predictionBlock(fx)}
        </div>

        <div class="subpanel" style="margin-top:12px">
          <h3>📊 Quote migliori</h3>
          ${oddsTable(fx)}
        </div>

        ${fx.ai_comment ? `<div class="motivation">🤖 ${esc(fx.ai_comment)}</div>` : ""}
      </div>
    `;
  }
  container.innerHTML = html;
}

// ------------------------------------------------------------- results & live
function renderResults() {
  const container = document.getElementById("tab-results");
  const d = state.data;
  if (!d || !d.fixtures) {
    container.innerHTML = `<div class="card">Nessun risultato disponibile.</div>`;
    return;
  }

  const finishedOrLive = d.fixtures.filter(fx => fx.status === "FT" || fx.status === "LIVE" || fx.status === "1H" || fx.status === "2H" || fx.status === "HT");
  if (!finishedOrLive.length) {
    container.innerHTML = `<div class="card">Nessuna partita terminata o in corso in questa giornata.</div>`;
    return;
  }

  let html = `<div class="section-title">Live & Ultime Partite</div>`;
  for (const fx of finishedOrLive) {
    const isLive = fx.status !== "FT";
    html += `
      <div class="card">
        <div class="match-head">
          <div class="teams">${esc(fx.home)} ${fx.home_goals ?? 0} - ${fx.away_goals ?? 0} ${esc(fx.away)}</div>
          <div class="meta">${isLive ? `<span class="live-dot"></span> ${esc(fx.status)} ${fx.minute || ""}'` : "FT"} · G${esc(fx.round)}</div>
        </div>
        ${fx.goal_scorers && fx.goal_scorers.length ? `<div class="muted" style="margin-top:8px;font-size:12px">⚽ ${esc(fx.goal_scorers.join(", "))}</div>` : ""}
      </div>
    `;
  }
  container.innerHTML = html;
}

// ------------------------------------------------------------- standings
function renderStandings() {
  const container = document.getElementById("tab-standings");
  const d = state.data;
  if (!d || !d.standings || !d.standings.length) {
    container.innerHTML = `<div class="card">Classifica non disponibile.</div>`;
    return;
  }

  let html = `
    <div class="card" style="overflow-x:auto">
      <div class="section-title">Classifica Serie A</div>
      <table>
        <thead>
          <tr>
            <th>Pos</th>
            <th>Squadra</th>
            <th>Pt</th>
            <th>G</th>
            <th>V</th>
            <th>N</th>
            <th>P</th>
            <th>GF</th>
            <th>GA</th>
            <th>DR</th>
            <th>Forma</th>
          </tr>
        </thead>
        <tbody>
  `;

  for (const s of d.standings) {
    const dr = s.gf - s.ga;
    const formChips = (s.form || "").split("").map(c => chipFrom(c)).join("");
    html += `
      <tr>
        <td><b>${s.rank}</b></td>
        <td><b>${esc(s.team)}</b></td>
        <td><b>${s.points}</b></td>
        <td>${s.played}</td>
        <td>${s.won}</td>
        <td>${s.drawn}</td>
        <td>${s.lost}</td>
        <td>${s.gf}</td>
        <td>${s.ga}</td>
        <td>${dr > 0 ? `+${dr}` : dr}</td>
        <td><span class="chips">${formChips}</span></td>
      </tr>
    `;
  }
  html += `</tbody></table></div>`;
  container.innerHTML = html;
}

// ------------------------------------------------------------- teams
function renderTeams() {
  const container = document.getElementById("tab-teams");
  const d = state.data;
  if (!d || !d.standings) {
    container.innerHTML = `<div class="card">Dati squadre non disponibili.</div>`;
    return;
  }

  let html = `<div class="grid2">`;
  for (const s of d.standings) {
    html += `
      <div class="card">
        <div class="match-head">
          <div class="teams">${esc(s.team)}</div>
          <div class="meta">${s.points} Punti · ${s.rank}° Posto</div>
        </div>
        <div class="subpanel" style="margin-top:12px">
          <h3>Statistiche Stagionali</h3>
          <div class="kv"><span class="muted">Partite giocate:</span><b>${s.played}</b></div>
          <div class="kv"><span class="muted">Vittorie / Pareggi / Sconfitte:</span><b>${s.won} / ${s.drawn} / ${s.lost}</b></div>
          <div class="kv"><span class="muted">Reti Fatte / Subite:</span><b>${s.gf} / ${s.ga}</b></div>
        </div>
      </div>
    `;
  }
  html += `</div>`;
  container.innerHTML = html;
}

// ------------------------------------------------------------- ai insights
function renderAI() {
  const container = document.getElementById("tab-ai");
  const d = state.data;
  if (!d || !d.fixtures) {
    container.innerHTML = `<div class="card">Nessun insight disponibile.</div>`;
    return;
  }

  let html = `<div class="section-title">Analisi AI & Value Bets Giornata</div>`;
  let count = 0;
  for (const fx of d.fixtures) {
    if (fx.ai_comment || (fx.value_flags && fx.value_flags.length)) {
      count++;
      html += `
        <div class="card">
          <div class="match-head">
            <div class="teams">${esc(fx.home)} vs ${esc(fx.away)}</div>
            <div class="meta">Giornata ${esc(fx.round)}</div>
          </div>
          ${fx.ai_comment ? `<div class="motivation" style="margin-top:12px">🤖 ${esc(fx.ai_comment)}</div>` : ""}
          ${fx.value_flags && fx.value_flags.length ? `
            <div class="subpanel" style="margin-top:12px">
              <h3>⚠ Segnali di Valore / Anomalie Quote</h3>
              ${fx.value_flags.map(f => `<div class="kv"><span>${esc(f.market)} - <b>${esc(f.pick)}</b></span><span class="chip ${f.severity}">${esc(f.kind)}</span></div>`).join("")}
            </div>
          ` : ""}
        </div>
      `;
    }
  }

  if (!count) {
    html += `<div class="card">Nessun insight di rilievo per questa giornata.</div>`;
  }
  container.innerHTML = html;
}

// ------------------------------------------------------------- schedina
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

// ------------------------------------------------------------- tracking (onesta)
const PICK_LABEL = { over_2_5: "over 2.5", under_2_5: "under 2.5", si: "sì", no: "no" };
const MARKET_LABEL = { "1x2": "Risultato 1X2", over_under: "Over/Under 2.5", btts: "Entrambe a segno" };

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

// ------------------------------------------------------------- controls & init
function renderActive() {
  const activeTab = document.querySelector("#tabs button.active");
  const tabId = activeTab ? activeTab.getAttribute("data-tab") : "matches";
  
  document.querySelectorAll(".tab").forEach(el => el.classList.remove("active"));
  const target = document.getElementById(`tab-${tabId}`);
  if (target) target.classList.add("active");

  if (tabId === "matches") renderMatches();
  else if (tabId === "results") renderResults();
  else if (tabId === "standings") renderStandings();
  else if (tabId === "teams") renderTeams();
  else if (tabId === "ai") renderAI();
  else if (tabId === "schedina") renderSchedina();
  else if (tabId === "tracking") renderTracking();
}

function updateRoundsDropdown() {
  const d = state.data;
  const sel = document.getElementById("filter-round");
  if (!d || !d.fixtures) return;

  const rounds = [...new Set(d.fixtures.map(fx => fx.round))].sort((a,b) => Number(a)-Number(b));
  let html = `<option value="">Tutte le giornate</option>`;
  for (const r of rounds) {
    html += `<option value="${esc(r)}"${String(state.filterRound) === String(r) ? " selected" : ""}>Giornata ${esc(r)}</option>`;
  }
  sel.innerHTML = html;
}

async function loadData() {
  try {
    const res = await fetch("/api/state");
    if (!res.ok) throw new Error("Network response was not ok");
    state.data = await res.json();
    renderHeader();
    updateRoundsDropdown();
    renderActive();
  } catch (err) {
    console.error("Failed to load data:", err);
    const cycle = document.getElementById("cycle-status");
    if (cycle) cycle.textContent = "⚠ Errore di connessione";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  tabs.forEach(btn => {
    btn.addEventListener("click", () => {
      tabs.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      renderActive();
    });
  });

  const searchInput = document.getElementById("search");
  if (searchInput) {
    searchInput.addEventListener("input", e => {
      state.filterText = e.target.value.trim();
      renderActive();
    });
  }

  const roundSelect = document.getElementById("filter-round");
  if (roundSelect) {
    roundSelect.addEventListener("change", e => {
      state.filterRound = e.target.value;
      renderActive();
    });
  }

  const favToggle = document.getElementById("fav-toggle");
  if (favToggle) {
    favToggle.addEventListener("click", () => {
      state.favOnly = !state.favOnly;
      favToggle.style.borderColor = state.favOnly ? "var(--accent)" : "";
      renderActive();
    });
  }

  loadData();
  setInterval(loadData, REFRESH_MS);
});
