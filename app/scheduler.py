"""Orchestratore: a ogni ciclo raccoglie dati, analizza e salva lo stato."""
import logging
import os
import threading
import time

import config
from app.analysis import form as form_mod
from app.analysis import predictor
from app.analysis import referee as referee_mod
from app.analysis import tracker
from app.analysis import value as value_mod
from app.analysis import shots as shots_mod
from app.analysis import scorer as scorer_mod
from app.analysis import saves as saves_mod
from app.analysis import tipsters as tipsters_mod
from app.analysis import lineups as lineups_mod
from app.core.models import Fixture, OddsPick
from app import notify
from app.sources import odds as odds_mod
from app.sources.client import FootballClient
from app.sources.centroquote import CentroquoteScraper, SogosportScraper

log = logging.getLogger("scheduler")


# ------------------------------------------------------------------- stato
def _probable_lineups(client, fx):
    """Ultimo undici ufficiale di ciascuna squadra (forma probabile)."""
    lu = {"home": None, "away": None}
    for side, tid in (("home", fx.home_id), ("away", fx.away_id)):
        if not tid:
            continue
        events = client.team_events(tid, max_events=40)
        finished = [e for e in events if e.get("finished")]
        if not finished:
            continue
        last = finished[0]
        data = client._cached(f"lu-{last['id']}",
                              lambda: client.lineups(last["id"]))
        if not data:
            continue
        want = "home" if last["home_id"] == tid else "away"
        block = data.get(want)
        if block:
            lu[side] = {**block, "probable": True}
    return lu


def _restore_fixture(d):
    fx = Fixture(
        id=d.get("id"), home=d.get("home"), away=d.get("away"),
        home_id=d.get("home_id"), away_id=d.get("away_id"),
        start_ts=d.get("start_ts"), round=d.get("round"),
        venue=d.get("venue", ""), status=d.get("status", ""),
        referee=d.get("referee", {}),
        odds=[OddsPick(o.get("source"), o.get("market"), o.get("pick"),
                       o.get("odds"), o.get("updated", 0))
              for o in d.get("odds", []) if o.get("odds")],
        history=[[OddsPick(o.get("source"), o.get("market"), o.get("pick"),
                           o.get("odds"), o.get("updated", 0))
                  for o in snap] for snap in d.get("history", [])],
        predictions=d.get("predictions", {}),
        lineups=d.get("lineups", {}),
        player_shots=d.get("player_shots", {}),
        probable_xi=d.get("probable_xi", {}),
        morale=d.get("morale", {}),
        h2h=d.get("h2h", []),
        form_home=d.get("form_home", []), form_away=d.get("form_away", []),
        stats_home=d.get("stats_home", {}), stats_away=d.get("stats_away", {}),
        value_flags=d.get("value_flags", []),
        scorer_probabilities=d.get("scorer_probabilities", {}),
        keeper_saves=d.get("keeper_saves", {}),
        coach=d.get("coach", {}),
    )
    return fx


def _league_avg(standings, all_forms):
    played = sum(r.get("played") or 0 for r in standings) or 1
    scored = sum(r.get("gf") or 0 for r in standings)
    conceded = sum(r.get("ga") or 0 for r in standings)
    home_gf, away_gf, count = 0.0, 0.0, 0
    for f in all_forms:
        for r in f.get("home_results", []) or []:
            try:
                home_gf += float(r["score"].split("-")[0])
            except (ValueError, KeyError):
                continue
            count += 1
        for r in f.get("away_results", []) or []:
            try:
                away_gf += float(r["score"].split("-")[1])
            except (ValueError, KeyError):
                continue
    return {
        "scored": scored / played, "conceded": conceded / played,
        "home": (home_gf / count if count else 1.30),
        "away": (away_gf / count if count else 1.05),
    }


# ------------------------------------------------------------------- ciclo
def run_cycle(store, quick=False):
    t0 = time.time()
    client = FootballClient()
    sources_status = dict(store.get("sources", {}))

    season = client.resolve_season()
    if not season:
        log.error("stagione Serie A non trovata")
        return
    season_id = season["id"]
    store.set("season", {"id": season_id, "name": season.get("name")})

    standings = client.standings(season_id)
    if standings:
        store.set("standings", standings)

    # ---- risultati delle giornate antecedenti (una richiesta, cache di
    #      giornata: cambiano solo quando finiscono le partite)
    try:
        store.set("results", client.season_results(season_id))
    except Exception as e:
        log.debug("risultati stagione non disponibili: %s", e)

    # ---- riallinea calendario
    prev = {f["id"]: _restore_fixture(f) for f in store.get("fixtures", [])}
    now_fx = []
    next_rows = client.next_fixtures(season_id, days=config.UPDATE_INTERVAL_SECONDS > 0 and 10 or 10)
    for row in next_rows:
        event_id = row[0]
        fx = prev.get(event_id)
        if fx is None:
            fx = client.build_fixture(row, season_id)
            fx.form_home = []
            fx.form_away = []
        else:
            fx.start_ts = row[5]
            detail = client.event_detail(event_id)
            if detail:
                fx.status = detail.get("status", fx.status)
                fx.venue = detail.get("venue", fx.venue)
                if detail.get("referee"):
                    fx.referee = detail["referee"]
        now_fx.append(fx)

    # salva subito i dati core: tengono vivo lo stato anche se le fasi
    # analitiche successive (forma/h2h/xg) restano in attesa per retry.
    store.set("fixtures", [fx.to_dict() for fx in sorted(now_fx, key=lambda x: x.start_ts)])
    store.save()

    # ---- quote aggiornate a ogni ciclo (10 min)
    for fx in now_fx:
        fx.odds = client.odds_to_picks(fx.id)

    # ---- forme (solo se mancanti o cambiate: la forma cambia di giornata)
    teams_to_build = []

    def need_form(fx):
        return not fx.form_home or not fx.form_away

    for fx in now_fx:
        if need_form(fx):
            teams_to_build.append((fx, "home"))
            teams_to_build.append((fx, "away"))
        elif not fx.h2h and fx.home_id and fx.away_id:
            fx.h2h = form_mod.h2h_between(client, fx.home_id, fx.away_id)

    # costruisce forme una sola volta per squadra
    built = {}
    for fx, side in teams_to_build:
        tid, name = (fx.home_id, fx.home) if side == "home" else (fx.away_id, fx.away)
        if tid not in built:
            built[tid] = form_mod.build_team_form(client, tid, name, season_id)
        if side == "home":
            fx.form_home = built[tid]
        else:
            fx.form_away = built[tid]
    for fx in now_fx:
        if fx.form_home and fx.form_away and not fx.h2h and fx.home_id and fx.away_id:
            fx.h2h = form_mod.h2h_between(client, fx.home_id, fx.away_id)

    # ---- quote (merge fonti + snapshot movimenti)
    odds_mod.tick(store, now_fx)

    # ---- nuovo allenatore ("new-manager bounce"): registro manuale
    #      (data/coaches.json) + auto-detezione dal manager di Sofascore
    #      (cache quotidiana). Disponibile per morale e pronostici.
    try:
        from app.analysis import coach as coach_mod
        reg = coach_mod.load()
        if config.NEW_MANAGER_ENABLED:
            reg = coach_mod.auto_update(reg, client, standings)
        coach_mod.attach(reg, now_fx)
        store.set("coaches", reg)
    except Exception as e:
        log.debug("rilevamento nuovo allenatore fallito: %s", e)

    # ---- formazioni: probabile (ultimo undici ufficiale) e, a ridosso del
    #      fischio d'inizio, quella confermata dalla fonte ufficiale.
    for fx in now_fx:
        start_in = fx.start_ts - time.time()
        if start_in < 0:
            continue
        live = start_in <= 3 * 3600
        if live:
            confirmed = client.lineups(fx.id)
            if confirmed and (confirmed["home"] or confirmed["away"]):
                sx = fx.id
                fx.lineups = {"home": confirmed["home"], "away": confirmed["away"],
                              "confirmed": True}
                continue

        # probabile di Sofascore (11 titolari + infortunati) incrociata con
        # l'ultimo undici ufficiale: badge "confermato / novità" per giocatore
        probable = client.probable_xi(fx.id)
        if probable and (probable["home"] or probable["away"]):
            last = _probable_lineups(client, fx)
            for side in ("home", "away"):
                pxi = probable.get(side)
                if not pxi:
                    continue
                ids = {p.get("id") for p in
                       ((last or {}).get(side) or {}).get("players", [])}
                for p in pxi["players"]:
                    if p.get("id") and p["id"] not in ids:
                        p["lineup_conf"] = "new"
                    else:
                        p["lineup_conf"] = "in"
            fx.probable_xi = probable
            if last and not fx.lineups:
                fx.lineups = last
            continue
        if not fx.lineups:
            fx.lineups = _probable_lineups(client, fx)

    # ---- XI probabile "merge di fonti": Sofascore (se c'è) + predittore
    #      interno dagli ultimi undici ufficiali. Copre anche le partite a
    #      giorni di distanza, esclude infortunati/squalificati e marca la
    #      concordanza tra le fonti.
    try:
        for fx in now_fx:
            if fx.start_ts - time.time() < 0:
                continue
            if fx.lineups and fx.lineups.get("confirmed"):
                continue
            lineups_mod.compute_fixture_xis(client, fx, season_id)
    except Exception as e:
        log.debug("merge formazioni non disponibile: %s", e)

    # ---- tiri in porta dei giocatori: media degli ultimi match finiti per
    #      ogni titolare probabile (cached su disco, super rapido dopo il
    #      primo calcolo) + threat score contro il fattore avversario
    try:
        team_sot = {}
        for fx in now_fx:
            for f in (fx.form_home, fx.form_away):
                if f and f.get("shots_avg") is not None:
                    team_sot[f.get("team_id")] = f["shots_avg"]
        sot_vals = [v for v in team_sot.values() if v]
        league_sot = round(sum(sot_vals) / len(sot_vals), 2) if sot_vals else None
        shots_mod.compute_for_fixtures(client, now_fx, season_id,
                                       team_sot, league_sot)
    except Exception as e:
        log.debug("tiri giocatori non disponibili: %s", e)

    # ---- probabilità marcatori: gol atteso per ogni titolare basato su
    #      forma, SOT, difesa avversaria e posizione
    try:
        scorer_mod.compute_for_fixtures(client, now_fx, season_id)
    except Exception as e:
        log.debug("scorer probabilities non disponibili: %s", e)

    # ---- parate dei portieri: media parate a gara della squadra (dalle
    #      statistiche già in cache) aggiustata per i tiri in porta che
    #      l'avversario produce rispetto alla media del campionato
    try:
        team_sot_map = {}
        for fx in now_fx:
            for f in (fx.form_home, fx.form_away):
                if f and f.get("shots_avg") is not None:
                    team_sot_map[f.get("team_id")] = f["shots_avg"]
        sot_vals = [v for v in team_sot_map.values() if v]
        league_sot = round(sum(sot_vals) / len(sot_vals), 2) if sot_vals else None
        saves_mod.compute_for_fixtures(client, now_fx, season_id,
                                       league_sot=league_sot)
    except Exception as e:
        log.debug("parate portieri non disponibili: %s", e)

    # ---- morale pre-partita + conferenze dei mister (Google News RSS,
    #      cached 6h): punteggio 1-10 da forma/infortuni/avversario, note
    #      con il tono dello spogliatoio
    try:
        from app.analysis import morale as morale_mod
        standings_map = {r.get("team_id"): r for r in standings}
        press_cache = {}
        for fx in now_fx:
            fx.morale = {"home": {}, "away": {}}
            for side in ("home", "away"):
                name = fx.home if side == "home" else fx.away
                tid = fx.home_id if side == "home" else fx.away_id
                form = fx.form_home if side == "home" else fx.form_away
                opp = fx.away_id if side == "home" else fx.home_id
                inj = len(((fx.probable_xi or {}).get(side) or {})
                          .get("missing") or [])
                opp_pts = (standings_map.get(opp) or {}).get("points")
                ch = (fx.coach or {}).get(side) or {}
                pre = morale_mod.pre_morale(form, inj, opp_pts,
                                            new_coach=ch.get("is_new"))
                if tid not in press_cache:
                    press_cache[tid] = morale_mod.press_notes(client, name)
                fx.morale[side] = {
                    "score": pre["score"], "label": pre["label"],
                    "injuries": inj, "ppg": pre["ppg"],
                    "notes": press_cache[tid],
                    "coach_note": (ch.get("note")
                                   or f"nuovo allenatore: {ch.get('manager') or '?'}")
                    if ch.get("is_new") else None,
                }
    except Exception as e:
        log.debug("morale non disponibile: %s", e)

    # ---- fonti extra best-effort
    try:
        cq = CentroquoteScraper()
        cq_matches, cq_ok = cq.fetch_matches()
        sources_status["centroquote"] = cq_ok
    except Exception as e:
        log.debug("centroquote fallito: %s", e)
        sources_status["centroquote"] = False
    try:
        sogo = SogosportScraper()
        sogo_rows, sogo_ok = sogo.fetch_odds()
        sources_status["sogosport"] = sogo_ok
    except Exception as e:
        log.debug("sogosport fallito: %s", e)
        sources_status["sogosport"] = False

    # ---- dati arbitri (cached, immutabili)
    ref_stats = {}
    if not quick:
        past_ids = client.collect_past_matches(season_id)
        ref_stats = referee_mod.build_referee_stats(client, season_id, past_ids)
        store.set("referee_stats", ref_stats)
    else:
        ref_stats = store.get("referee_stats", {}) or {}

    # ---- aggancia stats arbitro stagionali: prima dal campione stagionale,
    #      poi (se non presente) dal profilo arbitro dedicato
    for fx in now_fx:
        rid = (fx.referee or {}).get("id")
        if not rid:
            continue
        if rid in ref_stats:
            rs = ref_stats[rid]
            fx.referee = {**fx.referee,
                          "season_games": rs.get("season_games"),
                          "season_y_per_game": rs.get("season_y_per_game"),
                          "season_r_per_game": rs.get("season_r_per_game")}
            continue
        try:
            reid = client.referee_events(rid)
            if not reid:
                continue
            inc_map = client.incidents_for_events(reid, workers=5)
            season_games = []
            for eid in reid[:10]:
                y = r = 0
                for inc in inc_map.get(eid, []):
                    if inc.get("type") == "card":
                        if "red" in str(inc.get("class", "")).lower():
                            r += 1
                        elif "yellow" in str(inc.get("class", "")).lower():
                            y += 1
                season_games.append((y, r))
            n = len(season_games)
            if n:
                ty = sum(g[0] for g in season_games)
                tr = sum(g[1] for g in season_games)
                fx.referee = {**fx.referee,
                              "season_games": n,
                              "season_y_per_game": round(ty / n, 2),
                              "season_r_per_game": round(tr / n, 2)}
        except Exception as e:
            log.debug("stats arbitro %s non disponibili: %s", rid, e)

    # ---- autocritica: recupera i pronostici delle partite già giocate
    #      (se il programma è stato spento e sono passate partite), valuta
    #      se indovinati e impara dagli errori prima di fare i nuovi.
    try:
        stale = [d for d in store.get("fixtures", [])
                 if d.get("status") == "finished"
                 and (d.get("predictions") or {}).get("1x2")]
        if stale:
            log.info("tracker: riallineo %d pronostici di partite già giocate "
                     "mentre il programma era spento", len(stale))
            tracker.record(stale)
    except Exception as e:
        log.debug("tracker record retroattivo fallito: %s", e)
    try:
        tracker.evaluate(client)
    except Exception as e:
        log.debug("tracker evaluate fallito: %s", e)

    # ---- valutazione e raccolta dei pronosticatori esterni (tipster):
    #      chi sbaglia viene pesato meno / escluso dal mix delle previsioni
    try:
        tipsters_mod.evaluate()
        tipster_registry = tipsters_mod.load()
    except Exception as e:
        log.debug("tipster evaluate fallito: %s", e)
        tipster_registry = tipsters_mod.load()
    try:
        tipsters_mod.collect(now_fx)
    except Exception as e:
        log.debug("tipster collect fallito: %s", e)

    # ---- notifica foto "pronostico indovinato" a chi ha avviato il bot
    try:
        notify.send_pending_wins()
    except Exception as e:
        log.debug("notifica pronostici indovinati fallita: %s", e)

    try:
        tracking, calibration = tracker.analyze()
    except Exception as e:
        log.debug("tracker analyze fallito: %s", e)
        tracking, calibration = store.get("tracking", {}), \
            store.get("calibration", {})

    # ---- modello del mercato: ricalcola gli alpha OOS dalle quote storiche
    if config.MARKET_MODEL_ENABLED:
        try:
            from app.analysis import market_model as market_mod
            market_mod.fit()
        except Exception as e:
            log.debug("market_model fit fallito: %s", e)

    # ---- alert "85% O/U 2.5" al proprietario (@ziosapi): controlla a ogni
    #      valutazione di partita la media mobile dei pronostici O/U
    from app import ou_alert
    try:
        ou_alert.check_and_alert()
    except Exception as e:
        log.debug("ou_alert fallito: %s", e)

    # ---- pronostici (corretti con quanto imparato dagli errori + mercato +
    #      voce esterna affidabile). La calibrazione usa SOLO i round
    #      precedenti al singolo fixture (nessuna fuga di dati avanti).
    league_avg = _league_avg(standings, [f.form_home for f in now_fx] + [f.form_away for f in now_fx])
    standings_map = {r["team_id"]: r for r in standings}

    # ---- gol attesi (xG): media a squadra dagli expected_goals già nelle
    #      stats in cache (praticamente gratuita dopo il primo ciclo). Serve
    #      a rendere le valutazioni attacco/difesa più stabili (i gol reali
    #      su pochi campioni sono rumorosi).
    team_xg, league_xg = {}, None
    if config.XG_ENABLED:
        try:
            from app.analysis import xg as xg_mod
            team_ids = sorted({fx.home_id for fx in now_fx} |
                              {fx.away_id for fx in now_fx})
            team_xg = xg_mod.compute_all(client, team_ids, season_id)
            league_xg = xg_mod.league_xg(team_xg)
            store.set("team_xg", team_xg)
        except Exception as e:
            log.debug("xg non disponibile: %s", e)

    for fx in now_fx:
        calib_fx = tracker.calibration_for(fx.round, fx.start_ts)
        fx.predictions = predictor.predict_fixture(
            fx, standings_map, league_avg, calib_fx,
            tipster_registry=tipster_registry,
            team_xg=team_xg, league_xg=league_xg)

    # ---- salva i pronostici appena emessi (per confronto futuro)
    try:
        tracker.record(now_fx)
    except Exception as e:
        log.debug("tracker record fallito: %s", e)

    # ---- errore di quota / arbitraggi / movimenti
    value_flags = value_mod.detect_variables(now_fx)
    for fx in now_fx:
        fx.value_flags = [f.to_dict() for f in value_flags
                          if f.fixture == f"{fx.home} - {fx.away}"]

    store.set("sources", sources_status)
    store.set("tracking", tracking)
    store.set("calibration", calibration)
    store.set("code", f"espn-core-api@{os.uname().nodename if hasattr(os, 'uname') else 'host'}")
    store.set("fixtures", [fx.to_dict() for fx in sorted(now_fx, key=lambda x: x.start_ts)])
    store.set("value_flags", [f.to_dict() for f in value_flags])
    store.save()
    log.info("ciclo completato in %.1fs (%d partite)", time.time() - t0, len(now_fx))


# ------------------------------------------------------------------- loop
class Scheduler:
    def __init__(self, store):
        self.store = store
        self._stop = threading.Event()

    def start(self):
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _loop(self):
        log.info("scheduler avviato (intervallo %ds)", config.UPDATE_INTERVAL_SECONDS)
        first = True
        while not self._stop.is_set():
            if first:
                # primo ciclo immediato al boot (no attesa del primo tick)
                first = False
                time.sleep(15)
            try:
                run_cycle(self.store)
            except Exception as e:
                log.exception("errore nel ciclo: %s", e)
                self.store.set("last_error", str(e))
                self.store.save()
            for _ in range(int(config.UPDATE_INTERVAL_SECONDS / 5)):
                if self._stop.is_set():
                    break
                time.sleep(5)