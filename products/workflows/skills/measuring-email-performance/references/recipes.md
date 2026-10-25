# Email performance SQL recipes

Run each recipe with `posthog:execute-sql`.
All but **Clicked links** read the captured `$workflows_email_*` events, so they return nothing in a project that does not capture engagement events (see "Check the data exists" in the skill).
The events carry the workflow id for every kind of workflow, broadcasts and batch runs included.

Replace every `{placeholder}` with a literal before you run the query:

| Placeholder       | Holds                                                               | Write it as                                |
| ----------------- | ------------------------------------------------------------------- | ------------------------------------------ |
| `{workflow_id}`   | The workflow's UUID                                                 | `'01a1...'`                                |
| `{step_id}`       | The email step's action id from `posthog:workflows-get`             | `'action_function_email_...'`              |
| `{window_start}`  | Start of the window, inclusive, at the start of a UTC day           | `toDateTime('2026-10-12 00:00:00', 'UTC')` |
| `{window_end}`    | End of the window, exclusive, at the start of a UTC day in the past | `toDateTime('2026-10-19 00:00:00', 'UTC')` |
| `{outcome_event}` | The product event that counts as the outcome, checked in the schema | `'insight created'`                        |
| `{outcome_days}`  | How many days after the send the outcome may happen                 | `7`                                        |
| `{person_id}`     | One person's UUID                                                   | `'0189...'`                                |

## Recipes

### Step engagement

Every email step of one workflow, in event occurrences and in distinct people.
`tracked_sent` is the denominator for opens and clicks, because a send with tracking off can never record either.
`people_tracked` is the denominator for `openers` and `clickers`: people over people.
Bounces and spam complaints divide by `sent`. Hard bounces are the addresses that will never accept mail; soft bounces may succeed later.

```sql
SELECT
    properties.$workflow_action_id AS step,
    countIf(event = '$workflows_email_sent') AS sent,
    countIf(event = '$workflows_email_sent' AND toString(properties.$email_tracking_enabled) = 'true') AS tracked_sent,
    uniqIf(person_id, event = '$workflows_email_sent') AS people_sent,
    uniqIf(person_id, event = '$workflows_email_sent' AND toString(properties.$email_tracking_enabled) = 'true') AS people_tracked,
    countIf(event = '$workflows_email_delivered') AS delivered,
    countIf(event = '$workflows_email_opened') AS opens,
    uniqIf(person_id, event = '$workflows_email_opened') AS openers,
    countIf(event = '$workflows_email_link_clicked') AS clicks,
    uniqIf(person_id, event = '$workflows_email_link_clicked') AS clickers,
    countIf(event = '$workflows_email_bounced') AS bounces,
    countIf(event = '$workflows_email_bounced' AND properties.$bounce_type = 'hard') AS hard_bounces,
    countIf(event = '$workflows_email_blocked') AS spam_complaints
FROM events
WHERE timestamp >= {window_start}
    AND timestamp < {window_end}
    AND event LIKE '$workflows_email_%'
    AND properties.$workflow_id = {workflow_id}
GROUP BY step
ORDER BY sent DESC
```

`tracked_sent` is 0 for sends made before the sent event carried `$email_tracking_enabled`. When it is 0 while opens exist, read opens and clicks against the counters instead.

### Engagement by version

One step's callbacks split by the version that sent them.
Use it when `posthog:workflows-version-stats` is not available.
The sent event carries no version, so `delivered` is the per-version denominator, and the tracked share of each version is unknown.

```sql
SELECT
    toString(properties.$workflow_version) AS version,
    countIf(event = '$workflows_email_delivered') AS delivered,
    countIf(event = '$workflows_email_opened') AS opens,
    uniqIf(person_id, event = '$workflows_email_opened') AS openers,
    countIf(event = '$workflows_email_link_clicked') AS clicks,
    uniqIf(person_id, event = '$workflows_email_link_clicked') AS clickers,
    countIf(event = '$workflows_email_bounced') AS bounces,
    countIf(event = '$workflows_email_blocked') AS spam_complaints
FROM events
WHERE timestamp >= {window_start}
    AND timestamp < {window_end}
    AND event IN ('$workflows_email_delivered', '$workflows_email_opened', '$workflows_email_link_clicked', '$workflows_email_bounced', '$workflows_email_blocked')
    AND properties.$workflow_id = {workflow_id}
    AND properties.$workflow_action_id = {step_id}
GROUP BY version
ORDER BY toInt(version)
```

A row with no `version` holds callbacks whose message carried no version: sends from before versions were recorded, and messages whose version did not survive the provider's callback. Report it as unattributed, never as a version.
A version that went live before the window can still show opens and clicks in it: they belong to its older sends.

### Clicked links

Which links of one step get clicked, by position in the email and URL.
It reads the per-link click counter, not the click events: the counter stores each URL without its query string and with personal path segments, such as tokens and ids, replaced by `*`.
The click events keep the full URL, tokens included, so never group them by `$link_url`.

```sql
SELECT
    splitByChar('|', instance_id)[2] AS link_index,
    arrayStringConcat(arraySlice(splitByChar('|', instance_id), 3), '|') AS link,
    sum(count) AS clicks
FROM app_metrics
WHERE app_source = 'hog_flow_version'
    AND startsWith(app_source_id, concat({workflow_id}, '/'))
    AND metric_name = 'email_link_clicked_by_link'
    AND startsWith(instance_id, concat({step_id}, '|'))
    AND timestamp >= {window_start}
    AND timestamp < {window_end}
GROUP BY link_index, link
ORDER BY clicks DESC
LIMIT 50
```

`clicks` are occurrences. It reads the versioned series, because that one is keyed by the workflow for broadcasts and batch runs too, so clicks whose message carried no version are missing.
For people per link, count distinct `person_id` on `$workflows_email_link_clicked` grouped by `$link_index` only.

### Product outcome after the first send

The people a step sent to in the window, and how many did the outcome event within `{outcome_days}` days after their first send in the window.
The query reads only the recipients' events, so a common outcome event stays cheap.
`recipients` counts only people whose whole outcome window has closed; `recipients_still_in_window` counts the rest, who have not had the time yet.

```sql
SELECT
    countIf(window_closed) AS recipients,
    countIf(window_closed AND reached_outcome) AS reached_outcome,
    countIf(NOT window_closed) AS recipients_still_in_window
FROM (
    SELECT
        first_sent_at + toIntervalDay({outcome_days}) <= now() AS window_closed,
        arrayExists(t -> t > first_sent_at AND t <= first_sent_at + toIntervalDay({outcome_days}), outcome_times) AS reached_outcome
    FROM (
        SELECT
            person_id,
            minIf(timestamp, event = '$workflows_email_sent') AS first_sent_at,
            groupArrayIf(timestamp, event = {outcome_event}) AS outcome_times
        FROM events
        WHERE timestamp >= {window_start}
            AND timestamp < {window_end} + toIntervalDay({outcome_days})
            AND (
                (
                    event = '$workflows_email_sent'
                    AND timestamp < {window_end}
                    AND properties.$workflow_id = {workflow_id}
                    AND properties.$workflow_action_id = {step_id}
                )
                OR event = {outcome_event}
            )
            AND person_id IN (
                SELECT person_id
                FROM events
                WHERE timestamp >= {window_start}
                    AND timestamp < {window_end}
                    AND event = '$workflows_email_sent'
                    AND properties.$workflow_id = {workflow_id}
                    AND properties.$workflow_action_id = {step_id}
            )
        GROUP BY person_id
        HAVING countIf(event = '$workflows_email_sent') > 0
    )
)
```

The outcome only counts when the email and the product events land on the same person.
That holds when the workflow sends with the app's own distinct ID; a send addressed only by email can sit on a separate person.

### One person's email history

One person's email events and outcome events in the window, in order.

```sql
SELECT
    timestamp,
    event,
    properties.$workflow_id AS workflow_id,
    properties.$workflow_action_id AS step,
    properties.$link_index AS link_index
FROM events
WHERE person_id = {person_id}
    AND timestamp >= {window_start}
    AND timestamp < {window_end}
    AND (event LIKE '$workflows_email_%' OR event = {outcome_event})
ORDER BY timestamp
LIMIT 500
```

If it returns 500 rows, the rest of the window is cut off: narrow the window and run it again.
To see everything the person did after one email, drop the event condition and narrow the window to the day after that send.

Unsubscribes are not in it: `$workflows_email_unsubscribed` uses the email address as its distinct ID, so it lands on a different person.
