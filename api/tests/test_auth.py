from tests.conftest import ADMIN, login, register


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_register_defaults_to_user_role_and_ignores_role_field(client):
    r = client.post(
        "/auth/register",
        json={"email": "Eve@Example.com", "password": "password-123", "name": "Eve", "role": "admin"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "user"
    assert body["email"] == "eve@example.com"
    assert "password" not in body and "password_hash" not in body


def test_register_duplicate_email_conflicts(client):
    register(client, "a@example.com")
    r = client.post("/auth/register", json={"email": "A@example.com", "password": "password-123", "name": "A"})
    assert r.status_code == 409


def test_register_validation(client):
    r = client.post("/auth/register", json={"email": "bad", "password": "short", "name": " "})
    assert r.status_code == 422


def test_login_and_me(client):
    register(client, "a@example.com", name="A")
    headers = login(client, "a@example.com")
    me = client.get("/auth/me", headers=headers).json()
    assert me["email"] == "a@example.com" and me["role"] == "user"


def test_login_failures_are_indistinguishable(client):
    register(client, "a@example.com")
    wrong_pw = client.post("/auth/login", json={"email": "a@example.com", "password": "nope-nope"})
    unknown = client.post("/auth/login", json={"email": "zz@example.com", "password": "nope-nope"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


def test_protected_routes_require_valid_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_bootstrap_admin_exists_and_has_admin_role(client, admin_headers):
    assert client.get("/auth/me", headers=admin_headers).json()["role"] == "admin"


def test_deactivated_user_loses_access_immediately(client, admin_headers, alice):
    uid = client.get("/auth/me", headers=alice).json()["id"]
    assert client.patch(f"/users/{uid}", json={"is_active": False}, headers=admin_headers).status_code == 200
    assert client.get("/auth/me", headers=alice).status_code == 401
    assert client.post("/auth/login", json={"email": "alice@example.com", "password": "password-123"}).status_code == 401


def test_registration_can_be_disabled():
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    settings = Settings(database_url="sqlite://", secret_key="x" * 40, allow_registration=False)
    with TestClient(create_app(settings)) as c:
        r = c.post("/auth/register", json={"email": "a@example.com", "password": "password-123", "name": "A"})
        assert r.status_code == 403


def test_production_requires_real_secret():
    import pytest

    from app.config import Settings
    from app.main import create_app

    with pytest.raises(RuntimeError):
        create_app(Settings(env="production", database_url="sqlite://"))


def test_bootstrap_admin_is_not_overwritten_on_restart(client, admin_headers):
    from app.config import Settings
    from app.seed import ensure_admin

    other = Settings(admin_email=ADMIN["email"], admin_password="a-different-password")
    with client.app.state.session_factory() as db:
        ensure_admin(db, other)
    assert login(client, ADMIN["email"], ADMIN["password"])
    r = client.post("/auth/login", json={"email": ADMIN["email"], "password": "a-different-password"})
    assert r.status_code == 401
