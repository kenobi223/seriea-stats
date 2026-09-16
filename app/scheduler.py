"""Orchestratore: a ogni ciclo raccoglie dati, analizza e salva lo stato."""
import logging
import os
import threading
import time

import config
from app.analysis import form as form_mod
from app.analysis import predictor
from app.analysis import tracker
from app.analysis import value as value_mod
from app.analysis import tipsters as tipsters_mod
from app.core.models import Fixture, OddsPick
from app import notify
from app.sources import odds as odds_mod
from app.sources.client import FootballClient
from app.sources.centroquote import CentroquoteScraper, SogosportScraper

log = logging.getLogger("scheduler")


# ------------------------------------------------------------------- stato
def _restore_fixture(d):
    fx = Fixture(
        id=d.get("id"), home=d.get("home"), away=d.get("away"),
        home_id=d.get("home_id"), away_id=d.get("away_id"),
        start_ts=d.get("start_ts"), round=d.get("round"),
        venue=d.get("venue", ""), status=d.get("status", ""),
        odds=[OddsPick(o.get("source"), o.get("market"), o.get("pick"),
                       o.get("odds"), o.get("updated", 0))
              for o in d.get("odds", []) if o.get("odds")],
        history=[[OddsPick(o.get("source"), o.get("market"), o.get("pick"),
                           o.get("odds"), o.get("updated", 0))
                  for o in snap] for snap in d.get("history", [])],
        predictions=d.get("predictions", {}),
        morale=d.get("morale", {}),
        h2h=d.get("h2h", []),
        form_home=d.get("form_home", []), form_away=d.get("form_away", []),
        value_flags=d.get("value_flags", []),
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
def run_cycle(store):
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
        now_fx.append(fx)

    # salva subito i dati core: tengono vivo lo stato anche se le fasi
    # analitiche successive (forma/h2h) restano in attesa per retry.
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
                inj = 0
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
    #      (esclusivamente dagli esiti della schedina della giornata)
    try:
        notify.send_pending_wins(store)
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

    for fx in now_fx:
        calib_fx = tracker.calibration_for(fx.round, fx.start_ts)
        fx.predictions = predictor.predict_fixture(
            fx, standings_map, league_avg, calib_fx,
            tipster_registry=tipster_registry)

    # ---- salva i pronostici appena emessi (per confronto futuro)
    try:
        tracker.record(now_fx)
    except Exception as e:
        log.debug("tracker record fallito: %s", e)

    # ---- schedina della giornata: una volta per turno, prima della prima
    #      partita; valuta gli esiti a fine partite.
    try:
        from app.analysis import schedina as schedina_mod
        schedina_mod.build(store, now_fx)
        schedina_mod.evaluate(store, client)
        notify.send_pending_wins(store)
    except Exception as e:
        log.debug("schedina giornata fallita: %s", e)

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