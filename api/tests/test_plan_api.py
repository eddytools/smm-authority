from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import PlanSlot
from tests.conftest import fresh_rss, login, make_settings, register

BRIEF = {
    "ideation": {"niche_statement": "Founder-led growth for SaaS", "pillars": ["inbound leads", "case studies", "linkedin"]},
    "offer": {"lead_magnets": ["Planner"], "booking_url": "https://acme.example/book"},
    "platforms": [{"platform": "linkedin", "cadence_per_week": 4, "is_primary": True}, {"platform": "x", "cadence_per_week": 3}],
}


def next_monday():
    d = date.today() + timedelta(days=1)
    return d + timedelta(days=(7 - d.weekday()) % 7)


def venture(client, headers, brief=BRIEF, name="Acme"):
    vid = client.post("/ventures", json={"name": name}, headers=headers).json()["id"]
    if brief is not None:
        assert client.put(f"/ventures/{vid}/brief", json=brief, headers=headers).status_code == 200
    return vid


def generate(client, headers, vid, **over):
    body = {"start_date": next_monday().isoformat(), "period": "month", "timezone": "UTC", **over}
    return client.post(f"/ventures/{vid}/plan/generate", json=body, headers=headers)


def slots(client, headers, vid, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/ventures/{vid}/plan?{q}", headers=headers).json()


def test_framework_endpoint_lists_stages_types_and_pipeline(client, alice):
    fw = client.get("/planner/framework", headers=alice).json()
    assert [s["key"] for s in fw["stages"]] == ["tofu", "mofu", "bofu"]
    assert sum(len(s["post_types"]) for s in fw["stages"]) == 10
    reddit_types = {t["key"] for s in fw["stages"] for t in s["post_types"] if "reddit" in t["platforms"]}
    assert "lead_magnet" not in reddit_types and "story" in reddit_types
    assert fw["transitions"]["approved"] == ["archived", "in_review", "scheduled", "skipped"]
    assert client.get("/planner/framework").status_code == 401


def test_generate_a_month_plan(client, alice):
    vid = venture(client, alice)
    out = generate(client, alice, vid).json()
    assert out["created"] == 28 and out["removed"] == 0 and out["kept"] == 0
    assert all(out["by_stage"][s] > 0 for s in ("tofu", "mofu", "bofu"))
    items = slots(client, alice, vid)
    assert len(items) == 28 and all(i["status"] == "idea" and i["locked"] is False for i in items)
    assert [i["scheduled_at"] for i in items] == sorted(i["scheduled_at"] for i in items)
    assert all(i["scheduled_at"].endswith("Z") for i in items)  # always an explicit UTC instant, never a naive local time
    assert {i["pillar"] for i in items} == {"inbound leads", "case studies", "linkedin"}


def test_weekly_plan_is_seven_posts(client, alice):
    vid = venture(client, alice)
    assert generate(client, alice, vid, period="week").json()["created"] == 7


def test_generate_needs_a_brief_with_platforms(client, alice):
    no_brief = venture(client, alice, brief=None, name="A")
    assert generate(client, alice, no_brief).status_code == 400
    no_platforms = venture(client, alice, brief={"platforms": []}, name="B")
    r = generate(client, alice, no_platforms)
    assert r.status_code == 400 and "platform" in r.json()["detail"]


def test_generate_validation(client, alice):
    vid = venture(client, alice)
    assert generate(client, alice, vid, mix={"tofu": 50, "mofu": 30, "bofu": 30}).status_code == 422
    assert generate(client, alice, vid, timezone="Mars/Olympus").status_code == 422
    assert generate(client, alice, vid, period="year").status_code == 422
    assert generate(client, alice, vid, start_date=(date.today() + timedelta(days=900)).isoformat()).status_code == 422


def test_custom_mix_is_applied(client, alice):
    vid = venture(client, alice)
    out = generate(client, alice, vid, period="week", mix={"tofu": 0, "mofu": 50, "bofu": 50}).json()
    assert out["by_stage"]["tofu"] == 0 and out["by_stage"]["mofu"] + out["by_stage"]["bofu"] == 7


def test_timezone_changes_utc_times(client, alice):
    vid = venture(client, alice)
    generate(client, alice, vid, period="week", timezone="Asia/Kolkata")
    first_linkedin = next(i for i in slots(client, alice, vid) if i["platform"] == "linkedin")
    assert first_linkedin["scheduled_at"][11:16] == "03:00"  # 08:30 IST (UTC+5:30)


def test_regenerating_requires_confirmation_then_keeps_edited_and_locked_slots(client, alice):
    vid = venture(client, alice)
    generate(client, alice, vid, period="week")
    assert generate(client, alice, vid, period="week").status_code == 409

    items = slots(client, alice, vid)
    edited, locked, plain = items[0], items[1], items[2]
    client.patch(f"/ventures/{vid}/plan/slots/{edited['id']}", json={"draft": "My own text", "status": "drafted"}, headers=alice)
    client.patch(f"/ventures/{vid}/plan/slots/{locked['id']}", json={"locked": True}, headers=alice)

    out = generate(client, alice, vid, period="week", replace=True).json()
    assert out["kept"] == 2 and out["removed"] == 5
    after = {i["id"]: i for i in slots(client, alice, vid)}
    assert edited["id"] in after and locked["id"] in after and plain["id"] not in after
    assert after[edited["id"]]["draft"] == "My own text"
    # no duplicate platform+day created next to a kept slot
    seen = [(i["platform"], i["scheduled_at"][:10]) for i in after.values()]
    assert len(seen) == len(set(seen)) and len(after) == 7


def test_feed_items_become_slot_topics_without_reuse(client, alice, fetcher):
    fetcher.responses["https://blog.example/feed.xml"] = fresh_rss()
    vid = venture(client, alice)
    client.post(f"/ventures/{vid}/sources", json={"type": "rss", "target": "https://blog.example/feed.xml"}, headers=alice)
    client.post(f"/ventures/{vid}/feed/refresh", headers=alice)
    feed = client.get(f"/ventures/{vid}/feed", headers=alice).json()
    saved = next(i for i in feed if "Founder-led" in i["title"])
    client.patch(f"/ventures/{vid}/feed/{saved['id']}", json={"status": "saved"}, headers=alice)

    generate(client, alice, vid, period="week")
    linked = [s for s in slots(client, alice, vid) if s["source_item_id"]]
    assert {s["source_item_id"] for s in linked} == {i["id"] for i in feed}
    assert next(s for s in linked if s["source_item_id"] == saved["id"])["topic"] == saved["title"]
    # a second plan doesn't reuse items already planned
    generate(client, alice, vid, start_date=(next_monday() + timedelta(days=7)).isoformat(), period="week")
    ids = [s["source_item_id"] for s in slots(client, alice, vid) if s["source_item_id"]]
    assert len(ids) == len(set(ids))


def test_list_filters_by_window_status_and_hides_archived(client, alice):
    vid = venture(client, alice)
    generate(client, alice, vid)
    start = datetime.combine(next_monday() + timedelta(days=7), datetime.min.time(), tzinfo=timezone.utc)
    week2 = client.get(f"/ventures/{vid}/plan", params={"start": start.isoformat(), "end": (start + timedelta(days=7)).isoformat()}, headers=alice).json()
    assert len(week2) == 7 and all(start.isoformat()[:10] <= s["scheduled_at"][:10] < (start + timedelta(days=7)).isoformat()[:10] for s in week2)

    target = week2[0]
    client.patch(f"/ventures/{vid}/plan/slots/{target['id']}", json={"status": "archived"}, headers=alice)
    assert target["id"] not in {s["id"] for s in slots(client, alice, vid)}
    assert target["id"] in {s["id"] for s in slots(client, alice, vid, include_archived="true")}
    assert [s["id"] for s in slots(client, alice, vid, status="archived")] == [target["id"]]


# --- editing and the status pipeline ------------------------------------------------

def one_slot(client, alice):
    vid = venture(client, alice)
    generate(client, alice, vid, period="week")
    return vid, slots(client, alice, vid)[0]


def patch(client, alice, vid, sid, **body):
    return client.patch(f"/ventures/{vid}/plan/slots/{sid}", json=body, headers=alice)


def test_pipeline_walks_forward_and_enforces_draft_and_approval(client, alice):
    vid, s = one_slot(client, alice)
    sid = s["id"]
    assert patch(client, alice, vid, sid, status="drafted").status_code == 400  # no draft yet
    assert patch(client, alice, vid, sid, draft="  ", status="drafted").status_code == 400
    assert patch(client, alice, vid, sid, draft="Real post text", status="drafted").json()["status"] == "drafted"
    bad = patch(client, alice, vid, sid, status="scheduled")  # skipping review/approval
    assert bad.status_code == 400 and "Allowed:" in bad.json()["detail"]
    for status in ("in_review", "approved", "scheduled", "published", "analysed"):
        assert patch(client, alice, vid, sid, status=status).json()["status"] == status
    assert patch(client, alice, vid, sid, status="idea").status_code == 400  # no going back once analysed


def test_back_steps_and_skip_restore(client, alice):
    vid, s = one_slot(client, alice)
    sid = s["id"]
    patch(client, alice, vid, sid, draft="x", status="drafted")
    patch(client, alice, vid, sid, status="approved")
    assert patch(client, alice, vid, sid, status="in_review").status_code == 200  # reviewer sends it back
    assert patch(client, alice, vid, sid, status="skipped").status_code == 200
    assert patch(client, alice, vid, sid, status="idea").status_code == 200  # restore a skipped one


def test_published_posts_are_read_only_and_undeletable(client, alice):
    vid, s = one_slot(client, alice)
    sid = s["id"]
    patch(client, alice, vid, sid, draft="x", status="drafted")
    for st in ("approved", "scheduled", "published"):
        patch(client, alice, vid, sid, status=st)
    assert patch(client, alice, vid, sid, topic="changed").status_code == 400
    assert patch(client, alice, vid, sid, draft="changed").status_code == 400
    assert patch(client, alice, vid, sid, scheduled_at="2030-01-01T00:00:00Z").status_code == 400
    assert patch(client, alice, vid, sid, locked=True).status_code == 200  # non-content flags are still fine
    assert client.delete(f"/ventures/{vid}/plan/slots/{sid}", headers=alice).status_code == 400
    assert patch(client, alice, vid, sid, status="analysed").status_code == 200


def test_reschedule_edit_and_type_change_rules(client, alice):
    vid, s = one_slot(client, alice)
    sid = s["id"]
    moved = patch(client, alice, vid, sid, scheduled_at="2030-05-01T09:30:00+02:00").json()
    assert moved["scheduled_at"] == "2030-05-01T07:30:00Z"
    assert patch(client, alice, vid, sid, scheduled_at="2030-05-01T09:30:00").status_code == 422  # naive time rejected
    assert patch(client, alice, vid, sid, topic=None).status_code == 422
    assert patch(client, alice, vid, sid, topic="New topic", pillar=None, cta="Link: https://x.example").json()["topic"] == "New topic"

    changed = patch(client, alice, vid, sid, post_type="product_demo").json()
    assert changed["stage"] == "bofu" and changed["reactive"] is False
    news = patch(client, alice, vid, sid, post_type="newsjacking").json()
    assert news["stage"] == "tofu" and news["reactive"] is True


def test_platform_fit_is_enforced(client, alice):
    vid, s = one_slot(client, alice)
    sid = s["id"]
    assert patch(client, alice, vid, sid, platform="reddit", post_type="lead_magnet").status_code == 400
    assert patch(client, alice, vid, sid, platform="reddit", post_type="story").status_code == 200
    assert patch(client, alice, vid, sid, post_type="short_video").status_code == 400  # now on reddit
    assert patch(client, alice, vid, sid, platform="tiktok").status_code == 422


def test_manual_slots(client, alice):
    vid = venture(client, alice, brief=None)
    r = client.post(f"/ventures/{vid}/plan/slots", json={"scheduled_at": "2030-01-01T10:00:00Z", "platform": "x", "post_type": "story", "topic": "My launch story"}, headers=alice)
    assert r.status_code == 201 and r.json()["stage"] == "mofu" and r.json()["status"] == "idea"
    bad = client.post(f"/ventures/{vid}/plan/slots", json={"scheduled_at": "2030-01-01T10:00:00Z", "platform": "reddit", "post_type": "product_demo", "topic": "x"}, headers=alice)
    assert bad.status_code == 400
    assert client.post(f"/ventures/{vid}/plan/slots", json={"scheduled_at": "2030-01-01T10:00:00Z", "platform": "x", "post_type": "story", "topic": " "}, headers=alice).status_code == 422
    assert client.delete(f"/ventures/{vid}/plan/slots/{r.json()['id']}", headers=alice).status_code == 204


# --- access, cascade ----------------------------------------------------------------

def test_plans_are_private_to_the_owner_and_scoped_to_the_venture(client, alice, bob, admin_headers):
    v1, s = one_slot(client, alice)
    v2 = venture(client, alice, name="Other")
    sid = s["id"]
    for call in (
        lambda h: client.get(f"/ventures/{v1}/plan", headers=h),
        lambda h: generate(client, h, v1),
        lambda h: patch(client, h, v1, sid, topic="x"),
        lambda h: client.delete(f"/ventures/{v1}/plan/slots/{sid}", headers=h),
        lambda h: client.post(f"/ventures/{v1}/plan/slots", json={"scheduled_at": "2030-01-01T10:00:00Z", "platform": "x", "post_type": "story", "topic": "x"}, headers=h),
    ):
        assert call(bob).status_code == 404
    assert patch(client, alice, v2, sid, topic="x").status_code == 404  # slot belongs to a different venture
    assert client.get(f"/ventures/{v1}/plan", headers=admin_headers).status_code == 200
    assert client.get(f"/ventures/{v1}/plan").status_code == 401


def test_deleting_a_venture_removes_its_plan(client, alice):
    vid, _ = one_slot(client, alice)
    assert client.delete(f"/ventures/{vid}", headers=alice).status_code == 204
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PlanSlot)) == 0


def test_all_datetimes_come_back_as_utc_even_on_sqlite(client, alice):
    v = client.post("/ventures", json={"name": "T"}, headers=alice).json()
    assert v["created_at"].endswith("Z") or v["created_at"].endswith("+00:00")


def test_hand_editing_an_idea_locks_it_so_regenerate_keeps_it(client, alice):
    vid, s = one_slot(client, alice)
    sid = s["id"]
    assert s["locked"] is False
    assert patch(client, alice, vid, sid, scheduled_at="2030-05-01T09:30:00Z").json()["locked"] is True  # a drag/reschedule counts

    others = [i for i in slots(client, alice, vid) if i["id"] != sid]
    topic_edit = patch(client, alice, vid, others[0]["id"], topic="My own angle").json()
    assert topic_edit["locked"] is True
    status_only = patch(client, alice, vid, others[1]["id"], status="skipped").json()
    assert status_only["locked"] is False  # changing status isn't editing content
    explicit = patch(client, alice, vid, others[2]["id"], topic="Edited", locked=False).json()
    assert explicit["locked"] is False  # the user's explicit choice wins

    out = generate(client, alice, vid, period="week", replace=True).json()
    # in range: the re-topiced (locked) one and the skipped one are kept; the explicitly unlocked edit is replaced.
    # The slot moved to 2030 is outside the planned period, so regenerating never touches it.
    assert out["kept"] == 2
    ids = {i["id"] for i in slots(client, alice, vid)}
    assert sid in ids and others[0]["id"] in ids and others[2]["id"] not in ids


# --- drafting -----------------------------------------------------------------------

def draft(client, headers, vid, sid, **body):
    return client.post(f"/ventures/{vid}/plan/slots/{sid}/draft", json=body, headers=headers)


def test_draft_returns_text_hooks_notes_and_does_not_save(client, alice, fake_ai):
    vid, s = one_slot(client, alice)
    r = draft(client, alice, vid, s["id"], instructions="Make it punchy")
    assert r.status_code == 200
    body = r.json()
    assert body["draft"].startswith("Draft about:") and body["hooks"] == ["Alt hook one", "Alt hook two"] and body["notes"]
    ctx = fake_ai.draft_calls[0]
    assert ctx["post"]["topic"] == s["topic"] and ctx["post"]["platform"] == s["platform"] and ctx["extra_instructions"] == "Make it punchy"
    assert ctx["voice"] is not None and ctx["venture"]["name"] == "Acme"
    assert slots(client, alice, vid)[0]["draft"] is None  # the author decides what to keep
    with client.app.state.session_factory() as db:
        from app.models import AIUsage

        usage = [u for u in db.scalars(select(AIUsage)).all() if u.feature == "slot_draft"]
    assert len(usage) == 1 and usage[0].input_tokens == 300


def test_draft_includes_the_linked_feed_article(client, alice, fetcher, fake_ai):
    fetcher.responses["https://blog.example/feed.xml"] = fresh_rss()
    vid = venture(client, alice)
    client.post(f"/ventures/{vid}/sources", json={"type": "rss", "target": "https://blog.example/feed.xml"}, headers=alice)
    client.post(f"/ventures/{vid}/feed/refresh", headers=alice)
    generate(client, alice, vid, period="week")
    linked = next(s for s in slots(client, alice, vid) if s["source_item_id"])
    draft(client, alice, vid, linked["id"])
    article = fake_ai.draft_calls[0]["source_article"]
    assert article and article["title"] == linked["topic"] and article["url"].startswith("https://blog.example")


def test_draft_guards(client, alice, bob, fake_ai):
    vid, s = one_slot(client, alice)
    assert draft(client, bob, vid, s["id"]).status_code == 404
    assert client.post(f"/ventures/{vid}/plan/slots/{s['id']}/draft", json={}).status_code == 401
    assert draft(client, alice, vid, 9999).status_code == 404
    assert draft(client, alice, vid, s["id"], instructions="x" * 501).status_code == 422
    patch(client, alice, vid, s["id"], draft="text", status="drafted")
    for st in ("approved", "scheduled", "published"):
        patch(client, alice, vid, s["id"], status=st)
    assert draft(client, alice, vid, s["id"]).status_code == 400  # already published


def test_draft_503_without_ai_and_429_over_the_limit(make_client, fetcher):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(make_settings(), ai=None, fetcher=fetcher)) as c:
        register(c, "a@example.com")
        h = login(c, "a@example.com")
        vid, s = one_slot(c, h)
        assert draft(c, h, vid, s["id"]).status_code == 503

    c = make_client(ai_daily_limit_per_user=1)
    register(c, "b@example.com")
    h = login(c, "b@example.com")
    vid, s = one_slot(c, h)
    assert draft(c, h, vid, s["id"]).status_code == 200
    assert draft(c, h, vid, s["id"]).status_code == 429


def test_warnings_show_up_on_slots_and_follow_the_draft(client, alice):
    vid, s = one_slot(client, alice)
    sid = s["id"]
    assert s["warnings"] == []
    r = patch(client, alice, vid, sid, platform="x", draft="a" * 300).json()
    assert any("over X's 280 limit" in w for w in r["warnings"])
    assert patch(client, alice, vid, sid, draft="short and fine").json()["warnings"] == []
    r = patch(client, alice, vid, sid, draft="We grew [client result] in 90 days").json()
    assert any("placeholder" in w for w in r["warnings"])
    assert all("warnings" in i for i in slots(client, alice, vid))


def test_cannot_approve_while_placeholders_remain(client, alice):
    vid, s = one_slot(client, alice)
    sid = s["id"]
    patch(client, alice, vid, sid, draft="We grew [client result] in [number] weeks", status="drafted")
    blocked = patch(client, alice, vid, sid, status="approved")
    assert blocked.status_code == 400 and "[client result]" in blocked.json()["detail"]
    assert patch(client, alice, vid, sid, status="in_review").status_code == 200  # review can still happen
    assert patch(client, alice, vid, sid, status="approved").status_code == 400
    assert patch(client, alice, vid, sid, draft="We grew 40% in 12 weeks", status="approved").json()["status"] == "approved"
