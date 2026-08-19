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

## Was partial-response collection ever on?

```sql
SELECT
  coalesce(toString(properties.$survey_completed), '(not set)') AS completed,
  count() AS events,
  uniq(properties.$survey_submission_id) AS submissions,
  min(timestamp) AS first_seen, max(timestamp) AS last_seen
FROM events
WHERE event = 'survey sent' AND properties.$survey_id = '<SURVEY_ID>'
  AND timestamp >= now() - INTERVAL 180 DAY
GROUP BY completed ORDER BY events DESC
```

Any `completed = false` rows ⇒ `enable_partial_responses` was `true` in that window, so raw
`survey sent` rows include intermediate saves the UI collapses. `(not set)` ⇒ pre-1.240.0 SDK.
Compare `events` vs `submissions` to see how much of the gap is partial saves.

## Full event funnel including abandonment

```sql
SELECT event, count() AS events,
  uniq(distinct_id) AS people,
  uniq(properties.$survey_submission_id) AS submissions
FROM events
WHERE properties.$survey_id = '<SURVEY_ID>'
  AND event IN ('survey shown', 'survey sent', 'survey dismissed', 'survey abandoned')
  AND timestamp >= now() - INTERVAL 180 DAY
GROUP BY event ORDER BY events DESC
```

`events` above `submissions` on `survey sent` is the normal partial-response shape — partial mode
fires one `survey sent` per question (see above), so the raw event count inflates on its own.
Compare `submissions` against `people` instead: `submissions` well above `people` ⇒ repeat
responders, one likely cause being `schedule: 'always'` bypassing the internal targeting flag.
(`people` is `uniq(distinct_id)`, which one person spread across several IDs inflates, so this
comparison undercounts repeats rather than inventing them.)

## Every question and its answer, keyed off the survey JSON (preferred)

Take the ids from `questions[].id` and name the columns. Never guess which UUID is which
question — backtick the property because of the dashes.

```sql
SELECT timestamp,
  coalesce(person.properties.$email, person.properties.email) AS email,
  properties.`$survey_response_<Q1_UUID>` AS q1,
  properties.`$survey_response_<Q2_UUID>` AS q2,
  properties.$survey_completed AS completed,
  properties.$survey_submission_id AS submission_id
FROM events
WHERE event = 'survey sent' AND properties.$survey_id = '<SURVEY_ID>'
  AND timestamp >= now() - INTERVAL 180 DAY
ORDER BY timestamp DESC LIMIT 60
```

## Same thing without the survey JSON: unroll `$survey_questions`

`$survey_questions` is an array of `{id, question, response}` over the full question list, so the
arrays line up positionally with the survey's questions. Note the `ifNull` — without it ClickHouse
rejects the query with `Nested type Array(String) cannot be inside Nullable type`, because
`properties.$survey_questions` is `Nullable(String)`.

```sql
SELECT timestamp,
  properties.$survey_submission_id AS submission_id,
  properties.$survey_completed AS completed,
  arrayMap(x -> JSONExtractString(x, 'question'),
    JSONExtractArrayRaw(ifNull(toString(properties.$survey_questions), '[]'))) AS questions,
  arrayMap(x -> JSONExtractRaw(x, 'response'),
    JSONExtractArrayRaw(ifNull(toString(properties.$survey_questions), '[]'))) AS responses
FROM events
WHERE event = 'survey sent' AND properties.$survey_id = '<SURVEY_ID>'
  AND timestamp >= now() - INTERVAL 180 DAY
ORDER BY timestamp DESC LIMIT 60
```

## Answer rate per question (is "incomplete" just branching?)

Cross-tab the branching question's answer against whether the downstream questions got values. If
the split lines up exactly with the branching rules, the data is fine and the complaint is
explained.

```sql
SELECT properties.`$survey_response_<BRANCHING_Q_UUID>` AS branch_answer,
  count() AS submissions,
  countIf(coalesce(toString(properties.`$survey_response_<DOWNSTREAM_Q_UUID>`), '') != '') AS answered_downstream
FROM events
WHERE event = 'survey sent' AND properties.$survey_id = '<SURVEY_ID>'
  AND coalesce(toString(properties.$survey_completed), 'true') != 'false'
  AND timestamp >= now() - INTERVAL 180 DAY
GROUP BY branch_answer ORDER BY branch_answer
```

## Shown → sent latency (accidental / stray-click submissions)

`survey shown` fires when the popup becomes visible, _after_ `surveyPopupDelaySeconds`, so this is
real time-on-popup. A cluster of sub-10-second completions on a multi-question survey points at
`skipSubmitButton` plus a centred popup rather than considered feedback.

```sql
SELECT $session_id AS session,
  minIf(timestamp, event = 'survey shown') AS shown_at,
  minIf(timestamp, event = 'survey sent') AS sent_at,
  dateDiff('second', minIf(timestamp, event = 'survey shown'),
    minIf(timestamp, event = 'survey sent')) AS seconds_to_submit
FROM events
WHERE properties.$survey_id = '<SURVEY_ID>'
  AND event IN ('survey shown', 'survey sent')
  AND timestamp >= now() - INTERVAL 180 DAY
GROUP BY session HAVING sent_at > shown_at
ORDER BY seconds_to_submit ASC LIMIT 60
```

## Replay link per response (watch a disputed submission)

```sql
SELECT timestamp, distinct_id,
  coalesce(person.properties.$email, person.properties.email) AS email,
  properties.sessionRecordingUrl AS replay_url,
  properties.$survey_submission_id AS submission_id, $session_id
FROM events
WHERE event = 'survey sent' AND properties.$survey_id = '<SURVEY_ID>'
  AND timestamp >= now() - INTERVAL 180 DAY
ORDER BY timestamp DESC
LIMIT 1 BY coalesce(nullIf(properties.$survey_submission_id, ''), toString(uuid))
LIMIT 60
```

Beats arguing about whether a submission was intentional — when a recording exists. Every
`survey sent` / `dismissed` / `abandoned` event carries `sessionRecordingUrl`, but that only points
at a session id: replay is off by default, and the default cloud retention of 30 days is shorter
than this 180-day window, so the recording may never have been captured or may have aged out. Open
the link before citing it. The `LIMIT 1 BY` collapses partial mode's
per-question `survey sent` rows to the latest one per submission — matching how the results table
dedupes — so you get one link per response, not one per intermediate save. The `coalesce` falls
back to the event UUID for pre-1.240.0 events, which have no `$survey_submission_id`, so those are
kept as distinct rows rather than folded together.
