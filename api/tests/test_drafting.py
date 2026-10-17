import pytest

from app.drafting import build_context, check_draft, placeholders

SLOT = {"platform": "linkedin", "post_type": "story", "stage": "mofu", "pillar": "Case studies", "topic": "How I lost my first client", "cta": "Link: https://acme.example/book", "draft": None}
BRIEF = {
    "ideation": {"niche_statement": "Founder-led growth", "opinions": ["Daily posting is overrated"], "proof_assets": ["3 case studies"], "unique_angle": "Proof first"},
    "icp": {"industry": "SaaS", "roles": ["Founder"], "pains": ["No time"]},
    "offer": {"lead_magnets": ["30-day planner"]},
    "voice": {"tone": "Direct", "dos": ["use numbers"], "donts": ["buzzwords"], "writing_samples": ["x" * 5000, "second", "third", "fourth"]},
}


def test_placeholders_found_but_markdown_links_and_plain_brackets_are_not():
    assert placeholders("We grew [client result] in [number] weeks") == ["[client result]", "[number]"]
    assert placeholders("Read [the guide](https://x.example) now") == []
    assert placeholders("[a]") == []  # too short to be a placeholder
    assert placeholders(None) == [] and placeholders("") == []


@pytest.mark.parametrize(
    "platform,text,expected",
    [
        ("x", "short post", []),
        ("x", "a" * 281, ["281 characters, over X's 280 limit"]),
        ("x", "1/ " + "a" * 100 + "\n\n2/ " + "b" * 300, ["Part 2 is 300 characters"]),
        ("x", "1/ ok\n\n2/ also ok", []),
        ("linkedin", "a" * 3001, ["over the 3000 limit for linkedin"]),
        ("linkedin", "Nice #one #two #three #four", ["More than 3 hashtags"]),
        ("linkedin", "Nice #one #two #three", []),
        ("reddit", "see https://acme.example", ["Contains a link"]),
        ("linkedin", "see https://acme.example", []),
        ("linkedin", "Won [client result]", ["1 placeholder to fill in"]),
        ("linkedin", "", []),
        ("blog", "a" * 20000, []),  # no limit
    ],
)
def test_check_draft(platform, text, expected):
    got = check_draft(platform, text)
    assert len(got) == len(expected) and all(e in g for e, g in zip(expected, got))


def test_context_contains_what_the_model_needs_and_trims_samples():
    ctx = build_context({"name": "Acme", "niche": "Coaching", "description": "d" * 1000}, BRIEF, SLOT, {"title": "Big news", "summary": "s" * 900, "url": "https://n.example"}, "make it shorter")
    assert ctx["post"]["platform"] == "linkedin" and "LinkedIn" in ctx["post"]["platform_style"]
    assert ctx["post"]["post_type"] == "Story" and "lesson" in ctx["post"]["post_type_goal"]
    assert ctx["post"]["lead_magnet"] == "30-day planner" and ctx["post"]["pillar"] == "Case studies"
    assert ctx["voice"]["tone"] == "Direct" and ctx["voice"]["do"] == ["use numbers"]
    assert len(ctx["voice"]["writing_samples"]) == 3 and len(ctx["voice"]["writing_samples"][0]) == 1200
    assert ctx["positioning"]["proof_assets_you_may_cite"] == ["3 case studies"]
    assert len(ctx["venture"]["description"]) == 600
    assert ctx["source_article"] == {"title": "Big news", "summary": "s" * 600, "url": "https://n.example"}
    assert ctx["extra_instructions"] == "make it shorter"


def test_context_works_with_no_brief_and_no_source():
    ctx = build_context({"name": "Acme"}, None, SLOT, None, None)
    assert ctx["source_article"] is None and ctx["voice"]["writing_samples"] == [] and ctx["positioning"]["niche_statement"] is None
