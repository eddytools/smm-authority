import base64
import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest

from app.crypto import TokenCipher, TokenCipherError
from app.http import HttpResponse
from app.publishers import PartialPublishError, ProviderError, X, LinkedIn, escape_little_text, pkce_pair


class Recorder:
    """Fake `http` callable: returns queued responses (or raises queued exceptions) and remembers every call."""

    def __init__(self, *responses):
        self.queue, self.calls = list(responses), []

    def __call__(self, method, url, *, headers=None, form=None, json_body=None, timeout=20.0):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "form": form, "json": json_body})
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def resp(status=200, body=None, headers=None):
    return HttpResponse(status, json.dumps(body).encode() if body is not None else b"", {k.lower(): v for k, v in (headers or {}).items()})


# --- crypto ----------------------------------------------------------------------------

def test_tokens_roundtrip_and_are_not_stored_in_clear():
    from cryptography.fernet import Fernet

    c = TokenCipher(Fernet.generate_key().decode())
    enc = c.encrypt("super-secret-access-token")
    assert "super-secret" not in enc and c.decrypt(enc) == "super-secret-access-token"
    assert c.encrypt("x") != c.encrypt("x")  # randomised


def test_key_rotation_and_bad_keys():
    from cryptography.fernet import Fernet

    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    stored = TokenCipher(old).encrypt("t")
    rotated = TokenCipher(f"{new},{old}")  # first key encrypts, any key decrypts
    assert rotated.decrypt(stored) == "t" and TokenCipher(new).decrypt(rotated.encrypt("t")) == "t"
    with pytest.raises(TokenCipherError):
        TokenCipher(new).decrypt(stored)  # old key dropped: clear error, not garbage
    with pytest.raises(TokenCipherError):
        TokenCipher("not-a-key")
    with pytest.raises(TokenCipherError):
        TokenCipher(new).decrypt("tampered")


# --- LinkedIn --------------------------------------------------------------------------

def test_little_text_escaping_covers_every_reserved_character_once():
    raw = r"Grew 40% (in 90 days) | {team} @ acme [proof] <b> #growth *bold* _it_ ~x~ \path"
    out = escape_little_text(raw)
    for ch in "|{}@[]()<>#*_~\\":
        assert out.count("\\" + ch) == raw.count(ch), ch
    assert escape_little_text("Plain text, with punctuation: yes!") == "Plain text, with punctuation: yes!"


def test_linkedin_authorize_url():
    li = LinkedIn("cid", "secret", "202609")
    q = parse_qs(urlparse(li.authorize_url("http://api/cb", "STATE", None)).query)
    assert q["client_id"] == ["cid"] and q["state"] == ["STATE"] and q["redirect_uri"] == ["http://api/cb"]
    assert q["scope"] == ["openid profile w_member_social"] and "code_challenge" not in q


def test_linkedin_exchange_account_and_publish_request_shape():
    http = Recorder(resp(200, {"access_token": "AT", "expires_in": 5183999, "refresh_token": "RT"}), resp(200, {"sub": "abc123", "name": "Maya Founder"}),
                    resp(201, None, {"x-restli-id": "urn:li:share:777"}))
    li = LinkedIn("cid", "secret", "202609", http=http)
    tokens = li.exchange_code("CODE", "http://api/cb", None)
    assert (tokens.access_token, tokens.refresh_token, tokens.expires_in) == ("AT", "RT", 5183999)
    token_call = http.calls[0]
    assert token_call["url"] == "https://www.linkedin.com/oauth/v2/accessToken" and token_call["form"]["client_secret"] == "secret" and token_call["form"]["code"] == "CODE"
    acct = li.account("AT")
    assert (acct.external_id, acct.name) == ("abc123", "Maya Founder")

    post = li.publish("AT", "abc123", "Maya Founder", "Results (so far): 40%")
    assert post.external_id == "urn:li:share:777" and post.url == "https://www.linkedin.com/feed/update/urn:li:share:777/"
    call = http.calls[2]
    assert call["url"] == "https://api.linkedin.com/rest/posts" and call["headers"]["Authorization"] == "Bearer AT"
    assert call["headers"]["LinkedIn-Version"] == "202609" and call["headers"]["X-Restli-Protocol-Version"] == "2.0.0"
    body = call["json"]
    assert body["author"] == "urn:li:person:abc123" and body["commentary"] == r"Results \(so far\): 40%"
    assert body["visibility"] == "PUBLIC" and body["lifecycleState"] == "PUBLISHED"


def test_linkedin_refuses_overlong_posts_without_calling_the_api():
    http = Recorder()
    with pytest.raises(ProviderError, match="over LinkedIn's 3000 limit"):
        LinkedIn("c", "s", "202609", http=http).publish("AT", "a", "n", "x" * 3001)
    assert http.calls == []


def test_linkedin_success_without_an_id_is_flagged_not_retried_blindly():
    li = LinkedIn("c", "s", "202609", http=Recorder(resp(201, None)))
    with pytest.raises(ProviderError, match="no post id") as e:
        li.publish("AT", "a", "n", "hi")
    assert not e.value.transient  # retrying could double-post, so a human checks first


# --- X ---------------------------------------------------------------------------------

def test_pkce_pair_is_valid_s256():
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert pkce_pair()[0] != verifier


def test_x_authorize_url_and_token_requests():
    http = Recorder(resp(200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 7200}), resp(200, {"access_token": "AT2", "refresh_token": "RT2", "expires_in": 7200}))
    x = X("cid", "csecret", http=http)
    q = parse_qs(urlparse(x.authorize_url("http://api/cb", "S", "CHAL")).query)
    assert urlparse(x.authorize_url("http://api/cb", "S", "CHAL")).netloc == "x.com"
    assert q["code_challenge"] == ["CHAL"] and q["code_challenge_method"] == ["S256"] and "offline.access" in q["scope"][0] and "tweet.write" in q["scope"][0]
    x.exchange_code("CODE", "http://api/cb", "VERIFIER")
    first = http.calls[0]
    assert first["url"] == "https://api.x.com/2/oauth2/token" and first["form"]["code_verifier"] == "VERIFIER"
    assert first["headers"]["Authorization"] == "Basic " + base64.b64encode(b"cid:csecret").decode()
    refreshed = x.refresh("RT")
    assert http.calls[1]["form"]["grant_type"] == "refresh_token" and http.calls[1]["form"]["refresh_token"] == "RT" and refreshed.refresh_token == "RT2"


def test_x_account_and_single_post():
    http = Recorder(resp(200, {"data": {"id": "42", "username": "mayafounder"}}), resp(201, {"data": {"id": "1001", "text": "hi"}}))
    x = X("c", "s", http=http)
    acct = x.account("AT")
    assert (acct.external_id, acct.name) == ("42", "@mayafounder")
    post = x.publish("AT", "42", "@mayafounder", "Hello world")
    assert post.external_id == "1001" and post.url == "https://x.com/mayafounder/status/1001"
    assert http.calls[1]["url"] == "https://api.x.com/2/tweets" and http.calls[1]["json"] == {"text": "Hello world"}
    assert http.calls[1]["headers"]["Authorization"] == "Bearer AT"


def test_x_thread_is_chained_as_replies():
    http = Recorder(*[resp(201, {"data": {"id": str(100 + i)}}) for i in range(3)])
    post = X("c", "s", http=http).publish("AT", "42", "@maya", "1/ First part\n\n2/ Second part\n\n3/ Third part")
    assert post.external_id == "100" and post.url.endswith("/status/100")
    assert [c["json"]["text"] for c in http.calls] == ["First part", "Second part", "Third part"]
    assert "reply" not in http.calls[0]["json"]
    assert http.calls[1]["json"]["reply"] == {"in_reply_to_tweet_id": "100"} and http.calls[2]["json"]["reply"] == {"in_reply_to_tweet_id": "101"}


def test_x_thread_that_fails_midway_is_reported_as_partial_never_a_clean_failure():
    http = Recorder(resp(201, {"data": {"id": "100"}}), resp(503, {"title": "Service Unavailable"}))
    with pytest.raises(PartialPublishError) as e:
        X("c", "s", http=http).publish("AT", "42", "@maya", "1/ one\n\n2/ two\n\n3/ three")
    assert (e.value.posted, e.value.total, e.value.first_id) == (1, 3, "100") and "Finish it on X by hand" in e.value.message
    assert not e.value.transient  # retrying would post part 1 again


def test_x_first_part_failure_is_an_ordinary_error_and_overlong_parts_never_reach_the_api():
    with pytest.raises(ProviderError) as e:
        X("c", "s", http=Recorder(resp(429, {"title": "Too Many Requests"}))).publish("AT", "42", "@m", "hi")
    assert e.value.transient and not isinstance(e.value, PartialPublishError)
    http = Recorder()
    with pytest.raises(ProviderError, match="Part 2 is 281 characters"):
        X("c", "s", http=http).publish("AT", "42", "@m", "1/ ok\n\n2/ " + "a" * 281)
    assert http.calls == []


# --- error classification --------------------------------------------------------------

@pytest.mark.parametrize(
    "status,transient,reauth",
    [(401, False, True), (403, False, False), (400, False, False), (422, False, False), (429, True, False), (500, True, False), (503, True, False)],
)
def test_http_failures_are_classified(status, transient, reauth):
    li = LinkedIn("c", "s", "202609", http=Recorder(resp(status, {"message": "nope"})))
    with pytest.raises(ProviderError) as e:
        li.publish("AT", "a", "n", "hi")
    assert (e.value.transient, e.value.reauth) == (transient, reauth)


def test_network_failure_is_transient_and_garbage_responses_are_safe():
    with pytest.raises(ProviderError) as e:
        LinkedIn("c", "s", "202609", http=Recorder(TimeoutError("slow"))).publish("AT", "a", "n", "hi")
    assert e.value.transient
    for bad in (resp(200, ["not", "a", "dict"]), resp(200, {"nope": 1}), HttpResponse(200, b"<html>")):
        with pytest.raises(ProviderError):
            X("c", "s", http=Recorder(bad)).account("AT")
    msg = ""
    try:
        LinkedIn("c", "s", "202609", http=Recorder(resp(403, {"message": "Not enough permissions"}))).publish("AT", "a", "n", "hi")
    except ProviderError as exc:
        msg = exc.message
    assert "403" in msg and "Not enough permissions" in msg
