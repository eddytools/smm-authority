# SMM Authority — Product Requirements Document (PRD)

| | |
|---|---|
| **Status** | Draft v1.0 for review |
| **Date** | 2026-10-17 |
| **Owner** | eddytools |
| **Related** | [`SCOPE.md`](./SCOPE.md) (v0.3) |

> **[A]** = assumption, **[Q]** = open question. Open questions are collected in section 15.

---

## 1. Summary

SMM Authority is a multi-tenant SaaS that helps prospects (founders, consultants, coaches, B2B owners) **build online authority, grow their brand, and convert attention into leads**. After a one-time setup, it researches what the user's niche is discussing, suggests what to post, builds a weekly and monthly content calendar on a TOFU / MOFU / BOFU funnel, and measures what worked.

**Execution principle:** recurring tasks (ingestion, filtering, metrics, ranking, scheduling, publishing, digests) are plain **Python/JS scripts**. **AI APIs** are used only for research and judgment (ICP scoring, summaries, pattern extraction, suggestions, drafts, insights).

## 2. Background and Problem

Prospects who want authority online struggle because:

1. They don't know what to post, so they post inconsistently or generically.
2. Trend and community research is manual and scattered (Google, X, Reddit, LinkedIn, RSS).
3. Content is mostly top-of-funnel; there are no trust or selling posts, so followers don't become leads.
4. Hot conversations (a Reddit question, breaking news) are missed because replying well takes too long.
5. They can't tell which topics, formats and funnel stages produce engagement or leads.

## 3. Goals and Non-Goals

### Goals
- G1. Get a new user to a first set of ICP-grounded post suggestions in **< 15 minutes**.
- G2. Make a full **month-long, funnel-balanced content schedule** one click away.
- G3. Turn daily research into ready-to-edit drafts with minimal effort.
- G4. Close the loop: show **what worked and what didn't**, tied to leads, and use it to improve the next plan.
- G5. Keep per-user running cost low and predictable (scripts for recurring work; AI only where judgment is needed).

### Non-Goals (v1)
- Autonomous posting or commenting without human approval.
- Engagement manipulation (pods, bought followers/reviews).
- Scraping that violates platform terms; copying others' content.
- Ads management, CRM, email-marketing platform, full design/video editor.
- Native mobile apps; localisation beyond English.

## 4. Users and Personas

| Persona | Description | Key jobs |
|---|---|---|
| **Maya — Solo Expert (primary)** | Consultant/coach, 1-person business, ~3 hrs/week for marketing | Know what to post; keep a steady cadence; get inbound leads |
| **Dev — Startup Founder** | B2B SaaS founder building a personal brand | Ride trends; show product proof; drive demos |
| **Sam — Team Marketer** | Works for the founder or a small firm | Draft, review and schedule within a shared workspace |
| **Agency (later) [A]** | Manages many client workspaces | Switch workspaces, report to clients |
| **Admin** | Internal operator | Tenants, plans, source health, cost control |

## 5. Key User Journey

1. **Sign up** → create workspace → **one-time setup** (ICP, ideation, offer, voice) → Authority Brief generated.
2. **Choose platforms**; connect accounts; add sources (RSS, subreddits, keywords, influencers).
3. **Daily feed:** review trends, community heat, influencer themes, top-engagement posts.
4. **Suggestions:** accept or tweak ideas; generate drafts; approve.
5. **Plan:** generate the weekly/monthly schedule; adjust the calendar.
6. **Publish / schedule;** use quick-response for hot threads.
7. **Review:** weekly "what worked / what didn't" and lead report; re-plan.

## 6. Features and Requirements

Priority: **P0** = MVP must-have, **P1** = Phase 2, **P2** = Phase 3/later.

### 6.1 Account, Workspace and Billing — P0

| ID | Requirement |
|---|---|
| F1.1 | Sign-up/login with email + password and Google SSO. |
| F1.2 | Workspaces with roles: Owner, Editor, Viewer. |
| F1.3 | Subscription plans (Free trial, Starter, Pro, Team) with limits on connected accounts, sources, AI usage and seats; Stripe billing. |
| F1.4 | Data export and account deletion. |

**Acceptance:** a user can sign up, start a trial, invite a teammate, upgrade a plan, and see their usage against plan limits.

### 6.2 One-Time Setup and Authority Brief — P0

| ID | Requirement |
|---|---|
| F2.1 | Guided wizard capturing **ICP**: industry, company size, role, pains, goals, objections, language, where they spend time. |
| F2.2 | **Authority ideation:** niche statement, unique angle, 3–5 content pillars, proof assets (case studies, numbers, testimonials), opinions the user will take. |
| F2.3 | **Offer and funnel assets:** product/service, lead magnet(s), CTA and booking links. |
| F2.4 | **Voice:** tone sliders, do/don't list, 3+ writing samples (optional). |
| F2.5 | AI generates an **Authority Brief** from answers; user edits and approves; versioned. |
| F2.6 | Setup is one-time but fully editable later; changes re-version the brief. |

**Acceptance:** wizard completes in ≤ 10 minutes; brief is generated in < 60 seconds; every later AI call includes the active brief.

### 6.3 Platform Selection — P0

| ID | Requirement |
|---|---|
| F3.1 | User selects target platforms: LinkedIn, X, Reddit (MVP); Instagram, YouTube, blog/newsletter (later). |
| F3.2 | App recommends primary/secondary platforms from the ICP with a short reason. |
| F3.3 | Per-platform settings: cadence (posts/week), preferred formats, tone adjustments, connection status. |

### 6.4 Source Configuration — P0

| ID | Requirement |
|---|---|
| F4.1 | Add RSS feeds, subreddits, keywords/topics, and X accounts/keywords. |
| F4.2 | AI suggests starter sources from the ICP and niche. |
| F4.3 | Source health indicator (last fetch, errors). |

### 6.5 Daily Trending Topic Feed — P0

| ID | Requirement |
|---|---|
| F5.1 | Daily feed built from **Google (trends/rising queries/news), X, Reddit and RSS**, filtered to the ICP. |
| F5.2 | Scripts ingest, normalise, dedupe and apply rule-based shortlisting (keywords, recency, minimum engagement). |
| F5.3 | AI scores relevance to ICP/pillars and writes a one-line "why it matters" for shortlisted items only. |
| F5.4 | Topic clustering; each card shows source, age, engagement and relevance score. |
| F5.5 | Actions: **Save**, **Dismiss** (tunes relevance), **Make post idea**. |
| F5.6 | Feed refreshed at least daily; user sees the last-updated time. |

**Acceptance:** a configured workspace sees a feed each morning with ≥ 10 relevant items; dismissing an item reduces similar items next day; one click converts an item to a post idea.

### 6.6 Influencer and Peer Watch — P1

| ID | Requirement |
|---|---|
| F6.1 | Watchlist of influencers/communities (Reddit users/subreddits, X accounts; LinkedIn via approved route). |
| F6.2 | Summary of what watched accounts are discussing: recurring themes, new angles, posting patterns. |
| F6.3 | LinkedIn: user-captured links/pasted posts, or a licensed data provider **[Q]**; no unauthorised scraping. |

### 6.7 Community Topic Heat — P1

| ID | Requirement |
|---|---|
| F7.1 | For tracked subreddits/hashtags/groups, compute topic heat from likes/upvotes, comments and reply velocity (scripted). |
| F7.2 | Show rising / steady / fading topics and the questions the community keeps asking. |

### 6.8 High-Engagement Post Analysis — P1

| ID | Requirement |
|---|---|
| F8.1 | Rank niche posts by engagement (normalised to account size where available) via scripts. |
| F8.2 | AI breaks each top post into hook type, format, length, topic, CTA; aggregates **patterns** across posts. |
| F8.3 | Patterns inform suggestions; the app never reproduces others' text verbatim. |

### 6.9 Content Suggestion and Drafting — P0

| ID | Requirement |
|---|---|
| F9.1 | Suggestions combine feed, heat, influencer themes, engagement patterns and the Authority Brief. |
| F9.2 | Each suggestion shows: topic, angle, 2–3 hook options, platform, format, **funnel stage and post type**, pillar, rationale ("why this, why now"), source link. |
| F9.3 | One-click **draft** in the user's voice, per platform formatting; edit, regenerate with instructions, approve. |
| F9.4 | **Human approval required** before anything is scheduled or published. |
| F9.5 | Drafts include a suggested CTA tied to the user's lead magnet/offer where the post type calls for it. |

**Acceptance:** from a feed item, a user reaches an approved draft in ≤ 3 clicks plus edits; every suggestion has a funnel stage and rationale.

### 6.10 Quick-Response Assistant — P1

| ID | Requirement |
|---|---|
| F10.1 | User pastes a thread/question link or text, or picks from "questions worth answering" surfaced from tracked communities. |
| F10.2 | AI drafts a **short helpful reply** and an optional **expanded post idea** for owned channels. |
| F10.3 | Threads prioritised by engagement and recency (scripted scoring). |
| F10.4 | Replies are **not auto-posted**; community self-promotion rules are shown and CTA/link use is flagged when discouraged. |

### 6.11 Content Planning, Funnel Framework and Calendar — P0

The planner is built on the **10 post types** across three stages:

| Stage | Goal | Post types |
|---|---|---|
| **TOFU** | Growth | 1 Newsjacking · 2 Awareness · 3 Educational · 4 Spectacle |
| **MOFU** | Trust building | 5 Story · 6 Short video · 7 Lead magnet |
| **BOFU** | Selling | 8 Conversion · 9 Objection · 10 Product demo |

| ID | Requirement |
|---|---|
| F11.1 | **Weekly and monthly planner** generates a full-month schedule using code-based rules: funnel mix (default ~50/30/20 TOFU/MOFU/BOFU **[A]**), per-platform cadence, pillar coverage, stage sequencing (growth → trust → sell), best-time windows. |
| F11.2 | Reserved **reactive slots** for newsjacking and quick-response posts. |
| F11.3 | Calendar views (month, week, list); drag-and-drop; lock/swap/regenerate any slot. |
| F11.4 | Slots hold: date/time, platform, post type, funnel stage, pillar, topic source, CTA, status, owner. |
| F11.5 | **Status pipeline:** Idea → Drafted → In Review → Approved → Scheduled → Published → Analysed (also Skipped, Archived). |
| F11.6 | Auto-fill empty slots with suggestions from F9; user edits before approval. |
| F11.7 | Idea bank and reusable templates per post type. |
| F11.8 | Funnel-mix and cadence are editable; mix can be adjusted by performance data (P1). |

**Acceptance:** one click produces a 30-day plan containing all three stages and all pillars; a plan never schedules more than the platform cadence; changing a slot updates status/history.

### 6.12 Publishing and Reminders — P0 (core platforms)

| ID | Requirement |
|---|---|
| F12.1 | Scheduled auto-publish to **LinkedIn and X** (approved posts only) via official APIs **[A]**. |
| F12.2 | Reddit and any platform without write access: **reminder + copy-ready post** (manual posting). |
| F12.3 | Failed publishes are retried and surfaced to the user. |
| F12.4 | Email/in-app reminders for manual posts and pending approvals. |

### 6.13 Performance Tracking and Learning Loop — P0 (basic), P1 (advanced)

| ID | Requirement |
|---|---|
| F13.1 | Daily script collects per-post metrics (impressions, reactions, comments, shares, clicks, saves, follower change) as exposed by each platform. |
| F13.2 | Breakdowns by platform, pillar, post type, funnel stage, format, time of day. |
| F13.3 | **Lead attribution (P1):** UTM links, lead-magnet sign-ups, booking clicks, manual "lead from this post" tag. |
| F13.4 | **"What worked / what didn't"** weekly and monthly report: scripts compute stats; AI writes plain-language insights and recommended changes. |
| F13.5 | Learnings feed suggestion ranking and planner mix (P1). |

### 6.14 Dashboard, Notifications, Admin — P0/P1

| ID | Requirement |
|---|---|
| F14.1 | Home dashboard: today's feed highlights, this week's schedule, pending approvals, headline performance and lead metrics. |
| F14.2 | Weekly digest email with next three recommended actions (P1). |
| F14.3 | Admin: tenants, plans, usage and AI cost, **scheduled-job health** (last run, status, duration, error), template management. |

## 7. Execution Model (Scripts vs AI)

| Work | Executor |
|---|---|
| Fetch RSS/Reddit/X/Trends; dedupe; shortlist; metrics collection; engagement ranking; topic heat; plan skeleton; publishing; reminders; digests; token refresh; health checks | **Python/JS scripts** on a scheduler |
| Authority Brief; ICP relevance scoring; "why it matters"; pattern extraction; suggestions and hooks; drafts; quick-response replies; weekly insights | **AI API** |

Requirements:
- **R1.** Every recurring job is an idempotent script with logging, retries and health status.
- **R2.** AI sees only shortlisted items or on-demand requests; results cached by content hash.
- **R3.** All AI calls go through one wrapper: budgets per plan, JSON-schema-validated output, graceful "no AI result" fallback so script runs never fail because the model did.
- **R4.** Fixed formulas (funnel mix, cadence, slot placement, aggregation, ranking) live in code and are unit-tested.

## 8. Data Model (High Level)

| Entity | Key fields |
|---|---|
| Tenant/Workspace | id, plan, limits, settings |
| User, Membership | role, workspace |
| AuthorityBrief | ICP, niche, pillars, offer, voice, version |
| PlatformAccount | platform, OAuth tokens (encrypted), cadence, status |
| Source | type (rss/reddit/x/trends/influencer), config, health |
| RawItem | source, url, text, engagement, fetched_at, hash |
| Topic | cluster id, items, relevance score, summary, heat |
| Suggestion | topic, angle, hooks, funnel stage, post type, rationale |
| ContentPiece | draft text, platform, post type, stage, pillar, status, version |
| PlanSlot | date/time, content piece, platform, locked flag |
| Metric | content piece, date, impressions, engagement, clicks |
| Lead | content piece, source (UTM/manual), timestamp |
| JobRun | job name, status, duration, error |
| AIUsage | workspace, tokens, cost, feature |

## 9. UX Notes

- **Home:** "Today" view with feed highlights, next posts, approvals, and a "what worked" teaser.
- **Setup wizard:** step-by-step, progress bar, AI-prefilled suggestions the user edits.
- **Feed:** card list with filters (source, pillar, relevance); one-click "Make post idea."
- **Create:** split view, brief/research on the left, editor on the right, funnel stage and post-type chips.
- **Calendar:** month/week toggle, colour-coded by funnel stage (TOFU/MOFU/BOFU), status badges.
- **Insights:** charts by pillar, post type and funnel stage; "worked / didn't" cards with recommended actions.
- Responsive web; WCAG 2.1 AA for core flows.

## 10. Success Metrics

| Metric | Target (first 90 days) |
|---|---|
| Sign-up → first suggestion set | < 15 min median |
| Setup completion rate | ≥ 70% of sign-ups |
| Users approving a monthly plan | ≥ 50% of sign-ups |
| Weekly users converting ≥ 1 feed item to a post | ≥ 50% |
| Users hitting planned cadence in weeks 3–4 | ≥ 40% of activated users |
| Plans containing all three funnel stages | 100% |
| Leads attributed per active user per month | Baseline in beta, target set after |
| Month-2 paid retention | ≥ 60% |
| AI cost per active user per month | Within plan margin target [Q] |
| Scheduled job success rate | ≥ 99% |

## 11. Non-Functional Requirements

- **Freshness:** feed refreshed at least daily; community signals hourly where APIs permit.
- **Performance:** feed < 2 s load; monthly plan < 60 s; drafts < 20 s.
- **Reliability:** 99.5% uptime; failed jobs retried, surfaced in admin.
- **Security/privacy:** tenant isolation; encrypted tokens; least-privilege OAuth scopes; user content not used to train third-party models; data export/deletion.
- **Compliance:** follow platform API terms, rate limits and data retention; AI-content disclosure where required.
- **Cost:** recurring work has zero LLM cost; LLM use capped per plan and cached.
- **Quality:** scripts tested against recorded API fixtures; AI features checked with an evaluation set (relevance, voice match, factuality).

## 12. Technical Approach (Summary)

- **Frontend:** Next.js/React.
- **Backend:** Python (FastAPI) or Node **[Q]**, Postgres with vector search, object storage.
- **Scheduler and workers:** cron/queue running the script layer (ingest, filter, metrics, rank, plan, publish, digest, health).
- **AI layer:** provider-agnostic wrapper with caching, budgets, schema validation, model tiering **[Q]**.
- **Integrations:** Stripe, Google OAuth, LinkedIn/X/Reddit APIs, Google Trends/search data source, email service, UTM link tracking.

## 13. Release Plan

| Phase | Contents | Exit criteria |
|---|---|---|
| **MVP (Phase 1)** | F1, F2, F3, F4, F5, F9, F11, F12 (LinkedIn/X publish; Reddit manual), F13 (basic), F14.1/14.3, billing | Closed beta of 15–30 users completes setup, uses feed, publishes ≥ 8 posts each; job success ≥ 99% |
| **Phase 2** | F6 influencer watch, F7 topic heat, F8 high-engagement analysis, F10 quick response, lead attribution, learning loop, weekly digest | Users report suggestions improve over time; leads attributed |
| **Phase 3** | Agency multi-workspace, white-label reports, more platforms (Instagram, YouTube, newsletter), video repurposing, capture extension | Agency pilot live |

Indicative MVP timeline **~20–24 weeks** for a small team (2 full-stack engineers, 1 part-time designer, 1 product owner/QA) **[A]**; refine after discovery.

## 14. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| LinkedIn has no public read API for others' posts | Approved routes only (user capture, licensed provider); build Reddit/X/RSS first |
| X/Reddit API cost and rate limits | Cache, cap queries per plan, price tiers to usage |
| Platform policy changes | Connector abstraction; manual-publish fallback |
| Generic "AI-sounding" content | Brief grounding, voice samples, edit-first UX, evals |
| Community backlash to self-promotion | Human-in-the-loop replies, per-community rule hints, CTA warnings |
| Feed noise | ICP relevance scoring, save/dismiss tuning |
| Weak lead attribution | UTM defaults, lead-magnet tracking, manual tagging |
| LLM cost overrun | Scripts do recurring work; AI sees shortlist only; caching; caps |
| Scheduled scripts fail silently | Idempotent jobs, alerts, health dashboard, fixture tests |
| Scope creep | Hold phase boundaries |

## 15. Open Questions

1. Single-owner accounts only in v1, or agency multi-workspace?
2. Must-have launch platforms (LinkedIn, X, Reddit assumed)?
3. LinkedIn data approach: user capture, licensed provider, or skip in v1?
4. Should F8 (high-engagement analysis) and F10 (quick response) move into the MVP?
5. Pricing model: per seat, per connected account, or usage tier?
6. Default funnel ratio and weekly cadence?
7. Use the reference infographic's framework as-is, or rebrand/extend?
8. Python or Node for backend and scripts?
9. Where do scheduled scripts run (managed cron/queue, serverless, own worker)?
10. LLM provider, model tiers, and per-user daily AI budget?
11. Existing brand/design or technical constraints for this repository?

## 16. Approval

| Role | Name | Decision | Date |
|---|---|---|---|
| Product owner | | | |
| Technical lead | | | |
| Stakeholder | | | |
