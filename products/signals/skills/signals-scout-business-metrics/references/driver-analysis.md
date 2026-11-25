# Detection and key driver analysis

The recipes below use placeholders: `<table>`, `<ts>` (the time column), `<measure>` (a sum or count expression), `<num>` / `<den>` (a ratio's numerator and denominator), and `<dim>` (one dimension column).
Run every query with `execute-sql`. Bound every scan by time: never read a full table.

## Contents

- [Fallback selection](#fallback-selection)
- [Choosing dimensions](#choosing-dimensions)
- [Detection](#detection)
- [Decomposition](#decomposition)
- [Reading the result](#reading-the-result)

## Fallback selection

Use this only when the project has no approved, non-drifted catalog metric.

The warehouse tables people query most are the tables the business cares about.
Read them from `query_log`, with the same hygiene filters the data-warehouse scout uses:

```sql
SELECT extract(query, '(?i)from\\s+([a-z0-9_\\.]+)') AS table_name,
       count() AS runs,
       uniq(created_by) AS people
FROM query_log
WHERE event_date >= today() - 14
  AND event_time >= now() - INTERVAL 14 DAY
  AND status = 'QueryFinish'
  AND endpoint != ''
  AND query != ''
GROUP BY table_name
HAVING people >= 2
ORDER BY people DESC, runs DESC
LIMIT 15
```

Keep a table only when `system.data_warehouse_tables.columns` shows a date or datetime column and a numeric column.
Prefer measures that look like money or counts of business objects (amount, total, price, quantity, orders, subscriptions).
A table that only one person queries is an exploration, not a business measure.

## Choosing dimensions

Pick at most 5 dimensions per measure. Check each candidate with one query over the last 28 days:

```sql
SELECT uniq(<dim>) AS distinct_values,
       countIf(<dim> IS NULL OR toString(<dim>) = '') / count() AS null_share
FROM <table>
WHERE <ts> >= now() - INTERVAL 28 DAY
```

Keep a dimension when:

- it has 2 to 50 distinct values,
- its null or empty share is under 20%,
- it is not an identifier (ids, emails, URLs, free text) and not a time column.

Good dimensions name a business segment: plan, tier, country, region, currency, channel, product, payment method, customer type.
A join to a person or account table can add a dimension, but only when the join key is clean. Do not build multi-table joins on every run.

## Detection

### Daily series

```sql
SELECT toDate(<ts>) AS day, <measure> AS value
FROM <table>
WHERE <ts> >= today() - 35 AND <ts> < today()
GROUP BY day
ORDER BY day
```

`< today()` drops the current partial day. A missing day in the result is a zero only when the source is fresh. Otherwise it is missing data.

### Step lens

For the latest complete day `d`:

- `median_28d`: the median of the 28 days before `d`.
- `median_same_weekday`: the median of `d - 7`, `d - 14`, `d - 21`, `d - 28`.

Pass when `abs(value - median_28d) >= 0.3 * median_28d`, `abs(value - median_same_weekday) >= 0.3 * median_same_weekday`, and `greatest(value, median_28d) >= 20`. For a money measure, apply the 20 floor to the count of rows behind it, not to the amount.

### Drift lens

Compare the sum (or the ratio) over the last 7 complete days with the average of the 4 prior 7-day windows.
Pass at 15% or more.
Then check the 4 prior week-over-week changes. When at least 3 of them already went the same direction, this is a long trend that is already visible, not a new move. Remember it, do not report it.

## Decomposition

Use the same two windows as the lens that passed:

- step lens: `cur` = day `d`, `base` = the average of the 4 same weekdays before `d`,
- drift lens: `cur` = the last 7 days, `base` = the average of the 4 prior 7-day windows.

### Sum or count

```sql
SELECT <dim> AS segment,
       sumIf(<measure_column>, <cur_condition>) AS cur,
       sumIf(<measure_column>, <base_condition>) / 4 AS base,
       cur - base AS delta
FROM <table>
WHERE <ts> >= <earliest base start> AND <ts> < <cur end>
GROUP BY segment
ORDER BY abs(delta) DESC
LIMIT 20
```

Use `countIf` instead of `sumIf` for a count measure.
Each segment's share of the move is `delta / sum(delta)`.
Segments past the 20th go into one "other" row, computed as the total delta minus the listed segments.

### Ratio

For each segment `s`, with `w` = the segment's share of the total denominator and `r` = the segment's own ratio:

- mix effect: `(w_cur(s) - w_base(s)) * r_base(s)`
- rate effect: `w_cur(s) * (r_cur(s) - r_base(s))`

The mix and rate effects over all segments add up to the change in the overall ratio.

```sql
SELECT <dim> AS segment,
       sumIf(<num>, <cur_condition>) AS num_cur,
       sumIf(<den>, <cur_condition>) AS den_cur,
       sumIf(<num>, <base_condition>) / 4 AS num_base,
       sumIf(<den>, <base_condition>) / 4 AS den_base
FROM <table>
WHERE <ts> >= <earliest base start> AND <ts> < <cur end>
GROUP BY segment
```

Compute `w`, `r`, and both effects from these rows locally (`python3` in Bash), so the arithmetic stays exact.
Skip a segment with a zero denominator in either window, and note it.

## Reading the result

| Shape                                                                 | Meaning                                                                                       |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 1 or 2 segments carry 60% or more of the delta, the others hold       | A driver. This is the report.                                                                 |
| Every segment moves by a similar share                                | A global cause: data, capture, a calendar effect or a whole-market move. Not a driver report. |
| Ratio: the mix effect is larger than the rate effect                  | The audience changed, not the behavior. Say so in the report.                                 |
| Ratio: the rate effect is larger                                      | The segment itself performs differently. The stronger finding.                                |
| Two dimensions both explain the move                                  | They are probably the same segment (for example, a currency and a country). Report the more specific one and mention the other. |
| No dimension passes                                                   | Remember the move. Check it again next run.                                                   |

With 5 dimensions and up to 20 segments each, some segments move by chance.
Trust a driver only when its segment has at least 20 units in the base window and the move is still there when you widen the base to 8 weeks.
