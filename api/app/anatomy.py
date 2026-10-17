"""'Why do the top posts win?': a deterministic look at what high-engagement posts have in common.

Pure functions, no AI, no DB. Each post is tagged with simple, checkable features (how it opens, how long it is, whether
it's a list...). Engagement is judged against the post's own source (a post that beats its community's median), then each
feature is compared with the average, using the same 1.25x / 0.75x thresholds as the performance insights."""

import re
import statistics
from collections import defaultdict

from app.heat import _relative

MIN_POSTS = 12  # analysed posts needed before we draw any pattern
MIN_GROUP = 3  # posts carrying a feature before we judge it
WIN_LIFT = 1.25
LOSE_LIFT = 0.75
HIGH = 1.5  # a "high performer" beats its source's median by this multiple
MAX_TOP = 6

_QUESTION_START = re.compile(r"^(who|what|why|how|when|where|which|anyone|is|are|do|does|did|can|should|would|will)\b", re.I)
_CONTRARIAN = re.compile(r"\b(dead|dying|myth|myths|wrong|overrated|stop|never|isn'?t|aren'?t|don'?t|doesn'?t|not\b.*\banymore|unpopular opinion|hot take|nobody)\b", re.I)
_HOWTO = re.compile(r"\b(how to|how we|how i|playbook|guide|step[- ]by[- ]step|steps|framework|template|checklist|teardown|lessons?)\b", re.I)
_FIRST_PERSON = re.compile(r"^(i|we|my|our|i'm|we're|i've|we've)\b", re.I)
_NUMBER = re.compile(r"\d")
_BULLETS = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S", re.M)
_LINK = re.compile(r"https?://", re.I)

LABEL = {
    "question": "Opens with a question",
    "number": "Has a number in the first line",
    "contrarian": "Takes a contrarian stance",
    "howto": "Is a how-to, playbook or lessons post",
    "first_person": "Starts with “I” or “we” (personal story)",
    "list": "Is a list (3+ bullets or numbered lines)",
    "short": "Is short (under 300 characters)",
    "medium": "Is medium length (300–900 characters)",
    "long": "Is long (over 900 characters)",
    "link": "Contains a link",
}
ADVICE = {
    "question": "Open your next post with a direct question your ideal customer would answer in the comments.",
    "number": "Put a specific number in the first line (a result, a count, a time frame).",
    "contrarian": "Take a clear side against a common belief in your niche, then back it with proof.",
    "howto": "Write a how-to or lessons-learned post: the exact steps or what you'd do differently.",
    "first_person": "Tell it as a first-person story: what you did, what happened, what you'd tell others.",
    "list": "Format it as a short list of 3–7 points people can skim.",
    "short": "Cut it down: one idea, under 300 characters.",
    "medium": "Aim for a medium-length post: enough room for one idea and its proof.",
    "long": "Go deeper: a long, structured post when the topic deserves it.",
    "link": "Keep a link in the post.",
}
AVOID = {
    "link": "Keep links out of the main post: these communities react less to posts that send people away.",
    "long": "Trim long posts: shorter ones are landing better.",
    "short": "Very short posts are landing flat here: give the idea a little more substance.",
    "contrarian": "Dial back the contrarian takes: they aren't landing with this audience.",
    "question": "Questions aren't landing here: lead with a statement or a result instead.",
    "number": "A number alone isn't helping: lead with the idea.",
    "howto": "Generic how-to framing isn't landing: use a specific story instead.",
    "first_person": "Personal-story openers aren't landing: lead with the lesson.",
    "list": "List formatting isn't landing: try plain paragraphs.",
    "medium": "Medium-length posts are underperforming here.",
}


def tags_for(title: str, text: str | None) -> set[str]:
    body = (text or title or "").strip()
    first = title.strip()  # the headline is the hook (for pasted posts it is the post's first line)
    tags: set[str] = set()
    if first.endswith("?") or _QUESTION_START.match(first):
        tags.add("question")
    if _NUMBER.search(first):
        tags.add("number")
    if _CONTRARIAN.search(first):
        tags.add("contrarian")
    if _HOWTO.search(first):
        tags.add("howto")
    if _FIRST_PERSON.match(first):
        tags.add("first_person")
    if len(_BULLETS.findall(body)) >= 3:
        tags.add("list")
    n = len(body)
    tags.add("short" if n < 300 else "medium" if n <= 900 else "long")
    if _LINK.search(body):
        tags.add("link")
    return tags


def build_analysis(posts: list[dict], days: int) -> dict:
    """posts: dicts with community (the source label), title, summary, url, engagement, published_at."""
    usable = [p for p in posts if p["engagement"] >= 0]
    rel = _relative(usable)
    tagged = [tags_for(p["title"], p["summary"]) for p in usable]
    overall = statistics.mean(rel.values()) if rel else 0.0

    by_tag: dict[str, list[int]] = defaultdict(list)
    for i, ts in enumerate(tagged):
        for t in ts:
            by_tag[t].append(i)

    patterns = []
    for tag, idxs in by_tag.items():
        if len(idxs) < MIN_GROUP or overall <= 0:
            continue
        avg = statistics.mean(rel[i] for i in idxs)
        lift = avg / overall
        verdict = "works" if lift >= WIN_LIFT else "flat" if lift <= LOSE_LIFT else None
        if verdict is None or len(usable) < MIN_POSTS:
            continue
        best = max(idxs, key=lambda i: rel[i])
        patterns.append({
            "tag": tag, "label": LABEL[tag], "verdict": verdict, "posts": len(idxs), "lift": round(lift, 2),
            "high_share": round(sum(1 for i in idxs if rel[i] >= HIGH) / len(idxs), 2),
            "advice": ADVICE[tag] if verdict == "works" else AVOID[tag],
            "example": {"title": usable[best]["title"], "url": usable[best]["url"], "community": usable[best]["community"], "engagement": usable[best]["engagement"]},
        })
    patterns.sort(key=lambda p: (p["verdict"] != "works", -abs(p["lift"] - 1) * p["posts"] ** 0.5, p["tag"]))

    order = sorted(range(len(usable)), key=lambda i: (-rel[i], -usable[i]["engagement"]))
    top = [
        {"title": usable[i]["title"], "url": usable[i]["url"], "community": usable[i]["community"], "engagement": usable[i]["engagement"], "relative": round(rel[i], 1),
         "tags": [LABEL[t] for t in sorted(tagged[i], key=lambda t: list(LABEL).index(t))]}
        for i in order
        if rel[i] >= HIGH and usable[i]["engagement"] > 0
    ][:MAX_TOP]

    note = None
    if len(usable) < MIN_POSTS:
        note = f"Needs at least {MIN_POSTS} posts with engagement numbers to find patterns (you have {len(usable)}). Add subreddits, influencers or groups, or paste in more posts."
    elif not patterns:
        note = "No feature stands out yet: your top posts don't share an obvious pattern."
    return {
        "days": days,
        "posts": len(usable),
        "high_performers": sum(1 for r in rel.values() if r >= HIGH),
        "patterns": patterns,
        "top": top,
        "note": note,
    }
