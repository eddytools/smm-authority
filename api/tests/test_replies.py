from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
from sqlalchemy import func, select

from app.models import AIUsage, QuickReply
from app.replies import check_reply, is_question, parse_rules, promo_terms, rank_opportunities, reply_context
from tests.conftest import login, make_settings, register

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


# --- rules and checks (pure) -----------------------------------------------------------

@pytest.mark.parametrize(
    "rules,expected",
    [
        ("No self-promotion. No links. Be kind.", {"no_links": True, "no_promotion": True, "disclosure": False}),
        ("Please don't post links to your own site.", {"no_links": True, "no_promotion": False, "disclosure": False}),
        ("External links are not allowed.", {"no_links": True, "no_promotion": False, "disclosure": False}),
        ("Self promotion is banned here.", {"no_links": False, "no_promotion": True, "disclosure": False}),
        ("1. No advertising\n2. No soliciting", {"no_links": False, "no_promotion": True, "disclosure": False}),
        ("You must disclose any affiliation.", {"no_links": False, "no_promotion": False, "disclosure": True}),
        ("Be kind. Stay on topic.", {"no_links": False, "no_promotion": False, "disclosure": False}),
        (None, {"no_links": False, "no_promotion": False, "disclosure": False}),
    ],
)
def test_community_rules_become_flags(rules, expected):
    assert parse_rules(rules) == expected


def test_promo_terms_identify_the_authors_business():
    terms = promo_terms({"name": "Acme SaaS Growth", "website": "https://www.acme-growth.com/about"}, {"offer": {"offer": "90-day Authority Sprint", "lead_magnets": ["30-day planner", "ab"], "cta_url": "https://acme-growth.com/planner", "booking_url": None}})
    assert terms == ["Acme SaaS Growth", "90-day Authority Sprint", "30-day planner", "acme-growth.com"]  # www stripped, duplicates and tiny words dropped
    assert promo_terms({"name": "X"}, None) == []


GOOD = "The short answer is to pick one channel and stick with it for a month. Choose where your buyers already read, post twice a week, and track which posts get replies. Most teams spread thin and learn nothing."


def codes(platform, text, rules=None, terms=None):
    return " | ".join(check_reply(platform, text, parse_rules(rules), terms))


def test_a_clean_helpful_reply_has_no_warnings():
    assert check_reply("reddit", GOOD, {}, ["Acme"]) == []
    assert check_reply("reddit", "", {}, []) == [] and check_reply("reddit", None, {}, []) == []


def test_links_are_flagged_harder_when_the_rules_forbid_them():
    text = GOOD + " See https://example.com/guide"
    assert "Contains a link" in codes("reddit", text)
    assert "rules say no links" in codes("reddit", text, "No links allowed")
    assert "www.example.com" and "link" in codes("reddit", GOOD + " www.example.com/x").lower()


def test_mentioning_your_own_business_needs_disclosure_or_removal():
    text = GOOD + " At Acme SaaS Growth we see this daily."
    msg = codes("reddit", text, terms=["Acme SaaS Growth"])
    assert "own business or offer" in msg and "affiliated" in msg
    assert "bans self-promotion" in codes("reddit", text, "No self-promotion", ["Acme SaaS Growth"])
    assert "own business" not in codes("reddit", GOOD + " Acmeville is a town.", terms=["Acme"])  # whole words only
    assert "own business" in codes("reddit", GOOD + " I run acme-growth.com", terms=["acme-growth.com"])


def test_promotional_phrases_are_caught_even_without_a_name():
    for phrase in ("DM me and I'll send it over", "check out my newsletter", "Book a call with us", "link in bio", "my agency does this", "free trial available"):
        assert "promotion" in codes("reddit", GOOD + " " + phrase), phrase


def test_personal_claims_are_flagged_for_the_author_to_verify():
    for phrase in ("In my experience this works.", "When I ran a startup we did this.", "I've helped 40 clients.", "Our clients love it.", "I grew a channel to 10k."):
        assert "personal claim" in codes("reddit", GOOD + " " + phrase), phrase
    assert "personal claim" not in codes("reddit", GOOD)


def test_disclosure_rule_reminder_only_when_nothing_else_applies():
    assert "mention disclosure" in codes("reddit", GOOD, "Please disclose affiliations")
    assert "mention disclosure" not in codes("reddit", GOOD + " check out my newsletter", "Please disclose affiliations")


def test_placeholders_length_and_short_replies():
    assert "placeholder" in codes("reddit", GOOD + " It took [number] weeks.")
    assert "Very short" in codes("reddit", "Just use one channel.")
    assert "Very short" not in codes("linkedin", "Just use one channel and measure it.")  # short is normal on LinkedIn
    assert "over the 1250" in codes("linkedin", "a" * 1251)
    assert "over X's 280 limit" in codes("x", "a" * 281) and codes("x", "a" * 280) == ""


# --- opportunities (pure) ---------------------------------------------------------------

def test_question_detection():
    for q in ("How do you get inbound leads?", "Any tips for LinkedIn", "Should I niche down", "Is cold email dead?", "ELI5: dark funnel", "Looking for a CRM"):
        assert is_question(q), q
    for n in ("Ten pasta recipes", "We shipped v2 today", "LinkedIn changes its feed"):
        assert not is_question(n), n


def item(i, title, hours=2, eng=50, score=30):
    return {"id": i, "title": title, "summary": None, "url": f"https://x.example/{i}", "source_label": "r/x", "source_type": "reddit", "engagement": eng, "published_at": NOW - timedelta(hours=hours), "rule_score": score}


def test_opportunities_prefer_fresh_lively_on_topic_questions_and_skip_the_rest():
    items = [item(1, "How do I get leads?", hours=1, eng=200), item(2, "How do I get leads?", hours=40, eng=200), item(3, "How do I get leads?", hours=1, eng=2),
             item(4, "We shipped v2", hours=1, eng=900), item(5, "Anyone using founder-led growth for SaaS?", hours=1, eng=2, score=5)]
    ranked = rank_opportunities(items, NOW, {"founder", "growth", "saas"})
    assert [r["id"] for r in ranked][:3] == [1, 5, 3] or [r["id"] for r in ranked][0] == 1
    assert 4 not in [r["id"] for r in ranked]  # not a question
    scores = {r["id"]: r["score"] for r in ranked}
    assert scores[1] > scores[2] and scores[1] > scores[3]  # fresher and livelier beats stale or quiet
    assert scores[5] > scores[3] - 20 and ranked[0]["age_hours"] == 1.0
    assert len(rank_opportunities([item(i, "How?", hours=1) for i in range(30)], NOW, limit=5)) == 5


def test_context_gives_the_model_only_provided_facts_and_trims_untrusted_text():
    brief = {"ideation": {"proof_assets": ["Grew a client to 40 leads/month"], "opinions": ["Daily posting is overrated"], "niche_statement": "Founder-led growth"}, "voice": {"tone": "Direct", "writing_samples": ["s" * 2000, "b", "c"]}}
    ctx = reply_context({"name": "Acme", "niche": None}, brief, platform="reddit", community="startups", rules="r" * 5000, question="q" * 9000, instructions="i" * 900, existing=None)
    assert ctx["author"]["author_facts"] == ["Grew a client to 40 leads/month"] and ctx["author"]["niche"] == "Founder-led growth"
    assert len(ctx["thread"]) == 6000 and len(ctx["where"]["community_rules"]) == 3000 and len(ctx["extra_instructions"]) == 500
    assert len(ctx["voice"]["writing_samples"]) == 2 and len(ctx["voice"]["writing_samples"][0]) == 800
    assert "no links" in ctx["where"]["format"] and ctx["existing_reply"] is None


# --- API ---------------------------------------------------------------------------------

THREAD = "How do you get inbound leads as a solo SaaS founder? Cold email stopped working for us and I'm out of ideas."
BRIEF = {"ideation": {"proof_assets": ["Grew a client to 40 inbound leads a month"], "pillars": ["Founder-led growth"]}, "offer": {"offer": "Authority Sprint", "cta_url": "https://acme.example/book"}, "platforms": [{"platform": "linkedin", "cadence_per_week": 2}]}


def venture(client, headers, name="Acme", brief=BRIEF):
    vid = client.post("/ventures", json={"name": name, "website_url": "https://acme.example"}, headers=headers).json()["id"]
    if brief:
        client.put(f"/ventures/{vid}/brief", json=brief, headers=headers)
    return vid


def draft(client, headers, vid, **body):
    return client.post(f"/ventures/{vid}/replies/draft", json={"question_text": THREAD, **body}, headers=headers)


def rss(titles, hours_ago=1):
    when = format_datetime(datetime.now(timezone.utc) - timedelta(hours=hours_ago))
    items = "".join(f"<item><title>{t}</title><link>https://reddit.example/r/startups/comments/{i}/x/</link><description>body {i}</description><pubDate>{when}</pubDate></item>" for i, t in enumerate(titles))
    return f"<rss><channel>{items}</channel></rss>".encode()


def test_draft_saves_a_reply_with_context_and_posts_nothing(client, alice, fake_ai):
    vid = venture(client, alice)
    r = draft(client, alice, vid, community="r/startups", source_url="https://reddit.example/r/startups/comments/abc/x/", community_rules="No links.")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "open" and body["community"] == "startups" and body["platform"] == "reddit" and body["reply_draft"] and body["post_idea"] and body["warnings"] == []
    ctx = fake_ai.reply_calls[0]
    assert ctx["thread"] == THREAD and ctx["where"]["community"] == "startups" and ctx["where"]["community_rules"] == "No links."
    assert ctx["author"]["author_facts"] == ["Grew a client to 40 inbound leads a month"] and ctx["author"]["business"] == "Acme"
    assert client.get(f"/ventures/{vid}/replies", headers=alice).json()[0]["id"] == body["id"]
    with client.app.state.session_factory() as db:
        usage = [u for u in db.scalars(select(AIUsage)).all() if u.feature == "reply_draft"]
    assert len(usage) == 1 and usage[0].input_tokens == 250


def test_promotional_replies_carry_warnings_computed_from_the_venture_and_the_rules(client, alice, fake_ai):
    vid = venture(client, alice)
    fake_ai.reply_text = "Honestly, at Acme we helped dozens of founders. Book a call at https://acme.example/book and I'll walk you through it. " * 2
    body = draft(client, alice, vid, community_rules="No self-promotion. No links.").json()
    joined = " | ".join(body["warnings"])
    assert "rules say no links" in joined and "bans self-promotion" in joined and "personal claim" in joined
    # editing the reply updates the warnings immediately
    fixed = client.patch(f"/ventures/{vid}/replies/{body['id']}", json={"reply_draft": "Start with one channel and measure it for a month before adding another. Track which posts get replies, and double down there."}, headers=alice).json()
    assert fixed["warnings"] == [] or all("link" not in w for w in fixed["warnings"])


def test_one_draft_per_thread_even_if_the_url_is_written_differently(client, alice):
    vid = venture(client, alice)
    first = draft(client, alice, vid, source_url="https://reddit.example/r/startups/comments/abc/x/")
    assert first.status_code == 201
    again = draft(client, alice, vid, source_url="HTTPS://Reddit.example/r/startups/comments/abc/x?utm_source=share#top")
    assert again.status_code == 409 and f"#{first.json()['id']}" in again.json()["detail"]
    other = venture(client, alice, name="Other")
    assert draft(client, alice, other, source_url="https://reddit.example/r/startups/comments/abc/x/").status_code == 201  # a different venture may
    assert draft(client, alice, vid).status_code == 201 and draft(client, alice, vid).status_code == 201  # pasted text without a URL can't be matched


def test_replying_to_a_feed_item_uses_its_title_url_and_subreddit(client, alice, fetcher):
    fetcher.responses["https://www.reddit.example.com/feed"] = rss(["How do I get inbound leads?"])
    vid = venture(client, alice)
    client.post(f"/ventures/{vid}/sources", json={"type": "rss", "target": "https://www.reddit.example.com/feed"}, headers=alice)
    client.post(f"/ventures/{vid}/feed/refresh", headers=alice)
    item = client.get(f"/ventures/{vid}/feed", headers=alice).json()[0]
    r = client.post(f"/ventures/{vid}/replies/draft", json={"feed_item_id": item["id"]}, headers=alice)
    assert r.status_code == 201
    assert "How do I get inbound leads?" in r.json()["question_text"] and r.json()["source_url"] == item["url"] and r.json()["feed_item_id"] == item["id"]
    assert client.post(f"/ventures/{vid}/replies/draft", json={"feed_item_id": item["id"]}, headers=alice).status_code == 409  # same thread
    other = venture(client, alice, name="Other")
    assert client.post(f"/ventures/{other}/replies/draft", json={"feed_item_id": item["id"]}, headers=alice).status_code == 404  # not that venture's item


def test_validation(client, alice):
    vid = venture(client, alice)
    post = lambda body: client.post(f"/ventures/{vid}/replies/draft", json=body, headers=alice).status_code
    assert post({}) == 422 and post({"question_text": "short"}) == 422
    assert post({"question_text": THREAD, "platform": "tiktok"}) == 422
    assert post({"question_text": THREAD, "source_url": "javascript:alert(1)"}) == 422
    assert post({"question_text": THREAD, "community_rules": "x" * 3001}) == 422
    assert post({"question_text": THREAD, "instructions": "x" * 501}) == 422
    assert post({"question_text": "q" * 6001}) == 422
    assert post({"question_text": THREAD, "platform": "x"}) == 201 and post({"question_text": THREAD, "platform": "linkedin"}) == 201


def test_503_without_ai_and_429_over_the_daily_limit(make_client, fetcher):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(make_settings(), ai=None, fetcher=fetcher)) as c:
        register(c, "a@example.com")
        h = login(c, "a@example.com")
        assert draft(c, h, venture(c, h)).status_code == 503
    c = make_client(ai_daily_limit_per_user=1)
    register(c, "b@example.com")
    h = login(c, "b@example.com")
    vid = venture(c, h)
    assert draft(c, h, vid).status_code == 201 and draft(c, h, vid).status_code == 429


def test_replies_are_private_to_the_owner(client, alice, bob):
    vid = venture(client, alice)
    rid = draft(client, alice, vid).json()["id"]
    for call in (
        lambda h: client.get(f"/ventures/{vid}/replies", headers=h),
        lambda h: client.get(f"/ventures/{vid}/replies/{rid}", headers=h),
        lambda h: client.get(f"/ventures/{vid}/replies/opportunities", headers=h),
        lambda h: draft(client, h, vid),
        lambda h: client.patch(f"/ventures/{vid}/replies/{rid}", json={"status": "posted"}, headers=h),
        lambda h: client.post(f"/ventures/{vid}/replies/{rid}/redraft", json={}, headers=h),
        lambda h: client.delete(f"/ventures/{vid}/replies/{rid}", headers=h),
    ):
        assert call(bob).status_code == 404
    assert client.get(f"/ventures/{vid}/replies").status_code == 401
    other = venture(client, alice, name="Other")
    assert client.get(f"/ventures/{other}/replies/{rid}", headers=alice).status_code == 404  # reply belongs to a different venture


def test_edit_status_filter_and_delete(client, alice):
    vid = venture(client, alice)
    rid = draft(client, alice, vid).json()["id"]
    patch = lambda **b: client.patch(f"/ventures/{vid}/replies/{rid}", json=b, headers=alice)
    assert patch(reply_draft=None).status_code == 422 and patch(status="sent").status_code == 422 and patch(reply_draft="   ").status_code == 422
    assert patch(reply_draft="My own wording, which is better.").json()["reply_draft"] == "My own wording, which is better."
    assert patch(status="posted").json()["status"] == "posted"
    assert client.get(f"/ventures/{vid}/replies", headers=alice).json() == []
    assert [r["id"] for r in client.get(f"/ventures/{vid}/replies?status=posted", headers=alice).json()] == [rid]
    assert client.delete(f"/ventures/{vid}/replies/{rid}", headers=alice).status_code == 204
    assert client.get(f"/ventures/{vid}/replies/{rid}", headers=alice).status_code == 404


def test_redraft_replaces_the_reply_uses_the_current_text_and_is_budgeted(client, alice, fake_ai):
    vid = venture(client, alice)
    rid = draft(client, alice, vid).json()["id"]
    client.patch(f"/ventures/{vid}/replies/{rid}", json={"reply_draft": "My hand-edited answer"}, headers=alice)
    fake_ai.reply_text = "A fresh answer that is long enough to count as a genuinely useful reply, with a reason and an example included for good measure."
    r = client.post(f"/ventures/{vid}/replies/{rid}/redraft", json={"instructions": "shorter"}, headers=alice).json()
    assert r["reply_draft"].startswith("A fresh answer")
    ctx = fake_ai.reply_calls[-1]
    assert ctx["existing_reply"] == "My hand-edited answer" and ctx["extra_instructions"] == "shorter"
    client.patch(f"/ventures/{vid}/replies/{rid}", json={"status": "posted"}, headers=alice)
    assert client.post(f"/ventures/{vid}/replies/{rid}/redraft", json={}, headers=alice).status_code == 400  # already posted


def test_post_idea_becomes_a_locked_idea_in_the_plan_once(client, alice):
    vid = venture(client, alice)
    rid = draft(client, alice, vid).json()["id"]
    when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    to_plan = lambda **b: client.post(f"/ventures/{vid}/replies/{rid}/to-plan", json={"scheduled_at": when, "platform": "linkedin", **b}, headers=alice)
    assert to_plan(platform="reddit", post_type="lead_magnet").status_code == 400  # doesn't fit Reddit
    assert client.post(f"/ventures/{vid}/replies/{rid}/to-plan", json={"scheduled_at": "2030-01-01T10:00:00", "platform": "linkedin"}, headers=alice).status_code == 422  # naive time
    r = to_plan()
    assert r.status_code == 201
    slot = next(s for s in client.get(f"/ventures/{vid}/plan", headers=alice).json() if s["id"] == r.json()["slot_id"])
    assert slot["status"] == "idea" and slot["locked"] is True and slot["platform"] == "linkedin" and slot["stage"] == "tofu"
    assert slot["topic"] == "Why one channel beats three" and "Most teams spread thin" in slot["draft"]
    assert client.get(f"/ventures/{vid}/replies/{rid}", headers=alice).json()["plan_slot_id"] == slot["id"]
    assert to_plan().status_code == 409  # not twice
    client.patch(f"/ventures/{vid}/replies/{rid}", json={"post_idea": None}, headers=alice)
    other = draft(client, alice, vid).json()["id"]
    client.patch(f"/ventures/{vid}/replies/{other}", json={"post_idea": None}, headers=alice)
    assert client.post(f"/ventures/{vid}/replies/{other}/to-plan", json={"scheduled_at": when, "platform": "linkedin"}, headers=alice).status_code == 400  # nothing to plan


def test_opportunities_rank_questions_and_drop_the_ones_you_already_handled(client, alice, fetcher):
    fetcher.responses["https://reddit.example.com/feed"] = rss(["How do I get inbound leads as a founder?", "Ten pasta recipes", "Any tips for LinkedIn outreach?", "We shipped v2"])
    vid = venture(client, alice)
    client.post(f"/ventures/{vid}/sources", json={"type": "rss", "target": "https://reddit.example.com/feed"}, headers=alice)
    client.post(f"/ventures/{vid}/feed/refresh", headers=alice)
    opps = client.get(f"/ventures/{vid}/replies/opportunities", headers=alice).json()
    assert {o["title"] for o in opps} == {"How do I get inbound leads as a founder?", "Any tips for LinkedIn outreach?"}
    assert opps == sorted(opps, key=lambda o: -o["score"]) and all(o["age_hours"] >= 0 for o in opps)
    client.post(f"/ventures/{vid}/replies/draft", json={"feed_item_id": opps[0]["id"]}, headers=alice)
    assert [o["id"] for o in client.get(f"/ventures/{vid}/replies/opportunities", headers=alice).json()] == [opps[1]["id"]]
    client.patch(f"/ventures/{vid}/feed/{opps[1]['id']}", json={"status": "dismissed"}, headers=alice)
    assert client.get(f"/ventures/{vid}/replies/opportunities", headers=alice).json() == []


def test_deleting_a_venture_removes_its_replies(client, alice):
    vid = venture(client, alice)
    draft(client, alice, vid)
    assert client.delete(f"/ventures/{vid}", headers=alice).status_code == 204
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(QuickReply)) == 0
