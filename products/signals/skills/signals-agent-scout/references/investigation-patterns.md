# Investigation patterns

Common shapes the scout should recognize and how to drill in. Each pattern names the
profile signal that surfaces it, the validating queries, and the disqualifiers that
rule it out.

The project profile (`signals-agent-harness-project-profile-get`) is the entry point
for most patterns. Read it first — many of these patterns become obvious from the
profile alone.

## 1. Error burst → missing-migration / regression

**Profile signal**: `top_events.recent_24h_users` for `$exception` is much higher than
the project's normal baseline (`top_events.distinct_users` over 7d), or
`existing_inbox_reports` shows fresh `$exception`-related reports.

**Drill in**:

1. `error-tracking-issues-list` filtered to `status=active` and seen in last 24h.
2. For top-volume issues, get the hourly breakdown via `execute-sql` against
   `events` filtered to `event = '$exception'` and `properties.$exception_issue_id =
'<id>'`, grouped by `toStartOfHour(timestamp)`.
3. Look for the **one-occurrence-per-distinct-user** shape. If `count(*) ≈
uniq(person_id)`, it's a per-request server path, not a stray exception.
4. Check `read-data-schema event_property_values` for `$exception_type` to identify
   migration / undefined-table errors specifically.

**Disqualifiers**:

- High count + low distinct_users → power-user loop or a single misbehaving session.
- Burst confined to dev/internal — see noise patterns in
  [dedupe-rules.md](dedupe-rules.md).

**Worked example**: see the access-control finding in
[finding-schema.md](finding-schema.md).

## 2. Experiment regression — primary metric drop

**Profile signal**: a recently-launched experiment in `popular_insights` (the experiment
results dashboard would surface here) or `recent_dashboards` — and the team's recent
runs haven't touched it yet.

**Drill in**:

1. `experiment-list` to find experiments with `status=running` and recent `start_date`.
2. For each candidate, `experiment-get` to read the primary metric definition and
   variants.
3. `query-trends` or `query-funnel` mirroring the primary metric, broken down by
   `feature/experiment_variant` over the experiment window. Compare control vs
   treatment(s).
4. If treatment is materially worse (e.g. >5% relative drop on primary metric with
   sufficient sample), validate by checking the same trend pre-experiment to rule out
   secular drift.

**Disqualifiers**:

- Sample sizes too small to be material (look at `count` in trend results).
- Drop is in a non-primary metric — note it in the description but weight modestly.
- Drop predates the experiment — secular trend, not the experiment's fault.

## 3. Warehouse stalls → pipeline freshness

**Profile signal**: `external_data_sources` entries with `status` other than
`Completed`, or `last_synced_at` significantly older than `sync_frequency` would predict.

**Drill in**:

1. The profile already surfaces source-level state. For each suspect source,
   `external-data-schemas-list` to see per-table sync state.
2. `external-data-sync-logs-list` for the affected schema to see the failure messages
   from recent attempts.
3. Check whether downstream insights / dashboards depend on the stale data —
   `popular_insights` may show what's affected.

**Disqualifiers**:

- The sync is an irregular cadence (e.g. weekly) and "old" is expected.
- Source is `paused` deliberately (check activity log).

## 4. Feature-flag rollout → key-event regression

**Profile signal**: `signal_source_configs` enabled for feature flags + a recent
flag activation in activity log + a top event whose `recent_24h_users` shows a step
change.

**Drill in**:

1. `feature-flag-get-all` filtered to `active=true`. Sort by recent change time.
2. For each flag with recent variant changes, identify the user-facing key events the
   flag should affect (login, checkout, etc.).
3. `query-trends` for those events, broken down by `$feature/<flag_key>`. Compare
   exposed-true vs exposed-false populations.
4. If the variant-true population shows a regression on a key event vs
   variant-false, that's the signal.

**Disqualifiers**:

- The exposed-true population is too small for the trend to be material.
- The breakdown shows the flag isn't actually fanning out to users yet (rollout
  percentage low, or targeting still tightening).

## 5. Traffic anomaly → upstream root cause

**Profile signal**: `top_events.recent_24h_count / count` ratio is significantly lower
than `1/7` for events that should have steady volume (e.g. `$pageview`,
`$autocapture`). Or the ratio is much higher than `1/7` (a sudden spike).

**Drill in**:

1. `query-trends` with `event=$pageview` and a 7-day window to confirm the anomaly.
2. Break down by `$host`, `$current_url`, or `$lib` — narrow which property changed.
3. Check `activity-log-list` for recent deploys, integration changes, or capture
   config changes correlating with the inflection point.
4. Check session-replay sampling rates and feature-flag toggles that gate capture —
   sometimes the anomaly is a capture-side change, not a real traffic change.

**Disqualifiers**:

- The anomaly aligns with a known holiday / weekend / seasonal effect.
- A single bot/scraper user-agent dominates the spike — see noise patterns.

## 6. Popular-insight regression — the dashboard goes red

**Profile signal**: an entry in `popular_insights` (frequently-viewed by humans means
they care) whose underlying metric has regressed in last 7d vs prior period.

**Drill in**:

1. `insight-get` on the `short_id` from the profile to read the saved query.
2. Re-run the underlying query (or its `query-trends` / `query-funnel` equivalent)
   with `compare_to_previous` to quantify the change.
3. If the metric is filtered (cohort, breakdown, property), check whether the filter's
   population changed (cohort growth, property-value redistribution).

**Disqualifiers**:

- The insight is saved but stale (no recent `last_modified_at`) — humans may not still
  care about it; weight modestly.
- The regression is a known seasonal pattern.

## 7. Cross-source convergence — multi-evidence finding

**Profile signal**: any individual signal is too weak to emit on alone, but two or
more independent sources point at the same root cause.

**Drill in**:

1. Map the candidates: which sources are independently flagging which entities?
2. Look for shared time windows — fresh error issues + fresh dashboard regressions +
   fresh experiment exposures all in the same hour are a stronger signal than any one.
3. Build the description prose around the convergence: "X errors started 11:31, the
   experiment exposed 23K users in the same window, the checkout dashboard shows a
   12% drop in completion since 11:31."

This is where the agent earns its keep — the existing push pipeline can't synthesize
across sources at emit time. Cross-source convergence is the highest-value pattern this
scout produces.

## When the profile is genuinely quiet

If after orientation you can't find a concrete thread to investigate:

- Don't manufacture findings to fill space. Return an empty `findings` list.
- Write a memory entry summarizing what you looked at and saw nothing of note —
  next run reads it and saves cycles.
- Close out with a one-paragraph summary: what you scanned, what was below threshold,
  why you stopped.

A quiet run is a real outcome. The scout's value compounds across runs; one quiet
run today doesn't reduce the value of catching tomorrow's burst.
