"""Import di quote manuali da file CSV (per mercati non coperti dai
comparatori, es. tiri in porta giocatore su Sisal/SNAI).

Il CSV deve avere le colonne:
  casa,trasferta,mercato,esito,bookmaker,quota

Esempio (dimensione degli esiti giocatore):
  Inter, Roma, Tiri in porta, Lautaro Martinez, sisal, 1.80
  Inter, Roma, Tiri in porta, Lautaro Martinez, snai, 2.50

Uso:
  ./.venv/bin/python scripts/import_odds.py data/quote.csv
"""
import argparse
import csv
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    args = parser.parse_args()

    entries = []
    with open(args.csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                entries.append({
                    "home": row["casa"], "away": row["trasferta"],
                    "market": row["mercato"], "pick": row["esito"],
                    "source": row["bookmaker"], "odds": float(row["quota"]),
                })
            except (KeyError, ValueError) as e:
                print(f"riga saltata ({e}): {row}")

    try:
        with open(config.MANUAL_ODDS_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except FileNotFoundError:
        existing = []

    merged = existing + entries
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.MANUAL_ODDS_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)

    print(f"Importate {len(entries)} quote (totale {len(merged)} in file.")


if __name__ == "__main__":
    main()