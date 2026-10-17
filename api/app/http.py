"""Tiny HTTP client for the fixed, trusted platform APIs (stdlib only; honours HTTPS_PROXY). User-supplied URLs go
through app/fetch.py instead, which adds the SSRF guard."""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field


@dataclass
class HttpResponse:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def json(self):
        try:
            return json.loads(self.body or b"null")
        except ValueError:
            return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # an API answering with a redirect is unexpected; never replay credentials elsewhere
        return None


def http_request(method: str, url: str, *, headers: dict | None = None, form: dict | None = None, json_body=None, timeout: float = 20.0) -> HttpResponse:
    """Returns the response for any HTTP status. Raises OSError (URLError/timeouts) only when no response arrived."""
    data = None
    headers = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as resp:
            return HttpResponse(resp.status, resp.read(2_000_000), {k.lower(): v for k, v in resp.headers.items()})
    except urllib.error.HTTPError as err:
        return HttpResponse(err.code, err.read(2_000_000), {k.lower(): v for k, v in err.headers.items()})
