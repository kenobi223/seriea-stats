FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends tor && rm -rf /var/lib/apt/lists/*
RUN echo 'SocksPort 9050' >> /etc/tor/torrc && \
    echo 'ControlPort 9051' >> /etc/tor/torrc && \
    echo 'HashedControlPassword 16:57005C0CAD9AEA4960182B96F3E3AF66A3D25C1DBEF54B38B38416BAA1' >> /etc/tor/torrc
EXPOSE 9050 9051
CMD ["tor"]
