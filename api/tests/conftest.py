import pytest
from fastapi.testclient import TestClient

from app.ai import Suggestion
from app.brief_schemas import Ideation, Platform, PlatformPlan
from app.config import Settings
from app.main import create_app

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
def client(fake_ai):
    with TestClient(create_app(make_settings(), ai=fake_ai)) as c:
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
