# Email performance SQL recipes

Run each recipe with `posthog:execute-sql`.
**Step engagement**, **Engagement by version**, **Product outcome after the first send** and **One person's email history** read the captured `$workflows_email_*` events. They return nothing when no engagement events were captured for the workflow and window (see "Check the data exists" in the skill).
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
| `{run_ids}`       | One or more batch run ids, from `posthog:workflows-list-batch-jobs` | `('0199...', '019a...')`                   |
| `{person_id}`     | One person's UUID                                                   | `'0189...'`                                |

## Recipes

### Email steps

The id and name of each email step of one workflow.
Use it when the `posthog:workflows-get` response cuts off before the step names.

```sql
SELECT
    JSONExtractString(node, 'id') AS step_id,
    JSONExtractString(node, 'name') AS step_name
FROM (
    SELECT arrayJoin(JSONExtractArrayRaw(actions)) AS node
    FROM system.hog_flows
    WHERE id = {workflow_id}
)
WHERE JSONExtractString(node, 'type') = 'function_email'
```

### Step engagement

Every email step of one workflow, in event occurrences and in distinct people.
`tracked_sent` is the denominator for opens and clicks, because a send with tracking off can never record either. Opens over `tracked_sent` is a period occurrence ratio.
`people_tracked` is the denominator for `openers` and `clickers`. Openers over `people_tracked` is a period person ratio: the openers need not be among the people sent email in the window.
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

The sent event carries `$email_tracking_enabled` from 2026-07-29. For a window that starts earlier, `tracked_sent` undercounts, so divide opens and clicks by the counters instead.

### Run counters

The counters of one or more broadcast or batch runs for one step, one row per run and metric.
`posthog:workflows-stats` cannot read them, because it reads the counters keyed by the workflow.
It works whether or not the project captures engagement events.

```sql
SELECT
    app_source_id AS run_id,
    metric_name,
    sum(count) AS total
FROM app_metrics
WHERE app_source = 'hog_flow'
    AND app_source_id IN {run_ids}
    AND instance_id IN ({step_id}, {workflow_id})
    AND timestamp >= {window_start}
    AND timestamp < {window_end}
GROUP BY run_id, metric_name
ORDER BY run_id, metric_name
```

Divide opens and clicks by `email_sent` minus `email_untracked`. `conversion` counts the whole workflow's conversions in the run, not this step's.
For a trend across runs, pass every run in the window and order the rows by the run start times from `posthog:workflows-list-batch-jobs`.

### Counters by version

The workflow's own counters for one step, one row per version and metric.
Use it to compare versions when `posthog:workflows-version-stats` is not available.

```sql
SELECT
    splitByChar('/', app_source_id)[2] AS version,
    metric_name,
    sum(count) AS total
FROM app_metrics
WHERE app_source = 'hog_flow_version'
    AND startsWith(app_source_id, concat({workflow_id}, '/'))
    AND instance_id IN ({step_id}, {workflow_id})
    AND timestamp >= {window_start}
    AND timestamp < {window_end}
GROUP BY version, metric_name
ORDER BY toInt(version), metric_name
```

Start the window on the day the oldest compared version went live, and on or after the dates in "Versioned counters have start dates" in the skill. A newer version has no rows before it went live.
Divide opens and clicks by `email_sent` minus `email_untracked`. `conversion` counts the whole workflow's conversions for that version.

### Engagement by version

One step's callbacks split by the version that sent them.
Use it for openers and clickers per version. Report them as counts, because the sent event carries no version, so no count of people sent exists per version. Per-version ratios come from `posthog:workflows-version-stats` or the **Counters by version** recipe, as period occurrence ratios over tracked sends.

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

How often each link position of one step gets clicked.
It reads the per-link click counter instead of the click events.
The counter stores each web URL without its query string, replaces long token- and id-shaped path segments with `*`, and cuts URLs at 200 characters.
The click events keep the full URL, tokens included, so group links only through this counter, never by `$link_url`.

```sql
SELECT
    splitByChar('/', app_source_id)[2] AS version,
    splitByChar('|', instance_id)[2] AS link_index,
    sum(count) AS clicks
FROM app_metrics
WHERE app_source = 'hog_flow_version'
    AND startsWith(app_source_id, concat({workflow_id}, '/'))
    AND metric_name = 'email_link_clicked_by_link'
    AND startsWith(instance_id, concat({step_id}, '|'))
    AND timestamp >= {window_start}
    AND timestamp < {window_end}
GROUP BY version, link_index
ORDER BY toInt(version), toInt(link_index)
LIMIT 500
```

`clicks` are occurrences. Link positions number the links in the email's HTML in order, from 0.
The recipe returns no URLs, because the counter keeps short path segments and `mailto:` links unchanged, so a URL can hold a name or an address.
Name the positions of the live version from its email content in `posthog:workflows-get`. A version can add, move or change a link, and no tool returns the content of an older version, so report the positions of older versions by number.
The recipe reads the versioned series, so clicks whose message carried no version are missing. Start the window on or after the engagement start date in "Versioned counters have start dates" in the skill. For one broadcast or batch run, read the run's window, and say that the read also counts clicks of other runs in that window.
For people per link position, count distinct `person_id` on `$workflows_email_link_clicked` grouped by `$workflow_version` and `$link_index`. Clickers overlap across positions, so never add them up into a count of people who clicked.

### Product outcome after the first send

The people a step sent to in the window, and how many did the outcome event within `{outcome_days}` days after their first send in the window.
The query groups only the recipients, but it still reads every outcome event in the window. For a common outcome event, such as `$pageview`, keep the window and `{outcome_days}` short.
Set `{window_end}` at least `{outcome_days}` days before the end of the last closed UTC day. Then every recipient's outcome window has closed, and the read gives the same answer every time. When the sends are more recent, tell the user it is too early to judge the outcome.

```sql
SELECT
    count() AS recipients,
    countIf(reached_outcome) AS reached_outcome
FROM (
    SELECT
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

If it returns 500 rows, the limit cut off the rest of the window. Narrow the window and run it again.
To see everything the person did after one email, drop the event condition and narrow the window to the day after that send.

It does not show unsubscribes. `$workflows_email_unsubscribed` uses the email address as its distinct ID, so it lands on a different person.
