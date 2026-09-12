FROM python:3.12-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends tor \
    && rm -rf /var/lib/apt/lists/*
RUN printf '%s\n' \
    'DataDirectory /app/tor' \
    'SocksPort 9050' \
    'ControlPort 9051' \
    'HashedControlPassword 16:57005C0CAD9AEA4960182B96F3E3AF66A3D25C1DBEF54B38B38416BAA1' \
    'Log notice file /tmp/tor.log' > /etc/tor/torrc
WORKDIR /app
RUN mkdir -p /app/tor && chmod 0777 /app/tor
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENV PYTHONUNBUFFERED=1
CMD ["/entrypoint.sh"]