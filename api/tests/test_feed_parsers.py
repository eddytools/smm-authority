import json
from datetime import datetime, timezone

import pytest

from app.feed_parsers import ParseError, normalize_url, parse_feed, parse_reddit, url_hash
from app.jobs.scoring import brief_keywords, keywords, rule_score
from tests.conftest import RSS

NOW = datetime(2025, 10, 14, 12, 0, tzinfo=timezone.utc)


def test_rss_parses_cleans_and_skips_incomplete_items():
    items = parse_feed(RSS, NOW)
    assert [i.title for i in items] == ["Founder-led growth playbook for SaaS", "Ten pasta recipes"]
    first = items[0]
    assert first.summary == "How SaaS founders win inbound leads"  # html stripped
    assert first.author == "Ann"
    assert first.published_at == datetime(2025, 10, 13, 8, 0, tzinfo=timezone.utc)
    assert items[1].published_at == NOW  # missing date falls back to fetch time


def test_atom_parses():
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom post</title>
    <link rel="self" href="https://x.example/self"/><link rel="alternate" href="https://x.example/post"/>
    <updated>2025-10-12T10:00:00Z</updated><summary>Sum</summary><author><name>Bob</name></author></entry></feed>"""
    (item,) = parse_feed(atom, NOW)
    assert item.url == "https://x.example/post" and item.author == "Bob"
    assert item.published_at == datetime(2025, 10, 12, 10, 0, tzinfo=timezone.utc)


def test_future_dates_are_clamped_and_unsafe_links_dropped():
    xml = b"""<rss><channel>
    <item><title>Future</title><link>https://a.example/f</link><pubDate>Fri, 01 Jan 2100 00:00:00 GMT</pubDate></item>
    <item><title>Bad</title><link>javascript:alert(1)</link></item></channel></rss>"""
    items = parse_feed(xml, NOW)
    assert len(items) == 1 and items[0].published_at == NOW


@pytest.mark.parametrize(
    "body",
    [
        b"not xml at all",
        b"<rss><channel></channel></rss>",
        b'<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><rss><channel><item><title>&b;</title><link>https://a.example/x</link></item></channel></rss>',
    ],
)
def test_bad_or_hostile_feeds_raise_parse_error(body):
    with pytest.raises(ParseError):
        parse_feed(body, NOW)


def test_reddit_parser():
    def post(**kw):
        base = {"title": "T", "permalink": "/r/x/comments/1/t/", "score": 10, "num_comments": 5, "created_utc": 1760400000, "author": "u", "selftext": "body"}
        return {"data": {**base, **kw}}

    body = json.dumps({"data": {"children": [post(), post(stickied=True), post(over_18=True), post(title=""), post(title="Second", permalink="/r/x/comments/2/s/")]}}).encode()
    items = parse_reddit(body, NOW)
    assert [i.title for i in items] == ["T", "Second"]
    assert items[0].url == "https://www.reddit.com/r/x/comments/1/t/" and items[0].engagement == 15
    with pytest.raises(ParseError):
        parse_reddit(b"{}", NOW)


def test_url_normalisation_makes_duplicates_collide():
    a = "HTTPS://Blog.Example/growth/?utm_source=tw&id=3#section"
    b = "https://blog.example/growth?id=3"
    assert normalize_url(a) == normalize_url(b) and url_hash(a) == url_hash(b)
    assert url_hash("https://blog.example/growth?id=4") != url_hash(b)


# --- rule scoring -------------------------------------------------------------

def test_rule_score_ranks_relevance_then_freshness_then_engagement():
    kws = brief_keywords("Acme", "founder-led growth for SaaS", {"ideation": {"pillars": ["inbound leads"]}, "icp": {}})
    fresh = NOW
    old = datetime(2025, 9, 1, tzinfo=timezone.utc)
    relevant_fresh = rule_score("Founder-led growth drives inbound leads", None, fresh, 0, kws, NOW)
    irrelevant_fresh = rule_score("Ten pasta recipes", None, fresh, 0, kws, NOW)
    relevant_old = rule_score("Founder-led growth drives inbound leads", None, old, 0, kws, NOW)
    assert relevant_fresh > irrelevant_fresh and relevant_fresh > relevant_old
    assert rule_score("Ten pasta recipes", None, fresh, 800, kws, NOW) > irrelevant_fresh  # engagement helps
    assert 0 <= relevant_fresh <= 100


def test_rule_score_is_neutral_without_a_brief():
    assert rule_score("anything", None, NOW, 0, set(), NOW) == pytest.approx(rule_score("other thing", None, NOW, 0, set(), NOW))
    assert keywords("The founder and the SaaS growth") >= {"founder", "saas", "growth"}
