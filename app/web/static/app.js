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
function toast(msg) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 1800);
}
function shareText(text){
  if(navigator.share) navigator.share({title:"Serie A Stats", text}).catch(()=>{});
  else if(navigator.clipboard) navigator.clipboard.writeText(text).then(() => toast("Pronostico copiato")).catch(()=>{});
  else prompt("Copia:", text);
}

const STAR_SVG = `<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2.6l2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.4l-5.8 3.1 1.1-6.5L2.6 9.4l6.5-.9z"/></svg>`;

function favBtn(team) {
  const on = isFav(team);
  return `<button type="button" class="fav-btn" aria-pressed="${on}" aria-label="Preferito: ${esc(team)}" title="Preferito" onclick="toggleFav('${esc(team)}')">${STAR_SVG}</button>`;
}

function stateBlock(title, hint, retry) {
  return `<div class="state"><div class="state-title">${esc(title)}</div>
    ${hint ? `<div class="state-hint muted">${esc(hint)}</div>` : ""}
    ${retry ? `<button class="cta" onclick="loadData()">Riprova</button>` : ""}</div>`;
}

function teamFormMap() {
  const map = {};
  for (const fx of ((state.data && state.data.fixtures) || [])) {
    const h = (fx.form_home && fx.form_home.last_results) || [];
    const a = (fx.form_away && fx.form_away.last_results) || [];
    if (h.length) map[fx.home] = h;
    if (a.length) map[fx.away] = a;
  }
  return map;
}

function formChips(formArr, n) {
  if (!formArr || !formArr.length) return "";
  return formArr.slice(-n).map(e => chipFrom(resultCharMap(e.result) || "?")).join("");
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
  if (d.last_error) cycle.textContent = `Errore dati: ${d.last_error}`;
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

  const spreads = new Map();
  for (const f of fx.value_flags || []) {
    if (f.kind === "spread") spreads.set(`${f.market}|${f.pick}`, f);
  }

  let html = "";
  for (const m of markets) {
    html += `<div class="odds-market">${esc(m)}</div>`;
    for (const o of groups[m]) {
      const flag = spreads.get(`${m}|${o.pick}`);
      const sev = flag ? (flag.severity === "alert" ? "sev-alert" : "sev-warn") : "";
      const title = flag ? ` title="Segnale di valore: ${esc(flag.kind)}"` : "";
      html += `<div class="odds-row"><span>${esc(o.pick)}</span>
        <span class="val ${sev}"${title}><span class="source-pill">${esc(o.source)}</span>${fmtOdds(o.odds)}</span></div>`;
    }
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
  return `<div class="kv"><span class="muted">${esc(name)}:</span><b>${esc(m.label)}</b></div>
    <div class="ps-mid" style="margin-top:3px">
      <div class="ps-bar"><div class="ps-fill" style="width:${w}%"></div></div>
      <span class="ps-threat">${m.score}/10</span>
    </div>
    ${m.injuries ? `<div class="kv"><span class="muted">Assenti:</span><b>${m.injuries}</b></div>` : ""}
    ${notes ? `<div class="coach-note muted">Mister: ${notes}</div>` : ""}`;
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
  const es = p.exact_score || [];

  let html = "";
  if (Object.keys(prob).length) {
    const p1 = (prob["1"] * 100) || 0, px = (prob["x"] * 100) || 0, p2 = (prob["2"] * 100) || 0;
    html += `<div class="prob-bar" title="Clicca su «1» per condividere">
      <div style="width:${p1}%;background:var(--accent); cursor:pointer;" onclick="shareText('Pronostico ${esc(fx.home)}-${esc(fx.away)}: 1 ${p1.toFixed(0)}% X ${px.toFixed(0)}% 2 ${p2.toFixed(0)}%')" title="Condividi">${p1.toFixed(0)}%</div>
      <div style="width:${px}%;background:var(--prob-x)">${px.toFixed(0)}%</div>
      <div style="width:${p2}%;background:var(--prob-2)">${p2.toFixed(0)}%</div>
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

  if (bets.length) {
    html += `<div class="chip-row">`;
    for (const b of bets.slice(0, 3)) {
      html += `<span class="chip warn" title="Quota segnalata dal modello">${esc(b.market || b.pick)} (@${fmtOdds(b.odds)})</span>`;
    }
    html += `</div>`;
  }

  if (es.length) {
    const top3 = es.slice(0, 3).map(x => `${x.score} (${(x.prob * 100).toFixed(0)}%)`).join(", ");
    html += `<div class="kv tight"><span class="muted">Risultati esatti:</span><b>${top3}</b></div>`;
  }

  return html || `<div class="muted">Pronostico in elaborazione...</div>`;
}

function renderMatches() {
  const container = document.getElementById("tab-matches");
  const d = state.data;
  if (!d || !d.fixtures) {
    container.innerHTML = stateBlock("Nessuna partita disponibile", "I dati della giornata non sono ancora arrivati dal server.");
    return;
  }

  const list = d.fixtures.filter(fx => {
    if (state.filterRound && String(fx.round) !== String(state.filterRound)) return false;
    if (state.favOnly && !isFav(fx.home) && !isFav(fx.away)) return false;
    if (state.filterText) {
      const q = state.filterText.toLowerCase();
      const coach = fx.coach || {};
      const txt = `${fx.home} ${fx.away} ${fx.venue || ""} ${coach.home || ""} ${coach.away || ""}`.toLowerCase();
      if (!txt.includes(q)) return false;
    }
    return true;
  });

  if (!list.length) {
    container.innerHTML = stateBlock("Nessuna partita corrisponde ai filtri", "Prova a cambiare ricerca o giornata, oppure disattiva i preferiti.");
    return;
  }

  if (state.sortBy === "round") list.sort((a, b) => Number(a.round) - Number(b.round) || (a.start_ts || 0) - (b.start_ts || 0));
  else list.sort((a, b) => (a.start_ts || 0) - (b.start_ts || 0));

  let html = "";
  for (const fx of list) {
    const isLive = fx.status === "LIVE" || fx.status === "1H" || fx.status === "2H" || fx.status === "HT";
    const isFinished = fx.status === "FT" || fx.status === "AET" || fx.status === "PEN";
    const scoreStr = isLive || isFinished ? `${fx.home_goals ?? 0} - ${fx.away_goals ?? 0}` : "vs";

    html += `
      <div class="card" id="match-${fx.id}">
        <div class="match-head">
          <div class="teams">
            ${favBtn(fx.home)}
            <span>${esc(fx.home)}</span>
            <span class="vs${scoreStr === "vs" ? "" : " score"}">${scoreStr}</span>
            <span>${esc(fx.away)}</span>
            ${favBtn(fx.away)}
          </div>
          <div class="meta">
            ${isLive ? `<span class="live-dot is-live"></span> LIVE ${esc(fx.minute || "")}'` : (isFinished ? "FINITA" : fmtTime(fx.start_ts || fx.timestamp))}
            · Giornata ${esc(fx.round)}
          </div>
        </div>

        ${fx.venue ? `<div class="post-chip">${esc(fx.venue)}</div>` : ""}

        <div class="grid2 match-body">
          <div class="subpanel">
            <h3>${esc(fx.home)} (Casa)</h3>
            ${formBlock(fx, "home")}
            <div class="sp-gap">${moraleBlock(fx, "home")}</div>
          </div>
          <div class="subpanel">
            <h3>${esc(fx.away)} (Trasferta)</h3>
            ${formBlock(fx, "away")}
            <div class="sp-gap">${moraleBlock(fx, "away")}</div>
          </div>
        </div>

        <div class="subpanel">
          <h3>Pronostico &amp; valore</h3>
          ${predictionBlock(fx)}
        </div>

        <div class="subpanel">
          <h3>Quote migliori</h3>
          ${oddsTable(fx)}
        </div>

        ${fx.ai_comment ? `<div class="motivation">${esc(fx.ai_comment)}</div>` : ""}
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
    container.innerHTML = stateBlock("Nessun risultato disponibile", "I risultati appaiono qui appena una partita va in diretta o termina.");
    return;
  }

  const finishedOrLive = d.fixtures.filter(fx => fx.status === "FT" || fx.status === "LIVE" || fx.status === "1H" || fx.status === "2H" || fx.status === "HT");
  if (!finishedOrLive.length) {
    container.innerHTML = stateBlock("Nessuna partita terminata o in corso", "Quando la giornata parte i live e i risultati compariranno qui.");
    return;
  }

  let html = `<div class="section-title">Live & Ultime Partite</div>`;
  for (const fx of finishedOrLive) {
    const isLive = fx.status !== "FT";
    html += `
      <div class="card">
        <div class="match-head">
          <div class="teams">${esc(fx.home)} ${fx.home_goals ?? 0} - ${fx.away_goals ?? 0} ${esc(fx.away)}</div>
          <div class="meta">${isLive ? `<span class="live-dot is-live"></span> ${esc(fx.status)} ${fx.minute || ""}'` : "FT"} · G${esc(fx.round)}</div>
        </div>
        ${fx.goal_scorers && fx.goal_scorers.length ? `<div class="muted tight" style="font-size:12px">Marcatori: ${esc(fx.goal_scorers.join(", "))}</div>` : ""}
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
    container.innerHTML = stateBlock("Classifica non disponibile", "La classifica appare non appena arrivano i dati della giornata.");
    return;
  }

  const forms = teamFormMap();
  const hasForm = d.standings.some(s => (forms[s.name] || []).length);

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
            ${hasForm ? "<th>Forma</th>" : ""}
          </tr>
        </thead>
        <tbody>
  `;

  for (const s of d.standings) {
    const dr = (s.gf || 0) - (s.ga || 0);
    html += `
      <tr>
        <td><b>${s.position}</b></td>
        <td><b>${esc(s.name)}</b></td>
        <td><b>${s.points}</b></td>
        <td>${s.played}</td>
        <td>${s.wins}</td>
        <td>${s.draws}</td>
        <td>${s.losses}</td>
        <td>${s.gf}</td>
        <td>${s.ga}</td>
        <td>${dr > 0 ? `+${dr}` : dr}</td>
        ${hasForm ? `<td><span class="chips">${formChips(forms[s.name], 5) || "—"}</span></td>` : ""}
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
  if (!d || !d.standings || !d.standings.length) {
    container.innerHTML = stateBlock("Dati squadre non disponibili", "Le schede squadra arrivano insieme alla classifica.");
    return;
  }

  let html = `<div class="grid2">`;
  for (const s of d.standings) {
    html += `
      <div class="card">
        <div class="match-head">
          <div class="teams">${esc(s.name)}</div>
          <div class="meta">${s.points} Punti · ${s.position}° Posto</div>
        </div>
        <div class="subpanel">
          <h3>Statistiche stagionali</h3>
          <div class="kv"><span class="muted">Partite giocate:</span><b>${s.played}</b></div>
          <div class="kv"><span class="muted">Vittorie / Pareggi / Sconfitte:</span><b>${s.wins} / ${s.draws} / ${s.losses}</b></div>
          <div class="kv"><span class="muted">Reti fatte / subite:</span><b>${s.gf} / ${s.ga}</b></div>
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
    container.innerHTML = stateBlock("Nessun insight disponibile", "Le analisi AI arrivano quando ci sono commenti o segnali di valore.");
    return;
  }

  let html = `<div class="section-title">Analisi AI &amp; value bet della giornata</div>`;
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
          ${fx.ai_comment ? `<div class="motivation">${esc(fx.ai_comment)}</div>` : ""}
          ${fx.value_flags && fx.value_flags.length ? `
            <div class="subpanel">
              <h3>Segnali di valore / anomalie quote</h3>
              ${fx.value_flags.map(f => `<div class="kv"><span>${esc(f.market)} - <b>${esc(f.pick)}</b></span><span class="chip ${f.severity}">${esc(f.kind)}</span></div>`).join("")}
            </div>
          ` : ""}
        </div>
      `;
    }
  }

  if (!count) {
    html += stateBlock("Nessun insight di rilievo", "Per questa giornata il modello non ha segnalato value bet o commenti particolari.");
  }
  container.innerHTML = html;
}

// ------------------------------------------------------------- schedina
function pickRow(p) {
  const st = p.result === "win" ? `<span class="chip v">vinta</span>`
    : p.result === "loss" ? `<span class="chip alert">persa</span>`
    : `<span class="chip gray">in attesa</span>`;
  const pct = ((p.prob || 0) * 100).toFixed(0) + "%";
  const score = p.score ? ` · ${esc(p.score)}` : "";
  const lbl = ({1: "1", x: "X", 2: "2", "over_2.5": "Over 2.5",
                "under_2.5": "Under 2.5", si: "BTTS Sì", no: "BTTS No"})[p.pick] || p.pick;
  return `<div class="card"><div class="kv"><span>${esc(p.home)} - ${esc(p.away)}${score}</span>${st}</div>
      <div class="muted">${esc(lbl)} @ ${fmtOdds(p.odds)} · prob. ${pct}${p.edge != null ? " · edge " + (p.edge * 100).toFixed(0) + "%" : ""}</div></div>`;
}

function renderSchedina() {
  const el = document.getElementById("tab-schedina");
  const s = state.data.schedina || {};
  if (!s.round || !s.picks || !s.picks.length) {
    el.innerHTML = `<div class="section-title">Schedina della giornata</div>
      ${stateBlock("Nessuna schedina disponibile", "La schedina viene creata prima della prima partita della giornata con gli esiti più probabili del modello.")}`;
    return;
  }
  const won = s.picks.filter(p => p.result === "win").length;
  const lost = s.picks.filter(p => p.result === "loss").length;
  const rows = s.picks.map(pickRow).join("");
  const hist = (s.history || []).slice().reverse().map(h =>
    `<div class="card history-card" role="button" tabindex="0" onclick="this.classList.toggle('open')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.classList.toggle('open')}">
       <div class="kv"><span>Giornata ${h.round}</span>
       <span class="muted">${h.wins} vinti · ${h.losses} persi<span class="caret" aria-hidden="true">▾</span></span></div>
       <div class="history-picks">${(h.picks || []).map(pickRow).join("")}</div>
     </div>`).join("");
  el.innerHTML = `<div class="section-title">Schedina della giornata ${s.round || "?"}</div>
    <div class="grid3">
      <div class="card"><div class="big-num">${won}/${s.picks.length}</div>
        <div class="muted">eventi vinti</div></div>
      <div class="card"><div class="big-num">${lost}/${s.picks.length}</div>
        <div class="muted">eventi persi</div></div>
      <div class="card"><div class="big-num">${s.picks.length}</div>
        <div class="muted">esiti totali</div></div>
    </div>${rows}
    ${hist ? `<div class="section-title section-gap">Schedine passate</div>${hist}` : ""}`;
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
  const pRate = t.picks_rate != null ? (t.picks_rate * 100).toFixed(0) + "%" : "—";
  const bCls = t.bets_rate >= 0.5 ? "v" : "warn";

  let html = `<div class="section-title">Onestà del modello · quanto i pronostici diventano realtà</div>
    <div class="grid3">
      <div class="card"><div class="big-num">${t.evaluated || 0}</div>
        <div class="muted">partite valutate a fine gara</div></div>
      <div class="card"><div class="big-num">${t.picks_hit || 0}/${t.picks_total || 0}</div>
        <div class="muted">pronostici del modello centrati (${pRate})</div></div>
      <div class="card"><div class="big-num">${brier}</div>
        <div class="muted">Brier score · più basso = più onesto</div></div>
    </div>
    <div id="hit-detail"></div>`;

  // pronostici per mercato: il voto vero del modello (un pick per mercato)
  const pbm = t.picks_by_market || {};
  if (Object.values(pbm).some(st => st.picks_total)) {
    html += `<div class="card"><div class="section-title st-flush">Pronostici del modello per mercato</div>`;
    for (const [m, st] of Object.entries(pbm)) {
      if (!st.picks_total) continue;
      const cls = st.picks_rate >= 0.5 ? "v" : "warn";
      html += `<div class="kv"><span class="muted kv-label">${MARKET_LABEL[m] || m}</span>
        <span class="chip ${cls}">${st.picks_hit}/${st.picks_total} (${(st.picks_rate * 100).toFixed(0)}%)</span></div>`;
    }
    html += `<div class="muted tight">Un pronostico per mercato su ogni partita valutata: è il risultato che conta.</div></div>`;
  }

  // best-bet: la scommessa consigliata con quota (quote alte → hit basso)
  if (t.bets_total) {
    html += `<div class="card hit-card" role="button" tabindex="0" onclick="toggleHits(this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();toggleHits(this)}"><div class="kv">
        <span class="muted kv-label">Best-bet suggeriti (scommesse con quota)</span>
        <span class="chip ${bCls}">${t.bets_hit || 0}/${t.bets_total} (${rate})</span></div>
      <div class="muted tight">Quote alte (1.1–6.5): qui conta più il ROI della percentuale · clicca per i dettagli</div></div>`;
  }

  // conteggio per PARTITA (una partita può avere più best-bet/vincere in + mercati)
  if (t.match_bets_total) {
    const mRate = t.match_bets_rate != null ? (t.match_bets_rate * 100).toFixed(0) + "%" : "—";
    const mCls = t.match_bets_rate >= 0.5 ? "v" : "warn";
    html += `<div class="card"><div class="kv">
        <span class="muted kv-label">Partite con best-bet vinto</span>
        <span class="chip ${mCls}">${t.match_bets_hit || 0}/${t.match_bets_total} (${mRate})</span></div>
      <div class="muted tight">Conteggio per partita: azzeccata quando almeno un best-bet è stato centrato (il totale qui sopra è per singolo best-bet).</div></div>`;
  }

  const bins = t.calibration_bins || [];
  // calibrazione: predetto vs reale a fasce
  if (bins.some(b => b.count > 0)) {
    html += `<div class="card"><div class="section-title st-flush">Calibrazione: che probabilità do vs cosa succede davvero</div>
      <div class="hrow">`;
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
    html += `</div><div class="muted tight">Barra <span style="color:var(--accent)">verde</span> = probabilità dichiarata,
      barra <span style="color:var(--alert)">rossa</span> = centratura reale. Se la rossa è più corta della verde, ero troppo ottimista.</div></div>`;
  }

  // correttori appresi
  const withCal = Object.keys(MARKET_LABEL).filter(m => cal[m] && Object.keys(cal[m]).length);
  if (withCal.length) {
    html += `<div class="card"><div class="section-title st-flush">Cosa ho imparato (correttori attivi)</div>`;
    for (const m of withCal) {
      html += `<div class="kv"><span class="muted kv-label">${MARKET_LABEL[m]}</span>`;
      for (const [k, f] of Object.entries(cal[m])) {
        const bad = f > 1 ? "v" : f < 1 ? "warn" : "gray";
        html += `<span class="chip ${bad}" title="probabilità reale / probabilità stimata">${pickLabel(m, k)} ×${f}</span>`;
      }
      html += `</div>`;
    }
    html += `<div class="muted tight">Le probabilità dei prossimi pronostici vengono moltiplicate per questi fattori (poi rinormalizzate).</div></div>`;
  }

  // fuori campione: backtest walk-forward (solo round precedenti)
  const oos = t.oos || {};
  const oosPicks = (oos.check || {}).picks || {};
  if (oos.brier_calibrated != null && oos.brier != null && oos.records >= 2) {
    const imp = oos.improvement != null ? `${oos.improvement >= 0 ? "+" : ""}${oos.improvement.toFixed(3)}` : "—";
    const arrow = oos.reliable ? "↘" : "↗";
    html += `<div class="card"><div class="section-title st-flush">Fuori campione · vale anche senza vedere il futuro</div>
      <div class="grid3">
        <div class="stat"><div class="big-num">${oos.brier.toFixed(3)}</div>
          <div class="muted">Brier as-pubblicato</div></div>
        <div class="stat"><div class="big-num">${oos.brier_calibrated.toFixed(3)}</div>
          <div class="muted">Brier ri-calibrato OOS ${arrow}</div></div>
        <div class="stat"><div class="big-num">${imp}</div>
          <div class="muted">miglioramento (negativo = più onesto)</div></div>
      </div>`;
    if (oos.rps != null) {
      const rc = oos.rps_calibrated != null ? oos.rps_calibrated : oos.rps;
      html += `<div class="kv tight"><span class="muted">RPS 1X2 (ordinale) OOS</span>
        <span class="chip">${oos.rps.toFixed(3)} → ${rc.toFixed(3)}</span></div>`;
    }
    if (oos.ci95) {
      const sig = oos.significant ? "significativo" : "non conclusivo";
      html += `<div class="kv tight"><span class="muted">CI95 miglioramento (bootstrap)</span>
        <span class="chip ${oos.significant ? "v" : "warn"}">${oos.ci95.lo >= 0 ? "+" : ""}${oos.ci95.lo.toFixed(3)}…${(oos.ci95.hi >= 0 ? "+" : "") + oos.ci95.hi.toFixed(3)} · p_better ${oos.ci95.p_better.toFixed(2)} · ${sig}</span></div>`;
    }
    if (oosPicks.total) {
      html += `<div class="kv tight"><span class="muted">Pronostici del modello OOS</span>
        <span class="chip ${oosPicks.rate >= 0.5 ? "v" : "warn"}">${oosPicks.hit}/${oosPicks.total} (${(oosPicks.rate * 100).toFixed(0)}%)</span></div>`;
    }
    html += `<div class="muted tight">La calibrazione in produzione usa solo i round già finiti: nessuna fuga di dati avanti.</div></div>`;
  }

  // errori clamorosi
  const misses = t.notable_misses || [];
  if (misses.length) {
    html += `<div class="card"><div class="section-title st-flush">Dove ho sbagliato di più</div>`;
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
    html += `<div class="card"><div class="section-title st-flush">Riepilogo</div><ul>`;
    for (const c of lessons) html += `<li>${esc(c)}</li>`;
    html += `</ul></div>`;
  }

  if (!lessons.length && !bins.length) {
    html = `<div class="section-title">Onestà del modello</div>
      ${stateBlock("Ancora nessun pronostico valutato", "Quando le prossime partite finir confronto pronostico vs risultato reale qui, mostro il tasso di centratura e correggo il modello.")}`;
  }
  el.innerHTML = html;
}

let hitsLoaded = false;

async function toggleHits(card) {
  card.classList.toggle("open");
  const box = document.getElementById("hit-detail");
  const wantOpen = card.classList.contains("open");
  box.innerHTML = wantOpen ? `<div class="muted">Carico i best-bet…</div>` : "";
  if (!wantOpen || hitsLoaded) return;
  hitsLoaded = true;
  try {
    const r = await fetch("/api/tracking-records");
    const data = await r.json();
    const rows = [];
    for (const rec of data.records || []) {
      for (const h of rec.hits || []) {
        if (h.model) continue; // solo i best-bet, non i pick del modello
        rows.push({ ...h, home: rec.home, away: rec.away, score: rec.score, round: rec.round });
      }
    }
    if (!rows.length) {
      box.innerHTML = `<div class="card muted">Nessun best-bet registrato.</div>`;
      return;
    }
    const wins = rows.filter(x => x.hit).length;
    box.innerHTML = `<div class="card"><div class="section-title st-flush">Best-bet suggeriti (${wins}/${rows.length} centrati)</div>` +
      rows.map(h => `<div class="kv"><span><b>${esc(h.home)} - ${esc(h.away)}</b>
        <span class="muted">(${esc(h.score)} · gj ${esc(h.round || "?")})</span></span>
        <span><span class="chip ${h.hit ? "v" : "warn"}">${h.hit ? "✓" : "✗"} ${pickLabel(h.market, h.pick)}</span>
        prob ${((h.prob || 0) * 100).toFixed(0)}% @ ${fmtOdds(h.odds)}</span></div>`).join("") +
      `</div>`;
  } catch (e) {
    box.innerHTML = `<div class="card muted">Errore nel caricamento dei dettagli.</div>`;
  }
}

// ------------------------------------------------------------- community
const CM_MARKETS = [
  { market: "1x2", label: "Risultato", options: [["1", "1"], ["x", "X"], ["2", "2"]] },
  { market: "over_under", label: "Gol", options: [["over_2.5", "Over 2.5"], ["under_2.5", "Under 2.5"]] },
  { market: "btts", label: "Reti", options: [["si", "Sì"], ["no", "No"]] },
];
let cmState = null;
let cmDraft = {};
let cmFetching = false;
let cmError = false;

function cmPickLabel(market, pick) {
  const mk = CM_MARKETS.find(m => m.market === market);
  const opt = mk && mk.options.find(o => o[0] === pick);
  return opt ? opt[1] : pick;
}

async function refreshCommunity() {
  try {
    const res = await fetch("/api/community");
    if (!res.ok) throw new Error("community fetch failed");
    cmState = await res.json();
    cmError = false;
  } catch (err) {
    console.error("community:", err);
    cmError = true;
  }
  renderCommunity();
}

async function submitCommunity() {
  const picks = Object.keys(cmDraft).map(fid => ({
    fixture_id: fid, market: cmDraft[fid].market, pick: cmDraft[fid].pick,
  }));
  if (!picks.length) return;
  const btn = document.getElementById("cm-submit");
  if (btn) { btn.disabled = true; btn.textContent = "Invio…"; }
  try {
    const res = await fetch("/api/community", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ round: cmState && cmState.round, picks }),
    });
    cmDraft = {};
    if (!res.ok && res.status !== 409) {
      const err = await res.json().catch(() => ({}));
      console.error("community submit:", err);
    }
  } catch (err) {
    console.error("community submit:", err);
  }
  await refreshCommunity();
}

async function renderCommunity() {
  const el = document.getElementById("tab-community");
  if (!el) return;
  if (!cmState) {
    if (cmError) {
      el.innerHTML = `<div class="section-title">Schedina community</div>
        ${stateBlock("Errore di caricamento", "Non riesco a caricare la schedina community. Riprova.", true)}`;
      return;
    }
    el.innerHTML = `<div class="section-title">Schedina community</div>${renderSkeleton()}`;
    if (!cmFetching) {
      cmFetching = true;
      refreshCommunity().finally(() => { cmFetching = false; });
    }
    return;
  }
  const d = cmState;
  if (!d.round || !d.fixtures || !d.fixtures.length) {
    el.innerHTML = `<div class="section-title">Schedina community</div>
      ${stateBlock("Nessuna schedina aperta", "La schedina community si apre con le partite della giornata: scegli un esito per partita (1X2, Over/Under 2.5 o BTTS) e inviala. Una sola schedina per giornata.")}`;
    return;
  }
  const mine = d.my;
  const myByFid = {};
  (mine ? mine.picks || [] : []).forEach(p => { myByFid[p.fixture_id] = p; });
  const wins = mine ? mine.picks.filter(p => p.result === "win").length : 0;
  const losses = mine ? mine.picks.filter(p => p.result === "loss").length : 0;
  const pending = mine ? mine.picks.filter(p => !p.result).length : 0;
  const draftN = Object.keys(cmDraft).length;

  const cards = d.fixtures.map(fx => {
    const ag = d.aggregates[fx.id] || {};
    const my = myByFid[fx.id];
    let badge = "";
    if (my) {
      const cls = my.result === "win" ? "chip v" : my.result === "loss" ? "chip p" : "chip gray";
      const res = my.result === "win" ? `${my.score} ✅` : my.result === "loss" ? `${my.score} ❌` : "⏳";
      badge = `<span class="${cls}">${cmPickLabel(my.market, my.pick)} ${esc(res)}</span>`;
    }
    const groups = CM_MARKETS.map(mk => {
      const opts = mk.options.map(([pk, lbl]) => {
        const n = ((ag[mk.market] || {})[pk]) || 0;
        const on = my
          ? my.market === mk.market && my.pick === pk
          : cmDraft[fx.id] && cmDraft[fx.id].market === mk.market && cmDraft[fx.id].pick === pk;
        const dis = mine ? "disabled" : "";
        return `<button type="button" class="cm-opt${on ? " on" : ""}" ${dis}
          data-fid="${esc(fx.id)}" data-m="${esc(mk.market)}" data-p="${esc(pk)}"
          aria-pressed="${on ? "true" : "false"}">${lbl}${n ? `<span class="n">${n}</span>` : ""}</button>`;
      }).join("");
      return `<div class="cm-group"><span class="cm-group-label">${mk.label}</span>${opts}</div>`;
    }).join("");
    return `<div class="card"><div class="kv"><b>${esc(fx.home)} - ${esc(fx.away)}</b>${badge}</div>
      <div class="cm-groups">${groups}</div></div>`;
  }).join("");

  const stats = mine
    ? `<div class="grid3">
        <div class="card"><div class="big-num">${d.participants}</div><div class="muted">partecipanti</div></div>
        <div class="card"><div class="big-num">${mine.picks.length}</div><div class="muted">i tuoi esiti</div></div>
        <div class="card"><div class="big-num">${wins}/${mine.picks.length}</div><div class="muted">vinti · ${losses} persi${pending ? " · " + pending + " pending" : ""}</div></div>
      </div>`
    : `<div class="grid3">
        <div class="card"><div class="big-num">${d.participants}</div><div class="muted">partecipanti</div></div>
        <div class="card"><div class="big-num">${draftN}/${d.fixtures.length}</div><div class="muted">esiti scelti</div></div>
        <div class="card"><div class="big-num">1</div><div class="muted">schedina per giornata</div></div>
      </div>`;

  const action = mine
    ? `<div class="cm-sent">✅ Schedina inviata per la giornata ${esc(String(d.round))} — i risultati si aggiornano a fine partite. Non puoi modificarla.</div>`
    : `<button type="button" class="cm-submit" id="cm-submit" ${draftN ? "" : "disabled"}>
        ✅ Invia schedina${draftN ? ` (${draftN} esiti)` : ""}</button>
       <div class="muted" style="margin-top:8px">Scegli almeno un esito. Una sola schedina per giornata.</div>`;

  el.innerHTML = `<div class="section-title">👥 Schedina community — giornata ${esc(String(d.round))}</div>
    ${stats}${action}${cards}`;

  if (!mine) {
    el.querySelectorAll(".cm-opt").forEach(btn => {
      btn.addEventListener("click", () => {
        const fid = btn.getAttribute("data-fid");
        const m = btn.getAttribute("data-m");
        const p = btn.getAttribute("data-p");
        if (cmDraft[fid] && cmDraft[fid].market === m && cmDraft[fid].pick === p) {
          delete cmDraft[fid];
        } else {
          cmDraft[fid] = { market: m, pick: p };
        }
        renderCommunity();
      });
    });
    const submitBtn = document.getElementById("cm-submit");
    if (submitBtn) submitBtn.addEventListener("click", submitCommunity);
  }
}

// ------------------------------------------------------------------- fanta
let fantaCode = localStorage.getItem("fanta_code") || "";
let fantaSquad = null;
let fantaReport = null;
let fantaSuggest = null;
let fantaErr = "";
let fantaBusy = false;
let fantaAcTimer = null;
let fantaAcHits = [];

const FANTA_MODULI = ["4-3-3", "4-4-2", "3-5-2", "4-2-3-1", "3-4-3"];
const FANTA_ROLE = { P: "Portiere", D: "Difensore", C: "Centrocampista", A: "Attaccante" };

async function fantaLoadSquad() {
  if (!fantaCode) { fantaSquad = null; return; }
  fantaErr = "";
  try {
    const res = await fetch(`/api/fanta/squad?code=${encodeURIComponent(fantaCode)}`);
    if (!res.ok) {
      fantaErr = ((await res.json()).error) || "errore";
      fantaSquad = null;
      return;
    }
    fantaSquad = await res.json();
  } catch (e) {
    fantaErr = "rete";
    fantaSquad = null;
  }
}

async function fantaSave(patch) {
  if (!fantaSquad) return false;
  try {
    const res = await fetch("/api/fanta/squad", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: fantaCode, ...patch }),
    });
    if (res.ok) {
      const j = await res.json();
      if (patch.rosa !== undefined) fantaSquad.rosa = patch.rosa;
      fantaSquad.modulo = j.modulo;
      fantaSquad.mod_dif = j.mod_dif;
      fantaSquad.xi = j.xi;
      toast("Salvato ✓");
      return true;
    }
    toast("Salvataggio fallito");
    return false;
  } catch (e) {
    toast("Errore di rete");
    return false;
  }
}

function fantaCard(title, res) {
  const rows = (res.xi || []).map(r => {
    const arrow = r.trend === "up" ? "↑" : r.trend === "down" ? "↓" : "→";
    const flags = (r.injured ? " 🚑" : "") + (r.mod_note ? " 🛡" : "");
    const tit = r.tit !== null && r.tit !== undefined ? ` <span class="muted">· tit ${r.tit}%</span>` : "";
    return `<div class="kv"><span>${esc(r.role)} <b>${esc(r.name)}</b><span class="muted"> · ${esc(r.team || "")}</span>${tit}</span><span><b>${r.score}</b> ${arrow}${flags}</span></div>`;
  }).join("");
  return `<div class="card"><div class="kv"><b>${esc(title)}</b><span class="chip">modulo ${esc(res.modulo)}${res.mod_dif ? " · mod dif" : ""}</span></div>
    ${rows || '<div class="muted">Nessun giocatore.</div>'}
    <div class="kv" style="margin-top:8px"><b>Media ponderata: ${res.total}</b><span class="chip">${esc(res.label || "")}</span></div></div>`;
}

async function fantaLink() {
  const inp = document.getElementById("fanta-code-in");
  const code = ((inp && inp.value) || "").trim().toLowerCase();
  if (!code) { toast("Scrivi un codice"); return; }
  const prev = fantaCode;
  fantaCode = code;
  fantaSquad = null;
  fantaErr = "";
  await fantaLoadSquad();
  if (fantaSquad) {
    localStorage.setItem("fanta_code", code);
    fantaReport = null;
    fantaSuggest = null;
    toast("Rosa collegata ✓");
  } else {
    fantaCode = prev;
    toast("Codice non trovato");
  }
  renderFanta();
}

async function fantaRun(kind) {
  if (fantaBusy || !fantaCode) return;
  fantaBusy = true;
  renderFanta();
  try {
    const res = await fetch(`/api/fanta/${kind}?code=${encodeURIComponent(fantaCode)}`);
    const data = await res.json();
    if (kind === "report") fantaReport = data;
    else fantaSuggest = data;
  } catch (e) {
    if (kind === "report") fantaReport = { error: "errore di rete" };
    else fantaSuggest = { error: "errore di rete" };
  }
  fantaBusy = false;
  renderFanta();
}

function fantaAcRender(hits) {
  const box = document.getElementById("fanta-ac");
  if (!box) return;
  fantaAcHits = hits || [];
  if (!fantaAcHits.length) { box.hidden = true; box.innerHTML = ""; return; }
  box.innerHTML = fantaAcHits.map((p, i) =>
    `<button type="button" data-i="${i}">${esc(p.name)} · ${esc(p.team)} [${esc(p.role)}]</button>`).join("");
  box.hidden = false;
  box.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => {
      const p = fantaAcHits[Number(btn.getAttribute("data-i"))];
      if (!p) return;
      const rosa = fantaSquad.rosa || [];
      if (rosa.some(x => Number(x.id) === Number(p.id))) { toast("Già in rosa"); return; }
      rosa.push(p);
      fantaSave({ rosa });
      const add = document.getElementById("fanta-add");
      if (add) add.value = "";
      box.hidden = true;
      renderFanta();
    });
  });
}

async function renderFanta() {
  const el = document.getElementById("tab-fanta");
  if (!el) return;

  if (!fantaCode) {
    el.innerHTML = `<div class="section-title">⚽ Fanta — fantacalcio con voto reale</div>
      ${stateBlock("Collega la tua rosa", "Crea la rosa e il codice dal bot Telegram (menu ⚽ Fanta → 🔑 Codice), poi inseriscilo qui per vedere la rosa, valutare la formazione e scoprire la consigliata.")}
      <div class="card">
        <div class="kv"><b>Codice personale</b><span class="muted">3-12 caratteri</span></div>
        <div class="fanta-link-row">
          <input id="fanta-code-in" type="text" maxlength="12" placeholder="es. miofanta1" autocomplete="off" style="padding-left:12px">
          <button id="fanta-link" class="cta">Collega</button>
        </div>
      </div>`;
    document.getElementById("fanta-link").addEventListener("click", fantaLink);
    document.getElementById("fanta-code-in").addEventListener("keydown", e => { if (e.key === "Enter") fantaLink(); });
    return;
  }

  if (!fantaSquad && !fantaErr) {
    el.innerHTML = `<div class="section-title">⚽ Fanta</div>${renderSkeleton()}`;
    await fantaLoadSquad();
    renderFanta();
    return;
  }

  if (fantaErr) {
    el.innerHTML = `<div class="section-title">⚽ Fanta</div>
      ${stateBlock("Codice non valido", `Il codice «${fantaCode}» non è stato trovato. Controllalo sul bot o chiedine uno nuovo.`)}`;
    const btn = el.querySelector(".cta");
    if (btn) btn.addEventListener("click", () => {
      localStorage.removeItem("fanta_code");
      fantaCode = ""; fantaSquad = null; fantaErr = "";
      renderFanta();
    });
    return;
  }

  const s = fantaSquad;
  const rosa = s.rosa || [];
  const byId = {};
  rosa.forEach(p => { byId[p.id] = p; });
  const xiRoles = {};
  (s.xi || []).forEach(pid => {
    const p = byId[pid];
    if (p) (xiRoles[p.role] = xiRoles[p.role] || []).push(p);
  });

  const rosaHtml = rosa.length
    ? rosa.map(p => `<span class="chip">${esc(p.name)}<span class="muted"> · ${esc(p.team)}</span> [${esc(p.role)}]<button type="button" class="fanta-rm" data-pid="${esc(String(p.id))}" aria-label="Rimuovi ${esc(p.name)}">×</button></span>`).join("")
    : `<div class="muted">Rosa vuota: cerca un giocatore qui sotto e aggiungilo.</div>`;

  const xiHtml = (s.xi || []).length
    ? Object.keys(xiRoles).map(r => `<div style="margin:2px 0"><b>${FANTA_ROLE[r] || esc(r)}:</b> ${xiRoles[r].map(p => esc(p.name)).join(", ")}</div>`).join("")
    : `<div class="muted">Nessuna formazione scelta: la valutazione usa il miglior XI automatico. Per scegliere gli 11 titolari usa il bot (⚔️ Formazione titolare).</div>`;

  const blocks = [];
  if (fantaReport && fantaReport.error) blocks.push(`<div class="card">${esc(fantaReport.error)}</div>`);
  else if (fantaReport) blocks.push(fantaCard("📋 Valutazione formazione", fantaReport));
  if (fantaSuggest && fantaSuggest.error) blocks.push(`<div class="card">${esc(fantaSuggest.error)}</div>`);
  else if (fantaSuggest) blocks.push(fantaCard("✨ Formazione consigliata", fantaSuggest));

  el.innerHTML = `<div class="section-title">⚽ Fanta — codice <code>${esc(fantaCode)}</code></div>
    <div class="card">
      <div class="kv"><b>Impostazioni</b><span class="muted">salvataggio automatico</span></div>
      <div class="fanta-row">
        <label class="muted">Modulo
          <select id="fanta-modulo" aria-label="Modulo">${FANTA_MODULI.map(m => `<option ${m === s.modulo ? "selected" : ""}>${m}</option>`).join("")}</select>
        </label>
        <label class="fanta-switch"><input type="checkbox" id="fanta-mdif" ${s.mod_dif ? "checked" : ""}> Mod difesa</label>
      </div>
      <div class="kv" style="margin-top:10px"><b>Rosa (${rosa.length})</b></div>
      <div class="fanta-rosa">${rosaHtml}</div>
      <div class="fanta-add-row">
        <input id="fanta-add" type="search" placeholder="Cerca giocatore (es. lautaro)…" autocomplete="off" style="padding-left:12px">
        <div id="fanta-ac" class="fanta-ac" hidden></div>
      </div>
      <div class="kv" style="margin-top:10px"><b>Formazione titolare</b></div>
      <div>${xiHtml}</div>
    </div>
    <div class="fanta-actions">
      <button id="fanta-rate" class="cta" ${fantaBusy ? "disabled" : ""}>${fantaBusy ? "⏳…" : "📋 Valuta"}</button>
      <button id="fanta-sugg" class="ghost" ${fantaBusy ? "disabled" : ""}>✨ Consigliata</button>
      <button id="fanta-unlink" class="ghost">🔑 Cambia codice</button>
    </div>
    ${blocks.join("")}`;

  document.getElementById("fanta-modulo").addEventListener("change", e => {
    fantaSave({ modulo: e.target.value });
  });
  document.getElementById("fanta-mdif").addEventListener("change", e => {
    fantaSave({ mod_dif: e.target.checked });
  });
  el.querySelectorAll(".fanta-rm").forEach(btn => {
    btn.addEventListener("click", () => {
      const pid = Number(btn.getAttribute("data-pid"));
      const newRosa = (fantaSquad.rosa || []).filter(p => Number(p.id) !== pid);
      fantaSave({ rosa: newRosa });
      renderFanta();
    });
  });
  const addInp = document.getElementById("fanta-add");
  addInp.addEventListener("input", () => {
    clearTimeout(fantaAcTimer);
    const q = addInp.value.trim();
    if (q.length < 2) { fantaAcRender([]); return; }
    fantaAcTimer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/fanta/players?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        fantaAcRender(data.players || []);
      } catch (e) { fantaAcRender([]); }
    }, 300);
  });
  document.getElementById("fanta-rate").addEventListener("click", () => fantaRun("report"));
  document.getElementById("fanta-sugg").addEventListener("click", () => fantaRun("suggest"));
  document.getElementById("fanta-unlink").addEventListener("click", () => {
    localStorage.removeItem("fanta_code");
    fantaCode = ""; fantaSquad = null; fantaReport = null; fantaSuggest = null;
    renderFanta();
  });
}

// ------------------------------------------------------------- controls & init
function renderActive() {
  const activeTab = document.querySelector("#tabs button.active");
  const tabId = activeTab ? activeTab.getAttribute("data-tab") : "matches";

  document.querySelectorAll(".tab").forEach(el => el.classList.remove("active"));
  const target = document.getElementById(`tab-${tabId}`);
  if (target) target.classList.add("active");

  const controls = document.getElementById("controls");
  if (controls) controls.hidden = tabId !== "matches";

  if (!state.data) {
    if (target) target.innerHTML = renderSkeleton();
    return;
  }

  if (tabId === "matches") renderMatches();
  else if (tabId === "results") renderResults();
  else if (tabId === "standings") renderStandings();
  else if (tabId === "teams") renderTeams();
  else if (tabId === "ai") renderAI();
  else if (tabId === "schedina") renderSchedina();
  else if (tabId === "community") renderCommunity();
  else if (tabId === "fanta") renderFanta();
  else if (tabId === "tracking") renderTracking();
}

function renderSkeleton() {
  return `<div class="skeleton skeleton-card"></div>
    <div class="skeleton skeleton-card"></div>
    <div class="skeleton skeleton-card"></div>`;
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

let tunnelLoaded = false;
function loadTunnel() {
  if (tunnelLoaded) return;
  tunnelLoaded = true;
  fetch("/api/tunnel").then(r => r.json()).then(t => {
    const box = document.getElementById("tunnel-box");
    if (!box) return;
    if (t && t.running && t.url) {
      box.innerHTML = `Link pubblico: <a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.url)}</a>`;
    } else if (t && t.available === false) {
      box.textContent = "Link pubblico: non disponibile (cloudflared non installato)";
    }
  }).catch(() => {});
}

async function loadData() {
  try {
    const res = await fetch("/api/state");
    if (!res.ok) throw new Error("Network response was not ok");
    state.data = await res.json();
    renderHeader();
    updateRoundsDropdown();
    renderActive();
    loadTunnel();
  } catch (err) {
    console.error("Failed to load data:", err);
    const cycle = document.getElementById("cycle-status");
    if (cycle) cycle.textContent = "Errore di connessione";
    if (!state.data) {
      const target = document.querySelector(".tab.active");
      if (target) target.innerHTML = stateBlock("Impossibile caricare i dati", "Il server non risponde. Controlla la connessione e riprova.", true);
    }
  }
}

function measureNavTop() {
  const header = document.getElementById("site-header");
  if (!header) return;
  const headerStatic = window.matchMedia("(max-width: 860px)").matches;
  document.documentElement.style.setProperty("--nav-top", headerStatic ? "0px" : header.offsetHeight + "px");
}

document.addEventListener("DOMContentLoaded", () => {
  tabs.forEach(btn => {
    btn.addEventListener("click", () => {
      tabs.forEach(b => { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      btn.scrollIntoView({ inline: "nearest", block: "nearest" });
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
      favToggle.classList.toggle("on", state.favOnly);
      favToggle.setAttribute("aria-pressed", String(state.favOnly));
      renderActive();
    });
  }

  const sortToggle = document.getElementById("sort-toggle");
  if (sortToggle) {
    sortToggle.addEventListener("click", () => {
      state.sortBy = state.sortBy === "time" ? "round" : "time";
      const lbl = document.getElementById("sort-label");
      if (lbl) lbl.textContent = state.sortBy === "time" ? "Ordina: ora" : "Ordina: giornata";
      sortToggle.title = state.sortBy === "time" ? "Ordina per orario di inizio" : "Ordina per giornata";
      renderActive();
    });
  }

  measureNavTop();
  window.addEventListener("resize", measureNavTop);

  renderActive();
  loadData();
  setInterval(loadData, REFRESH_MS);
});
