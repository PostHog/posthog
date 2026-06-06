# Engineering analytics

Owner: team-devex. Engineering contract: [SPEC.md](./SPEC.md).

## The one-sentence version

**It's product analytics, but the "users" are pull requests and the "events" are what happens to them on the way to production.**

Everything else is mechanics.

## The analogy

If you understand PostHog product analytics, you understand this. Map it one-to-one:

| Product analytics                        | Engineering analytics                          |
| ---------------------------------------- | ---------------------------------------------- |
| A **person** does things in your app     | A **PR** moves through your pipeline           |
| Events: `pageview`, `signup`, `purchase` | Events: `opened`, `ready_for_review`, `merged` |
| "How long from signup to purchase?"      | "How long from opened to merged?"              |
| "What % of signups convert?" (funnel)    | "What % of PRs make it to prod?" (funnel)      |
| "Is conversion getting better?" (trend)  | "Is CI getting faster?" (trend)                |
| Segment by country, plan, browser        | Segment by repo, author, file path             |

Same product, different noun.

## The shape of the thing

```text
A PR's life, as a stream of timestamped events:

opened ──> ready_for_review ──> ci_passed ──> approved ──> merged ──> deployed
  │              │                  │            │           │           │
t=0          t=2h              t=2h15m        t=4h        t=4h30m      t=5h

Engineering analytics measures every gap:
  opened→ready     = how long it sat as a draft
  ready→merged     = THE NORTH STAR (shorten this)
  any→ci_passed    = how long CI took to go green
  merged→deployed  = ship latency

Then averages each gap across all PRs, and trends it over weeks.
DevEx's job: watch those gaps shrink.
```

The product is: **measure every gap in a PR's life, average it, and watch it shrink.**

## A moment of use

The primary surface is MCP tools. You're in Claude Code and you ask:

> "Is CI getting faster or slower on posthog/posthog over the last 8 weeks?"

A tool runs HogQL over the PR/CI data and answers:

> CI time-to-green: median dropped from 14m to 9m over 8 weeks (good). But p95 rose
> from 31m to 47m — a long tail of PRs is getting stuck. Worst offender is the
> `e2e-playwright` workflow on `products/web_analytics`. Want the slow PRs?

That grounded, trended, segmented answer **is the product.** The read-only UI is just a prettier rendering of the same data for show-and-tell.

## Why this exists

PostHog already has the two ends of its own AI-to-prod loop:

```text
PostHog Code              engineering_analytics            PostHog product analytics
(generates code,      →   (CI / review / merge / deploy) →  (events, errors, flags,
 opens PRs)                                                  surveys, replays)
        ↑                                                            │
        └───────────  signals feed back to PostHog Code  ───────────┘
```

The middle — what happens to code between "PR opened" and "running in production" — is invisible to both ends today. Engineering analytics fills it, serving two consumers with the same tools:

- **Engineers** driving an agent (Claude Code, Cursor, PostHog AI) asking about their monorepo. We dogfood on `PostHog/posthog` from day one.
- **PostHog Code** itself, autonomously, calling the same tools on its own PRs — to diagnose why a PR is stuck, decide whether to retry, and eventually see how a merged change behaved in production.

Tool return shapes must be legible to an autonomous agent, not just renderable in chat: typed contracts with explicit `metric_quality` markers, never prose an LLM might paraphrase wrong.

## v1 vs the destination

The specs read as cautious ("coarse", "deferred", "later") because they're written around a **data-availability constraint**, not the product. Strip the constraint and it's simple:

- **Destination:** every PR is a stream of lifecycle events. Every gap is measurable and trendable. Ask any question in natural language; get a grounded answer. Funnels, retention, cohorts — all PostHog tooling — on PRs.
- **v1 (ships first):** only the gaps measurable from today's snapshot warehouse data — total open time, CI duration. Honest, partial, useful immediately.

The gap between them is **just data ingestion** (the path from warehouse snapshots to lifecycle events). v1 lives on HogQL over `github_pull_requests` + `github_workflow_runs`; no event ingestion, no PR-as-group-type, no webhook receiver yet.

## Locked decisions

Change one only in a separate PR with a written reason. Engineering-level decisions live in [SPEC.md](./SPEC.md) → Locked decisions.

- Two motivations: (A) DevEx dogfood, (B) close the dark middle in PostHog's AI-to-prod loop. Both must be served by every design decision.
- Two consumer classes: human-driven agents (primary) and agent-driven agents like PostHog Code (secondary, designed-for-now).
- Unit of value = the open PR.
- Phase model: draft (experimentation, low rigor) vs ready-for-review (high stakes).
- North star: shorten ready-for-review-to-merge without removing useful friction.
- Wedge = end-to-end code visibility, served as MCP tools to PostHog Code (autonomous) and engineers using PostHog MCP (human-driven).
- Tool return shapes = typed Python (pydantic / dataclasses) with explicit `metric_quality` markers (`precise | coarse | partial`). Not free-form prose.
- Validation UI = demo surface. Read-only. Capped at the design-system showcase. No saved views — saved state lives in agent memory, not Postgres.
- v1 data path = HogQL on warehouse. Event ingestion deferred. Product Postgres DB stays empty.
- Author identity = `Author{handle, display_name, avatar_url, is_bot}`. No PostHog-user mapping in v1.
- Bots and drafts excluded by default in throughput / cycle-time tools; bots are first-class in bot-impact analysis (don't strip them everywhere).
- Bot detection = `handle.endswith("[bot]") OR handle in KNOWN_BOT_HANDLES`. Hardcoded allowlist for v1.
- `time_to_merge` v1 = `merged_at - created_at` (draft + ready-for-review combined), marked coarse on the return shape.
- CI granularity = workflow level (`github_workflow_runs`). Job-level is a later add.
- `pull_request_reviews` warehouse source deferred until the wedge tool is built.
- No privacy guardrails in v1; revisit if scope widens beyond the team-devex maintainer.

## Glossary

| Term                       | Definition                                                                                                                                            |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **PR (unit of value)**     | An open GitHub pull request, draft or ready-for-review — the atomic thing this product measures                                                       |
| **Draft phase**            | Experimentation. Low-rigor measurement. Selective tests + advisory bots are OK                                                                        |
| **Ready-for-review phase** | High-stakes. Where DevEx measures aggressively                                                                                                        |
| **Good friction**          | Tests / bots / checks that catch real problems. Kept and optimized                                                                                    |
| **Bad friction**           | Tests / bots / checks that engineers ignore or that fail for unrelated reasons. Removed                                                               |
| **Wedge**                  | End-to-end code visibility: code tracked from written → CI / review → live, served via MCP to PostHog Code and engineers using PostHog MCP            |
| **MCP tool**               | A function the agent calls. Its description is a production prompt                                                                                    |
| **Surface**                | Primary = MCP tools; secondary = read-only demo UI                                                                                                    |
| **Human-driven agent**     | Claude Code / Cursor / PostHog AI invoked by an engineer typing                                                                                       |
| **Agent-driven agent**     | An autonomous agent (e.g. PostHog Code) invoking MCP tools without a human in the loop                                                                |
| **The AI-to-prod loop**    | PostHog Code → engineering_analytics → PostHog product analytics → feedback to PostHog Code. The full lifecycle of agent-generated code, instrumented |
| **The dark middle**        | The CI / review / merge / deploy steps between PostHog Code and PostHog product analytics, currently invisible to both                                |
| **`time_to_merge` (v1)**   | `merged_at - created_at`. PR open to merge — combines draft + ready-for-review until state-transition data lands. Marked coarse on the return shape   |
| **Workflow**               | A GitHub Actions workflow run on a PR's head commit. One row in `github_workflow_runs`. v1 CI granularity; job-level is a later add                   |
| **Bot**                    | An `Author` with `is_bot = True`. Detection: `handle.endswith("[bot]") OR handle in KNOWN_BOT_HANDLES`                                                |
