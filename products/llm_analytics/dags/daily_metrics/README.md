# LLMA Daily Metrics Pipeline

Daily aggregation of AI event metrics into the `llma_metrics_daily` ClickHouse
table.

## Overview

Aggregates AI event metrics ($ai_trace, $ai_generation, $ai_span,
$ai_embedding) by team and date into a long-format metrics table for efficient
querying.

## Architecture

The pipeline uses a modular SQL template system:

- Each metric type lives in its own `.sql` file under `sql/`
- Templates are auto-discovered and combined with UNION ALL
- To add a new metric, simply drop a new `.sql` file in the directory

### SQL Template Format

Each SQL file should return these columns:

```sql
SELECT
    date(timestamp) as date,
    team_id,
    'metric_name' as metric_name,
    toFloat64(value) as metric_value
FROM llma_events
GROUP BY ...
```

The following CTEs are automatically provided:

- `llma_events`: AI events pre-filtered to teams with AI activity
- `llma_pageview_events`: Pageview events pre-filtered to teams viewing LLM analytics pages

This two-step filtering (first find teams, then filter events) allows ClickHouse to
use the sorting key (team_id, timestamp) efficiently.

Templates have access to these Jinja2 variables:

- `event_types`: List of AI event types to aggregate
- `metric_date`: The date being aggregated (YYYY-MM-DD)
- `pageview_mappings`: List of (url_path, metric_suffix) tuples for pageview categorization
- `include_error_rates`: Boolean flag for error rate calculation (default: true)

## Output Schema

```sql
CREATE TABLE llma_metrics_daily (
    date Date,
    team_id UInt64,
    metric_name String,
    metric_value Float64
) ENGINE = ReplicatedMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (team_id, date, metric_name)
```

Long format allows adding new metrics without schema changes.

## Current Metrics

### Event Counts

Defined in `sql/event_counts.sql`:

- `ai_generation_count`: Number of AI generation events
- `ai_trace_count`: Number of AI trace events
- `ai_span_count`: Number of AI span events
- `ai_embedding_count`: Number of AI embedding events

Each event is counted individually, even if multiple events share the same trace_id.

### Trace Counts

Defined in `sql/trace_counts.sql`:

- `ai_trace_id_count`: Number of unique traces (distinct $ai_trace_id values)

Counts unique traces across all AI event types. A trace may contain multiple events (generations, spans, etc).

### Session Counts

Defined in `sql/session_counts.sql`:

- `ai_session_id_count`: Number of unique sessions (distinct $ai_session_id values)

Counts unique sessions across all AI event types. A session can link multiple related traces together.

### Event Error Rates

Defined in `sql/error_rates.sql`:

- `ai_generation_error_rate`: Proportion of AI generation events with errors (0.0 to 1.0)
- `ai_trace_error_rate`: Proportion of AI trace events with errors (0.0 to 1.0)
- `ai_span_error_rate`: Proportion of AI span events with errors (0.0 to 1.0)
- `ai_embedding_error_rate`: Proportion of AI embedding events with errors (0.0 to 1.0)

### Trace Error Rates

Defined in `sql/trace_error_rates.sql`:

- `ai_trace_id_has_error_rate`: Proportion of unique traces that had at least one error (0.0 to 1.0)

A trace is considered errored if ANY event within it has an error. Compare with event error rates which report the proportion of individual events with errors.

### Pageview Metrics

Defined in `sql/pageview_counts.sql`:

- `pageviews_traces`: Pageviews on /llm-analytics/traces
- `pageviews_generations`: Pageviews on /llm-analytics/generations
- `pageviews_users`: Pageviews on /llm-analytics/users
- `pageviews_sessions`: Pageviews on /llm-analytics/sessions
- `pageviews_playground`: Pageviews on /llm-analytics/playground
- `pageviews_datasets`: Pageviews on /llm-analytics/datasets
- `pageviews_evaluations`: Pageviews on /llm-analytics/evaluations

Tracks $pageview events on LLM Analytics pages. URL patterns are mapped to page types via config.pageview_mappings.

### Error Detection

All error metrics detect errors by checking for:

- `$ai_error` property is non-empty
- `$ai_is_error` property is true

## Configuration

See `config.py` for configuration options:

- `partition_start_date`: First date to backfill (default: 2025-01-01)
- `cron_schedule`: Schedule for daily runs (default: 6 AM UTC)
- `max_partitions_per_run`: Max partitions to process in backfill (default: 14)
- `ai_event_types`: List of AI event types to track (default: $ai_trace, $ai_generation, $ai_span, $ai_embedding)
- `pageview_mappings`: URL path to metric name mappings for pageview tracking
- `include_error_rates`: Enable error rate metrics (default: true)

## Schedule

Runs daily at 6 AM UTC for the previous day's partition.

## Local Development

Query results in ClickHouse:

```bash
docker exec posthog-clickhouse-1 clickhouse-client --query \
  "SELECT * FROM llma_metrics_daily WHERE date = today() FORMAT Pretty"
```

Or use HogQL in PostHog UI:

```sql
SELECT
    date,
    metric_name,
    sum(metric_value) as total
FROM llma_metrics_daily
WHERE date >= today() - INTERVAL 7 DAY
GROUP BY date, metric_name
ORDER BY date DESC, metric_name
```

## Testing

Run the test suite to validate SQL structure and logic:

```bash
python -m pytest products/llm_analytics/dags/tests/daily_metrics/test_sql_metrics.py -v
```

Tests validate:

- SQL templates render without errors
- All SQL files produce the correct 4-column output
- Calculation logic is correct (using mock data)
- Date filtering and grouping work as expected

Test file location: `products/llm_analytics/dags/tests/daily_metrics/test_sql_metrics.py`

## Adding New Metrics

1. Create a new SQL file in `sql/` (e.g., `sql/token_counts.sql`)
2. Query from `llma_events` (pre-filtered CTE) for AI event metrics
3. Return columns: `date`, `team_id`, `metric_name`, `metric_value`
4. The pipeline will automatically discover and include it
5. Add test coverage in `products/llm_analytics/dags/tests/daily_metrics/test_sql_metrics.py` with mock data and expected output

Example:

```sql
SELECT
    date(timestamp) as date,
    team_id,
    concat(substring(event, 2), '_tokens') as metric_name,
    toFloat64(sum(JSONExtractInt(properties, '$ai_total_tokens'))) as metric_value
FROM llma_events
GROUP BY date, team_id, event
HAVING metric_value > 0
```
