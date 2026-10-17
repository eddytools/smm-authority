from datetime import datetime, timedelta, timezone

from app.heat import build_heat
from tests.conftest import fresh_rss

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def venture(client, headers, name="Acme"):
    return client.post("/ventures", json={"name": name, "niche": "SaaS growth"}, headers=headers).json()["id"]


def group(client, headers, vid, name="SaaS Founders", platform="linkedin", **extra):
    return client.post(f"/ventures/{vid}/communities", json={"name": name, "platform": platform, **extra}, headers=headers)


def paste(client, headers, vid, cid, text, url, **extra):
    return client.post(f"/ventures/{vid}/communities/{cid}/posts", json={"text": text, "url": url, **extra}, headers=headers)


def heat(client, headers, vid, **q):
    return client.get(f"/ventures/{vid}/communities/heat" + ("?" + "&".join(f"{k}={v}" for k, v in q.items()) if q else ""), headers=headers)


# --- groups API -----------------------------------------------------------------

def test_add_list_update_delete(client, alice):
    vid = venture(client, alice)
    r = group(client, alice, vid, url="https://linkedin.com/groups/1", notes="my ICP lives here")
    assert r.status_code == 201 and r.json()["posts_30d"] == 0 and r.json()["median_engagement"] is None
    assert group(client, alice, vid).status_code == 409
    cid = r.json()["id"]
    assert client.patch(f"/ventures/{vid}/communities/{cid}", json={"enabled": False}, headers=alice).json()["enabled"] is False
    assert client.patch(f"/ventures/{vid}/communities/{cid}", json={"enabled": None}, headers=alice).status_code == 422
    assert client.delete(f"/ventures/{vid}/communities/{cid}", headers=alice).status_code == 204
    assert client.get(f"/ventures/{vid}/communities", headers=alice).json() == []
    assert group(client, alice, vid).status_code == 201  # name is free again


def test_validation_and_limit(client, alice):
    vid = venture(client, alice)
    assert group(client, alice, vid, platform="myspace").status_code == 422
    assert group(client, alice, vid, url="javascript:x").status_code == 422
    assert group(client, alice, vid, name=" ").status_code == 422
    for i in range(15):
        assert group(client, alice, vid, name=f"G{i}").status_code == 201
    assert group(client, alice, vid, name="too many").status_code == 400


def test_access_rules(client, alice, bob, admin_headers):
    vid = venture(client, alice)
    cid = group(client, alice, vid).json()["id"]
    assert client.get(f"/ventures/{vid}/communities", headers=bob).status_code == 404
    assert heat(client, bob, vid).status_code == 404
    assert paste(client, bob, vid, cid, "hi", "https://x.example/1").status_code == 404
    assert client.delete(f"/ventures/{vid}/communities/{cid}", headers=bob).status_code == 404
    assert heat(client, admin_headers, vid).status_code == 200
    other = venture(client, alice, "Other")
    assert paste(client, alice, other, cid, "hi", "https://x.example/1").status_code == 404


def test_pasted_post_sums_likes_and_comments_and_joins_the_feed(client, alice):
    vid = venture(client, alice)
    cid = group(client, alice, vid).json()["id"]
    r = paste(client, alice, vid, cid, "Anyone tried webinars for lead gen?", "https://fb.example/p/1", likes=30, comments=12)
    assert r.status_code == 201
    assert paste(client, alice, vid, cid, "dup", "https://fb.example/p/1").status_code == 409
    assert paste(client, alice, vid, cid, "x", "https://fb.example/p/2", likes=-1).status_code == 422
    assert paste(client, alice, vid, cid, "x", "ftp://fb.example/p/2").status_code == 422
    feed = client.get(f"/ventures/{vid}/feed", headers=alice).json()
    assert len(feed) == 1 and feed[0]["engagement"] == 42 and feed[0]["source_label"] == "SaaS Founders" and feed[0]["influencer_name"] is None
    assert client.get(f"/ventures/{vid}/sources", headers=alice).json() == []  # managed with the community, not in Sources
    listed = client.get(f"/ventures/{vid}/communities", headers=alice).json()[0]
    assert listed["posts_30d"] == 1 and listed["median_engagement"] == 42


def test_deleting_a_community_removes_its_posts_and_a_venture_cascades(client, alice):
    vid = venture(client, alice)
    cid = group(client, alice, vid).json()["id"]
    paste(client, alice, vid, cid, "post", "https://x.example/1")
    client.delete(f"/ventures/{vid}/communities/{cid}", headers=alice)
    assert client.get(f"/ventures/{vid}/feed", headers=alice).json() == []
    group(client, alice, vid)
    assert client.delete(f"/ventures/{vid}", headers=alice).status_code == 204


def test_heat_includes_subreddits_and_groups_but_not_influencers_or_plain_rss(client, alice, fetcher):
    vid = venture(client, alice)
    cid = group(client, alice, vid).json()["id"]
    paste(client, alice, vid, cid, "Webinars for pipeline", "https://x.example/1", likes=5)
    paste(client, alice, vid, cid, "Webinars are working", "https://x.example/2", likes=9)
    iid = client.post(f"/ventures/{vid}/influencers", json={"name": "Ann", "platform": "x"}, headers=alice).json()["id"]
    client.post(f"/ventures/{vid}/influencers/{iid}/posts", json={"text": "Webinars rule", "url": "https://x.example/inf"}, headers=alice)
    client.post(f"/ventures/{vid}/sources", json={"type": "reddit", "target": "startups"}, headers=alice)
    client.post(f"/ventures/{vid}/sources", json={"type": "rss", "target": "https://blog.example/feed.xml"}, headers=alice)
    import json as _json

    def reddit(title, score, hours):
        return {"data": {"title": title, "permalink": f"/r/startups/{abs(hash(title))}", "score": score, "num_comments": 3, "selftext": "", "created_utc": (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp(), "author": "u", "id": str(abs(hash(title)))[:6]}}

    fetcher.responses["https://www.reddit.com/r/startups/hot.json?limit=30&raw_json=1"] = _json.dumps({"data": {"children": [reddit("Webinars dead?", 40, 5)]}}).encode()
    fetcher.responses["https://blog.example/feed.xml"] = fresh_rss()
    client.post(f"/ventures/{vid}/feed/refresh", headers=alice)
    d = heat(client, alice, vid).json()
    names = {c["community"] for c in d["communities"]}
    assert "SaaS Founders" in names and "r/startups" in names and "Ann" not in names and len(names) == 2
    webinar = next(t for t in d["topics"] if t["term"] == "webinar")
    assert webinar["posts"] == 3 and set(webinar["communities"]) == {"SaaS Founders", "r/startups"}  # the influencer's post is not community heat


def test_disabled_community_drops_out_and_window_validation(client, alice):
    vid = venture(client, alice)
    cid = group(client, alice, vid).json()["id"]
    for n in (1, 2):
        paste(client, alice, vid, cid, "Webinars again", f"https://x.example/{n}", likes=3)
    assert heat(client, alice, vid).json()["topics"]
    client.patch(f"/ventures/{vid}/communities/{cid}", json={"enabled": False}, headers=alice)
    assert heat(client, alice, vid).json()["topics"] == []
    assert heat(client, alice, vid, days=3).status_code == 422
    assert heat(client, alice, vid, days=61).status_code == 422


# --- heat rules -----------------------------------------------------------------

def post(community, title, eng, days_ago, summary=None):
    return {"community": community, "title": title, "summary": summary, "url": f"https://x.example/{community}/{title}/{days_ago}", "engagement": eng, "published_at": NOW - days_ago * DAY}


def run(posts, own=(), niche=(), days=14):
    return build_heat(posts, list(own), set(niche), NOW, days)


def test_a_single_post_is_not_a_topic():
    assert run([post("A", "webinars", 100, 1)])["topics"] == []


def test_big_and_small_communities_are_compared_fairly():
    # r/big normally gets ~1000; the group normally gets ~10. A 30-engagement post in the group is hotter than 1200 in r/big.
    posts = [post("big", f"filler{i}", 1000, 2) for i in range(4)] + [post("big", "pricing talk", 1200, 2), post("small", "pricing question", 30, 2)]
    posts += [post("small", f"other{i}", 10, 3) for i in range(4)]
    d = run(posts)
    hot = {p["title"]: p["relative"] for p in d["hot_posts"]}
    assert hot["pricing question"] == 3.0 and "pricing talk" not in hot  # 1.2x its own median: not noteworthy
    assert [p["title"] for p in d["hot_posts"]][0] == "pricing question"


def test_trend_rising_cooling_new_and_unknown():
    posts = [
        post("A", "webinar launch", 50, 1), post("A", "webinar tips", 60, 2),  # recent webinar heat
        post("A", "webinar old", 5, 20), post("A", "webinar older", 5, 21),  # weak before: rising
        post("A", "pricing now", 5, 1), post("A", "pricing today", 5, 2),
        post("A", "pricing before", 80, 20), post("A", "pricing earlier", 90, 22),  # strong before: cooling
        post("A", "newsletter idea", 20, 1), post("A", "newsletter plan", 25, 3),  # absent before: new
    ]
    t = {x["term"]: x["trend"] for x in run(posts)["topics"]}
    assert t["webinar"] == "rising" and t["pricing"] == "cooling" and t["newsletter"] == "new"
    nobase = {x["term"]: x["trend"] for x in run([post("A", "webinar a", 5, 1), post("A", "webinar b", 5, 2)])["topics"]}
    assert nobase["webinar"] == "unknown"  # nothing older to compare with: don't claim "new"


def test_steady_when_heat_is_similar():
    posts = [post("A", "webinar a", 10, 1), post("A", "webinar b", 10, 2), post("A", "webinar c", 10, 16), post("A", "webinar d", 10, 17)]
    assert run(posts)["topics"][0]["trend"] == "steady"


def test_covered_gaps_and_ranking():
    posts = [post("A", "webinar a", 50, 1), post("B", "webinar b", 60, 2), post("A", "funnel x", 5, 1), post("B", "funnel y", 5, 2), post("A", "sourdough a", 90, 1), post("B", "sourdough b", 90, 2)]
    d = run(posts, own=["Our webinar playbook"], niche={"webinar", "funnel"})
    assert [t["term"] for t in d["topics"]][0] == "sourdough"  # hottest first, niche or not
    assert "funnel" in d["gaps"] and "webinar" not in d["gaps"] and "sourdough" not in d["gaps"]


def test_notes_and_empty():
    assert "No community posts" in run([])["note"]
    assert "only 2 posts" in run([post("A", "a", 1, 1), post("A", "b", 1, 2)])["note"]
    assert run([post("A", f"p{i}", 1, 1) for i in range(10)])["note"] is None


def test_old_posts_only_form_the_baseline():
    d = run([post("A", "webinar a", 5, 20), post("A", "webinar b", 5, 21)])
    assert d["posts"] == 0 and d["topics"] == [] and d["has_baseline"] is True


def test_cooling_topics_stay_visible_below_the_top_list():
    posts = [post("A", f"hot{i}x topic{i}x", 500, 1) for i in range(30)] + [post("A", f"hot{i}x topic{i}x", 500, 2) for i in range(30)]
    posts += [post("A", "paid ads one", 1, 1), post("A", "paid ads two", 1, 2), post("A", "paid ads old", 90, 20), post("A", "paid ads older", 90, 22)]
    d = run(posts)
    assert len(d["topics"]) > 12 and any(t["term"] == "paid" and t["trend"] == "cooling" for t in d["topics"])
