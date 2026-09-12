"""Client HTTP comune con retry, UA, rate limiting e failover verso
proxy SOCKS (Tor) quando la connessione diretta viene bloccata."""
import logging
import random
import socket
import threading
import time

import requests

from config import ASSETS_UA, HTTP_RETRIES, HTTP_TIMEOUT, POLITE_DELAY
from config import TOR_CONTROL_HOST, TOR_CONTROL_PORT, TOR_CONTROL_PASSWORD
from config import TOR_FAILOVER_ON_BLOCK, TOR_MAX_RETRIES, TOR_SOCKS_PROXY, TOR_ROTATE_EVERY

log = logging.getLogger("http")

_lock = threading.Lock()
_last_request = 0.0
# contatore globale richieste dirette, per ruotare il circuito Tor di tanto
# in tanto anche senza blocchi espliciti
_requests_since_rotate = 0


def tor_newnym():
    """Ordina a Tor di cambiare circuito (e quindi IP d'uscita).
    Best-effort: se il control port non è aperto ritorna False senza errori."""
    if not TOR_CONTROL_PORT:
        return False
    try:
        with socket.create_connection((TOR_CONTROL_HOST, TOR_CONTROL_PORT), timeout=3) as s:
            f = s.makefile("rwb")
            if TOR_CONTROL_PASSWORD:
                f.write(b'AUTHENTICATE "' + TOR_CONTROL_PASSWORD.encode() + b'"\r\n')
            else:
                f.write(b"AUTHENTICATE\r\n")
            f.flush()
            line = f.readline()
            if not line.startswith(b"250"):
                return False
            f.write(b"SIGNAL NEWNYM\r\n")
            f.flush()
            line = f.readline()
            return line.startswith(b"250")
    except OSError:
        return False


class HTTPClient:
    def __init__(self, base=None, delay=POLITE_DELAY, host=None, proxy=None,
                 tor_mode="auto"):
        """tor_mode:
        - "auto":   connessione diretta, passa a Tor solo se bloccata (403/429)
        - "always": parte sempre da Tor (cambia IP con la rotazione)
        - "never":  mai via Tor (proxy disattivato)"""
        self.base = base
        self.delay = delay
        if tor_mode == "never":
            self.proxy = None
        else:
            self.proxy = proxy or TOR_SOCKS_PROXY
        self.tor_mode = tor_mode
        self.bypass_proxy = tor_mode == "never"  # True = senza failover
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": ASSETS_UA})
        self._zone = host or "default"
        self._use_tor = tor_mode == "always"

    def _pace(self):
        global _last_request
        with _lock:
            wait = self.delay - (time.time() - _last_request)
            if wait > 0:
                time.sleep(wait + random.uniform(0.0, 0.25))
            _last_request = time.time()

    def _send(self, url, params, timeout, headers, proxy):
        global _requests_since_rotate
        if proxy:
            if _requests_since_rotate >= TOR_ROTATE_EVERY:
                _requests_since_rotate = 0
                log.info("rotazione circuito Tor (%d richieste)", TOR_ROTATE_EVERY)
                tor_newnym()
            proxies = {"http": proxy, "https": proxy}
            resp = self.session.get(url, params=params, timeout=timeout,
                                    headers=headers, proxies=proxies)
        else:
            resp = self.session.get(url, params=params, timeout=timeout,
                                    headers=headers)
        _requests_since_rotate += 1
        return resp

    def get(self, path, *, params=None, timeout=HTTP_TIMEOUT, as_json=True,
            retries=HTTP_RETRIES, headers=None):
        url = path if path.startswith("http") else (self.base.rstrip("/") + "/" + path.lstrip("/"))
        # quando usiamo Tor abbiamo bisogno di più tentativi perché diversi
        # nodi d'uscita sono bloccati: ruotiamo il circuito finché non passa
        max_retries = TOR_MAX_RETRIES if (self._use_tor or self.proxy) else retries
        for attempt in range(max_retries):
            self._pace()
            use_tor = self._use_tor
            try:
                resp = self._send(url, params, timeout, headers,
                                  self.proxy if use_tor else None)
                if resp.status_code in (403, 429, 503) and use_tor:
                    if attempt < max_retries - 1:
                        log.warning("proxy Tor bloccato (HTTP %s): cambio circuito (%d)",
                                    resp.status_code, attempt + 1)
                        tor_newnym()
                        time.sleep(1 + attempt)
                        continue
                if resp.status_code in (403, 429) and TOR_FAILOVER_ON_BLOCK and not use_tor:
                    self._use_tor = True
                    log.warning("blocco HTTP %s da %s: passo a proxy Tor", resp.status_code, url)
                    tor_newnym()
                    continue
                if resp.status_code >= 400:
                    if resp.status_code in (429, 503) and attempt < max_retries - 1:
                        time.sleep(2 * (attempt + 1))
                        continue
                    log.warning("GET %s -> HTTP %s", url, resp.status_code)
                    return None
                return resp.json() if as_json else resp
            except requests.RequestException as e:
                if self._use_tor:
                    tor_newnym()
                log.warning("GET %s fallito (tentativo %d): %s", url, attempt + 1, e)
                time.sleep(1.5 * (attempt + 1))
        return None