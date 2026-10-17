from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.analytics import PULL_AFTER, run_pulls
from app.models import Connection, PlanSlot
from app.publishers import ProviderError
from tests.test_publishing import connect, make_slot, run, slot, venture

NUMBERS = {"impressions": 1200, "reactions": 40, "comments": 6, "shares": 3, "saves": 2}


def pull(client, now):
    return run_pulls(client.app.state.session_factory, client.app.state.publishing, now)


def published_x(client, headers, providers, vid, *, platform="x", n=1):
    """Connect the platform and publish n posts through the app. Returns slot ids."""
    connect(client, headers, vid, platform)
    ids = [make_slot(client, headers, vid, platform=platform, hours_from_now=-1 - i) for i in range(n)]
    run(client)
    return ids


def published_at(client, sid):
    with client.app.state.session_factory() as db:
        return db.get(PlanSlot, sid).published_at.replace(tzinfo=timezone.utc)


def metrics(client, headers, vid, sid):
    return client.get(f"/ventures/{vid}/plan/slots/{sid}/metrics", headers=headers).json()


# --- the schedule ---------------------------------------------------------------

def test_nothing_is_pulled_before_a_day_has_passed(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    when = published_at(pub_client, sid)
    assert pull(pub_client, when + timedelta(hours=23)) == [] and providers["x"].metric_calls == []


def test_pulls_at_1_3_7_and_14_days_then_stops(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    when = published_at(pub_client, sid)
    providers["x"].metric_results = {"post-1": NUMBERS}
    for step, age in enumerate(PULL_AFTER, 1):
        assert [o.status for o in pull(pub_client, when + age)] == ["updated"], f"pull {step}"
        assert pull(pub_client, when + age + timedelta(minutes=5)) == []  # not due again until the next step
    assert len(providers["x"].metric_calls) == 4
    assert pull(pub_client, when + timedelta(days=60)) == []  # done for good


def test_first_pull_records_numbers_and_moves_the_post_to_analysed(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    assert slot(pub_client, alice_pub, vid, sid)["status"] == "published"
    providers["x"].metric_results = {"post-1": NUMBERS}
    pull(pub_client, published_at(pub_client, sid) + timedelta(days=1))
    m = metrics(pub_client, alice_pub, vid, sid)
    assert (m["impressions"], m["reactions"], m["comments"], m["shares"], m["saves"]) == (1200, 40, 6, 3, 2) and m["source"] == "auto"
    assert m["clicks"] == m["follows"] == m["leads"] == 0
    assert slot(pub_client, alice_pub, vid, sid)["status"] == "analysed"
    token, ids = providers["x"].metric_calls[0]
    assert ids == ["post-1"] and token == "fresh-access"  # a day later the short-lived token had expired, so it was refreshed first


def test_posts_are_batched_per_connection(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    sids = published_x(pub_client, alice_pub, providers, vid, n=3)
    providers["x"].metric_results = {f"post-{i}": NUMBERS for i in (1, 2, 3)}
    outcomes = pull(pub_client, published_at(pub_client, sids[0]) + timedelta(days=2))
    assert [o.status for o in outcomes] == ["updated"] * 3 and len(providers["x"].metric_calls) == 1


# --- your numbers win -----------------------------------------------------------

def test_hand_entered_numbers_are_never_overwritten(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    pub_client.put(f"/ventures/{vid}/plan/slots/{sid}/metrics", json={"impressions": 777, "leads": 2}, headers=alice_pub)
    providers["x"].metric_results = {"post-1": NUMBERS}
    assert pull(pub_client, published_at(pub_client, sid) + timedelta(days=2)) == []
    m = metrics(pub_client, alice_pub, vid, sid)
    assert m["impressions"] == 777 and m["source"] == "manual" and providers["x"].metric_calls == []


def test_adding_leads_to_pulled_numbers_keeps_them_automatic_but_editing_a_pulled_number_does_not(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    when = published_at(pub_client, sid)
    providers["x"].metric_results = {"post-1": NUMBERS}
    pull(pub_client, when + timedelta(days=1))
    put = lambda **b: pub_client.put(f"/ventures/{vid}/plan/slots/{sid}/metrics", json={**NUMBERS, "clicks": 0, "follows": 0, "leads": 0, **b}, headers=alice_pub)
    assert put(leads=3, clicks=11).json()["source"] == "auto"
    providers["x"].metric_results = {"post-1": {**NUMBERS, "impressions": 5000}}
    pull(pub_client, when + timedelta(days=3))
    m = metrics(pub_client, alice_pub, vid, sid)
    assert m["impressions"] == 5000 and m["leads"] == 3 and m["clicks"] == 11  # platform fields refreshed, yours untouched
    assert put(impressions=9999).json()["source"] == "manual"
    assert pull(pub_client, when + timedelta(days=7)) == []


def test_missing_fields_do_not_overwrite_existing_values(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    when = published_at(pub_client, sid)
    providers["x"].metric_results = {"post-1": NUMBERS}
    pull(pub_client, when + timedelta(days=1))
    providers["x"].metric_results = {"post-1": {"reactions": 55}}  # X returned no impressions this time
    pull(pub_client, when + timedelta(days=3))
    m = metrics(pub_client, alice_pub, vid, sid)
    assert m["reactions"] == 55 and m["impressions"] == 1200


# --- what is skipped ------------------------------------------------------------

def test_linkedin_is_never_pulled(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid, platform="linkedin")
    assert pull(pub_client, published_at(pub_client, sid) + timedelta(days=30)) == []
    r = pub_client.post(f"/ventures/{vid}/plan/slots/{sid}/metrics/refresh", headers=alice_pub)
    assert r.status_code == 400 and "by hand" in r.json()["detail"]
    st = pub_client.get(f"/ventures/{vid}/plan/slots/{sid}/metrics/auto", headers=alice_pub).json()
    assert st["supported"] is False and st["next_pull_at"] is None


def test_posts_not_published_by_the_app_and_disconnected_accounts_are_skipped(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    when = published_at(pub_client, sid)
    with pub_client.app.state.session_factory() as db:
        manual = PlanSlot(venture_id=vid, scheduled_at=when, platform="x", post_type="story", stage="mofu", topic="by hand", status="published", published_at=when)
        db.add(manual)
        conn = db.scalar(select(Connection).where(Connection.venture_id == vid))
        conn.status = "revoked"
        db.commit()
    providers["x"].metric_results = {"post-1": NUMBERS}
    assert pull(pub_client, when + timedelta(days=2)) == [] and providers["x"].metric_calls == []


# --- failures -------------------------------------------------------------------

def test_transient_errors_retry_on_the_next_pass_without_using_up_a_pull(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    when = published_at(pub_client, sid) + timedelta(days=1)
    providers["x"].metric_errors = [ProviderError("X post numbers: busy (429)", transient=True, status=429)]
    assert [o.status for o in pull(pub_client, when)] == ["retry"]
    st = pub_client.get(f"/ventures/{vid}/plan/slots/{sid}/metrics/auto", headers=alice_pub).json()
    assert st["pulls_done"] == 0 and "busy" in st["error"]
    providers["x"].metric_results = {"post-1": NUMBERS}
    assert [o.status for o in pull(pub_client, when + timedelta(minutes=10))] == ["updated"]
    assert pub_client.get(f"/ventures/{vid}/plan/slots/{sid}/metrics/auto", headers=alice_pub).json()["error"] is None


def test_a_rejected_token_marks_the_connection_for_reconnect(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    providers["x"].metric_errors = [ProviderError("rejected (401)", reauth=True, status=401)]
    assert [o.status for o in pull(pub_client, published_at(pub_client, sid) + timedelta(days=1))] == ["reconnect"]
    integ = {r["platform"]: r for r in pub_client.get(f"/ventures/{vid}/integrations", headers=alice_pub).json()}
    assert integ["x"]["status"] == "needs_reconnect"
    assert pull(pub_client, published_at(pub_client, sid) + timedelta(days=2)) == []  # no active connection: nothing more is attempted


def test_forbidden_stops_pulling_that_post_and_explains(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    when = published_at(pub_client, sid)
    providers["x"].metric_errors = [ProviderError("X post numbers: 403 forbidden", status=403)]
    assert [o.status for o in pull(pub_client, when + timedelta(days=1))] == ["forbidden"]
    st = pub_client.get(f"/ventures/{vid}/plan/slots/{sid}/metrics/auto", headers=alice_pub).json()
    assert "API access level" in st["error"] and st["next_pull_at"] is None
    assert pull(pub_client, when + timedelta(days=5)) == [] and len(providers["x"].metric_calls) == 1


def test_a_deleted_post_is_reported_and_not_asked_for_again(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    when = published_at(pub_client, sid)
    providers["x"].metric_results = {}  # X no longer knows post-1
    assert [o.status for o in pull(pub_client, when + timedelta(days=1))] == ["missing"]
    assert pub_client.get(f"/ventures/{vid}/plan/slots/{sid}/metrics", headers=alice_pub).json() is None  # no fake zero row
    assert slot(pub_client, alice_pub, vid, sid)["status"] == "published"
    assert pull(pub_client, when + timedelta(days=5)) == []


# --- the refresh button ---------------------------------------------------------

def test_refresh_pulls_now_hands_a_manual_post_back_and_is_rate_limited(pub_client, alice_pub, bob_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    pub_client.put(f"/ventures/{vid}/plan/slots/{sid}/metrics", json={"impressions": 5, "leads": 1}, headers=alice_pub)
    providers["x"].metric_results = {"post-1": NUMBERS}
    r = pub_client.post(f"/ventures/{vid}/plan/slots/{sid}/metrics/refresh", headers=alice_pub)
    assert r.status_code == 200 and r.json()["impressions"] == 1200 and r.json()["source"] == "auto" and r.json()["leads"] == 1
    assert pub_client.post(f"/ventures/{vid}/plan/slots/{sid}/metrics/refresh", headers=alice_pub).status_code == 429
    assert pub_client.post(f"/ventures/{vid}/plan/slots/{sid}/metrics/refresh", headers=bob_pub).status_code == 404
    st = pub_client.get(f"/ventures/{vid}/plan/slots/{sid}/metrics/auto", headers=alice_pub).json()
    assert st["supported"] and st["connected"] and st["source"] == "auto" and st["last_pulled_at"]


def test_refresh_errors_map_to_clear_statuses(pub_client, alice_pub, providers):
    vid = venture(pub_client, alice_pub)
    (sid,) = published_x(pub_client, alice_pub, providers, vid)
    providers["x"].metric_errors = [ProviderError("busy", transient=True, status=429)]
    assert pub_client.post(f"/ventures/{vid}/plan/slots/{sid}/metrics/refresh", headers=alice_pub).status_code == 502
    idea = make_slot(pub_client, alice_pub, vid, platform="x", hours_from_now=5, to="idea")
    assert pub_client.post(f"/ventures/{vid}/plan/slots/{idea}/metrics/refresh", headers=alice_pub).status_code == 400


def test_the_job_entry_point_imports_cleanly():
    import app.jobs.pull_metrics as job

    assert callable(job.main)
