# Skill — querying AI observability

When you're debugging a session or improving an agent, the
conversation JSON tells you _what was said_; the LLM-observability
events tell you _what it cost, how long it took, what the model
actually saw, and where a tool errored_. The runner emits these into
**the agent's own team project**, so you can HogQL them with
`posthog__execute-sql` as the connected user — no extra setup.

Load this for the authoritative event contract. `cost-and-quota-analysis`
has the cost-framing rollups; this skill has the ground truth of
_what the runner actually emits_ and the queries that matter when
something went wrong.

## What the runner emits (the real contract)

Three event types, one project, all carrying the agent identifiers.
These names match the runner's `analytics-sink` exactly — older docs
that say `agent_session_ended` / `properties.agent_application_id` /
`$ai_cost_usd` predate the shipped emitter; trust the table below.

| Event            | One per…            | Read it for                                |
| ---------------- | ------------------- | ------------------------------------------ |
| `$ai_generation` | model call (a turn) | model, tokens, cost, latency, stop reason  |
| `$ai_span`       | tool dispatch       | tool name, args, result, latency, errors   |
| `$ai_trace`      | session (terminal)  | session name + input/output state, roll-up |

Shared properties (note the `$` prefixes — easy to get wrong):

| Property                | Meaning                                                   |
| ----------------------- | --------------------------------------------------------- |
| `$ai_trace_id`          | **the session id** — the join key across all three events |
| `$ai_span_id`           | `<session>:gen:<turn>` (generation) / `…:tool:…` (span)   |
| `$ai_parent_id`         | on a span: the generation that emitted the tool call      |
| `$agent_application_id` | the agent — your primary filter                           |
| `$agent_revision_id`    | which revision produced the event                         |
| `$agent_session_id`     | session id (same value as `$ai_trace_id`)                 |
| `$agent_turn`           | 1-indexed turn within the session                         |
| `team_id`               | owning team                                               |
| `$ai_origin`            | always `agent_platform_runner`                            |

Generation-only: `$ai_model`, `$ai_provider`, `$ai_input_tokens`,
`$ai_output_tokens`, `$ai_total_cost_usd` (omitted on the gateway
path — see caveats), `$ai_latency` (seconds), `$ai_stop_reason`,
`$ai_is_error`, `$ai_error`, `$ai_input`, `$ai_output_choices`.

Span-only: `$ai_span_name` (the tool id), `$ai_tool_call_id`,
`$ai_input_state` (args), `$ai_output_state` (result), `$ai_latency`,
`$ai_is_error`, `$ai_error`.

Trace-only: `$ai_span_name` (the agent's display name),
`$ai_input_state`, `$ai_output_state`.

When unsure a field exists, probe first — don't guess:

```sql
SELECT DISTINCT event FROM events
WHERE event LIKE '$ai_%' AND timestamp > now() - INTERVAL 1 DAY
LIMIT 10
```

## Debugging one session

You usually arrive here from `debugging-sessions` with a session id.
`$ai_trace_id` **is** that session id, so one filter pulls the whole
trace — model turns and tool calls interleaved:

```sql
SELECT
    event,
    properties.$agent_turn AS turn,
    properties.$ai_span_name AS tool,
    properties.$ai_model AS model,
    properties.$ai_latency AS latency_s,
    properties.$ai_total_cost_usd AS cost_usd,
    properties.$ai_is_error AS is_error,
    properties.$ai_error AS error
FROM events
WHERE properties.$ai_trace_id = '<session-id>'
  AND event IN ('$ai_generation', '$ai_span')
  AND timestamp > now() - INTERVAL 30 DAY
ORDER BY turn, timestamp
```

Read it top-to-bottom: a turn that ballooned in `latency_s`, a span
with `is_error = 1`, the same tool firing every turn (a loop), a
`$ai_stop_reason` of `length` (truncation). That's the evidence you
cite in the debugging report — concrete, not inferred from prose.

To see exactly what the model was sent on a bad turn, pull
`properties.$ai_input` / `properties.$ai_output_choices` for that
`$ai_span_id`. Heavy columns — fetch one turn, not the whole trace.

## Finding which sessions tripped up (improving)

When the goal is "make this agent better", start from the population,
not one session. Sessions with any error, last 7 days:

```sql
SELECT
    properties.$ai_trace_id AS session,
    countIf(properties.$ai_is_error = 1) AS errors,
    sum(properties.$ai_total_cost_usd) AS cost_usd,
    max(properties.$agent_turn) AS turns
FROM events
WHERE properties.$agent_application_id = '<app-id>'
  AND event IN ('$ai_generation', '$ai_span')
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY session
HAVING errors > 0
ORDER BY errors DESC, cost_usd DESC
LIMIT 25
```

Then drill into the worst with the per-session query above. Group
findings by root cause, not by session — five sessions with the same
tool error are one finding.

### Tool error breakdown

Which tool is failing, and how often:

```sql
SELECT
    properties.$ai_span_name AS tool,
    count() AS calls,
    countIf(properties.$ai_is_error = 1) AS errors,
    round(countIf(properties.$ai_is_error = 1) / count(), 3) AS error_rate,
    quantile(0.95)(properties.$ai_latency) AS p95_latency_s
FROM events
WHERE event = '$ai_span'
  AND properties.$agent_application_id = '<app-id>'
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY tool
ORDER BY errors DESC, calls DESC
```

A tool with a high `error_rate` is a config/credential problem (the
agent can't fix a 403) or a bad-args problem (the agent CAN — tighten
the prompt/schema). Read a couple of the failing spans'
`$ai_output_state` to tell which.

## Rolling up cost / latency / failure-rate per agent

For an at-a-glance health line (one row per agent), aggregate
`$ai_generation`:

```sql
SELECT
    properties.$agent_application_id AS agent,
    uniq(properties.$ai_trace_id) AS sessions,
    sum(properties.$ai_total_cost_usd) AS cost_usd,
    sum(properties.$ai_input_tokens + properties.$ai_output_tokens) AS tokens,
    quantile(0.95)(properties.$ai_latency) AS p95_model_latency_s,
    countIf(properties.$ai_is_error = 1) AS model_errors
FROM events
WHERE event = '$ai_generation'
  AND timestamp > now() - INTERVAL 7 DAY
  AND notEmpty(properties.$agent_application_id)
GROUP BY agent
ORDER BY cost_usd DESC
```

This is the query a fleet-wide audit leans on for its per-agent
health line. Filter to one `$agent_application_id` for a
single-agent deep dive.

## How to use the evidence

- **Debugging:** cite the session id + turn + the specific
  `$ai_is_error` / `$ai_stop_reason` in your root-cause line. "Turn 12
  span `@posthog/query` returned is_error=1 (`timeout`)" beats "the
  query tool seems flaky".
- **Improving:** a finding needs a population, not an anecdote —
  "`@posthog/slack-post-message` failed in 9/40 sessions this week,
  all `not_in_channel`" is a proposal-worthy finding; one failure is
  noise.
- **Always offer the deep link.** PostHog Code's session page links
  straight to the trace in LLM Analytics — point the user there for
  the rich waterfall view rather than pasting a giant result set.

## Caveats

- **Gateway path zeroes `$ai_total_cost_usd`** on `$ai_generation`
  (the gateway owns billing; pi-ai's client-side number is an
  estimate). Token counts are still accurate. For true cost on the
  gateway path, the session row's `usage_total` is authoritative —
  read it via `posthog__agent-applications-sessions-retrieve`.
- **Emission is best-effort.** A dropped event means a slightly low
  count, never a wrong one. Don't treat counts as exact.
- **Heavy columns** (`$ai_input`, `$ai_output_choices`,
  `$ai_input_state`, `$ai_output_state`) are large — select them only
  for the specific span you're inspecting, never across a population
  query.
