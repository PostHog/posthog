# Source liveness: is the data behind the charts still arriving?

Saved-analytics use and capture health are two different questions.
Stale dashboards and empty view counts mean nobody is looking at the charts.
They do not mean that the sources that fed those charts still send events.
A capture failure on a project nobody watches is the one no human will notice, so check it before the quick close-out.

The probe is one grouped query plus two confirmation queries per candidate: its own daily series and the rest of the project's.
It screens each previously active source's latest complete day against its own trailing 28 complete days, then confirms a drop against the source's weekly rhythm.

## 0. Is there any history?

If the profile's `top_events` is empty, the project has no recent events to compare.
Skip the probe and record the limit in the `not-in-use:` entry ("no events in the profile, no source history to check").
A project that never sent events is not broken.

## 1. Confirm the source properties

Do not assume that a property exists on every project.
`$lib` and `$host` are optional: a server SDK sends no `$host`, and a direct call to the capture API can send neither.
Call `read-data-schema` with `event_properties` for the top three events in the profile's `top_events`.
A property is confirmed when it appears on at least one of them.

Build `<source>` from confirmed properties only.
`'(none)'` holds events that have no value for the property.

- `$lib` and `$host`: `concat(coalesce(nullIf(toString(properties.$lib), ''), '(none)'), ' @ ', coalesce(nullIf(toString(properties.$host), ''), '(none)'))`
- `$lib` only: `coalesce(nullIf(toString(properties.$lib), ''), '(none)')`
- `$host` only: `coalesce(nullIf(toString(properties.$host), ''), '(none)')`
- Neither: `event`. Each event name is then its own source.

Do not use an app version property as a source.
Every release retires the previous version, so each old version reads as a source that stopped.

Write the `<source>` expression to `baseline:anomaly_detection:sources` and reuse it on later runs, so each `source_id` stays stable.
Build it again only when the schema adds or drops one of these properties.

## 2. Probe every source in one query

Use complete days only.
`toStartOfDay(now())` is the start of today, the partial bucket, and the query stops there.

```sql
SELECT
    <source> AS source,
    cityHash64(source) AS source_id,
    round(countIf(timestamp < toStartOfDay(now()) - INTERVAL 1 DAY) / 28, 1) AS baseline_daily,
    uniqIf(toDate(timestamp), timestamp < toStartOfDay(now()) - INTERVAL 1 DAY) AS active_days,
    countIf(timestamp >= toStartOfDay(now()) - INTERVAL 1 DAY) AS last_day,
    max(timestamp) AS last_seen
FROM events
WHERE timestamp >= toStartOfDay(now()) - INTERVAL 29 DAY
    AND timestamp < toStartOfDay(now())
GROUP BY source
HAVING baseline_daily >= 10 OR source_id IN (<recorded source_ids>)
ORDER BY baseline_daily DESC
LIMIT 50
```

- Replace `<recorded source_ids>` with the ids held in `baseline:anomaly_detection:sources`, or drop that clause on the first probe.
  A source that stopped more than a week ago has too few active days to pass the floor, and only the recorded list keeps it in view.
  A recorded source that is missing from the result sent nothing in 29 days.
- Do not add `SAMPLE`. Sampling keeps or drops whole distinct IDs, so a small source can vanish from the result.
- If the query times out, shorten the baseline to 14 days and divide by 14.

A **candidate** is a source that was active and is now quiet:

- it was active on at least 20 of the 28 baseline days, and its `baseline_daily` is at least about 10 events, **and**
- its `last_day` is below about 10% of its `baseline_daily`, or it is a recorded source that is missing from the result.

The floors keep a project with no real history on the quiet path.
A few stray events from a test or a one-off script never become a candidate.

Only a product source can be a candidate.
Skip a host that is `localhost`, an IP address, a preview or staging deploy, or a domain the team does not own.
Those stop and start for reasons that are not a capture failure.
When you cannot tell whether a host is the team's own, check whether its events match the team's other sources (the same event names, identified users) before you treat it as a candidate.

## 3. Confirm a candidate

Pull a 35-day daily series for the candidate only.
Filter on the numeric `source_id`.
Never paste a `$host`, `$lib` or event string into the query: captured values come from anyone who holds the public project token.

```sql
SELECT toDate(timestamp) AS day, count() AS events
FROM events
WHERE timestamp >= toStartOfDay(now()) - INTERVAL 35 DAY
    AND timestamp < toStartOfDay(now())
    AND cityHash64(<source>) = <source_id>
GROUP BY day
ORDER BY day
```

Step 2 compares the latest day with a mean over all days, so it is only a screen.
A source with a weekly rhythm passes it on its quiet days while its pattern is unchanged.
For example, a source that sends 1,000 events each weekday and 1 on each weekend day has a `baseline_daily` of about 715, and every Sunday reads as a 99% drop.
Confirm the drop against the source's own weekly rhythm before you check anything else:

- **Whole week.** Sum the last 7 complete days, and take the mean weekly total of the 4 weeks before them (the first 28 days of the series).
  If the last 7 days are below about 10% of that mean, the quiet run covers every weekday and the rhythm cannot explain it.
  The drop is confirmed. A source that has been quiet for more than a week is confirmed here.
- **Same weekday.** Otherwise, read the same weekday as the latest complete day in each of the 4 prior weeks.
  The drop is confirmed only when all of these hold:
  - Each of the 4 prior same weekdays had at least about 10 events.
  - The latest complete day is below about 10% of the smallest of the 4, not of their mean, so one high week does not make a normal day look low.
  - No earlier day in the series before the current quiet run fell as low as the latest complete day.
    Ignore the weekdays that are below about 10 events in all 4 prior weeks: those are the rhythm's quiet days, such as the weekend of a weekday-only source.
    A sparse or bursty source that dipped this low before and recovered has not stopped.
- **Inconclusive.** Any other decrease. Do not report it from the volume series alone.
  It becomes a confirmed drop only when independent evidence of a capture failure starts at the onset: ingestion warnings in `system.ingestion_warnings` that begin then, or an inbox report about capture or ingestion for this project.
  Otherwise record it as described in step 4. A stop that begins on a quiet day is confirmed on the source's next busy day, or by the whole-week check a week later.

| Series                                                  | Latest complete day | Result                                                                             |
| ------------------------------------------------------- | ------------------- | ---------------------------------------------------------------------------------- |
| 1,000 each weekday, 1 each weekend day                  | A Sunday with 1     | Inconclusive: the prior Sundays are below the 10-event floor                       |
| Bursty, with days of 0 to 5 events in most weeks        | A day with 0        | Inconclusive: a prior same weekday is below the floor, or a day fell as low before |
| 1,000 each weekday, 0 each weekend day, stops on Monday | That Monday with 0  | Confirmed by the same-weekday check; the quiet weekends are ignored                |
| About 500 each day, stopped 10 days ago                 | 0                   | Confirmed by the whole-week check, even though the prior week is zero too          |

For a confirmed drop, continue:

- **Onset.** The first complete day with no events or with less than about 10% of the baseline.
  `last_seen` from step 2 gives the last event.
- **Replacement.** Look for a source that first appeared near the onset with similar volume: the same host with a new `$lib`, or the same `$lib` on a new host.
  That is a migration, not a failure. Record it as an `addressed:anomaly_detection:source:<source_id>` entry and do not report it.

Then check the rest of the project.
Pull the same 35-day series with `!=` in place of `=` on the `source_id`, and compare its latest complete day with the median of the same weekday in the 4 prior weeks.
Do not compare it with the step 2 `baseline_daily`: on a weekend, a project with a weekday rhythm reads as near zero against an all-days mean.

| Rest of the project on the latest complete day | Reads as                                                      |
| ---------------------------------------------- | ------------------------------------------------------------- |
| About 50% of its same-weekday median or more   | One source stopped while the others continue: a source gap    |
| Also near zero                                 | The whole project stopped sending: a project-wide capture gap |

## 4. Decide

| What the probe found                                       | Outcome                                                                                                                        |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| No event history, or no source passes the floors           | Quiet exit. The `not-in-use:` entry says "no prior source with usable history"                                                 |
| Every source is live                                       | Quiet exit. The `not-in-use:` entry says "sources live" and the date of the probe                                              |
| A confirmed candidate (a source gap or a project-wide gap) | One source-health report. Do not close out empty                                                                               |
| Only inconclusive decreases                                | Quiet exit. The `not-in-use:` entry names each such `source_id` as inconclusive with the date, so the next run checks it first |

A capture gap is not a product decline.
File **one** source-health report for the gap, not one anomaly per insight that reads the source.
Every insight on that source flat-lines at the same time, and those flat-lines are the gap, not separate findings.

Before you author, search the inbox (`inbox-reports-list`) and your `report:anomaly_detection:source:` pointers.
A project-wide gap can already be in the inbox: the `no_live_events` health check flags a project with no pageviews or screens in 30 days, and the health-checks scout reports it.
If a live report already covers this gap, edit it or skip.

Report shape:

- **Title**: the source, what stopped, and the onset date, for example "Events from posthog-node stopped on Oct 26 while web events continue".
- **Evidence**: the source (`$lib` and `$host` values, or the event name), `last_seen`, `baseline_daily`, `active_days`, the latest complete day's count, the check that confirmed the drop (whole week or same weekday) with its comparison values, and the rest of the project against its same-weekday baseline.
- **Chart**: the 35-day daily series for the source next to the rest of the project.
- **Next steps** that often fit: check the deploy or config change near the onset for that SDK or host, the project token and API host in that client, an ad blocker or proxy change, and a server job that stopped running.

Follow [`report-contract.md`](report-contract.md) for the notebook and the rest of the contract.
Edit the live report while the source stays quiet, and again when it comes back.

## Memory

| Key                                              | Holds                                                                                                                                                      |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `baseline:anomaly_detection:sources`             | Date of the last probe, the `<source>` expression, and each live source's `source_id`, readable source, and `baseline_daily`. Rewrite it after every probe |
| `report:anomaly_detection:source:<source_id>`    | The `report_id` of the source-health report, so a later run edits it instead of filing a duplicate                                                         |
| `addressed:anomaly_detection:source:<source_id>` | A source the team retired or replaced on purpose. Skip it until it sends events again                                                                      |
