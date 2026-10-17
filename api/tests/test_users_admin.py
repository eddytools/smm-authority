def test_user_cannot_access_admin_endpoints(client, alice):
    assert client.get("/users", headers=alice).status_code == 403
    assert client.post(
        "/users", json={"email": "x@example.com", "password": "password-123", "name": "X", "role": "admin"}, headers=alice
    ).status_code == 403


def test_unauthenticated_cannot_list_users(client):
    assert client.get("/users").status_code == 401


def test_admin_lists_and_updates_users(client, admin_headers, alice):
    users = client.get("/users", headers=admin_headers).json()
    assert {u["email"] for u in users} == {"admin@example.com", "alice@example.com"}
    uid = next(u["id"] for u in users if u["email"] == "alice@example.com")

    r = client.patch(f"/users/{uid}", json={"role": "admin", "name": "Alice A"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["role"] == "admin" and r.json()["name"] == "Alice A"
    # now she can use admin endpoints
    assert client.get("/users", headers=alice).status_code == 200


def test_admin_can_create_admin_and_reset_password(client, admin_headers):
    r = client.post(
        "/users",
        json={"email": "ops@example.com", "password": "password-123", "name": "Ops", "role": "admin"},
        headers=admin_headers,
    )
    assert r.status_code == 201 and r.json()["role"] == "admin"
    uid = r.json()["id"]
    client.patch(f"/users/{uid}", json={"password": "new-password-456"}, headers=admin_headers)
    ok = client.post("/auth/login", json={"email": "ops@example.com", "password": "new-password-456"})
    old = client.post("/auth/login", json={"email": "ops@example.com", "password": "password-123"})
    assert ok.status_code == 200 and old.status_code == 401


def test_admin_cannot_lock_themselves_out(client, admin_headers):
    me = client.get("/auth/me", headers=admin_headers).json()
    assert client.patch(f"/users/{me['id']}", json={"role": "user"}, headers=admin_headers).status_code == 400
    assert client.patch(f"/users/{me['id']}", json={"is_active": False}, headers=admin_headers).status_code == 400
    # harmless self-edits still work
    assert client.patch(f"/users/{me['id']}", json={"name": "Root"}, headers=admin_headers).status_code == 200


def test_unknown_user_404(client, admin_headers):
    assert client.get("/users/9999", headers=admin_headers).status_code == 404
    assert client.patch("/users/9999", json={"name": "x"}, headers=admin_headers).status_code == 404
