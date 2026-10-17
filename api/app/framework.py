"""The content framework behind the planner: three funnel stages and ten post types (PRD section 6.11).
Constants only, no imports from the rest of the app, so models/schemas/planner can all share it."""

from datetime import time
from enum import Enum


class Stage(str, Enum):
    tofu = "tofu"
    mofu = "mofu"
    bofu = "bofu"


class PostType(str, Enum):
    newsjacking = "newsjacking"
    awareness = "awareness"
    educational = "educational"
    spectacle = "spectacle"
    story = "story"
    short_video = "short_video"
    lead_magnet = "lead_magnet"
    conversion = "conversion"
    objection = "objection"
    product_demo = "product_demo"


STAGE_OF: dict[PostType, Stage] = {
    PostType.newsjacking: Stage.tofu,
    PostType.awareness: Stage.tofu,
    PostType.educational: Stage.tofu,
    PostType.spectacle: Stage.tofu,
    PostType.story: Stage.mofu,
    PostType.short_video: Stage.mofu,
    PostType.lead_magnet: Stage.mofu,
    PostType.conversion: Stage.bofu,
    PostType.objection: Stage.bofu,
    PostType.product_demo: Stage.bofu,
}

STAGE_GOAL = {Stage.tofu: "Growth", Stage.mofu: "Trust building", Stage.bofu: "Selling"}

LABEL = {
    PostType.newsjacking: "Newsjacking",
    PostType.awareness: "Awareness",
    PostType.educational: "Educational",
    PostType.spectacle: "Spectacle",
    PostType.story: "Story",
    PostType.short_video: "Short video",
    PostType.lead_magnet: "Lead magnet",
    PostType.conversion: "Conversion",
    PostType.objection: "Objection",
    PostType.product_demo: "Product demo",
}

GUIDANCE = {
    PostType.newsjacking: "Share your take on news your audience is interested in.",
    PostType.awareness: "Reframe a common problem in a unique and relatable way.",
    PostType.educational: "Teach one useful idea your audience can try immediately.",
    PostType.spectacle: "Take a bold risk people will want to watch. Follow through.",
    PostType.story: "Share a real story, focusing on the lesson it taught you.",
    PostType.short_video: "Show your face in a video where you solve a common problem.",
    PostType.lead_magnet: "Give away something useful (checklist, template) for an email.",
    PostType.conversion: "Show a client's before-and-after transformation with real numbers.",
    PostType.objection: "Answer a common concern stopping people from buying.",
    PostType.product_demo: "Show your product solving a real problem, live.",
}

# Order in which a stage's types are rotated through when filling slots.
ROTATION: dict[Stage, list[PostType]] = {
    Stage.tofu: [PostType.educational, PostType.awareness, PostType.newsjacking, PostType.spectacle],
    Stage.mofu: [PostType.story, PostType.lead_magnet, PostType.short_video],
    Stage.bofu: [PostType.conversion, PostType.objection, PostType.product_demo],
}

_ALL = set(PostType)
PLATFORM_ALLOWED: dict[str, set[PostType]] = {
    "linkedin": _ALL,
    "x": _ALL,
    "instagram": _ALL,
    "youtube": _ALL,
    "blog": _ALL - {PostType.short_video},
    "newsletter": _ALL - {PostType.short_video},
    # communities discourage promotion: only helpful/story-style posts
    "reddit": {PostType.newsjacking, PostType.awareness, PostType.educational, PostType.story, PostType.objection},
}

# Assumed best posting windows (preferred weekdays, Mon=0, in priority order; local time). Tunable defaults, not data.
PLATFORM_SCHEDULE: dict[str, tuple[list[int], time]] = {
    "linkedin": ([1, 2, 3, 0, 4, 5, 6], time(8, 30)),
    "x": ([1, 2, 3, 0, 4, 5, 6], time(12, 0)),
    "reddit": ([1, 3, 0, 2, 4, 5, 6], time(9, 0)),
    "instagram": ([2, 4, 0, 1, 3, 5, 6], time(11, 0)),
    "youtube": ([3, 5, 1, 2, 4, 6, 0], time(15, 0)),
    "blog": ([1, 3, 2, 0, 4, 5, 6], time(10, 0)),
    "newsletter": ([3, 1, 2, 0, 4, 5, 6], time(8, 0)),
}

# Month rhythm: growth first, then trust, then capture, then convert. Multiplies the base mix per week.
WEEK_EMPHASIS: list[dict[Stage, float]] = [
    {Stage.tofu: 1.6, Stage.mofu: 0.8, Stage.bofu: 0.4},
    {Stage.tofu: 0.9, Stage.mofu: 1.6, Stage.bofu: 0.6},
    {Stage.tofu: 0.9, Stage.mofu: 1.4, Stage.bofu: 0.8},
    {Stage.tofu: 0.5, Stage.mofu: 0.8, Stage.bofu: 2.0},
]
DEFAULT_MIX = {"tofu": 50, "mofu": 30, "bofu": 20}


class SlotStatus(str, Enum):
    idea = "idea"
    drafted = "drafted"
    in_review = "in_review"
    approved = "approved"
    scheduled = "scheduled"
    published = "published"
    analysed = "analysed"
    skipped = "skipped"
    archived = "archived"


S = SlotStatus
TRANSITIONS: dict[SlotStatus, set[SlotStatus]] = {
    S.idea: {S.drafted, S.skipped, S.archived},
    S.drafted: {S.idea, S.in_review, S.approved, S.skipped, S.archived},
    S.in_review: {S.drafted, S.approved, S.skipped, S.archived},
    S.approved: {S.in_review, S.scheduled, S.skipped, S.archived},
    S.scheduled: {S.approved, S.published, S.skipped},
    S.published: {S.analysed, S.archived},
    S.analysed: {S.archived},
    S.skipped: {S.idea, S.archived},
    S.archived: set(),
}
DRAFT_REQUIRED = {S.drafted, S.in_review, S.approved, S.scheduled, S.published, S.analysed}
READ_ONLY = {S.published, S.analysed, S.archived}  # content can't change once it went out


# --- drafting (PRD F9) -------------------------------------------------------------

# Hard-ish limits used for deterministic warnings. X counts characters per post (threads are checked per part).
CHAR_LIMIT: dict[str, int] = {"x": 280, "linkedin": 3000, "instagram": 2200, "youtube": 5000, "reddit": 40000}

# What a good post looks like on each platform: handed to the model as instructions, never enforced by it.
PLATFORM_STYLE: dict[str, str] = {
    "linkedin": "LinkedIn post. A strong first line that earns the 'see more' click, short paragraphs of 1-2 sentences, "
    "roughly 900-1,300 characters, a clear point of view, at most 3 hashtags at the end, no emoji spam.",
    "x": "X post. One post of 280 characters or fewer, OR a numbered thread (start each part with '1/', '2/', ...) with every part "
    "280 characters or fewer. Hook first, no hashtags unless essential.",
    "reddit": "Reddit post or comment. Conversational and genuinely helpful, no marketing tone, no hype, no links or self-promotion "
    "unless the community clearly allows them. Lead with the useful answer or story.",
    "instagram": "Instagram caption. A hook in the first line, a friendly tone, short lines, a call to action, 3-5 relevant hashtags at the end.",
    "youtube": "Short-form video script (30-60 seconds). Format as HOOK (first 3 seconds), BODY (3 short beats), CTA. Spoken language.",
    "blog": "Blog article draft: a headline, a one-paragraph intro, 3-5 section headings each with a short outline of the point, and a closing takeaway.",
    "newsletter": "Newsletter edition: a subject line, a personal opening, one main idea developed in 3-4 short paragraphs, and one call to action.",
}


# --- quick replies (PRD F10) -------------------------------------------------------

REPLY_PLATFORMS = ("reddit", "linkedin", "x")
REPLY_LIMIT = {"x": 280, "linkedin": 1250}  # LinkedIn comments are capped well below posts
REPLY_STYLE = {
    "reddit": "A Reddit comment. Conversational and genuinely helpful, written like a knowledgeable community member and not a brand. "
    "Answer the question in the first sentence or two, then give the reasoning or a concrete example. 80-250 words. No headings, no emoji, "
    "no sales language, no links, no signature.",
    "linkedin": "A LinkedIn comment on someone else's post. 1-4 sentences that add something specific (an example, a counterpoint, a useful detail). "
    "No pitch, no link, no 'great post!' filler.",
    "x": "A reply on X. 280 characters or fewer. Add one specific, useful point. No hashtags, no link, no pitch.",
}
