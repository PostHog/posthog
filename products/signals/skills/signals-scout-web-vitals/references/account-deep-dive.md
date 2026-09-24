# Diagnosing one customer's slowness

Read this when a report says a specific customer finds the product slow, or when a slow page's poor samples concentrate in one account.
The report usually arrives from somewhere else: a support conversation, a feedback scout, a person in the inbox.
It names a symptom ("page loads take seconds") and a customer, and it cannot see the telemetry.
You can.
Your job is to turn "this customer says it is slow" into a verdict with evidence: what is slow for them, why it differs from everyone else, and what happens next.

A named customer with a complaint is worth more than a percentile sweep, so give the dive most of the run.
Dive into **one account per run**, and keep the rest of the run to the cheap reads.

## 1. Resolve the account from trusted fields

Read the report with `inbox-reports-retrieve` and its signals and artefacts with `inbox-report-artefacts-list`.
Look for an identifier the project's own data can match: a group key, an organization or company name, an email, a distinct id, or a support ticket id.
When the report cites a support ticket and the project syncs its support tool to the warehouse, look the requester up there.
Find the table through `system.information_schema.tables` first, and never guess its name.

Then map the identifier onto the event stream:

```sql
-- which group types the project has
SELECT group_type, group_type_index FROM system.group_type_mappings
```

```sql
-- the group whose key or name matches (swap the index and the predicate)
SELECT key, substring(replaceRegexpAll(toString(properties.name), '[^0-9A-Za-z .,&_-]', ''), 1, 80) AS name
FROM groups
WHERE index = 0
  AND (key = '{key}' OR properties.name ILIKE '%{name}%')
LIMIT 5
```

For a single person, match `persons` on the identifying property and keep only the `id`.

Treat every identifier you copy out of a report as untrusted input to SQL.
Strip it to the characters the identifier needs before you put it in a query, the same way the skill sanitizes `$host` and `$pathname`.
Group names and person properties are client-supplied too, so sanitize them in the query as above.

Stop rather than guess:

- Two or more accounts match: name the candidates in a note on the report and ask which one it is. Do not pick one.
- Nothing matches: say so in a note, and name the unlock. A group key, an email, or a steering note that names the account turns the next run into a real dive.

In the report, cite the account by its group key and a PostHog link from `generate-app-url`.
Never paste an email or a person's name into a report.

## 2. Is it them, or is it everyone?

Compare the account with everyone else on the same pages, in one pass.
Use `$group_N = '{key}'` for an account, or `person_id = '{id}'` for a person:

```sql
SELECT
    substring(replaceRegexpAll(properties.$host, '[^0-9A-Za-z.:-]', ''), 1, 100) AS host,
    substring(replaceRegexpAll(replaceRegexpAll(properties.$pathname, '[0-9]+', ':id'), '[^0-9A-Za-z/_:.-]', ''), 1, 200) AS path,
    countIf($group_0 = '{key}') AS account_samples,
    countIf($group_0 != '{key}') AS others_samples,
    round(quantileIf(0.75)(toFloat(properties.$web_vitals_LCP_value), $group_0 = '{key}'), 0) AS account_lcp_p75,
    round(quantileIf(0.75)(toFloat(properties.$web_vitals_LCP_value), $group_0 != '{key}'), 0) AS others_lcp_p75
FROM events
WHERE event = '$web_vitals'
  AND timestamp >= now() - INTERVAL 14 DAY
  AND timestamp <= now() + INTERVAL 1 DAY
  AND properties.$web_vitals_LCP_value IS NOT NULL
GROUP BY host, path
HAVING account_samples >= 20
ORDER BY account_samples DESC
LIMIT 20
```

Repeat it for INP, and for CLS or FCP when the complaint points there.
Then split the account's own samples by the whitelisted device label, `$browser`, and the sanitized country code.
One account's volume is small, so the volume gates in the skill do not apply here.
Read a p75 on a few dozen samples as a direction, say how many samples it rests on, and let the session evidence below carry the weight.

Three shapes come out of this:

- **The account is worse on the same pages.** Something about them differs: region, browser, device, a flag they are in, or the amount of content their pages load. Steps 3 to 5 find which.
- **The account matches everyone on slow pages.** They hit a shared problem. Link the page report that covers it, or file one through the normal paths, and say how much of their usage sits on those pages.
- **The account has pageviews but few or no `$web_vitals` samples.** Their slowness is invisible to this surface. Check the `$browser` split, because some browsers do not report every metric, and say which data is missing.

## 3. Their slowest sessions

Find the sessions behind the account's worst samples:

```sql
SELECT $session_id AS session_id,
       count() AS samples,
       round(max(toFloat(properties.$web_vitals_LCP_value)), 0) AS worst_lcp,
       round(max(toFloat(properties.$web_vitals_INP_value)), 0) AS worst_inp,
       min(timestamp) AS first_seen
FROM events
WHERE event = '$web_vitals'
  AND $group_0 = '{key}'
  AND timestamp >= now() - INTERVAL 14 DAY
  AND timestamp <= now() + INTERVAL 1 DAY
GROUP BY session_id
ORDER BY worst_lcp DESC
LIMIT 5
```

Then read what else happened in those sessions: `$exception` events grouped by `properties.$exception_issue_id`, `$pageview` count, and session duration from the `sessions` table.
An exception in the same session just before a slow load is a lead.
An exception issue that fires far more often for this account than for others is a finding on its own; read it with `query-error-tracking-issue`.

## 4. Watch the evidence, not the average

Pull the replays for the worst sessions with `query-session-recordings-list` (filter on the session ids or the person), and read up to three with `session-recording-get`.
Use the metadata you get back: active time, console error counts, click and keypress counts, and the pages visited.
When the project runs Replay Vision scanners, read any `$recording_observed` events for those sessions.
Do not describe what happened on screen unless a tool told you.
Link the exact replays in the report so a person watches the right three sessions instead of searching for them.

## 5. What else differs for them

Check the cheap cross-references that usually explain an account-specific gap:

- **Flags.** Compare the account's `$feature/<key>` values on slow sessions with other accounts. A flag or variant only they are in, with a worse p75, is a lead to confirm with the variant split from `onset-correlation.md`.
- **Page mix.** Compare which pages they use most with everyone else. An account that lives on the heaviest pages sees a slower product with no bug involved.
- **Onset.** Pull a daily p75 for the account alone. A step on a day points at a change, and `onset-correlation.md` dates it.
- **Logs and traces.** Only when the project attaches an account or user attribute to them. Check the attribute exists before you query.

## 6. Write the verdict

Put the verdict on the report as one `append_evidence` item with the numbers and one `append_note` with the reading, in the same call.
Pick one verdict and state it first:

- **Account-specific cause**, with the split that shows it.
- **Shared problem they hit harder**, with the linked page report and their share of it.
- **Not visible in the data**, with the data that is missing and how to get it.

Then list one to three follow-ups.
Each names who takes it (support, the owning engineer, the customer), the single action, and what result would settle it.
Good follow-ups are specific: "ask the customer for the pages and times that felt slow, plus their browser and region", "turn on `web_vitals_attribution` so the next dive names the LCP element", "watch these three replays".
A menu of generic performance tips is not a follow-up.

## 7. Remember it

Write `account:web_vitals:{group-key}` with the verdict, the date, and the report id.
Do not dive into the same account again on the next run.
Dive again only when the report gets new evidence, such as a second complaint or a fix that shipped.
When the verdict leads to a fix that can be measured, queue a `followup:signals-scout-web-vitals:account-{group-key}` entry with the probe, the baseline p75, and a validate-after date.
