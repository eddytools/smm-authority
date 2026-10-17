"""SSRF-safe HTTP GET for user-supplied URLs (RSS feeds etc).

Guards: http/https only, no embedded credentials, every hop (including redirects) must resolve to a public
IP, the connection is pinned to the validated IP (so DNS cannot change between check and connect) while TLS
still verifies the real hostname, bounded redirects/size/time. stdlib only.
"""

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

MAX_BYTES = 2_000_000
REDIRECT_CODES = {301, 302, 303, 307, 308}


class FetchError(Exception):
    pass


@dataclass
class FetchResult:
    status: int
    body: bytes
    final_url: str
    content_type: str


def _check_ip(ip: str, allow_private: bool) -> None:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if not allow_private and not addr.is_global:
        raise FetchError("URL points to a non-public address")


def _resolve(host: str, port: int, allow_private: bool) -> str:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise FetchError("Could not resolve host")
    ips = list(dict.fromkeys(info[4][0] for info in infos))
    if not ips:
        raise FetchError("Could not resolve host")
    for ip in ips:  # every answer must be public, not just the first
        _check_ip(ip, allow_private)
    return ips[0]


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout):
        self._ctx = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self._ctx)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._ctx.wrap_socket(sock, server_hostname=self.host)


def safe_fetch(
    url: str,
    *,
    user_agent: str,
    timeout: float = 10.0,
    max_redirects: int = 3,
    allow_private: bool = False,
    accept: str = "*/*",
) -> FetchResult:
    for _ in range(max_redirects + 1):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise FetchError("Only http(s) URLs are allowed")
        if parsed.username or parsed.password:
            raise FetchError("URLs with credentials are not allowed")
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            raise FetchError("Invalid port")
        ip = _resolve(parsed.hostname, port, allow_private)
        conn_cls = _PinnedHTTPS if parsed.scheme == "https" else _PinnedHTTP
        conn = conn_cls(parsed.hostname, port, ip, timeout)
        try:
            path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
            conn.request("GET", path, headers={"User-Agent": user_agent, "Accept": accept, "Accept-Encoding": "identity", "Connection": "close"})
            resp = conn.getresponse()
            if resp.status in REDIRECT_CODES:
                location = resp.getheader("Location")
                if not location:
                    raise FetchError("Redirect without Location")
                url = urljoin(url, location)
                continue
            if not 200 <= resp.status < 300:
                raise FetchError(f"HTTP {resp.status}")
            declared = resp.getheader("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_BYTES:
                raise FetchError("Response too large")
            body = resp.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise FetchError("Response too large")
            return FetchResult(resp.status, body, url, resp.getheader("Content-Type") or "")
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            if isinstance(exc, FetchError):
                raise
            raise FetchError(f"Connection failed: {type(exc).__name__}")
        finally:
            conn.close()
    raise FetchError("Too many redirects")
