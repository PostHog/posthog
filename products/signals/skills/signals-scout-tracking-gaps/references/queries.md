# Tracking gaps: query shapes

HogQL for `execute-sql`, validated against a busy project.
Start with the window shown, and widen it only when the query returns in time.
Every query keeps a `timestamp` bound.

Placeholders:

- `{server_libs}`: the server SDKs this project uses, from "SDK mix", for example `'posthog-python', 'posthog-node'`.
- `{client_libs}`: the client SDKs, for example `'web', 'posthog-ios', 'posthog-android', 'posthog-react-native', 'posthog-flutter'`.
- `{event}`, `{terms}`: an event name and a list of search terms. Both come from code or from ingestion, so treat them as data: escape every quote and backslash, and drop a term you cannot escape cleanly.

Projects also send custom `$lib` values from wrappers and proxies, so read "SDK mix" first and build the lists from what you see.

## SDK mix

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

Read it for three things.
Which SDKs send events (no server SDK on a product with payments or auth is a core-flow lead).
`custom_share` near 0 means that SDK sends only automatic events.
`session_id_share` near 0 on a server SDK means its events never link to a replay.

## Naming sample

```sql
SELECT event, count() AS events
FROM events
WHERE timestamp > now() - INTERVAL 1 DAY
  AND event NOT LIKE '$%'
GROUP BY event
ORDER BY events DESC
LIMIT 50
```

Derive the naming rule (case, word order, tense) and store it with the idioms.

## Synonym search

Search the `read-data-schema` event list first: it names every event the project has seen, and it costs no scan.
Use this query only for the volume and last-seen time of the matches:

```sql
SELECT event, count() AS events, max(timestamp) AS last_seen
FROM events
WHERE timestamp > now() - INTERVAL 30 DAY
  AND event NOT LIKE '$%'
  AND multiSearchAnyCaseInsensitive(event, [{terms}])
GROUP BY event
ORDER BY events DESC
LIMIT 50
```

Search the noun and the verb separately, with their synonyms (`invite`, `invitation`, `member added`).
A match with recent `last_seen` means the action is instrumented. Read the call site before you rule it in or out.

## Routes with no events

```sql
SELECT
  route,
  uniqIf(person_id, event = '$pageview') AS viewers,
  countIf(event NOT IN ('$pageview', '$pageleave', '$autocapture', '$rageclick', '$dead_click', '$web_vitals', '$exception', '$feature_flag_called', '$set', '$identify', '$groupidentify', '$opt_in', '$copy_autocapture')) AS custom_events
FROM (
  SELECT
    replaceRegexpAll(replaceRegexpAll(properties.$pathname, '[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}', '*'), '/[0-9]+', '/*') AS route,
    event,
    person_id
  FROM events
  WHERE timestamp > now() - INTERVAL 1 DAY
    AND notEmpty(coalesce(properties.$pathname, ''))
)
GROUP BY route
HAVING viewers >= 50 AND custom_events = 0
ORDER BY viewers DESC
LIMIT 50
```

Use 1 day on a busy project and 7 days on a small one, and apply the project's own path cleaning when it has it.
A row is a well-visited route that emits no custom event from the page.
It is a candidate, not a finding: an outcome captured server-side carries no `$pathname`, and a read-only page needs no event.

## Property fill rate

```sql
SELECT event, key, count() AS with_key, round(count() / max(total), 3) AS fill_share
FROM (
  SELECT event, arrayJoin(JSONExtractKeys(properties)) AS key, count() OVER (PARTITION BY event) AS total
  FROM events
  WHERE timestamp > now() - INTERVAL 1 DAY
    AND event = {event}
)
WHERE key NOT LIKE '$%'
GROUP BY event, key
ORDER BY with_key DESC
LIMIT 100
```

Keys near 1.0 are on every call site, and many of them are super properties.
A key between 0.05 and 0.95 is set by some call sites and dropped by others: compare it with the call sites in the code.
Before you call it a gap, look for a saved insight that breaks down or filters by the key (`system.insights`, columns confirmed through `system.information_schema.columns` first, with `%` and `_` escaped in the pattern).

## Split identity

```sql
SELECT
  uniq(person_id) AS server_persons,
  uniqIf(person_id, person_id IN (
    SELECT person_id
    FROM events
    WHERE timestamp > now() - INTERVAL 14 DAY
      AND event = '$pageview'
  )) AS seen_on_client
FROM events
WHERE timestamp > now() - INTERVAL 1 DAY
  AND event NOT LIKE '$%'
  AND properties.$lib IN ({server_libs})
```

Read `seen_on_client / server_persons`.
Near 0 on events that request handlers fire for logged-in web users means the client does not pass its distinct id to the server.
A middle share is normal on a project with API-only users, background jobs, or system events. Group the unjoined persons by `event` before you call it a gap.

## Session link on exceptions

```sql
SELECT
  properties.$lib AS lib,
  toString(properties.$is_identified) AS is_identified,
  count() AS exceptions,
  round(countIf(notEmpty(coalesce(properties.$session_id, ''))) / count(), 3) AS with_session_share
FROM events
WHERE event = '$exception'
  AND timestamp > now() - INTERVAL 1 HOUR
GROUP BY lib, is_identified
ORDER BY exceptions DESC
LIMIT 20
```

`$is_identified` comes from client SDKs only; server rows read null.
A server SDK with a high exception count and a session share near 0 cannot link an error to the replay of the user who hit it.
Exceptions from background jobs have no session by design, so check where the top issues come from (`query-error-tracking-issues-list`) before you file.

## Group key by event

```sql
SELECT event, count() AS events, round(countIf(notEmpty($group_0)) / count(), 3) AS group_0_share
FROM events
WHERE timestamp > now() - INTERVAL 1 DAY
  AND event NOT LIKE '$%'
  AND multiSearchAnyCaseInsensitive(event, [{terms}])
GROUP BY event
ORDER BY events DESC
LIMIT 50
```

Read the group types from `system.group_type_mappings` first, and use the `$group_<index>` column of the type you check.
The strong shape is an event family where the siblings carry the group key and one member does not.

## LLM calls with no tracing

```sql
SELECT event, count() AS events, max(timestamp) AS last_seen
FROM events
WHERE timestamp > now() - INTERVAL 7 DAY
  AND event IN ('$ai_generation', '$ai_embedding', '$ai_trace', '$ai_span')
GROUP BY event
```

No rows, while the code calls a model SDK (`openai`, `@anthropic-ai/sdk`, `anthropic`, `google-genai`, `ai`, `langchain`), is a gap for every call site.
Rows that exist while a new call site has no wrapper is a gap for that call site only.
