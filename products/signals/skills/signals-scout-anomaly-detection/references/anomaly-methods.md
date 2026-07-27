# Anomaly detection methods

How to score the latest bucket of an insight, choose the right cadence, and avoid the two
false-positive traps (weekly seasonality and low-count noise). Two scorers: PostHog's own
anomaly-detection **simulator** for saved time-series insights (primary), and a hand-rolled
robust z-score for everything else (fallback).

## Primary scorer: the alert anomaly-detection simulator

For any watchlist item that is a **saved time-series insight**, score it with `alert-simulate`
instead of hand-rolling stats. It runs PostHog's production anomaly detectors server-side over
the insight's series and returns, per point, the anomaly score and the triggered dates. It's a
stateless preview: it needs only a saved `insight` id, a `detector_config`, and a
`series_index` — **no alert has to exist**, and nothing is written. This is the same engine
behind PostHog's shipped anomaly alerts, so lean on it rather than reinvent z-scores in SQL.

**Pick the detector that fits the series — don't be dogmatic.** The menu: `zscore`, `mad`,
`iqr`, `copod`, `ecod`, `hbos`, `isolation_forest`, `knn`, `lof`, `ocsvm`, `pca`, and
`ensemble` (combine several with `and`/`or`). Each takes a `threshold`, a `window` (rolling
history length), and a `preprocessing` block (`diffs_n`, `lags_n`, `smooth_n`). The config
proven across PostHog's own working alert inventories is an `or`-ensemble of `zscore`
(`diffs_n: 1`, `smooth_n: 3`) + `isolation_forest` (`smooth_n: 3`) at `window` 336 hourly /
~90 daily — a good starting point, not a mandate. For battle-tested, metric-shape-specific
configs and a detector-selection guide, read the `anomaly-alerts`, `signals-alerts`, and
`llma-alerts` skills (via `/phs`).

**Gotchas that will bite (all learned in production):**

- **Every sub-detector inside an `ensemble` needs an explicit `window`.** A null window on a
  standalone detector defaults fine, but a null window inside an ensemble 500s the evaluation.
- **`diffs_n` defaults to `0` (raw values), not `1`.** For `zscore`/`mad` on count or level
  metrics with a diurnal cycle, set `diffs_n: 1` explicitly — differencing is what cancels the
  daily/weekly rhythm. (`mad` on raw sparse/bursty integer counts over-fires; difference it or
  use the ensemble.)
- **Target a time-series insight.** A single-value / BoldNumber insight returns one point and
  scores nothing — point the simulator at a trend displayed over time.
- **`alert-simulate` only accepts `TrendsQuery` insights.** A SQL-backed saved insight
  (`DataVisualizationNode` wrapping a `HogQLQuery` — most revenue, MRR/ARR, and LLM-cost
  insights are this) is rejected outright with `Only TrendsQuery insights are supported`. Don't
  burn a call discovering this: check the insight's `query.kind` first (via `insight-get`), and
  if it's a `DataVisualizationNode`, score it with the SQL fallback below instead of the
  simulator.
- **Breakdown insights return a per-series block per breakdown value plus a meaningless
  rolled-up total.** `series_index` does not cleanly isolate one breakdown value — read the
  per-series sub-blocks, or prefer a non-breakdown insight for a clean read.
- **Only points with ≥ `window` history get scored.** On a short series, simulate with a
  smaller `window` (e.g. ≤ 168) to get scored points; `date_from` controls how far back to go.

**When to still hand-roll (the fallback below).** `alert-simulate` requires a saved insight,
and its detectors use rolling windows rather than explicit same-day-of-week / same-hour-of-week
matching. Keep the SQL path for: series that aren't a saved insight (e.g. an hourly
operational-pulse built in `execute-sql`), custom long baselines, or strict seasonality
matching the detector doesn't do. The MAD-based z-score below is both that fallback and the
concept the simulator automates.

## Fallback scorer: robust z on the latest complete bucket

Use this when `alert-simulate` doesn't apply (a non-saved series) or you need a custom
baseline. For a series of bucket values, the anomaly score of the latest **complete** bucket
`x` is:

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
- **Minimum-data guard.** Need enough comparable baseline buckets after seasonal matching —
  **≥ 6 same-weekday points for daily, ≥ 12 same-hour-of-day points for hourly** (matching
  the Baseline windows table below). Fewer → don't score; widen the cadence or mark it `low-data`
  on the watchlist and move on.
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

| Cadence | Baseline window    | Seasonal match     | Min buckets after matching   |
| ------- | ------------------ | ------------------ | ---------------------------- |
| Daily   | trailing 6–8 weeks | same day-of-week   | ≥ 6 same-weekday points      |
| Hourly  | trailing 2–4 weeks | same hour-of-day † | ≥ 12 same-hour-of-day points |

† Hour-of-day over 2–4 weeks gives ~14–28 comparable points, so the ≥ 12 floor is
attainable. Upgrade to full **hour-of-week** (hour-of-day × weekday) only once you have ~8+
weeks of history — same-hour-of-week yields just one point per week, far too few over 2–4
weeks.

Exclude the latest complete bucket itself from its own baseline, and exclude the current
partial bucket entirely.

## execute-sql cookbook (fallback path)

When `alert-simulate` doesn't apply, `execute-sql` is the most reliable hand-rolled path: it
gives you the full series and the baseline in one query, with exact control over the bucket and
the comparison window. Always
`read-data-schema` to confirm the event/properties first, and `insight-get` to learn which
event(s)/filters the insight actually uses so your SQL matches it.

PostHog SQL is HogQL (ClickHouse dialect). Its date functions (`toStartOfDay`,
`toStartOfHour`, `now()`) already evaluate in the **project timezone** automatically — the
buckets below come back project-local with no explicit timezone argument needed.

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

**Hourly series for a high-volume metric** (last 21 days, hourly, for same-hour-of-day baseline):

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

Score the latest complete `hour` against prior rows sharing its `hod` (same-hour-of-day) —
~14–28 comparable points over 21 days, so the ≥ 12 baseline floor is reachable. To upgrade to
a full hour-of-week baseline (rows sharing both `dow` and `hod`), **first widen the `WHERE
timestamp >= ...` window to ~8+ weeks** — at 21 days `(dow, hod)` yields only ~3 points per
bucket, far below the floor. (`dow` is already selected above, so only the window needs to
change.)

**Tips**

- **Zero buckets produce no row — guard the drop-to-zero case.** `GROUP BY day`/`hour` omits
  buckets that had zero events, so the most recent _returned_ row may not be the latest
  complete bucket. Verify the expected latest bucket (yesterday / last complete hour) is
  actually present; if it's missing, its true value is **0** — score that as a drop-to-zero
  (the highest-signal shape), don't silently fall back to the prior non-zero row. A date/hour
  spine (`arrayJoin`/`range` join) or an explicit presence check avoids the trap.
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

## Distribution shift & changepoint (KS two-sample)

A different lens from everything above. The simulator and the z-score answer _"is the **latest
bucket** an outlier?"_ — point/level detection. They miss a metric whose **mean barely moves
but whose distribution changes shape** (variance widens, a tail appears, a bimodal split, a
mix shift), and they don't tell you _where_ a drift started. A two-sample
**Kolmogorov-Smirnov** test does both: it compares two samples' whole empirical distributions
(`D = max|F_a(x) − F_b(x)|`, with a p-value) and, swept across an ordered series, locates the
**changepoint** that best separates it into two differently-distributed halves. Reach for it
in the explore phase when a watched series looks fine on the mean but you suspect a shape/mix
change, or to pin the onset of a drift a level detector already flagged.

**Running it.** A scheduled run has `Bash` + `python3` but **no repo and no bundled file on
disk** — skill files arrive via `llma-skill-file-get`, not the filesystem — so don't assume
`scripts/ks2.py` is on a path. Two ways to run KS (no numpy/scipy needed; neither is in the
sandbox):

- **Inline** (zero dependencies) — paste a self-contained heredoc for a quick two-sample check:

  ```bash
  python3 - <<'PY'
  import json, math
  def ks(a, b):
      a = sorted(a); b = sorted(b); n, m = len(a), len(b)
      i = j = 0; d = 0.0
      while i < n and j < m:
          x = a[i] if a[i] <= b[j] else b[j]
          while i < n and a[i] <= x: i += 1
          while j < m and b[j] <= x: j += 1
          d = max(d, abs(i/n - j/m))
      en = math.sqrt(n*m/(n+m)); t = (en + 0.12 + 0.11/en)*d
      p = sum(2*(-1)**(k-1)*math.exp(-2*k*k*t*t) for k in range(1, 101))
      return d, max(0.0, min(1.0, p))
  a = []   # window A (seasonality-matched to B)
  b = []   # window B
  d, p = ks(a, b); print(json.dumps({"d": round(d, 4), "p": p}))
  PY
  ```

- **Full helper** — the tested implementation (raw + binned two-sample, and the changepoint
  sweep with a multiple-comparisons `p_adj`) is bundled at `scripts/ks2.py`. Fetch it with
  `llma-skill-file-get` (`file_path: scripts/ks2.py`), write it to `/tmp/ks2.py`, then pipe
  JSON in: `echo '{"mode":"changepoint","series":[...]}' | python3 /tmp/ks2.py`. Request
  shapes: `{"a": [...], "b": [...]}`; `{"a_hist": [[value, count], ...], "b_hist": [...]}`
  (the cheap path); `{"mode": "changepoint", "series": [...ordered...], "min_seg": 24}`.

**Pull histograms, not raw rows.** `execute-sql` caps at 500 rows, and raw samples are
token-heavy. Instead `GROUP BY` a value-bucket expression (e.g.
`round(rate, 4)` or `floor(value/10)*10`) so a whole window comes back as a few dozen
`(value, count)` rows, and feed `a_hist`/`b_hist`. Binned KS reproduces the raw verdict
closely (validated: D 0.76 raw vs 0.77 binned on the same windows) at a fraction of the
payload. For a changepoint you do need the ordered series, but a daily series — or ≤ 500
hourly buckets (~20 days) — fits under the cap.

**Compare like with like — KS is not seasonality-aware.** Fed a weekend window against a
weekday-heavy baseline, KS will correctly report the distributions differ — but that's the
weekly rhythm, not an anomaly. Use seasonality-matched windows: same-day-of-week, full-week
vs full-week (a whole week cancels its own diurnal+weekly shape), or difference the series
first. The same discipline as the rest of this file; KS just makes the trap easy to fall into
because it's so sensitive.

**Calibration.** Emit only when **all three** hold: a small p (≲ ~0.01), a **meaningful effect
size** `D` (the max CDF gap — a real separation, not a hair), and a move not explained by
seasonality or a pipeline gap. On large samples p goes tiny on trivial differences, so `D` and
the windows compared are the real evidence — put both in the finding, plus the changepoint
timestamp when you have one. For a **changepoint**, the returned `p` is a **scan minimum**: the
sweep picked the split that maximized `D` over many candidates, so `p` is biased low by
multiple comparisons. Use `p_adj` (the Bonferroni-corrected value the helper returns), and
confirm the chosen split with a direct two-sample KS on seasonality-matched windows before
treating it as emit evidence — never emit on the raw scan `p` alone.

**Worked example.** A high-volume hourly rate metric (~480 hourly buckets) with a genuine level
shift partway through the window: the changepoint sweep located the break at the shift hour
(`D ≈ 0.86`, corrected `p_adj` tiny); a clean prior week vs the shifted day gave `D ≈ 0.76`;
two ordinary like-for-like weeks compared against each other gave `D ≈ 0.06`, `p ≈ 0.92`
(silent — no false positive). The level detectors saw the drop in magnitude; KS additionally
pinned _when_ it broke and confirmed a genuine distribution shift, not noise — while staying
quiet on seasonality-matched windows.

## Per-insight-type recipes (all insight types are in scope)

Most dashboard tiles are trends-style numeric series and the method above applies directly.
For the other insight types, adapt the same "deviation from the metric's own baseline" idea —
the discriminator is always _the latest value vs its seasonality-matched history_, just on a
different metric.

### Trends (counts / sums / uniques over time) — primary

This is the bulk of dashboards. Score it with `alert-simulate` on the saved insight; drop to
the `insight-query` / `execute-sql` fallback only when the simulator doesn't apply.

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
