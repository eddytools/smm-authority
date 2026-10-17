import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ADMIN = {"email": "admin@example.com", "password": "admin-password-1"}


@pytest.fixture
def client():
    settings = Settings(
        database_url="sqlite://",
        secret_key="test-secret-key-that-is-long-enough-for-hs256",
        admin_email=ADMIN["email"],
        admin_password=ADMIN["password"],
    )
    with TestClient(create_app(settings)) as c:
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
