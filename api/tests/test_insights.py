from datetime import datetime, timedelta, timezone

from app.insights import build_report

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
SINCE = NOW - timedelta(days=90)


def m(imp, reactions=0, comments=0, shares=0, saves=0, clicks=0, follows=0, leads=0):
    return {"impressions": imp, "reactions": reactions, "comments": comments, "shares": shares, "saves": saves, "clicks": clicks, "follows": follows, "leads": leads}


_id = iter(range(1, 10_000))


def row(post_type="story", stage="mofu", platform="linkedin", pillar="Case studies", metrics=None, status="analysed", days_ago=5, topic="t"):
    return {"slot_id": next(_id), "scheduled_at": NOW - timedelta(days=days_ago), "platform": platform, "pillar": pillar, "post_type": post_type, "stage": stage, "topic": topic, "status": status, "metrics": metrics}


def report(rows):
    return build_report(rows, NOW, SINCE, 90)


def test_empty_data_does_not_crash():
    r = report([])
    assert r["totals"]["published"] == 0 and r["totals"]["measured"] == 0 and r["totals"]["engagement_rate"] is None
    assert r["worked"] == [] and r["didnt"] == [] and r["top"] == [] and r["adherence"]["rate"] is None
    assert "only 0 measured posts" in r["note"]


def test_totals_and_engagement_rate_are_weighted_by_impressions():
    r = report([row(metrics=m(1000, 40, 10, 5, 5)), row(metrics=m(100, 1))])
    t = r["totals"]
    assert t["impressions"] == 1100 and t["engagements"] == 61 and t["engagement_rate"] == round(61 / 1100, 4)  # not the mean of the two rates
    assert t["measured"] == 2 and t["published"] == 2


def test_worked_and_didnt_need_enough_posts_and_enough_difference():
    rows = (
        [row("story", "mofu", metrics=m(1000, 100)) for _ in range(3)]  # 10%
        + [row("product_demo", "bofu", metrics=m(1000, 10)) for _ in range(3)]  # 1%
        + [row("educational", "tofu", metrics=m(1000, 55)) for _ in range(3)]  # 5.5%
        + [row("spectacle", "tofu", metrics=m(10, 5))]  # a single post (50% on tiny reach): never a conclusion
    )
    r = report(rows)
    worked = [w for w in r["worked"] if w["dimension"] == "post_type"]
    didnt = [d for d in r["didnt"] if d["dimension"] == "post_type"]
    assert [w["key"] for w in worked] == ["story"] and "Story posts earn" in worked[0]["message"] and worked[0]["posts"] == 3
    assert [d["key"] for d in didnt] == ["product_demo"] and "underperforming" in didnt[0]["message"]
    assert "spectacle" not in {x["key"] for x in r["worked"] + r["didnt"]}  # 1 post only
    assert any("Plan more Story posts" in s for s in r["recommendations"])
    assert any("Product demo" in s for s in r["recommendations"])


def test_no_conclusions_when_there_is_nothing_to_compare():
    r = report([row(metrics=m(1000, 50)) for _ in range(4)])  # one group in every dimension
    assert r["worked"] == [] and r["didnt"] == []


def test_small_samples_carry_a_warning_and_large_ones_do_not():
    assert "hints, not conclusions" in report([row(metrics=m(100, 5)) for _ in range(9)])["note"]
    assert report([row(metrics=m(100, 5)) for _ in range(10)])["note"] is None


def test_unmeasured_published_posts_are_listed_as_waiting():
    r = report([row(metrics=m(100, 5)), row(status="published", metrics=None, topic="needs results")])
    assert [w["topic"] for w in r["waiting"]] == ["needs results"]
    assert r["totals"]["published"] == 2 and r["totals"]["measured"] == 1


def test_zero_impression_posts_dont_divide_by_zero_or_rank():
    r = report([row(metrics=m(0, 5)), row(metrics=m(0))])
    assert r["totals"]["engagement_rate"] is None and r["top"] == [] and r["worked"] == []


def test_top_and_bottom_posts_by_engagement_rate():
    rows = [row(topic=f"p{i}", metrics=m(1000, i * 10)) for i in range(1, 7)]
    r = report(rows)
    assert [p["topic"] for p in r["top"]] == ["p6", "p5", "p4"]
    assert [p["topic"] for p in r["bottom"]] == ["p1", "p2", "p3"]
    assert report(rows[:3])["bottom"] == []  # too few posts to call anything "worst"


def test_leads_insight_names_the_stage_that_brought_them():
    rows = [row("conversion", "bofu", metrics=m(500, 10, leads=4)), row("conversion", "bofu", metrics=m(500, 10, leads=2)), row("story", "mofu", metrics=m(500, 10, leads=1))]
    lead = next(w for w in report(rows)["worked"] if w["dimension"] == "leads")
    assert "Selling (BOFU)" in lead["message"] and "6 of your 7 leads" in lead["message"] and "86%" in lead["message"]
    assert not [w for w in report([row(metrics=m(500, 10, leads=2))])["worked"] if w["dimension"] == "leads"]  # fewer than 3 leads: no claim


def test_adherence_counts_due_posts_not_future_or_skipped_ones():
    rows = [
        row(status="published", metrics=None),
        row(status="analysed", metrics=m(100, 5)),
        row(status="idea"),  # due but never posted
        row(status="skipped"),  # excluded from the denominator
        row(status="archived"),  # ignored
        row(status="scheduled", days_ago=-3),  # in the future
    ]
    a = report(rows)["adherence"]
    assert a == {"due": 3, "published": 2, "skipped": 1, "rate": 0.667}


def test_funnel_mix_planned_vs_published():
    rows = [row("educational", "tofu", status="published"), row("educational", "tofu", status="idea"), row("story", "mofu", status="idea"), row("conversion", "bofu", status="skipped")]
    mix = report(rows)["mix"]
    assert mix["tofu"] == {"planned": 2, "published": 1} and mix["mofu"] == {"planned": 1, "published": 0} and mix["bofu"] == {"planned": 0, "published": 0}


def test_posts_without_a_pillar_are_grouped():
    r = report([row(pillar=None, metrics=m(100, 5)), row(pillar="A", metrics=m(100, 5))])
    assert {b["key"] for b in r["breakdowns"]["pillar"]} == {"(no pillar)", "A"}


def test_demo_seed_builds_a_complete_venture_and_a_readable_story(tmp_path):
    """The demo data has to be coherent, or the first screens a new user sees are misleading."""
    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker

    from app.db import Base, make_engine
    from app.demo import DEMO_EMAIL, seed
    from app.models import BriefVersion, FeedItem, PlanSlot, PostMetric, User

    engine = make_engine(f"sqlite:///{tmp_path}/demo.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    assert "created" in seed(factory)
    assert "already exists" in seed(factory)  # idempotent
    assert "created" in seed(factory, reset=True)  # reset rebuilds instead of duplicating

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.email == DEMO_EMAIL)) == 1
        assert db.scalar(select(func.count()).select_from(BriefVersion)) == 1
        assert db.scalar(select(func.count()).select_from(FeedItem)) == 10
        slots = db.scalars(select(PlanSlot)).unique().all()
        assert len(slots) > 40 and db.scalar(select(func.count()).select_from(PostMetric)) >= 15
        rows = [
            {"slot_id": s.id, "scheduled_at": s.scheduled_at, "platform": s.platform, "pillar": s.pillar, "post_type": s.post_type.value, "stage": s.stage.value, "topic": s.topic,
             "status": s.status.value, "metrics": {f: getattr(s.metric, f) for f in ("impressions", "reactions", "comments", "shares", "saves", "clicks", "follows", "leads")} if s.metric else None}
            for s in slots
        ]
    r = build_report(rows, datetime.now(timezone.utc), datetime.now(timezone.utc) - timedelta(days=90), 90)
    assert r["totals"]["measured"] >= 15 and r["worked"] and r["didnt"]
    assert any(w["key"] == "story" for w in r["worked"] if w["dimension"] == "post_type") or any(w["key"] == "short_video" for w in r["worked"] if w["dimension"] == "post_type")
    # selling-stage posts are the built-in laggard (individual types may have too few posts to be judged, which is correct)
    assert any(d["key"] == "bofu" for d in r["didnt"] if d["dimension"] == "stage") or any(d["key"] in ("product_demo", "conversion") for d in r["didnt"])
