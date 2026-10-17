import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import app.fetch as fetch_mod
from app.fetch import MAX_BYTES, FetchError, safe_fetch

UA = "test-agent"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/ok":
            body = b"<rss/>"
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
        elif self.path == "/to-private":
            self.send_response(302)
            self.send_header("Location", f"http://10.0.0.5:{self.server.server_port}/ok")
            self.end_headers()
        elif self.path == "/big":
            self.send_response(200)
            self.send_header("Content-Length", str(MAX_BYTES + 10))
            self.end_headers()
            self.wfile.write(b"x" * 1000)
        elif self.path == "/ua":
            body = self.headers.get("User-Agent", "").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://0.0.0.0/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://100.64.0.1/",
    ],
)
def test_private_and_internal_addresses_are_blocked(url):
    with pytest.raises(FetchError, match="non-public"):
        safe_fetch(url, user_agent=UA)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x", "http:///nohost", "http://user:pw@example.com/"])
def test_bad_schemes_and_credentials_are_rejected(url):
    with pytest.raises(FetchError):
        safe_fetch(url, user_agent=UA)


def test_happy_path_redirect_and_user_agent(server):
    assert safe_fetch(f"{server}/ok", user_agent=UA, allow_private=True).body == b"<rss/>"
    r = safe_fetch(f"{server}/redir", user_agent=UA, allow_private=True)
    assert r.body == b"<rss/>" and r.final_url.endswith("/ok")
    assert safe_fetch(f"{server}/ua", user_agent=UA, allow_private=True).body == b"test-agent"


def test_errors_size_and_redirect_limits(server):
    with pytest.raises(FetchError, match="HTTP 404"):
        safe_fetch(f"{server}/nope", user_agent=UA, allow_private=True)
    with pytest.raises(FetchError, match="too large"):
        safe_fetch(f"{server}/big", user_agent=UA, allow_private=True)
    with pytest.raises(FetchError, match="redirects"):
        safe_fetch(f"{server}/loop", user_agent=UA, allow_private=True)
    with pytest.raises(FetchError):
        safe_fetch("http://127.0.0.1:1/", user_agent=UA, allow_private=True, timeout=1)  # connection refused


def test_every_redirect_hop_is_validated(server, monkeypatch):
    real = fetch_mod._check_ip

    def only_loopback(ip, allow_private):
        if ip != "127.0.0.1":
            raise FetchError("URL points to a non-public address")

    monkeypatch.setattr(fetch_mod, "_check_ip", only_loopback)
    with pytest.raises(FetchError, match="non-public"):
        safe_fetch(f"{server}/to-private", user_agent=UA, allow_private=True)
    monkeypatch.setattr(fetch_mod, "_check_ip", real)


# --- TLS: pinned-IP connection must still verify the hostname/certificate -------------

import shutil
import ssl
import subprocess

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI not available")


@pytest.fixture(scope="module")
def tls_server(tmp_path_factory):
    d = tmp_path_factory.mktemp("tls")
    cert, key = d / "cert.pem", d / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1",
         "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
        check=True, capture_output=True,
    )
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"https://localhost:{srv.server_port}", cert
    srv.shutdown()


@needs_openssl
def test_https_works_when_the_certificate_is_trusted(tls_server, monkeypatch):
    url, cert = tls_server
    original = ssl.create_default_context  # captured before patching: ssl is a shared module

    def trusting_context():
        ctx = original()
        ctx.load_verify_locations(cafile=str(cert))
        return ctx

    monkeypatch.setattr(fetch_mod.ssl, "create_default_context", trusting_context)
    assert safe_fetch(f"{url}/ok", user_agent=UA, allow_private=True).body == b"<rss/>"


@needs_openssl
def test_https_rejects_an_untrusted_certificate(tls_server):
    url, _ = tls_server
    with pytest.raises(FetchError, match="SSL"):
        safe_fetch(f"{url}/ok", user_agent=UA, allow_private=True)  # default trust store: self-signed must fail
