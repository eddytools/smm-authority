"""'What is hot in my communities': a deterministic read of community posts and how people reacted to them.

Pure functions, no AI, no DB. Engagement is whatever the community exposes (Reddit: upvotes + comments; pasted posts:
the likes + comments you entered). Communities differ hugely in size, so a post's "heat" is its engagement relative to
its own community's typical post, never the raw number."""

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from app.influence import stem, terms

MIN_POSTS = 2  # a topic needs this many posts before it counts
RISING = 1.5  # heat in the recent half at least 1.5x the earlier half
COOLING = 0.5
MAX_TOPICS = 12
MAX_HOT = 6
MAX_COOLING = 3  # extra cooling topics shown beyond the top list


def _relative(posts: list[dict]) -> dict[int, float]:
    """post index -> engagement relative to that community's median post (median floored at 1)."""
    by_community: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(posts):
        by_community[p["community"]].append(i)
    out: dict[int, float] = {}
    for idxs in by_community.values():
        median = max(1.0, statistics.median(posts[i]["engagement"] for i in idxs))
        for i in idxs:
            out[i] = posts[i]["engagement"] / median
    return out


def build_heat(posts: list[dict], own_texts: list[str], niche_terms: set[str], now: datetime, days: int) -> dict:
    """posts: dicts with community, title, summary, url, engagement, published_at, covering the last 2*days days. The
    window [now-days, now] is what's reported; [now-2*days, now-days] is the baseline that decides rising/cooling."""
    recent_from = now - timedelta(days=days)
    recent = [p for p in posts if p["published_at"] >= recent_from]
    earlier = [p for p in posts if p["published_at"] < recent_from]
    rel = _relative(recent)
    rel_earlier = _relative(earlier)

    def heat(relmap: dict[int, float], index: list[int]) -> float:
        return sum(math.log1p(relmap[i]) for i in index)

    recent_terms = [terms(p["title"], p["summary"]) for p in recent]
    earlier_terms = [terms(p["title"], p["summary"]) for p in earlier]
    by_term: dict[str, list[int]] = defaultdict(list)
    for i, ts in enumerate(recent_terms):
        for t in ts:
            by_term[t].append(i)
    prev_by_term: dict[str, list[int]] = defaultdict(list)
    for i, ts in enumerate(earlier_terms):
        for t in ts:
            prev_by_term[t].append(i)

    own = terms(*own_texts)
    niche = {stem(t) for t in niche_terms}
    topics = []
    for term, idxs in by_term.items():
        if len(idxs) < MIN_POSTS:
            continue
        now_heat = heat(rel, idxs)
        before = prev_by_term.get(term, [])
        before_heat = heat(rel_earlier, before)
        if not before and len(idxs) >= MIN_POSTS:
            trend = "new" if earlier else "unknown"
        elif now_heat >= RISING * before_heat:
            trend = "rising"
        elif now_heat <= COOLING * before_heat:
            trend = "cooling"
        else:
            trend = "steady"
        top = max(idxs, key=lambda i: (recent[i]["engagement"], recent[i]["published_at"]))
        comms = sorted({recent[i]["community"] for i in idxs})
        topics.append({
            "term": term,
            "posts": len(idxs),
            "communities": comms,
            "engagement": sum(recent[i]["engagement"] for i in idxs),
            "avg_relative": round(sum(rel[i] for i in idxs) / len(idxs), 2),
            "heat": round(now_heat, 2),
            "trend": trend,
            "in_niche": term in niche,
            "covered": term in own,
            "example": {"title": recent[top]["title"], "url": recent[top]["url"], "community": recent[top]["community"], "engagement": recent[top]["engagement"]},
        })
    topics.sort(key=lambda t: (-t["heat"], -t["posts"], t["term"]))
    # Cooling topics are low in heat by definition, so keep a few visible even when they miss the top list.
    shown = topics[:MAX_TOPICS]
    shown += [t for t in topics[MAX_TOPICS:] if t["trend"] == "cooling"][:MAX_COOLING]

    hot = sorted(range(len(recent)), key=lambda i: (-rel[i], -recent[i]["engagement"]))
    hot_posts = [
        {"title": recent[i]["title"], "url": recent[i]["url"], "community": recent[i]["community"], "engagement": recent[i]["engagement"], "relative": round(rel[i], 1)}
        for i in hot
        if rel[i] >= 1.5 and recent[i]["engagement"] > 0
    ][:MAX_HOT]

    per: dict[str, list[dict]] = defaultdict(list)
    for p in recent:
        per[p["community"]].append(p)
    communities = [
        {"community": name, "posts": len(ps), "median_engagement": statistics.median(p["engagement"] for p in ps), "top_engagement": max(p["engagement"] for p in ps)}
        for name, ps in per.items()
    ]
    communities.sort(key=lambda c: (-c["posts"], c["community"]))

    note = None
    if not recent:
        note = "No community posts in this window yet. Add a subreddit as a source, or add a community and paste in posts."
    elif len(recent) < 10:
        note = f"Based on only {len(recent)} post{'s' if len(recent) != 1 else ''}: treat these as hints, not conclusions."
    return {
        "days": days,
        "posts": len(recent),
        "has_baseline": bool(earlier),
        "topics": shown,
        "gaps": [t["term"] for t in topics if t["in_niche"] and not t["covered"]][:5],
        "hot_posts": hot_posts,
        "communities": communities,
        "note": note,
    }
