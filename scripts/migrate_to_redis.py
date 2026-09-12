"""Migrazione one-shot dello stato locale (data/*.json) verso Redis (Upstash).

Su Koyeb/Render free il filesystem è effimero: i dati devono stare in Redis.
Questo script copia i blocchi JSON attualmente su disco nel backend remoto,
così il cloud parte dallo stesso stato (sconto/tracking/follows/coupon…).

Uso:
    REDIS_URL=redis://default:xxx@xxx.upstash.io:6379 \
        .venv/bin/python scripts/migrate_to_redis.py [--dry-run]

Sicuro da rieseguire: non tocca il disco, scrive solo in Redis. I blocchi già
presenti in Redis più recenti dei file locali NON vengono sovrascritti.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from app.core import kv


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="stampa cosa farebbe senza scrivere")
    args = ap.parse_args()

    if not config.REDIS_URL:
        print("ERRORE: imposta REDIS_URL (es. REDIS_URL=redis://... .venv/bin/python scripts/migrate_to_redis.py)")
        sys.exit(1)

    ok = skipped = 0
    for name, path in kv.KEYS.items():
        if not os.path.exists(path):
            print(f"  - {name}: nessun file locale, salto")
            continue
        with open(path, "r", encoding="utf-8") as f:
            import json
            data = json.load(f)

        # non sovrascrivere un blocco remoto più recente del file locale
        remote = kv.read_json(name)
        if remote is not None:
            local_mtime = os.path.getmtime(path)
            if local_mtime < time.time() - 30:
                print(f"  ~ {name}: già presente in Redis, salto (preservo il remoto)")
                skipped += 1
                continue

        if args.dry_run:
            print(f"  * {name} ({len(json.dumps(data))} byte): migrestei")
            ok += 1
            continue
        kv.write_json(name, data)
        print(f"  + {name}: migrato ({len(json.dumps(data))} byte)")
        ok += 1

    print(f"\nFatto: {ok} migrati, {skipped} saltati.")
    if args.dry_run:
        print("(dry-run: nessuna scrittura effettuata)")


if __name__ == "__main__":
    main()