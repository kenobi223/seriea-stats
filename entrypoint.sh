#!/bin/sh
set -e

# Avvia Tor (SOCKS 9050 + control 9051 per il cambio identità) e app.
tor --runasdaemon 1 --log "notice file /tmp/tor.log" || true

# attende che la porta SOCKS sia accettante
i=0
while [ "$i" -lt 60 ]; do
  if python -c "import socket,sys; s=socket.create_connection(('127.0.0.1',9050),1); s.close(); sys.exit(0)" 2>/dev/null; then
    break
  fi
  sleep 1
  i=$((i+1))
done

exec python /app/run.py "$@"