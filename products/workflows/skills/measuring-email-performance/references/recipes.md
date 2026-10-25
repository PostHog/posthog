# Email performance SQL recipes

Run each recipe with `execute-sql`.
They read the captured `$workflows_email_*` events, so they return nothing in a project that does not capture engagement events (see "Check the data exists" in the skill).

Replace every `{placeholder}` with a literal before you run the query:

| Placeholder       | Holds                                                               | Write it as                                |
| ----------------- | ------------------------------------------------------------------- | ------------------------------------------ |
| `{workflow_id}`   | The workflow's UUID                                                 | `'01a1...'`                                |
| `{step_id}`       | The email step's action id from `workflows-get`                     | `'action_function_email_...'`              |
| `{window_start}`  | Start of the window, inclusive, at the start of a UTC day           | `toDateTime('2026-10-12 00:00:00', 'UTC')` |
| `{window_end}`    | End of the window, exclusive, at the start of a UTC day in the past | `toDateTime('2026-10-19 00:00:00', 'UTC')` |
| `{outcome_event}` | The product event that counts as the outcome, checked in the schema | `'insight created'`                        |
| `{outcome_days}`  | How many days after the send the outcome may happen                 | `7`                                        |
| `{person_id}`     | One person's UUID                                                   | `'0189...'`                                |

## Recipes

### Step engagement

Every email step of one workflow, in event occurrences and in distinct people.
`tracked_sent` is the only honest denominator for opens and clicks, because a send with tracking off can never record either.
Bounces and spam complaints divide by `sent`.

```sql
SELECT
    properties.$workflow_action_id AS step,
    countIf(event = '$workflows_email_sent') AS sent,
    countIf(event = '$workflows_email_sent' AND toString(properties.$email_tracking_enabled) = 'true') AS tracked_sent,
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
    AND event LIKE '$workflows_email_%'
    AND properties.$workflow_id = {workflow_id}
GROUP BY step
ORDER BY sent DESC
```

### Engagement by version

One step's callbacks split by the version that sent them.
Use it when `workflows-version-stats` is not available.
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
ORDER BY version
```

A row with no `version` holds callbacks of sends made before the send carried a version. Report it as unattributed, never as a version.
A version that went live before the window can still show opens and clicks in it: they belong to its older sends.

### Clicked links

Which links of one step get clicked, by position in the email, domain and path.
The query string and fragment are left out on purpose: they can hold tokens, emails or other personal data.

```sql
SELECT
    toString(properties.$link_index) AS link_index,
    domain(toString(properties.$link_url)) AS link_domain,
    path(toString(properties.$link_url)) AS link_path,
    count() AS clicks,
    uniq(person_id) AS clickers
FROM events
WHERE timestamp >= {window_start}
    AND timestamp < {window_end}
    AND event = '$workflows_email_link_clicked'
    AND properties.$workflow_id = {workflow_id}
    AND properties.$workflow_action_id = {step_id}
GROUP BY link_index, link_domain, link_path
ORDER BY clicks DESC
LIMIT 50
```

`clickers` overlap across links, so never add them up into a count of people who clicked.
A path can still carry a personal segment, such as an invite code: collapse those into one row in your report.

### Product outcome after the first send

The people a step sent to in the window, and how many did the outcome event within `{outcome_days}` days after their first send in the window.
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
        GROUP BY person_id
        HAVING countIf(event = '$workflows_email_sent') > 0
    )
)
```

The outcome only counts when the email and the product events land on the same person.
That holds when the workflow sends with the app's own distinct ID; a send addressed only by email can sit on a separate person.

### One person's email history

Everything one person did in the window, email events and product events together, in order.

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
ORDER BY timestamp
LIMIT 500
```

Unsubscribes are not in it: `$workflows_email_unsubscribed` uses the email address as its distinct ID, so it lands on a different person.
