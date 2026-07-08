# AI observability events (`posthog.ai_events`)

LLM/AI events (`$ai_generation`, `$ai_span`, `$ai_trace`, `$ai_embedding`, `$ai_metric`, `$ai_feedback`, `$ai_evaluation`) are captured on the shared `events` table. The **heavy LLM properties are not stored on `events`** — they live as native columns on a dedicated ClickHouse table, `posthog.ai_events`.

**Namespacing:** Reference this table as `posthog.ai_events`, not bare `ai_events` — it's registered under the `posthog.` namespace in the HogQL database (see `posthog/hogql/database/database.py`), same as `posthog.trace_spans` / `posthog.metrics`. A bare `FROM ai_events` fails with "Unknown table" at HogQL compile time. (Asymmetric with `events` and `logs`, which are registered at root level.)

**Prefer the typed tools when they fit:** `posthog:query-llm-trace` for a single trace and `posthog:query-llm-traces-list` for listing both join `posthog.ai_events` for you. Reach for HogQL when you need custom aggregations, joins, or pre-filtering the typed tools don't expose.

## Which columns live where

`events` keeps the lightweight metadata — token counts, costs, model, provider, `$ai_trace_id`, latency, error flags (also mirrored as native columns on `posthog.ai_events`, where the `$ai_`-prefixed property maps to the un-prefixed column, e.g. `$ai_model` → `model`). The heavy properties live only on `posthog.ai_events`:

| Heavy content  | `events` property    | `posthog.ai_events` column |
| -------------- | -------------------- | -------------------------- |
| Input messages | `$ai_input`          | `input`                    |
| Output         | `$ai_output`         | `output`                   |
| Output choices | `$ai_output_choices` | `output_choices`           |
| Input state    | `$ai_input_state`    | `input_state`              |
| Output state   | `$ai_output_state`   | `output_state`             |
| Tools          | `$ai_tools`          | `tools`                    |

Nothing restricts which heavy columns an event can carry, but the typical shape is: `$ai_generation` carries `input` / `output_choices` / `tools` (embeddings carry `input`); `$ai_span` and `$ai_trace` carry `input_state` / `output_state`. The full native column list is in `posthog/hogql/database/schema/ai_events.py`.

## Access patterns

`posthog.ai_events` is `ORDER BY (team_id, trace_id, timestamp)`, so **`trace_id` is the access path, not `timestamp`**. Rows are dropped after the retention period (30 days by default), so traces older than that have no content.

**Single trace (you have the ID):** read it directly.

```sql
SELECT timestamp, span_id, event, model, input, output_choices
FROM posthog.ai_events
WHERE trace_id = '<trace_id>'
ORDER BY timestamp
```

**Batch / analytics (a time window across many traces):** filter the timestamp-indexed `events` table to get the trace IDs, then fetch the heavy content from `posthog.ai_events` anchored on `trace_id`.

```sql
WITH matching_traces AS (
    SELECT DISTINCT properties.$ai_trace_id AS trace_id
    FROM events
    WHERE event = '$ai_generation'
        AND timestamp >= now() - INTERVAL 7 DAY
        AND properties.$ai_model = 'gpt-4o'
)
SELECT a.trace_id, a.span_id, a.model, a.input, a.output_choices
FROM posthog.ai_events AS a
WHERE a.trace_id IN (SELECT trace_id FROM matching_traces)
ORDER BY a.trace_id, a.timestamp
```
