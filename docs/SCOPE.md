# SMM Authority — Project Scope Document

| | |
|---|---|
| **Status** | Draft v0.3 for review |
| **Date** | 2026-10-17 |
| **Owner** | eddytools |
| **Supersedes** | v0.2 (added execution model: scripts for recurring work, AI API for research) |

> **[A]** = assumption, **[Q]** = open question. Confirm or correct before build starts.

---

## 1. Purpose

SMM Authority is a **multi-tenant SaaS** that helps a prospect (founder, consultant, coach, B2B service or product owner) **build authority, grow a personal/brand presence, and convert that attention into leads**.

The app does five things:

1. **Understands** the user once (ICP, niche, offer, voice) in a one-time guided setup.
2. **Researches** what the niche is talking about right now (trends, influencers, high-engagement posts, community questions).
3. **Suggests** what to post, grounded in that research and the user's ICP.
4. **Plans** a weekly and monthly calendar built on a TOFU / MOFU / BOFU content mix.
5. **Measures** what worked and what didn't, and feeds that back into the next suggestions.

**Outcome chain:** Authority → Branding → Lead conversion.

## 2. Problem Statement

- Prospects don't know what to post, so they post inconsistently or generically.
- Trend and community research is manual, scattered across Google, X, Reddit, LinkedIn and RSS, and rarely turned into content.
- Content is often all top-of-funnel (growth) with no trust-building or selling posts, so followers never become leads.
- Fast-moving conversations (a Reddit or forum question, a breaking news item) are missed because drafting a good reply takes too long.
- There is no feedback loop: users can't tell which topics, formats and funnel stages actually drive engagement and leads.

## 3. Target Users

| Persona | Description | Primary need |
|---|---|---|
| **Prospect / account owner (primary)** | Solo expert or small-business owner, limited marketing time | Know what to post, post it consistently, see what converts |
| **Team member** | Marketer or VA working under the owner | Draft, schedule, track within one workspace |
| **Agency (secondary) [A]** | Manages several client workspaces | Multi-workspace switching, reports |
| **Platform admin** | Internal operator | Tenants, plans, usage and cost control |

**[Q]** Is multi-workspace/agency mode needed in v1, or single workspace per account?

## 4. Goals and Success Metrics

| Goal | Metric | Target (first 90 days) |
|---|---|---|
| Fast time-to-value | Sign-up → first suggested content set | < 15 minutes median |
| Activation | Users who approve a monthly plan | ≥ 50% of sign-ups |
| Consistency | Users hitting planned cadence in weeks 3–4 | ≥ 40% of activated users |
| Research value | Weekly users who open the trend feed and convert ≥ 1 idea to a post | ≥ 50% |
| Funnel balance | Plans containing all three stages (TOFU, MOFU, BOFU) | 100% (system-enforced) |
| Outcome | Lead-magnet and CTA clicks per month vs. baseline | Tracked; target set after beta |
| Retention | Month-2 paid retention | ≥ 60% |

## 5. Product Modules (Scope Map)

Each module maps to the requirements in the brief. Numbers in brackets are the original requirement numbers.

### Execution Model (applies to all modules)

**Rule: AI APIs are used for research and judgment. Recurring, predictable work runs as plain Python or JS scripts.** AI is never called to do something a script can do deterministically.

| Work type | Executor | Examples |
|---|---|---|
| **Recurring / scheduled, deterministic** | **Python or JS scripts** on a scheduler | Fetch RSS, Reddit, X and Google Trends data; dedupe; normalise; collect post metrics; compute engagement stats and rankings; build the monthly calendar skeleton from the funnel rules; fire reminders and scheduled publishes; send the weekly digest; refresh tokens; retry failures |
| **Research / judgment, on demand or batched** | **AI API (LLM)** | Build the Authority Brief from setup answers; score topic relevance to the ICP; summarise why a topic matters; extract patterns from high-engagement posts; suggest post angles and hooks; draft content in the user's voice; draft quick-response replies; write the "what worked / what didn't" insights |

How the two connect:

1. **Scripts gather and prepare.** A scheduled job pulls raw items, filters with cheap rules (keywords, recency, minimum engagement, dedupe), and stores them.
2. **AI processes only the shortlist.** Only items that pass the script filters are sent to the LLM, in batches, with results cached by content hash. This keeps cost predictable.
3. **Scripts act on the output.** Results are written to the database, and other scripts place them on the calendar, send notifications, or publish after approval.

Rules for the implementation:
- Each recurring job is a standalone, idempotent script with logging, retries, and a per-source health status.
- LLM calls go through one wrapper that applies caching, token budgets per plan, structured (JSON) output validation, and a fallback to "no AI result" so a script run never fails because the model did.
- Fixed formulas (funnel mix, cadence, slot placement, metric aggregation, engagement ranking) live in code, not in prompts, so they are testable and free to run.
- On-demand AI features (draft, quick response, regenerate) run when the user asks, not on a schedule, unless the user opts into daily auto-suggestions.

### M1. Account, Workspace and One-Time Setup [1, 2]

A **one-time guided setup** (editable later) that captures everything the engine needs:

- **ICP profile:** industry, company size, role/title, pain points, goals, objections, where they hang out, language they use.
- **Authority ideation:** niche statement, unique angle, 3–5 content pillars, proof assets (case studies, numbers, testimonials), points of view the user is willing to take.
- **Offer and funnel:** product/service, lead magnet(s), CTA links, booking/landing page.
- **Voice:** tone, do/don't list, writing samples.
- **Competitors/peers** and **influencers to watch**.

Output: an **Authority Brief** that grounds every later feature. SaaS foundations: sign-up, workspaces, roles, subscription plans with usage limits, billing, onboarding emails.

### M2. Platform Selection [3]

- User picks the platforms to build authority on (LinkedIn, X, Reddit, Instagram, YouTube, Medium/blog/newsletter **[A]**).
- App recommends a primary and secondary platform from the ICP, with reasons.
- Per-platform settings: posting cadence, format mix, tone adjustments, connection status.

### M3. Daily Trending Topic Feed [4]

A daily, ICP-filtered feed of topics gathered from:

| Source | What we pull | Notes |
|---|---|---|
| Google | Trends and rising queries, "people also ask", news | Official trends/search APIs or a data provider |
| X | Trending and niche-keyword posts | Paid API tier likely required **[A]** |
| Reddit | Rising/hot posts in chosen subreddits | Official API, rate limits and commercial terms apply |
| RSS | User-added blogs, news and newsletters | Low risk, high reliability |

Features: topic clustering and de-duplication, relevance score against the ICP and pillars, "why it matters" summary, save/dismiss, **one-click "turn into post idea."**

### M4. Influencer and Peer Watch [5]

- User maintains a watchlist of same-domain influencers and communities (Reddit users/subreddits, LinkedIn creators, X accounts).
- App surfaces what they are talking about: recurring themes, new angles, posting patterns.
- **[Risk] LinkedIn:** there is no public API for reading other people's posts. Options: (a) user-supplied links/pasted posts and browser-extension capture, (b) a licensed data provider, (c) skip automated reading for v1. Scraping against platform terms is **not** in scope. **[Q]** Which option do you prefer?

### M5. Community and Topic Heat [6]

- For tracked subreddits, groups and hashtags, show which topics are heating up, measured by upvotes, likes, comments and reply velocity over time.
- Topic heat chart (rising, steady, fading) and "what the community keeps asking."
- LinkedIn group-level data is limited by API access; same options as M4.

### M6. High-Engagement Post Analysis [7]

- Rank posts in the niche by engagement (relative to account size where available).
- Break each down: hook type, format, length, topic, posting time, CTA type.
- Extract reusable **patterns** ("contrarian hook + list posts outperform"), not copy. The app never reproduces others' content verbatim.

### M7. Content Suggestion Engine [8]

- Combines M3–M6 with the Authority Brief to suggest posts: topic, angle, hook options, format, funnel stage, platform, and the research that justifies it.
- Suggestion types follow the **10 post types** in section 6.
- Each suggestion carries a short "why this, why now" rationale and an estimated fit/priority score.
- Draft generator in the user's voice, per platform; edit, regenerate, approve.

### M8. Quick-Response Assistant [11]

For forum and community questions (Reddit, Quora-style forums, LinkedIn/X conversations):

- User pastes a link/question, or picks from "questions worth answering" detected in tracked communities.
- App drafts: (a) a **short, genuinely helpful reply**, (b) an optional **expanded post idea** based on the same question for owned channels.
- Prioritises threads with high engagement and recency.
- **Safeguards:** human review and manual posting by default (no auto-replies); community self-promotion rules shown per subreddit; link/CTA use flagged when a community discourages it.

### M9. Content Planning and Status Workflow [9, 12]

- **Weekly and monthly planner** that auto-generates a schedule for the month (see section 6).
- Calendar views: month, week, list; drag-and-drop rescheduling; best-time suggestions.
- **Status pipeline:** Idea → Drafted → In Review → Approved → Scheduled → Published → Analysed (plus Skipped/Archived).
- Idea bank, templates, comments/approvals for teams.
- Publishing: schedule and auto-publish where APIs allow; otherwise reminder + copy-ready post. **[A]** LinkedIn, X and Reddit first.

### M10. Performance Tracking and Learning Loop [10]

- Per-post metrics: impressions, likes, comments, shares, clicks, saves, follower change, profile visits **[A]** (as exposed by each platform).
- **Lead attribution:** UTM links, lead-magnet sign-ups, booking clicks, and manual "lead from this post" tagging.
- Breakdowns by platform, pillar, post type, funnel stage, format, time of day.
- **"What worked / what didn't"** report (weekly and monthly) with plain-language insights and recommended changes.
- Learnings feed back into M7 ranking and M9 planning.

### M11. Dashboard, Notifications, Admin

- Home dashboard: today's feed, this week's schedule, pending approvals, headline performance and lead metrics.
- Weekly email digest; reminders for scheduled/manual posts.
- Admin: tenants, plans, usage and API cost monitoring, source health, content/template management.

## 6. Content Strategy Framework (from the reference funnel)

The planner is built on a **three-stage funnel with 10 post types**. This is a built-in framework, editable by admins and tunable per workspace.

| Stage | Goal | # | Post type | What it does |
|---|---|---|---|---|
| **TOFU** | Growth | 1 | Newsjacking | Share a take on news the audience cares about |
| | | 2 | Awareness | Reframe a common problem in a unique, relatable way |
| | | 3 | Educational | Teach one useful idea the audience can try immediately |
| | | 4 | Spectacle | Take a bold, watchable risk and follow through |
| **MOFU** | Trust building | 5 | Story | Real story focused on the lesson learned |
| | | 6 | Short video | Face-to-camera video solving a common problem |
| | | 7 | Lead magnet | Give away a checklist/template for an email |
| **BOFU** | Selling | 8 | Conversion | Client before-and-after with real numbers |
| | | 9 | Objection | Answer a common concern stopping people from buying |
| | | 10 | Product demo | Show the product solving a real problem, live |

### How the planner uses it

- **Default mix [A]:** ~50% TOFU, ~30% MOFU, ~20% BOFU, adjustable by the user and by what the performance data shows works.
- **Weekly plan:** a balanced set of posts across stages and platforms, e.g. 3–5 posts/week per primary platform. A TOFU post that earns attention is followed by MOFU and BOFU posts on the same pillar.
- **Monthly plan:** a full-month schedule that
  - covers every pillar,
  - sequences funnel stages (growth → trust → sell) across weeks,
  - places lead-magnet and conversion posts on a regular rhythm,
  - reserves slots for **reactive posts** (newsjacking, quick responses) fed from M3/M8,
  - respects per-platform cadence and best-time windows.
- **Auto-fill, then edit:** the system proposes the month; the user can lock, swap, regenerate or move any slot.
- Each calendar slot stores: date/time, platform, post type, funnel stage, pillar, topic source, status and CTA.

### Illustrative monthly rhythm **[A]**

| Week | Focus | Typical posts |
|---|---|---|
| 1 | Growth + awareness | Newsjacking, Awareness, Educational |
| 2 | Trust | Story, Short video, Educational |
| 3 | Capture | Lead magnet, Awareness, Spectacle |
| 4 | Convert | Conversion, Objection, Product demo |

## 7. Core User Journey

1. Sign up → one-time setup (ICP, ideation, offer, voice) → Authority Brief.
2. Choose platforms; connect accounts and add RSS, subreddits, influencers.
3. Open the daily feed → see trends, influencer themes, hot topics and top-performing posts.
4. Receive content suggestions → accept, edit, and approve drafts.
5. Generate the weekly/monthly plan → review the calendar.
6. Publish/schedule; use the quick-response assistant for hot threads.
7. Review the performance and lead report → apply "what worked" to the next plan.

## 8. Functional Requirements (Summary)

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Multi-tenant accounts, workspaces, roles, subscription billing | Must |
| FR-2 | One-time setup capturing ICP, ideation, offer and voice; generates an editable Authority Brief | Must |
| FR-3 | Platform selection with recommendations and per-platform settings | Must |
| FR-4 | Daily trending feed from Google, X, Reddit and RSS, filtered to the ICP | Must |
| FR-5 | Influencer/peer watchlist and "what they're talking about" summary (Reddit first; LinkedIn per chosen option) | Should |
| FR-6 | Topic heat tracking by community engagement (likes, comments, velocity) | Should |
| FR-7 | High-engagement post ranking with pattern extraction | Must |
| FR-8 | Content suggestions with rationale, funnel stage and post type | Must |
| FR-9 | Draft generation in user voice, per platform, with approval before publish | Must |
| FR-10 | Quick-response drafts for forum/Reddit questions (human-posted by default) | Must |
| FR-11 | Weekly and monthly planner using the 10-post-type TOFU/MOFU/BOFU framework | Must |
| FR-12 | Calendar with status pipeline and drag-and-drop | Must |
| FR-13 | Scheduling/publishing to LinkedIn, X and Reddit where APIs allow | Should |
| FR-14 | Per-post performance tracking and "what worked / what didn't" reports | Must |
| FR-15 | Lead attribution via UTM links and manual tagging | Should |
| FR-16 | Feedback loop: performance data re-ranks suggestions and adjusts the mix | Should |
| FR-17 | Weekly digest email and reminders | Should |
| FR-18 | Admin console with usage and cost monitoring | Should |
| FR-19 | All recurring jobs (ingestion, filtering, metrics, ranking, plan skeleton, publishing, digests) run as Python/JS scripts, not LLM calls | Must |
| FR-20 | LLM calls limited to research/judgment tasks, routed through one wrapper with caching, budgets and validated output | Must |
| FR-21 | Admin view of each scheduled job's last run, status, duration and error | Should |

## 9. Non-Functional Requirements

- **Freshness:** trend feed refreshed at least daily; hot-community signals at least hourly where APIs permit.
- **Performance:** feed loads < 2 s; monthly plan generated < 60 s.
- **Security and privacy:** tenant data isolation; encrypted OAuth tokens; data export and deletion; user content not used to train third-party models.
- **Compliance:** follow each platform's API terms, rate limits and data-retention rules; no scraping that violates terms; AI-content disclosure where required.
- **Reliability:** failed scheduled posts retried and surfaced; ingestion failures per source visible in admin.
- **Cost control:** recurring work runs as scripts with zero LLM cost; LLM calls are limited to shortlisted items and on-demand requests, cached by content hash, and capped per plan (LLM calls, source queries, connected accounts).
- **Script quality:** every scheduled script is idempotent, unit-tested against recorded API fixtures, logs structured output, and reports success/failure to the admin health view.
- **Accessibility:** WCAG 2.1 AA for core flows.

## 10. Proposed Architecture (High Level) **[A]**

- **Frontend:** Next.js/React responsive web app.
- **Backend:** API service (Python/FastAPI or Node) plus a job scheduler and worker queue **[A]** (e.g. cron/APScheduler/Celery or BullMQ).
- **Scheduled scripts layer (Python or JS):** one script per recurring job, run by the scheduler:

  | Script | Frequency [A] | Purpose |
  |---|---|---|
  | `ingest_rss` / `ingest_reddit` / `ingest_x` / `ingest_trends` | Hourly to daily | Pull and normalise items per workspace sources |
  | `filter_and_dedupe` | After each ingest | Rule-based shortlist (relevance keywords, recency, engagement threshold) |
  | `collect_metrics` | Daily | Pull post analytics from platform APIs |
  | `rank_engagement` / `topic_heat` | Daily/hourly | Compute engagement ranking and topic velocity |
  | `build_plan_skeleton` | Weekly/monthly | Fill slots from funnel mix, cadence and pillar rules |
  | `publish_due_posts` / `send_reminders` | Every few minutes | Publish approved posts or notify for manual posting |
  | `send_digest` | Weekly | Digest email |
  | `refresh_tokens` / `health_check` | Daily | Keep connectors working; flag failing sources |

- **Ingestion layer:** pluggable source connectors (Google, X, Reddit, RSS, LinkedIn-via-approved-route) used by the scripts above, writing normalised items to the database.
- **AI layer (API-based):** LLM called only for research and judgment on shortlisted items and on-demand requests: ICP relevance scoring, topic summaries, pattern extraction, suggestions, drafts and insights, grounded on the Authority Brief. Single wrapper with caching, token budgets, JSON schema validation; evaluation set for quality and brand-voice checks.
- **Data:** Postgres (tenants, briefs, sources, topics, posts, plans, metrics) with vector search for relevance and voice; object storage for assets.
- **Integrations:** Stripe, OAuth providers, platform publishing/analytics APIs, email service, UTM/link tracking.

**[Q]** Any required stack, hosting or existing codebase? (The repository is currently empty.)

## 11. Phasing

| Phase | Contents |
|---|---|
| **MVP (Phase 1)** | M1 setup; M2 platform selection; M3 feed (RSS, Google, Reddit, X); M7 suggestions and drafts; M9 planner with funnel framework and status; M10 basic performance tracking; LinkedIn and X (and Reddit manual) publishing; billing |
| **Phase 2** | M4 influencer watch and M5 topic heat in full; M6 high-engagement analysis; M8 quick-response assistant; lead attribution; learning-loop re-ranking |
| **Phase 3** | Agency multi-workspace and white-label reports; more platforms (YouTube, Instagram, newsletter/blog); video repurposing; browser extension for capture |

**[Q]** M8 and M6 are core to the differentiation. Should they move into the MVP, accepting a longer timeline?

## 12. Out of Scope

- Auto-posting replies or comments in communities without human review.
- Fake engagement, engagement pods, bought followers or reviews.
- Scraping platforms in violation of their terms.
- Copying or reposting other creators' content.
- Paid ads management, CRM, or email-marketing platform (only lead-magnet link tracking).
- Full graphic or video editing suite.
- Native mobile apps (responsive web for v1).
- Done-for-you human ghostwriting.

## 13. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **LinkedIn exposes no public read API** | Influencer/engagement analysis limited | Offer approved routes only (user capture, licensed provider); design M4/M5 to work Reddit/X/RSS-first |
| **X and Reddit API cost and rate limits** | Margin pressure, feed gaps | Cache aggressively, cap queries per plan, price tiers to usage |
| Platform policy changes | Features break | Connector abstraction; manual fallback |
| Generic or "AI-sounding" content | Low results, churn | Authority Brief grounding, voice samples, edit-first UX, quality evals |
| Community backlash to self-promotion | Account bans or bad reputation | Human-in-the-loop replies, per-community rule hints, CTA warnings |
| Trend feed noise | Users ignore it | ICP-based relevance scoring, feedback (dismiss/save) tuning |
| Weak lead attribution | Can't prove ROI | UTM defaults, lead-magnet tracking, manual tagging |
| LLM cost overrun | Margin loss | Scripts do the recurring work; LLM sees only shortlisted items; caching, model tiering, per-plan caps |
| Scheduled scripts fail silently or break on API changes | Stale feed, missed posts | Idempotent jobs, retries, health dashboard and alerts, fixture-based tests |
| Scope creep | Delays | Hold phase boundaries in section 11 |

## 14. Assumptions and Dependencies

- Developer access to X, Reddit and LinkedIn APIs can be obtained (and budgeted) early.
- A Google trends/search data source and (optionally) an SEO/keyword data provider are selected.
- English first; localisation deferred.
- Legal review of terms, privacy and AI disclosure is done before beta.

## 15. Open Questions

1. Is the first release for single-owner accounts only, or does it need agency multi-workspace support?
2. Which platforms are must-have for launch (LinkedIn, X and Reddit are assumed)?
3. LinkedIn data approach: user capture, licensed provider, or skip for v1?
4. Should M6 (high-engagement analysis) and M8 (quick responses) be in the MVP?
5. Pricing model: per seat, per connected account, or per usage tier?
6. Default TOFU/MOFU/BOFU ratio and weekly posting cadence?
7. Is the reference infographic's framework to be used as-is, or branded and extended?
8. Existing brand, design or technical constraints for this repository?
9. Python or JS (Node) for the scripts and backend? Python is a natural fit for ingestion and data work; Node keeps one language with the Next.js frontend.
10. Where do the scheduled scripts run (managed cron/queue, serverless scheduler, or a worker on your own server)?
11. Which LLM provider and model tiers for research tasks, and should there be a per-user daily AI budget?

## 16. Approval

| Role | Name | Decision | Date |
|---|---|---|---|
| Product owner | | | |
| Technical lead | | | |
| Stakeholder | | | |
