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

function renderHeader() {
  const d = state.data;
  const upd = document.getElementById("last-updated");
  upd.textContent = "Aggiornato: " + fmtTime(d.updated);
  const cycle = document.getElementById("cycle-status");
  if (d.last_error) cycle.textContent = "⚠ " + d.last_error;
  else cycle.textContent = d.season ? `Stagione ${d.season.name}` : "";
}

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
    html += `<div class="prob-bar" title="Clicca per copiare">
      <div style="width:${p1}%;background:var(--accent); cursor:pointer;" onclick="shareText('Pronostico ${esc(fx.home)}-${esc(fx.away)}: 1 ${p1.toFixed(0)}% X ${px.toFixed(0)}% 2 ${p2.toFixed(0)}%')" title="Condividi">${p1.toFixed(0)}%</div>
      <div style="width:${px}%;background:#6e7681">${px.toFixed(0)}%</div>
      <div style="width:${p2}%;background:var(--alert)">${p2.toFixed(0)}%</div>
    </div>`;
  }
  return html;
}

function renderActive() {
  if (!state.data) return;
  renderHeader();
}

async function loadData() {
  try {
    const res = await fetch("/api/data");
    state.data = await res.json();
    renderActive();
  } catch(e) {
    console.error(e);
  }
}

loadData();
setInterval(loadData, REFRESH_MS);
