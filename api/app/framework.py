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
