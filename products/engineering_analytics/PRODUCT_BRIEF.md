# engineering_analytics — Product Brief

> **Purpose of this document.** This is the **alignment doc**, not the engineering spec. SPEC.md is the technical contract. This file exists so we converge on _what the product is_ before we argue about how to build it.
>
> **How to read.** `[!LOCKED]` = settled, don't re-litigate. `[!OPEN]` = needs a decision, has a default + counter-claim, annotate to pick a side. `[!RISK]` = load-bearing assumption; if it's wrong, the plan breaks.
>
> **Owner.** team-devex. **Status.** Aligned. **Sibling doc.** [SPEC.md](./SPEC.md).

---

## 1. One-paragraph pitch

A PostHog product that lights up the dark middle of PostHog's own AI-to-prod lifecycle — the CI, code-review, merge, and deploy steps between PostHog Code (the agent that generates code and opens PRs) and PostHog product analytics (the suite that observes the running app). Built around the open PR as the unit of value. The primary surface is MCP tools served to two consumer classes: human-driven agents (a PostHog engineer asking Claude Code) and agent-driven agents (PostHog Code autonomously reading signals to act on its own PRs). We dogfood on PostHog/posthog from day one.

## 1.1 The two motivations

> [!LOCKED] **There are two reasons to build this product, not one. Both must be served by every design decision.**

### Motivation A — DevEx dogfood

Internal team-devex tooling. The open PR is the unit of value. team-devex uses this product on `PostHog/posthog` to answer real questions about its own monorepo — what's slow in CI, where PRs are getting stuck, what's getting better or worse over time. Same way PostHog product analytics is used by web engineers to answer questions about their app.

### Motivation B — Close the dark middle of PostHog's AI-to-prod loop

```text
PostHog Code              engineering_analytics              PostHog product analytics
(generates code,      →   ( CI / review / merge / deploy )  →   ( events, errors, flags,
 opens PRs)               THE DARK MIDDLE, BECOMING LIGHT        surveys, replays )
        ↑                                                                │
        └────────────  feedback loop: signals to PostHog Code  ──────────┘
```

PostHog already has the start of the loop (Code) and the end of the loop (product analytics). The middle — what happens to AI-generated code between "PR opened" and "running in production" — is invisible today. engineering_analytics instruments it. The signals it produces feed back to PostHog Code so the agent learns from the lifecycle of its own work: which CI job failed, which test is flaky, why the last PR took four hours to merge, whether the change it shipped actually moved the metric it was trying to move.

> [!RISK] **Motivation B is the bigger product story but the harder one to deliver.** The initial product surface ships only data and tools usable by Motivation A. The "PostHog Code consumes engineering_analytics signals" piece lands when PostHog Code adopts the MCP tools (separate workstream, separate team). Designing for it now means making tool descriptions and return shapes legible to an autonomous agent, not just a human asking questions.

---

## 2. Persona

> [!LOCKED] **Primary consumer:** a PostHog engineer using agentic tooling.
> [!LOCKED] **Secondary consumer:** PostHog Code itself, calling MCP tools programmatically to inform its own work.

### 2.1 Primary: human-driven agent use

- A PostHog engineer in Claude Code, Cursor, or the PostHog AI Slack surface.
- Occasionally peeks at the UI because PostHog's design system makes data tangible for show-and-tell.
- Same shape as the eventual external customer (an engineer at another engineering org). Dogfooding isn't a phase — it's the canonical use case. _Same way PostHog product-analytics users want to understand their web app's customer behaviors; we want to understand the monorepo's engineer behaviors._

### 2.2 Secondary: agent-driven autonomous use

- PostHog Code, calling these MCP tools without a human in the loop to:
  - Diagnose why one of its own PRs is stuck ("which CI job failed, and is it flaky?")
  - Decide whether to retry, rebase, or escalate
  - Compare its own PR throughput / cycle time to baseline
  - Read deploy + downstream-impact signals to learn whether the code it shipped actually worked
- Implication for design: tool descriptions and return shapes must be **legible to an autonomous agent**, not just renderable in a human chat. That means structured returns with explicit confidence notes and explicit "this metric is coarse / partial / waiting on data" markers — never prose that an LLM might paraphrase wrong.

**Acceptance criterion for v1:** the team-devex maintainer invokes engineering_analytics MCP tools regularly from Claude Code (target: a handful of real sessions before declaring v1 working) to answer real DevEx questions.

---

## 3. Unit of value: the open PR

> [!LOCKED] **A PR is the atomic thing this product analyzes.** Not engineers, not file paths, not features.

PRs progress through two phases with different rigor expectations:

### 3.1 Draft phase = experimentation

- Engineer is iterating. Low-friction expectations.
- Selective tests are OK. Bots advisory. Failed CI not yet a problem to escalate.
- We track signals but do not analyze aggressively. Draft-phase noise is real and not interesting.

### 3.2 Ready-for-review phase = high stakes

- This is where engineer pain lives.
- This is where DevEx's job-to-be-done lives: grow PR confidence to merge-ready, fast.
- This is where we measure aggressively: CI duration, review latency, bot effectiveness, rebase count, unaddressed-comment count.

**DevEx's mission, restated:** _shorten the time from "ready for review" to "merged" without removing useful friction._

> [!RISK] **Distinguishing draft time from ready-for-review time requires state-transition history.** The warehouse `github_pull_requests` table holds the PR's _current_ state, not a timeline. v1 metrics will be coarse (`merged_at - created_at` = draft + ready-for-review combined) until we ingest state-transition events. Plan: ship the coarse metric, label it honestly in the tool description, fix the data path later.

---

## 4. Example questions the product should answer

The product exists to make the PR lifecycle queryable. Concrete examples of questions either a human-driven agent or PostHog Code should be able to ask:

- "Of the 10 PRs I opened recently, which ones merged, which got reverted, which are still stuck and why?"
- "The deploy that just went out bumped error rate. Which PRs were in that deploy?"
- "Which CI workflows have been slowest this week, and which product areas do they belong to?"
- "Is `products/X` getting slower or faster to land PRs against?"
- "Did the PR I just merged actually fix the issue I was trying to fix (looking at downstream PostHog events)?"

If the v1 tools answer the first three, the product is on track. The last two require data we don't have yet (deploy concept, downstream join) and land later.

---

## 5. The wedge: end-to-end code visibility

> [!LOCKED] **PostHog should be able to track code from when it's written, through CI and review, into production — and expose that lifecycle as MCP tools consumable by agents and engineers alike.**

PostHog already has the **upstream**: PostHog Code generates code and opens PRs.
PostHog already has the **downstream**: PostHog product analytics observes the running app — events, errors, flag exposures, surveys, replays.
The **middle** — what happens to that code in CI, review, merge, deploy — is invisible to both ends today.

engineering_analytics is the middle. It surfaces the lifecycle of every PR (and the CI workflows attached to it) as queryable PostHog data, served as MCP tools to two kinds of consumers:

- **PostHog Code**, autonomously, calling tools to act on its own work — diagnose why its PR is stuck, decide whether to retry, eventually see how its merged changes behaved in production.
- **Engineers using PostHog MCP** (Claude Code / Cursor / PostHog AI), asking the same kinds of questions about their own monorepo — internally on `PostHog/posthog`, externally for any team using PostHog MCP with a connected GitHub data source.

The differentiator is the **full lifecycle in one query language (HogQL), served through one surface (MCP), accessible to both humans and autonomous agents**.

> [!RISK] **End-to-end coverage takes time to build.** v1 covers the PR + CI workflow data we already have. Review events (`pull_request_reviews`), state transitions (draft / ready-for-review), and the deploy join to PostHog product analytics all land later. The v1 product is a partial wedge; the full one is the multi-PR target.

---

## 6. v1 scope — what we ship

Constrained by data we have today: `github_pull_requests` already syncing, `github_workflow_runs` landing in the in-flight workflow_runs PR.

### Ship now

| Tool                                      | Source                 | What it answers                                                                                                                                                                                                                                                                                               |
| ----------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `slowest_workflows(window, repo?)`        | `github_workflow_runs` | Which CI workflows are the long-poles right now                                                                                                                                                                                                                                                               |
| `time_to_merge(window, paths?, authors?)` | `github_pull_requests` | `merged_at - created_at` — total open time from PR open (including draft) to merge, grouped by path or author. Tool description and return field mark this explicitly as combined draft + ready-for-review time. A precise companion (ready-for-review-to-merge only) lands once state-transition data exists |
| `pr_throughput(window, paths?, authors?)` | `github_pull_requests` | PR counts, with cohort splits                                                                                                                                                                                                                                                                                 |
| `pr_lifecycle(pr_number)`                 | both                   | PR header + CI workflow timeline. Reviews and comments deferred until reviews data lands                                                                                                                                                                                                                      |

The "CI" tool operates at **workflow level**, not job level. Job-level breakdown (which step inside a workflow took the time) is a later add — would require a new `github_workflow_jobs` warehouse endpoint.

### Defer

| Tool                                                          | Blocker                                                    |
| ------------------------------------------------------------- | ---------------------------------------------------------- |
| `bot_review_impact(bot, window)` (wedge POC for Motivation A) | `pull_request_reviews` warehouse source                    |
| `pr_to_impact(pr_number)` (wedge POC for Motivation B)        | Deploy concept + join to PostHog product events. Beyond v1 |
| `time_in_phase(window)`                                       | PR state-transition history                                |
| `pr_confidence(pr_number)`                                    | Composite, needs reviews + state-transition data           |

### UI

One read-only scene showing the output of `slowest_workflows` — a horizontal bar chart of slowest workflows over the last 7 days, sorted longest-first, with workflow name + median duration + run count. PostHog design system showcase. No filters, no kea forms, no saved views. Demo surface only.

### Dual-consumer check

Each tool must be legible to **both** consumer classes (human-driven and agent-driven):

| Tool                | Human use                                           | Agent-driven use                                                      |
| ------------------- | --------------------------------------------------- | --------------------------------------------------------------------- |
| `slowest_workflows` | "what's the long pole today?"                       | PostHog Code: "is my PR being held up by a known long-pole workflow?" |
| `time_to_merge`     | "how long are PRs sitting against my product area?" | PostHog Code: "is my PR throughput in line with baseline?"            |
| `pr_throughput`     | "are we shipping more or less than before?"         | PostHog Code: "did my latest run of PRs land or stall?"               |
| `pr_lifecycle`      | "where is this PR stuck?"                           | PostHog Code: "where is my PR stuck, and what should I do next?"      |

Tool return shapes are typed Python (pydantic / dataclasses) following repo conventions, with explicit "this metric is coarse" or "this metric is precise" markers as fields — not free-form prose — so an autonomous agent can act on the result without paraphrasing.

---

## 7. Data path: warehouse for v1, events later

> [!LOCKED] **v1 data path: HogQL on `github_pull_requests` + `github_workflow_runs`.** No event ingestion, no PR-as-group-type, no webhook receiver in v1.

The more PostHog-native version of the product (PRs as group type, lifecycle as events) is the right long-term shape but is not on the immediate path. It enables funnel / retention / experiment tooling on PRs natively and unlocks state-transition timing, but it requires designing an event schema we haven't designed yet.

**Note on webhook ingestion (verified, not yet adopted).** The warehouse source framework already supports webhook ingestion (gated behind the `warehouse-source-webhooks` feature flag). Two sources use it today: `customer_io` and `slack`. The shared machinery lands in `posthog/temporal/data_imports/sources/common/webhook_s3.py` — payloads land in S3 then flow through the normal pipeline. When we promote engineering_analytics to event-style ingestion, it's an **extension to the existing GitHub source**, not a separate service we have to stand up. One less unknown to design around when we get there.

---

## 8. Dogfood plan

> [!LOCKED] **Dogfooder:** team-devex, internal use on `PostHog/posthog`.

**Question categories the dogfooder asks:**

- "What's the long pole in CI on `PostHog/posthog` right now?"
- "Is `products/X` getting slower or faster to land PRs against?"
- "Is there a CI workflow that's broken or flaky and needs attention?"

**Ritual:** ask one of these in Claude Code regularly. Note when the tool fails to answer. Each failure is the next PR.

---

## 9. Decisions made during alignment

These were open questions; this section records how each was resolved and why, in case a future reader wants the trail.

| Question                                                                      | Decision                                                                    | Reason                                                                                                               |
| ----------------------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Distinguishing draft from ready-for-review time without state-transition data | Ship coarse `merged_at - created_at`; label as combined in tool description | Per-PR GitHub API scraping is slow and doesn't scale; fix the data path later, not the metric                        |
| Bot identification                                                            | Handle suffix `[bot]` + small hardcoded allowlist (e.g. `posthog-bot`)      | Catches every GitHub App auto-suffix; new bots = one-line code change. No team-level config until somebody asks      |
| First UI scene                                                                | One chart: slowest workflows over last 7 days                               | One tight demo beats two competing charts; cycle-time visual comes when its tool is live                             |
| Privacy guardrails                                                            | None for now                                                                | Not a spying product; the only current consumer is the team-devex maintainer. Revisit if scope widens                |
| CI granularity                                                                | Workflow level via `github_workflow_runs`                                   | Already-ingested data; job-level would need a new warehouse endpoint and isn't required for the first useful answers |
| `pull_request_reviews` data                                                   | Defer until building the bot-impact wedge tool                              | Heaviest warehouse endpoint of the three options (per-PR fan-out); not needed for the v1 tools                       |
| Event ingestion timing                                                        | Defer; stay on warehouse polling                                            | Polling cadence is fine for the questions we ask first. Webhook path is in the framework already if needed later     |
| Tool return shapes                                                            | Typed pydantic / dataclasses, with coarse/precise markers as fields         | Repo convention + secondary-consumer (PostHog Code) needs structure, not prose                                       |

---

## 10. Locked decisions

If you want to change one, do it in a separate PR with a written reason.

- `[!LOCKED]` Two motivations: (A) DevEx dogfood, (B) close the dark middle in PostHog's AI-to-prod loop.
- `[!LOCKED]` Two consumer classes for MCP tools: human-driven agents (primary) and agent-driven agents like PostHog Code (secondary, designed-for-now).
- `[!LOCKED]` Tool return shapes follow repo conventions — typed Python (pydantic / dataclasses), with explicit "this metric is coarse" or "this metric is precise" markers as fields. Not free-form prose.
- `[!LOCKED]` Persona (human side) = PostHog engineer using agents.
- `[!LOCKED]` Unit of value = the open PR.
- `[!LOCKED]` Phase model: draft (experimentation) vs ready-for-review (high-stakes).
- `[!LOCKED]` North star: shorten ready-for-review-to-merge without removing useful friction.
- `[!LOCKED]` Wedge = end-to-end code visibility. PostHog tracks code from when it's written, through CI and review, into production, served as MCP tools to PostHog Code (autonomous) and to engineers using PostHog MCP (human-driven).
- `[!LOCKED]` Validation UI = demo surface. Read-only. Capped at the design-system showcase.
- `[!LOCKED]` v1 data path = HogQL on warehouse. Event ingestion deferred.
- `[!LOCKED]` Saved state lives in agent memory, not a Postgres `SavedView` table.
- `[!LOCKED]` Postgres deferred indefinitely for this product. Product DB stays empty.
- `[!LOCKED]` Author identity = `Author{handle, display_name, avatar_url, is_bot}`. No PostHog-user mapping in v1.
- `[!LOCKED]` Bots excluded by default in PR-listing tools; bots are **first-class** in bot-impact analysis (don't strip them everywhere).
- `[!LOCKED]` Drafts excluded by default in throughput / cycle-time tools.
- `[!LOCKED]` `time_to_merge` v1 = `merged_at - created_at` (PR open to merge, draft + ready-for-review combined). Documented as coarse on the tool return shape.
- `[!LOCKED]` Repo scope = `list[RepoRef]` always.
- `[!LOCKED]` Bot identification = handle suffix `[bot]` + hardcoded allowlist (e.g. `posthog-bot`).
- `[!LOCKED]` CI granularity = workflow level (`github_workflow_runs`). Job-level is a later add.
- `[!LOCKED]` `pull_request_reviews` warehouse source = deferred until wedge tool is built.
- `[!LOCKED]` No privacy guardrails in v1; revisit if scope widens beyond the team-devex maintainer.
- `[!LOCKED]` Each PR independently mergeable. Bottom must land before next opens for review. Draft-only by default.

---

## 11. PR ordering

Vertical slices. Draft-only by default. Each independently mergeable. No date commitments — ordering only.

| Step | PR                                                                                                                                          | Output                                               |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| 1    | #58888 (existing draft): scaffold + SPEC.md + this BRIEF                                                                                    | One source of truth                                  |
| 2    | #58890 (existing, ready for review): `github_workflow_runs` data source                                                                     | CI data ingested                                     |
| 3    | New: `slowest_workflows` + `time_to_merge` + `pr_throughput` + `pr_lifecycle` MCP tools — HogQL → facade → DRF → MCP, single vertical slice | First useful MCP tools                               |
| 4    | New: one read-only UI scene for `slowest_workflows`                                                                                         | Demo surface                                         |
| 5    | New (parallel, not on the critical path): open `pull_request_reviews` warehouse source PR                                                   | Unblocks the wedge tool when we're ready to build it |

---

## 12. Antibodies from prior attempts

Third attempt at this surface. Two prior stacks died at the bottom of bundled PR ropes (#51818/#51820/#51824, #55316–#55322). Encoded antibodies:

1. Each PR independently mergeable — no rope.
2. PR 1 ships zero business logic. Just structure + this brief + SPEC.md.
3. Vertical slices, not horizontal layers — each feature PR delivers HogQL → facade → DRF → MCP.
4. Draft-only by default — reviewer attention is the rate limit.
5. Salvageable nuggets > rope — single PRs land standalone if a stack stalls.

---

## 13. Glossary

| Term                       | Definition                                                                                                                                                                      |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **PR (unit of value)**     | An open GitHub pull request, draft or ready-for-review, the atomic thing this product measures                                                                                  |
| **Draft phase**            | Experimentation. Low-rigor measurement. Selective tests + advisory bots are OK                                                                                                  |
| **Ready-for-review phase** | High-stakes. Where DevEx measures aggressively                                                                                                                                  |
| **Good friction**          | Tests / bots / checks that catch real problems. Kept and optimized                                                                                                              |
| **Bad friction**           | Tests / bots / checks that engineers ignore or that fail for unrelated reasons. Removed                                                                                         |
| **Wedge**                  | End-to-end code visibility: PostHog tracks code from written → CI / review → live, served via MCP to PostHog Code and to engineers using PostHog MCP                            |
| **MCP tool**               | Function the agent calls. Description is a production prompt                                                                                                                    |
| **Surface**                | Primary = MCP tools; secondary = read-only demo UI                                                                                                                              |
| **Human-driven agent**     | Claude Code / Cursor / PostHog AI invoked by an engineer typing                                                                                                                 |
| **Agent-driven agent**     | An autonomous agent (e.g. PostHog Code) invoking MCP tools without a human in the loop                                                                                          |
| **The AI-to-prod loop**    | PostHog Code → engineering_analytics (this product) → PostHog product analytics → feedback to PostHog Code. The full lifecycle of agent-generated code, instrumented end to end |
| **The dark middle**        | The CI / review / merge / deploy steps between PostHog Code and PostHog product analytics, currently invisible to both                                                          |
| **`time_to_merge` (v1)**   | `merged_at - created_at`. PR open to merge — combines draft + ready-for-review until state-transition data lands. Tool return field marks it as coarse                          |
| **Workflow**               | A GitHub Actions workflow run on a PR's head commit. One row in `github_workflow_runs`. v1 CI granularity. Job-level breakdown is a later add                                   |
| **Bot**                    | An `Author` with `is_bot = True`. Detection: `handle.endswith("[bot]") OR handle in KNOWN_BOT_HANDLES`                                                                          |

---

## 14. What this doc is not

- Not the engineering spec — that's SPEC.md.
- Not a roadmap with dates. Ordering, not scheduling.
- Not sales narrative.
- Resolved questions stay in §9 as a record; new questions can be appended.
