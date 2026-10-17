from datetime import datetime, timedelta, timezone

from app.anatomy import build_analysis, tags_for

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def post(title, eng, source="A", summary=None, days=3):
    return {"community": source, "title": title, "summary": summary, "url": f"https://x.example/{source}/{abs(hash(title + str(eng)))}", "engagement": eng, "published_at": NOW - timedelta(days=days)}


def pad(n=10, source="A", eng=10):
    return [post(f"plain note number {i} about work", eng, source, summary="x" * 400) for i in range(n)]


# --- tagging --------------------------------------------------------------------

def test_hook_tags():
    assert "question" in tags_for("Anyone tried webinars for lead gen?", None)
    assert "question" in tags_for("How do founders get inbound leads", None)
    assert "number" in tags_for("We got 3x more demos", None)
    assert "contrarian" in tags_for("Cold email is dead", None)
    assert "howto" in tags_for("Our playbook for webinars", None)
    assert "first_person" in tags_for("We ran 6 webinars", None) and "first_person" not in tags_for("Weekly notes", None)
    t = tags_for("Plain statement", "Plain statement with no features at all")
    assert not t & {"question", "number", "contrarian", "howto", "first_person", "list", "link"}


def test_format_tags():
    body = "Intro\n- one\n- two\n- three\n"
    assert "list" in tags_for("Tips", body)
    assert "list" not in tags_for("Tips", "- one\n- two\n")
    assert "list" in tags_for("Tips", "1. a\n2. b\n3. c")
    assert "link" in tags_for("Read this", "see https://example.com/x")
    assert "short" in tags_for("t", "x" * 100) and "medium" in tags_for("t", "x" * 500) and "long" in tags_for("t", "x" * 1000)
    assert "short" in tags_for("only a title", None)


def test_the_title_is_the_hook_even_when_the_body_starts_differently():
    assert "question" in tags_for("Is webinar lead gen worth it?", "I have been running these for a year.")
    assert "first_person" not in tags_for("Is webinar lead gen worth it?", "I have been running these for a year.")


# --- analysis -------------------------------------------------------------------

def test_not_enough_posts_gives_a_note_and_no_patterns():
    d = build_analysis(pad(5), 60)
    assert d["patterns"] == [] and "at least 12" in d["note"]


def test_question_posts_that_outperform_are_called_out_and_flat_ones_too():
    posts = pad(10, eng=10)
    posts += [post(f"Anyone tried approach {i}?", 80, summary="x" * 400) for i in range(4)]  # questions win
    posts += [post(f"Link roundup {i}", 2, summary="see https://example.com " + "x" * 400) for i in range(4)]  # links are flat
    d = build_analysis(posts, 60)
    by = {p["tag"]: p for p in d["patterns"]}
    assert by["question"]["verdict"] == "works" and by["question"]["lift"] >= 1.25 and by["question"]["high_share"] == 1.0
    assert by["link"]["verdict"] == "flat" and "links" in by["link"]["advice"].lower()
    assert d["patterns"][0]["verdict"] == "works"  # winners listed before duds
    assert all(p["posts"] >= 3 for p in d["patterns"])


def test_a_feature_on_too_few_posts_is_not_judged():
    posts = pad(12, eng=10) + [post("Anyone tried this?", 500, summary="x" * 400), post("Anyone using that?", 400, summary="x" * 400)]
    assert all(p["tag"] != "question" for p in build_analysis(posts, 60)["patterns"])  # 2 posts < MIN_GROUP


def test_engagement_is_judged_within_each_source():
    # 1000 is normal in "big", 10 is normal in "small": a question that does 1000 in big is not a winner.
    posts = pad(8, "big", 1000) + pad(8, "small", 10)
    posts += [post(f"Anyone tried {i}?", 1000, "big", "x" * 400) for i in range(3)]
    d = build_analysis(posts, 60)
    assert all(p["tag"] != "question" or p["verdict"] != "works" for p in d["patterns"])
    assert d["top"] == [] or all(t["relative"] >= 1.5 for t in d["top"])


def test_top_posts_list_their_tags_and_only_include_real_outperformers():
    posts = pad(12, eng=10) + [post("We got 3x more demos from webinars", 90, summary="x" * 400)]
    d = build_analysis(posts, 60)
    assert d["top"][0]["title"].startswith("We got 3x") and d["top"][0]["relative"] >= 1.5
    assert "Has a number in the first line" in d["top"][0]["tags"]
    assert d["high_performers"] == 1
    zero = build_analysis([post(f"t{i}", 0) for i in range(14)], 60)
    assert zero["top"] == [] and zero["patterns"] == []


def test_no_pattern_note_when_nothing_stands_out():
    d = build_analysis(pad(14), 60)
    assert d["patterns"] == [] and "No feature stands out" in d["note"]


# --- API ------------------------------------------------------------------------

def test_endpoint_uses_engagement_sources_only_and_respects_access(client, alice, bob, fetcher):
    vid = client.post("/ventures", json={"name": "Acme"}, headers=alice).json()["id"]
    cid = client.post(f"/ventures/{vid}/communities", json={"name": "Grp", "platform": "linkedin"}, headers=alice).json()["id"]
    iid = client.post(f"/ventures/{vid}/influencers", json={"name": "Ann", "platform": "x"}, headers=alice).json()["id"]
    for i in range(8):
        client.post(f"/ventures/{vid}/communities/{cid}/posts", json={"text": f"plain group post {i}", "url": f"https://g.example/{i}", "likes": 5}, headers=alice)
    for i in range(4):
        client.post(f"/ventures/{vid}/communities/{cid}/posts", json={"text": f"Anyone tried thing {i}?", "url": f"https://g.example/q{i}", "likes": 60}, headers=alice)
    client.post(f"/ventures/{vid}/influencers/{iid}/posts", json={"text": "one influencer post", "url": "https://i.example/1", "engagement": 9}, headers=alice)
    client.post(f"/ventures/{vid}/sources", json={"type": "rss", "target": "https://blog.example/feed.xml"}, headers=alice)
    d = client.get(f"/ventures/{vid}/top-posts", headers=alice).json()
    assert d["posts"] == 13  # group + influencer posts, no RSS
    assert d["patterns"] and d["patterns"][0]["tag"] == "question" and d["top"][0]["community"] == "Grp"
    assert client.get(f"/ventures/{vid}/top-posts", headers=bob).status_code == 404
    assert client.get(f"/ventures/{vid}/top-posts?days=3", headers=alice).status_code == 422
    client.patch(f"/ventures/{vid}/communities/{cid}", json={"enabled": False}, headers=alice)
    assert client.get(f"/ventures/{vid}/top-posts", headers=alice).json()["posts"] == 1
