# AI observability lenses

The depth behind the lens table in `SKILL.md`. Each lens is a recurring question about
this team's LLM usage. **You do not run every lens every tick** — pick the one(s) the
orientation reads flag as interesting, or the one that has gone stalest in memory, and
rotate so the fleet builds a full picture over time instead of re-probing the same metric
every hour.

For each lens below: the **signal** (the change that's worth a finding), the
**dimensions** to slice by to localize it, the **deep-dive skill** to read for the exact
queries, and the **discipline** (what's noise here).

## Before you start

The two cross-cutting habits every lens leans on — **discover the team's dimensions**
(don't guess them) and **trend → spike → localize → sample** — live in `SKILL.md`, the
always-read surface, so they aren't restated here to avoid drift. The per-lens detail below
assumes them.

## Quick-probe HogQL gotchas

For the cheap trend queries you write yourself (the deep-dive skills have the maintained
queries for anything more):

- The `$ai_*` numeric properties sit in a **typed property group**, so guard them
  numerically — filter `properties.$ai_latency > 0` (a `!= ''` guard triggers a float-cast
  error) and aggregate them directly: `quantile(0.9)(properties.$ai_latency)`, no `toFloat`.
- HogQL has `toFloatOrDefault` / `toIntOrDefault`, **not** `toFloatOrNull`.
- `$ai_tools_called` is a **comma-joined string**, not a JSON array —
  `arrayJoin(splitByChar(',', properties.$ai_tools_called))` to tally tool usage.
- Not every team emits `$ai_embedding` (the dogfood project doesn't); including it in cost
  rollups is harmless but querying an absent event raises a taxonomy warning.

## The deep-dive skills

The sandbox bakes four upstream PostHog skills — they hold the exact, maintained query
recipes so this scout doesn't have to. Read the matching one **when you go deep on a
lens**, not on every run:

- `posthog:exploring-llm-costs` — cost over time, breakdowns by any dimension, cache /
  token economics, the 5-step cost-regression playbook.
- `posthog:exploring-llm-traces` — finding traces by filter, the event hierarchy, drilling
  a single trace/session, parsing scripts. (Message content lives on the `posthog.ai_events`
  table, not `events.properties`.)
- `posthog:exploring-llm-evaluations` — the real eval-results path: AI pass/fail/N/A
  pattern summaries and raw `$ai_evaluation` SQL, plus config inspection and Hog dry-runs.
- `posthog:exploring-llm-clusters` — per-cluster cost/latency/error metrics, comparing
  clusters across runs.

`posthog:querying-posthog-data` is also baked — read it before writing non-trivial HogQL.

---

## Cost — read `posthog:exploring-llm-costs`

- **Signal.** Total `$ai_total_cost_usd` for a complete period ≥ ~2× the team's baseline
  and held, or one dimension's cost stepping up and staying there.
- **Slice by.** model, provider, `ai_product`, `distinct_id` (top spenders), trace (top
  expensive traces), custom dims (`feature` / `tenant_id` / `workflow_name`).
- **Discipline.** Use the skill's rollup query (it covers the summation and embedding
  gotchas) — don't hand-roll cost SQL. Scheduled batch/eval jobs and deliberate model swaps
  recur — record their cadence as `pattern:`/`addressed:`; a known swap is not a spike. High
  panic radius for finance: hold to ≥ 2× _sustained_, not a single-hour blip.

## Latency — read `posthog:exploring-llm-traces`

- **Signal.** `$ai_latency` p50/p90/p99 drifting up and holding, or spiking, **per model**
  vs that model's band.
- **Slice by.** model, provider, `$ai_span_name`, `ai_product`.
- **Discipline.** Never band latency in aggregate — o3 / preview models are structurally
  slow, so a mix shift moves the aggregate without any regression. Provider-side slowness
  during a known upstream incident is not a PostHog bug (but may be worth a `watch:`).

## Errors — read `posthog:exploring-llm-traces`

- **Signal.** `$ai_is_error` rate or `$ai_http_status >= 400` composition trending up, or
  the composition shifting (client 4xx → provider 5xx, or 429 rate-limits appearing).
- **Slice by.** model, provider, status class (4xx / 5xx / 429), `ai_product`, and
  `distinct_id` / trace (is it concentrated on one user or spread?).
- **Discipline.** Raw `$ai_is_error` is inflated by HITL approval interrupts and
  cancellations — filter them. Benign client-side 400 classes on a specific model recur:
  characterize once as `noise:` with an explicit re-investigate tripwire. Provider 429/5xx
  during a known upstream incident → check status pages first.

## Volume — read `posthog:exploring-llm-traces` / `execute-sql`

- **Signal.** `$ai_generation` / `$ai_trace` count or `distinct_users` stepping off
  baseline — a _collapse_ (instrumentation broke, product down) or a _surge_ (new use case,
  runaway loop). The count-very-high vs distinct-users-very-low shape is the runaway/power-
  user detector; a single trace with > 50 generations is either a multi-step agent or a
  stuck loop (memory usually records which side this team is on).
- **Slice by.** model, `ai_product`, `$ai_span_name`; count-to-distinct-users ratio.
- **Discipline.** Diurnal and weekly seasonality dominate — compare like-for-like buckets.
  A complete-weekday vs partial-today comparison is a false drop.

## Eval performance — read `posthog:exploring-llm-evaluations`

- **Signal.** A specific evaluation's pass-rate (or fails/day) changing recently vs its own
  baseline — catching a real upstream regression or the eval going flaky.
- **How to read it.** `llma-evaluation-list` only gives **config** — the pass-rate lives in
  `$ai_evaluation` events. Read the **trend straight from those events** (fails/day with the
  N/A guard) following the eval skill's "Why is evaluation X suddenly failing more?"
  workflow — that raw query is the reliable spine. `llma-evaluation-summary-create
{evaluation_id, filter:"fail"}` is an optional drill-down that groups failures into
  patterns with example IDs, but it's billed, rate-limited, and currently prone to 500s —
  treat it as a bonus, not a dependency, and fall back to sampling the raw failing rows via
  `query-llm-trace` when it's unavailable.
- **Discipline.** Pass-rate regressions **also auto-flow to the inbox** via the enabled
  `llm_analytics:evaluation` signal source — so only emit when you've localized something
  the auto-flow won't (a specific eval + a specific failure pattern + a cause); otherwise
  hold + remember. A known-flaky eval (steady % noise) is `noise:` with a floor.

## Eval / enrichment config health — read `posthog:exploring-llm-evaluations`

The configuration surface, not the telemetry — evals, **taggers**, and **scorers** are all
LLM/Hog jobs that can silently break.

- **Signal.** A config that's meant to be running but isn't doing its job: an eval / tagger
  / scorer disabled or status-flipped unexpectedly, an N/A-heavy eval (applicability too
  broad — `summary-create {filter:"na"}`), a job pointed at a **deprecated model** or a
  **disabled/revoked provider key**, or a Hog evaluator hitting the 5s execution limit.
- **How to read it.** `llma-evaluation-list` (status/enabled, type), `llma-tagger-list`
  (`enabled`, `model_configuration.provider_key_id`, `conditions`),
  `llma-score-definition-list`. Cross-reference provider-key failures the error-tracking
  lens has already surfaced (ProviderMismatchError, disabled-key) — those are this surface
  failing _reactively_; this lens is how you'd catch it _proactively_.
- **Discipline.** These are config objects — a deliberately-disabled tagger is not a
  defect. Emit only when something meant to be running is silently failing or scoring
  nothing.

## Clusters — read `posthog:exploring-llm-clusters`

- **Signal.** A new cluster appearing, a cluster's volume jumping, or an error-heavy /
  expensive / slow cluster — a new use case or a regression localized to one kind of
  traffic.
- **How to read it.** `llma-clustering-job-list` / `-get`; results land in
  `$ai_trace_clusters` / `$ai_generation_clusters` events; compute per-cluster
  cost/latency/error via `execute-sql` (the skill has the recipe).
- **Discipline.** Clusters shift run-to-run — compare across runs before calling a one-run
  blip a trend.

## Tool usage — read `posthog:exploring-llm-traces`

- **Signal.** The mix of tools called (`$ai_tools_called` / a trace's `tools`) changing —
  a new tool appearing, a heavily-used tool vanishing, one tool's error/latency rising, or
  tool-calls-per-trace climbing (agent-loop shape).
- **Slice by.** tool name, `ai_product`, model.
- **Discipline.** Intentional product changes (a tool shipped/retired) explain most mix
  shifts — correlate with prompt version bumps and deploys before calling it a regression.

## Prompts (a cause, not a lens) — `llma-prompt-list` / `-get`

Not a standalone metric — a correlate. When the cost, latency, eval, or tool lens flags a
change, check `llma-prompt-list` for a version bump (`updated_at` / `version`) in the same
window. A prompt change is a more direct cause than a generic `activity-log-list` deploy
and sharpens the finding.
