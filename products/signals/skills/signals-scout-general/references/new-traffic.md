# New traffic: where did the extra events come from?

A project's event volume can step up for good reasons (a launch, a new SDK, a new market) or for bad ones (a public project token copied into a fork or an open-source build, a leaked key, a bot, a client stuck in a loop).
The team pays for every event either way, and a slow-growing surge is easy to miss: it never trips a one-day spike detector, and every trailing baseline absorbs it within a few weeks.
No specialist scout owns this. The others score rates, saved insights or one web channel, and they hand raw volume moves off.

This check is cheap and slow-moving, so run it every few runs, not every run.
Gate it on `pattern:general:new-traffic`: skip it when that entry is less than about a week old.

## 1. Find the step, by source

The profile's `top_events` covers 7 days, so it cannot see a step that started weeks ago.
Compare the latest 7 days with the 4 weeks before, broken down by where the events come from:

```sql
SELECT
    coalesce(nullIf(toString(properties.$lib), ''), '(none)') AS lib,
    coalesce(nullIf(toString(properties.$host), ''), nullIf(toString(properties.$app_version), ''), '(none)') AS origin,
    countIf(timestamp >= now() - INTERVAL 7 DAY) AS last_7d,
    round(countIf(timestamp < now() - INTERVAL 7 DAY) / 4) AS prior_weekly_avg,
    round(last_7d / greatest(prior_weekly_avg, 1), 2) AS ratio,
    uniqIf(distinct_id, timestamp >= now() - INTERVAL 7 DAY) AS ids_7d
FROM events
WHERE timestamp >= now() - INTERVAL 35 DAY
GROUP BY lib, origin
HAVING last_7d >= 1000
ORDER BY last_7d - prior_weekly_avg DESC
LIMIT 20
```

- Sort by absolute growth, not by ratio. A 2000x ratio on a few hundred events is noise. A 1.5x ratio on the project's biggest source can be most of the bill.
- On a large project (tens of millions of events a week), add `SAMPLE 1/100` after `FROM events` and lower the `HAVING` floor to match. Counts are then sample counts.
- `SAMPLE` keeps or drops whole distinct IDs, so a source with only a few IDs comes back all or nothing and its sampled ratio is noise. Treat a sampled result as a shortlist, and confirm every candidate with the unsampled query in step 2 before you read anything into its ratio.
- The baseline is a 4-week average, so one heavy day in the latest week can carry a high ratio on its own. Step 2 is where that falls out.
- Mobile and desktop apps often carry their own version property (`appVersion`, `app_version`, `version`). Check `read-data-schema` for a property ending in `version` and swap it into `origin` when `$app_version` is empty.
- Run the same query without the `GROUP BY` to see whether the whole project stepped, or only one source.

A candidate is a source that grew to about 2x or more of its own baseline **and** now carries a meaningful share of the project's weekly events (about 10% or more), or a source that appeared from nothing at real volume.

## 2. Confirm it is sustained and pin the onset

Pull a 56-day daily series for the candidate source only:

```sql
SELECT toDate(timestamp) AS day, count() AS events, uniq(distinct_id) AS ids
FROM events
WHERE timestamp >= now() - INTERVAL 56 DAY
    AND properties.$host = '<origin>'
GROUP BY day
ORDER BY day
```

- **Onset**: the first day of the step.
- **Pre-surge baseline**: the median daily volume over the 28 days before the onset.
- A step that has not held for 3 days or more is a spike, not new traffic. Leave it, or record it as a `pattern:` and check again next time.

Write both to `pattern:general:traffic-baseline:<origin>` as soon as you find them.
Later runs compare against this pinned baseline, not a trailing one. That keeps a surge that grows slowly visible.

## 3. Read the shape

Drill into the candidate before you decide what it is:

```sql
SELECT
    event,
    count() AS events,
    uniq(distinct_id) AS ids,
    round(count() / greatest(uniq(distinct_id), 1), 1) AS events_per_id,
    min(timestamp) AS first_seen
FROM events
WHERE timestamp >= now() - INTERVAL 7 DAY
    AND properties.$host = '<origin>'
GROUP BY event
ORDER BY events DESC
LIMIT 20
```

Add `properties.$lib_version`, `properties.$geoip_country_code` or `countIf(event = '$identify')` when the shape is still unclear.

| What you see                                                                                                                            | Leans                                                                                    |
| --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| A host on the team's own domain, or an app version that follows their release sequence, with identified users rising alongside it       | Interesting: a launch, a new surface, real growth                                        |
| A new SDK or `$lib` that matches the team's stack, with the same events as their other sources                                          | Interesting: a new integration                                                           |
| A host the team does not own (not their domain, not their proxy)                                                                        | Suspicious: someone copied the snippet or the project token                              |
| Hosts the team does not own, carrying the team's own embedded product (a widget, toolbar, embed or snippet built to run on other sites) | Expected: their product running where it is meant to. Record as `noise:`                 |
| App version values the team never shipped, out of sequence, or in a different version scheme                                            | Suspicious: a fork or a modified build of their client                                   |
| Events with no `$lib` rising, where the baseline came from an SDK                                                                       | Suspicious: a script or server posting straight to the capture API with the public token |
| Many new distinct IDs with about one event each and no `$identify`                                                                      | Suspicious: a bot or spoofed traffic                                                     |
| One or a few distinct IDs with very high counts                                                                                         | A runaway client loop, often the team's own bug                                          |
| A new country or region that dominates the new volume                                                                                   | A hint toward bots or scrapers. Check it against the rest of the shape                   |

Hosts like `localhost`, staging or preview domains, and the team's own CI are dev traffic.
Record them as `noise:` and move on.

## 4. Decide

Report a material, sustained step either way. Below the bar, write a `pattern:` and move on.

- **Interesting** traffic gets a short report that names what drives the growth and how much of the weekly volume it now carries. The team wants to know what moves their bill even when the cause is good news.
- **Suspicious** traffic gets a report that says why it looks foreign and what to do about it:
  confirm whether the source is theirs,
  drop it with a transformation that filters on the host or version,
  set a billing limit while they look,
  and contact PostHog support about the billed volume if the traffic was never theirs.
- Set `actionability` against the harness criteria. A runaway loop in the team's own client is usually a code fix. Foreign traffic usually needs a person to confirm the source and change project settings first.

Put the evidence in the report: the source, the onset, the pinned baseline, the current daily level, the ratio, the days sustained, and an estimate of the excess events since onset (daily events minus the pinned baseline, summed).
Do not convert the excess to a dollar figure. Billing tiers vary by plan, so name the volume and point the team at their billing page.
Attach the daily series as a chart, with the candidate source next to the rest of the project.

## Memory

| Key                                         | Holds                                                                                                                  |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `pattern:general:new-traffic`               | Date of the last check and the top three sources by growth, so the next check knows when it is due and what was normal |
| `pattern:general:traffic-baseline:<origin>` | Onset date, pinned pre-surge baseline, last reported level                                                             |
| `report:general:new-traffic:<origin>`       | The `report_id`, so a later run edits it instead of filing a duplicate                                                 |
| `noise:general:traffic:<origin>`            | A source the team confirmed as theirs, or dev traffic                                                                  |

Edit the existing report when the source grows to about 2x the level you last reported, and again when it falls back near the pinned baseline for 3 days or more.
