"""Tunnel Cloudflare: rende la dashboard raggiungibile da fuori casa
(anche da un telefono su dati mobili) tramite cloudflared + trycloudflare.

Il binario può essere scaricato in ./bin/ fai da te, oppure già installato
nel PATH di sistema. Nessuna registrazione necessaria.
"""
import os
import re
import shutil
import subprocess
import time

LOG_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class Tunnel:
    def __init__(self, port, data_dir):
        self.port = port
        self.log_path = os.path.join(data_dir, "tunnel.log")
        self.binary = self._find_binary()
        self.proc = None
        self._url = None

    def _find_binary(self):
        local = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "bin", "cloudflared")
        if os.path.exists(local):
            return local
        return shutil.which("cloudflared")

    @property
    def available(self):
        return self.binary is not None

    def start(self):
        if not self.available or self.proc:
            return False
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        log_fh = open(self.log_path, "ab")
        self.proc = subprocess.Popen(
            [self.binary, "tunnel", "--url", f"http://127.0.0.1:{self.port}",
             "--protocol", "http2",
             "--no-autoupdate", "--logfile", self.log_path],
            stdout=log_fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True)
        return True

    def status(self):
        running = self.proc is not None and self.proc.poll() is None
        if self._url is None:
            self._url = self._read_url()
        return {"running": running, "url": self._url}

    def _read_url(self):
        try:
            with open(self.log_path, "r", errors="ignore") as fh:
                data = fh.read()
            urls = LOG_RE.findall(data)
            if urls:
                return urls[-1]
        except OSError:
            pass
        return None

    def stop(self):
        if self.proc:
            try:
                self.proc.terminate()
            except OSError:
                pass
            self.proc = None


def wait_url(tunnel, timeout=30):
    """Attende che il tunnel produca un URL pubblico."""
    end = time.time() + timeout
    while time.time() < end:
        st = tunnel.status()
        if st["url"]:
            return st["url"]
        time.sleep(1.5)
    return None