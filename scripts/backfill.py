#!/usr/bin/env python3
"""Backfill pronostici per partite passate (es. Giornata 3).

Usage:
    .venv/bin/python scripts/backfill.py --round 3
    .venv/bin/python scripts/backfill.py --round 3 --season-id 95836
"""
import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from app.analysis.form import build_team_form, h2h_between
from app.analysis.predictor import predict_fixture
from app.analysis.tracker import record, evaluate, analyze, load, save
from app.core.models import Fixture, OddsPick
from app.sources.sofascore import SofascoreClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("backfill")


def get_round_fixtures(client, season_id, target_round):
    """Recupera tutte le partite di una giornata specifica."""
    data = client.http.get(f"unique-tournament/23/season/{season_id}/events/last/0")
    if not data:
        return []
    
    fixtures = []
    for e in data.get("events", []):
        ri = e.get("roundInfo") or {}
        rnd = ri.get("round")
        if rnd != target_round:
            continue
        
        status = (e.get("status") or {}).get("type")
        if status != "finished":
            continue
        
        ht = e.get("homeTeam") or {}
        at = e.get("awayTeam") or {}
        hs = (e.get("homeScore") or {}).get("current")
        as_ = (e.get("awayScore") or {}).get("current")
        
        fixtures.append({
            "id": e.get("id"),
            "home": ht.get("name"),
            "away": at.get("name"),
            "home_id": ht.get("id"),
            "away_id": at.get("id"),
            "start_ts": e.get("startTimestamp"),
            "round": rnd,
            "home_score": hs,
            "away_score": as_,
        })
    
    return fixtures


def build_fixture_obj(client, fix_data, season_id):
    """Costruisce un oggetto Fixture con dati storici."""
    # Ottieni forma delle squadre (agli eventi passati, Sofascore restituisce i dati corretti)
    home_form = build_team_form(client, fix_data["home_id"], fix_data["home"], season_id)
    away_form = build_team_form(client, fix_data["away_id"], fix_data["away"], season_id)
    
    # H2H
    h2h = h2h_between(client, fix_data["home_id"], fix_data["away_id"])
    
    # Quote (per backfill potrebbero non essere disponibili, ma servono per best_bets)
    odds = []  # Le quote passate potrebbero non essere disponibili
    
    fixture = Fixture(
        id=fix_data["id"],
        home=fix_data["home"],
        away=fix_data["away"],
        home_id=fix_data["home_id"],
        away_id=fix_data["away_id"],
        start_ts=fix_data["start_ts"],
        round=fix_data["round"],
        venue="",
        status="finished",
        referee={},
    )
    fixture.form_home = home_form
    fixture.form_away = away_form
    fixture.h2h = h2h
    fixture.odds = odds
    
    return fixture


def main():
    parser = argparse.ArgumentParser(description="Backfill pronostici per giornate passate")
    parser.add_argument("--round", type=int, required=True, help="Numero della giornata da backfillare")
    parser.add_argument("--season-id", type=int, default=None, help="ID della stagione (default: dal config)")
    args = parser.parse_args()
    
    client = SofascoreClient()
    
    # Risolvi stagione
    if args.season_id:
        season_id = args.season_id
    else:
        season = client.resolve_season()
        if not season:
            log.error("Impossibile risolvere la stagione")
            return
        season_id = season["id"]
    
    log.info("Stagione: %d", season_id)
    
    # Ottieni classifica
    standings = client.standings(season_id)
    standings_map = {r["team_id"]: r for r in standings}
    
    # Calcola media lega
    total_scored = sum(r.get("gf", 0) for r in standings)
    total_conceded = sum(r.get("ga", 0) for r in standings)
    total_played = sum(r.get("played", 0) for r in standings)
    league_avg = {
        "scored": total_scored / max(total_played, 1),
        "conceded": total_conceded / max(total_played, 1),
        "home": 1.3,  # media casa storica Serie A
        "away": 1.0,
    }
    
    # Carica calibrazione esistente
    learning = load()
    calibration = learning.get("calibration") or {}
    
    # Ottieni partite della giornata
    fixtures_data = get_round_fixtures(client, season_id, args.round)
    if not fixtures_data:
        log.error("Nessuna partita trovata per la giornata %d", args.round)
        return
    
    log.info("Trovate %d partite per la giornata %d", len(fixtures_data), args.round)
    
    # Registry per evitare duplicati
    known = {r["id"] for r in learning.get("records", [])}
    
    added = 0
    for fix_data in fixtures_data:
        if fix_data["id"] in known:
            log.info("Saltato %s vs %s (già registrato)", fix_data["home"], fix_data["away"])
            continue
        
        log.info("Elaboro %s vs %s...", fix_data["home"], fix_data["away"])
        
        try:
            fixture = build_fixture_obj(client, fix_data, season_id)
            
            # Genera pronostico (senza quote, così non ci saranno best_bets)
            predictions = predict_fixture(fixture, standings_map, league_avg, calibration)
            
            # Aggiungi predictions al fixture per il record
            fixture.predictions = predictions
            
            # Salva nel tracker
            record([fixture])
            added += 1
            
            log.info("  Pronostico salvato: %s", json.dumps({
                "1x2": predictions.get("1x2"),
                "over_under": predictions.get("over_under"),
            }, indent=2))
            
            # Piccola pausa per non sovraccaricare l'API
            time.sleep(0.5)
            
        except Exception as e:
            log.error("Errore elaborando %s vs %s: %s", fix_data["home"], fix_data["away"], e)
            continue
    
    log.info("Aggiunti %d pronostici", added)
    
    # Valuta i pronostici appena aggiunti
    log.info("Valutazione pronostici...")
    evaluated = evaluate(client)
    log.info("Valutati %d pronostici", evaluated)
    
    # Analizza e calibra
    log.info("Analisi e calibrazione...")
    tracking, calibration = analyze()
    
    # Mostra risultati
    print("\n" + "="*60)
    print("RIEPILOGO BACKFILL")
    print("="*60)
    print(f"Giornata: {args.round}")
    print(f"Partite trovate: {len(fixtures_data)}")
    print(f"Pronostici aggiunti: {added}")
    print(f"Pronostici valutati: {evaluated}")
    print(f"\nTracker:")
    print(f"  Totale record: {tracking.get('records', 0)}")
    print(f"  Valutati: {tracking.get('evaluated', 0)}")
    print(f"  Tasso centramento: {tracking.get('bets_rate', 0) or 0:.1%}")
    print(f"  Brier score: {tracking.get('brier', 'N/A')}")
    
    if tracking.get("conclusions"):
        print(f"\nConclusioni:")
        for c in tracking["conclusions"]:
            print(f"  - {c}")
    
    if tracking.get("notable_misses"):
        print(f"\nErrori più clamorosi:")
        for m in tracking["notable_misses"][:3]:
            print(f"  - {m['home']} vs {m['away']} ({m['round']}): predetto {m['pick']} "
                  f"({m['prob']*100:.0f}%), risultato {m['score']}")
    
    print(f"\nCalibrazione salvata in {config.LEARNING_FILE}")


if __name__ == "__main__":
    main()
