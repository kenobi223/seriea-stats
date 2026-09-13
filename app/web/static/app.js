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

function lineupsBlock(fx, side) {
  const pxi = fx.probable_xi && fx.probable_xi[side];
  const lu = fx.lineups && fx.lineups[side];
  const form = side === "home" ? fx.form_home : fx.form_away;
  const src = pxi || lu;
  if (!src || !src.players) {
    return `<div class="muted">Formazione non ancora ufficiale. L'ultimo undici noto sarà mostrato a ridosso del calcio d'inizio.</div>`;
  }
  const starters = src.players.slice(0, 11);
  const list = starters.map(p => {
    let b = p.lineup_conf === "new" ? `<span class="lnew">novità</span>` : "";
    if (p.src === "both") b = `<span class="lsrc" title="concorda con il modello">✔</span>`;
    else if (p.src === "model") b = b + `<span class="lmod" title="scelta del modello">mod</span>`;
    else if (p.src === "sf") b = b + `<span class="lsrc" title="solo Sofascore">sf</span>`;
    return `<span class="chip gray">${esc(p.shirt || "")} ${esc(p.name)}${b}</span>`;
  }).join(" ");
  const inj = (pxi && pxi.missing || []).map(m =>
    `${esc(m.name)} <span class="muted">(${esc(m.reason || "?" )}${m.until ? " fino " + fmtIsoDate(m.until) : ""})</span>`
  ).join(", ");
  const injrows = inj
    ? `<div class="injuries" style="margin-top:6px">🚑 Assenti: ${inj}</div>` : "";
  const source = !pxi ? (lu && lu.confirmed ? "Formazione ufficiale" : "Ultimo undici ufficiale")
    : pxi._source === "model" ? "XI probabile · previsione dati"
    : pxi._source === "merge" ? "XI probabile · Sofascore + modello" : "XI probabile";
  const contese = pxi && pxi.contese && pxi.contese.length
    ? `<div style="margin-top:6px;font-size:11.5px;color:var(--warn)">⚡ In corsa (modello): ${pxi.contese.map(esc).join(", ")}</div>` : "";
  return `<div class="muted" style="margin-bottom:6px">
      ${source}
      ${src.formation ? ` · ${esc(src.formation)}` : ""}</div>
      <div class="chips">${list}</div>
      ${injrows}
      ${contese}
      ${(form && form.injuries || []).slice(0, 3).map(i => esc(i.player)).join(", ")
        ? `<div style="margin-top:6px;font-size:11.5px;color:var(--warn)">⚠ Lista infermeria: ${(form.injuries || []).slice(0, 3).map(i => esc(i.player)).join(", ")}</div>` : ""}`;
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

function fmtIsoDate(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function scorerBlock(fx, side) {
  const list = (fx.scorer_probabilities && fx.scorer_probabilities[side]) || [];
  const team = side === "home" ? fx.home : fx.away;
  if (!list.length) {
    return `<div class="muted">Nessun dato marcatori per ${esc(team)}.</div>`;
  }
  const rows = list.slice(0, 3).map(r => {
    const w = Math.max(4, Math.min(100, (r.prob_pct || 1)));
    const minIcon = r.prob_pct >= 40 ? "🔥" : (r.prob_pct >= 25 ? "⚡" : "");
    return `
      <div class="ps-row">
        <div class="ps-main">
          <span class="ps-name">${esc(r.name)}${minIcon}
            ${r.pos ? `<span class="ps-pos">${esc(r.pos)}</span>` : ""}</span>
          <span class="ps-num"><b>${r.prob_pct}%</b> · ${r.goals_last5} gol ult. ${r.matches_last5} g</span>
        </div>
        <div class="ps-mid">
          <div class="ps-bar"><div class="ps-fill" style="width:${w}%"></div></div>
          <span class="ps-threat">${r.prob_pct}%</span>
        </div>
        ${r.avg_sot != null ? `<div class="ps-meta muted">SOT ${Number(r.avg_sot).toFixed(2)}/gara · opp. subisce ${r.opp_goals_conceded}/g</div>` : ""}
      </div>`;
  }).join("");
  return `<div class="muted" style="font-size:11px;margin-bottom:6px">Probabilità di andare a segno: forma ultimi 5, tiri in porta e difesa avversaria</div>${rows}`;
}

function playerShotsBlock(fx, side) {
  const list = (fx.player_shots && fx.player_shots[side]) || [];
  const team = side === "home" ? fx.home : fx.away;
  if (!list.length) {
    return `<div class="muted">Nessun dato tiri in porta giocatore per ${esc(team)} (dalla media degli ultimi match).</div>`;
  }
  const confIcon = {high: "🟢", medium: "🟡", low: "🔴"};
  const trendIcon = {up: "▲", down: "▼", flat: "▪"};
  const rows = list.slice(0, 7).map(r => {
    const conf = confIcon[r.conf] || "";
    const trend = trendIcon[r.trend] || "";
    const fair = (r.fair_o05 != null)
      ? `<span class="ps-fair">Ov 0.5 <b>@${Number(r.fair_o05).toFixed(2)}</b>${r.fair_o15 != null ? ` · Ov 1.5 <b>@${Number(r.fair_o15).toFixed(2)}</b>` : ""}</span>`
      : "";
    const expected = r.expected != null ? `<span class="ps-exp">atteso <b>${Number(r.expected).toFixed(2)}</b> vs avv.</span>` : "";
    const w = Math.max(4, Math.min(100, (r.threat || 1) * 10));
    return `
      <div class="ps-row">
        <div class="ps-main">
          <span class="ps-name">${esc(r.name)}${conf}${trend}
            ${r.pos ? `<span class="ps-pos">${esc(r.pos)}</span>` : ""}</span>
          <span class="ps-num"><b>${Number(r.avg).toFixed(2)}</b> a gara · ${esc(r.played)} g</span>
        </div>
        <div class="ps-mid">
          <div class="ps-bar"><div class="ps-fill" style="width:${w}%"></div></div>
          <span class="ps-threat">${r.threat || "?"} /10</span>
        </div>
        ${fair || expected ? `<div class="ps-meta">${expected}${expected ? " " : ""}${fair}</div>` : ""}
      </div>`;
  }).join("");
  return `<div class="muted" style="font-size:11px;margin-bottom:6px">Minaccia offensiva: media, quota fair e atteso vs avversario</div>${rows}`;
}

function formBlock(fx, side) {
  const form = (side === "home" ? fx.form_home : fx.form_away) || {};
  const lasts = form.last_results || [];
  const chips = lasts.slice(-6).map(e => chipFrom(resultCharMap(e.result) || "?")).join("");
  const season = form.current_season;
  const shots = form.shots_avg;
  const cards = form.cards_y_avg;
  return `
    <div class="kv"><span class="muted">Ultimi:</span><span class="chips">${chips}</span></div>
    ${season ? `<div class="kv"><span class="muted">Stagione:</span><b>${season.giocate} g · ${season.v}V ${season.n}N ${season.p}P · GF ${season.gf} GA ${season.ga}</b></div>` : ""}
    ${shots != null ? `<div class="kv"><span class="muted">Tiri in porta/gara:</span><b>${shots}</b></div>` : ""}
    ${cards != null ? `<div class="kv"><span class="muted">Gialli subiti/gara:</span><b>${cards}</b></div>` : ""}
  `;
}

function refereeBlock(ref) {
  if (!ref || !ref.name) return `<div class="muted">Arbitro non ancora comunicato.</div>`;
  const career = ref.games ? `${ref.games} gare, ${(ref.yellow / ref.games).toFixed(1)} gialli/g, ${(ref.red / ref.games).toFixed(2)} rossi/g` : "";
  const season = ref.season_y_per_game != null
    ? `in stagione (${ref.season_games} g): ${ref.season_y_per_game} gialli/g, ${ref.season_r_per_game} rossi/g` : "";
  return `<div><b>${esc(ref.name)}</b></div>
    <div class="muted" style="font-size:12px">${esc(career)}${career && season ? " · " : ""}${esc(season)}</div>`;
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
  const xg = p.xg || {};
  if (xg.enabled) {
    html += `<div class="kv"><span class="muted">xG (gol attesi reali):</span>
      <b>${esc(fx.home)} ${Number(xg.home_for).toFixed(2)}↔${Number(xg.home_ag).toFixed(2)}
       · ${esc(fx.away)} ${Number(xg.away_for).toFixed(2)}↔${Number(xg.away_ag).toFixed(2)}</b></div>`;
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
      const odds = mp.odds ? ` @ ${fmtOdds(mp.odds)}` : "";
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

function savesBlock(fx, side) {
  const ks = fx.keeper_saves || {};
  const b = ks[side];
  if (!b) return `<div class="muted">Nessun dato sulle parate.</div>`;
  const rows = [];
  rows.push(`<div class="kv"><span class="muted">Portiere:</span><b>${esc(b.gk || (side === "home" ? fx.home : fx.away))}</b></div>`);
  rows.push(`<div class="kv"><span class="muted">Media parate (${b.played || 0} g):</span><b>${fmtOdds(b.avg || 0)}</b></div>`);
  if (b.expected != null) {
    rows.push(`<div class="kv"><span class="muted">Stimate oggi (~):</span><b>${fmtOdds(b.expected)}</b></div>`);
  }
  if (b.over_prob != null && b.threshold != null) {
    const fair = b.fair_over ? ` · fair @${fmtOdds(b.fair_over)}` : "";
    rows.push(`<div class="kv"><span class="muted">Over ${b.threshold} parate:</span>
      <b>${(b.over_prob * 100).toFixed(0)}%${fair}</b></div>`);
  }
  if (b.pick) {
    rows.push(`<div class="kv"><span class="chip v">${esc(b.pick.toUpperCase())}</span>
      <b class="muted">(${esc(b.conf || "")})</b></div>`);
  }
  return rows.join("");
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
          <div class="subpanel"><h3>Arbitro</h3>${refereeBlock(fx.referee)}</div>
        </div>
        <div class="grid2" style="margin-top:12px">
          <div class="subpanel"><h3>Formazione provabile · ${esc(fx.home)}</h3>${lineupsBlock(fx, "home")}</div>
          <div class="subpanel"><h3>Formazione provabile · ${esc(fx.away)}</h3>${lineupsBlock(fx, "away")}</div>
        </div>
        <div class="grid2" style="margin-top:12px">
          <div class="subpanel"><h3>🎯 Tiri in porta · ${esc(fx.home)}</h3>${playerShotsBlock(fx, "home")}</div>
          <div class="subpanel"><h3>🎯 Tiri in porta · ${esc(fx.away)}</h3>${playerShotsBlock(fx, "away")}</div>
        </div>
        <div class="grid2" style="margin-top:12px">
          <div class="subpanel"><h3>🎭 Morale & conferenze · ${esc(fx.home)}</h3>${moraleBlock(fx, "home")}</div>
          <div class="subpanel"><h3>🎭 Morale & conferenze · ${esc(fx.away)}</h3>${moraleBlock(fx, "away")}</div>
        </div>
        <div class="grid2" style="margin-top:12px">
          <div class="subpanel"><h3>⚽ Probabilità marcatori · ${esc(fx.home)}</h3>${scorerBlock(fx, "home")}</div>
          <div class="subpanel"><h3>⚽ Probabilità marcatori · ${esc(fx.away)}</h3>${scorerBlock(fx, "away")}</div>
        </div>
        <div class="grid2" style="margin-top:12px">
          <div class="subpanel"><h3>🧤 Parate portiere · ${esc(fx.home)}</h3>${savesBlock(fx, "home")}</div>
          <div class="subpanel"><h3>🧤 Parate portiere · ${esc(fx.away)}</h3>${savesBlock(fx, "away")}</div>
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
      <div class="card"><div class="big-num">${t.bets_hit || 0}/${t.bets_total || 0}</div>
        <div class="muted">pronostici indovinati (${rate})</div></div>
      <div class="card"><div class="big-num">${brier}</div>
        <div class="muted">Brier score · più basso = più onesto</div></div>
    </div>`;

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

// ------------------------------------------------------------- errors
function renderErrors() {
  const el = document.getElementById("tab-errors");
  const flags = state.data.value_flags || [];
  if (!flags.length) {
    el.innerHTML = `<div class="card muted">Nessun errore di quota rilevato nell'ultimo refresh. 
      Le segnalazioni compaiono quando due bookmaker hanno un disallineamento ≥ 15% sullo stesso esito.</div>`;
    return;
  }
  el.innerHTML = `<div class="section-title">${flags.length} segnalazioni · ultimo refresh ${fmtTime(state.data.updated)}</div>`;
  for (const f of flags) {
    const vals = Object.entries(f.values || {}).map(([k, v]) =>
      `<span class="source-pill">${esc(k)} ${fmtOdds(v)}</span>`).join(" ");
    el.insertAdjacentHTML("beforeend", `
      <div class="card flag-card ${esc(f.severity)}">
        <div class="match-head">
          <div><b>${esc(f.fixture)}</b> <span class="chip ${f.severity === "alert" ? "alert" : "warn"}">${esc(f.kind)}</span></div>
          <div class="meta">${esc(f.severity === "alert" ? "ATTENZIONE" : "controlla")}</div>
        </div>
        <div style="margin-top:6px">${esc(f.message)}</div>
        <div style="margin-top:6px">${vals}</div>
      </div>`);
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
    <thead><tr><th>#</th><th>Squadra</th><th>G</th><th>V</th><th>N</th><th>P</th><th>GF</th><th>GA</th><th>Pt</th><th>Tiri porta</th></tr></thead><tbody>` +
    rows.map(r => {
      const f = formByTeam.get(r.team_id);
      const shots = f && f.shots_avg != null ? f.shots_avg : "—";
      const last = f ? (f.last_results || []).slice(-5).map(e => chipFrom(resultCharMap(e.result) || "?")).join("") : "";
      return `<tr><td class="pos-chip">${r.position}</td><td>${esc(r.name)}</td>
        <td>${r.played}</td><td>${r.wins}</td><td>${r.draws}</td><td>${r.losses}</td>
        <td>${r.gf}</td><td>${r.ga}</td><td><b>${r.points}</b></td>
        <td>${shots}<span class="chips" style="margin-left:6px">${last}</span></td></tr>`;
    }).join("") +
    `</tbody></table></div>`;
}

// ------------------------------------------------------------- manual odds
function renderManual() {
  const el = document.getElementById("tab-manual");
  el.innerHTML = `
    <div class="card">
      <div class="section-title">Importa quota manuale (Sisal, SNAI, ecc.)</div>
      <p class="muted" style="margin-top:-6px">Usa questo modulo per i mercati che i comparatori non coprono, es. 
      "Lautaro Tiro in porta" @1.80 su Sisal e @2.50 su SNAI: inseriscili entrambi e verranno confrontati automaticamente.</p>
      <div class="form-row compact">
        <input id="m-home" placeholder="Casa (es. Inter)">
        <input id="m-away" placeholder="Trasferta (es. Roma)">
        <input id="m-market" placeholder="Mercato (es. Tiri in porta)">
        <input id="m-pick" placeholder="Esito (es. Lautaro) ">
        <input id="m-source" placeholder="Bookmaker (es. sisal)">
        <input id="m-odds" type="number" step="0.01" min="1.01" placeholder="Quota (es. 1.80)">
      </div>
      <button class="cta" onclick="addManualOdds()">Aggiungi quota</button>
    </div>
    <div class="card">
      <div class="section-title" id="manual-list-title">Quote inserite manualmente</div>
      <div id="manual-list"></div>
      <button class="ghost" style="margin-top:8px" onclick="clearManual()">Svuota elenco</button>
    </div>`;
  refreshManualList();
}

async function refreshManualList() {
  const el = document.getElementById("manual-list");
  if (!el) return;
  try {
    const r = await fetch("/api/manual-odds");
    const list = await r.json();
    el.innerHTML = list.length
      ? `<table><thead><tr><th>Casa</th><th>Trasferta</th><th>Mercato</th><th>Esito</th><th>Bookmaker</th><th class="right">Quota</th></tr></thead><tbody>` +
        list.map(x => `<tr><td>${esc(x.home)}</td><td>${esc(x.away)}</td><td>${esc(x.market)}</td>
          <td>${esc(x.pick)}</td><td>${esc(x.source)}</td><td class="right"><b>${fmtOdds(x.odds)}</b></td></tr>`).join("") +
        `</tbody></table>`
      : `<div class="muted">Nessuna quota manuale. Le quote Sofascore vengono comunque confrontate automaticamente.</div>`;
  } catch (e) {
    el.innerHTML = `<div class="muted">Errore nel caricamento.</div>`;
  }
}

async function addManualOdds() {
  const get = id => document.getElementById(id).value.trim();
  const payload = {
    home: get("m-home"), away: get("m-away"), market: get("m-market"),
    pick: get("m-pick"), source: get("m-source"),
    odds: parseFloat(get("m-odds")),
  };
  if (!payload.home || !payload.away || !payload.market || !payload.source || !payload.odds) {
    alert("Compila tutti i campi (es. Inter / Roma / Tiri in porta / Lautaro / sisal / 1.80)");
    return;
  }
  const r = await fetch("/api/odds", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const res = await r.json();
  if (res.ok) {
    ["m-home", "m-away", "m-market", "m-pick", "m-source", "m-odds"].forEach(id => (document.getElementById(id).value = ""));
    refreshManualList();
  } else {
    alert(res.error || "Errore");
  }
}

async function clearManual() {
  await fetch("/api/manual-odds", { method: "DELETE" });
  refreshManualList();
}

// ------------------------------------------------------------- sources
function renderSources() {
  const el = document.getElementById("tab-sources");
  const s = state.data.sources || {};
  const rows = [
    ["Sofascore", "risultati, statistiche, arbitri, quote 1X2", s.sofascore ? "attivo" : "inattivo", true],
    ["centroquote", "conferma calendario Serie A dall'Italia", s.centroquote ? "raggiungibile" : "non raggiungibile da questo IP (datacenter)", false],
    ["sogosport", "quote bookmaker italiane (best-effort)", s.sogosport ? "raggiungibile" : "non raggiungibile da questo IP (datacenter)", false],
    ["Sisal / SNAI (manuale)", "quote inserite a mano per i mercati giocatore", "usa il tab «Import quote»", false],
  ];
  el.innerHTML = `<div class="card"><table>
    <thead><tr><th>Fonte</th><th>Cosa fornisce</th><th>Stato</th></tr></thead><tbody>` +
    rows.map(r => `<tr><td><b>${esc(r[0])}</b></td><td>${esc(r[1])}</td>
      <td style="color:${r[3] ? "var(--accent)" : "var(--muted)"}">${esc(r[2])}</td></tr>`).join("") +
    `</tbody></table>
    <div style="margin-top:12px" class="muted">NB: i bookmaker italiani (Sisal, SNAI, Goldbet...) spesso bloccano gli IP dei data center.
    Se il server gira sulla rete di casa, lo scraper li rileva in automatico. In ogni caso il confronto manuale copre i mercati
    giocatore come i tiri in porta.</div></div>`;
}

// ------------------------------------------------------------- AI chat
let aiReady = false;

const AI_SUGGESTIONS = [
  "Che tiri in porta mi consigli? non scontati",
  "Ci sono errori di quota oggi?",
  "Qual è il pronostico della giornata?",
  "Arbitri con più cartellini",
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
      <p class="muted" style="margin-top:-6px">Chiedi in italiano: raccomandazioni sui tiri in porta
      (scontati o probabili), errori di quota, pronostici, arbitri o un'analisi partita.</p>
      <div class="ai-suggest">${suggestions.map((s, i) =>
        `<button class="chip ai-chip" onclick="askAIByIndex(${i})">${esc(s)}</button>`).join(" ")}</div>
      <div id="ai-log" class="ai-log"></div>
      <div class="form-row compact">
        <input id="ai-input" placeholder="es. che tiri in porta mi consigli per la prossima giornata?"
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
  document.querySelectorAll(".tab").forEach(s => s.classList.toggle("active", s.id === "tab-" + name));
  renderActive();
}

tabs.forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));

function renderActive() {
  const active = document.querySelector("#tabs button.active");
  const name = active ? active.dataset.tab : "matches";
  if (name === "matches") renderMatches();
  else if (name === "results") { renderResults(); refreshLive(); }
  else if (name === "tracking") renderTracking();
  else if (name === "ai") renderAI();
  else if (name === "errors") renderErrors();
  else if (name === "standings") renderStandings();
  else if (name === "manual") renderManual();
  else if (name === "sources") renderSources();
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

poll();
setInterval(poll, REFRESH_MS);
setInterval(refreshLive, LIVE_REFRESH_MS);
setInterval(() => {
  if (document.querySelector("#tabs button.active").dataset.tab === "manual") refreshManualList();
}, 10000);
renderTunnel();
setInterval(renderTunnel, 15000);