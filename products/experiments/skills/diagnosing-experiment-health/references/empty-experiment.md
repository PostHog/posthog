# Empty experiment / 0 exposures / "not enough data"

Diagnose by walking the chain:
SDK call → exposure event captured → ingested → matches the configured exposure criteria → counted.

**Which exposure event?** When `exposure_criteria` names no custom event, the experiment counts exposures on its default event.
Read it from `resolved_exposure_event` in `experiment-get`: `$feature_flag_called`, or `$experiment_exposure` for an experiment that started on or after 2026-09-01 (UTC) in a project that is in the rollout of that event.
An `exposure_criteria.exposure_config` that names `$experiment_exposure` counts that event, whatever `resolved_exposure_event` says.
A config that names `$feature_flag_called` counts the default event, as an absent config does.
`$experiment_exposure` is a copy of `$feature_flag_called`, written at ingestion with the same properties, and only for a string response other than `true`, `false` and the empty value.
So the SDK-side diagnostics below apply to both: an SDK that never fires `$feature_flag_called` produces neither event.
The reverse case, `$feature_flag_called` with variant responses and no `$experiment_exposure`, is not an SDK fault ("Which event, which property" in `diagnostic-snapshot.md`).

**What counts as an exposure.** An event counts only when all of these hold:

- it is the experiment's exposure event, inside the experiment's window;
- its variant property holds one of the flag's current variant keys (`$feature_flag_response` on a default event, `$feature/<flag-key>` on a custom event), and that key is not in `excluded_variants`;
- on a group-aggregated flag, it carries the key of that group type;
- with an activation event (`exposure_criteria.activation_config`), the person also sent that event at or after their first flag exposure, and counts from then;
- it passes the test-account filter and every filter of the exposure criteria.

An event that fails one of them is not counted at all.
There is no "no variant" bucket.
A launched experiment without a counted exposure shows a total of 0 and a flat chart, and its open Exposures panel says "No exposures yet".
The panel says the same for a draft, for a start date after today, and for an exposure query that failed.

The queries this file refers to are in `diagnostic-snapshot.md`, with their rules.

## Contents

- Quick triage decision tree
- B0 — Fresh-launch check (launched minutes or hours ago)
- B1 — Wrong flag-evaluation method (no exposure recorded)
- B2 — `identify()` timing and ids that are never linked
- B3 — `$feature_flag_called` deduplication per identity
- B4 — Custom exposure event missing variant property
- B5 — Required properties on `$feature_flag_called`
- B6 — Ad-blockers / network drops
- B7 — Test-account filter hides the data
- B8 — Metric events firing before exposure
- B9 — Eligibility check ordered after the flag check
- B10 — "Variant always undefined / false"
- B11 — `$feature/<key>` is missing on metric events
- B12 — An exposure criteria filter that cannot match
- If none of the above: the code path may not be running

## Quick triage decision tree

The tree is for an experiment that counts 0 exposures, or 0 in one variant.
For exposures that grew and then stopped, go to the closing section.
For exposures without conversions, go to B2, B8 and B11, then to D11 in `numbers-vs-sql.md`.

Check directly, in this order, and ask only what the tools cannot answer:

1. **How long ago was the experiment launched?** `start_date` from `experiment-get`.
   Null means it is a draft. Minutes or a few hours → B0 first.
2. **Has the code that calls the flag been deployed and is traffic flowing through it?**
   If no → the experiment will be empty until that ships. Stop here.
3. **What did the application send?** Run the raw-responses query for the flag.
   - **Events with a variant response, and the experiment still counts 0** → the criteria remove them (B4, B7, B12), the variant is in `excluded_variants`, the flag is aggregated by a group and the events carry no group key, an activation event is set and nobody sent it after the flag call, or the 0 is a result computed before the events arrived (`last_refresh`, B0).
   - **Events whose response is no variant** (`false`, empty) → B10, and A10 in `bias-and-skew.md` when only a part is affected.
     On a custom exposure event, values of `$feature/<flag-key>` that are empty or no variant key → B4.
   - **One variant has events and another has none** → a variant at 0% or a pinned variant (A7b in `bias-and-skew.md`, E3 in `mid-run-changes.md`), or code that serves one arm only (closing section).
   - **No events at all** → SDK or capture (B1, B6), a read before the SDK has loaded the flags (B10), events sent without the flag's key (B5), or the code calls another flag key (closing section).
     When the experiment counts `$experiment_exposure` (`resolved_exposure_event`, or an `exposure_config` that names it), run the query on `$feature_flag_called` too before you conclude that nothing is sent.
4. **Are some people exposed and others not?**
   → B3 (returning users who do not send the event again), a read before the SDK has loaded the flags that the code does not repeat (B10: visitors without flags from an earlier visit send nothing), or A10 in `bias-and-skew.md`.

## B0 — Fresh-launch check (launched minutes or hours ago) [MEDIUM]

**Evidence.** `start_date` from `experiment-get`, against the current time.

- `start_date` is null: the experiment is not launched. Recommend launching.
- Exposures above 0 for any variant: B0 is ruled out.

**What a fresh experiment shows** `[HIGH]`.

- For its first 12 hours an experiment reads exposures directly from events, and the page forces one fresh read on each load while the experiment has fewer than 50 exposures in total.
  So a correctly wired experiment shows its first exposures on the page within minutes of the first flag call. The delay is ingestion.
  `experiment-results-get` is different: it can return a result up to 24 hours old, so a 0 that it read earlier can outlast the first exposures (`last_refresh` on the result says how old it is).
- A variant with fewer than 50 exposures has no result yet: the metric reads "Not enough data yet".
  That is the floor, not a fault (C2 in `interpretation.md`).
- Stored results may not exist yet for a fresh experiment.
  A read of the stored results that returns nothing in the first hours is expected.
  The scheduled calculation skips an experiment younger than 12 hours or with fewer than 50 exposures in total, so an empty experiment has stored results only when a calculation was started another way, for example from the experiment page.
- In a project with precomputed exposures, an experiment older than 12 hours can lag today's new exposures by up to 15 minutes.
  The total is 0 because of that only when every exposure is younger than 15 minutes.

<!-- Source for maintainers (may rot): MIN_PRECOMPUTATION_DURATION_SECONDS, DEFAULT_EXPOSURE_TTL_SECONDS and
ExperimentResultsCacheMixin in products/experiments/backend/hogql_queries/experiment_query_runner.py; validate_variant_result in
products/experiments/backend/hogql_queries/utils.py (the per-variant floor); NEW_EXPERIMENT_FORCE_REFRESH_AFTER_MINUTES and
EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS in products/experiments/frontend/constants.ts (the forced page read); MIN_EXPERIMENT_AGE and
MIN_TOTAL_EXPOSURES in products/experiments/backend/temporal/scheduled_recalculation_logic.py. Verify before citing. -->

**Reading.** Zero exposures minutes after launch, on a surface with little traffic, is waiting.
Zero exposures an hour after launch, on a surface that people visit, is a real B-series case: walk B1 to B12.

## B1 — Wrong flag-evaluation method (no exposure recorded) [MEDIUM]

Only a read of _one flag's value_ records exposure. A read of all flags, of a payload, or of the
values a callback hands over does not fire `$feature_flag_called`.

| SDK                       | Records `$feature_flag_called`                                                                                                                                           | Does NOT record                                                                                                                                                                                                 |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| posthog-js                | `getFeatureFlag()`, `getFeatureFlagResult()`, `isFeatureEnabled()`, the React hooks `useFeatureFlagVariantKey()`, `useFeatureFlagEnabled()` and `useFeatureFlagResult()` | `getFeatureFlagPayload()` (deprecated for this reason), `getFlags()`, `getFeatureFlagDetails()`, the values passed to `onFeatureFlags`, the React hooks `useFeatureFlagPayload()` and `useActiveFeatureFlags()` |
| posthog-node              | `evaluateFlags()` then `getFlag()` or `isEnabled()` on the result. Older: `getFeatureFlag()`, `getFeatureFlagResult()`, `isFeatureEnabled()`                             | `getFlagPayload()` on the result, `getFeatureFlagPayload()`, `getAllFlags()`, `getAllFlagsAndPayloads()`                                                                                                        |
| posthoganalytics (Python) | `evaluate_flags()` then `get_flag()` or `is_enabled()` on the result. Older: `get_feature_flag()`, `get_feature_flag_result()`, `feature_enabled()`                      | `get_feature_flag_payload()`, `get_all_flags()`, `get_all_flags_and_payloads()`                                                                                                                                 |

The pattern across SDKs: **methods that ask about one specific flag fire exposure; methods that
return the whole flag bag or just a payload don't.** Other SDKs (Ruby, Go, PHP, mobile) follow the
same shape — when in doubt, check that SDK's docs.

An option can switch the event off for a call that would send it: `send_event: false` in posthog-js, `sendFeatureFlagEvents: false` in posthog-node, `send_feature_flag_events=False` in Python.

**Verify:** the raw-responses query shows no events for the flag while the surface has traffic.
Then ask which SDK method reads the flag, and whether the value is
read directly or pulled from a cached bulk result.

**Fix:** switch to the single-flag read. If
the user genuinely needs the bulk accessor, they must additionally fire `$feature_flag_called`
themselves with the right properties (see B5).

## B2 — `identify()` timing and ids that are never linked [LOW]

The experiment joins a person's metric events to that person's exposure.
Two shapes break the join or the assignment:

- **`identify()` runs after the flag is evaluated.**
  The exposure is sent under the anonymous id.
  Once the two ids are linked, exposure and later events belong to one person, and the metric counts.
  The exception is a project that keeps each event's person id as it was written: there a merge of two persons that both existed does not move the exposure sent before it.
  The risk is a second evaluation under the identified id that lands in another variant (A3 in `bias-and-skew.md`).
- **The ids are never linked.**
  The exposure is sent under one id and the metric events under another that PostHog never joins to it: a second pipeline (a customer data platform, a backend) that sends events under its own anonymous id, or anonymous events sent without a person profile in a project that keeps each event's person id as it was written.
  The experiment then shows exposures and almost no conversions.

**Evidence.** Take one person who converted.
Compare the `distinct_id` of the exposure event with the `distinct_id` of the metric event, and check whether both belong to one person.
When the ids are never linked, the person who converted has no exposure event at all.
Then compare `properties.$lib` and the form of `distinct_id` on that person's metric events with those on the exposure events: another library or another form of id points to a second pipeline.

Common symptoms:

- Exposure events exist but don't match later events under the same person
- Variant-specific metric counts are far below exposures

**Fix:** call `identify()` before flag evaluation. Never re-`identify()` to a different distinct_id
mid-session.
Give every pipeline that sends events for one visitor the same id from the first event on.

## B3 — `$feature_flag_called` deduplication per identity [MEDIUM]

PostHog SDKs deduplicate `$feature_flag_called` to avoid flooding ingestion with identical exposure
events. The _scope_ of "duplicate" varies by SDK:

- **posthog-js** dedupes per identity across sessions by default. Returning users who evaluated the
  flag before the experiment launched will _not_ re-emit exposure on later visits — they look like
  they've never seen the flag. Enable `advanced_feature_flags_dedup_per_session: true` to reset the
  cache each session.
  The key is the flag together with its response, so a person whose response changes sends a new event.
- **posthog-node / posthoganalytics (Python)** dedupe per distinct id, flag, response and groups within the process
  lifetime, in memory. The cache is emptied when the process restarts.
  At 50,000 distinct ids posthog-node empties it (the `maxCacheSize` option sets the limit), while Python drops only the oldest distinct id for each new one.
- **Mobile SDKs (iOS / Android / React Native / Flutter)** dedupe per session, not across
  sessions — the "returning user with stale dedup" shape is a web concern.

**Where it bites: a flag that people evaluated before the experiment started.**

- The flag was active before launch.
- The flag key is reused from an earlier experiment or an earlier run.
  The same key also gives every person the same draw as before.
- The experiment was reset and relaunched on the same flag.

Returning people already sent the event with the same response, so they send nothing after launch and are missing from the experiment.

**Evidence.** The flag's history in `experiment-activity`: was the flag active before `start_date`?
The history holds this flag's own changes, and only when the user can view the flag.
It does not list other experiments that used the flag, nor a deleted flag with the same key: ask the user whether the key was used before.
First-time visitors are exposed and returning visitors are not.

**Fix:** match the dedup strategy to the user's complaint with a concrete change:

- **Web with returning users (`posthog-js`).** In the SDK init config, set
  `advanced_feature_flags_dedup_per_session: true`. The cache resets each session, so returning
  users re-emit exposure once per session and the experiment captures them.
- **A new run:** a new flag key (E15 in `mid-run-changes.md`).
- **Server-side long-lived workers (`posthog-node`, `posthoganalytics`).** Two paths, pick one:
  (a) restart workers more frequently so the in-memory cache flushes more often, or (b) bypass
  SDK dedup by firing a custom exposure event yourself (see B4) — the experiment can then use
  that event as its exposure criterion instead of `$feature_flag_called`. Option (b) is the
  cleaner fix when you also want the exposure to carry custom properties.

Repeated exposure events with the same variant are harmless: the experiment counts each person once, at the first exposure.
A person whose exposure events carry two variants is `$multiple`, and under the default `multiple_variant_handling` (`exclude`) leaves the analysis (A3 in `bias-and-skew.md`).

## B4 — Custom exposure event missing variant property [HIGH]

If the experiment uses a custom exposure event instead of the default one, the event **must
include `$feature/<flag-key>`** with the variant value (e.g. `$feature/new-checkout: 'control'`).

Without it the event is not an exposure.
The same holds for a value that is not exactly one of the flag's variant keys: another spelling, another case, `true`, a key of another flag.

**Evidence.** The custom-exposure query of the snapshot lists the values of the property with their counts.
Compare them with `feature_flag.filters.multivariate.variants[].key`:

- every row empty → the sender does not set the property;
- values that differ from the variant keys → the sender sets another value.

**Fix:** set the property on the event in the tracking code.
posthog-js adds it to every event once flags have loaded, except while its flag cache is older than `feature_flag_cache_ttl_ms` when that option is set `[MEDIUM]`.
An event that arrives another way carries it only when the sender adds it: a server SDK adds it only when the capture call is given the evaluated flags (`flags`) or asked to evaluate them (`sendFeatureFlags: true` in posthog-node, `send_feature_flags=True` in Python), and a customer data platform or a hand-written event never adds it `[MEDIUM]`.

**Placebo / variant-less experiments still need the property.** A "no UX impact" experiment
(common for instrumentation-only or breakdown-driven analyses) requires `$feature/<flag-key>` on
the custom exposure event just like any other experiment. PostHog uses the property for _variant
attribution_, not for product behavior.

## B5 — Required properties on `$feature_flag_called` [HIGH]

An exposure event that the user's own code sends (a bulk accessor plus a hand-written event, a third-party path) must carry:

- `$feature_flag` — the experiment's flag key
- `$feature_flag_response` — one of the flag's variant keys

One such event per person is enough: the experiment takes each person's first exposure.

**Evidence.** The raw-responses query of the snapshot.
No rows for the flag key means the events carry another key or none, or that no event is sent at all (B1).
The same query without the `$feature_flag` condition, grouped by `properties.$feature_flag`, shows which keys the events carry: one day only, since it reads every flag of the project.
Rows whose response is no variant key are not counted.

**Fix:** set both properties on the event.

## B6 — Ad-blockers / network drops [MEDIUM]

Common cause of partial or zero data. The SDK call goes out, but the request never reaches PostHog.

A consent step has the same effect `[LOW]`: nothing is captured before the visitor opts in, and when flags load only after consent, every read before it returns no variant.
With posthog-js opted out by default (`opt_out_capturing_by_default: true`) and persistence left on, a read before opt-in returns the variant and records the exposure as sent, while the event itself is dropped.
After opt-in the same read sends nothing until the distinct id changes, so that person is never exposed unless `advanced_feature_flags_dedup_per_session` is on (B3) `[MEDIUM]`.

**Fix:** set up a [reverse proxy](https://posthog.com/docs/advanced/proxy) so capture requests come from
the user's own domain, which ad-blockers don't block.

## B7 — Test-account filter hides the data [HIGH]

`exposure_criteria.filterTestAccounts` defaults to `true`. If the user's own traffic matches the
project's test-account filter (e.g. their email domain is in the filter), their events are excluded from
the experiment.
When a rule of the project's filter is inverted, so that it keeps what it was meant to remove, every production event is dropped.

**Evidence.**

- **The filter.** `project-get` without an id returns the active project's `test_account_filters`: an array of `{ key, type, value, operator }` conditions, with `type` usually `person`, `event` or `cohort`, and sometimes `group` or `element`.
  An event is kept only when it matches **every** row.
  Rows are normally negative (`is_not`, `not_icontains`, and `not_in` on the cohort row a new project starts with): a positive row (`exact`, `icontains`, `in`) keeps only what it names, so check whether that is intended.
- **The effect.** Compare the people in the raw-responses query (no filter) with `exposures.total_exposures` (filtered) over the same window.
  People in the raw events and none in the experiment, with exposure criteria that hold nothing else, points to this cause.
  The other causes in the same branch of the triage tree give the same picture, so confirm it: add the rows to the raw-responses query one at a time (`properties.<key>` for an event row, `person.properties.<key>` for a person row, `person_id IN COHORT <id>` for a cohort row), and the row after which the count falls to zero, or nearly, is the cause.
- Summarize the rows in plain language so the user can recognize their own traffic.
  Don't assume what the rows contain — they vary per project (common shapes: email-domain exclusions, localhost host filters, internal IP ranges, specific cohorts).

**Fix:** turn `filterTestAccounts` off for this experiment, or correct the project's filter.
Both change which exposures count for the whole run (E5 in `mid-run-changes.md`).

## B8 — Metric events firing before exposure [HIGH]

Metric events that occur **before** a user's first exposure are ignored. Only events after exposure are
included in the calculation.

Common cause: the exposure event fires too late in the user journey. For example, if the metric event is
`signup_completed` and the exposure event is on a checkout page that the user only reaches _after_ signup,
exposures will lag the metric and the metric appears to barely register.

**Verify directly.** One scan over both events, for the people who sent the metric event in the window:

```sql
SELECT
    countIf(exposure_events = 0) AS persons_with_metric_and_no_exposure,
    countIf(exposure_events > 0 AND last_metric < first_exposure) AS persons_with_every_metric_event_before_exposure,
    countIf(exposure_events > 0 AND last_metric >= first_exposure) AS persons_with_a_metric_event_after_exposure
FROM (
    SELECT
        person_id,
        countIf(event = '<resolved_exposure_event>') AS exposure_events,
        minIf(timestamp, event = '<resolved_exposure_event>') AS first_exposure,
        maxIf(timestamp, event = '<metric-event>') AS last_metric
    FROM events
    WHERE timestamp >= toDateTime('<window_start>', 'UTC')
      AND timestamp < toDateTime('<window_end>', 'UTC')
      AND (
          event = '<metric-event>'
          OR (
              event = '<resolved_exposure_event>'
              AND properties.$feature_flag = '<flag-key>'
              AND properties.$feature_flag_response IN ('<variant-key-1>', '<variant-key-2>')
          )
      )
    GROUP BY person_id
    HAVING countIf(event = '<metric-event>') > 0
)
```

On a custom exposure event, put that event in place of `<resolved_exposure_event>`, drop the `$feature_flag` condition, and test `` properties.`$feature/<flag-key>` `` in place of `$feature_flag_response`.

If the second count dominates, the exposure event is firing too late in the journey — confirmed B8.
The first count also holds every person outside the experiment: with a rollout under 100%, release conditions, or a metric event that also fires on other surfaces, it is large by design.
If it dominates beyond that, the people who convert are not being exposed at all (back to B1, B2, B10), or they were exposed before the window.

**Fix:** capture exposure at the first encounter with the experimental change, not later in the flow.
An exposure placed late can also differ between the arms (A9 in `bias-and-skew.md`).

## B9 — Eligibility check ordered after the flag check [MEDIUM]

Eligibility filtering should happen **before** you call the flag — otherwise unaffected users are pulled
into the analysis and the picture gets noisy. This shows up as exposures being much higher than expected
and metric rates unexpectedly low.

The same shape has other sources: a flag that is read on more surfaces than the one under test, and an experiment on new users whose flag existing users also evaluate.
In each, the experiment counts people the decision is not about (D12 in `numbers-vs-sql.md`).

**Fix:** structure the code as: eligibility check → flag check → render. Not: flag check → eligibility →
render.
Where the code cannot change, narrow who counts: a filter in the exposure criteria, which removes a person only when every exposure event of that person fails it (B12 lists what such a filter can read), or a custom exposure event sent at the point of the change.

## B10 — "Variant always undefined / false" [MEDIUM]

Almost always one of:

- B1 (wrong evaluation method), when the code reads a payload: `getFeatureFlagPayload()` returns the payload, which is empty for a flag without one
- B2 (`identify()` timing), on a flag whose release conditions read person properties that are set at `identify()`: a read before it gets no variant
- `posthog is not defined` (SDK init order — initialize PostHog before any flag call)
- The code reads the flag before the SDK has loaded the flags.
  posthog-js then returns `undefined` and sends no `$feature_flag_called`, unless the browser holds flags from an earlier visit
- The flag is genuinely off — `feature_flag.active === false` (`status` is `paused`), or rollout `0%`, or the user is outside
  release conditions
- The flag buckets on the device id, and the call carries none (A10 in `bias-and-skew.md`)
- The code reads the multivariate flag as a boolean and gets `true`, or replaces "no variant" with a default of its own

**Fix:** walk the user through their SDK setup. Verify in this order: (a) is PostHog initialized?
(b) is the flag active and rolled out? (c) is the right variant key being requested?

When only a part of the audience gets no variant, the question is who: A10 in `bias-and-skew.md`.

## B11 — `$feature/<key>` is missing on metric events [HIGH]

**For a current experiment this is not a fault.**
Only the exposure event decides a person's variant.
Metric events are matched to that person and need no flag property, for every metric type.
A user who adds `$feature/<flag-key>` to metric events changes nothing in the results.

Where the property does matter:

- **Legacy experiments** (E13 in `mid-run-changes.md`) attribute metric events by `$feature/<flag-key>`, so events without it are not counted there.
- **A custom exposure event** needs it (B4).
- **The user's own insight or SQL** that filters or breaks down by `$feature/<flag-key>`.
  It undercounts events from a server SDK, which adds the property only when the capture call is given the evaluated flags or asked to evaluate them `[MEDIUM]`.
  It also overcounts in the other direction: the property is on events of everyone whose SDK holds the flag's value, including people who were never exposed, so it is not a filter for participants.

**Verify directly.** `is_legacy` in `experiment-get`.
It is true when any primary, secondary or shared metric is legacy, and only a metric whose `kind` is `ExperimentTrendsQuery` or `ExperimentFunnelsQuery` attributes metric events by the property.
When it is false, or the metric in question has another `kind`, look elsewhere for a missing conversion: B2 (ids), B8 (order), D1 in `numbers-vs-sql.md` (scope).

Part of the public docs still asks for the property on metric events.
The exposures page states the current rule.

<!-- Source for maintainers (may rot): build_variant_property in
products/experiments/backend/hogql_queries/experiment_exposure_query_builder.py reads the property on the exposure side only;
the legacy runners experiment_trends_query_runner.py and experiment_funnels_query_runner.py break down metric events by it.
Docs: https://posthog.com/docs/experiments/exposures#metric-events-dont-need-a-variant-property -->

## B12 — An exposure criteria filter that cannot match [MEDIUM]

**Symptom (in the user's vocabulary):** "exposures dropped to zero after I added a filter", "the experiment shows far fewer users than the flag", "I copied the experiment and the new one is empty".

**Behavior.** A filter in the exposure criteria is evaluated on each exposure event.
It reads the event's own properties, and person properties either as they were attached to that event or as the person holds them now: which of the two depends on a project setting that the tools do not show.
A filter that names something the exposure event cannot carry removes every exposure, and nothing reports it.

Shapes:

- **A property the exposure event does not have.**
  A browser property (device type, URL) on an exposure that a server sends.
- **A person property that is set after the exposure,** such as a sign-up timestamp on an exposure that happens before sign-up.
  This shape occurs only where person properties are read as they were attached to the event.
- **A misspelled property name or value.**
- **Criteria copied from another experiment** that name the other experiment's flag or event.
- **An exposure event the project has never received.**
- **A URL filter, or another event-property filter, that is meant to keep people out.**
  It drops the events that do not match. A person with one matching exposure event is in, with everything they did.

**Evidence to gather.**

- `exposure_criteria.exposure_config` from `experiment-get`: the event and its `properties`.
- The raw-responses query once without and once with the filter's condition.
  A count that falls to zero, or nearly, names the filter.
  One condition at a time when there are several.
- For a person-property filter: the raw-responses query with the same condition on `person.properties.<key>`.
  That query reads person properties the same way the experiment does, so the check holds whichever way the project reads them.

**Co-occurs with:** B7, and D9 in `numbers-vs-sql.md`.

**Recommendation.** Remove or correct the filter.
Filter on what the exposure event carries.
To restrict the experiment to a group of people, use the flag's release conditions.
An edit of the exposure criteria recomputes the whole run (E5 in `mid-run-changes.md`).

## If none of the above: the code path may not be running

Two sub-cases:

**Never had exposures** (the experiment has shown 0 since launch). After B1–B12, check the obvious:

- Has the deploy with the flag-reading code shipped to production?
- Is real traffic flowing through that code path?
- Does the code read the experiment's flag key, and not another key?
- Is the date range correct (start_date in the future, etc.)?

Ask explicitly. The "empty experiment" shape often resolves to a feature flag still on a feature
branch that hasn't merged, or a page that calls the flag not being live yet.

**Exposures were healthy then stopped** (the experiment ran for weeks/months, then the
exposure count plateaued and never moved again). Before investigating, check the experiment's
status from Step 1:

- `exposure_frozen` — someone froze exposure. The plateau is the intended behavior: enrollment is closed, metrics still flow (E16 in `mid-run-changes.md`).
- `paused` — the flag is off.
- `stopped` — the results end at the end date.

Then check where the project keeps its flag calls: `project-get` returns `flag_evaluations_mode`.
At 2, `$feature_flag_called` no longer arrives in `events` for the projects that setting covers, and an experiment that counts that event gains no exposures, without a warning.
That is no fault of the SDK or of the application: say so, and point the user to PostHog support.

Then read the flag's change history, before any conclusion about the application:

- **A change of the flag after launch can explain the plateau by itself.**
  A split edited to 0% for one variant, a variant pinned on a broad release condition, or a rollout cut to 0 stops one arm or all of them while `status` still reads `running` (A5, A6 and A7b in `bias-and-skew.md`, E3 in `mid-run-changes.md`).
- **No change of the flag after launch** means that an edit of the rollout, the split or the release conditions cannot explain it.
  What is left: the application stopped calling the flag, a release condition on a cohort or a property stopped matching new people, the audience has no new people, or the project's test-account filter changed, which the experiment's history does not show.

_Verify directly:_

- `exposures.timeseries` in the exposure data: the cumulative count per variant stops growing.
  One arm flat while the other grows points to the flag or to one code path. All arms flat points to the application, or to an audience without new people: the series counts each person once.
- `last_seen` per variant in the raw-responses query, over the last days: no recent events means the application stopped sending them, or that only people who already sent the event still reach the code (B3).
  Both variants silent is a code-path removal, or an audience without new people. One variant silent while the other still fires is a one-sided change, in the flag or in the code.

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
`posthog:diagnosing-sdk-health` skill — an outdated SDK is one possible cause of the "no exposures
at all" shape (missing instrumentation, broken `identify()` ordering, deprecated flag methods).
