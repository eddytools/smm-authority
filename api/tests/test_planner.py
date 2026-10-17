from collections import Counter
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.framework import DEFAULT_MIX, PLATFORM_ALLOWED, STAGE_OF, PostType, Stage
from app.planner import Candidate, PlanningError, allocate, generate

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)  # a Monday


def brief(platforms=None, pillars=("Founder-led growth", "Case studies", "LinkedIn tactics")):
    return {
        "platforms": platforms if platforms is not None else [{"platform": "linkedin", "cadence_per_week": 4}, {"platform": "x", "cadence_per_week": 3}],
        "ideation": {"pillars": list(pillars)},
        "offer": {"lead_magnets": ["30-day content planner"], "cta_url": "https://acme.example/planner", "booking_url": "https://acme.example/book"},
    }


def month(b=None, **kw):
    return generate(b or brief(), START, 4, UTC, DEFAULT_MIX, **kw)


def test_allocate_is_exact_deterministic_and_proportional():
    w = {Stage.tofu: 50, Stage.mofu: 30, Stage.bofu: 20}
    assert allocate(10, w) == {Stage.tofu: 5, Stage.mofu: 3, Stage.bofu: 2}
    assert sum(allocate(7, w).values()) == 7 and allocate(7, w) == allocate(7, w)
    assert allocate(0, w) == {Stage.tofu: 0, Stage.mofu: 0, Stage.bofu: 0}
    assert allocate(3, {Stage.tofu: 1, Stage.mofu: 1, Stage.bofu: 1}) == {Stage.tofu: 1, Stage.mofu: 1, Stage.bofu: 1}


def test_cadence_is_respected_per_platform_per_week():
    slots = month()
    for week in range(4):
        per_platform = Counter(s.platform for s in slots if s.week == week)
        assert per_platform == {"linkedin": 4, "x": 3}
    assert len(slots) == 28


def test_slots_stay_inside_the_period_and_use_best_time_windows():
    slots = month()
    assert all(START <= s.local_date < date(2026, 11, 30) for s in slots)
    linkedin = [s for s in slots if s.platform == "linkedin" and s.week == 0]
    assert sorted(s.local_date.weekday() for s in linkedin) == [0, 1, 2, 3]  # Tue, Wed, Thu, Mon preferred first
    assert {s.scheduled_at.hour for s in linkedin} == {8} and {s.scheduled_at.minute for s in linkedin} == {30}


def test_month_plan_contains_all_stages_and_all_pillars_and_a_lead_magnet():
    slots = month()
    assert {s.stage for s in slots} == set(Stage)
    assert {s.pillar for s in slots} == {"Founder-led growth", "Case studies", "LinkedIn tactics"}
    assert any(s.post_type == PostType.lead_magnet for s in slots)
    assert all(STAGE_OF[s.post_type] == s.stage for s in slots)


def test_month_follows_growth_then_trust_then_sell_rhythm():
    slots = month()

    def share(week, stage):
        ws = [s for s in slots if s.week == week]
        return sum(s.stage == stage for s in ws) / len(ws)

    assert share(0, Stage.tofu) > share(3, Stage.tofu)
    assert share(3, Stage.bofu) > share(0, Stage.bofu)
    assert share(1, Stage.mofu) > share(0, Stage.mofu)


def test_within_a_week_growth_comes_before_selling():
    slots = month()
    order = {Stage.tofu: 0, Stage.mofu: 1, Stage.bofu: 2}
    for week in range(4):
        ranks = [order[s.stage] for s in slots if s.week == week]  # slots are chronological
        assert ranks == sorted(ranks)


def test_a_single_week_is_balanced_to_the_requested_mix():
    slots = generate(brief([{"platform": "linkedin", "cadence_per_week": 5}, {"platform": "x", "cadence_per_week": 5}]), START, 1, UTC, DEFAULT_MIX)
    assert Counter(s.stage for s in slots) == {Stage.tofu: 5, Stage.mofu: 3, Stage.bofu: 2}


def test_zero_percent_stage_is_respected_not_forced():
    slots = generate(brief(), START, 4, UTC, {"tofu": 60, "mofu": 40, "bofu": 0})
    assert not any(s.stage == Stage.bofu for s in slots)


def test_reddit_never_gets_promotional_or_video_posts():
    slots = generate(brief([{"platform": "reddit", "cadence_per_week": 7}]), START, 4, UTC, DEFAULT_MIX)
    assert slots and all(s.post_type in PLATFORM_ALLOWED["reddit"] for s in slots)
    banned = {PostType.lead_magnet, PostType.product_demo, PostType.conversion, PostType.short_video}
    assert not banned & {s.post_type for s in slots}


def test_blog_and_newsletter_never_get_short_video():
    slots = generate(brief([{"platform": "blog", "cadence_per_week": 5}, {"platform": "newsletter", "cadence_per_week": 3}]), START, 4, UTC, DEFAULT_MIX)
    assert PostType.short_video not in {s.post_type for s in slots}


def test_ctas_come_from_the_offer():
    slots = month()
    lm = next(s for s in slots if s.post_type == PostType.lead_magnet)
    assert "30-day content planner" in lm.cta and "acme.example/planner" in lm.cta
    conv = next(s for s in slots if s.post_type == PostType.conversion)
    assert conv.cta == "Link: https://acme.example/book"
    assert next(s for s in slots if s.post_type == PostType.educational).cta is None


def test_topics_default_to_framework_guidance_and_reactive_slots_are_flagged():
    slots = month()
    story = next(s for s in slots if s.post_type == PostType.story)
    assert "Story:" in story.topic and "lesson" in story.topic and story.topic.startswith("[")
    news = [s for s in slots if s.post_type == PostType.newsjacking]
    assert news and all(s.reactive for s in news)
    assert not any(s.reactive for s in slots if s.post_type != PostType.newsjacking)


def test_feed_items_become_topics_saved_first_newsjacking_first():
    cands = [Candidate(1, "Low score unsaved", 40, False), Candidate(2, "Saved item", 10, True), Candidate(3, "High score unsaved", 90, False)]
    slots = month(candidates=cands)
    used = {s.source_item_id: s for s in slots if s.source_item_id}
    assert set(used) == {1, 2, 3}
    assert all(used[i].post_type in (PostType.newsjacking, PostType.awareness, PostType.educational) for i in used)
    first_news = next(s for s in slots if s.post_type == PostType.newsjacking)
    assert first_news.source_item_id == 2  # saved beats higher-scoring unsaved
    assert used[3].topic == "High score unsaved"


def test_each_feed_item_is_used_at_most_once():
    slots = month(candidates=[Candidate(1, "Only one", 80, False)])
    assert [s.source_item_id for s in slots if s.source_item_id] == [1]


def test_skip_set_avoids_existing_platform_days():
    base = month()
    victim = next(s for s in base if s.platform == "linkedin")
    slots = month(skip={("linkedin", victim.local_date)})
    assert not any(s.platform == "linkedin" and s.local_date == victim.local_date for s in slots)
    assert len(slots) == len(base) - 1


def test_timezones_shift_utc_but_keep_local_time_and_handle_dst():
    ny = ZoneInfo("America/New_York")
    slots = generate(brief([{"platform": "linkedin", "cadence_per_week": 3}]), date(2026, 10, 26), 2, ny, DEFAULT_MIX)
    assert all(s.scheduled_at.astimezone(ny).hour == 8 and s.scheduled_at.astimezone(ny).minute == 30 for s in slots)
    offsets = {s.scheduled_at.hour for s in slots}
    assert offsets == {12, 13}  # 08:30 New York is 12:30 UTC in EDT, 13:30 in EST (DST ends Nov 1 2026)
    assert all(s.scheduled_at.tzinfo == timezone.utc for s in slots)


def test_high_cadence_spills_into_extra_slots_per_day():
    slots = generate(brief([{"platform": "x", "cadence_per_week": 14}]), START, 1, UTC, DEFAULT_MIX)
    assert len(slots) == 14
    per_day = Counter(s.local_date for s in slots)
    assert set(per_day.values()) == {2}
    assert len({s.scheduled_at for s in slots}) == 14  # no two posts at the exact same instant


def test_tiny_plans_do_not_crash():
    one = generate(brief([{"platform": "linkedin", "cadence_per_week": 1}]), START, 1, UTC, DEFAULT_MIX)
    assert len(one) == 1 and one[0].topic
    two = generate(brief([{"platform": "linkedin", "cadence_per_week": 2}]), START, 1, UTC, DEFAULT_MIX)
    assert len(two) == 2


def test_no_pillars_still_works():
    slots = month(brief(pillars=()))
    assert all(s.pillar is None for s in slots) and all(s.topic for s in slots)


def test_deterministic():
    a, b = month(candidates=[Candidate(1, "x", 50, False)]), month(candidates=[Candidate(1, "x", 50, False)])
    assert [(s.scheduled_at, s.platform, s.post_type, s.pillar, s.topic) for s in a] == [(s.scheduled_at, s.platform, s.post_type, s.pillar, s.topic) for s in b]


def test_requires_platforms():
    with pytest.raises(PlanningError):
        generate(brief([]), START, 4, UTC, DEFAULT_MIX)
