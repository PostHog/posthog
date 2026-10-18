# Tracking gaps: query shapes

HogQL for `execute-sql`, validated against a busy project.
Every query on `events` keeps a `timestamp` bound. Start with the window shown and widen it only when the query returns in time.
Before you query a `system.*` table the first time in a run, confirm its columns in `system.information_schema.columns`.

Placeholders come from code or from ingestion, so treat them as data: escape every quote and backslash, and drop a value you cannot escape cleanly.

- `{event}`, `{terms}`: an event name and a list of search terms.
- `{server_libs}`, `{client_libs}`: the SDKs this project uses, from "SDK mix", for example `'posthog-python', 'posthog-node'` and `'web', 'posthog-ios'`.

## Family 1: proxy measurements

### Events split by URL in saved insights

```sql
WITH series AS (
  SELECT short_id, name, last_modified_at,
    arrayJoin(JSONExtractArrayRaw(assumeNotNull(ifNull(toString(query), '{}')), 'source', 'series')) AS s
  FROM system.insights
  WHERE deleted = 0 AND saved = 1 AND last_modified_at > now() - INTERVAL 180 DAY
)
SELECT
  JSONExtractString(s, 'kind') AS kind,
  if(JSONExtractString(s, 'kind') = 'ActionsNode', toString(JSONExtractInt(s, 'id')), JSONExtractString(s, 'event')) AS target,
  uniq(short_id) AS insights,
  max(last_modified_at) AS last_modified
FROM series
WHERE (s ILIKE '%"$pathname"%' OR s ILIKE '%"$current_url"%')
  AND JSONExtractString(s, 'event') NOT IN ('$pageview', '$pageleave', '$autocapture', '$screen', '$exception', '$rageclick', '$dead_click')
GROUP BY kind, target
ORDER BY insights DESC
LIMIT 40
```

Read one target's filters before you judge it (`JSONExtractRaw(s, 'properties')` for that target): the URL values say which dimension the team rebuilds.

### Does the event already carry the dimension?

```sql
SELECT key, count() AS with_key
FROM (
  SELECT arrayJoin(JSONExtractKeys(properties)) AS key
  FROM events
  WHERE timestamp > now() - INTERVAL 1 DAY AND event = {event}
)
WHERE NOT startsWith(key, '$')
GROUP BY key
ORDER BY with_key DESC
LIMIT 50
```

A key that names the split (`source`, `surface`, `product_key`, `placement`, `scene`, `context`) on most events means no code gap.
A key on 5% to 95% of events means some call sites drop it.

### Actions that stand in for an outcome

```sql
WITH series AS (
  SELECT id AS insight_id, short_id, last_modified_at,
    arrayJoin(JSONExtractArrayRaw(assumeNotNull(ifNull(toString(query), '{}')), 'source', 'series')) AS s
  FROM system.insights
  WHERE deleted = 0 AND saved = 1 AND last_modified_at > now() - INTERVAL 365 DAY
),
used AS (
  SELECT JSONExtractInt(s, 'id') AS action_id,
    uniq(short_id) AS insights,
    uniqIf(short_id, insight_id IN (SELECT insight_id FROM system.dashboard_tiles WHERE deleted = 0 OR deleted IS NULL)) AS on_dashboards,
    max(last_modified_at) AS last_edit
  FROM series
  WHERE JSONExtractString(s, 'kind') = 'ActionsNode'
  GROUP BY action_id
),
actions AS (
  SELECT id, name, JSONExtractArrayRaw(assumeNotNull(ifNull(toString(steps_json), '[]'))) AS steps
  FROM system.actions
  WHERE deleted = 0
)
SELECT a.id AS action_id, a.name AS name, u.insights AS insights, u.on_dashboards AS on_dashboards, toDate(u.last_edit) AS last_edit
FROM actions AS a
JOIN used AS u ON a.id = u.action_id
WHERE length(a.steps) > 0
  AND arrayAll(st -> JSONExtractString(st, 'event') IN ('$autocapture', '$pageview')
    AND NOT JSONExtractString(st, 'selector') ILIKE '%data-attr%', a.steps)
ORDER BY insights DESC
LIMIT 30
```

Most pageview actions measure a visit, and the visit is the right data ("Visited the billing page", a journey stage built from page groups).
A candidate is an action whose name is an outcome (submitted, signed up, subscribed, accepted, purchased, upgraded) while its steps are clicks or pageviews.
An action with a code event among its steps is not a proxy.

### How far the proxy is from the real event

```sql
SELECT
  toStartOfWeek(timestamp) AS week,
  countIf(matchesAction({action_id})) AS proxy,
  countIf(event = {event} {same_scope_filter}) AS code_event_same_scope
FROM events
WHERE timestamp > now() - INTERVAL 42 DAY
  AND event IN ('$autocapture', '$pageview', {event})
GROUP BY week
ORDER BY week
```

`{same_scope_filter}` repeats the proxy's own scope on the code event: the URL or path the action's steps match (`AND properties.$pathname LIKE '%/newsletter%'`), the host, the surface.
Without it the code event counts every page and the two numbers always disagree.
A gap of a quarter or more on the same scope, week after week, makes a config-only fix worth a report.

### Real events against a URL proxy

A pageview or URL-filtered proxy misses every view that happens without a URL change (an inline player, a modal, a side panel).
Count the real event split by the page it happened on, and how many of those carried the URL marker the proxy needs:

```sql
SELECT
  {page_bucket_expression} AS surface,
  count() AS events,
  uniq(person_id) AS people,
  countIf(properties.$current_url LIKE '%{url_marker}%') AS with_url_marker
FROM events
WHERE event = {event} AND timestamp > now() - INTERVAL 1 DAY
GROUP BY surface
ORDER BY events DESC
```

A surface where `with_url_marker` is near zero is a surface the proxy cannot see.

### Is the anchor read?

`insights-trending-retrieve` (`days=30`, `limit=100`) returns the insights people open, with `view_count`, `viewers`, and `dashboards`.
An anchor in that list, or on a dashboard listed with one that is, has readers.
`insight-get` returns `last_viewed_at` for the caller only, so it cannot show readership.

### Synonym search

Search the `read-data-schema` event list first: it names every event the project has seen, at no scan cost.
Use this query only for volume and last-seen time of the matches:

```sql
SELECT event, count() AS events, uniq(person_id) AS persons, max(timestamp) AS last_seen
FROM events
WHERE timestamp > now() - INTERVAL 30 DAY
  AND event NOT LIKE '$%'
  AND multiSearchAnyCaseInsensitive(event, [{terms}])
GROUP BY event
ORDER BY events DESC
LIMIT 50
```

## Family 2: owned problems nobody can diagnose

### Context on owned error issues

```sql
WITH ex AS (
  SELECT toString(properties.$exception_issue_id) AS issue_id, properties.$lib AS lib, person_id,
    properties.$session_id AS sid, toString(properties.$is_identified) AS ident,
    length(arrayFilter(k -> NOT startsWith(k, '$') AND k NOT IN ('token', 'distinct_id'), JSONExtractKeys(properties))) AS custom_keys
  FROM events
  WHERE event = '$exception' AND timestamp > now() - INTERVAL 2 DAY
),
owned AS (
  SELECT toString(id) AS id, name
  FROM system.error_tracking_issues
  WHERE status = 'active' AND toString(id) IN (SELECT toString(issue_id) FROM system.error_tracking_issue_assignments)
)
SELECT ex.issue_id AS issue_id, left(owned.name, 70) AS issue, any(ex.lib) AS lib,
  count() AS events, uniq(ex.person_id) AS persons,
  round(countIf(notEmpty(coalesce(ex.sid, ''))) / count(), 2) AS with_session,
  round(countIf(ex.ident = 'true') / count(), 2) AS identified,
  round(countIf(ex.custom_keys > 0) / count(), 2) AS with_custom_context
FROM ex
JOIN owned ON ex.issue_id = owned.id
GROUP BY issue_id, issue
ORDER BY persons DESC
LIMIT 25
```

`events` equal to `persons` on a busy issue means every exception got its own random distinct id: the issue cannot say who it hit.
`$is_identified` comes from client SDKs only; server rows read null.
With no assigned issues, rank active issues by reach with `query-error-tracking-issues-list` instead.

### Random distinct ids and groups on server exceptions

```sql
SELECT
  properties.$lib AS lib,
  notEmpty(coalesce(toString(properties.$request_path), '')) AS request_scoped,
  count() AS exceptions,
  round(countIf(match(distinct_id, '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')) / count(), 2) AS uuid_like_distinct_id,
  round(countIf(notEmpty($group_0)) / count(), 2) AS with_group_0,
  round(countIf(notEmpty(coalesce(properties.$session_id, ''))) / count(), 2) AS with_session
FROM events
WHERE event = '$exception' AND timestamp > now() - INTERVAL 1 HOUR AND properties.$lib IN ({server_libs})
GROUP BY lib, request_scoped
```

Request-scoped exceptions that carry random ids and no group, on a product with logged-in users, point at the capture helper or the middleware.
Two causes are common: the exception is captured outside the request's analytics context, or the request authenticates in the view (API keys, tokens) after the middleware that sets the identity has run.
Read where the identity is set and where the exception is captured before you propose the fix.
Read the group types from `system.group_type_mappings` (confirm its columns first) and use the `$group_<index>` column of the type you check.

### Failure events with one reason

```sql
SELECT
  event,
  uniq(coalesce(toString(properties.failure_reason), toString(properties.error_type), toString(properties.error), toString(properties.reason), '')) AS distinct_reasons,
  any(coalesce(toString(properties.failure_reason), toString(properties.error_type), toString(properties.error), toString(properties.reason), '')) AS sample_reason,
  count() AS failures
FROM events
WHERE timestamp > now() - INTERVAL 7 DAY
  AND event NOT LIKE '$%'
  AND (toString(properties.result) IN ('failed', 'error', 'failure')
    OR toString(properties.status) IN ('failed', 'error', 'failure')
    OR toString(properties.outcome) IN ('failed', 'error', 'failure')
    OR event ILIKE '%failed%')
GROUP BY event
HAVING failures >= 50
ORDER BY distinct_reasons ASC, failures DESC
LIMIT 25
```

A row with `distinct_reasons` of 0 or 1 is a candidate.
Before you call it a gap, list the event's error-like keys, because the cause may sit under another name:

```sql
SELECT event, groupUniqArray(key) AS error_like_keys
FROM (
  SELECT event, arrayJoin(arrayFilter(k -> match(lower(k), '(err|fail|reason|exception|code|message|cause|kind)') AND NOT startsWith(k, '$'), JSONExtractKeys(properties))) AS key
  FROM events
  WHERE timestamp > now() - INTERVAL 1 DAY AND event IN ({candidate_events})
)
GROUP BY event
```

Then find the demand: saved insights that read the event (`position(toString(query), '"<event>"') > 0` on `system.insights`), and whether people read them.

### Checks that could not measure

```sql
SELECT toDate(c.last_run_at) AS checked, c.title AS check_title, c.rationale, r.title AS report, r.status AS report_status
FROM system.inbox_report_checks AS c
LEFT JOIN system.inbox_reports AS r ON c.report_id = r.id
WHERE c.last_outcome = 'inconclusive'
  AND c.last_outcome_reason IN ('unmeasurable', 'needs_manual_verification')
  AND c.last_run_at > now() - INTERVAL 45 DAY
ORDER BY c.last_run_at DESC
LIMIT 50
```

Keep the checks whose rationale names a missing product event or property ("no event counts", "no event separates", "no property records"). Database, query-plan, and deploy claims are out of scope.

## Family 3: decisions waiting on data

### Partial rollouts with no experiment

```sql
WITH flags AS (
  SELECT id, key, created_at,
    JSONExtractArrayRaw(assumeNotNull(ifNull(toString(filters), '{}')), 'groups') AS groups,
    JSONExtractArrayRaw(assumeNotNull(ifNull(toString(filters), '{}')), 'multivariate', 'variants') AS variants
  FROM system.feature_flags
  WHERE deleted = 0 AND created_at > now() - INTERVAL 90 DAY
)
SELECT key, toDate(created_at) AS created, length(variants) AS n_variants,
  arrayMap(g -> JSONExtractRaw(g, 'rollout_percentage'), groups) AS rollouts
FROM flags
WHERE id NOT IN (SELECT feature_flag_id FROM system.experiments WHERE feature_flag_id IS NOT NULL)
  AND arrayExists(g -> toFloatOrZero(JSONExtractRaw(g, 'rollout_percentage')) > 0
    AND toFloatOrZero(JSONExtractRaw(g, 'rollout_percentage')) < 100
    AND length(JSONExtractArrayRaw(g, 'properties')) = 0, groups)
ORDER BY created DESC
LIMIT 40
```

Drop infrastructure switches (shadow reads, caches, prewarming, rate limits): read the flag's code path before you judge it.
For a product change, look for insights that break down by the flag (`toString(query) ILIKE '%<flag key>%'` on `system.insights`): those are hand-rolled experiments.

### Do an experiment's metric events fire?

Read the metrics with `experiment-get`, then count each metric event with the property its metric filters on since the start date:

```sql
SELECT event, count() AS events, uniq(person_id) AS persons, min(timestamp) AS first_seen, max(timestamp) AS last_seen
FROM events
WHERE timestamp > {experiment start} AND event IN ({metric events})
GROUP BY event
```

Compare with the step before the metric (the composer was viewed, the form was opened). A step that fires while its outcome never does is a candidate. Low counts on both mean low traffic.

## Family 4: tracking that broke

```sql
WITH referenced AS (
  SELECT JSONExtractString(s, 'event') AS event, uniq(short_id) AS insights
  FROM (
    SELECT short_id, arrayJoin(JSONExtractArrayRaw(assumeNotNull(ifNull(toString(query), '{}')), 'source', 'series')) AS s
    FROM system.insights
    WHERE deleted = 0 AND saved = 1 AND last_modified_at > now() - INTERVAL 365 DAY
  )
  WHERE JSONExtractString(s, 'kind') = 'EventsNode' AND NOT startsWith(JSONExtractString(s, 'event'), '$') AND JSONExtractString(s, 'event') != ''
  GROUP BY event
)
SELECT e.event AS event, any(r.insights) AS insights,
  countIf(e.timestamp > now() - INTERVAL 7 DAY) AS last_7d,
  round(countIf(e.timestamp <= now() - INTERVAL 7 DAY) / 4) AS prior_weekly_avg,
  max(e.timestamp) AS last_seen
FROM events AS e
JOIN referenced AS r ON e.event = r.event
WHERE e.timestamp > now() - INTERVAL 35 DAY
GROUP BY event
HAVING prior_weekly_avg >= 50 AND last_7d < prior_weekly_avg * 0.2
ORDER BY prior_weekly_avg DESC
LIMIT 30
```

A failure event that falls is good news, not a break.
Then `git log -S '<event name>' --format='%h %as %an %s' -- <source dirs>` on a tree with history, and read the diff.

## Shared

### SDK mix

```sql
SELECT
  properties.$lib AS lib,
  count() AS events,
  uniq(person_id) AS persons,
  round(countIf(notEmpty(coalesce(properties.$session_id, ''))) / count(), 3) AS session_id_share,
  round(countIf(event NOT LIKE '$%') / count(), 3) AS custom_share
FROM events
WHERE timestamp > now() - INTERVAL 1 HOUR
GROUP BY lib
ORDER BY events DESC
LIMIT 20
```

### Naming sample

```sql
SELECT event, count() AS events
FROM events
WHERE timestamp > now() - INTERVAL 1 DAY AND event NOT LIKE '$%'
GROUP BY event
ORDER BY events DESC
LIMIT 50
```

Derive the naming rule (case, word order, tense) and store it with the idioms.
