"""Quick replies: pure helpers (no DB, no network, no AI).

Replying to strangers in communities is where marketing most easily turns into spam, so the guardrails live here, in
code the model cannot talk its way around:
- community rules the user pastes are parsed into hard flags (no links / no promotion / disclosure needed);
- every reply is scanned for links, mentions of the author's own business, promotional phrases and personal claims;
- 'questions worth answering' are ranked by recency, engagement and fit with a plain formula."""

import math
import re
from datetime import datetime

from app.drafting import over_limit, placeholders
from app.framework import GUIDANCE, LABEL, REPLY_STYLE, PostType
from app.jobs.scoring import keywords

_URL = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
_NO_LINKS = re.compile(r"\bno\s+(external\s+|outside\s+)?(links?|urls?)\b|\blinks?\s+(are\s+)?(not\s+allowed|prohibited|banned|forbidden)|\b(do\s+not|don'?t|never)\s+(post|include|share|add)\s+(any\s+)?(links?|urls?)", re.I)
_NO_PROMO = re.compile(
    r"\bno\s+(self[-\s]?promo(tion)?|promotion|advertis(ing|ements?)|ads\b|spam|soliciting|marketing)|self[-\s]?promo(tion)?\s+(is\s+)?(not\s+allowed|prohibited|banned|forbidden)|\b(do\s+not|don'?t|never)\s+(advertise|promote|solicit)",
    re.I,
)
_DISCLOSE = re.compile(r"\bdisclos(e|ure)|affiliat", re.I)
_PROMO_PHRASES = re.compile(
    r"\b(dm|pm)\s+me\b|\bmessage\s+me\b|check\s+out\s+(my|our)|\blink\s+in\s+(my\s+)?(bio|profile)|\bbook\s+a\s+(free\s+)?(call|demo|consult)|\bsign\s+up\b|\bsubscribe\b|\bfollow\s+(me|us)\b|\b(my|our)\s+(newsletter|course|agency|service|product|tool|platform|company|software)\b|\bfree\s+(trial|consultation|audit)\b",
    re.I,
)
_CLAIM_VERBS = r"(grew|built|helped|ran|started|launched|worked|managed|doubled|tripled|increased|reduced|saw|got|made|raised|closed|scaled|cut|boosted|generated|landed)"
_PERSONAL_CLAIM = re.compile(
    rf"\bin my experience\b|\bwhen i\b|\bi['’]?ve\b|\bwe['’]?ve\b|\b(i|we)\s+{_CLAIM_VERBS}\b|\bour\s+(clients?|customers?|team|users?)\b|\bmy\s+(clients?|customers?|team)\b"
    r"|\bi\s+am\s+a\b|\bas\s+a\s+\w+(\s+\w+)?\s+(founder|consultant|coach|owner)\b",
    re.I,
)
_QUESTION_START = re.compile(r"^\s*(how|what|why|when|where|which|who|should|can|could|would|is|are|do|does|did|any|anyone|anybody|has\s+anyone|have\s+you|looking\s+for|recommend|need\s+help|help|advice|tips|eli5)\b", re.I)


def parse_rules(text: str | None) -> dict[str, bool]:
    """Turn pasted community rules into flags. Deliberately blunt: when in doubt the stricter reading wins."""
    t = text or ""
    return {"no_links": bool(_NO_LINKS.search(t)), "no_promotion": bool(_NO_PROMO.search(t)), "disclosure": bool(_DISCLOSE.search(t))}


def promo_terms(venture: dict, brief: dict | None) -> list[str]:
    """Words that identify the author's own business, so a reply that names it can be flagged."""
    brief = brief or {}
    offer = brief.get("offer", {})
    candidates = [venture.get("name"), offer.get("offer"), *offer.get("lead_magnets", [])]
    for url in (venture.get("website"), offer.get("cta_url"), offer.get("booking_url")):
        if url:
            host = re.sub(r"^https?://", "", url.strip().lower()).split("/")[0].removeprefix("www.")
            candidates.append(host)
    out: list[str] = []
    for c in candidates:
        c = (c or "").strip()
        if len(c) >= 3 and c.lower() not in (o.lower() for o in out):
            out.append(c[:80])
    return out[:12]


def _mentions(text: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE))


def check_reply(platform: str, text: str | None, flags: dict[str, bool] | None = None, terms: list[str] | None = None) -> list[str]:
    """Advisory warnings shown beside a reply. Nothing is posted for the user, so these are for their judgement."""
    text = (text or "").strip()
    if not text:
        return []
    flags, terms, out = flags or {}, terms or [], []
    reply_limit = {"x": 280, "linkedin": 1250}.get(platform)
    if platform == "x":
        out += over_limit("x", text)
    elif reply_limit and len(text) > reply_limit:
        out.append(f"{len(text)} characters is over the {reply_limit}-character limit for a {platform} comment.")

    if _URL.search(text):
        out.append("This community's rules say no links. Remove the link." if flags.get("no_links") else "Contains a link. Links in replies are often removed and can read as promotion, so leave it out unless it directly answers the question.")
    named = [t for t in terms if _mentions(text, t)]
    promo = _PROMO_PHRASES.search(text)
    if named or promo:
        what = f"mentions your own business or offer ({', '.join(repr(t) for t in named[:3])})" if named else f"reads like promotion ({promo.group(0).strip()!r})"
        if flags.get("no_promotion"):
            out.append(f"This community bans self-promotion and this reply {what}. Rewrite it so it only helps.")
        else:
            out.append(f"This reply {what}. Many communities remove unlabelled self-promotion: either remove it, or say plainly that you're affiliated.")
    elif flags.get("disclosure"):
        out.append("The community rules mention disclosure. Check whether anything in your reply needs to be disclosed.")
    if _PERSONAL_CLAIM.search(text):
        out.append("Makes a personal claim (an experience, a result, a client). Keep it only if it is true and you can back it up.")
    if found := placeholders(text):
        out.append(f"{len(found)} placeholder{'s' if len(found) != 1 else ''} to fill in before you post: {', '.join(found[:4])}")
    if len(text) < 120 and platform == "reddit":
        out.append("Very short for a Reddit answer. Add the reason or a concrete example so it actually helps.")
    return out


def reply_context(venture: dict, brief: dict | None, *, platform: str, community: str | None, rules: str | None, question: str, instructions: str | None, existing: str | None) -> dict:
    """Everything the model may know. `author_facts` is the ONLY source of personal claims it is allowed to make."""
    brief = brief or {}
    ideation, icp, voice = brief.get("ideation", {}), brief.get("icp", {}), brief.get("voice", {})
    return {
        "author": {
            "business": venture.get("name"),
            "niche": venture.get("niche") or ideation.get("niche_statement"),
            "author_facts": ideation.get("proof_assets", [])[:8],  # the only experiences/results the reply may claim
            "views": ideation.get("opinions", [])[:5],
            "audience": {k: icp.get(k) for k in ("industry", "roles", "pains")},
        },
        "voice": {"tone": voice.get("tone"), "do": voice.get("dos", []), "dont": voice.get("donts", []), "writing_samples": [s[:800] for s in voice.get("writing_samples", [])[:2]]},
        "where": {"platform": platform, "format": REPLY_STYLE[platform], "community": community, "community_rules": (rules or "")[:3000] or None},
        "thread": question[:6000],
        "existing_reply": (existing or "")[:3000] or None,
        "extra_instructions": (instructions or "")[:500] or None,
        "post_idea_format": {"type": LABEL[PostType.educational], "goal": GUIDANCE[PostType.educational]},
    }


def is_question(title: str) -> bool:
    return "?" in title or bool(_QUESTION_START.match(title))


def rank_opportunities(items: list[dict], now: datetime, brief_keywords: set[str] | None = None, limit: int = 10) -> list[dict]:
    """'Questions worth answering': question-like threads, newest and liveliest first, nudged toward the author's niche.
    items: dicts with id, title, summary, url, source_label, source_type, engagement, published_at (aware), rule_score."""
    ranked = []
    for it in items:
        if not is_question(it["title"]):
            continue
        age_h = max((now - it["published_at"]).total_seconds() / 3600, 0)
        freshness = math.exp(-age_h / 12)  # a reply is most useful in the first hours
        engage = min(math.log1p(max(it["engagement"], 0)) / math.log1p(500), 1.0)
        fit = min(it.get("rule_score", 0) / 100, 1.0)
        if brief_keywords:
            fit = max(fit, min(len(brief_keywords & keywords(it["title"], it.get("summary"))) / 3, 1.0))
        ranked.append({**it, "age_hours": round(age_h, 1), "score": round(100 * (0.4 * freshness + 0.35 * engage + 0.25 * fit), 1)})
    return sorted(ranked, key=lambda r: (-r["score"], r["id"]))[:limit]
