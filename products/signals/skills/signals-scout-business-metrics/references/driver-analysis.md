# Detection and key driver analysis

The recipes below use placeholders: `<table>`, `<ts>` (the time column), `<measure>` (a sum or count expression), `<num>` / `<den>` (a ratio's numerator and denominator), and `<dim>` (one dimension column).
Run every query with `execute-sql`, one at a time, and count each call, and each `data-catalog-metric-run`, against the run's budget of 40.
Every query here reads a bounded, absolute window and only the columns it names.
Never widen a window past the grain's cap, and never drop the time predicate.

## Contents

- [Windows per grain](#windows-per-grain)
- [Choosing dimensions](#choosing-dimensions)
- [Detection](#detection)
- [Decomposition](#decomposition)
- [Reading the result](#reading-the-result)

## Windows per grain

| Grain     | Series window        | Current (`cur`)        | Base (`base`)                                          | Widen check              |
| --------- | -------------------- | ---------------------- | ------------------------------------------------------ | ------------------------ |
| Daily     | 35 complete days     | The latest complete day, or the last 7 days for the drift lens | The 4 same weekdays before it, or the 4 prior weeks | 8 weeks, 63 days in total |
| Weekly    | 13 closed weeks      | The latest closed week | The 8 prior closed weeks                               | None                     |
| Monthly   | 13 closed months     | The latest closed month | The 6 prior closed months, plus the same month a year earlier when it exists | None   |
| Quarterly | 9 closed quarters    | The latest closed quarter | The 4 prior closed quarters                         | None                     |

A period is closed when its end is before today, and for a monthly or quarterly measure also when at least 5 (or 10) days have passed since, so late rows have posted.
Pin `cur` and `base` to absolute dates in every query, so a `pending:` candidate decomposed later reads the same periods.

## Choosing dimensions

A metric with its own dimension column (a `GROUP BY month, product`) needs no profile: that column is the dimension, and the decomposition reads the metric's own rows.

For a metric without one, pick candidate columns by name first, from the referenced table's schema (`read-data-schema`), so the profile query stays small: plan, tier, country, region, currency, channel, product, payment method, customer type, status.
Leave out identifiers (ids, emails, URLs, free text), time columns and amounts.

Profile every candidate in **one query** over the base window:

```sql
SELECT count() AS rows,
       uniq(<dim1>) AS dim1_values, countIf(<dim1> IS NULL OR toString(<dim1>) = '') AS dim1_nulls,
       uniq(<dim2>) AS dim2_values, countIf(<dim2> IS NULL OR toString(<dim2>) = '') AS dim2_nulls,
       uniq(<dim3>) AS dim3_values, countIf(<dim3> IS NULL OR toString(<dim3>) = '') AS dim3_nulls
FROM <table>
WHERE <ts> >= '<base start>' AND <ts> < '<cur end>'
```

Keep a dimension when it has 2 to 50 distinct values and its null share (`dimN_nulls / rows`) is under 20%.
Keep at most 5, the ones with the fewest distinct values first, and record them on the `watchlist:` entry with the profile date.
Do not profile again for 30 days.

A join to a person or account table can add a dimension, but only when the join key is clean and the joined table is small.
Never build a multi-table join on a scheduled run.

## Detection

### The series

Prefer the canonical run (`data-catalog-metric-run`) when the budget rules allow it; read each row against `columns`.
Otherwise, the daily shape, with `< today()` dropping the current partial day:

```sql
SELECT toDate(<ts>) AS day, <measure> AS value
FROM <table>
WHERE <ts> >= today() - 35 AND <ts> < today()
GROUP BY day
ORDER BY day
LIMIT 40
```

For a monthly measure, `toStartOfMonth(<ts>)` over 13 closed months, `LIMIT 14`; weekly and quarterly follow the same pattern.
A missing period in the result is a zero only when the source is fresh.
Otherwise it is missing data.
Both daily lenses read this one result; do not run a second series query.

### Step lens (daily)

For the latest complete day `d`:

- `median_28d`: the median of the 28 days before `d`.
- `median_same_weekday`: the median of `d - 7`, `d - 14`, `d - 21`, `d - 28`.

Pass when `abs(value - median_28d) >= 0.3 * median_28d`, `abs(value - median_same_weekday) >= 0.3 * median_same_weekday`, and `greatest(value, median_28d) >= 20`.
For a money measure, apply the 20 floor to the count of rows behind it, not to the amount.

### Drift lens (daily)

Compare the sum (or the ratio) over the last 7 complete days with the average of the 4 prior 7-day windows.
Pass at 15% or more.
Then check the 4 prior week-over-week changes.
When at least 3 of them already went the same direction, this is a long trend that is already visible, not a new move.
Remember it, do not report it.

### Period lens (weekly, monthly, quarterly)

Compare the latest closed period with the median of the prior periods in the base.
Pass at 20% or more off that median, with the same 20-unit floor.
For a monthly measure with 13 closed months, also compare with the same month a year earlier: a move that the year-earlier month shows too is seasonal, so remember it and do not report it.
A measure that moved by 20% or more in the same direction in each of the 3 prior periods is a long trend, not a new move.

## Decomposition

Use the `cur` and `base` windows of the lens that passed.

### From the metric's own rows

When the series carries a dimension column, group its rows: `cur` per segment, the average of the base periods per segment, and the delta.
No query runs.
Segments past the 20th by `abs(delta)` go into one "other" row.

### Sum or count, from the table

```sql
SELECT <dim> AS segment,
       sumIf(<measure_column>, <ts> >= '<cur start>' AND <ts> < '<cur end>') AS cur,
       sumIf(<measure_column>, <base condition>) / <number of base periods> AS base,
       cur - base AS delta
FROM <table>
WHERE <ts> >= '<base start>' AND <ts> < '<cur end>'
GROUP BY segment
ORDER BY abs(delta) DESC
LIMIT 20
```

Use `countIf` instead of `sumIf` for a count measure.
Each segment's share of the move is `delta / sum(delta)`.
Segments past the 20th go into one "other" row, computed as the total delta from the series minus the listed segments.

### Ratio, from the table

For each segment `s`, with `w` = the segment's share of the total denominator and `r` = the segment's own ratio:

- mix effect: `(w_cur(s) - w_base(s)) * r_base(s)`
- rate effect: `w_cur(s) * (r_cur(s) - r_base(s))`

The mix and rate effects over all segments add up to the change in the overall ratio.

```sql
SELECT <dim> AS segment,
       sumIf(<num>, <cur condition>) AS num_cur,
       sumIf(<den>, <cur condition>) AS den_cur,
       sumIf(<num>, <base condition>) / <number of base periods> AS num_base,
       sumIf(<den>, <base condition>) / <number of base periods> AS den_base
FROM <table>
WHERE <ts> >= '<base start>' AND <ts> < '<cur end>'
GROUP BY segment
ORDER BY den_cur DESC
LIMIT 20
```

Compute `w`, `r`, and both effects from these rows locally (`python3` in Bash), so the arithmetic stays exact and costs no query.
Skip a segment with a zero denominator in either window, and note it.

### The widen check (daily, full-method tier only)

Before you trust a driver, run its dimension query once more with the base set to the 8 prior weeks (`/ 8`), 63 days in total.
A driver that holds against both bases is real.
Skip it in the 20M-to-200M tier and say so in the evidence.

## Reading the result

| Shape                                                           | Meaning                                                                                                                                 |
| --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 1 or 2 segments carry 60% or more of the delta, the others hold | A driver. This is the report.                                                                                                           |
| Every segment moves by a similar share                          | A global cause: data, capture, a calendar effect or a whole-market move. Not a driver report.                                           |
| Ratio: the mix effect is larger than the rate effect            | The audience changed, not the behavior. Say so in the report.                                                                           |
| Ratio: the rate effect is larger                                | The segment itself performs differently. The stronger finding.                                                                          |
| Two dimensions both explain the move                            | They are probably the same segment (for example, a currency and a country). Report the more specific one and mention the other.         |
| No dimension passes                                             | Remember the move. Check it again next run.                                                                                             |

With 5 dimensions and up to 20 segments each, some segments move by chance.
Trust a driver only when its segment has at least 20 units in the base window and, at daily grain, the widen check holds.
