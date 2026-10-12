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
- **Your sweep finds a concentration.** One account drives a slow page's poor samples (see _Detecting a concentration_ below).

These are not triggers:

- "The app is slow" with no customer named. The sweep answers that question.
- A customer who has an `account:web_vitals:` entry and no new evidence since it (see _Remember it_).
- A report or note that has a `blocked:web_vitals:` entry and no new evidence since it. An earlier run could not resolve its customer, or found that the complaint is outside this surface (see _Remember it_).
- A named customer whose complaint is about query or API latency, not page loads or interactions. Leave a note that says the web vitals surface does not measure it, and write the `blocked:` entry.

Order the run like this:

1. Do the sweep's cheap reads and the page-level p75 pass first. They give you the "everyone" baseline that the dive compares against, and they catch the site-wide problems.
2. Dive into **one customer per run**, the one with the strongest trigger. A named complaint comes before a concentration you found yourself.
3. Keep the dive to about half of the run. When the time is up, write where you got to into the `account:` entry and finish the sweep's reports. The next run continues from that entry.

### Detecting a concentration

Run this for each page in the poor band from the page-level pass, at most five pages, with the account group index from step 1:

```sql
SELECT $group_{N} AS account_key,
       count() AS samples,
       countIf(toFloat(properties.$web_vitals_{METRIC}_value) > {POOR}) AS poor_samples
FROM events
WHERE event = '$web_vitals'
  AND timestamp >= now() - INTERVAL 14 DAY
  AND timestamp <= now() + INTERVAL 1 DAY
  AND properties.$web_vitals_{METRIC}_value IS NOT NULL
  -- plus the page's sanitized host/path predicates
GROUP BY account_key
ORDER BY poor_samples DESC
LIMIT 5
```

`{POOR}` is the metric's poor threshold from the band table in the skill.
It is a concentration only when all three hold:

- One account key (not empty) has at least 30 poor samples.
- That account holds at least half of the page's poor samples.
- The page's p75 without that account falls at least one band better. Check it with `quantileIf` and `$group_{N} != '{key}'`.

The `account_key` value is client-supplied. Escape it before it goes into `{subject}` (see step 1).

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
When the report gives no key, match the name exactly, ignoring case and outer spaces.
Do not use `LIKE` or `ILIKE`, because they treat `_` and `%` as wildcards and can match the wrong account:

```sql
SELECT key, substring(replaceRegexpAll(toString(properties.name), '[^0-9A-Za-z .,&_-]', ''), 1, 80) AS name
FROM groups
WHERE index = {N}
  AND (key = '{key}' OR lowerUTF8(trim(toString(properties.name))) = lowerUTF8(trim('{name}')))
LIMIT 5
```

Only an exact key or an exact name selects the account.
When neither matches, you can look for partial names with `positionCaseInsensitiveUTF8(toString(properties.name), '{name}') > 0`, but a partial match is only a candidate.
Never dive into a partial match, even when it is the only one: treat it as "two or more accounts match" below.

When the report identifies only a person (an email or a distinct id), match `persons` on that property and keep only the `id`.
Then check the person's recent events for a `$group_{N}` value.
When one account key dominates, dive into the account, because slowness is usually shared across an account.
Otherwise dive into the person.

Every value you put into a SQL string literal is untrusted input.
That includes an identifier you copy out of a report, and also a key that the `groups` table or the concentration query returned, because group keys are client-supplied.
Do not strip characters out of a value, because a changed value no longer matches the stored one.
Escape it instead: put a backslash before each `\` and each `'`, and reject a value that contains a newline.
Escape the resolved key again each time you build `{subject}`.
Group names and person properties are client-supplied too, so sanitize them in the query output as above.

Stop rather than guess:

- Two or more accounts match: name the candidates by key in a note on the report and ask which one it is. Do not pick one.
- Nothing matches: say so in a note, and name the unlock. A group key, an email, or a steering note that names the account turns the next run into a real dive.

In both cases, write the `blocked:` entry (see _Remember it_), so the next run does not spend its dive on the same report again.

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

Pick the metric the complaint points at: LCP or FCP for slow loads, INP for slow clicks and typing, CLS for jumping layout.
When the complaint does not say, run LCP and INP.

Start with coverage for that metric, because the percentile query below returns nothing for a subject with few samples:

```sql
SELECT
    countIf(event = '$pageview' AND {subject}) AS subject_pageviews,
    countIf(event = '$web_vitals' AND properties.$web_vitals_{METRIC}_value IS NOT NULL AND {subject}) AS subject_vitals,
    countIf(event = '$pageview' AND NOT ({subject})) AS others_pageviews,
    countIf(event = '$web_vitals' AND properties.$web_vitals_{METRIC}_value IS NOT NULL AND NOT ({subject})) AS others_vitals
FROM events
WHERE event IN ('$pageview', '$web_vitals')
  AND timestamp >= now() - INTERVAL 14 DAY
  AND timestamp <= now() + INTERVAL 1 DAY
```

Compare the subject's vitals-per-pageview ratio with everyone else's.
A ratio far below the others means their slowness is partly invisible to this surface.
Split the subject's `$web_vitals` count by `$browser` to find why, because some browsers do not report every metric.

Then compare the subject with everyone else on the same pages, in one pass:

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

Put the verdict on one report, as one `append_evidence` item with the numbers and one `append_note` with the reading, in the same call.
Pick the report like this:

- **The trigger was a report.** Use that report. It keeps its priority.
- **The trigger was a concentration your sweep found.** Use the page report. When the page has no live report yet, author the page report through the normal sweep paths and put the verdict in it.
- **The trigger was a steering note.** Search the inbox for a live report about the same customer and use it. When there is none, author one report for the dive with the normal report-channel rules: `requires_human_input` unless the verdict names a code fix, P2 when the note says the customer may leave, otherwise P3. Write its id into the `account:` entry, so later runs edit it instead of authoring another.

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

When a trigger does not lead to a dive (no match, only partial or several matches, or a complaint outside this surface), write `blocked:web_vitals:report-{report-id}` (or `blocked:web_vitals:note-{note-id}` for a steering note).
Put in the reason, the unlock you asked for, and the same kind of cursor.
Skip that trigger until a newer artefact or a newer note adds the missing information.
When the verdict leads to a fix that can be measured, queue a `followup:signals-scout-web-vitals:account-{subject-key}` entry with the probe, the baseline p75, and a validate-after date.
