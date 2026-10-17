from datetime import datetime, timedelta, timezone

import pytest

from app.influence import build_digest
from app.models import FeedItem, Source
from tests.conftest import fresh_rss

FEED = "https://ann.example/feed.xml"
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def venture(client, headers, name="Acme"):
    return client.post("/ventures", json={"name": name, "niche": "SaaS growth"}, headers=headers).json()["id"]


def follow(client, headers, vid, name="Ann", platform="linkedin", **extra):
    return client.post(f"/ventures/{vid}/influencers", json={"name": name, "platform": platform, **extra}, headers=headers)


def paste(client, headers, vid, iid, text, url, **extra):
    return client.post(f"/ventures/{vid}/influencers/{iid}/posts", json={"text": text, "url": url, **extra}, headers=headers)


# --- watchlist ------------------------------------------------------------------

def test_follow_list_update_delete(client, alice):
    vid = venture(client, alice)
    r = follow(client, alice, vid, "Ann", profile_url="https://linkedin.com/in/ann", notes="B2B founders")
    assert r.status_code == 201
    body = r.json()
    assert body["feed_url"] is None and body["enabled"] is True and body["posts_30d"] == 0 and body["last_post_at"] is None
    assert follow(client, alice, vid, "Ann").status_code == 409
    assert follow(client, alice, vid, "Bo", platform="blog", feed_url=FEED).json()["feed_url"] == FEED
    assert [i["name"] for i in client.get(f"/ventures/{vid}/influencers", headers=alice).json()] == ["Ann", "Bo"]
    iid = body["id"]
    patched = client.patch(f"/ventures/{vid}/influencers/{iid}", json={"notes": "new", "enabled": False}, headers=alice).json()
    assert patched["notes"] == "new" and patched["enabled"] is False
    assert client.patch(f"/ventures/{vid}/influencers/{iid}", json={"name": None}, headers=alice).status_code == 422
    assert client.delete(f"/ventures/{vid}/influencers/{iid}", headers=alice).status_code == 204
    assert [i["name"] for i in client.get(f"/ventures/{vid}/influencers", headers=alice).json()] == ["Bo"]


def test_validation(client, alice):
    vid = venture(client, alice)
    assert follow(client, alice, vid, "X", platform="myspace").status_code == 422
    assert follow(client, alice, vid, "X", feed_url="javascript:alert(1)").status_code == 422
    assert follow(client, alice, vid, "X", profile_url="not a url").status_code == 422
    assert follow(client, alice, vid, "  ").status_code == 422


def test_limit_and_duplicate_feed(client, alice):
    vid = venture(client, alice)
    assert follow(client, alice, vid, "A", feed_url=FEED).status_code == 201
    dup = follow(client, alice, vid, "B", feed_url=FEED)
    assert dup.status_code == 409 and "feed" in dup.json()["detail"]
    for i in range(24):
        assert follow(client, alice, vid, f"P{i}").status_code == 201
    assert follow(client, alice, vid, "one too many").status_code == 400


def test_private_to_owner_but_visible_to_admin(client, alice, bob, admin_headers):
    vid = venture(client, alice)
    iid = follow(client, alice, vid).json()["id"]
    assert client.get(f"/ventures/{vid}/influencers", headers=bob).status_code == 404
    assert client.get(f"/ventures/{vid}/influencers/digest", headers=bob).status_code == 404
    assert client.patch(f"/ventures/{vid}/influencers/{iid}", json={"notes": "x"}, headers=bob).status_code == 404
    assert paste(client, bob, vid, iid, "hi", "https://x.example/1").status_code == 404
    assert client.delete(f"/ventures/{vid}/influencers/{iid}", headers=bob).status_code == 404
    assert client.get(f"/ventures/{vid}/influencers", headers=admin_headers).status_code == 200


def test_cannot_touch_another_ventures_influencer(client, alice):
    v1, v2 = venture(client, alice, "One"), venture(client, alice, "Two")
    iid = follow(client, alice, v1).json()["id"]
    assert client.delete(f"/ventures/{v2}/influencers/{iid}", headers=alice).status_code == 404
    assert paste(client, alice, v2, iid, "hi", "https://x.example/1").status_code == 404


# --- posts and the feed ---------------------------------------------------------

def test_pasted_post_joins_the_feed_and_is_deduplicated(client, alice):
    vid = venture(client, alice)
    iid = follow(client, alice, vid, "Ann").json()["id"]
    r = paste(client, alice, vid, iid, "Cold email is dead for SaaS founders.\nHere is what works instead.", "https://linkedin.com/posts/ann-1?utm_source=share", engagement=240)
    assert r.status_code == 201 and r.json()["title"] == "Cold email is dead for SaaS founders."
    assert paste(client, alice, vid, iid, "again", "https://linkedin.com/posts/ann-1").status_code == 409  # same link, tracking params ignored
    feed = client.get(f"/ventures/{vid}/feed", headers=alice).json()
    assert len(feed) == 1 and feed[0]["influencer_name"] == "Ann" and feed[0]["author"] == "Ann" and feed[0]["engagement"] == 240
    listed = client.get(f"/ventures/{vid}/influencers", headers=alice).json()[0]
    assert listed["posts_30d"] == 1 and listed["avg_engagement"] == 240 and listed["last_post_at"]


def test_post_validation(client, alice):
    vid = venture(client, alice)
    iid = follow(client, alice, vid).json()["id"]
    assert paste(client, alice, vid, iid, "", "https://x.example/1").status_code == 422
    assert paste(client, alice, vid, iid, "hi", "").status_code == 422
    assert paste(client, alice, vid, iid, "hi", "ftp://x.example/1").status_code == 422
    assert paste(client, alice, vid, iid, "hi", "https://x.example/1", engagement=-1).status_code == 422
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    assert paste(client, alice, vid, iid, "hi", "https://x.example/1", posted_at=future).status_code == 422
    assert paste(client, alice, vid, iid, "x" * 5001, "https://x.example/1").status_code == 422
    long_title = paste(client, alice, vid, iid, "y" * 400, "https://x.example/2").json()["title"]
    assert len(long_title) == 298 and long_title.endswith("…")


def test_influencer_sources_are_managed_with_the_influencer(client, alice):
    vid = venture(client, alice)
    r = follow(client, alice, vid, "Bo", platform="blog", feed_url=FEED).json()
    follow(client, alice, vid, "Ann")
    assert client.get(f"/ventures/{vid}/sources", headers=alice).json() == []  # not in the Sources list
    assert client.delete(f"/ventures/{vid}/sources/{r['source_id']}", headers=alice).status_code == 404
    assert client.patch(f"/ventures/{vid}/sources/{r['source_id']}", json={"enabled": False}, headers=alice).status_code == 404
    assert client.post(f"/ventures/{vid}/sources", json={"type": "manual", "target": "xx"}, headers=alice).status_code == 422


def test_rss_influencer_is_ingested_and_manual_ones_are_not_fetched(client, alice, fetcher):
    vid = venture(client, alice)
    follow(client, alice, vid, "Bo", platform="blog", feed_url=FEED)
    follow(client, alice, vid, "Ann")
    fetcher.responses[FEED] = fresh_rss()
    r = client.post(f"/ventures/{vid}/feed/refresh", headers=alice)
    assert r.status_code == 200 and r.json()["new_items"] >= 1
    assert fetcher.calls == [FEED]  # the manual source is never fetched
    assert {i["influencer_name"] for i in client.get(f"/ventures/{vid}/feed", headers=alice).json()} == {"Bo"}
    by_name = {i["name"]: i for i in client.get(f"/ventures/{vid}/influencers", headers=alice).json()}
    assert by_name["Bo"]["last_status"] == "ok" and by_name["Ann"]["last_status"] is None


def test_failed_feed_is_reported_on_the_influencer(client, alice, fetcher):
    vid = venture(client, alice)
    follow(client, alice, vid, "Bo", platform="blog", feed_url=FEED)
    client.post(f"/ventures/{vid}/feed/refresh", headers=alice)  # FakeFetcher has no response: 404
    bo = client.get(f"/ventures/{vid}/influencers", headers=alice).json()[0]
    assert bo["last_status"] == "error" and "404" in bo["last_error"]


def test_deleting_an_influencer_removes_their_posts_and_source(client, alice):
    vid = venture(client, alice)
    iid = follow(client, alice, vid, "Ann").json()["id"]
    paste(client, alice, vid, iid, "post", "https://x.example/1")
    client.delete(f"/ventures/{vid}/influencers/{iid}", headers=alice)
    assert client.get(f"/ventures/{vid}/feed", headers=alice).json() == []
    # same name can be followed again afterwards
    assert follow(client, alice, vid, "Ann").status_code == 201


def test_deleting_a_venture_cascades(client, alice):
    vid = venture(client, alice)
    iid = follow(client, alice, vid).json()["id"]
    paste(client, alice, vid, iid, "post", "https://x.example/1")
    assert client.delete(f"/ventures/{vid}", headers=alice).status_code == 204


def test_disabled_influencers_drop_out_of_the_digest(client, alice):
    vid = venture(client, alice)
    ids = [follow(client, alice, vid, n).json()["id"] for n in ("Ann", "Bo")]
    for n, iid in zip(("a", "b"), ids):
        paste(client, alice, vid, iid, "Webinars convert badly", f"https://x.example/{n}")
    assert client.get(f"/ventures/{vid}/influencers/digest", headers=alice).json()["topics"]
    client.patch(f"/ventures/{vid}/influencers/{ids[1]}", json={"enabled": False}, headers=alice)
    assert client.get(f"/ventures/{vid}/influencers/digest", headers=alice).json()["topics"] == []


def test_digest_endpoint_flags_topics_you_have_not_covered(client, alice):
    vid = venture(client, alice)
    a, b = (follow(client, alice, vid, n).json()["id"] for n in ("Ann", "Bo"))
    paste(client, alice, vid, a, "Why webinars beat cold outreach for SaaS", "https://x.example/1", engagement=50)
    paste(client, alice, vid, b, "Webinars are my best SaaS channel", "https://x.example/2", engagement=90)
    d = client.get(f"/ventures/{vid}/influencers/digest", headers=alice).json()
    webinar = next(t for t in d["topics"] if t["term"] == "webinar")
    assert webinar["voices"] == 2 and webinar["covered"] is False and webinar["example"]["engagement"] == 90
    # once you plan a post about it, it counts as covered
    client.post(f"/ventures/{vid}/plan/slots", json={"scheduled_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(), "platform": "linkedin", "post_type": "educational", "topic": "Our take on webinars"}, headers=alice)
    d = client.get(f"/ventures/{vid}/influencers/digest", headers=alice).json()
    assert next(t for t in d["topics"] if t["term"] == "webinar")["covered"] is True
    assert client.get(f"/ventures/{vid}/influencers/digest?days=3", headers=alice).status_code == 422


# --- digest rules ---------------------------------------------------------------

def post(iid, name, title, eng=0, summary=None, days=1):
    return {"influencer_id": iid, "influencer": name, "title": title, "summary": summary, "url": f"https://x.example/{iid}/{title}", "engagement": eng, "published_at": NOW - timedelta(days=days)}


def digest(posts, own=(), niche=()):
    return build_digest(posts, list(own), set(niche), NOW, 14)


def test_one_voice_repeating_themselves_is_not_a_trend():
    d = digest([post(1, "Ann", "Webinars work"), post(1, "Ann", "More webinars news")])
    assert d["topics"] == []


def test_topic_needs_two_posts_from_two_voices_and_merges_plurals():
    d = digest([post(1, "Ann", "Lead magnets that convert"), post(2, "Bo", "My lead magnet teardown"), post(3, "Cy", "Pasta recipes")])
    t = d["topics"][0]
    assert t["term"] == "lead" and t["voices"] == 2 and t["influencers"] == ["Ann", "Bo"]
    assert all(x["term"] != "pasta" for x in d["topics"])


def test_topics_ranked_by_voices_then_posts_and_niche_breaks_ties():
    posts = [post(1, "A", "alpha beta"), post(2, "B", "alpha beta"), post(3, "C", "alpha"), post(1, "A", "gamma delta"), post(2, "B", "gamma delta")]
    d = digest(posts, niche={"beta"})
    assert d["topics"][0]["term"] == "alpha"  # 3 voices
    rest = [t["term"] for t in d["topics"][1:]]
    assert rest[0] == "beta"  # tie with gamma/delta on voices and posts: the one in your niche first


def test_gaps_are_niche_topics_you_have_not_posted_about():
    posts = [post(1, "A", "webinar funnel tips"), post(2, "B", "webinar funnel results"), post(1, "A", "sourdough starter"), post(2, "B", "sourdough starter")]
    d = digest(posts, own=["Our webinar playbook"], niche={"webinar", "funnel", "sourdough"})
    assert "funnel" in d["gaps"] and "webinar" not in d["gaps"]


def test_per_influencer_summary_and_empty_note():
    d = digest([post(1, "Ann", "a", 10), post(1, "Ann", "b", 30)])
    v = d["voices"][0]
    assert v["posts"] == 2 and v["avg_engagement"] == 20 and v["top_post"]["engagement"] == 30
    assert "No posts" in digest([])["note"]
