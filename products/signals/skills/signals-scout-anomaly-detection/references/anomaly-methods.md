# Anomaly detection methods

How to turn an insight into a clean time series, choose the right cadence, build a
seasonality-matched baseline, and score the latest bucket. The goal is a method robust
enough that you can trust a high z-score, and conservative enough that weekly seasonality and
low-count noise don't generate false positives.

## The core score: robust z on the latest complete bucket

For a series of bucket values, the anomaly score of the latest **complete** bucket `x` is:

```text
median  = median(baseline buckets)
MAD     = median(|b - median| for b in baseline buckets)
robust_z = |x - median| / (1.4826 * MAD)
```

- `1.4826 * MAD` is the normal-consistent robust estimate of standard deviation. It is far
  more resistant to the occasional past spike than a plain mean/stddev — past anomalies in
  the baseline window won't desensitize you.
- **Emit threshold: `robust_z ≥ ~3.5`** on the latest complete bucket. Treat `2.5–3.5` as
  "watch / remember", below `2.5` as normal.
- **Direction matters**: a spike (`x > median`) and a drop (`x < median`) are both anomalies;
  say which in the finding. A drop to exactly zero across a previously non-zero series is the
  highest-signal shape (possible outage or pipeline break).

### Guards (apply before trusting the score)

- **Partial-bucket guard.** Never score the in-progress bucket. For daily series, the latest
  complete day is _yesterday_ (in the project's timezone — read it from the environment
  block); for hourly, the latest complete hour is the one before the current one. Exclude the
  current partial bucket from both scoring and baseline.
- **Minimum-data guard.** Need at least ~12 comparable baseline buckets after seasonal
  matching. Fewer → don't score; set the insight's cadence wider or mark it `low-data` on the
  watchlist and move on.
- **MAD-zero guard.** If `MAD == 0` (a flat series, e.g. constant or mostly zeros), the
  z-score explodes on any movement. Fall back to: emit only if the absolute change is large
  _and_ the relative change clears the floor below; otherwise remember, don't emit.
- **Low-count floor.** Require both a **relative** move (`|x - median| / max(median, 1) ≥
~0.5`, i.e. ≥50%) **and** a **minimum absolute** baseline (`median ≥ ~20` events/bucket)
  before emitting. Tiny series move around a lot in percentage terms — this is the single
  biggest false-positive source after seasonality.

## Cadence: hourly vs daily

Pick per insight and store it on the watchlist entry. Infer it from the insight's own
definition (`insight-get`) and its volume:

| Pick **hourly** when…                                             | Pick **daily** when…                                       |
| ----------------------------------------------------------------- | ---------------------------------------------------------- |
| High-volume operational metric (≫ hundreds/hour)                  | Business / product metric that moves on a daily rhythm     |
| The insight itself uses an hourly interval or a short (≤7d) range | Revenue, signups, conversions, retention, weekly actives   |
| You want to catch a regression within the same day                | Hourly buckets would be too sparse to baseline (low-count) |

When unsure, start **daily** (cheaper, less noisy) and promote an insight to hourly only if
it's high-volume and a human would care about a same-day move.

## Seasonality matching

Compare like with like — this is what separates a real anomaly from the normal rhythm.

- **Daily cadence → match day-of-week.** Baseline = the same weekday over the trailing
  ~6–8 weeks (e.g. score this Monday against the last ~6–8 Mondays). A Monday is not
  comparable to a Sunday.
- **Hourly cadence → match hour-of-week** (hour-of-day × weekday) when you have enough
  history, or at minimum hour-of-day over the trailing ~2–4 weeks. 3pm Tuesday is not
  comparable to 4am Sunday.
- If history is too short for full seasonal matching, fall back to a shorter window with
  weaker matching (hour-of-day only) and lower your confidence accordingly — or mark the item
  `low-data` and skip emitting.

## Baseline windows (defaults)

| Cadence | Baseline window    | Seasonal match    | Min buckets after matching |
| ------- | ------------------ | ----------------- | -------------------------- |
| Daily   | trailing 6–8 weeks | same day-of-week  | ≥ 6 same-weekday points    |
| Hourly  | trailing 2–4 weeks | same hour-of-week | ≥ 12 matched points        |

Exclude the latest complete bucket itself from its own baseline, and exclude the current
partial bucket entirely.

## execute-sql cookbook

`execute-sql` is the most reliable path: it gives you the full series and the baseline in one
query, with exact control over the bucket and the comparison window. Always
`read-data-schema` to confirm the event/properties first, and `insight-get` to learn which
event(s)/filters the insight actually uses so your SQL matches it.

PostHog SQL is HogQL (ClickHouse dialect). Use the project timezone for bucket boundaries.

**Daily series with same-weekday baseline** (score yesterday vs the last 8 same-weekdays):

```sql
-- Replace <event> and any property filters to match the insight (from insight-get).
WITH daily AS (
    SELECT toStartOfDay(timestamp) AS day, count() AS value
    FROM events
    WHERE event = '<event>'
      AND timestamp >= now() - INTERVAL 60 DAY
      AND timestamp < toStartOfDay(now())          -- exclude today (partial)
    GROUP BY day
)
SELECT day, toDayOfWeek(day) AS dow, value
FROM daily
ORDER BY day DESC
```

Then in your reasoning: take the most recent `day` as `x`, filter the rest to the same `dow`,
compute median + MAD over those, and score. (Compute the robust stats in your head / from the
rows — keep the SQL simple and do the small stats on the returned series.)

**Hourly series for a high-volume metric** (last 21 days, hourly, for hour-of-week baseline):

```sql
SELECT toStartOfHour(timestamp) AS hour,
       toDayOfWeek(timestamp)   AS dow,
       toHour(timestamp)        AS hod,
       count() AS value
FROM events
WHERE event = '<event>'
  AND timestamp >= now() - INTERVAL 21 DAY
  AND timestamp < toStartOfHour(now())            -- exclude current partial hour
GROUP BY hour, dow, hod
ORDER BY hour DESC
```

Score the latest complete `hour` against prior rows sharing its `(dow, hod)`.

**Tips**

- For unique-user or sum metrics, swap `count()` for `count(DISTINCT person_id)` or
  `sum(toFloat(properties.<prop>))` to match the insight's math.
- If the insight is a saved one and you only need its standard windows, prefer `insight-query`
  with `filters_override` (`{"date_from": "-30d"}`) and read the returned series rather than
  rebuilding the SQL — fall back to SQL when you need a custom bucket or a longer baseline
  than the insight defines.
- A move that appears identically across many unrelated insights at the same timestamp is a
  data/pipeline artifact, not per-insight signal — see the disqualifier in the body.

## Attribute the move via the breakdown

When a metric moves, don't stop at the top-line number — find _which segment_ drove it. Most
saved insights already carry a breakdown; re-run the insight (`insight-query`, widened with
`filters_override`) or add a `GROUP BY <dimension>` to your SQL and score the leading segment
against its own baseline. Attribution sharpens the finding ("the move is entirely segment X")
and separates noise from signal: a single known segment ramping — a new feature, a backfill,
an internal product dialing up usage — is usually expected and belongs in a
`noise:`/`addressed:` memory, whereas a move spread across many unrelated segments is a real
broad regression. Put the driving segment and its share of the move in the evidence.

## Per-insight-type recipes (all insight types are in scope)

Most dashboard tiles are trends-style numeric series and the method above applies directly.
For the other insight types, adapt the same "deviation from the metric's own baseline" idea —
the discriminator is always _the latest value vs its seasonality-matched history_, just on a
different metric.

### Trends (counts / sums / uniques over time) — primary

The core method above. This is the bulk of dashboards. Pull the series via `insight-query`
(json) or rebuild with `execute-sql`; score the latest complete bucket.

### Funnels — overall conversion rate as the metric

Run the funnel over a recent window and the trailing baseline window (`insight-query` with
`filters_override` date ranges, or `query-funnel`). The tracked metric is **overall
conversion rate** (and optionally the largest per-step drop-off). Baseline = conversion rate
over comparable prior windows. Anomaly = the conversion rate moves materially (e.g. ≥ a few
points, clearing the relative floor) vs baseline, especially a sudden drop at one step.
Daily cadence is almost always right for funnels.

### Retention — first-period or cohort-curve shift

Run the retention insight and track the **Day-1 / Week-1 retention value** (and the overall
curve shape) for the most recent fully-observed cohort vs prior cohorts. Anomaly = the latest
mature cohort's early-period retention drops/jumps materially vs the trailing cohorts. Only
score cohorts old enough to be fully observed for the period you're measuring; never score a
cohort whose retention window hasn't elapsed.

### Paths / stickiness / lifecycle

Track the single headline number these expose (e.g. lifecycle's new/returning/resurrecting
/dormant counts, stickiness's active-days distribution mode) and score that number against
its trailing seasonality-matched baseline. These are noisier and lower priority — prefer to
spend the run on trends/funnels/retention, and only deep-dive these when a dashboard the team
clearly cares about is built around one.

For any type, if you can't get a clean comparable baseline, mark the item `low-data` on the
watchlist and skip emitting rather than guessing.
