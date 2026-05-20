# Empty experiment / 0 exposures / "not enough data"

Diagnose by walking the chain:
SDK call → exposure event captured → ingested → matches the configured exposure criteria → counted.

## Contents

- Quick triage decision tree
- B0 — Fresh-launch check (experiment less than ~15 minutes old)
- B1 — Wrong flag-evaluation method (no exposure recorded)
- B2 — `identify()` timing
- B3 — `$feature_flag_called` deduplication per identity
- B4 — Custom exposure event missing variant property
- B5 — Required properties on `$feature_flag_called`
- B6 — Ad-blockers / network drops
- B7 — Test-account filter hides the data
- B8 — Metric events firing before exposure
- B9 — Eligibility check ordered after the flag check
- B10 — "Variant always undefined / false"
- B11 — Some server-side SDKs don't auto-populate `$feature/<key>` on subsequent events
- If none of the above: the code path may not be running

## Quick triage decision tree

Ask the user (or check directly) in this order:

1. **How long ago was the experiment launched?** If less than ~15 minutes → see B0 first; this
   shape often self-resolves and isn't a real setup issue.
2. **Has the code that calls the flag been deployed and is traffic flowing through it?**
   If no → the experiment will be empty until that ships. Stop here.
3. **Open the Exposures tab. Is `$feature_flag_called` showing for the flag at all (any variant)?**
   - **Some events, but 0 attributed to the experiment** → criteria mismatch (B4–B9).
   - **No events at all** → SDK / capture issue (B1, B2, B6, B10).
4. **Is `$feature_flag_called` showing for some users but not others?**
   → likely B3 (returning-user dedup) or B11 (SDK doesn't re-emit on every call).

## B0 — Fresh-launch check (experiment less than ~15 minutes old) [HIGH]

Newly-launched experiments can show 0 exposures for up to ~15 minutes even when the setup is
correct. PostHog precomputes exposure data on a schedule; until the first precomputation lands,
the results view falls back to a real-time query path that may briefly read nothing.

**Verify directly.** `experiment-get` already returns `start_date`. Compute `now() - start_date` —
if under ~15 minutes, this is the most likely cause; no need to ask. If `start_date` is null the
experiment isn't actually launched (a different shape — recommend launching).

Cross-check against the Step 1.5 snapshot: if exposures > 0 for _some_ variant, B0 is ruled out and
you're looking at B1–B11. If exposures = 0 across the board on a fresh-launch experiment, wait and
force-refresh before debugging further. Most cases in this shape resolve on their own.

Pre-computation is gated behind a 12-hour minimum runtime, so the mirage is most acute on
freshly-launched experiments and shouldn't recur on experiments older than a few hours.

<!-- Source for maintainers: MIN_PRECOMPUTATION_DURATION_SECONDS in
posthog/hogql_queries/experiments/experiment_query_runner.py. Verify before citing. -->

If the experiment is older than ~15 minutes and still shows 0 exposures, walk B1–B11 below.

## B1 — Wrong flag-evaluation method (no exposure recorded) [MEDIUM]

Only the _single-flag evaluation_ methods record exposure. The "bulk" and "payload-only" methods
don't fire `$feature_flag_called` — they read from the local flag cache without notifying PostHog.

| SDK                       | Records `$feature_flag_called`                                                                                           | Does NOT record                                                                                 |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| posthog-js                | `getFeatureFlag()`, `getFeatureFlagResult()`, `isFeatureEnabled()`, framework hooks (`useFeatureFlagVariantKey()`, etc.) | `getFeatureFlagPayload()` (deprecated for this reason), `getFlags()`, `getFeatureFlagDetails()` |
| posthog-node              | `getFeatureFlag()`, `isFeatureEnabled()`                                                                                 | `getFeatureFlagPayload()`, `getAllFlags()`, `getAllFlagsAndPayloads()`                          |
| posthoganalytics (Python) | `get_feature_flag()`, `get_feature_flag_result()`, `feature_enabled()`                                                   | `get_feature_flag_payload()`, `get_all_flags()`, `get_all_flags_and_payloads()`                 |

The pattern across SDKs: **methods that ask about one specific flag fire exposure; methods that
return the whole flag bag or just a payload don't.** Other SDKs (Ruby, Go, PHP, mobile) follow the
same shape — when in doubt, check that SDK's docs.

**Verify:** ask the user which SDK method they're using to read the flag, and whether the value is
read directly or pulled from a cached bulk result.

**Fix:** switch to the single-flag method (`getFeatureFlag()` / `get_feature_flag()` / etc.). If
the user genuinely needs the bulk accessor, they must additionally fire `$feature_flag_called`
themselves with the right properties (see B5).

## B2 — `identify()` timing [LOW]

`identify()` must be called **before** the flag is evaluated. If `identify()` runs after, the exposure
attaches to the anonymous distinct_id, then the person is later identified — splitting them across two
distinct_ids and decoupling exposure from later metric events.

Common symptoms:

- Exposure events exist but don't match later events under the same person
- Variant-specific metric counts are far below exposures

**Fix:** call `identify()` before flag evaluation. Never re-`identify()` to a different distinct_id
mid-session.

## B3 — `$feature_flag_called` deduplication per identity [MEDIUM]

PostHog SDKs deduplicate `$feature_flag_called` to avoid flooding ingestion with identical exposure
events. The _scope_ of "duplicate" varies by SDK:

- **posthog-js** dedupes per identity across sessions by default. Returning users who evaluated the
  flag before the experiment launched will _not_ re-emit exposure on later visits — they look like
  they've never seen the flag. Enable `advanced_feature_flags_dedup_per_session: true` to reset the
  cache each session.
- **posthog-node / posthoganalytics (Python)** dedupe per `distinct_id` within the process
  lifetime (in-memory cache: `distinctIdHasSentFlagCalls` / `distinct_ids_feature_flags_reported`).
  The cache resets when the process restarts. On long-lived workers, a `distinct_id` will only emit
  one exposure for the lifetime of that worker.
- **Mobile SDKs (iOS / Android / React Native / Flutter)** typically dedupe per session, not across
  sessions — meaning B3's "returning user with stale dedup" shape is largely a web concern. Verify
  against the specific SDK's docs before quoting an exact policy.

**Fix:** match the dedup strategy to the user's complaint with a concrete change:

- **Web with returning users (`posthog-js`).** In the SDK init config, set
  `advanced_feature_flags_dedup_per_session: true`. The cache resets each session, so returning
  users re-emit exposure once per session and the experiment captures them.
- **Server-side long-lived workers (`posthog-node`, `posthoganalytics`).** Two paths, pick one:
  (a) restart workers more frequently so the in-memory cache flushes more often, or (b) bypass
  SDK dedup by firing a custom exposure event yourself (see B4) — the experiment can then use
  that event as its exposure criterion instead of `$feature_flag_called`. Option (b) is the
  cleaner fix when you also want the exposure to carry custom properties.
- **Mobile (iOS / Android / React Native / Flutter).** Mobile SDKs typically dedupe per session
  by default, so B3 is rarely the cause on mobile. If a mobile setup is hitting this shape,
  check the SDK's docs for its specific session/dedup config — there's no single config key
  that's consistent across all four.

## B4 — Custom exposure event missing variant property [HIGH]

If the experiment uses a custom exposure event instead of `$feature_flag_called`, the event **must
include `$feature/<flag-key>`** with the variant value (e.g. `$feature/new-checkout: 'control'`).

Without it, the experiment can't attribute exposure to a variant — events count as "exposed" but with no
variant, which means they're effectively dropped from per-variant calculations.

**Verify directly:**

```sql
SELECT
  count() AS total,
  countIf(JSONExtractString(properties, '$feature/<flag-key>') != '') AS with_variant,
  count() - countIf(JSONExtractString(properties, '$feature/<flag-key>') != '') AS missing_variant
FROM events
WHERE event = '<custom-exposure-event>'
  AND timestamp >= '<start_date>'
```

If `missing_variant` is most of `total`, B4 is the cause.

**Fix:** set the property on the event in your tracking code, or configure the SDK so it's added
automatically. (For some SDKs, only `$feature_flag_called` populates this automatically.)

**Placebo / variant-less experiments still need the property.** A "no UX impact" experiment
(common for instrumentation-only or breakdown-driven analyses) requires `$feature/<flag-key>` on
the custom exposure event just like any other experiment. PostHog uses the property for _variant
attribution_, not for product behavior — without it, exposures land in the `None`/null variant
bucket and the results page reads as empty.

## B5 — Required properties on `$feature_flag_called` [HIGH]

The event must carry:

- `$feature_flag_response` — the variant value
- `$feature_flag` — the flag key

…on every flag retrieval, even when the variant doesn't change.

**Verify directly:**

```sql
SELECT
  count() AS total,
  countIf(properties.$feature_flag_response != '' AND properties.$feature_flag != '') AS well_formed
FROM events
WHERE event = '$feature_flag_called'
  AND properties.$feature_flag = '<flag-key>'
  AND timestamp >= '<start_date>'
```

A gap between `total` and `well_formed` confirms B5.

**Fix:** if a custom or third-party path is firing the event, ensure both properties are set.

## B6 — Ad-blockers / network drops [MEDIUM]

Common cause of partial or zero data. The SDK call goes out, but the request never reaches PostHog.

**Fix:** set up a [reverse proxy](https://posthog.com/docs/advanced/proxy) so capture requests come from
the user's own domain, which ad-blockers don't block.

## B7 — Test-account filter hides the data [HIGH]

`exposure_criteria.filterTestAccounts` defaults to `true`. If the user's own traffic matches the
project's test-account filter (e.g. their email domain is in the filter), their events are excluded from
the experiment.

**Verify directly.** Pull the filter from project settings — `project-get { id: "@current" }` returns
`test_account_filters`, an array of `{ key, type, value, operator }` conditions (`type` is `event` or
`person`; `operator` is the usual filter operator set: `is_not`, `not_icontains`, `exact`, etc.). Two
ways to use it:

1. **Read the live filter back to the user.** Summarize the rows in plain language so they can
   recognize whether their own traffic matches one. Don't assume what the rows contain — they vary
   per project (common shapes: email-domain exclusions, localhost host filters, internal IP ranges,
   specific cohorts).
2. **Estimate the exclusion rate.** For each filter row, translate to HogQL and count events that
   _would be_ dropped. Example for a person-property filter:

   ```sql
   SELECT count() AS would_be_filtered
   FROM events
   WHERE event = '$feature_flag_called'
     AND properties.$feature_flag = '<flag-key>'
     AND timestamp >= '<start_date>'
     AND person.properties.<key> <operator> <value>  -- one row from test_account_filters
   ```

   If that count is most of the exposures, B7 is the cause.

**Fix:** temporarily toggle `filterTestAccounts` off to confirm. Audit and adjust the filter conditions if
needed.

## B8 — Metric events firing before exposure [HIGH]

Metric events that occur **before** a user's first exposure are ignored. Only events after exposure are
included in the calculation.

Common cause: the exposure event fires too late in the user journey. For example, if the metric event is
`signup_completed` and the exposure event is on a checkout page that the user only reaches _after_ signup,
exposures will lag the metric and the metric appears to barely register.

**Verify directly:**

```sql
WITH exposures AS (
  SELECT person_id, min(timestamp) AS first_exposure
  FROM events
  WHERE event = '$feature_flag_called'  -- or the custom exposure event
    AND properties.$feature_flag = '<flag-key>'
    AND properties.$feature_flag_response != '$multiple'
    AND timestamp >= '<start_date>'
  GROUP BY person_id
)
SELECT
  countIf(e.timestamp < x.first_exposure) AS before_exposure,
  countIf(e.timestamp >= x.first_exposure) AS after_exposure,
  countIf(x.first_exposure IS NULL) AS no_exposure
FROM events e
LEFT JOIN exposures x ON e.person_id = x.person_id
WHERE e.event = '<metric-event>'
  AND e.timestamp >= '<start_date>'
```

If `before_exposure` dominates, the exposure event is firing too late in the journey — confirmed B8.
If `no_exposure` dominates, the user isn't getting bucketed at all (back to B1/B2/B10).

**Fix:** capture exposure at the first encounter with the experimental change, not later in the flow.

## B9 — Eligibility check ordered after the flag check [MEDIUM]

Eligibility filtering should happen **before** you call the flag — otherwise unaffected users are pulled
into the analysis and the picture gets noisy. This shows up as exposures being much higher than expected
and metric rates unexpectedly low.

**Fix:** structure the code as: eligibility check → flag check → render. Not: flag check → eligibility →
render.

## B10 — "Variant always undefined / false" [MEDIUM]

Almost always one of:

- B1 (wrong evaluation method)
- B2 (`identify()` timing)
- `posthog is not defined` (SDK init order — initialize PostHog before any flag call)
- The flag is genuinely off — `feature_flag.active === false`, or rollout `0%`, or the user is outside
  release conditions

**Fix:** walk the user through their SDK setup. Verify in this order: (a) is PostHog initialized?
(b) is the flag active and rolled out? (c) is the right variant key being requested?

## B11 — Some server-side SDKs don't auto-populate `$feature/<key>` [MEDIUM]

Some server-side SDKs (notably Ruby; behavior varies across server SDKs) do not automatically add
`$feature/<flag-key>` to subsequent events after the flag is read. This means metric events have no
variant property, breakdowns can show "none", and the experiment under-counts.

**Verify directly.** Compare exposure events to a same-flag metric event under the same person, and
check whether `$feature/<flag-key>` is set on the metric event. If exposures look fine but metric
events are missing the property, this is the cause.

**Fix:** manually set `$feature/<flag-key>` on the metric events being captured server-side, or capture
the metric event from the client where the JS SDK does add it automatically.

## If none of the above: the code path may not be running

Two sub-cases:

**Never had exposures** (the experiment has shown 0 since launch). After B1–B11, check the obvious:

- Has the deploy with the flag-reading code shipped to production?
- Is real traffic flowing through that code path?
- Is the date range correct (start_date in the future, etc.)?

Ask explicitly. The "empty experiment" shape often resolves to a feature flag still on a feature
branch that hasn't merged, or a page that calls the flag not being live yet.

**Exposures were healthy then stopped** (the experiment ran for weeks/months, then the daily
exposure count plateaued and never moved again). A different shape — capture and config are
both fine; the application stopped calling the flag.

_Verify directly:_

- Read `exposures.timeseries[].exposure_counts` from `experiment-results-get`. A flat tail
  (e.g. 27,372 → 27,376 over 100 days = +4 new exposures total) is the signature, distinct from
  a fresh experiment that's still ramping or one that recently launched. Compare to the
  `last_seen` per variant from the diagnostic snapshot — both variants flat is a code-path
  removal; one variant flat while the other still fires is a one-sided refactor.
- Cross-check `feature-flags-activity-retrieve { id: <feature_flag_id> }`. If there are no
  post-launch flag edits, the flag config is unchanged and the plateau cannot be explained by
  rollout / variant / condition changes. The cause is on the application side.

_Common causes:_

- The flag-reading call was removed in a refactor (most common).
- The page or component that hosts the flag-read was deprecated or rerouted (e.g. URL
  restructuring moved the eligible traffic onto a different page that doesn't read this flag).
- A different flag is now serving the same UX (intentional migration that wasn't paired with
  ending the original experiment).

_Recommend:_

- **If the hypothesis is settled enough:** end the experiment with the appropriate conclusion
  (won / lost / inconclusive). The metric data accumulated before the plateau is the experiment's
  documented outcome. Don't ship the variant unless the code path is being restored — an "end +
  ship" on a dormant flag flips the variant distribution to a UX that isn't being served anyway.
- **If you want to keep running the hypothesis:** restore the flag-reading call in the
  application code, then either continue (and treat the pre-/post-resumption windows separately)
  or reset + relaunch for a clean comparison window.

**SDK-side fallback.** If B1, B2, and B10 are all on the table and you can't pin one down, invoke the
`posthog:diagnosing-sdk-health` skill — outdated SDKs are a frequent root cause of the "no exposures
at all" shape (missing instrumentation, broken `identify()` ordering, deprecated flag methods).
