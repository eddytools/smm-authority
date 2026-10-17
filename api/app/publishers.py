"""LinkedIn and X: OAuth connect, token refresh and posting. Each provider takes an injectable `http` callable, so
all of this is tested against canned responses (see tests/test_publishers.py).

NOT VERIFIED AGAINST THE LIVE APIS: the build environment had no developer credentials and could not reach these
hosts. The OAuth endpoints, scopes, LinkedIn's escaping rules and headers were checked against search snippets of the
official docs; the exact POST /2/tweets request body is written from memory. Run one real post per platform before
relying on this, and confirm LinkedIn's current API version (SMM_LINKEDIN_API_VERSION)."""

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

from app.drafting import x_parts
from app.framework import CHAR_LIMIT
from app.http import HttpResponse, http_request


class ProviderError(Exception):
    """transient: worth retrying later. reauth: the stored authorisation no longer works, the user must reconnect."""

    def __init__(self, message: str, *, transient: bool = False, reauth: bool = False):
        super().__init__(message)
        self.message, self.transient, self.reauth = message, transient, reauth


class PartialPublishError(ProviderError):
    """A thread went out only partly. Retrying would duplicate the parts already posted, so it is never retried."""

    def __init__(self, message: str, *, first_id: str, first_url: str, posted: int, total: int):
        super().__init__(message)
        self.first_id, self.first_url, self.posted, self.total = first_id, first_url, posted, total


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_in: int | None


@dataclass
class Account:
    external_id: str
    name: str


@dataclass
class PostResult:
    external_id: str
    url: str


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:100]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _body_message(resp: HttpResponse) -> str:
    data = resp.json()
    if isinstance(data, dict):
        for key in ("message", "detail", "error_description", "title", "error"):
            if isinstance(data.get(key), str):
                return data[key][:200]
        errors = data.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict) and isinstance(errors[0].get("message"), str):
            return errors[0]["message"][:200]
    return (resp.body or b"")[:120].decode(errors="replace").strip()


def _raise_for(resp: HttpResponse, what: str) -> None:
    """Map an HTTP failure to retry / reconnect / give-up so callers never inspect status codes."""
    if resp.status < 400:
        return
    detail = _body_message(resp)
    if resp.status == 401:
        raise ProviderError(f"{what}: the connection was rejected (401). Reconnect the account.", reauth=True)
    if resp.status == 429 or resp.status >= 500:
        raise ProviderError(f"{what}: the platform is busy or rate-limiting ({resp.status}). {detail}".strip(), transient=True)
    raise ProviderError(f"{what}: {resp.status} {detail}".strip())


def _call(http, method: str, url: str, what: str, **kw) -> HttpResponse:
    try:
        resp = http(method, url, **kw)
    except OSError as exc:  # no response at all: network, DNS, timeout
        raise ProviderError(f"{what}: could not reach the platform ({type(exc).__name__}).", transient=True)
    _raise_for(resp, what)
    return resp


def _tokens(resp: HttpResponse, what: str) -> TokenSet:
    data = resp.json()
    if not isinstance(data, dict) or not data.get("access_token"):
        raise ProviderError(f"{what}: unexpected response from the platform.")
    expires = data.get("expires_in")
    return TokenSet(data["access_token"], data.get("refresh_token"), int(expires) if isinstance(expires, (int, str)) and str(expires).isdigit() else None)


# --- LinkedIn --------------------------------------------------------------------------

_LITTLE_TEXT = re.compile(r"([\\|{}@\[\]()<>#*_~])")


def escape_little_text(text: str) -> str:
    """LinkedIn parses `commentary` as 'little text': | { } @ [ ] ( ) < > # \\ * _ ~ are markup, and an unescaped
    parenthesis can silently truncate the post. Escape every one once so the post shows exactly what the author wrote.
    Trade-off: hashtags post as plain text, not clickable links."""
    return _LITTLE_TEXT.sub(r"\\\1", text)


class LinkedIn:
    platform = "linkedin"
    label = "LinkedIn"
    uses_pkce = False
    scope = "openid profile w_member_social"

    def __init__(self, client_id: str | None, client_secret: str | None, api_version: str, http=http_request):
        self.client_id, self.client_secret, self.api_version, self.http = client_id, client_secret, api_version, http

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def authorize_url(self, redirect_uri: str, state: str, code_challenge: str | None) -> str:
        q = urlencode({"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect_uri, "state": state, "scope": self.scope})
        return f"https://www.linkedin.com/oauth/v2/authorization?{q}"

    def _token(self, form: dict, what: str) -> TokenSet:
        form = {**form, "client_id": self.client_id, "client_secret": self.client_secret}
        return _tokens(_call(self.http, "POST", "https://www.linkedin.com/oauth/v2/accessToken", what, form=form), what)

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None) -> TokenSet:
        return self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}, "LinkedIn sign-in")

    def refresh(self, refresh_token: str) -> TokenSet:  # only issued to some LinkedIn apps; most connections just expire after ~60 days
        return self._token({"grant_type": "refresh_token", "refresh_token": refresh_token}, "LinkedIn token refresh")

    def account(self, access_token: str) -> Account:
        data = _call(self.http, "GET", "https://api.linkedin.com/v2/userinfo", "LinkedIn profile lookup", headers={"Authorization": f"Bearer {access_token}"}).json()
        if not isinstance(data, dict) or not data.get("sub"):
            raise ProviderError("LinkedIn profile lookup: unexpected response.")
        return Account(str(data["sub"]), str(data.get("name") or "LinkedIn member"))

    def publish(self, access_token: str, account_id: str, account_name: str, text: str) -> PostResult:
        if len(text) > CHAR_LIMIT["linkedin"]:
            raise ProviderError(f"This post is {len(text)} characters, over LinkedIn's {CHAR_LIMIT['linkedin']} limit.")
        body = {
            "author": f"urn:li:person:{account_id}",
            "commentary": escape_little_text(text),
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        headers = {"Authorization": f"Bearer {access_token}", "LinkedIn-Version": self.api_version, "X-Restli-Protocol-Version": "2.0.0"}
        resp = _call(self.http, "POST", "https://api.linkedin.com/rest/posts", "LinkedIn post", headers=headers, json_body=body)
        urn = resp.headers.get("x-restli-id") or resp.headers.get("x-linkedin-id")
        if not urn:
            raise ProviderError("LinkedIn post: the platform accepted the request but returned no post id. Check LinkedIn before retrying.")
        return PostResult(urn, f"https://www.linkedin.com/feed/update/{urn}/")


# --- X ---------------------------------------------------------------------------------

class X:
    platform = "x"
    label = "X"
    uses_pkce = True
    scope = "tweet.read tweet.write users.read offline.access"

    def __init__(self, client_id: str | None, client_secret: str | None, http=http_request):
        self.client_id, self.client_secret, self.http = client_id, client_secret, http

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def authorize_url(self, redirect_uri: str, state: str, code_challenge: str | None) -> str:
        q = urlencode({"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect_uri, "scope": self.scope, "state": state,
                       "code_challenge": code_challenge, "code_challenge_method": "S256"})
        return f"https://x.com/i/oauth2/authorize?{q}"

    def _token(self, form: dict, what: str) -> TokenSet:
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()  # confidential client
        return _tokens(_call(self.http, "POST", "https://api.x.com/2/oauth2/token", what, headers={"Authorization": f"Basic {basic}"}, form={**form, "client_id": self.client_id}), what)

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None) -> TokenSet:
        return self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": code_verifier or ""}, "X sign-in")

    def refresh(self, refresh_token: str) -> TokenSet:  # X rotates refresh tokens: the new one must be stored before it is used
        return self._token({"grant_type": "refresh_token", "refresh_token": refresh_token}, "X token refresh")

    def account(self, access_token: str) -> Account:
        data = _call(self.http, "GET", "https://api.x.com/2/users/me", "X profile lookup", headers={"Authorization": f"Bearer {access_token}"}).json()
        user = data.get("data") if isinstance(data, dict) else None
        if not isinstance(user, dict) or not user.get("id") or not user.get("username"):
            raise ProviderError("X profile lookup: unexpected response.")
        return Account(str(user["id"]), f"@{user['username']}")

    def publish(self, access_token: str, account_id: str, account_name: str, text: str) -> PostResult:
        parts = x_parts(text)
        for i, part in enumerate(parts, 1):
            if len(part) > CHAR_LIMIT["x"]:
                where = f"Part {i}" if len(parts) > 1 else "This post"
                raise ProviderError(f"{where} is {len(part)} characters, over X's {CHAR_LIMIT['x']} limit.")
        username = account_name.lstrip("@")
        first_id, reply_to = None, None
        for i, part in enumerate(parts, 1):
            body: dict = {"text": part}
            if reply_to:
                body["reply"] = {"in_reply_to_tweet_id": reply_to}
            try:
                data = _call(self.http, "POST", "https://api.x.com/2/tweets", "X post", headers={"Authorization": f"Bearer {access_token}"}, json_body=body).json()
                tweet_id = str(data["data"]["id"])
            except (ProviderError, KeyError, TypeError) as exc:
                message = exc.message if isinstance(exc, ProviderError) else "X post: unexpected response from the platform."
                if first_id is None:
                    raise exc if isinstance(exc, ProviderError) else ProviderError(message)
                raise PartialPublishError(f"Thread incomplete: posted {i - 1} of {len(parts)} parts. {message} Finish it on X by hand.", first_id=first_id,
                                          first_url=f"https://x.com/{username}/status/{first_id}", posted=i - 1, total=len(parts))
            first_id = first_id or tweet_id
            reply_to = tweet_id
        return PostResult(first_id, f"https://x.com/{username}/status/{first_id}")
