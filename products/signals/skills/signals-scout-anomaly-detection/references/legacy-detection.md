# Legacy detection: the watchlist method

Use this method only in legacy mode: the project has no `$anomaly_score` events, so you score insights yourself.

**The discriminator.** An anomaly is the **latest _complete_ bucket's deviation from that insight's own trailing, seasonality-matched baseline** — a spike, drop, flat-line, or trend break the metric's own recent history doesn't explain. **Don't reinvent the scoring.** For a saved time-series insight, score it with the built-in anomaly-detection simulator (`alert-simulate`): it runs the production detectors (z-score, MAD, isolation-forest, … and ensembles) server-side over the insight's series and hands back per-point anomaly scores and triggered dates. Only fall back to a hand-computed MAD-based z-score (`|value − median| / (1.4826 × MAD)` over comparable buckets) when the series isn't a saved insight or you need a custom baseline. Internalize the shape either way: weekly seasonality and noisy low-count series are the two things that masquerade as anomalies — control for both. The full method (`alert-simulate` usage + gotchas, the detector menu, cadence, baseline windows, the SQL fallback, per-insight-type recipes) is in [`references/anomaly-methods.md`](anomaly-methods.md) — read it before scoring your first candidate.

You cannot scan a whole project in one run. Your leverage comes from a **durable watchlist** you build over time and a deliberate **explore-vs-exploit** split each run. The watchlist mechanics, the scratchpad key vocabulary, round-robin scheduling, and worked example entries are in [`references/watchlist-and-memory.md`](watchlist-and-memory.md) — it is the spine of this scout, read it early.

## Quick close-out: is anything worth checking?

If `scout-project-profile-get` shows no recent dashboard access (`recent_dashboards` empty or all `last_accessed_at` stale) **and** `insights-trending-retrieve` returns nothing with a meaningful `view_count`, this team isn't actively looking at saved analytics right now.
That proves low saved-analytics use. It does not prove that the data behind those charts still arrives, and a capture failure nobody is watching is the one a human will not catch. So check two things before you close out:

1. **Due watchlist items.** Read the watchlist first (see Get oriented). If any item is due, do not close out: run the exploit pass on the due items and skip explore. Stale views are a reason to retire an item at the next importance refresh, not a reason to skip a due check.
2. **Source liveness.** Run the bounded probe in [`references/source-liveness.md`](source-liveness.md). It screens each previously active product source's latest complete day against its own trailing 28 days, on source properties you confirm first, and confirms a drop only against the source's weekly rhythm.

Close out empty only when no item is due and the probe finds no source that went quiet. Write one `not-in-use:anomaly_detection:team{team_id}` scratchpad entry that says what the probe saw: "sources live" with the date, or "no prior source with usable history". A project with no usable history is not broken, so it keeps the quiet exit. Re-running with the same key idempotently refreshes the timestamp.
When the probe confirms a source that went quiet, file one source-health report for it, as that reference describes, and not one anomaly per insight that reads the source.

## How a run works

Cycle between these moves; skip what's not useful. Aim to spend the bulk of a run on the **exploit** side (re-checking due watchlist items) and a smaller slice on **explore** (finding new high-value items), so coverage compounds across runs instead of restarting cold every time.

### Get oriented

Three cheap reads cold-start every run:

- `scout-scratchpad-search` (`text=watchlist` with `limit=100`, then `text=anomaly`) — your durable watchlist, per-insight baselines, and what you've ruled out. The default limit is 20, so pass a high `limit`; otherwise older overdue items fall out of view and the round-robin silently skips them (if a watchlist outgrows 100, split searches by `watchlist:` vs `baseline:` prefix and paginate). This is what makes you cheaper and smarter each run.
- `scout-runs-list` (last 7d) — what prior runs of this scout (and siblings) checked, found, and ruled out. Don't re-walk ground a recent run already covered.
- `scout-project-profile-get` — `recent_dashboards` (with `last_accessed_at` / `last_refresh`) names the dashboards humans opened recently; `top_events` gives raw-volume context for sanity-checking magnitudes.

### Exploit — re-check the watchlist items that are due

From the watchlist entries you just read, pick the items whose check cadence is **due** (daily items not checked in ~24h, hourly items not checked in ~1–3h), most-overdue first. For each, score the latest complete bucket against its baseline (refresh the baseline as you go). Tools, primary first:

- `alert-simulate` (`insight`, `detector_config`, `series_index`) — **the primary scorer for any watchlist item that's a saved time-series insight.** Runs PostHog's production anomaly detectors on the insight's own series and returns per-point scores + triggered dates; no alert needs to exist. Pick the detector(s) that fit the series — `anomaly-methods.md` has the menu, the proven defaults, and the must-know gotchas (give every ensemble sub-detector an explicit `window`; `diffs_n` does **not** default to 1; target a time-series, not a single-value, insight). **Never pass the AI detector (`llm`)**: it makes a charged model call per simulate, needs `alert:write`, and judges only the latest point with no scores.
- `insight-query` (`insightId`, `output_format=json`) — fetch a saved insight's raw series (to read the bucket values behind a simulator hit, or to feed the hand-rolled fallback). **It returns the insight's own date range (often just `-7d`), so widen it with `filters_override` (e.g. `{"date_from": "-63d"}`).** Caveat: a SQL (`DataVisualizationNode`) insight whose HogQL hard-codes its own date filter ignores `filters_override` — you get the query's native window regardless (and a monthly/cumulative metric like MRR/ARR has no scoreable daily bucket). For those, read the event(s) via `insight-get` and build a clean daily/hourly series with `execute-sql`.
- `dashboard-insights-run` (`id`, `output_format=json`, `refresh=blocking`, `filters_override`) — runs every tile on a dashboard at once; efficient for sweeping a whole high-value dashboard. Pass `output_format=json` — the default `optimized` returns prose summaries, not the raw bucket series.
- `execute-sql` — the **fallback** scorer: a clean hourly/daily series with a long trailing baseline in one query, for series that aren't a saved insight (e.g. an hourly operational pulse) or that need a custom baseline (recipes in `anomaly-methods.md`). Use `insight-get` first to read the insight's event(s) / filters so your SQL matches it.

Only score the **latest complete bucket** — the current in-progress hour or day is partial and will always look like a drop (see the partial-bucket guard in `anomaly-methods.md`).

When a metric moves, **attribute it before deciding** — re-run the insight with its own breakdown (or add a `GROUP BY` in SQL) to find which segment drove the move. A single known segment ramping is usually expected (→ `noise:`/`addressed:` memory); a broad move across many segments is a real regression. See [`references/anomaly-methods.md`](anomaly-methods.md).

**Change-detection lens (optional).** Point/level scoring catches an outlier _bucket_; it misses a metric whose mean holds but whose **distribution shifts shape** (variance, tail, mix) and it won't tell you _where_ a drift began. For that, run a two-sample Kolmogorov-Smirnov test in `Bash` + `python3` — inline as a self-contained heredoc, or fetch the bundled `scripts/ks2.py` via `llma-skill-file-get` and write it to `/tmp` first (it is **not** on disk in a scheduled run). Compare two seasonality-matched windows, or sweep an ordered series for the changepoint. Pull **histograms** (`GROUP BY` a value bucket), not raw rows, to stay cheap and under the `execute-sql` cap. Full recipe, calibration (incl. the changepoint multiple- comparisons caveat), and the seasonality caveat in [`references/anomaly-methods.md`](anomaly-methods.md).

### Explore — discover new high-value insights/dashboards to add

Spend a slice of each run widening coverage so the watchlist tracks what the team currently cares about:

- `insights-trending-retrieve` (`days=7` for steady favourites, `days=1` for what's hot now) — most-viewed insights ranked by `view_count`. High view count = humans care = worth watching. Add the strongest not-yet-watched ones.
- `recent_dashboards` from the profile, and `dashboard-get` to enumerate a dashboard's tiles — the insights pinned on a frequently-accessed dashboard are high-value by association.
- `dashboards-get-all` / `insights-list` / `execute-sql` over `system.dashboards` / `system.insights` when you want to search by name, favourite, or recency.

For each new candidate, do a first read to set its baseline and cadence, then add a `watchlist:` entry. Don't add more than a few per run — let coverage grow steadily.

Explore is not only additive — **importance decays.**
Every few days (~3), re-pull the ranking and reconcile the _existing_ watchlist against it: promote newly-hot items, and retire ones whose dashboards have gone cold.
**Retiring is a delete, not a demote** — leave a one-line `retired:` tombstone, then `scout-scratchpad-forget` the item's `watchlist:` and `baseline:` entries, so the ledger holds only what you still score.
Retire on evidence a metric went cold, never to make a refresh look productive, and never an item whose report is still live — the reference has the guard list.
A large or "mature" watchlist is **not** a reason to skip explore — a frozen watchlist tracks last week's priorities, not today's.
The refresh cadence, the terminal-state convention, and the `importance-refresh` memo are in [`references/watchlist-and-memory.md`](watchlist-and-memory.md).

### Save memory as you go

Memory is continuous, not a final step. Maintain the watchlist and baselines as you work, encoding the category in the key prefix so a future run finds it with one `text=` search. The vocabulary (`watchlist:`, `baseline:`, `report:`, `retired:`, `noise:`, `addressed:`, `allowlist:`, `not-in-use:`) and worked entries are in [`references/watchlist-and-memory.md`](watchlist-and-memory.md). The short version:

- `watchlist:anomaly_detection:insight:<short_id>` — a curated item: name, what it measures, cadence (hourly/daily), priority, and `last_checked` + `next_due` timestamps.
- `baseline:anomaly_detection:insight:<short_id>` — the learned normal (median + MAD per seasonal bucket) so the next run scores cheaply instead of recomputing from scratch.
- `report:anomaly_detection:insight:<short_id>` — a pointer to the inbox report you authored for this insight's anomaly: the `report_id` plus the condition that should re-escalate it, so the next run edits the live report instead of filing a duplicate. Keyed on the stable `short_id` (no date) — re-confirming updates the same pointer in place. Add a `:<series-or-direction>` suffix only when one insight carries genuinely distinct concurrent anomalies, so they don't collapse onto one report.

Then return to Decide and Close out in the skill body.
