"""Local demo data. Creates a demo user with a fully set-up venture, a trend feed, a plan with history, and results,
so every screen has something to show.   python -m app.demo [--reset]

Everything here is made up (fictional company, example.com links, synthetic numbers with a built-in pattern).
It never contacts the network or an AI service."""

import argparse
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import make_engine, prepare_schema
from app.framework import DEFAULT_MIX, SlotStatus
from app.jobs.scoring import brief_keywords, rule_score
from app.feed_parsers import url_hash
from app.models import BriefVersion, FeedItem, Influencer, ItemStatus, PlanSlot, PostMetric, Role, Source, SourceType, User, Venture
from app.planner import Candidate, generate
from app.security import hash_password

INFLUENCERS = [
    ("Dana Whitfield (fictional)", "linkedin", "Founder-led marketing for B2B SaaS", [
        ("Webinars quietly beat cold outreach for inbound leads", "We ran 6 webinars last quarter. Inbound leads from them cost a third of outbound. Here is the setup.", 2, 410),
        ("Your pricing page is a marketing asset", "Most SaaS founders hide pricing. Showing it filtered our leads and doubled demo quality.", 6, 260),
    ]),
    ("Marcus Lee (fictional)", "blog", "Newsletter operator, practical SaaS growth", [
        ("How we grew a founder newsletter to 5,000 readers", "Webinars were our best newsletter growth channel. Pricing experiments came second.", 3, 150),
        ("Inbound leads from a newsletter: what the numbers say", "Newsletter readers convert 3x better than cold traffic when the offer is clear.", 9, 95),
    ]),
    ("Priya Nair (fictional)", "x", "Posts threads on founder content", [
        ("Thread: why your LinkedIn posts never turn into leads", "Posting is not the problem. A clear offer and a webinar-style follow-up is. Pricing clarity helps too.", 1, 320),
    ]),
]
DEMO_EMAIL, DEMO_PASSWORD = "demo@example.com", "demo-password-1"

BRIEF = {
    "icp": {
        "industry": "B2B SaaS", "company_size": "5-50 people",
        "roles": ["Founder", "Head of Marketing"],
        "pains": ["No time to post consistently", "Content feels generic", "Followers never turn into leads"],
        "goals": ["Steady inbound leads", "Be known for one clear idea"],
        "objections": ["We tried LinkedIn and it didn't work", "We can't afford an agency"],
        "channels": ["LinkedIn", "r/startups", "Founder newsletters"],
    },
    "ideation": {
        "niche_statement": "I help B2B SaaS founders turn their expertise into a steady stream of inbound leads.",
        "unique_angle": "Proof-first content: every post is backed by a real number or a real story.",
        "pillars": ["Founder-led growth", "Case studies", "LinkedIn tactics", "Sales without cold outreach"],
        "proof_assets": ["Grew a client from 0 to 40 inbound leads a month in 90 days", "3 published case studies"],
        "opinions": ["Posting every day is overrated", "Most founders hide their best stories"],
    },
    "offer": {"offer": "90-day Authority Sprint", "lead_magnets": ["30-day content planner"], "cta_url": "https://example.com/planner", "booking_url": "https://example.com/book"},
    "voice": {"tone": "Direct, warm, no jargon", "dos": ["use real numbers", "short sentences"], "donts": ["buzzwords", "hype"], "writing_samples": []},
    "platforms": [
        {"platform": "linkedin", "cadence_per_week": 4, "is_primary": True, "reason": "Your buyers are founders and marketers who live on LinkedIn."},
        {"platform": "x", "cadence_per_week": 3, "is_primary": False, "reason": "Good for newsjacking and testing hooks quickly."},
        {"platform": "reddit", "cadence_per_week": 1, "is_primary": False, "reason": "Helpful answers in founder communities build trust."},
    ],
}

FEED = [
    ("rss", "https://example.com/feed.xml", "Why founder-led content is replacing outbound for early-stage SaaS", "Teams that publish weekly see more inbound than those cold emailing.", 6, 0),
    ("rss", "https://example.com/feed.xml", "LinkedIn tests a new feed ranking that favours comments over reactions", "Early reports suggest longer comment threads now carry more weight.", 14, 0),
    ("google_news", "b2b saas marketing", "B2B buyers now research 70% of the way before talking to sales", "A new survey of 1,200 buyers shows most decisions are made before first contact.", 9, 0),
    ("google_news", "b2b saas marketing", "The rise of the 'dark funnel' and what it means for content teams", "Attribution gets harder as buyers move to private channels.", 30, 0),
    ("reddit", "startups", "How do you get inbound leads as a solo founder?", "I've tried cold email and it's dead. What's actually working for you in 2026?", 5, 212),
    ("reddit", "startups", "We stopped posting daily and our reach went up", "Switching to 3 strong posts a week doubled our engagement.", 20, 340),
    ("reddit", "startups", "What's a good case study format for a service business?", "Looking for structure: problem, approach, result?", 40, 64),
    ("rss", "https://example.com/feed.xml", "Case study teardown: a $40k deal that started with a LinkedIn comment", "A breakdown of the five touchpoints before the call.", 52, 0),
    ("google_news", "b2b saas marketing", "Short-form video is now the top format for B2B discovery", "Video posts from founders outperform company-page posts 3 to 1.", 70, 0),
    ("rss", "https://example.com/feed.xml", "Ten pasta recipes for busy weeknights", "Dinner ideas that take 20 minutes.", 12, 0),
]

DRAFTS = {
    "story": "I lost my first big client in week three.\n\nHere is what I got wrong, and the one change that turned it around.\n\n[Demo draft: replace with your own story.]",
    "educational": "One thing you can try this week:\n\n1. Pick one customer question you answer weekly.\n2. Turn the answer into a post.\n3. Add one real number.\n\nThat is it. Simple wins.",
    "awareness": "Founders don't have a content problem.\n\nThey have a 'saying the same thing as everyone else' problem.",
    "newsjacking": "Everyone is talking about the latest feed change. Here is my take for founders: stop optimising for the algorithm.",
    "lead_magnet": "I built a 30-day content planner for founders who hate planning.\n\nComment 'planner' and I will send it.",
    "conversion": "Before: 2 inbound leads a month.\nAfter 90 days: 40.\n\nWhat changed, step by step.",
    "objection": "'We tried LinkedIn and it didn't work.'\n\nUsually it was the first line, not the platform. Here is how to check.",
    "product_demo": "Two minutes: how the Authority Sprint turns one idea into a month of posts.",
    "spectacle": "I posted every day for 30 days and tracked everything. The results surprised me.",
    "short_video": "HOOK: Stop writing posts the hard way.\nBODY: three quick beats.\nCTA: follow for more.",
}

# Built-in pattern so the insights page has a story to tell: stories and video win, product demos lag.
TYPE_BOOST = {"story": 1.7, "short_video": 1.5, "spectacle": 1.3, "educational": 1.15, "newsjacking": 1.05, "awareness": 1.0, "lead_magnet": 0.95, "objection": 0.9, "conversion": 0.75, "product_demo": 0.5}
LEAD_RATE = {"lead_magnet": 1.6, "conversion": 1.2, "objection": 0.6, "product_demo": 0.5, "story": 0.3}


def seed(session_factory, reset: bool = False, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    with session_factory() as db:
        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user and not reset:
            return "Demo data already exists. Run with --reset to rebuild it."
        if user:
            db.execute(delete(User).where(User.id == user.id))
            db.commit()
        user = User(email=DEMO_EMAIL, name="Demo User", password_hash=hash_password(DEMO_PASSWORD), role=Role.user)
        db.add(user)
        db.flush()
        v = Venture(owner_id=user.id, name="Acme SaaS Growth", niche="Founder-led growth for B2B SaaS", website_url="https://example.com",
                    description="Demo venture with made-up data: a fictional consultancy helping B2B SaaS founders build authority and inbound leads.")
        db.add(v)
        db.flush()
        db.add(BriefVersion(venture_id=v.id, version=1, data=BRIEF, created_by_id=user.id))

        sources = {}
        for st, target in (("rss", "https://example.com/feed.xml"), ("google_news", "b2b saas marketing"), ("reddit", "startups")):
            src = Source(venture_id=v.id, type=SourceType(st), target=target, last_status="ok", last_fetched_at=now - timedelta(hours=2))
            db.add(src)
            db.flush()
            sources[(st, target)] = src
        kws = brief_keywords(v.name, v.niche, BRIEF)
        saved_items = []
        for i, (st, target, title, summary, hours, eng) in enumerate(FEED):
            published = now - timedelta(hours=hours)
            item = FeedItem(venture_id=v.id, source_id=sources[(st, target)].id, url=f"https://example.com/demo/{i}", url_hash=f"demo{i:04d}".ljust(64, "0"), title=title,
                            summary=summary, author="demo", published_at=published, fetched_at=now - timedelta(hours=2), engagement=eng,
                            rule_score=rule_score(title, summary, published, eng, kws, now), status=ItemStatus.saved if i in (0, 4) else ItemStatus.new)
            db.add(item)
            db.flush()
            if item.status == ItemStatus.saved:
                saved_items.append(Candidate(item.id, title, 90, True))

        for name, platform, note, posts in INFLUENCERS:
            src = Source(venture_id=v.id, type=SourceType.manual, target=f"influencer:demo-{name.split()[0].lower()}", label=name)
            db.add(Influencer(venture_id=v.id, name=name, platform=platform, notes=note, source=src))
            db.flush()
            for j, (title, text, days, eng) in enumerate(posts):
                url = f"https://example.com/demo-influencers/{name.split()[0].lower()}-{j}"
                published = now - timedelta(days=days)
                db.add(FeedItem(venture_id=v.id, source_id=src.id, url=url, url_hash=url_hash(url), title=title, summary=text, author=name, published_at=published, fetched_at=now,
                                engagement=eng, rule_score=rule_score(title, text, published, eng, kws, now)))

        tz = ZoneInfo("UTC")
        today = now.date()
        monday = today - timedelta(days=today.weekday())
        past = generate(BRIEF, monday - timedelta(days=28), 4, tz, DEFAULT_MIX)  # four full weeks, including the selling week
        coming = generate(BRIEF, monday, 4, tz, DEFAULT_MIX, candidates=saved_items)
        rng = random.Random(7)
        for p in past + coming:
            slot = PlanSlot(venture_id=v.id, scheduled_at=p.scheduled_at, platform=p.platform, post_type=p.post_type, stage=p.stage, pillar=p.pillar, topic=p.topic,
                            cta=p.cta, reactive=p.reactive, source_item_id=p.source_item_id)
            due = p.scheduled_at < now - timedelta(hours=6)
            if due:
                roll = rng.random()
                if roll < 0.08:
                    slot.status = SlotStatus.skipped
                elif roll < 0.14:
                    slot.status = SlotStatus.idea  # planned but never written
                else:
                    slot.draft = DRAFTS[p.post_type.value]
                    slot.status = SlotStatus.published
            else:
                days_out = (p.scheduled_at - now).days
                if days_out <= 2:
                    slot.draft, slot.status = DRAFTS[p.post_type.value], rng.choice([SlotStatus.drafted, SlotStatus.approved, SlotStatus.scheduled])
                elif days_out <= 5 and rng.random() < 0.4:
                    slot.draft, slot.status = DRAFTS[p.post_type.value], SlotStatus.drafted
            db.add(slot)
            db.flush()
            if slot.status == SlotStatus.published and rng.random() < 0.9:
                base = 1600 if p.platform == "linkedin" else 800 if p.platform == "x" else 600
                imp = int(base * rng.uniform(0.7, 1.4))
                rate = 0.035 * TYPE_BOOST[p.post_type.value] * rng.uniform(0.8, 1.2)
                eng = int(imp * rate)
                leads = int(rng.random() * 2 * LEAD_RATE.get(p.post_type.value, 0.15) + (1 if rng.random() < LEAD_RATE.get(p.post_type.value, 0.15) / 2 else 0))
                db.add(PostMetric(slot_id=slot.id, impressions=imp, reactions=int(eng * 0.72), comments=int(eng * 0.12), shares=int(eng * 0.06), saves=eng - int(eng * 0.72) - int(eng * 0.12) - int(eng * 0.06),
                                  clicks=int(imp * rng.uniform(0.004, 0.02)), follows=int(eng * 0.05), leads=leads, source="manual"))
                slot.status = SlotStatus.analysed
        db.commit()
    return f"Demo data created. Sign in as {DEMO_EMAIL} / {DEMO_PASSWORD}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="delete and recreate the demo user's data")
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(settings.database_url)
    prepare_schema(engine, settings)
    print(seed(sessionmaker(bind=engine, expire_on_commit=False), reset=args.reset))


if __name__ == "__main__":
    main()
