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
        └───────────  Signals feed back to PostHog Code  ───────────┘
```

The middle — what happens to code between "PR opened" and "running in production" — is invisible to both ends today. Engineering analytics fills it, serving two consumers with the same tools:

- **Engineers** driving an agent (Claude Code, Cursor, PostHog AI) asking about their monorepo. We dogfood on `PostHog/posthog` from day one.
- **PostHog Code** itself, autonomously, calling the same tools on its own PRs — to diagnose why a PR is stuck, decide whether to retry, and eventually see how a merged change behaved in production.

Tool return shapes must be legible to an autonomous agent, not just renderable in chat: typed contracts whose caveats ride in honest field names and a `metric_quality` marker where load-bearing, never free-form prose an LLM might paraphrase wrong.

## Goal: surface CI Signals for PostHog Code

The product drives toward one outcome: turn the curated CI/PR read layer into
**Signals** — emitted into PostHog's [Signals](../signals) product, grouped and
researched against the repository, and, when a finding is actionable, handed to
PostHog Code for autonomous remediation. "CI slowed down on workflow X", "this PR is
wedged on a failing required check", "this check is flaky" become first-class Signals
an agent acts on — not dashboards a human has to watch.

The two read surfaces exist to serve that goal, in priority order:

1. **MCP tools — the official surface.** Engineers query the monorepo through PostHog
   MCP, and agents (including PostHog Code) call the same tools. Detection of what
   counts as a valuable CI Signal lives in `logic/` over the read layer, so the same
   definitions back the MCP tools and the Signal emitter.
2. **Read-only UI — a showcase** over the same endpoints. Useful, but secondary.

Shortening ready-for-review-to-merge is the headline _metric_ this serves; emitting
actionable CI Signals to PostHog Code is the _goal_ that metric ladders up to.

## v1 vs the destination

The specs read as cautious ("coarse", "deferred", "later") because they're written around a **data-availability constraint**, not the product. Strip the constraint and it's simple:

- **Destination:** every PR is a stream of lifecycle events. Every gap is measurable and trendable. Ask any question in natural language; get a grounded answer. Funnels, retention, cohorts — all PostHog tooling — on PRs.
- **v1 (ships first):** only the gaps measurable from today's snapshot warehouse data — total open time, CI duration. Honest, partial, useful immediately.

The gap between them is **just data ingestion** (the path from warehouse snapshots to lifecycle events). v1 lives on HogQL over `github_pull_requests` + `github_workflow_runs`; no event ingestion, no PR-as-group-type, no webhook receiver yet.

## What pays for the destination: token cost per outcome

The destination (lifecycle events + git history) is easy to defer while the payoff reads as "nicer CI metrics."
Attaching **dollars** changes the calculus, and it's the strongest near-term reason to build it.

LLM analytics already knows what agent work _costs_ — the `$ai_*_cost_usd` properties on generation events.
What it structurally cannot know is whether that spend was _worth it_: it has no concept of merge, revert, or rework.
That denominator — a PR's outcome and lifecycle — lives only here.
Token cost alone is trivia; **token cost per outcome** is the metric, and the join only lands in this product.

Roughly in order of "impossible elsewhere":

- **Rework cost (needs git history).** Sum agent spend across a change _and its fixups_ — a reverted PR plus its two follow-up fixes is the true cost of churn, invisible without the commit/PR graph.
- **Cost ÷ outcome.** "$X of agent tokens; Y% of those PRs merged, Z% reverted within a week" — a funnel with cost attached at each step.
- **Cost per code area.** Which products/paths burn the most agent tokens, via the PR's changed files.
- **The full three-ledger picture.** Human-hours + CI-minutes + tokens on the same unit (the PR) — the only place an agent-authored change and a human one are economically comparable.

Division of labor matters: LLM analytics does the cost grouping itself (it groups by any key on the event).
This product's job is the **join** — the agent stamps the **branch** at capture time (it knows the branch; the PR often doesn't exist yet), and we resolve that branch to a PR via `github_pull_requests.head.ref`, then enrich with outcome and lifecycle.
Not the commit SHA: the PR snapshot is current-state-only, so a SHA join matches only the latest push and silently drops every earlier one — undercounting exactly the multi-push work.
Review and CI-bot spend self-attributes (the PR exists by then); the coding slice is the part that needs us.

So cost is a _payload_, not a new surface: it rides the same lifecycle model, and it's the forcing function that makes ingesting that model — and the git history behind it — worth funding.
It serves both motivations — a DevEx dogfood metric, and the economics of the AI-to-prod loop.

## Locked decisions

Change one only in a separate PR with a written reason. Engineering-level decisions live in [SPEC.md](./SPEC.md) → Locked decisions.

- Two motivations: (A) DevEx dogfood, (B) close the dark middle in PostHog's AI-to-prod loop. Both must be served by every design decision.
- Two consumer classes: human-driven agents (primary) and agent-driven agents like PostHog Code (secondary, designed-for-now).
- Unit of value = the open PR.
- Phase model: draft (experimentation, low rigor) vs ready-for-review (high stakes).
- North star: surface actionable CI Signals for PostHog Code, emitted into the Signals product. Shortening ready-for-review-to-merge is the headline metric it serves, not the end in itself.
- Wedge = end-to-end code visibility, served as MCP tools to PostHog Code (autonomous) and engineers using PostHog MCP (human-driven).
- Surface = MCP is the official surface, delivered as named typed endpoints that run the curated read layer privately (no global HogQL view; off the per-query hot path; core imports only the viewset). `metric_quality` is a typed field on `pr_lifecycle`; aggregate endpoints carry caveats in honest field names + tool docs — never free-form prose an LLM might paraphrase wrong. See [SPEC.md](./SPEC.md) §3 / §7.
- UI = read-only analytics surface on the **same** endpoints (PR list, CI health, workflow health) — a real read surface, not only a design-system showcase. No saved views or stateful filters in this phase; persisted/stateful surfaces are a later, separate decision.
- v1 data path = HogQL on warehouse. Event ingestion deferred. Product Postgres DB stays empty.
- Author identity = `Author{handle, display_name, avatar_url, is_bot}`. No PostHog-user mapping in v1.
- Bots and drafts excluded by default in throughput / cycle-time tools; bots are first-class in bot-impact analysis (don't strip them everywhere).
- Bot detection = `handle.endswith("[bot]") OR handle in KNOWN_BOT_HANDLES`. Hardcoded allowlist for v1.
- Time to merge v1 = the read layer's `open_to_merge_seconds` column = `merged_at - created_at` (draft + ready-for-review combined). Coarse — encoded in the column name, never named cycle/review time.
- CI granularity = workflow level (`github_workflow_runs`). Job-level is a later add.
- `pull_request_reviews` warehouse source deferred until the wedge tool is built.
- No privacy guardrails in v1; revisit if scope widens beyond the team-devex maintainer.

## Glossary

| Term                             | Definition                                                                                                                                                                                  |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **PR (unit of value)**           | An open GitHub pull request, draft or ready-for-review — the atomic thing this product measures                                                                                             |
| **Draft phase**                  | Experimentation. Low-rigor measurement. Selective tests + advisory bots are OK                                                                                                              |
| **Ready-for-review phase**       | High-stakes. Where DevEx measures aggressively                                                                                                                                              |
| **Good friction**                | Tests / bots / checks that catch real problems. Kept and optimized                                                                                                                          |
| **Bad friction**                 | Tests / bots / checks that engineers ignore or that fail for unrelated reasons. Removed                                                                                                     |
| **Wedge**                        | End-to-end code visibility: code tracked from written → CI / review → live, served via MCP to PostHog Code and engineers using PostHog MCP                                                  |
| **MCP tool**                     | A function the agent calls. Its description is a production prompt                                                                                                                          |
| **Surface**                      | Primary = MCP tools; secondary = read-only demo UI                                                                                                                                          |
| **Human-driven agent**           | Claude Code / Cursor / PostHog AI invoked by an engineer typing                                                                                                                             |
| **Agent-driven agent**           | An autonomous agent (e.g. PostHog Code) invoking MCP tools without a human in the loop                                                                                                      |
| **The AI-to-prod loop**          | PostHog Code → engineering_analytics → PostHog product analytics → feedback to PostHog Code. The full lifecycle of agent-generated code, instrumented                                       |
| **The dark middle**              | The CI / review / merge / deploy steps between PostHog Code and PostHog product analytics, currently invisible to both                                                                      |
| **`open_to_merge_seconds` (v1)** | The read layer's coarse time-to-merge column: `merged_at - created_at`. PR open to merge — combines draft + ready-for-review until state-transition data lands. The name encodes the caveat |
| **Workflow**                     | A GitHub Actions workflow run on a PR's head commit. One row in `github_workflow_runs`. v1 CI granularity; job-level is a later add                                                         |
| **Bot**                          | An `Author` with `is_bot = True`. Detection: `handle.endswith("[bot]") OR handle in KNOWN_BOT_HANDLES`                                                                                      |
