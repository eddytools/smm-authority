# SMM Authority — Project Scope Document

| | |
|---|---|
| **Status** | Draft v0.1 for review |
| **Date** | 2026-10-16 |
| **Owner** | eddytools |

> Assumptions are marked **[A]** and open questions **[Q]**. Confirm or correct these before build starts.

---

## 1. Purpose

SMM Authority is a web app that guides a prospect (a founder, consultant, coach, or small-business owner) from "no clear online presence" to "recognised voice in their niche." It does this by diagnosing where they stand, producing a positioning and content plan, helping them create and schedule content, and measuring authority growth over time.

The core promise: **a prospect can sign up and, within one session, see their authority score, a defined niche position, and a 30-day action plan.**

## 2. Problem Statement

Prospects who want to build authority online usually fail for the same reasons:

- No defined positioning, so content is generic and forgettable.
- Inconsistent posting across channels.
- No visibility into what builds credibility (mentions, backlinks, engagement from the right people).
- Time and skill limits for producing quality content.
- No way to tell whether the effort is working.

## 3. Target Users

| Persona | Description | Primary need |
|---|---|---|
| **Prospect (primary)** | Solo expert or small-business owner, 1–10 people, limited marketing time | Clear plan, fast content, visible progress |
| **Agency/consultant (secondary)** **[A]** | Runs the app on behalf of several prospects | Multi-client management, white-label reports |
| **Admin** | Internal operator | User management, billing, content/template management |

**[Q]** Is the first release for self-serve prospects only, or is an agency/multi-client mode required for v1?

## 4. Goals and Success Metrics

| Goal | Metric | Target (first 90 days post-launch) |
|---|---|---|
| Fast time-to-value | Signup → first Authority Report | < 10 minutes median |
| Activation | Users who approve a content plan | ≥ 50% of signups |
| Habit | Users publishing/scheduling ≥ 3 posts/week by week 4 | ≥ 35% of activated users |
| Outcome | Average Authority Score lift after 60 days | ≥ +15 points |
| Retention | Month-2 paid retention | ≥ 60% |

## 5. Scope Overview

### 5.1 In Scope — MVP (Phase 1)

**A. Onboarding and Profile**
- Account creation (email + Google/LinkedIn sign-in).
- Guided intake: niche, audience, offer, goals, tone of voice, existing channel links, competitors/peers.

**B. Authority Audit and Score**
- Connect or enter public profiles (LinkedIn, X, Instagram, YouTube, website) **[A]** via public data/OAuth where available.
- Authority Score (0–100) built from sub-scores:
  - Profile completeness and consistency
  - Content consistency and depth
  - Engagement quality
  - Search presence (branded search, ranking pages)
  - Third-party credibility (mentions, backlinks, testimonials)
- Competitor/peer benchmark (up to 3 peers).
- Prioritised gap list with plain-language explanations.

**C. Positioning Builder**
- AI-assisted niche statement, value proposition, and 3–5 content pillars.
- Bio/headline generator per platform.
- User edits and approves; the result becomes the "Authority Brief" that drives all later generation.

**D. Content Strategy and Calendar**
- 30-day plan generated from pillars (post ideas, formats, cadence).
- Drag-and-drop calendar.
- Content idea bank with topic suggestions from search/keyword data.

**E. Content Creation Studio**
- AI draft generation per platform (LinkedIn post, X thread, Instagram caption, short-video script, long-form article outline).
- Brand-voice control using the Authority Brief and user writing samples.
- Edit, regenerate, and approve flow. **Human approval is required before anything is published.**
- Basic image/carousel template support **[A]** via template library, not full design tool.

**F. Publishing and Scheduling**
- Scheduling and auto-publish to LinkedIn, X, and Instagram **[A]** (subject to API availability and terms; fall back to reminders + copy-to-clipboard).

**G. Progress Dashboard**
- Authority Score trend, posting consistency, engagement, follower quality.
- Weekly email digest with next 3 recommended actions.

**H. Billing and Admin**
- Subscription plans (Free audit, Pro, Team) via Stripe.
- Admin console: users, plans, templates, usage and cost monitoring.

### 5.2 Phase 2 (Planned, Not in MVP)

- Authority-building outreach: guest post / podcast / PR opportunity finder and pitch drafting.
- Backlink and brand-mention monitoring with alerts.
- Engagement assistant: suggested comments and replies on relevant people's posts (human-approved).
- Multi-client agency workspace with white-label PDF reports.
- Testimonial and case-study collection workflow.
- Newsletter and blog publishing (WordPress/Substack integration).
- Video repurposing (long-form to clips).

### 5.3 Out of Scope

- Fully autonomous posting or commenting without user approval.
- Buying followers, engagement pods, fake reviews, or any platform-policy-violating growth tactic.
- Paid ads management.
- A full graphic/video editor.
- Native mobile apps (responsive web only for v1).
- CRM, email marketing platform, or lead-gen features.
- Ghostwriting by human staff.

## 6. Key User Journey (MVP)

1. Sign up → complete 5-minute intake.
2. Receive Authority Report (score, benchmark, top gaps).
3. Review and approve positioning and content pillars.
4. Receive the 30-day calendar → approve or edit.
5. Generate and edit drafts → schedule/publish.
6. Check weekly dashboard and digest → adjust plan.

## 7. Functional Requirements (Summary)

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Users can create accounts and complete a guided intake | Must |
| FR-2 | System computes an Authority Score with explainable sub-scores | Must |
| FR-3 | System benchmarks the user against up to 3 peers | Should |
| FR-4 | System generates positioning, pillars, and platform bios | Must |
| FR-5 | System generates a 30-day content calendar | Must |
| FR-6 | System drafts platform-specific content in the user's voice | Must |
| FR-7 | Users must approve content before it is published | Must |
| FR-8 | Users can schedule/publish to at least LinkedIn and X | Must |
| FR-9 | Dashboard shows score trend and consistency metrics | Must |
| FR-10 | Weekly digest email with next actions | Should |
| FR-11 | Subscription billing and plan limits | Must |
| FR-12 | Admin console for users, plans, and usage | Should |
| FR-13 | Export report as PDF | Could |

## 8. Non-Functional Requirements

- **Performance:** Authority Report generated in under 2 minutes; UI interactions under 300 ms.
- **Security and privacy:** OAuth tokens encrypted at rest; least-privilege scopes; GDPR-style data export and deletion; no use of user content to train third-party models.
- **Reliability:** Scheduled posts retried on failure with user notification; 99.5% uptime target.
- **Compliance:** Respect each platform's API terms and rate limits; disclose AI-generated content where required.
- **Cost control:** Per-user LLM and data-API budgets, with usage caps per plan.
- **Accessibility:** WCAG 2.1 AA for core flows.

## 9. Proposed Architecture (High Level) **[A]**

- **Frontend:** React/Next.js web app.
- **Backend:** API service with a job queue for audits, generation, and publishing.
- **AI layer:** LLM for positioning/content generation with retrieval over the user's Authority Brief and writing samples; prompt and output guardrails; evaluation set for quality.
- **Data:** Postgres (users, briefs, calendar, scores); object storage for assets.
- **Integrations:** LinkedIn, X, Instagram APIs; SEO/keyword and backlink data provider; Stripe; transactional email; Google OAuth.

**[Q]** Any required stack, hosting, or existing codebase to align with? (The repository is currently empty.)

## 10. Data Sources for Authority Score

| Signal | Source | Risk |
|---|---|---|
| Profile completeness | Platform APIs / user input | Limited API access |
| Posting cadence and engagement | Platform APIs | API restrictions, rate limits |
| Search presence and rankings | SEO data provider (e.g. Search Console / keyword APIs) | Cost per query |
| Backlinks and mentions | Backlink data provider | Cost, coverage |
| Testimonials/reviews | User-provided links | Manual entry |

The score formula and weights must be documented and shown to the user. Scores are directional, not a guarantee of outcomes.

## 11. Delivery Plan

| Milestone | Contents | Estimate |
|---|---|---|
| M0 — Discovery | Confirm scope, personas, score model, tech choices, API access | 1–2 weeks |
| M1 — Foundation | Auth, intake, data model, billing skeleton, design system | 3 weeks |
| M2 — Audit and Score | Data connectors, scoring engine, report UI | 3–4 weeks |
| M3 — Positioning and Strategy | Authority Brief, pillars, 30-day calendar | 3 weeks |
| M4 — Creation and Publishing | Drafting studio, approval flow, scheduling, publishing | 4 weeks |
| M5 — Dashboard and Digest | Progress tracking, weekly email, admin console | 2–3 weeks |
| M6 — Beta and Hardening | Closed beta (15–30 users), QA, security review, cost tuning | 3 weeks |

Estimated MVP duration: **~19–22 weeks** with a small team (2 full-stack engineers, 1 designer part-time, 1 product owner/QA). **[A]** Estimates to be refined after M0.

## 12. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Social platform API limits or policy changes | Core publishing/analytics break | Abstract connectors; support manual-publish fallback; prioritise LinkedIn/X first |
| Authority Score seen as arbitrary | Low trust | Transparent sub-scores, explanations, and documented method |
| Generic, "AI-sounding" content | Weak results, churn | Voice samples, Authority Brief grounding, edit-first UX, quality evals |
| LLM and data-API costs exceed pricing | Margin loss | Usage caps, caching, model tiering |
| Policy or reputational risk from automation | Account bans | Human approval, rate limiting, no engagement manipulation |
| Scope creep into Phase 2 features | Delays | Hold the MVP boundary in section 5; log requests to the backlog |

## 13. Assumptions and Dependencies

- Access to LinkedIn, X, and Instagram developer programmes is obtainable within M0–M1.
- An SEO/backlink data provider is selected and budgeted.
- Prospects are English-speaking in v1; localisation is deferred.
- Legal review of terms, privacy policy, and AI-content disclosure is completed before beta.

## 14. Open Questions

1. Who is the paying customer: the prospect directly, or an agency serving prospects?
2. Which platforms are must-have for launch versus nice-to-have?
3. Pricing model (per seat, per profile, or per content volume)?
4. Is there existing brand, design, or technical direction for this repo?
5. Is a done-for-you service layer planned alongside the software?

## 15. Approval

| Role | Name | Decision | Date |
|---|---|---|---|
| Product owner | | | |
| Technical lead | | | |
| Stakeholder | | | |
