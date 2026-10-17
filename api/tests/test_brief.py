from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import AIUsage, BriefVersion
from tests.conftest import make_settings

BRIEF = {
    "icp": {"industry": "B2B SaaS", "roles": ["Founder", "Head of Marketing"], "pains": ["No time to post"]},
    "ideation": {"niche_statement": "I help SaaS founders get inbound leads", "pillars": ["Founder-led growth", "LinkedIn", "Case studies"]},
    "offer": {"offer": "Authority sprint", "lead_magnets": ["30-day planner"], "cta_url": "https://acme.example/book"},
    "voice": {"tone": "Direct, warm", "dos": ["use numbers"], "donts": ["buzzwords"]},
    "platforms": [
        {"platform": "linkedin", "cadence_per_week": 4, "is_primary": True},
        {"platform": "x", "cadence_per_week": 3},
    ],
}


def venture(client, headers, name="Acme"):
    return client.post("/ventures", json={"name": name}, headers=headers).json()["id"]


def test_empty_until_saved(client, alice):
    vid = venture(client, alice)
    r = client.get(f"/ventures/{vid}/brief", headers=alice)
    assert r.status_code == 200 and r.json() is None
    assert client.get(f"/ventures/{vid}/brief/versions", headers=alice).json() == []


def test_save_creates_new_versions_and_keeps_history(client, alice):
    vid = venture(client, alice)
    v1 = client.put(f"/ventures/{vid}/brief", json=BRIEF, headers=alice)
    assert v1.status_code == 200 and v1.json()["version"] == 1
    changed = {**BRIEF, "voice": {"tone": "Playful"}}
    v2 = client.put(f"/ventures/{vid}/brief", json=changed, headers=alice).json()
    assert v2["version"] == 2

    latest = client.get(f"/ventures/{vid}/brief", headers=alice).json()
    assert latest["version"] == 2 and latest["data"]["voice"]["tone"] == "Playful"
    old = client.get(f"/ventures/{vid}/brief/versions/1", headers=alice).json()
    assert old["data"]["voice"]["tone"] == "Direct, warm"
    assert [v["version"] for v in client.get(f"/ventures/{vid}/brief/versions", headers=alice).json()] == [2, 1]
    assert client.get(f"/ventures/{vid}/brief/versions/9", headers=alice).status_code == 404


def test_roundtrip_preserves_data(client, alice):
    vid = venture(client, alice)
    client.put(f"/ventures/{vid}/brief", json=BRIEF, headers=alice)
    data = client.get(f"/ventures/{vid}/brief", headers=alice).json()["data"]
    assert data["icp"]["roles"] == ["Founder", "Head of Marketing"]
    assert data["offer"]["cta_url"] == "https://acme.example/book"
    assert [p["platform"] for p in data["platforms"]] == ["linkedin", "x"]


def test_validation(client, alice):
    vid = venture(client, alice)
    put = lambda body: client.put(f"/ventures/{vid}/brief", json=body, headers=alice).status_code
    assert put({"ideation": {"pillars": ["1", "2", "3", "4", "5", "6"]}}) == 422
    assert put({"platforms": [{"platform": "x"}, {"platform": "x"}]}) == 422
    assert put({"platforms": [{"platform": "x", "is_primary": True}, {"platform": "reddit", "is_primary": True}]}) == 422
    assert put({"platforms": [{"platform": "tiktok"}]}) == 422
    assert put({"platforms": [{"platform": "x", "cadence_per_week": 0}]}) == 422
    assert put({"offer": {"cta_url": "javascript:alert(1)"}}) == 422
    assert put({}) == 200  # an empty brief is a valid starting point


def test_access_control(client, admin_headers, alice, bob):
    vid = venture(client, alice)
    client.put(f"/ventures/{vid}/brief", json=BRIEF, headers=alice)
    for call in (
        lambda h: client.get(f"/ventures/{vid}/brief", headers=h),
        lambda h: client.put(f"/ventures/{vid}/brief", json=BRIEF, headers=h),
        lambda h: client.get(f"/ventures/{vid}/brief/versions", headers=h),
        lambda h: client.post(f"/ventures/{vid}/brief/suggest", json={}, headers=h),
    ):
        assert call(bob).status_code == 404
    assert client.get(f"/ventures/{vid}/brief").status_code == 401
    assert client.get(f"/ventures/{vid}/brief", headers=admin_headers).status_code == 200  # admin sees all


def test_deleting_venture_removes_briefs(client, alice):
    vid = venture(client, alice)
    client.put(f"/ventures/{vid}/brief", json=BRIEF, headers=alice)
    assert client.delete(f"/ventures/{vid}", headers=alice).status_code == 204
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(BriefVersion)) == 0


# --- AI suggestions -----------------------------------------------------------

def test_suggest_returns_unsaved_draft_and_records_usage(client, alice, fake_ai):
    vid = venture(client, alice, "Acme Coaching")
    r = client.post(f"/ventures/{vid}/brief/suggest", json={"icp": {"industry": "SaaS"}}, headers=alice)
    assert r.status_code == 200
    body = r.json()
    assert body["ideation"]["pillars"] == ["a", "b", "c"]
    assert body["platforms"][0]["platform"] == "linkedin" and body["platforms"][0]["is_primary"] is True
    # venture details and the user's answers reach the provider
    venture_info, inputs = fake_ai.calls[0]
    assert venture_info["name"] == "Acme Coaching" and inputs.icp.industry == "SaaS"
    # nothing saved
    assert client.get(f"/ventures/{vid}/brief", headers=alice).json() is None
    with client.app.state.session_factory() as db:
        usage = db.scalars(select(AIUsage)).all()
    assert len(usage) == 1 and usage[0].input_tokens == 100 and usage[0].feature == "brief_suggest"


def test_daily_limit_applies_to_users_not_admins(fake_ai):
    app = create_app(make_settings(ai_daily_limit_per_user=2), ai=fake_ai)
    with TestClient(app) as c:
        c.post("/auth/register", json={"email": "u@example.com", "password": "password-123", "name": "U"})
        h = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "u@example.com", "password": "password-123"}).json()["access_token"]}
        vid = c.post("/ventures", json={"name": "V"}, headers=h).json()["id"]
        codes = [c.post(f"/ventures/{vid}/brief/suggest", json={}, headers=h).status_code for _ in range(3)]
        assert codes == [200, 200, 429]

        a = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "admin@example.com", "password": "admin-password-1"}).json()["access_token"]}
        avid = c.post("/ventures", json={"name": "A"}, headers=a).json()["id"]
        assert all(c.post(f"/ventures/{avid}/brief/suggest", json={}, headers=a).status_code == 200 for _ in range(4))


def test_suggest_503_when_ai_not_configured(alice):
    with TestClient(create_app(make_settings(), ai=None)) as c:
        c.post("/auth/register", json={"email": "u@example.com", "password": "password-123", "name": "U"})
        h = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "u@example.com", "password": "password-123"}).json()["access_token"]}
        vid = c.post("/ventures", json={"name": "V"}, headers=h).json()["id"]
        assert c.post(f"/ventures/{vid}/brief/suggest", json={}, headers=h).status_code == 503
        # everything else still works without AI
        assert c.put(f"/ventures/{vid}/brief", json=BRIEF, headers=h).status_code == 200
