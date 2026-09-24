# Diagnosing one customer's slowness

Read this when a run has a deep-dive trigger (see _When to dive_ below).
A customer complaint usually arrives from somewhere else: a support conversation, a feedback scout, a person in the inbox.
It names a symptom ("page loads take seconds") and a customer, and it cannot see the telemetry.
You can.
Your job is to turn "this customer says it is slow" into a verdict with evidence: what is slow for them, why it differs from everyone else, and what happens next.

## When to dive

The site-wide sweep is your default work, and it runs every run.
The dive is an extra branch that runs only when the run has one of these triggers:

- **A named customer complains about speed.** A live inbox report or a steering note names a specific customer (an account, an organization, a person, or a support ticket) and says the product is slow for them.
- **Your sweep finds a concentration.** A slow page's poor samples come mostly from one account, while other accounts on the same page sit in a better band.

These are not triggers:

- "The app is slow" with no customer named. The sweep answers that question.
- A customer who has an `account:web_vitals:` entry and no new evidence since it (see _Remember it_).
- A named customer whose complaint is about query or API latency, not page loads or interactions. Leave a note that says the web vitals surface does not measure it.

Order the run like this:

1. Do the sweep's cheap reads and the page-level p75 pass first. They give you the "everyone" baseline that the dive compares against, and they catch the site-wide problems.
2. Dive into **one customer per run**, the one with the strongest trigger. A named complaint comes before a concentration you found yourself.
3. Keep the dive to about half of the run. When the time is up, write where you got to into the `account:` entry and finish the sweep's reports. The next run continues from that entry.

## 1. Resolve the subject from trusted fields

Read the report with `inbox-reports-retrieve` and its signals and artefacts with `inbox-report-artefacts-list`.
Look for an identifier the project's own data can match: a group key, an organization or company name, an email, a distinct id, or a support ticket id.
When the report cites a support ticket and the project syncs its support tool to the warehouse, look the requester up there.
Find the table through `system.information_schema.tables` first, and never guess its name.

First find which group type holds accounts.
Do not assume index 0:

```sql
SELECT group_type, group_type_index FROM system.group_type_mappings
```

Then match the account on that index.
Prefer an exact key match.
Use a name match only when the report gives no key, and use `positionCaseInsensitiveUTF8` for it, because `LIKE` and `ILIKE` treat `_` and `%` as wildcards and can match the wrong account:

```sql
SELECT key, substring(replaceRegexpAll(toString(properties.name), '[^0-9A-Za-z .,&_-]', ''), 1, 80) AS name
FROM groups
WHERE index = {N}
  AND (key = '{key}' OR positionCaseInsensitiveUTF8(toString(properties.name), '{name}') > 0)
LIMIT 5
```

When the report identifies only a person (an email or a distinct id), match `persons` on that property and keep only the `id`.
Then check the person's recent events for a `$group_{N}` value.
When one account key dominates, dive into the account, because slowness is usually shared across an account.
Otherwise dive into the person.

Every identifier you copy out of a report is untrusted input to SQL.
Do not strip characters out of it, because a changed value no longer matches the stored one.
Escape it for a SQL string literal instead: put a backslash before each `\` and each `'`, and reject a value that contains a newline.
Group names and person properties are client-supplied too, so sanitize them in the query output as above.

Stop rather than guess:

- Two or more accounts match: name the candidates by key in a note on the report and ask which one it is. Do not pick one.
- Nothing matches: say so in a note, and name the unlock. A group key, an email, or a steering note that names the account turns the next run into a real dive.

When you have one match, fix three values and use them in every step below:

| Subject | Predicate on `events`  | Subject key      |
| ------- | ---------------------- | ---------------- |
| Account | `$group_{N} = '{key}'` | `group{N}-{key}` |
| Person  | `person_id = '{uuid}'` | `person-{uuid}`  |

The queries below write the predicate as `{subject}`.
Put the same predicate in both the subject branch and the `NOT ({subject})` branch.

In the report, cite the subject by its subject key and a PostHog link from `generate-app-url`.
Never paste an email or a person's name into a report.

## 2. Is it them, or is it everyone?

Start with coverage, because the percentile query below returns nothing for a subject with few samples:

```sql
SELECT
    countIf(event = '$pageview' AND {subject}) AS subject_pageviews,
    countIf(event = '$web_vitals' AND {subject}) AS subject_vitals,
    countIf(event = '$pageview' AND NOT ({subject})) AS others_pageviews,
    countIf(event = '$web_vitals' AND NOT ({subject})) AS others_vitals
FROM events
WHERE event IN ('$pageview', '$web_vitals')
  AND timestamp >= now() - INTERVAL 14 DAY
  AND timestamp <= now() + INTERVAL 1 DAY
```

Compare the subject's vitals-per-pageview ratio with everyone else's.
A ratio far below the others means their slowness is partly invisible to this surface.
Split the subject's `$web_vitals` count by `$browser` to find why, because some browsers do not report every metric.

Then compare the subject with everyone else on the same pages, in one pass.
Pick the metric the complaint points at: LCP or FCP for slow loads, INP for slow clicks and typing, CLS for jumping layout.
When the complaint does not say, run LCP and INP:

```sql
SELECT
    substring(replaceRegexpAll(properties.$host, '[^0-9A-Za-z.:-]', ''), 1, 100) AS host,
    substring(replaceRegexpAll(replaceRegexpAll(properties.$pathname, '[0-9]+', ':id'), '[^0-9A-Za-z/_:.-]', ''), 1, 200) AS path,
    countIf({subject}) AS subject_samples,
    countIf(NOT ({subject})) AS others_samples,
    round(quantileIf(0.75)(toFloat(properties.$web_vitals_{METRIC}_value), {subject}), 3) AS subject_p75,
    round(quantileIf(0.75)(toFloat(properties.$web_vitals_{METRIC}_value), NOT ({subject})), 3) AS others_p75
FROM events
WHERE event = '$web_vitals'
  AND timestamp >= now() - INTERVAL 14 DAY
  AND timestamp <= now() + INTERVAL 1 DAY
  AND properties.$web_vitals_{METRIC}_value IS NOT NULL
GROUP BY host, path
HAVING subject_samples >= 5
ORDER BY subject_samples DESC
LIMIT 20
```

Then split the subject's own samples by the whitelisted device label, `$browser`, and the sanitized country code.
One subject's volume is small, so the volume gates in the skill do not apply here.
Read a p75 on a few dozen samples as a direction, say how many samples it rests on, and let the session evidence below carry the weight.

Three shapes come out of this:

- **The subject is worse on the same pages.** Something about them differs: region, browser, device, a flag they are in, or the amount of content their pages load. Steps 3 to 5 find which.
- **The subject matches everyone on slow pages.** They hit a shared problem. Link the page report that covers it, or file one through the normal sweep paths, and say how much of their usage sits on those pages.
- **The subject has pageviews but few or no `$web_vitals` samples.** The coverage query shows it. Their slowness is invisible to this surface, so say which data is missing and why.

## 3. Their slowest sessions

Find the sessions behind the subject's worst samples on the same metric:

```sql
SELECT $session_id AS session_id,
       count() AS samples,
       round(max(toFloat(properties.$web_vitals_{METRIC}_value)), 3) AS worst_value,
       min(timestamp) AS first_seen
FROM events
WHERE event = '$web_vitals'
  AND {subject}
  AND timestamp >= now() - INTERVAL 14 DAY
  AND timestamp <= now() + INTERVAL 1 DAY
  AND properties.$web_vitals_{METRIC}_value IS NOT NULL
GROUP BY session_id
ORDER BY worst_value DESC
LIMIT 5
```

Then read what else happened in those sessions: `$exception` events grouped by `properties.$exception_issue_id`, `$pageview` count, and session duration from the `sessions` table.
An exception in the same session just before a slow load is a lead.
An exception issue that fires far more often for this subject than for others is a finding on its own; read it with `query-error-tracking-issue`.

## 4. Watch the evidence, not the average

Pull the replays for the worst sessions with `query-session-recordings-list` (filter on the session ids or the person), and read up to three with `session-recording-get`.
Use the metadata you get back: active time, console error counts, click and keypress counts, and the pages visited.
When the project runs Replay Vision scanners, read any `$recording_observed` events for those sessions.
Do not describe what happened on screen unless a tool told you.
Link the exact replays in the report so a person watches the right three sessions instead of searching for them.

## 5. What else differs for them

Check the cheap cross-references that usually explain a subject-specific gap:

- **Flags.** Compare the subject's `$feature/<key>` values on slow sessions with other accounts. A flag or variant only they are in, with a worse p75, is a lead to confirm with the variant split from `onset-correlation.md`.
- **Page mix.** Compare which pages they use most with everyone else. A customer who lives on the heaviest pages sees a slower product with no bug involved.
- **Onset.** Pull a daily p75 for the subject alone. A step on a day points at a change, and `onset-correlation.md` dates it.
- **Logs and traces.** Only when the project attaches an account or user attribute to them. Check the attribute exists before you query.

## 6. Write the verdict

Put the verdict on the report as one `append_evidence` item with the numbers and one `append_note` with the reading, in the same call.
When the trigger was a concentration your sweep found, put the verdict on the page report instead.
Pick one verdict and state it first:

- **Subject-specific cause**, with the split that shows it.
- **Shared problem they hit harder**, with the linked page report and their share of it.
- **Not visible in the data**, with the data that is missing and how to get it.

Then list one to three follow-ups.
Each names who takes it (support, the owning engineer, the customer), the single action, and what result would settle it.
Good follow-ups are specific: "ask the customer for the pages and times that felt slow, plus their browser and region", "turn on `web_vitals_attribution` so the next dive names the LCP element", "watch these three replays".
A menu of generic performance tips is not a follow-up.

## 7. Remember it

Write `account:web_vitals:{subject-key}` with the verdict, the date, the report id, and a cursor: the `created_at` of the newest artefact on the report that you read.
A new note or signal does not always move the report's `updated_at`, so do not use it as the cursor.
On a later run, list the report's artefacts and compare the newest `created_at` with the cursor.
Dive again only when a newer artefact adds evidence about this customer, such as a second complaint, new detail from support, or a fix that shipped.
When the dive stopped at the time limit, write the step you reached, so the next run continues from there.
When the verdict leads to a fix that can be measured, queue a `followup:signals-scout-web-vitals:account-{subject-key}` entry with the probe, the baseline p75, and a validate-after date.
