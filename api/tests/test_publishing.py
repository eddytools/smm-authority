from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.models import Connection, OAuthAttempt, User
from app.publishers import PartialPublishError, ProviderError
from app.publishing import MAX_ATTEMPTS, run_due
from tests.conftest import login, register

BRIEF = {"platforms": [{"platform": "linkedin", "cadence_per_week": 3}, {"platform": "x", "cadence_per_week": 3}, {"platform": "reddit", "cadence_per_week": 1}]}


def venture(client, headers, name="Acme"):
    vid = client.post("/ventures", json={"name": name}, headers=headers).json()["id"]
    client.put(f"/ventures/{vid}/brief", json=BRIEF, headers=headers)
    return vid


def connect(client, headers, vid, platform="linkedin", code="CODE"):
    """Runs the whole OAuth dance with the fake provider and returns the callback response."""
    url = client.post(f"/ventures/{vid}/integrations/{platform}/connect", headers=headers).json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    return client.get(f"/integrations/{platform}/callback?code={code}&state={state}", follow_redirects=False)


def patch(client, headers, vid, sid, **body):
    return client.patch(f"/ventures/{vid}/plan/slots/{sid}", json=body, headers=headers)


def make_slot(client, headers, vid, *, platform="linkedin", hours_from_now=-1, draft="A finished post", to="scheduled", post_type="story"):
    when = (datetime.now(timezone.utc) + timedelta(hours=hours_from_now)).isoformat()
    sid = client.post(f"/ventures/{vid}/plan/slots", json={"scheduled_at": when, "platform": platform, "post_type": post_type, "topic": "t"}, headers=headers).json()["id"]
    if to != "idea":
        assert patch(client, headers, vid, sid, draft=draft, status="drafted").status_code == 200
        for st in ("approved", "scheduled"):
            if to in (st, "scheduled") or st == "approved":
                r = patch(client, headers, vid, sid, status=st)
                assert r.status_code == 200, r.text
            if st == to:
                break
    return sid


def slot(client, headers, vid, sid):
    return next(s for s in client.get(f"/ventures/{vid}/plan?limit=500", headers=headers).json() if s["id"] == sid)


def run(client, now=None):
    return run_due(client.app.state.session_factory, client.app.state.publishing, now)


# --- connecting ----------------------------------------------------------------------

def test_unconfigured_platforms_are_reported_and_cannot_connect(client, alice):
    vid = venture(client, alice)
    rows = {r["platform"]: r for r in client.get(f"/ventures/{vid}/integrations", headers=alice).json()}
    assert rows["linkedin"]["configured"] is False and rows["linkedin"]["connected"] is False and rows["x"]["configured"] is False
    r = client.post(f"/ventures/{vid}/integrations/linkedin/connect", headers=alice)
    assert r.status_code == 503 and "administrator" in r.json()["detail"]
    assert client.post(f"/ventures/{vid}/integrations/myspace/connect", headers=alice).status_code == 404


def test_connect_flow_stores_encrypted_tokens_and_hides_them(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    assert {r["platform"]: r["configured"] for r in c.get(f"/ventures/{vid}/integrations", headers=h).json()} == {"linkedin": True, "x": True}
    r = connect(c, h, vid, "linkedin", "ABC")
    assert r.status_code == 303 and r.headers["location"] == f"http://localhost:5173/ventures/{vid}/publishing?connected=linkedin"
    assert providers["linkedin"].exchanged[0][0] == "ABC" and providers["linkedin"].exchanged[0][1].endswith("/integrations/linkedin/callback")

    row = {r["platform"]: r for r in c.get(f"/ventures/{vid}/integrations", headers=h).json()}["linkedin"]
    assert row["connected"] and row["account_name"] == "Maya Test" and row["status"] == "active" and row["auto_publish"] is True
    assert "token" not in str(row).lower()
    with c.app.state.session_factory() as db:
        conn = db.scalar(select(Connection))
        assert conn.access_token_enc != "access-ABC" and "access-ABC" not in conn.access_token_enc
        assert c.app.state.publishing.cipher.decrypt(conn.access_token_enc) == "access-ABC"
        assert c.app.state.publishing.cipher.decrypt(conn.refresh_token_enc) == "refresh-ABC"


def test_x_uses_pkce_and_the_verifier_never_leaves_the_server(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    url = c.post(f"/ventures/{vid}/integrations/x/connect", headers=h).json()["authorize_url"]
    challenge = parse_qs(urlparse(url).query)["cc"][0]
    state = parse_qs(urlparse(url).query)["state"][0]
    assert challenge != "None"
    with c.app.state.session_factory() as db:
        verifier = db.scalar(select(OAuthAttempt)).code_verifier
    assert verifier and verifier not in url and state != verifier
    c.get(f"/integrations/x/callback?code=C&state={state}", follow_redirects=False)
    assert providers["x"].exchanged[0][2] == verifier  # handed to the token exchange from the database
    linkedin_url = c.post(f"/ventures/{vid}/integrations/linkedin/connect", headers=h).json()["authorize_url"]
    assert parse_qs(urlparse(linkedin_url).query)["cc"] == ["None"]  # LinkedIn's standard flow has no PKCE


def test_callback_rejects_unknown_replayed_expired_and_mismatched_state(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    for bad in ("", "?code=C", "?code=C&state=forged", "?error=access_denied&state=forged"):
        r = c.get(f"/integrations/linkedin/callback{bad}", follow_redirects=False)
        assert r.status_code == 303 and "publishing_error=invalid_state" in r.headers["location"]
    assert providers["linkedin"].exchanged == []

    assert connect(c, h, vid).status_code == 303
    url = c.post(f"/ventures/{vid}/integrations/linkedin/connect", headers=h).json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    assert "error=invalid_state" in c.get(f"/integrations/x/callback?code=C&state={state}", follow_redirects=False).headers["location"]  # wrong platform
    # the state was issued for linkedin, and replaying a used one fails
    assert "connected=linkedin" in c.get(f"/integrations/linkedin/callback?code=C&state={state}", follow_redirects=False).headers["location"]
    assert "error=invalid_state" in c.get(f"/integrations/linkedin/callback?code=C&state={state}", follow_redirects=False).headers["location"]

    url = c.post(f"/ventures/{vid}/integrations/linkedin/connect", headers=h).json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    with c.app.state.session_factory() as db:
        a = db.scalar(select(OAuthAttempt).where(OAuthAttempt.state == state))
        a.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert "error=expired" in c.get(f"/integrations/linkedin/callback?code=C&state={state}", follow_redirects=False).headers["location"]


def test_user_denying_access_and_provider_failures_are_handled(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    url = c.post(f"/ventures/{vid}/integrations/linkedin/connect", headers=h).json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    assert "error=denied" in c.get(f"/integrations/linkedin/callback?error=access_denied&state={state}", follow_redirects=False).headers["location"]

    def boom(*a):
        raise ProviderError("token endpoint said no")

    providers["linkedin"].exchange_code = boom
    url = c.post(f"/ventures/{vid}/integrations/linkedin/connect", headers=h).json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    assert "error=exchange_failed" in c.get(f"/integrations/linkedin/callback?code=C&state={state}", follow_redirects=False).headers["location"]
    assert c.get(f"/ventures/{vid}/integrations", headers=h).json()[0]["connected"] is False


def test_callback_requires_the_initiating_user_to_still_have_access(pub_client, admin_headers_pub, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    url = c.post(f"/ventures/{vid}/integrations/linkedin/connect", headers=h).json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    uid = c.get("/auth/me", headers=h).json()["id"]
    c.patch(f"/users/{uid}", json={"is_active": False}, headers=admin_headers_pub)  # deactivated while on LinkedIn's consent screen
    assert "error=not_allowed" in c.get(f"/integrations/linkedin/callback?code=C&state={state}", follow_redirects=False).headers["location"]
    with c.app.state.session_factory() as db:
        assert db.scalars(select(Connection)).all() == []


def test_integrations_are_private_to_the_owner(pub_client, alice_pub, bob_pub):
    c = pub_client
    vid = venture(c, alice_pub)
    connect(c, alice_pub, vid)
    assert c.get(f"/ventures/{vid}/integrations", headers=bob_pub).status_code == 404
    assert c.post(f"/ventures/{vid}/integrations/linkedin/connect", headers=bob_pub).status_code == 404
    assert c.patch(f"/ventures/{vid}/integrations/linkedin", json={"auto_publish": False}, headers=bob_pub).status_code == 404
    assert c.delete(f"/ventures/{vid}/integrations/linkedin", headers=bob_pub).status_code == 404
    assert c.get(f"/ventures/{vid}/integrations").status_code == 401


def test_pause_resume_and_disconnect(pub_client, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    assert c.patch(f"/ventures/{vid}/integrations/x", json={"auto_publish": False}, headers=h).status_code == 404  # not connected yet
    connect(c, h, vid)
    assert c.patch(f"/ventures/{vid}/integrations/linkedin", json={"auto_publish": False}, headers=h).json()["auto_publish"] is False
    assert c.delete(f"/ventures/{vid}/integrations/linkedin", headers=h).status_code == 204
    assert c.get(f"/ventures/{vid}/integrations", headers=h).json()[0]["connected"] is False
    assert c.delete(f"/ventures/{vid}/integrations/linkedin", headers=h).status_code == 404


# --- the publishing job ----------------------------------------------------------------

def test_job_posts_due_scheduled_posts_exactly_once(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid)
    sid = make_slot(c, h, vid, draft="Hello (world) #growth")
    assert slot(c, h, vid, sid)["will_auto_publish"] is True
    outcomes = run(c)
    assert [(o.slot_id, o.status) for o in outcomes] == [(sid, "published")]
    s = slot(c, h, vid, sid)
    assert s["status"] == "published" and s["external_url"] == "https://fake.example/linkedin/post/1" and s["published_at"] and s["publish_error"] is None
    assert providers["linkedin"].published[0]["text"] == "Hello (world) #growth" and providers["linkedin"].published[0]["token"] == "access-CODE"
    assert run(c) == [] and len(providers["linkedin"].published) == 1  # a second pass finds nothing to do


def test_job_only_posts_what_a_human_scheduled_and_whose_time_has_come(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid)
    future = make_slot(c, h, vid, hours_from_now=5)
    approved_only = make_slot(c, h, vid, to="approved")
    idea = make_slot(c, h, vid, to="idea")
    assert run(c) == [] and providers["linkedin"].published == []
    for sid in (future, approved_only, idea):
        assert slot(c, h, vid, sid)["status"] != "published"
    # time passes: the future post becomes due, the others still aren't scheduled
    out = run(c, now=datetime.now(timezone.utc) + timedelta(hours=6))
    assert [o.slot_id for o in out] == [future]


def test_job_skips_manual_platforms_paused_and_disconnected_ventures(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid, "linkedin")
    reddit = make_slot(c, h, vid, platform="reddit")
    x_unconnected = make_slot(c, h, vid, platform="x")
    assert slot(c, h, vid, reddit)["will_auto_publish"] is False and slot(c, h, vid, x_unconnected)["will_auto_publish"] is False
    li = make_slot(c, h, vid)
    c.patch(f"/ventures/{vid}/integrations/linkedin", json={"auto_publish": False}, headers=h)  # kill switch
    assert slot(c, h, vid, li)["will_auto_publish"] is False
    assert run(c) == [] and all(p.published == [] for p in providers.values())
    c.patch(f"/ventures/{vid}/integrations/linkedin", json={"auto_publish": True}, headers=h)
    assert [o.slot_id for o in run(c)] == [li]


def test_transient_failures_back_off_then_give_up(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid)
    sid = make_slot(c, h, vid)
    providers["linkedin"].errors = [ProviderError("rate limited (429)", transient=True) for _ in range(MAX_ATTEMPTS)]
    now = datetime.now(timezone.utc)
    waits = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        (o,) = run(c, now)
        s = slot(c, h, vid, sid)
        assert s["status"] == "scheduled"
        waits.append(o.status)
        if attempt < MAX_ATTEMPTS:
            assert o.status == "retry" and run(c, now) == []  # not retried until its backoff has passed
            now += timedelta(hours=2)
    assert waits == ["retry", "retry", "retry", "failed"]
    s = slot(c, h, vid, sid)
    assert s["publish_error"].startswith("Gave up after 4 attempts") and run(c, now + timedelta(days=1)) == []


def test_permanent_failure_is_not_retried_and_editing_gives_a_fresh_start(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid)
    sid = make_slot(c, h, vid)
    providers["linkedin"].errors = [ProviderError("422 duplicate content")]
    (o,) = run(c)
    assert o.status == "failed" and "duplicate content" in slot(c, h, vid, sid)["publish_error"]
    assert run(c, datetime.now(timezone.utc) + timedelta(days=1)) == []  # a permanent error is not retried, even much later
    assert len(providers["linkedin"].published) == 1  # never retried
    # the author fixes the text: error cleared, and it posts on the next pass
    assert patch(c, h, vid, sid, draft="A different post").json()["publish_error"] is None
    assert [o.status for o in run(c)] == ["published"]
    assert providers["linkedin"].published[-1]["text"] == "A different post"


def test_rejected_credentials_mark_the_connection_for_reconnect(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid)
    sid = make_slot(c, h, vid)
    providers["linkedin"].errors = [ProviderError("401", reauth=True)]
    assert [o.status for o in run(c)] == ["reconnect"]
    assert c.get(f"/ventures/{vid}/integrations", headers=h).json()[0]["status"] == "needs_reconnect"
    assert slot(c, h, vid, sid)["status"] == "scheduled"
    assert run(c) == []  # nothing is attempted with a dead connection
    connect(c, h, vid, "linkedin", "NEW")  # reconnecting restores it
    assert c.get(f"/ventures/{vid}/integrations", headers=h).json()[0]["status"] == "active"
    patch(c, h, vid, sid, status="approved")
    patch(c, h, vid, sid, status="scheduled")
    assert [o.status for o in run(c)] == ["published"] and providers["linkedin"].published[-1]["token"] == "access-NEW"


def test_posts_far_past_their_time_are_not_sent_after_an_outage(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid)
    stale = make_slot(c, h, vid, hours_from_now=-30)
    fresh = make_slot(c, h, vid, hours_from_now=-2)
    out = {o.slot_id: o for o in run(c)}
    assert out[stale].status == "failed" and "more than 24 hours" in out[stale].message
    assert out[fresh].status == "published"
    assert [p["text"] for p in providers["linkedin"].published] == ["A finished post"] and slot(c, h, vid, stale)["status"] == "scheduled"


def test_partial_thread_is_published_with_a_note_and_never_retried(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid, "x")
    sid = make_slot(c, h, vid, platform="x", draft="1/ one\n\n2/ two")
    providers["x"].errors = [PartialPublishError("Thread incomplete: posted 1 of 2 parts.", first_id="100", first_url="https://x.com/m/status/100", posted=1, total=2)]
    (o,) = run(c)
    s = slot(c, h, vid, sid)
    assert o.status == "published" and s["status"] == "published" and s["external_url"] == "https://x.com/m/status/100" and "Thread incomplete" in s["publish_error"]
    assert run(c, datetime.now(timezone.utc) + timedelta(days=1)) == [] and len(providers["x"].published) == 1


def test_a_claimed_post_is_not_posted_twice_but_a_crashed_claim_is_recovered(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid)
    sid = make_slot(c, h, vid)
    from app.models import PlanSlot

    def claim(minutes_ago):
        with c.app.state.session_factory() as db:
            db.get(PlanSlot, sid).claimed_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
            db.commit()

    claim(1)  # another worker is posting it right now
    assert [o.status for o in run(c)] == ["skipped"] and providers["linkedin"].published == []
    claim(30)  # that worker died long ago
    assert [o.status for o in run(c)] == ["published"] and len(providers["linkedin"].published) == 1


def test_expiring_tokens_are_refreshed_and_the_rotated_refresh_token_is_saved(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid)
    make_slot(c, h, vid)
    with c.app.state.session_factory() as db:
        db.scalar(select(Connection)).expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)  # inside the 5 minute margin
        db.commit()
    assert [o.status for o in run(c)] == ["published"]
    assert providers["linkedin"].refreshed == ["refresh-CODE"] and providers["linkedin"].published[0]["token"] == "fresh-access"
    with c.app.state.session_factory() as db:
        conn = db.scalar(select(Connection))
        cipher = c.app.state.publishing.cipher
        assert cipher.decrypt(conn.access_token_enc) == "fresh-access" and cipher.decrypt(conn.refresh_token_enc) == "fresh-refresh"
        assert conn.expires_at > datetime.now(timezone.utc) + timedelta(hours=1)


def test_failed_refresh_asks_for_reconnect_and_expired_without_refresh_token_too(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid)
    make_slot(c, h, vid)
    providers["linkedin"].refresh_error = ProviderError("invalid_grant")
    with c.app.state.session_factory() as db:
        db.scalar(select(Connection)).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert [o.status for o in run(c)] == ["reconnect"] and providers["linkedin"].published == []
    assert c.get(f"/ventures/{vid}/integrations", headers=h).json()[0]["status"] == "needs_reconnect"

    vid2 = venture(c, h, "Second")
    connect(c, h, vid2)
    make_slot(c, h, vid2)
    with c.app.state.session_factory() as db:
        conn = db.scalar(select(Connection).where(Connection.venture_id == vid2))
        conn.refresh_token_enc, conn.expires_at = None, datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert [o.status for o in run(c)] == ["reconnect"]  # LinkedIn tokens without a refresh token simply expire


# --- publish now + scheduling guards ---------------------------------------------------

def test_publish_now(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    idea = make_slot(c, h, vid, to="idea")
    assert c.post(f"/ventures/{vid}/plan/slots/{idea}/publish", headers=h).status_code == 400  # not approved
    approved = make_slot(c, h, vid, hours_from_now=3, to="approved")
    r = c.post(f"/ventures/{vid}/plan/slots/{approved}/publish", headers=h)
    assert r.status_code == 400 and "isn't connected" in r.json()["detail"]
    connect(c, h, vid)
    r = c.post(f"/ventures/{vid}/plan/slots/{approved}/publish", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "published" and r.json()["external_url"].endswith("/post/1")
    assert c.post(f"/ventures/{vid}/plan/slots/{approved}/publish", headers=h).status_code == 400  # already published
    assert len(providers["linkedin"].published) == 1


def test_publish_now_failures_are_reported_and_leave_the_post_scheduled_with_the_reason(pub_client, providers, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid)
    sid = make_slot(c, h, vid, hours_from_now=3, to="approved")
    providers["linkedin"].errors = [ProviderError("busy", transient=True)]
    r = c.post(f"/ventures/{vid}/plan/slots/{sid}/publish", headers=h)
    assert r.status_code == 502 and "busy" in r.json()["detail"]
    s = slot(c, h, vid, sid)
    assert s["status"] == "scheduled" and s["publish_error"] == "busy"
    assert c.post(f"/ventures/{vid}/plan/slots/{sid}/publish", headers=h).json()["status"] == "published"  # retry clears the error


def test_over_limit_posts_cannot_be_scheduled_for_auto_posting_or_published_now(pub_client, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    long_x = "a" * 300
    manual = make_slot(c, h, vid, platform="x", draft=long_x, hours_from_now=4, to="approved")  # no X connection: it will be posted by hand
    assert patch(c, h, vid, manual, status="scheduled").status_code == 200
    connect(c, h, vid, "x")
    blocked = make_slot(c, h, vid, platform="x", draft="b", hours_from_now=4, to="approved")
    assert patch(c, h, vid, blocked, draft=long_x).status_code == 200
    r = patch(c, h, vid, blocked, status="scheduled")
    assert r.status_code == 400 and "over X's 280 limit" in r.json()["detail"]
    assert c.post(f"/ventures/{vid}/plan/slots/{blocked}/publish", headers=h).status_code == 400
    assert patch(c, h, vid, blocked, draft="short enough", status="scheduled").status_code == 200


def test_deleting_a_venture_removes_its_connections(pub_client, alice_pub):
    c, h = pub_client, alice_pub
    vid = venture(c, h)
    connect(c, h, vid)
    assert c.delete(f"/ventures/{vid}", headers=h).status_code == 204
    with c.app.state.session_factory() as db:
        assert db.scalars(select(Connection)).all() == []
