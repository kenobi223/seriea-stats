#!/bin/bash
# Impacchetta il progetto pronto per il deploy su Oracle Cloud Always Free.
# Uso (da questa macchina):
#   ./deploy/package.sh            -> crea seriea-stats.tar.gz in /tmp
#   ./deploy/package.sh ~/proj.tgz -> crea il pacchetto nel percorso scelto
set -euo pipefail

SRC="/home/ziosapi/seriea-stats"
DEST="${1:-/tmp/seriea-stats.tar.gz}"

cd "$SRC"
tar --exclude=.venv --exclude=data --exclude=logs --exclude=.git \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
    --exclude=deploy/oracle-setup.sh \
    -czf "$DEST" \
    Dockerfile Dockerfile.oc docker-compose.yml render.yaml requirements.txt \
    run.py config.py entrypoint.sh assets \
    app deploy/setup-oracle.sh deploy/package.sh .env.example .dockerignore tor

echo "Pacchetto: $DEST"
ls -lh "$DEST"