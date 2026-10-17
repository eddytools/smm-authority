def make(client, headers, name="Acme Coaching", **extra):
    r = client.post("/ventures", json={"name": name, **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_user_can_create_multiple_ventures(client, alice):
    a = make(client, alice, "Acme Coaching", niche="Executive coaching", website_url="https://acme.example")
    b = make(client, alice, "Beta SaaS", description="B2B analytics")
    assert a["id"] != b["id"]
    assert a["owner_email"] == "alice@example.com"
    names = [v["name"] for v in client.get("/ventures", headers=alice).json()]
    assert set(names) == {"Acme Coaching", "Beta SaaS"}


def test_duplicate_name_per_owner_conflicts_but_other_users_may_reuse(client, alice, bob):
    make(client, alice, "Acme")
    assert client.post("/ventures", json={"name": "Acme"}, headers=alice).status_code == 409
    assert client.post("/ventures", json={"name": "Acme"}, headers=bob).status_code == 201


def test_users_only_see_their_own_ventures(client, alice, bob):
    mine = make(client, alice, "Alice Venture")
    make(client, bob, "Bob Venture")
    assert [v["name"] for v in client.get("/ventures", headers=alice).json()] == ["Alice Venture"]
    # another user's venture is 404 for read, update and delete
    assert client.get(f"/ventures/{mine['id']}", headers=bob).status_code == 404
    assert client.patch(f"/ventures/{mine['id']}", json={"name": "Hacked"}, headers=bob).status_code == 404
    assert client.delete(f"/ventures/{mine['id']}", headers=bob).status_code == 404
    assert client.get(f"/ventures/{mine['id']}", headers=alice).json()["name"] == "Alice Venture"


def test_user_cannot_request_all_scope(client, alice):
    assert client.get("/ventures?scope=all", headers=alice).status_code == 403


def test_admin_scope_all_and_can_manage_any_venture(client, admin_headers, alice, bob):
    a = make(client, alice, "Alice Venture")
    make(client, bob, "Bob Venture")
    assert len(client.get("/ventures?scope=all", headers=admin_headers).json()) == 2
    assert client.get("/ventures", headers=admin_headers).json() == []  # default scope is "mine"
    assert client.get(f"/ventures/{a['id']}", headers=admin_headers).status_code == 200
    assert client.patch(f"/ventures/{a['id']}", json={"niche": "Edited"}, headers=admin_headers).json()["niche"] == "Edited"
    assert client.delete(f"/ventures/{a['id']}", headers=admin_headers).status_code == 204


def test_update_partial_and_clear_optional_fields(client, alice):
    v = make(client, alice, "Acme", niche="Coaching", website_url="https://acme.example")
    r = client.patch(f"/ventures/{v['id']}", json={"niche": None, "description": "New"}, headers=alice).json()
    assert r["niche"] is None and r["description"] == "New" and r["name"] == "Acme"
    assert r["website_url"] == "https://acme.example"


def test_update_rejects_null_name_and_duplicate_rename(client, alice):
    make(client, alice, "One")
    two = make(client, alice, "Two")
    assert client.patch(f"/ventures/{two['id']}", json={"name": None}, headers=alice).status_code == 422
    assert client.patch(f"/ventures/{two['id']}", json={"name": "One"}, headers=alice).status_code == 409


def test_archive_hides_from_default_list(client, alice):
    v = make(client, alice, "Old")
    client.patch(f"/ventures/{v['id']}", json={"is_archived": True}, headers=alice)
    assert client.get("/ventures", headers=alice).json() == []
    assert len(client.get("/ventures?include_archived=true", headers=alice).json()) == 1


def test_delete(client, alice):
    v = make(client, alice, "Temp")
    assert client.delete(f"/ventures/{v['id']}", headers=alice).status_code == 204
    assert client.get(f"/ventures/{v['id']}", headers=alice).status_code == 404


def test_validation(client, alice):
    assert client.post("/ventures", json={"name": "  "}, headers=alice).status_code == 422
    assert client.post("/ventures", json={"name": "x" * 121}, headers=alice).status_code == 422
    assert client.post("/ventures", json={"name": "ok", "website_url": "javascript:alert(1)"}, headers=alice).status_code == 422
    assert client.post("/ventures", json={"name": "ok", "website_url": "not a url"}, headers=alice).status_code == 422


def test_requires_auth(client):
    assert client.get("/ventures").status_code == 401
    assert client.post("/ventures", json={"name": "x"}).status_code == 401
