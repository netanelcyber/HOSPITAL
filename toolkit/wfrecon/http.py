"""Thin HTTP client wrapper used by all recon modules.

Uses only the Python standard library so the toolkit runs with zero pip installs.
Python 3.5 compatible (no f-strings, dataclasses, or PEP 526 annotations).
"""

import gzip
import ssl
import time
import urllib.error
import urllib.request
from typing import Optional

DEFAULT_UA = "wfrecon/0.1 (+authorized-lab-testing)"


class Response(object):
    def __init__(self, url, status, headers, body, elapsed_ms, error=None):
        self.url = url
        self.status = status
        self.headers = headers
        self.body = body
        self.elapsed_ms = elapsed_ms
        self.error = error


class Client(object):
    def __init__(self, base_url, timeout=10.0, user_agent=DEFAULT_UA,
                 verify_tls=True, delay=0.0):
        self.base_url = base_url
        self.timeout = timeout
        self.user_agent = user_agent
        self.verify_tls = verify_tls
        self.delay = delay  # polite delay between requests (seconds)
        self._last = 0.0

    def _ctx(self):
        if self.base_url.startswith("https") and not self.verify_tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return None

    def get(self, path="/", extra_headers=None, method="GET", data=None,
            allow_redirects=True):
        if self.delay and self._last:
            wait = self.delay - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)

        if path.startswith("http"):
            url = path
        else:
            url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip"}
        if extra_headers:
            headers.update(extra_headers)

        req = urllib.request.Request(url, headers=headers, method=method, data=data)
        opener = urllib.request.urlopen
        if not allow_redirects:
            handler = _NoRedirect()
            ctx = self._ctx()
            handlers = [handler]
            if ctx is not None:
                handlers.append(urllib.request.HTTPSHandler(context=ctx))
            opener = urllib.request.build_opener(*handlers).open
        start = time.time()
        try:
            if allow_redirects:
                r = opener(req, timeout=self.timeout, context=self._ctx())
            else:
                r = opener(req, timeout=self.timeout)
            try:
                raw = r.read()
                status = getattr(r, "status", None) or r.getcode()
                body = _decode(raw, r.headers.get("Content-Encoding"))
                self._last = time.time()
                return Response(url, status, dict(r.headers), body,
                                (time.time() - start) * 1000)
            finally:
                r.close()
        except urllib.error.HTTPError as e:
            raw = e.read()
            enc = e.headers.get("Content-Encoding") if e.headers else None
            body = _decode(raw, enc)
            self._last = time.time()
            return Response(url, e.code, dict(e.headers or {}), body,
                            (time.time() - start) * 1000)
        except Exception as e:  # noqa: BLE001 — surface any transport error to caller
            self._last = time.time()
            return Response(url, 0, {}, "", (time.time() - start) * 1000, error=str(e))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Turn 3xx responses into HTTPError so the Location header is preserved."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _decode(raw, encoding):
    if encoding and "gzip" in encoding.lower():
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    return raw.decode("utf-8", errors="replace")
