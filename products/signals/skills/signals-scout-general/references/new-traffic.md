# New traffic: where did the extra events come from?

A project's event volume can step up for good reasons (a launch, a new SDK, a new market) or for bad ones (a public project token copied into a fork or an open-source build, a leaked key, a bot, a client stuck in a loop).
The team pays for every event either way, and a slow-growing surge is easy to miss: it never trips a one-day spike detector, and every trailing baseline absorbs it within a few weeks.
No specialist scout owns this. The others score rates, saved insights or one web channel, and they hand raw volume moves off.

This check is cheap and slow-moving, so run it every few runs, not every run.
Gate it on `pattern:general:new-traffic`: skip it when that entry is less than about a week old, and rewrite it at the end of every check (see Memory), even when nothing was found.

## 1. Find the step, by source

The profile's `top_events` covers 7 days, so it cannot see a step that started weeks ago.
Compare the latest 7 days with the same 7 days 4 weeks back and 8 weeks back, broken down by where the events come from.

### Confirm the source properties first

`$lib`, `$host` and `$app_version` are optional. A server SDK sends no `$host`, a web SDK sends no `$app_version`, and a direct call to the capture API can send none of them.
Before the first query, confirm each one with `read-data-schema`:

- Call it with `event_properties` for the top three events by volume in the profile's `top_events`.
- A property is confirmed when it appears on at least one of these events.
- Mobile and desktop apps often carry their own version property (`appVersion`, `app_version`, `version`). Look for a property that ends in `version`, and use it in place of `$app_version` when `$app_version` is not confirmed.

Build the two source expressions from confirmed properties only.
`'(none)'` is the unknown bucket: it holds events that have no value, and it is the whole expression when no property is confirmed.

- `<lib>`: `coalesce(nullIf(toString(properties.$lib), ''), '(none)')` when `$lib` is confirmed, else `'(none)'`.
- `<origin>`: one `nullIf(toString(properties.<property>), '')` term for each confirmed property, host first, then the version property, followed by `'(none)'`, all inside one `coalesce`:

| Confirmed origin properties | `<origin>`                                                                                                  |
| --------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `$host` and `$app_version`  | `coalesce(nullIf(toString(properties.$host), ''), nullIf(toString(properties.$app_version), ''), '(none)')` |
| `$host` only                | `coalesce(nullIf(toString(properties.$host), ''), '(none)')`                                                |
| `$app_version` only         | `coalesce(nullIf(toString(properties.$app_version), ''), '(none)')`                                         |
| Neither                     | `'(none)'`                                                                                                  |

Put the same `<lib>` and `<origin>` text into every query in steps 1, 2 and 3. A different expression gives different `source_id` values for the same traffic.
Write both expressions to `pattern:general:new-traffic` and reuse them on later runs, so each `source_id` keeps its pinned baseline.
Build them again only when the schema adds or drops a source property.

### Compare the windows

```sql
SELECT
    <lib> AS lib,
    <origin> AS origin,
    cityHash64(concat(lib, '|', origin)) AS source_id,
    countIf(timestamp >= now() - INTERVAL 7 DAY) AS last_7d,
    countIf(timestamp >= now() - INTERVAL 35 DAY AND timestamp < now() - INTERVAL 28 DAY) AS week_4_back,
    countIf(timestamp < now() - INTERVAL 56 DAY) AS week_8_back,
    round(last_7d / greatest(week_4_back, 1), 2) AS ratio_4w,
    round(last_7d / greatest(week_8_back, 1), 2) AS ratio_8w,
    toInt(last_7d) - toInt(least(week_4_back, week_8_back)) AS growth,
    uniqIf(distinct_id, timestamp >= now() - INTERVAL 7 DAY) AS ids_7d
FROM events
WHERE timestamp <= now() + INTERVAL 1 DAY
    AND (
        timestamp >= now() - INTERVAL 7 DAY
        OR (timestamp >= now() - INTERVAL 35 DAY AND timestamp < now() - INTERVAL 28 DAY)
        OR (timestamp >= now() - INTERVAL 63 DAY AND timestamp < now() - INTERVAL 56 DAY)
    )
GROUP BY lib, origin
HAVING last_7d >= 1000
ORDER BY growth DESC
LIMIT 20
```

- The query reads three single weeks, not a rolling window, so it scans 21 days and every week lines up on the same weekdays.
- `ratio_8w` catches a slow surge. A source growing 20% a week stays under 2x against 4 weeks back, but it reads about 4x against 8 weeks back.
- Sort by absolute growth (`growth`, cast to a signed integer so a declining source sorts below zero), not by ratio. A 2000x ratio on a few hundred events is noise. A 1.5x ratio on the project's biggest source can be most of the bill.
- Do not add `SAMPLE`. Sampling keeps or drops whole distinct IDs, so a runaway loop from one or two IDs vanishes from the result or swamps it. If the query times out, drop the 8-weeks-back window first.
- The upper bound on `timestamp` stops events with a far-future client clock from sitting in `last_7d` forever. Keep it on every query here.

For the project total, run the same windows with no source columns:

```sql
SELECT
    countIf(timestamp >= now() - INTERVAL 7 DAY) AS last_7d,
    countIf(timestamp >= now() - INTERVAL 35 DAY AND timestamp < now() - INTERVAL 28 DAY) AS week_4_back,
    countIf(timestamp < now() - INTERVAL 56 DAY) AS week_8_back
FROM events
WHERE timestamp <= now() + INTERVAL 1 DAY
    AND (
        timestamp >= now() - INTERVAL 7 DAY
        OR (timestamp >= now() - INTERVAL 35 DAY AND timestamp < now() - INTERVAL 28 DAY)
        OR (timestamp >= now() - INTERVAL 63 DAY AND timestamp < now() - INTERVAL 56 DAY)
    )
```

A candidate is a source that grew to about 2x or more against either window **and** now carries a meaningful share of the project's `last_7d` (about 10% or more), or a source that appeared from nothing at that share.
Volume matters too. On a small project a doubling from 100 to 200 events a week costs nothing, so something around 10,000 events a week is a sensible floor before a step is worth a person's time.

Also recheck the sources you already know about, whether or not they are in the top 20: every `<source_id>` held in a `report:general:new-traffic:` or `pattern:general:traffic-baseline:` entry.
Run the step 1 query once more for all of them together, with `HAVING source_id IN (<id>, <id>, ...)` in place of the volume floor and without the `LIMIT`.
Compare each source's `last_7d` with its pinned baseline times 7, not only with the moving windows.
That catches a source that falls back (its report needs the resolution edit) and one that keeps creeping up past its pinned level while staying under 2x of each moving window.

## 2. Confirm it is sustained and pin the onset

Pull a 91-day daily series for the candidate only. 91 days covers the 28 days before any onset that step 1 can see.
Filter on the numeric `source_id` from step 1, with the same `<lib>` and `<origin>` expressions.
Never paste a host or version string into the query: those values come from captured events, and anyone with the public project token can put a quote in one.

```sql
SELECT toDate(timestamp) AS day, count() AS events, uniq(distinct_id) AS ids
FROM events
WHERE timestamp >= now() - INTERVAL 91 DAY
    AND timestamp <= now() + INTERVAL 1 DAY
    AND cityHash64(concat(<lib>, '|', <origin>)) = <source_id>
GROUP BY day
ORDER BY day
```

- **Onset**: the first day of the step.
- **Pre-surge baseline**: the total events over the 28 days before the onset, divided by 28. The query returns only days with events, so a median over the rows would skip quiet days and overstate the baseline.
- A step that has not held for 3 days or more is a spike, not new traffic. Leave it, or record it as a `pattern:` and check again next time.

Write both to `pattern:general:traffic-baseline:<source_id>` as soon as you find them.
Later runs compare against this pinned baseline, not a trailing one. That keeps a surge that grows slowly visible.

## 3. Read the shape

Drill into the candidate before you decide what it is, with the same `source_id` filter:

```sql
SELECT
    event,
    count() AS events,
    uniq(distinct_id) AS ids,
    round(count() / greatest(uniq(distinct_id), 1), 1) AS events_per_id,
    min(timestamp) AS first_seen_in_7d
FROM events
WHERE timestamp >= now() - INTERVAL 7 DAY
    AND timestamp <= now() + INTERVAL 1 DAY
    AND cityHash64(concat(<lib>, '|', <origin>)) = <source_id>
GROUP BY event
ORDER BY events DESC
LIMIT 20
```

`first_seen_in_7d` is the earliest event inside this 7-day window, not the first time the event ever appeared.
Use the step 2 series to judge whether a source is new.
Add `properties.$lib_version`, `properties.$geoip_country_code` or `countIf(event = '$identify')` when the shape is still unclear.

| What you see                                                                                                                            | Leans                                                                                    |
| --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| A host on the team's own domain, or an app version that follows their release sequence, with identified users rising alongside it       | Growth: a launch, a new surface, real users                                              |
| A new SDK or `$lib` that matches the team's stack, with the same events as their other sources                                          | Growth: a new integration                                                                |
| A host the team does not own (not their domain, not their proxy)                                                                        | Suspicious: someone copied the snippet or the project token                              |
| Hosts the team does not own, carrying the team's own embedded product (a widget, toolbar, embed or snippet built to run on other sites) | Expected: their product running where it is meant to                                     |
| App version values the team never shipped, out of sequence, or in a different version scheme                                            | Suspicious: a fork or a modified build of their client                                   |
| Events with no `$lib` rising, where the baseline came from an SDK                                                                       | Suspicious: a script or server posting straight to the capture API with the public token |
| Many new distinct IDs with about one event each and no `$identify`                                                                      | Suspicious: a bot or spoofed traffic                                                     |
| One or a few distinct IDs with very high counts                                                                                         | A runaway client loop, often the team's own bug                                          |
| A new country or region that dominates the new volume                                                                                   | A hint toward bots or scrapers. Check it against the rest of the shape                   |

## 4. Decide

How to read the step, whether to report it, and its actionability are your call.
Some context for that call:

- A significant step (a candidate from step 1 that held for 3 days or more in step 2) usually deserves a report even when it looks like good news. It moves the team's bill and changes what their data means, and a person can often tell in seconds what you cannot see from the data.
- A small step is usually better as a `pattern:general:traffic-baseline:<source_id>` entry, so a later run can tell when that source changes shape.
- The shape from step 3 is the most useful lead for a reader: growth from their own surface, traffic that looks foreign, or a loop.
- Next steps that often fit: confirm whether the source is theirs and wanted, filter it in code (a `before_send` check on the host or app version) or with a transformation that drops it, fix a loop in their own client, set a billing limit while they look, and contact PostHog support about the billed volume if the traffic was never theirs.
- The harness suppresses a `not_actionable` report, so a step you want a person to see needs an actionability that reflects the decision in front of them.

Put the evidence in the report: the source, the onset, the pinned baseline, the current daily level, the ratio, the days sustained, and an estimate of the excess events since onset (daily events minus the pinned baseline, summed).
Do not convert the excess to a dollar figure. Billing tiers vary by plan, so name the volume and point the team at their billing page.
Attach the daily series as a chart, with the candidate source next to the rest of the project.

## Memory

Key every per-source entry on the numeric `source_id` from step 1, and write the readable `lib` and `origin` into the entry's content.
Two SDKs on one host are two sources, and they need separate baselines and reports.

| Key                                            | Holds                                                                                                                                                        |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `pattern:general:new-traffic`                  | Date of the last check, the `<lib>` and `<origin>` expressions, and the top three sources by growth. Rewrite it at the end of every check, so the gate works |
| `pattern:general:traffic-baseline:<source_id>` | `lib`, `origin`, onset date, pinned pre-surge baseline, last reported level or last seen level                                                               |
| `report:general:new-traffic:<source_id>`       | The `report_id`, so a later run edits it instead of filing a duplicate                                                                                       |
| `noise:general:traffic:<source_id>`            | Dev traffic only: `localhost`, staging or preview domains, the team's own CI                                                                                 |

Do not record a source as `noise:` only because it is the team's own or is expected.
Keep it as a `pattern:` with its level, so a later loop, bot flood or new step on that same source still surfaces.

Edit the existing report when the source grows to about 2x the level you last reported, and again when it falls back near the pinned baseline for 3 days or more.
Check the report's status with `inbox-reports-retrieve` first.
Edit only a report that is still live. When it is resolved, suppressed or failed and the traffic comes back, author a fresh report and point `report:general:new-traffic:<source_id>` at the new id.
