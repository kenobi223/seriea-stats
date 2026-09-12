#!/bin/bash
# Setup one-shot su una Oracle Cloud Always Free VM (Ubuntu 22.04/24.04).
# Dopo aver copiato il pacchetto sulla VM:
#   scp -P 22 /tmp/seriea-stats.tar.gz ubuntu@<IP>:/tmp/
#   ssh ubuntu@<IP>
#   tar xzf /tmp/seriea-stats.tar.gz -C ~/
#   cd seriea-stats && bash deploy/setup-oracle.sh
set -euo pipefail

echo "== 1/5 Installo Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  echo "Rilancia la sessione (logout/login) per usare docker senza sudo, poi riesegui."
  # not newgrp in una pipeline; il prossimo run userà docker già installato
  exit 0
fi

echo "== 2/5 Verifico docker compose"
docker compose version >/dev/null 2>&1 || \
  sudo apt-get install -y docker-compose-plugin

echo "== 3/5 Cedo il token bot"
if [ -f .env ]; then
  echo "Trovo già un .env: lo lascio."
else
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    echo "⚠  Manca TELEGRAM_BOT_TOKEN."
    echo "    Metti il token in un file .env (una riga):"
    echo '    TELEGRAM_BOT_TOKEN=123456:AAAA'
    exit 1
  fi
  echo "TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}" > .env
fi

echo "== 4/5 Costruisco e avvio (Tor + app)"
docker compose up -d --build

echo "== 5/5 Stato"
sleep 20
docker compose ps

echo ""
echo "Fatto. Collegamenti utili:"
echo "  logs : docker compose logs -f app"
echo "  web  : ssh -L 8765:127.0.0.1:8765 ubuntu@<IP>  poi aprire http://127.0.0.1:8765"