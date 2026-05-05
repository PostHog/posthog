# Lens: LLM analytics

The profile's `top_events` will surface LLM events directly when the team is
using the product: `$ai_generation`, `$ai_evaluation`, `$ai_trace`, `$ai_span`,
`$ai_metric`, `$ai_feedback`. The relationship between `count` and
`distinct_users` is meaningful — `$ai_generation` should look ~1:1 in healthy
operation (one generation per user request), and large divergence from that
baseline is the strongest signal-vs-noise discriminator.

## Quick scan from the profile alone

Look at LLM events in `top_events`:

| Pattern                                                    | What it usually means                            |
| ---------------------------------------------------------- | ------------------------------------------------ |
| `$ai_generation` `count` ≈ `distinct_users` (close to 1:1) | Healthy — one generation per user request        |
| `$ai_generation` `count` ≫ `distinct_users` (e.g. 10x)     | Multi-step agents, retries, or runaway loops     |
| `$ai_generation` `recent_24h_count / count` ≫ `1/7`        | Today's spike — new feature launch or runaway    |
| `$ai_evaluation` count rising fast                         | Eval coverage growing (good) or eval loop        |
| `$ai_evaluation` present but `$ai_generation` absent       | Eval-only project — no production LLM traffic    |
| `$ai_generation` quiet but `$exception` from LLM SDK loud  | LLM calls failing before emitting a trace        |
| `$ai_generation` users dropped sharply 24h vs 7d           | Provider outage or model deprecation propagating |

If LLM events don't appear in `top_events`, the team isn't using LLM analytics
heavily this week — check `get-llm-total-costs-for-project` for low-frequency
spend, then move on if quiet.

## Patterns to look for

### Cost spike

`get-llm-total-costs-for-project` plus a per-day breakdown via
`query-llm-traces-list` shows cost rising materially (≥ 2x baseline) over the
recent window. Common causes: a model swap (Sonnet → Opus), a prompt
regression that ballooned token counts, a runaway agent loop.

Pair with `query-llm-trace` on a sample trace from the spike window: longer
context, more tool calls, larger output. Cross-source convergence with a
recent deploy from `activity-log-list` is high-signal.

### Eval pass-rate drop

`llma-evaluation-list` plus `llma-evaluation-run` (or recent run results)
shows pass-rate dropping below baseline. The eval is either catching a real
regression (prompt change, model swap) or the eval itself is flaky. Scout
priority is to surface — let the team triage which it is.

### Runaway loop / power-user pattern

`$ai_generation` `count` very high, `distinct_users` very low. One user (often
a developer or an agentic workflow) generating thousands of calls. Validate
with `query-llm-traces-list` filtered to the top user — if a single trace has
more than 50 generations, it's either a multi-step agent (intentional) or a
stuck loop. Memory probably already records which side of this the team is on.

### New model adoption

`query-llm-traces-list` shows traces from a model that wasn't in the previous
profile snapshot. Worth flagging if the new model has materially different
cost / latency / quality — usually warrants a memory entry rather than an
emit, unless the cost or eval pass-rate has shifted with it.

### Trace-level failure spike

`query-llm-traces-list` filtered to traces with errors or non-2xx responses.
A surge usually correlates with provider rate limits or upstream incidents,
which `posthog:exploring-llm-traces` can tell apart from PostHog-side bugs.

### Cluster-level pattern

`llma-clustering-job-list` exposes existing clustering jobs over recent
generations. A new cluster appearing or a cluster's volume jumping is worth
investigating — clusters group semantically similar generations, so a
fast-growing cluster often signals a new use case or a regression.

## Disqualifiers (skip these)

- **Anthropic / OpenAI rate-limit errors** — these surface in the
  error-tracking lens too. If memory already has a `noise` entry for them,
  skip; otherwise leave one.
- **Single developer testing locally** — `properties.environment ∈ {dev,
local}` or the user is internal. Filter before weighing.
- **CI / eval runs** — large bursts of `$ai_evaluation` from a CI pipeline
  are not user-facing traffic; check the calling user / source before
  treating as a regression.
- **Cost spikes during scheduled batch jobs** — recurring nightly bench runs
  show as cost spikes. Memory should record their cadence.

When in doubt, write a memory entry instead of emitting.

## MCP tools

- `query-llm-traces-list` — start here. Recent traces, filterable by user /
  model / cost / error.
- `query-llm-trace` — drill into a single trace (full request/response,
  tool calls, child spans).
- `llma-evaluation-list` — what evals exist on this team.
- `llma-evaluation-run` — current pass-rate / failure modes for a given eval.
- `llma-clustering-job-list` / `llma-clustering-job-get` — semantic clusters
  over generations; a fast-growing cluster is a finding candidate.
- `get-llm-total-costs-for-project` — top-level cost surface; pair with
  per-day breakdowns to detect spikes.
- `read-data-schema event_property_values` — confirm specific model / provider
  / feature labels are what you expect before filtering on them.

For deep investigation playbooks, the sandbox image bakes
`posthog:exploring-llm-traces` (debugging individual traces, agent decisions,
context surfacing), `posthog:exploring-llm-evaluations` (eval failure modes,
common patterns, dry-running new judges), `posthog:exploring-llm-costs`
(cost regressions by model / user / feature, cost dashboards), and
`posthog:exploring-llm-clusters` (cluster comparison, cost/latency per
cluster, drilling into individual traces).

## Memory shapes worth writing

After investigating LLM analytics on a project, leave durable steers like:

- _"This team's `$ai_generation` baseline is ~5k/day across ~3k distinct
  users; a 1.6:1 ratio is normal for their multi-step agent."_ (`pattern`,
  `domain:llm_analytics`)
- _"Eval `relevance-judge` flakes ~5% per run — flag only if pass-rate drops
  below 80%."_ (`noise`, `domain:llm_analytics`, `entity:relevance-judge`)
- _"Nightly batch eval runs ~02:00-04:00 UTC and accounts for ~40% of daily
  cost — not a runaway, recurring."_ (`pattern`, `domain:llm_analytics`)
- _"Switched primary model from Sonnet to Opus 2026-04-28; cost ~2.1x
  baseline expected."_ (`addressed`, `domain:llm_analytics`,
  `entity:model_swap_2026-04-28`)

These compound: by run #5, the scout knows the team's healthy baselines, which
spikes are recurring, and which evals deserve more or less weight.
