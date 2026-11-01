"""The 'Today' summary: one read of everything the research jobs collected and the plan ahead. Deterministic, no AI.

Pure helpers live here (easy to test); the router does the queries."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MAX_SUGGESTIONS = 6
STALE_AFTER = timedelta(hours=24)
DONE = {"published", "analysed"}
OFF = {"skipped", "archived"}


def day_bounds(now: datetime, tz: ZoneInfo, days: int) -> tuple[datetime, datetime, list[date]]:
    """Start of today in the user's timezone, the end of the window, and the list of dates in it."""
    local_today = now.astimezone(tz).date()
    start = datetime.combine(local_today, datetime.min.time(), tzinfo=tz)
    dates = [local_today + timedelta(days=i) for i in range(days)]
    return start, start + timedelta(days=days), dates


def week_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    today = now.astimezone(tz).date()
    monday = today - timedelta(days=today.weekday())
    start = datetime.combine(monday, datetime.min.time(), tzinfo=tz)
    return start, start + timedelta(days=7)


def source_health(last_status: str | None, last_fetched_at: datetime | None, now: datetime) -> str:
    """ok | error | stale | never"""
    if last_fetched_at is None:
        return "never"
    if last_status == "error":
        return "error"
    at = last_fetched_at if last_fetched_at.tzinfo else last_fetched_at.replace(tzinfo=now.tzinfo)
    return "ok" if now - at <= STALE_AFTER else "stale"


def coverage(health: list[str]) -> dict:
    total = len(health)
    counts = {k: health.count(k) for k in ("ok", "error", "stale", "never")}
    return {"sources": total, **counts, "pct": round(100 * counts["ok"] / total) if total else None}


def week_progress(slots: list[dict]) -> dict:
    planned = [s for s in slots if s["status"] not in OFF]
    done = sum(s["status"] in DONE for s in planned)
    return {"planned": len(planned), "published": done, "skipped": sum(s["status"] == "skipped" for s in slots), "pct": round(100 * done / len(planned)) if planned else None}


def suggestions(*, topic_gaps: list[dict], heat_gaps: list[dict], draft_slots: list[dict], opportunities: list[dict], saved_items: list[dict], setup: dict) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for t in topic_gaps:
        if t["term"] in seen:
            continue
        seen.add(t["term"])
        out.append({"kind": "topic_gap", "title": f"{', '.join(t['influencers'][:3])} are all writing about “{t['term']}”", "detail": f"{t['voices']} voices, {t['posts']} posts. It's not in your plan yet.", "term": t["term"], "link": None})
        if len(out) >= 2:
            break
    for t in heat_gaps:
        if t["term"] in seen:
            continue
        seen.add(t["term"])
        trend = {"rising": "is rising", "new": "just appeared"}.get(t["trend"], "is hot")
        out.append({"kind": "topic_gap", "title": f"“{t['term']}” {trend} in your communities", "detail": f"{t['posts']} posts across {', '.join(t['communities'][:2])}.", "term": t["term"], "link": None})
        if len(out) >= 3:
            break
    for s in draft_slots[:2]:
        out.append({"kind": "draft", "title": f"Write the draft: {s['topic']}", "detail": f"Planned for {s['when']} on {s['platform']}, still an idea.", "term": None, "link": "plan"})
    for o in opportunities[:2]:
        out.append({"kind": "reply", "title": f"Answer: {o['title']}", "detail": f"{o['source_label']}, a question worth a helpful reply.", "term": None, "link": "replies"})
    for i in saved_items[:1]:
        out.append({"kind": "saved", "title": f"Turn your saved item into a post: {i['title']}", "detail": "You saved it but haven't planned it.", "term": None, "link": "feed"})
    if not out:
        if not setup["brief"]:
            out.append({"kind": "setup", "title": "Finish your authority setup", "detail": "Your ICP, pillars and platforms drive every ranking here.", "term": None, "link": "setup"})
        if not setup["sources"]:
            out.append({"kind": "setup", "title": "Add a few sources to the trend feed", "detail": "RSS feeds, subreddits or a Google News search.", "term": None, "link": "feed"})
        if not setup["influencers"]:
            out.append({"kind": "setup", "title": "Follow 3 to 10 influencers in your niche", "detail": "You'll see what they're all writing about, here.", "term": None, "link": "influencers"})
        if not setup["plan"]:
            out.append({"kind": "setup", "title": "Generate your first content plan", "detail": "A month of TOFU / MOFU / BOFU posts in one click.", "term": None, "link": "plan"})
    return out[:MAX_SUGGESTIONS]
