"""'What the people I follow are talking about': a deterministic digest over influencer posts.

Pure functions, no AI, no DB. A topic is a word that shows up in at least MIN_POSTS different posts from at least
MIN_VOICES different influencers, so one person repeating themselves doesn't read as a trend."""

import re
from collections import defaultdict
from datetime import datetime

from app.jobs.scoring import keywords

MIN_POSTS = 2
MIN_VOICES = 2
MAX_TOPICS = 10
GENERIC = frozenset(
    "thing things people year years time times today really great good best work works working think back first still "
    "anyone down format cost thoughts question questions tips worth getting want keep some something".split()
)


def stem(word: str) -> str:
    # Merge trivial plurals ("leads"/"lead") without a stemming library; deliberately crude.
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def terms(*texts: str | None) -> set[str]:
    return {t for t in (stem(w) for w in keywords(*texts)) if t not in GENERIC}


def _blob(*texts: str | None) -> str:
    return " ".join(t for t in texts if t).lower()


def build_digest(posts: list[dict], own_texts: list[str], niche_terms: set[str], now: datetime, days: int) -> dict:
    """posts: dicts with influencer_id, influencer, title, summary, url, engagement, published_at.
    own_texts: topics/drafts of your own recent and upcoming posts, used to flag topics you haven't covered."""
    by_term: dict[str, list[dict]] = defaultdict(list)
    for p in posts:
        for t in terms(p["title"], p["summary"]):
            by_term[t].append(p)
    own = terms(*own_texts)
    niche = {stem(t) for t in niche_terms}

    topics = []
    for term, ps in by_term.items():
        voices = {p["influencer_id"] for p in ps}
        if len(ps) < MIN_POSTS or len(voices) < MIN_VOICES:
            continue
        top = max(ps, key=lambda p: (p["engagement"], p["published_at"]))
        topics.append({
            "term": term,
            "posts": len(ps),
            "voices": len(voices),
            "influencers": sorted({p["influencer"] for p in ps}),
            "engagement": sum(p["engagement"] for p in ps),
            "in_niche": term in niche,
            "covered": term in own,
            "example": {"title": top["title"], "url": top["url"], "influencer": top["influencer"], "engagement": top["engagement"]},
        })
    topics.sort(key=lambda t: (-t["voices"], -t["posts"], not t["in_niche"], -t["engagement"], t["term"]))

    per: dict[int, list[dict]] = defaultdict(list)
    for p in posts:
        per[p["influencer_id"]].append(p)
    voices_out = []
    for iid, ps in per.items():
        best = max(ps, key=lambda p: (p["engagement"], p["published_at"]))
        voices_out.append({
            "influencer_id": iid, "influencer": ps[0]["influencer"], "posts": len(ps),
            "avg_engagement": round(sum(p["engagement"] for p in ps) / len(ps), 1),
            "top_post": {"title": best["title"], "url": best["url"], "engagement": best["engagement"]},
        })
    voices_out.sort(key=lambda v: (-v["posts"], v["influencer"]))

    return {
        "days": days,
        "posts": len(posts),
        "topics": topics[:MAX_TOPICS],
        "gaps": [t["term"] for t in topics if not t["covered"] and t["in_niche"]][:5],
        "voices": voices_out,
        "note": None if posts else "No posts from the people you follow in this window yet. Add an influencer's feed, or paste in their posts.",
    }
