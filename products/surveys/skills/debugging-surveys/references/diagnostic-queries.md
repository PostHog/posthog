# Diagnostic queries (HogQL, read-only)

Run via the PostHog MCP `execute-sql` against the customer's project. Adjust the date and
survey ID. Tables: `events`, `static_cohort_people` (NOT `person_static_cohort` — that's
the ClickHouse name; HogQL exposes `static_cohort_people`), `persons`.

## Shown vs sent, before/after a change (the "none vs fewer" disambiguator)

```sql
SELECT
  countIf(event = 'survey shown' AND timestamp < toDateTime('<CUTOFF>')) AS shown_before,
  countIf(event = 'survey shown' AND timestamp >= toDateTime('<CUTOFF>')) AS shown_after,
  countIf(event = 'survey sent' AND timestamp < toDateTime('<CUTOFF>')) AS sent_before,
  countIf(event = 'survey sent' AND timestamp >= toDateTime('<CUTOFF>')) AS sent_after
FROM events
WHERE properties.$survey_id = '<SURVEY_ID>' AND timestamp >= toDateTime('<WINDOW_START>')
```

Stable sent/shown ratio ⇒ upstream eligibility issue, not rendering/submission. Always
normalize by period length (before vs after windows are rarely equal).

## What did the gating flag return, and was group context set

```sql
SELECT distinct_id, timestamp,
  properties.$feature_flag_response AS flag_response,
  properties.$groups AS groups_in_session,
  person.properties.email AS email
FROM events
WHERE event = '$feature_flag_called'
  AND properties.$feature_flag = '<FLAG_KEY>'
  AND timestamp >= toDateTime('<WINDOW_START>')
ORDER BY timestamp DESC LIMIT 50
```

All `false` with empty `$groups` ⇒ group-aggregated flag without `posthog.group()`.

## Did a static cohort actually populate (with country breakdown)

```sql
SELECT cohort_id, count() AS persons,
  countIf(person.properties.$geoip_country_code = 'DE') AS in_DE
FROM static_cohort_people
WHERE team_id = <TEAM_ID> AND cohort_id IN (<IDS>)
GROUP BY cohort_id
```

## Real reach by survey, before/after a date (find the affected surveys)

```sql
SELECT properties.$survey_id AS survey_id,
  countIf(timestamp < toDateTime('<CUTOFF>')) AS shown_before,
  countIf(timestamp >= toDateTime('<CUTOFF>')) AS shown_after,
  uniqIf(distinct_id, timestamp >= toDateTime('<CUTOFF>')) AS users_after
FROM events
WHERE event = 'survey shown' AND timestamp >= toDateTime('<WINDOW_START>')
GROUP BY survey_id HAVING shown_before > 0 OR shown_after > 0
ORDER BY shown_before DESC
```
