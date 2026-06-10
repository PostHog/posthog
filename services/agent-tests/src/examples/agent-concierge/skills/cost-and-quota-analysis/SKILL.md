# Skill — cost and quota analysis

How to use `@posthog/query` to answer "how much does this agent
cost?" / "where is it slow?" / "what's the failure rate?". Load
when the user asks about cost, performance, usage, or limits.

> **Event contract:** the runner emits `$ai_generation` / `$ai_span`
> / `$ai_trace` into the agent's own team project — the authoritative
> property names live in `querying-ai-observability` (e.g.
> `$agent_application_id`, `$ai_total_cost_usd`, `$ai_trace_id` = the
> session id). Some queries below use older/aspirational names
> (`agent_session_ended`, `properties.agent_application_id`,
> `$ai_cost_usd`); when one returns nothing, load
> `querying-ai-observability` and use the shipped names. Probe with a
> `DISTINCT event` query first if unsure.

## The data model

PostHog's LLM analytics auto-captures events tagged with
`$agent_application_id` (when the runner publishes from a session).
Useful event types:

| Event                   | Properties of interest                                                                              |
| ----------------------- | --------------------------------------------------------------------------------------------------- |
| `$ai_generation`        | `$ai_provider`, `$ai_model`, `$ai_input_tokens`, `$ai_output_tokens`, `$ai_cost_usd`, `$ai_latency` |
| `$ai_trace`             | rolled-up trace (session-level), includes total cost / tokens / duration                            |
| `agent_session_started` | `agent_application_id`, `revision_id`, `trigger_type`, `principal_kind`                             |
| `agent_session_ended`   | adds `state`, `failure_reason`, `total_cost_usd`, `total_input_tokens`, etc.                        |
| `agent_tool_called`     | `tool_id`, `tool_kind` (`native`/`custom`/`mcp`/`client`), `latency_ms`, `is_error`                 |

The exact event names depend on the runner's publisher config —
verify by running a small probe query against `events` filtered
to your team:

```sql
SELECT distinct event FROM events
WHERE event LIKE 'agent_%' OR event LIKE '$ai_%'
AND timestamp > now() - INTERVAL 1 DAY
LIMIT 20
```

## Standard rollups

### Cost over time, per agent

```sql
SELECT
    properties.agent_application_id AS agent,
    toStartOfDay(timestamp) AS day,
    sum(properties.$ai_cost_usd) AS cost_usd,
    sum(properties.$ai_input_tokens) AS input_tokens,
    sum(properties.$ai_output_tokens) AS output_tokens,
    count() AS generation_count
FROM events
WHERE event = '$ai_generation'
  AND notEmpty(properties.agent_application_id)
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY agent, day
ORDER BY day DESC, cost_usd DESC
```

### Session-level summary

```sql
SELECT
    properties.agent_application_id AS agent,
    properties.state AS state,
    count() AS sessions,
    sum(properties.total_cost_usd) AS total_cost,
    avg(properties.total_cost_usd) AS avg_cost_per_session,
    avg(properties.turn_count) AS avg_turns
FROM events
WHERE event = 'agent_session_ended'
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY agent, state
ORDER BY total_cost DESC
```

### Tool call frequency

```sql
SELECT
    properties.tool_id AS tool,
    properties.tool_kind AS kind,
    count() AS calls,
    sum(properties.is_error) AS errors,
    avg(properties.latency_ms) AS avg_latency_ms
FROM events
WHERE event = 'agent_tool_called'
  AND properties.agent_application_id = '<slug-or-id>'
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY tool, kind
ORDER BY calls DESC
```

### Failure rate by reason

```sql
SELECT
    properties.failure_reason AS reason,
    count() AS sessions,
    sum(properties.total_cost_usd) AS wasted_cost
FROM events
WHERE event = 'agent_session_ended'
  AND properties.state = 'failed'
  AND properties.agent_application_id = '<slug-or-id>'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY reason
ORDER BY sessions DESC
```

## Three queries to run by default for "is X healthy?"

When the user says "audit X" / "is X healthy?" / "how's X doing?",
run these three in order:

1. **7d session count + state mix** — gives you "is the agent
   even running, and is it succeeding?"
2. **7d cost + 30d trend** — gives you "is cost stable, or
   drifting up?"
3. **Top 3 tools by call count, with error rate** — gives you
   "where are the runtime problems?"

That's enough for a useful summary. Don't run more queries
without a specific question.

## Comparing agents

For "why is X 3x more expensive than Y?" run side-by-side:

```sql
SELECT
    properties.agent_application_id AS agent,
    avg(properties.total_cost_usd) AS avg_cost,
    avg(properties.turn_count) AS avg_turns,
    avg(properties.total_input_tokens) AS avg_input_tokens,
    avg(properties.total_output_tokens) AS avg_output_tokens
FROM events
WHERE event = 'agent_session_ended'
  AND properties.agent_application_id IN ('agent_x', 'agent_y')
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY agent
```

Then explain the delta in terms of the spec:

- Different model? Check `spec.model`.
- Different reasoning level? Check `spec.reasoning` — `high` is
  ~3x `medium` for thinking-heavy turns.
- More turns? Likely a prompt issue — read `agent.md` for both
  and compare.
- More tool calls? Likely different tool mix — pull
  `agent_tool_called` for both.

## Surfacing the cost analysis

Don't dump raw query results. Present a structured summary:

```text
**weekly-digest cost overview (7 days)**

12 sessions, 12 completed, 0 failed. ✅ healthy.

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

| Lever                              | Effect                                                              |
| ---------------------------------- | ------------------------------------------------------------------- |
| Model (`spec.model`)               | Biggest factor — claude-haiku is ~1/5 sonnet, gpt-4-mini is similar |
| Reasoning level (`spec.reasoning`) | `high` / `xhigh` add deliberation tokens — multiplicative           |
| Skills layout                      | Many skills loaded per turn means a fatter system prompt every turn |
| Custom tool egress                 | Tools that fetch large pages inflate input tokens on the next turn  |
| Conversation length                | Longer multi-turn agents pay for the conversation re-feed           |
| Limits                             | `max_turns` is the upper bound on cost per session                  |

## Latency analysis

For "X is slow":

```sql
SELECT
    properties.tool_id AS tool,
    quantile(0.5)(properties.latency_ms) AS p50,
    quantile(0.95)(properties.latency_ms) AS p95,
    quantile(0.99)(properties.latency_ms) AS p99,
    count() AS calls
FROM events
WHERE event = 'agent_tool_called'
  AND properties.agent_application_id = '<slug-or-id>'
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY tool
ORDER BY p95 DESC
```

Then for the agent's `$ai_generation` latency:

```sql
SELECT
    quantile(0.5)(properties.$ai_latency) AS p50,
    quantile(0.95)(properties.$ai_latency) AS p95
FROM events
WHERE event = '$ai_generation'
  AND properties.agent_application_id = '<slug-or-id>'
  AND timestamp > now() - INTERVAL 7 DAY
```

Decompose total session latency into "model time" + "tool time".
If model time dominates, the fix is usually model choice or
reasoning level. If tool time dominates, the fix is usually a
slow custom tool or external dependency.

## Caveats

- The runner's analytics publisher is best-effort. Event drops
  are possible; don't treat counts as exactly authoritative.
- Cost numbers are billed by the provider — if the user wants the
  truth-of-bill, send them to PostHog's LLM analytics surface or
  the provider's own dashboard.
- The schema above is the v0 plan; field names may have evolved.
  When in doubt, probe the events table first with a `DISTINCT
event` / `DISTINCT properties.X` query.
