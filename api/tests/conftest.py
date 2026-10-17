import pytest
from fastapi.testclient import TestClient

from app.ai import DraftResult, ReplyResult, ScoreResult, Suggestion
from app.brief_schemas import Ideation, Platform, PlatformPlan
from app.config import Settings
from app.main import create_app

@pytest.fixture(autouse=True)
def _isolate_from_local_config(monkeypatch):
    """Tests must behave the same on every machine: ignore a developer's api/.env and any SMM_*/ANTHROPIC_* variables."""
    import os

    for name in list(os.environ):
        if name.startswith("SMM_") or name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


ADMIN = {"email": "admin@example.com", "password": "admin-password-1"}


class FakeAI:
    model = "fake-model"

    def __init__(self):
        self.calls = []

    def suggest_brief(self, venture, inputs):
        self.calls.append((venture, inputs))
        return Suggestion(
            ideation=Ideation(niche_statement="Help X do Y", unique_angle="Z", pillars=["a", "b", "c"]),
            platforms=[PlatformPlan(platform=Platform.linkedin, is_primary=True, cadence_per_week=4, reason="ICP is there")],
            rationale="because",
            input_tokens=100,
            output_tokens=50,
            model=self.model,
        )


    def score_feed(self, venture, brief, items):
        self.score_calls = getattr(self, "score_calls", []) + [(venture, brief, items)]
        # deterministic: longer titles score higher, so tests can assert ordering
        scores = {i["id"]: (min(len(i["title"]), 100), f"why {i['id']}") for i in items}
        return ScoreResult(scores=scores, input_tokens=200, output_tokens=80, model=self.model)


    def draft_post(self, context):
        self.draft_calls = getattr(self, "draft_calls", []) + [context]
        post = getattr(self, "draft_text", None) or f"Draft about: {context['post']['topic']}"
        return DraftResult(post=post, hooks=["Alt hook one", "Alt hook two"], notes="Used a contrarian angle.", input_tokens=300, output_tokens=120, model=self.model)


    def draft_reply(self, context):
        self.reply_calls = getattr(self, "reply_calls", []) + [context]
        reply = getattr(self, "reply_text", None) or ("The short answer is to start with one channel and measure it for a month before adding another. "
                                                       "Pick the place your buyers already read, post twice a week, and track what they reply to. " * 2)
        return ReplyResult(reply=reply, post_idea_title="Why one channel beats three", post_idea="Most teams spread thin. Here is a simple way to pick one channel.", notes="Kept it generic.", input_tokens=250, output_tokens=90, model=self.model)


def make_settings(**overrides):
    base = dict(
        database_url="sqlite://",
        secret_key="test-secret-key-that-is-long-enough-for-hs256",
        admin_email=ADMIN["email"],
        admin_password=ADMIN["password"],
        anthropic_api_key=None,
    )
    return Settings(**{**base, **overrides})


@pytest.fixture
def fake_ai():
    return FakeAI()


@pytest.fixture
def client(fake_ai, fetcher):
    with TestClient(create_app(make_settings(), ai=fake_ai, fetcher=fetcher)) as c:
        yield c


def register(client, email, password="password-123", name="Test User"):
    r = client.post("/auth/register", json={"email": email, "password": password, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


def login(client, email, password="password-123"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin_headers(client):
    return login(client, ADMIN["email"], ADMIN["password"])


@pytest.fixture
def alice(client):
    register(client, "alice@example.com", name="Alice")
    return login(client, "alice@example.com")


@pytest.fixture
def bob(client):
    register(client, "bob@example.com", name="Bob")
    return login(client, "bob@example.com")


RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>Blog</title>
<item><title>Founder-led growth playbook for SaaS</title><link>https://blog.example/growth?utm_source=x</link>
<description>&lt;p&gt;How SaaS founders win inbound leads&lt;/p&gt;</description><pubDate>Mon, 13 Oct 2025 08:00:00 GMT</pubDate><dc:creator>Ann</dc:creator></item>
<item><title>Ten pasta recipes</title><link>https://blog.example/pasta</link><description>Dinner ideas</description></item>
<item><title>No link here</title></item>
</channel></rss>"""


def fresh_rss() -> bytes:
    """Same shape as RSS but dated relative to now, so age-based rules (14-day scoring window) don't rot."""
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    day_ago = format_datetime(datetime.now(timezone.utc) - timedelta(days=1))
    return RSS.replace(b"Mon, 13 Oct 2025 08:00:00 GMT", day_ago.encode())


class FakeFetcher:
    """Stands in for the network: url -> bytes, or an Exception to raise."""

    def __init__(self):
        self.responses = {}
        self.calls = []

    def __call__(self, url, accept):
        from app.fetch import FetchResult

        self.calls.append(url)
        value = self.responses.get(url)
        if value is None:
            from app.fetch import FetchError

            raise FetchError("HTTP 404")
        if isinstance(value, Exception):
            raise value
        return FetchResult(200, value, url, "text/xml")


@pytest.fixture
def fetcher():
    return FakeFetcher()


@pytest.fixture
def make_client(fake_ai, fetcher):
    """Factory so a test can tweak settings (limits, intervals) while keeping the fakes."""
    stack = []

    def factory(**settings):
        c = TestClient(create_app(make_settings(**settings), ai=fake_ai, fetcher=fetcher))
        c.__enter__()
        stack.append(c)
        return c

    yield factory
    for c in stack:
        c.__exit__(None, None, None)


# --- publishing fakes ----------------------------------------------------------------

class FakeProvider:
    """Stands in for LinkedIn / X: records what it was asked and fails on demand."""

    def __init__(self, platform, pkce=False):
        self.platform, self.label, self.uses_pkce, self.configured = platform, platform.title(), pkce, True
        self.published, self.exchanged, self.refreshed, self.errors = [], [], [], []
        self.refresh_result, self.refresh_error = None, None
        self.metrics_supported = pkce  # X-like fakes can report numbers, LinkedIn-like ones can't
        self.metric_calls, self.metric_results, self.metric_errors = [], {}, []

    def authorize_url(self, redirect_uri, state, code_challenge):
        return f"https://fake.example/{self.platform}/authorize?state={state}&redirect_uri={redirect_uri}&cc={code_challenge}"

    def exchange_code(self, code, redirect_uri, code_verifier):
        from app.publishers import TokenSet

        self.exchanged.append((code, redirect_uri, code_verifier))
        return TokenSet(f"access-{code}", f"refresh-{code}", 3600)

    def account(self, token):
        from app.publishers import Account

        return Account("acct-1", "Maya Test")

    def refresh(self, refresh_token):
        from app.publishers import TokenSet

        self.refreshed.append(refresh_token)
        if self.refresh_error:
            raise self.refresh_error
        return self.refresh_result or TokenSet("fresh-access", "fresh-refresh", 7200)

    def publish(self, token, account_id, account_name, text):
        from app.publishers import PostResult

        self.published.append({"token": token, "account_id": account_id, "text": text})
        if self.errors:
            raise self.errors.pop(0)
        n = len(self.published)
        return PostResult(f"post-{n}", f"https://fake.example/{self.platform}/post/{n}")


def _fetch_metrics(self, token, ids):
    self.metric_calls.append((token, list(ids)))
    if self.metric_errors:
        raise self.metric_errors.pop(0)
    return {i: self.metric_results.get(i) for i in ids}


FakeProvider.fetch_metrics = _fetch_metrics


@pytest.fixture
def providers():
    return {"linkedin": FakeProvider("linkedin"), "x": FakeProvider("x", pkce=True)}


@pytest.fixture
def pub_client(fake_ai, fetcher, providers):
    from cryptography.fernet import Fernet

    settings = make_settings(token_encryption_key=Fernet.generate_key().decode())
    with TestClient(create_app(settings, ai=fake_ai, fetcher=fetcher, providers=providers)) as c:
        yield c


@pytest.fixture
def alice_pub(pub_client):
    register(pub_client, "alice@example.com", name="Alice")
    return login(pub_client, "alice@example.com")


@pytest.fixture
def bob_pub(pub_client):
    register(pub_client, "bob@example.com", name="Bob")
    return login(pub_client, "bob@example.com")


@pytest.fixture
def admin_headers_pub(pub_client):
    return login(pub_client, ADMIN["email"], ADMIN["password"])
