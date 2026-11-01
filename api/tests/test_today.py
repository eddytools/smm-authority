from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models import FeedItem, Source
from app.today import STALE_AFTER, coverage, day_bounds, source_health, suggestions, week_bounds, week_progress
from tests.conftest import fresh_rss

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)  # a Wednesday


def venture(client, headers, name="Acme"):
    return client.post("/ventures", json={"name": name, "niche": "SaaS growth"}, headers=headers).json()["id"]


def get(client, headers, vid, tz="UTC"):
    return client.get(f"/ventures/{vid}/today?tz={tz}", headers=headers)


def slot(client, headers, vid, hours=2, platform="linkedin", topic="A post", draft=None):
    when = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    sid = client.post(f"/ventures/{vid}/plan/slots", json={"scheduled_at": when, "platform": platform, "post_type": "story", "topic": topic}, headers=headers).json()["id"]
    if draft:
        client.patch(f"/ventures/{vid}/plan/slots/{sid}", json={"draft": draft, "status": "drafted"}, headers=headers)
    return sid


# --- pure rules ------------------------------------------------------------------

def test_source_health_and_coverage():
    assert source_health(None, None, NOW) == "never"
    assert source_health("ok", NOW - timedelta(hours=2), NOW) == "ok"
    assert source_health("ok", NOW - STALE_AFTER - timedelta(minutes=1), NOW) == "stale"
    assert source_health("error", NOW - timedelta(hours=1), NOW) == "error"
    assert source_health("ok", (NOW - timedelta(hours=1)).replace(tzinfo=None), NOW) == "ok"  # naive timestamps from SQLite are read as UTC
    c = coverage(["ok", "ok", "error", "stale"])
    assert c == {"sources": 4, "ok": 2, "error": 1, "stale": 1, "never": 0, "pct": 50}
    assert coverage([])["pct"] is None


def test_day_and_week_bounds_follow_the_users_timezone():
    tz = ZoneInfo("Asia/Kolkata")  # UTC+5:30: 10:00 UTC is 15:30 on the 4th
    start, end, dates = day_bounds(NOW, tz, 7)
    assert dates[0].isoformat() == "2026-11-04" and len(dates) == 7 and end - start == timedelta(days=7)
    late = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)  # already the 5th in Kolkata
    assert day_bounds(late, tz, 1)[2][0].isoformat() == "2026-11-05"
    ws, we = week_bounds(NOW, ZoneInfo("UTC"))
    assert ws.isoformat().startswith("2026-11-02") and we - ws == timedelta(days=7)  # Monday to Monday


def test_week_progress_ignores_skipped_and_handles_empty():
    p = week_progress([{"status": s} for s in ("published", "analysed", "scheduled", "idea", "skipped")])
    assert (p["planned"], p["published"], p["skipped"], p["pct"]) == (4, 2, 1, 50)
    assert week_progress([])["pct"] is None


def test_suggestions_are_ordered_deduplicated_and_capped():
    gap = {"term": "webinar", "influencers": ["Ann", "Bo"], "voices": 2, "posts": 3}
    heat = {"term": "webinar", "trend": "rising", "posts": 3, "communities": ["r/x"]}
    heat2 = {"term": "pricing", "trend": "new", "posts": 2, "communities": ["r/y"]}
    tips = suggestions(topic_gaps=[gap], heat_gaps=[heat, heat2], draft_slots=[{"topic": "T", "platform": "x", "when": "Thu 09:00"}] * 3,
                       opportunities=[{"title": "How?", "source_label": "r/z"}] * 3, saved_items=[{"title": "Saved"}] * 2, setup={})
    kinds = [t["kind"] for t in tips]
    assert kinds[0] == "topic_gap" and "webinar" in tips[0]["title"] and sum(t.get("term") == "webinar" for t in tips) == 1
    assert len(tips) <= 6 and "reply" in kinds and "draft" in kinds
    assert [t["link"] for t in tips if t["kind"] == "draft"] == ["plan", "plan"]  # two at most


def test_empty_workspace_gets_setup_nudges_and_a_busy_one_does_not():
    setup = {"brief": False, "sources": False, "influencers": False, "plan": False}
    tips = suggestions(topic_gaps=[], heat_gaps=[], draft_slots=[], opportunities=[], saved_items=[], setup=setup)
    assert [t["link"] for t in tips] == ["setup", "feed", "influencers", "plan"] and all(t["kind"] == "setup" for t in tips)
    done = suggestions(topic_gaps=[], heat_gaps=[], draft_slots=[], opportunities=[], saved_items=[], setup={k: True for k in setup})
    assert done == []


# --- the endpoint ----------------------------------------------------------------

def test_empty_venture_returns_a_complete_empty_summary(client, alice):
    d = get(client, alice, venture(client, alice)).json()
    assert d["setup"] == {"brief": False, "sources": False, "influencers": False, "plan": False}
    assert d["fetch"]["coverage"]["pct"] is None and d["fetch"]["items_24h"] == 0 and len(d["fetch"]["by_day"]) == 7
    assert d["trending"]["items"] == [] and d["influencers"]["people"] == [] and len(d["calendar"]["days"]) == 7
    assert d["calendar"]["week"]["pct"] is None and [t["link"] for t in d["suggestions"]][:1] == ["setup"]


def test_access_rules_and_timezone_validation(client, alice, bob, admin_headers):
    vid = venture(client, alice)
    assert get(client, bob, vid).status_code == 404
    assert get(client, admin_headers, vid).status_code == 200
    assert client.get(f"/ventures/{vid}/today").status_code == 401
    assert get(client, alice, vid, tz="Mars/Base").status_code == 422
    assert get(client, alice, vid, tz="America/New_York").status_code == 200


def test_fetched_details_show_health_counts_and_progress(client, alice, fetcher):
    vid = venture(client, alice)
    good, bad = "https://good.example/feed.xml", "https://bad.example/feed.xml"
    for url in (good, bad):
        client.post(f"/ventures/{vid}/sources", json={"type": "rss", "target": url, "label": url.split("//")[1].split("/")[0]}, headers=alice)
    fetcher.responses[good] = fresh_rss()
    client.post(f"/ventures/{vid}/feed/refresh", headers=alice)
    f = get(client, alice, vid).json()["fetch"]
    by = {s["label"]: s for s in f["sources"]}
    assert by["good.example"]["health"] == "ok" and by["good.example"]["new_24h"] >= 1 and by["good.example"]["items_7d"] >= 1
    assert by["bad.example"]["health"] == "error" and "404" in by["bad.example"]["error"] and by["bad.example"]["new_24h"] == 0
    assert f["coverage"] == {"sources": 2, "ok": 1, "error": 1, "stale": 0, "never": 0, "pct": 50}
    assert f["items_24h"] == by["good.example"]["new_24h"] and f["unreviewed"] >= 1 and f["last_fetched_at"]
    assert sum(d["items"] for d in f["by_day"]) == f["items_24h"] and f["by_day"][-1]["items"] == f["items_24h"]  # all fetched today
    client.patch(f"/ventures/{vid}/sources/{by['bad.example']['id']}", json={"enabled": False}, headers=alice)
    f = get(client, alice, vid).json()["fetch"]
    assert f["coverage"]["sources"] == 1 and f["coverage"]["pct"] == 100
    assert {s["label"]: s["health"] for s in f["sources"]}["bad.example"] == "paused"


def test_influencers_with_avatars_latest_posts_and_topics(client, alice):
    vid = venture(client, alice)
    a = client.post(f"/ventures/{vid}/influencers", json={"name": "Ann", "platform": "linkedin", "avatar_url": "https://img.example/ann.jpg"}, headers=alice).json()
    b = client.post(f"/ventures/{vid}/influencers", json={"name": "Bo", "platform": "x"}, headers=alice).json()
    client.post(f"/ventures/{vid}/influencers", json={"name": "Quiet", "platform": "blog"}, headers=alice)
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    client.post(f"/ventures/{vid}/influencers/{a['id']}/posts", json={"text": "Webinars beat cold email", "url": "https://x.example/1", "engagement": 40, "posted_at": old}, headers=alice)
    client.post(f"/ventures/{vid}/influencers/{b['id']}/posts", json={"text": "Why webinars work for SaaS", "url": "https://x.example/2", "engagement": 90}, headers=alice)
    d = get(client, alice, vid).json()
    people = d["influencers"]["people"]
    assert [p["name"] for p in people] == ["Bo", "Ann", "Quiet"]  # most recent post first, silent ones last
    assert people[1]["avatar_url"] == "https://img.example/ann.jpg" and people[0]["avatar_url"] is None
    assert people[0]["latest"]["title"] == "Why webinars work for SaaS" and people[0]["posts_7d"] == 1 and people[2]["latest"] is None
    assert any(t["term"] == "webinar" and t["voices"] == 2 for t in d["influencers"]["topics"])
    gap = [s for s in d["suggestions"] if s["kind"] == "topic_gap"]
    assert gap and gap[0]["term"] == "webinar" and "Ann" in gap[0]["title"]
    # a paused influencer drops out
    client.patch(f"/ventures/{vid}/influencers/{b['id']}", json={"enabled": False}, headers=alice)
    assert "Bo" not in [p["name"] for p in get(client, alice, vid).json()["influencers"]["people"]]


def test_avatar_links_must_be_https_images_urls(client, alice):
    vid = venture(client, alice)
    post = lambda url: client.post(f"/ventures/{vid}/influencers", json={"name": "N" + url[-3:], "platform": "x", "avatar_url": url}, headers=alice).status_code
    assert post("https://img.example/a.png") == 201
    assert post("http://img.example/a.png") == 422 and post("javascript:alert(1)") == 422 and post("not a url") == 422
    iid = client.get(f"/ventures/{vid}/influencers", headers=alice).json()[0]["id"]
    assert client.patch(f"/ventures/{vid}/influencers/{iid}", json={"avatar_url": "http://x.example/a.png"}, headers=alice).status_code == 422
    assert client.patch(f"/ventures/{vid}/influencers/{iid}", json={"avatar_url": "https://x.example/b.png"}, headers=alice).json()["avatar_url"] == "https://x.example/b.png"


def test_trending_ranks_feed_items_and_excludes_dismissed(client, alice, fetcher):
    vid = venture(client, alice)
    fetcher.responses["https://blog.example/feed.xml"] = fresh_rss()
    client.post(f"/ventures/{vid}/sources", json={"type": "rss", "target": "https://blog.example/feed.xml"}, headers=alice)
    client.post(f"/ventures/{vid}/feed/refresh", headers=alice)
    items = get(client, alice, vid).json()["trending"]["items"]
    assert items and items == sorted(items, key=lambda i: -i["score"]) and items[0]["source_type"] == "rss" and items[0]["ai_scored"] is False and items[0]["icon"] == "rss"
    feed_id = client.get(f"/ventures/{vid}/feed", headers=alice).json()[0]["id"]
    client.patch(f"/ventures/{vid}/feed/{feed_id}", json={"status": "dismissed"}, headers=alice)
    assert feed_id not in [i["id"] for i in get(client, alice, vid).json()["trending"]["items"]]


def test_calendar_groups_upcoming_posts_by_day_and_reports_late_ones(client, alice):
    vid = venture(client, alice)
    slot(client, alice, vid, hours=1, topic="Soon", draft="Ready draft")
    slot(client, alice, vid, hours=60, platform="x", topic="Later")
    slot(client, alice, vid, hours=-30, topic="Missed", draft="Draft")
    slot(client, alice, vid, hours=24 * 12, topic="Next month")
    cal = get(client, alice, vid).json()["calendar"]
    in_days = {s["topic"]: d["date"] for d in cal["days"] for s in d["slots"]}
    assert set(in_days) == {"Soon", "Later"} and cal["total_upcoming"] == 2 and cal["days"][0]["is_today"] is True
    slots = {s["topic"]: s for d in cal["days"] for s in d["slots"]}
    assert slots["Soon"]["has_draft"] is True and slots["Later"]["has_draft"] is False and slots["Soon"]["status"] == "drafted"
    assert [s["topic"] for s in cal["late"]] == ["Missed"]  # in the past and still not published
    assert cal["week"]["planned"] >= 1


def test_idea_soon_without_a_draft_is_suggested(client, alice):
    vid = venture(client, alice)
    slot(client, alice, vid, hours=5, topic="Needs words")
    slot(client, alice, vid, hours=6, topic="Has words", draft="Done")
    tips = [t for t in get(client, alice, vid).json()["suggestions"] if t["kind"] == "draft"]
    assert [t["title"] for t in tips] == ["Write the draft: Needs words"]


def test_calendar_days_use_the_callers_timezone(client, alice):
    vid = venture(client, alice)
    slot(client, alice, vid, hours=1, topic="Now-ish")
    for tz in ("Pacific/Auckland", "Pacific/Pago_Pago"):
        cal = get(client, alice, vid, tz=tz).json()["calendar"]
        placed = [d["date"] for d in cal["days"] if d["slots"]]
        assert len(placed) == 1
    a = get(client, alice, vid, tz="Pacific/Auckland").json()["calendar"]["days"][0]["date"]
    b = get(client, alice, vid, tz="Pacific/Pago_Pago").json()["calendar"]["days"][0]["date"]
    assert a >= b  # Auckland is a day ahead of Pago Pago


def test_reply_opportunities_and_saved_items_appear_as_suggestions(client, alice, fetcher):
    vid = venture(client, alice)
    fetcher.responses["https://blog.example/feed.xml"] = fresh_rss().replace(b"Founder-led growth playbook for SaaS", b"How do SaaS founders get inbound leads?")
    client.post(f"/ventures/{vid}/sources", json={"type": "rss", "target": "https://blog.example/feed.xml"}, headers=alice)
    client.post(f"/ventures/{vid}/feed/refresh", headers=alice)
    feed_id = client.get(f"/ventures/{vid}/feed", headers=alice).json()[0]["id"]
    client.patch(f"/ventures/{vid}/feed/{feed_id}", json={"status": "saved"}, headers=alice)
    kinds = {t["kind"] for t in get(client, alice, vid).json()["suggestions"]}
    assert {"reply", "saved"} <= kinds


def test_icons_follow_the_platform_of_pasted_sources(client, alice):
    vid = venture(client, alice)
    iid = client.post(f"/ventures/{vid}/influencers", json={"name": "Ann", "platform": "linkedin"}, headers=alice).json()["id"]
    cid = client.post(f"/ventures/{vid}/communities", json={"name": "Grp", "platform": "facebook"}, headers=alice).json()["id"]
    client.post(f"/ventures/{vid}/influencers/{iid}/posts", json={"text": "Post one", "url": "https://x.example/1"}, headers=alice)
    client.post(f"/ventures/{vid}/communities/{cid}/posts", json={"text": "Post two", "url": "https://x.example/2"}, headers=alice)
    d = get(client, alice, vid).json()
    assert {i["title"]: i["icon"] for i in d["trending"]["items"]} == {"Post one": "linkedin", "Post two": "facebook"}
    rows = {s["label"]: s for s in d["fetch"]["sources"]}
    assert {k: v["icon"] for k, v in rows.items()} == {"Ann": "linkedin", "Grp": "facebook"}
    assert all(r["health"] == "manual" and r["new_24h"] == 1 and r["last_fetched_at"] for r in rows.values())
    assert d["fetch"]["coverage"]["sources"] == 0 and d["fetch"]["last_fetched_at"] is None  # pasted sources aren't "fetched", so they don't count towards coverage
