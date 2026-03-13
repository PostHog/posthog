# Evaluation query examples

All queries use HogQL and filter on `event = '$ai_evaluation'`.
Always include a time range to keep queries efficient.

## Pass rate for an evaluation

```sql
SELECT
    countIf(properties.$ai_evaluation_result = true AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as pass_count,
    countIf(properties.$ai_evaluation_result = false AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as fail_count,
    countIf(properties.$ai_evaluation_applicable = false) as na_count,
    round(if(pass_count + fail_count = 0, null, pass_count / (pass_count + fail_count) * 100), 1) as pass_rate
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_evaluation_id = '<evaluation_uuid>'
    AND timestamp > now() - interval 7 day
```

## Pass rate by model

```sql
SELECT
    g.properties.$ai_model as model,
    countIf(e.properties.$ai_evaluation_result = true) as pass_count,
    countIf(e.properties.$ai_evaluation_result = false) as fail_count,
    round(if(pass_count + fail_count = 0, null, pass_count / (pass_count + fail_count) * 100), 1) as pass_rate
FROM events e
JOIN events g ON g.uuid = e.properties.$ai_target_event_id
WHERE e.event = '$ai_evaluation'
    AND e.properties.$ai_evaluation_id = '<evaluation_uuid>'
    AND e.timestamp > now() - interval 7 day
    AND g.event = '$ai_generation'
GROUP BY model
ORDER BY fail_count DESC
```

## Pass rate over time (daily trend)

```sql
SELECT
    toDate(timestamp) as day,
    countIf(properties.$ai_evaluation_result = true) as pass_count,
    countIf(properties.$ai_evaluation_result = false) as fail_count,
    round(if(pass_count + fail_count = 0, null, pass_count / (pass_count + fail_count) * 100), 1) as pass_rate
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_evaluation_id = '<evaluation_uuid>'
    AND timestamp > now() - interval 30 day
GROUP BY day
ORDER BY day
```

## Recent failing generations with reasoning

```sql
SELECT
    properties.$ai_target_event_id as generation_id,
    properties.$ai_evaluation_reasoning as reasoning,
    timestamp
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_evaluation_id = '<evaluation_uuid>'
    AND properties.$ai_evaluation_result = false
    AND timestamp > now() - interval 7 day
ORDER BY timestamp DESC
LIMIT 20
```

## All evaluation results for a specific generation

```sql
SELECT
    properties.$ai_evaluation_id as evaluation_id,
    properties.$ai_evaluation_name as evaluation_name,
    properties.$ai_evaluation_result as result,
    properties.$ai_evaluation_reasoning as reasoning,
    properties.$ai_evaluation_applicable as applicable
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_target_event_id = '<generation_event_uuid>'
ORDER BY timestamp DESC
```

## Evaluations summary across all evaluations

```sql
SELECT
    properties.$ai_evaluation_name as evaluation_name,
    properties.$ai_evaluation_id as evaluation_id,
    count() as total_runs,
    countIf(properties.$ai_evaluation_result = true) as pass_count,
    countIf(properties.$ai_evaluation_result = false) as fail_count,
    round(if(pass_count + fail_count = 0, null, pass_count / (pass_count + fail_count) * 100), 1) as pass_rate
FROM events
WHERE event = '$ai_evaluation'
    AND timestamp > now() - interval 7 day
GROUP BY evaluation_name, evaluation_id
ORDER BY total_runs DESC
```
