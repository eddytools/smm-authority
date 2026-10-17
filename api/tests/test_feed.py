import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.jobs.ingest import prune, run_all
from app.models import AIUsage, FeedItem, ItemStatus, Source
from tests.conftest import fresh_rss, login, make_settings, register

BRIEF = {"ideation": {"niche_statement": "Founder-led growth for SaaS", "pillars": ["inbound leads"]}, "icp": {"industry": "SaaS"}}
RSS_URL = "https://blog.example/feed.xml"


def setup_venture(client, headers, name="Acme"):
    return client.post("/ventures", json={"name": name}, headers=headers).json()["id"]


def add_source(client, headers, vid, type="rss", target=RSS_URL, **extra):
    return client.post(f"/ventures/{vid}/sources", json={"type": type, "target": target, **extra}, headers=headers)


def feed(client, headers, vid, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/ventures/{vid}/feed?{q}", headers=headers).json()


# --- sources -------------------------------------------------------------------

def test_source_validation_and_normalisation(client, alice):
    vid = setup_venture(client, alice)
    bad = add_source(client, alice, vid, target="not a url")
    assert bad.status_code == 422 and "RSS target must be an http(s) URL" in bad.text and "website_url" not in bad.text
    assert add_source(client, alice, vid, target="not a url").status_code == 422
    assert add_source(client, alice, vid, target="javascript:alert(1)").status_code == 422
    assert add_source(client, alice, vid, type="reddit", target="bad name!").status_code == 422
    assert add_source(client, alice, vid, type="google_news", target="x").status_code == 422
    r = add_source(client, alice, vid, type="reddit", target="r/Startups")
    assert r.status_code == 201 and r.json()["target"] == "Startups" and r.json()["enabled"] is True
    assert add_source(client, alice, vid, type="reddit", target="/r/Startups").status_code == 409  # same after normalising


def test_source_limit(client, alice):
    vid = setup_venture(client, alice)
    for i in range(20):
        assert add_source(client, alice, vid, target=f"https://f{i}.example/rss").status_code == 201
    assert add_source(client, alice, vid, target="https://one-too-many.example/rss").status_code == 400


def test_sources_are_private_to_owner_and_scoped_to_venture(client, alice, bob, admin_headers):
    v1, v2 = setup_venture(client, alice, "One"), setup_venture(client, alice, "Two")
    sid = add_source(client, alice, v1).json()["id"]
    assert client.get(f"/ventures/{v1}/sources", headers=bob).status_code == 404
    assert add_source(client, bob, v1).status_code == 404
    assert client.delete(f"/ventures/{v2}/sources/{sid}", headers=alice).status_code == 404  # wrong venture
    assert client.get(f"/ventures/{v1}/sources", headers=admin_headers).status_code == 200
    assert client.patch(f"/ventures/{v1}/sources/{sid}", json={"enabled": None}, headers=alice).status_code == 422
    assert client.patch(f"/ventures/{v1}/sources/{sid}", json={"enabled": False}, headers=alice).json()["enabled"] is False
    assert client.delete(f"/ventures/{v1}/sources/{sid}", headers=alice).status_code == 204


# --- refresh / ingest -----------------------------------------------------------

def test_refresh_ingests_dedupes_and_ranks_by_the_brief(client, alice, fetcher):
    fetcher.responses[RSS_URL] = fresh_rss()
    vid = setup_venture(client, alice)
    client.put(f"/ventures/{vid}/brief", json=BRIEF, headers=alice)
    add_source(client, alice, vid)

    out = client.post(f"/ventures/{vid}/feed/refresh", headers=alice).json()
    assert out["new_items"] == 2 and out["sources"][0]["status"] == "ok"
    items = feed(client, alice, vid)
    assert [i["title"] for i in items] == ["Founder-led growth playbook for SaaS", "Ten pasta recipes"]  # brief keywords win
    assert items[0]["rule_score"] > items[1]["rule_score"] and items[0]["relevance"] is None
    assert items[0]["source_label"] == RSS_URL and items[0]["url"].startswith("https://blog.example/growth")

    sources = client.get(f"/ventures/{vid}/sources", headers=alice).json()
    assert sources[0]["last_status"] == "ok" and sources[0]["last_fetched_at"]


def test_second_refresh_adds_nothing_new(make_client, fetcher):
    c = make_client(refresh_min_interval_seconds=0)
    register(c, "a@example.com")
    h = login(c, "a@example.com")
    fetcher.responses[RSS_URL] = fresh_rss()
    vid = setup_venture(c, h)
    add_source(c, h, vid)
    assert c.post(f"/ventures/{vid}/feed/refresh", headers=h).json()["new_items"] == 2
    assert c.post(f"/ventures/{vid}/feed/refresh", headers=h).json()["new_items"] == 0
    assert len(feed(c, h, vid)) == 2


def test_refresh_is_rate_limited(client, alice, fetcher):
    fetcher.responses[RSS_URL] = fresh_rss()
    vid = setup_venture(client, alice)
    add_source(client, alice, vid)
    assert client.post(f"/ventures/{vid}/feed/refresh", headers=alice).status_code == 200
    assert client.post(f"/ventures/{vid}/feed/refresh", headers=alice).status_code == 429


def test_one_failing_source_does_not_block_others_and_error_is_recorded(client, alice, fetcher):
    from app.fetch import FetchError

    fetcher.responses[RSS_URL] = fresh_rss()
    fetcher.responses["https://dead.example/rss"] = FetchError("Connection failed: TimeoutError")
    fetcher.responses["https://junk.example/rss"] = b"<html>not a feed</html>"
    vid = setup_venture(client, alice)
    for url in (RSS_URL, "https://dead.example/rss", "https://junk.example/rss"):
        add_source(client, alice, vid, target=url)
    out = client.post(f"/ventures/{vid}/feed/refresh", headers=alice).json()
    assert [s["status"] for s in out["sources"]] == ["ok", "error", "error"] and out["new_items"] == 2
    by_target = {s["target"]: s for s in client.get(f"/ventures/{vid}/sources", headers=alice).json()}
    assert by_target["https://dead.example/rss"]["last_error"] == "Connection failed: TimeoutError"
    assert by_target["https://junk.example/rss"]["last_status"] == "error"
    assert by_target[RSS_URL]["last_error"] is None


def test_disabled_sources_are_skipped(client, alice, fetcher):
    fetcher.responses[RSS_URL] = fresh_rss()
    vid = setup_venture(client, alice)
    sid = add_source(client, alice, vid).json()["id"]
    client.patch(f"/ventures/{vid}/sources/{sid}", json={"enabled": False}, headers=alice)
    assert client.post(f"/ventures/{vid}/feed/refresh", headers=alice).json() == {"new_items": 0, "sources": []}
    assert fetcher.calls == []


def test_reddit_and_google_news_urls(client, alice, fetcher):
    reddit = json.dumps({"data": {"children": [{"data": {"title": "Ask: how do founders get leads?", "permalink": "/r/startups/comments/1/q/", "score": 40, "num_comments": 12, "created_utc": 1760400000}}]}}).encode()
    fetcher.responses["https://www.reddit.com/r/startups/hot.json?limit=30&raw_json=1"] = reddit
    fetcher.responses["https://news.google.com/rss/search?q=saas+growth&hl=en-US&gl=US&ceid=US:en"] = fresh_rss()
    vid = setup_venture(client, alice)
    add_source(client, alice, vid, type="reddit", target="startups")
    add_source(client, alice, vid, type="google_news", target="saas growth")
    out = client.post(f"/ventures/{vid}/feed/refresh", headers=alice).json()
    assert out["new_items"] == 3
    assert {i["source_type"] for i in feed(client, alice, vid)} == {"reddit", "google_news"}
    reddit_item = next(i for i in feed(client, alice, vid) if i["source_type"] == "reddit")
    assert reddit_item["engagement"] == 52


def test_refresh_requires_access(client, alice, bob):
    vid = setup_venture(client, alice)
    assert client.post(f"/ventures/{vid}/feed/refresh", headers=bob).status_code == 404
    assert client.post(f"/ventures/{vid}/feed/score", headers=bob).status_code == 404
    assert client.get(f"/ventures/{vid}/feed", headers=bob).status_code == 404


# --- triage ---------------------------------------------------------------------

def test_save_dismiss_and_dismissed_items_do_not_come_back(make_client, fetcher):
    c = make_client(refresh_min_interval_seconds=0)
    register(c, "a@example.com")
    h = login(c, "a@example.com")
    fetcher.responses[RSS_URL] = fresh_rss()
    vid = setup_venture(c, h)
    add_source(c, h, vid)
    c.post(f"/ventures/{vid}/feed/refresh", headers=h)
    first, second = feed(c, h, vid)
    assert c.patch(f"/ventures/{vid}/feed/{first['id']}", json={"status": "saved"}, headers=h).json()["status"] == "saved"
    assert c.patch(f"/ventures/{vid}/feed/{second['id']}", json={"status": "dismissed"}, headers=h).status_code == 200
    assert c.patch(f"/ventures/{vid}/feed/{second['id']}", json={"status": "bogus"}, headers=h).status_code == 422

    assert [i["id"] for i in feed(c, h, vid)] == [first["id"]]  # default view hides dismissed
    assert [i["id"] for i in feed(c, h, vid, status="dismissed")] == [second["id"]]
    assert [i["id"] for i in feed(c, h, vid, status="saved")] == [first["id"]]
    c.post(f"/ventures/{vid}/feed/refresh", headers=h)
    assert [i["id"] for i in feed(c, h, vid, status="dismissed")] == [second["id"]]  # not re-added as new
    assert len(feed(c, h, vid, status="new")) == 0


def test_item_from_another_venture_is_404(client, alice, fetcher):
    fetcher.responses[RSS_URL] = fresh_rss()
    v1, v2 = setup_venture(client, alice, "One"), setup_venture(client, alice, "Two")
    add_source(client, alice, v1)
    client.post(f"/ventures/{v1}/feed/refresh", headers=alice)
    item_id = feed(client, alice, v1)[0]["id"]
    assert client.patch(f"/ventures/{v2}/feed/{item_id}", json={"status": "saved"}, headers=alice).status_code == 404


# --- AI scoring -----------------------------------------------------------------

def refreshed(client, headers, fetcher):
    fetcher.responses[RSS_URL] = fresh_rss()
    vid = setup_venture(client, headers)
    client.put(f"/ventures/{vid}/brief", json=BRIEF, headers=headers)
    add_source(client, headers, vid)
    client.post(f"/ventures/{vid}/feed/refresh", headers=headers)
    return vid


def test_scoring_updates_relevance_reorders_and_records_usage(client, alice, fetcher, fake_ai):
    vid = refreshed(client, alice, fetcher)
    assert client.post(f"/ventures/{vid}/feed/score", headers=alice).json() == {"scored": 2}
    items = feed(client, alice, vid)
    assert all(i["relevance"] is not None and i["why_it_matters"] for i in items)
    assert [i["relevance"] for i in items] == sorted((i["relevance"] for i in items), reverse=True)
    venture_info, brief, sent = fake_ai.score_calls[0]
    assert brief["pillars"] == ["inbound leads"] and {s["id"] for s in sent} == {i["id"] for i in items}
    with client.app.state.session_factory() as db:
        (usage,) = db.scalars(select(AIUsage)).all()
    assert usage.feature == "feed_score" and usage.input_tokens == 200


def test_scoring_is_incremental_and_does_not_recharge_for_nothing(client, alice, fetcher, fake_ai):
    vid = refreshed(client, alice, fetcher)
    client.post(f"/ventures/{vid}/feed/score", headers=alice)
    assert client.post(f"/ventures/{vid}/feed/score", headers=alice).json() == {"scored": 0}
    assert len(fake_ai.score_calls) == 1  # nothing left to score, so no second AI call


def test_scoring_sends_only_a_batch_best_rule_scores_first_and_skips_dismissed(make_client, fetcher, fake_ai):
    c = make_client(ai_score_batch=1)
    register(c, "a@example.com")
    h = login(c, "a@example.com")
    vid = refreshed(c, h, fetcher)
    best = feed(c, h, vid)[0]
    assert c.post(f"/ventures/{vid}/feed/score", headers=h).json() == {"scored": 1}
    sent_ids = [i["id"] for i in fake_ai.score_calls[0][2]]
    assert sent_ids == [best["id"]]
    c.patch(f"/ventures/{vid}/feed/{feed(c, h, vid)[1]['id']}", json={"status": "dismissed"}, headers=h)
    assert c.post(f"/ventures/{vid}/feed/score", headers=h).json() == {"scored": 0}  # remaining item was dismissed


def test_scoring_503_without_ai_and_429_over_the_daily_limit(make_client, fetcher):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(make_settings(), ai=None, fetcher=fetcher)) as c:
        register(c, "a@example.com")
        h = login(c, "a@example.com")
        vid = refreshed(c, h, fetcher)
        assert c.post(f"/ventures/{vid}/feed/score", headers=h).status_code == 503

    c = make_client(ai_daily_limit_per_user=1, ai_score_batch=1)
    register(c, "b@example.com")
    h = login(c, "b@example.com")
    vid = refreshed(c, h, fetcher)
    assert c.post(f"/ventures/{vid}/feed/score", headers=h).status_code == 200
    assert c.post(f"/ventures/{vid}/feed/score", headers=h).status_code == 429


# --- housekeeping ---------------------------------------------------------------

def test_prune_drops_old_unsaved_items_but_keeps_saved_and_recent(client, alice, fetcher):
    fetcher.responses[RSS_URL] = fresh_rss()
    vid = setup_venture(client, alice)
    add_source(client, alice, vid)
    client.post(f"/ventures/{vid}/feed/refresh", headers=alice)
    now = datetime.now(timezone.utc)
    with client.app.state.session_factory() as db:
        a, b = db.scalars(select(FeedItem).order_by(FeedItem.id)).unique().all()
        a.fetched_at = now - timedelta(days=60)
        b.fetched_at = now - timedelta(days=60)
        b.status = ItemStatus.saved
        db.commit()
        prune(db, vid, client.app.state.settings, now)
        remaining = db.scalars(select(FeedItem)).unique().all()
    assert [i.id for i in remaining] == [b.id]


def test_run_all_skips_archived_ventures_and_reports_per_source(client, alice, fetcher):
    fetcher.responses[RSS_URL] = fresh_rss()
    live, archived = setup_venture(client, alice, "Live"), setup_venture(client, alice, "Old")
    for vid in (live, archived):
        add_source(client, alice, vid)
    client.patch(f"/ventures/{archived}", json={"is_archived": True}, headers=alice)
    report = run_all(client.app.state.session_factory, client.app.state.settings, fetch=fetcher)
    assert len(report.sources) == 1 and report.new_items == 2
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(FeedItem).where(FeedItem.venture_id == archived)) == 0


def test_deleting_a_venture_removes_sources_and_items(client, alice, fetcher):
    fetcher.responses[RSS_URL] = fresh_rss()
    vid = setup_venture(client, alice)
    add_source(client, alice, vid)
    client.post(f"/ventures/{vid}/feed/refresh", headers=alice)
    assert client.delete(f"/ventures/{vid}", headers=alice).status_code == 204
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Source)) == 0
        assert db.scalar(select(func.count()).select_from(FeedItem)) == 0
