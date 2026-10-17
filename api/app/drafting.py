"""Pure helpers for the drafting studio: build the model's context from stored data, and run deterministic checks
on a draft. Nothing here calls the network, so it is fully testable."""

import re

from app.framework import CHAR_LIMIT, GUIDANCE, LABEL, PLATFORM_STYLE, PostType

# [client result], [number]: text the author must fill in. Markdown links "[text](url)" are not placeholders.
PLACEHOLDER = re.compile(r"\[(?![^\]\n]*\]\()[^\]\n]{2,80}\]")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_HASHTAG = re.compile(r"(?<!\w)#\w+")
_THREAD_PART = re.compile(r"(?m)^\s*\d+\s*/\s*")


def placeholders(text: str | None) -> list[str]:
    return PLACEHOLDER.findall(text or "")


def _x_parts(text: str) -> list[str]:
    if _THREAD_PART.search(text):
        return [p.strip() for p in _THREAD_PART.split(text) if p.strip()]
    return [text.strip()]


def check_draft(platform: str, text: str | None) -> list[str]:
    """Advisory warnings shown next to the draft. Only unfilled placeholders also block approval (see the plan router)."""
    text = (text or "").strip()
    if not text:
        return []
    warnings: list[str] = []
    limit = CHAR_LIMIT.get(platform)
    if platform == "x":
        for i, part in enumerate(_x_parts(text), 1):
            if len(part) > limit:
                where = f"Part {i} is" if len(_x_parts(text)) > 1 else "This post is"
                warnings.append(f"{where} {len(part)} characters, over X's {limit} limit. Shorten it or split it into a numbered thread.")
    elif limit and len(text) > limit:
        warnings.append(f"{len(text)} characters is over the {limit} limit for {platform}.")
    found = placeholders(text)
    if found:
        warnings.append(f"{len(found)} placeholder{'s' if len(found) != 1 else ''} to fill in before approving: {', '.join(found[:4])}{'…' if len(found) > 4 else ''}")
    if platform == "reddit" and _URL.search(text):
        warnings.append("Contains a link. Many subreddits remove posts with links or self-promotion, so check the community rules.")
    if platform == "linkedin" and len(_HASHTAG.findall(text)) > 3:
        warnings.append("More than 3 hashtags can look spammy on LinkedIn.")
    return warnings


def _clip(value: str | None, n: int) -> str | None:
    return value[:n] if value else value


def build_context(venture: dict, brief: dict | None, slot: dict, item: dict | None, instructions: str | None) -> dict:
    """Everything the model is allowed to know, as plain data. Writing samples are trimmed to keep calls cheap."""
    brief = brief or {}
    ideation, icp, offer, voice = (brief.get(k, {}) for k in ("ideation", "icp", "offer", "voice"))
    post_type = PostType(slot["post_type"])
    return {
        "venture": {"name": venture["name"], "niche": venture.get("niche"), "description": _clip(venture.get("description"), 600)},
        "positioning": {
            "niche_statement": ideation.get("niche_statement"),
            "unique_angle": ideation.get("unique_angle"),
            "opinions": ideation.get("opinions", [])[:5],
            "proof_assets_you_may_cite": ideation.get("proof_assets", [])[:8],
        },
        "audience": {k: icp.get(k) for k in ("industry", "roles", "pains", "goals", "objections")},
        "voice": {
            "tone": voice.get("tone"),
            "do": voice.get("dos", []),
            "dont": voice.get("donts", []),
            "writing_samples": [_clip(s, 1200) for s in voice.get("writing_samples", [])[:3]],
        },
        "post": {
            "platform": slot["platform"],
            "platform_style": PLATFORM_STYLE.get(slot["platform"], ""),
            "post_type": LABEL[post_type],
            "post_type_goal": GUIDANCE[post_type],
            "funnel_stage": slot["stage"],
            "pillar": slot.get("pillar"),
            "topic": slot["topic"],
            "call_to_action": slot.get("cta"),
            "lead_magnet": (offer.get("lead_magnets") or [None])[0],
            "existing_draft": _clip(slot.get("draft"), 3000),
        },
        "source_article": {"title": item["title"], "summary": _clip(item.get("summary"), 600), "url": item.get("url")} if item else None,
        "extra_instructions": _clip(instructions, 500),
    }
