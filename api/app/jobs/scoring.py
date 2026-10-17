"""Deterministic relevance scoring (no AI, no network). The ingest script uses this to shortlist items so the
AI only ever sees the best few. Formula lives in code so it is testable and free to run."""

import math
import re
from datetime import datetime

_WORD = re.compile(r"[a-z][a-z0-9+#-]{3,}")
STOPWORDS = frozenset(
    "that this with from your have what when where which their about they them then than into over more most "
    "make made want need help helps helping helped build building using used also just like will would could should "
    "very much many some other such only both each every being been were does done doing".split()
)


def keywords(*texts: str | None) -> set[str]:
    words: set[str] = set()
    for text in texts:
        for w in _WORD.findall((text or "").lower()):
            if w not in STOPWORDS:
                words.add(w)
    return words


def brief_keywords(venture_name: str, venture_niche: str | None, brief: dict | None) -> set[str]:
    parts: list[str | None] = [venture_name, venture_niche]
    if brief:
        ideation, icp = brief.get("ideation", {}), brief.get("icp", {})
        parts += [ideation.get("niche_statement"), ideation.get("unique_angle"), *ideation.get("pillars", [])]
        parts += [icp.get("industry"), *icp.get("roles", []), *icp.get("pains", []), *icp.get("goals", [])]
    return keywords(*parts)


def rule_score(title: str, summary: str | None, published_at: datetime, engagement: int, kws: set[str], now: datetime) -> float:
    """0-100: 50% keyword overlap with the venture, 30% freshness (48h half-ish life), 20% engagement."""
    if kws:
        hits = len(kws & keywords(title, summary))
        keyword_part = min(hits / 3, 1.0)  # three distinct matches saturates; more doesn't help
    else:
        keyword_part = 0.3  # no brief yet: neutral rather than zero so the feed isn't empty
    age_hours = max((now - published_at).total_seconds() / 3600, 0)
    freshness = math.exp(-age_hours / 48)
    engage = min(math.log1p(max(engagement, 0)) / math.log1p(1000), 1.0)
    return round(100 * (0.5 * keyword_part + 0.3 * freshness + 0.2 * engage), 1)
