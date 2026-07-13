# Skill — cost and quota analysis

How to use `posthog__execute-sql` to answer "how much does this agent
cost?" / "where is it slow?" / "what's the failure rate?". Load
when the user asks about cost, performance, usage, or limits.

> **Event contract lives in `querying-ai-observability`.** That skill
> is the ground truth for what the runner actually emits and every
> property name + caveat. This skill is the cost/quota _framing_ on top
> of it. If a property here ever disagrees with that skill, trust that
> skill. The short version: the runner emits three LLM-observability
> events — `$ai_generation` (per model turn), `$ai_span` (per tool
> call), `$ai_trace` (per session, at terminal outcome) — into the
> agent's own team project. There are **no** session-level or
> tool-level custom events; older docs referencing `agent_session_ended`
> / `agent_tool_called` / `$ai_cost_usd` / `properties.agent_application_id`
> predate the shipped emitter and match nothing.

## The data model

PostHog's LLM analytics surface keys on the `$ai_*` events the runner
captures, each tagged with `$agent_application_id`. The fields that
matter for cost/quota work:

| Event            | Properties of interest                                                                                                                       |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `$ai_generation` | `$ai_model`, `$ai_provider`, `$ai_input_tokens`, `$ai_output_tokens`, `$ai_total_cost_usd`, `$ai_latency`, `$ai_is_error`, `$ai_stop_reason` |
| `$ai_span`       | `$ai_span_name` (the tool id), `$ai_latency`, `$ai_is_error`, `$ai_tool_call_id`                                                             |
| `$ai_trace`      | one per session (terminal); `$ai_span_name` = the agent's display name + input/output state                                                  |

Shared identifiers on all three: `$ai_trace_id` (**the session id** —
the join key), `$agent_application_id` (your primary filter),
`$agent_revision_id`, `$agent_turn` (1-indexed), `team_id`, `$ai_origin`
(always `agent_platform_runner`). `$ai_latency` is in **seconds**.

> **CRITICAL — gateway mode zeroes cost.** On the ai-gateway path the
> runner emits `$ai_total_cost_usd` as `undefined` (pi-ai's client-side
> number is just an estimate; the gateway owns billing), so the property
> is **absent** and any `sum(...$ai_total_cost_usd)` rollup reads as
> **zero**. Token counts are still accurate. When cost comes back zero
> but tokens are non-zero, you're on the gateway path — the authoritative
> per-session cost is the session row's `usage_total`, which the runner
> backfills from the gateway after each turn. Read it via
> `posthog__agent-applications-sessions-retrieve`, not from the events. Always
> sanity-check a cost rollup against token volume before reporting it.

Verify the events exist for your team before trusting a query:

```sql
SELECT DISTINCT event FROM events
WHERE event LIKE '$ai_%'
  AND timestamp > now() - INTERVAL 1 DAY
LIMIT 10
```

## Standard rollups

### Cost + tokens over time, per agent

`$ai_generation` carries per-turn cost and tokens. Sum them per agent
per day:

```sql
SELECT
    properties.$agent_application_id AS agent,
    toStartOfDay(timestamp) AS day,
    sum(properties.$ai_total_cost_usd) AS cost_usd,
    sum(properties.$ai_input_tokens) AS input_tokens,
    sum(properties.$ai_output_tokens) AS output_tokens,
    count() AS generations
FROM events
WHERE event = '$ai_generation'
  AND notEmpty(properties.$agent_application_id)
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY agent, day
ORDER BY day DESC, cost_usd DESC
```

If `cost_usd` is zero while `input_tokens`/`output_tokens` are not, the
agent is on the gateway path — get true cost from `usage_total` (see the
gateway caveat above).

### Session-level summary

There's no session-ended event; roll the per-turn generations up by
`$ai_trace_id` (= the session id) instead:

```sql
SELECT
    properties.$agent_application_id AS agent,
    properties.$ai_trace_id AS session,
    sum(properties.$ai_total_cost_usd) AS session_cost_usd,
    sum(properties.$ai_input_tokens + properties.$ai_output_tokens) AS tokens,
    max(properties.$agent_turn) AS turns,
    countIf(properties.$ai_is_error = 1) AS model_errors
FROM events
WHERE event = '$ai_generation'
  AND properties.$agent_application_id = '<app-id>'
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY agent, session
ORDER BY session_cost_usd DESC
```

For the per-agent averages across sessions, wrap this in an outer
aggregate, or read `usage_total` per session when cost matters and the
agent is on the gateway path.

### Tool call frequency + error rate

Tool dispatches are `$ai_span` events; the tool id is `$ai_span_name`:

```sql
SELECT
    properties.$ai_span_name AS tool,
    count() AS calls,
    countIf(properties.$ai_is_error = 1) AS errors,
    avg(properties.$ai_latency) AS avg_latency_s
FROM events
WHERE event = '$ai_span'
  AND properties.$agent_application_id = '<app-id>'
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY tool
ORDER BY calls DESC
```

### Failure rate

No `failure_reason` property exists. Use `$ai_is_error` on generations
(model-level failures) and `$ai_stop_reason` (e.g. `length` =
truncation) for the closest signal:

```sql
SELECT
    properties.$ai_stop_reason AS stop_reason,
    count() AS generations,
    countIf(properties.$ai_is_error = 1) AS errors
FROM events
WHERE event = '$ai_generation'
  AND properties.$agent_application_id = '<app-id>'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY stop_reason
ORDER BY generations DESC
```

For a per-session error population and the tool-error breakdown, defer
to `querying-ai-observability` — it has the canonical "which sessions
tripped up" and "which tool is failing" queries.

## Three queries to run by default for "is X healthy?"

When the user says "audit X" / "is X healthy?" / "how's X doing?",
run these in order:

1. **7d session count + error mix** — count distinct `$ai_trace_id` and
   `countIf($ai_is_error = 1)`. Gives you "is the agent running, and is
   it succeeding?"
2. **7d cost + tokens + 30d trend** — the per-agent rollup above. Gives
   you "is cost stable, or drifting up?" (Remember: zero cost + nonzero
   tokens = gateway path; pull `usage_total`.)
3. **Top 3 tools by call count, with error rate** — the `$ai_span`
   rollup. Gives you "where are the runtime problems?"

That's enough for a useful summary. Don't run more queries without a
specific question.

## Comparing agents

For "why is X 3x more expensive than Y?" run them side by side off
`$ai_generation`:

```sql
SELECT
    properties.$agent_application_id AS agent,
    uniq(properties.$ai_trace_id) AS sessions,
    sum(properties.$ai_total_cost_usd) AS cost_usd,
    sum(properties.$ai_input_tokens) AS input_tokens,
    sum(properties.$ai_output_tokens) AS output_tokens
FROM events
WHERE event = '$ai_generation'
  AND properties.$agent_application_id IN ('agent_x', 'agent_y')
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY agent
```

Then explain the delta in terms of the spec:

- Different model? Check `spec.models`.
- Different reasoning level? Check `spec.reasoning` — a higher level
  (`high` / `xhigh`) adds deliberation tokens on thinking-heavy turns.
- More turns? Likely a prompt issue — `max($agent_turn)` per session,
  then read `agent.md` for both and compare.
- More tool calls? Likely a different tool mix — pull `$ai_span` for
  both.

(If both agents are on the gateway path, cost columns read zero — fall
back to comparing token volume, or `usage_total` per session.)

## Surfacing the cost analysis

Don't dump raw query results. Present a structured summary:

```text
**weekly-digest cost overview (7 days)**

12 sessions, 0 with model errors. ✅ healthy.

Cost: $0.48 (avg $0.04/session, range $0.02-$0.09)
Trend: stable — 30d avg is $0.04/session, no inflation.

Token mix: 80% input, 20% output. Mostly reading data, summarizing.

Tool mix: 47% @posthog/query, 35% @posthog/slack-post-message, 18%
@posthog/load-skill. No errors.

Want me to: drill into the most-expensive session? compare against
daily-digest? show the 30d trend graph?
```

## Cost levers — what changes cost when

Useful to know when someone asks "how do I make it cheaper?":

| Lever                              | Effect                                                                                                                                       |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Model (`spec.models`)              | Biggest factor — a `low`-level model is often ~5-10x cheaper than `high`; see `@posthog/agent-applications-models` for live per-Mtok pricing |
| Reasoning level (`spec.reasoning`) | Higher levels (`high` / `xhigh`) add deliberation tokens                                                                                     |
| Skills layout                      | Many skills loaded per turn means a fatter system prompt every turn                                                                          |
| Custom tool egress                 | Tools that fetch large pages inflate input tokens on the next turn                                                                           |
| Conversation length                | Longer multi-turn agents pay for the conversation re-feed                                                                                    |
| Limits                             | `spec.limits.max_turns` is the upper bound on cost per session                                                                               |

The reasoning levels are `minimal` | `low` | `medium` | `high` |
`xhigh`. Treat the cost impact as directional, not a fixed multiplier —
the actual token cost depends on how much the model deliberates per turn.

## Latency analysis

For "X is slow", split model time from tool time. Tool latency from
`$ai_span` (`$ai_latency` is in seconds):

```sql
SELECT
    properties.$ai_span_name AS tool,
    quantile(0.5)(properties.$ai_latency) AS p50_s,
    quantile(0.95)(properties.$ai_latency) AS p95_s,
    quantile(0.99)(properties.$ai_latency) AS p99_s,
    count() AS calls
FROM events
WHERE event = '$ai_span'
  AND properties.$agent_application_id = '<app-id>'
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY tool
ORDER BY p95_s DESC
```

Then the model-call latency from `$ai_generation`:

```sql
SELECT
    quantile(0.5)(properties.$ai_latency) AS p50_s,
    quantile(0.95)(properties.$ai_latency) AS p95_s
FROM events
WHERE event = '$ai_generation'
  AND properties.$agent_application_id = '<app-id>'
  AND timestamp > now() - INTERVAL 7 DAY
```

If model time dominates, the fix is usually model choice or reasoning
level. If tool time dominates, the fix is usually a slow custom tool or
external dependency.

## Caveats

- **Gateway path zeroes `$ai_total_cost_usd`.** This is the one that
  bites: a cost rollup reads zero on the gateway path even though the
  agent is spending money. Token counts stay accurate. Truth-of-cost is
  the session row's `usage_total` (`posthog__agent-applications-sessions-retrieve`).
  See the boxed caveat at the top.
- **Emission is best-effort.** The runner's analytics writes are
  fire-and-forget; a dropped event means a slightly low count, never a
  wrong one. Don't treat counts as exactly authoritative.
- **Heavy columns** (`$ai_input`, `$ai_output_choices`,
  `$ai_input_state`, `$ai_output_state`) are large — only select them
  for a single span you're inspecting, never across a population query.
- **When in doubt, defer to `querying-ai-observability`** for the event
  contract and probe the events table first with a `DISTINCT event`
  query.
