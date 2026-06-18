# Diagnostic snapshot

Before asking clarifying questions, gather evidence directly. Most diagnostics in this skill can be
confirmed or ruled out by data — the agent has `execute-sql`, `experiment-stats`,
`feature-flags-activity-retrieve`, and `activity-log-list` and should use them. Treat user-facing
questions as a fallback for when MCP cannot answer.

Run this snapshot once and reuse the results across the dispatch table in `SKILL.md`.

## Exposure shape

Powers A1/A2, B0, C2.

```sql
-- Default exposure event ($feature_flag_called):
SELECT
  properties.$feature_flag_response AS variant,
  count() AS exposures,
  count(DISTINCT person_id) AS persons,
  count(DISTINCT distinct_id) AS distinct_ids
FROM events
WHERE event = '$feature_flag_called'
  AND properties.$feature_flag = '<flag-key>'
  AND timestamp >= '<start_date>'
GROUP BY variant
ORDER BY exposures DESC
```

**If the experiment uses a custom exposure event** (`exposure_criteria.exposure_config.event` is
set in `experiment-get`), the variant attribution lives in a different property. Adjust both the
event filter _and_ the variant projection:

```sql
-- Custom exposure event:
SELECT
  properties.`$feature/<flag-key>` AS variant,  -- note: NOT $feature_flag_response
  count() AS exposures,
  count(DISTINCT person_id) AS persons,
  count(DISTINCT distinct_id) AS distinct_ids
FROM events
WHERE event = '<custom-exposure-event>'         -- from exposure_criteria.exposure_config.event
  AND timestamp >= '<start_date>'
GROUP BY variant
ORDER BY exposures DESC
```

Reason: `$feature_flag_called` carries `$feature_flag` (the flag key being evaluated) and
`$feature_flag_response` (the variant returned). Custom exposure events don't carry those — the SDK
stamps `$feature/<flag-key>` onto subsequent events instead. Querying a custom exposure event with
`$feature_flag_response` returns zero rows even when exposure capture is working fine.

Read off:

- **Total exposures** — < ~100 means "wait" territory (B0, C2); 0 means walk B-series.
- **`$multiple` share** — non-zero brings A1/A3/A4 onto the table; > ~0.5% is visible to the eye.
- **`distinct_ids / persons`** per variant — ratio noticeably > 1 (use 1.2 as a soft cue) suggests
  identity fragmentation (A3).
- **Visible split** vs configured split — flag a real SRM only after the chi-squared check (A2);
  small-sample noise is normal under ~1,000 per variant.
- **Per-variant `last_seen` and exposure trajectory.** Aggregate exposure counts can look healthy
  while the experiment is dormant — the trajectory is where you see it. Add
  `min(timestamp) AS first_seen, max(timestamp) AS last_seen` to the snapshot SQL, and scan the
  daily `exposures.timeseries[].exposure_counts` from `experiment-results-get`. Two shapes to catch:
  - **One variant's `last_seen` is days or weeks behind the other's.** The application is still
    firing the flag for one variant but stopped for the other — typically because the code path
    serving the silent variant was removed in a refactor. Walk B-series footer.
  - **Total exposures flat for weeks or months on a `running` experiment** (both variants stopped
    accumulating). The flag-reading call is gone from the application. Confirm via
    `feature-flags-activity-retrieve`: if there are no post-launch flag edits, the flag config
    can't explain the plateau and the cause is application-side. Walk B-series footer.

**Ignore `$feature_flag_response = false` / `None` / `null` rows.** `$feature_flag_called` fires on
every flag evaluation, including ones that didn't bucket the user into the experiment — flag returned
`false` (user didn't match release conditions), evaluation failed, or the SDK didn't stamp the
response. PostHog's experiment query filters these out via `in(properties.$feature_flag_response,
['<variant1>', '<variant2>', …])`. They can be larger than the real variants combined and they're
not bias signals; don't pull them into the variant-balance discussion. The exception is when _every_
exposure is `None`/`false` — that's a B-series symptom, not an A-series one.

## Recent flag mutations

Powers A6, E7; E5 lives on the experiment, not the flag.

If the user reports a _surprising change_ (variant ratio flipped, distribution off after an edit, flag
distribution went 0/100 unexpectedly), pull recent activity _before_ diagnosing further. A8
(`distinct_id` strategy change) is a code-side change and does _not_ show up here — diagnose it from
event-side identity signals, not the activity log.

- **`feature-flags-activity-retrieve { id: <feature_flag_id> }`** — recent flag edits and their diffs.
  Most "why did the numbers change?" surprises trace back to a variant-distribution change visible here.
- **`activity-log-list { scope: "Experiment", item_id: <experiment_id> }`** — experiment-level edits as
  a timeline (the response currently doesn't carry a change diff, so use it for _who/when_, not
  _what_).

## Handing off the snapshot

If the snapshot already disproves a diagnostic, skip it; if it confirms one, lead the response with
the evidence ("the data shows X → that's diagnostic Y").
