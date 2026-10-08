# Bias & skew on a running experiment

Variant counts don't match the configured split, one variant looks biased, the in-app warning banner
appeared, or users are showing up under multiple variants.

## Before diagnosing

Read three values first.
The first two come from the exposure data of the Step 1.5 snapshot (`exposures` in `experiment-results-get`), the third from `experiment-get`.
`experiment-results-get` runs queries: call it once, after the stored results and the change history of the snapshot, and reuse its `exposures` for every check in this file.
The first two are computed on the population the experiment analyzes, which a query of your own does not reproduce.

1. **The sample ratio test: `exposures.sample_ratio_mismatch.p_value`.**
   The page flags a mismatch below **0.001**.
   - Below 0.001: a real assignment or capture problem, or a split that changed during the run, because the test compares the whole run with the current split. Walk A2.
   - At or above 0.001: no mismatch by the product's rule.
     On a small sample the visible split is noise (see C2 in `interpretation.md`).
   - A value between 0.001 and 0.05 is not cleared by that rule `[MEDIUM]`.
     A slow leak of exposures in one arm looks like this for days before it crosses the threshold.
     No tool returns the p-value of an earlier day.
     Read the series in `exposures.timeseries`, which is cumulative per variant: take the difference between days, and walk A9 when the gap grows in one direction.
2. **People in more than one variant: `exposures.total_exposures['$multiple']`** over the sum of all values.
   Non-zero puts A1, A3 and A4 on the table, and A6 and A8 when the flag or the identifier changed during the run.
   Under `first_seen` handling the key is absent, because each person keeps the first variant.
3. **The configured split.** `feature_flag.filters.multivariate.variants[].rollout_percentage` from `experiment-get`.
   An uneven split amplifies whichever bias source is present.
   The flag shows the split of today.
   On an experiment that has ended, or whose flag was edited, take the split of the run from the change history ("Changes after launch" in `diagnostic-snapshot.md`).

**When the observed split matches the split the flag had during the run, there is no mismatch to explain.**
A user who expects 50/50 on a flag that ran at 90/10 has a question about the configuration, not about bias: say which split the flag had and since when.
If the split changed after launch, walk E3 in `mid-run-changes.md`.
The product's sample ratio test compares against the flag's current split, so after such a change its p-value tests the wrong expectation.

If the symptom is "metric count is far smaller than exposures" (e.g. 10× or 100× gap), walk this
file before `numbers-vs-sql.md` — that shape of divergence is most often a bucketing / identity
problem (A3/A4), not a query-scope problem.

The SQL in this file follows the query rules in `diagnostic-snapshot.md`: the experiment's exposure event, the flag's variant keys, a window with both ends set, and no test-account filter.
The exposure event is `resolved_exposure_event`, unless `exposure_criteria.exposure_config` names `$experiment_exposure`: then it is that event ("Which event, which property" in `diagnostic-snapshot.md`).
The queries count `person_id`.
On a flag aggregated by a group type (`feature_flag.filters.aggregation_group_type_index` is set), put `$group_<index>` in its place and leave out the rows where it is empty.
When a result is compared with `$multiple`, leave out the keys in `excluded_variants`: the experiment never counts them.
`resolved_exposure_event` is always the default event.
On an experiment with a custom exposure event these queries read the flag's calls, not the people the experiment counts: say so when you report them.

## Contents

- A1 — Multi-variant exclusion bias on uneven split
- A2 — Sample ratio mismatch (SRM)
- A3 — Identity fragmentation (users in both control and test)
- A4 — Bootstrap × `/flags` variant disagreement
- A5 — Flag/experiment state inconsistency
- A6 — Mid-run flag edits that rebucket already-exposed users
- A7 — Non-randomized assignment via release conditions
- A7b — A forced-variant group starves the other arm
- A8 — Migrating the `distinct_id` strategy during a running experiment
- A9 — Exposure events are lost or sent unevenly between the arms
- A10 — Part of the audience gets no variant from the flag

## A1 — Multi-variant exclusion bias on uneven split [HIGH]

This is the signal behind the in-app banner "Setup likely introduced bias".

**Evidence.** The banner's check reports a finding when **all four** hold:

- `multiple_variant_handling == "exclude"` (the default)
- the variant rollouts are uneven.
  A variant at 0% counts, so a flag at 0/50/50 is uneven.
- the share of people in more than one variant is above **0.1%**.
  The value is `exposures.bias_risk.multiple_variant_percentage`: the `$multiple` count over all exposures.
- the experiment has no end date.
  After the end the check reports nothing, and the banner is gone.
  The exclusion is still in the numbers: the banner's absence on an ended experiment clears nothing.

<!-- Source for maintainers (may rot): evaluate_bias_risk and MULTIPLE_VARIANT_BIAS_THRESHOLD in
products/experiments/backend/health/checks/bias_risk.py; the end-date rule in _evaluate_bias_risk,
products/experiments/backend/hogql_queries/experiment_exposures_query_runner.py. Verify before citing. -->

**The warning-vs-visible gap.** The banner fires above 0.1%.
The collapsed summary of the Exposures panel leaves the `$multiple` row out at or below 0.5%.
The expanded table always lists it, labeled "(excluded from analysis)".
So a user can see the banner while the summary shows a clean split.
The warning is real: point the user to the expanded table, and state the exact share from `exposures.bias_risk`.

<!-- Source for maintainers (may rot): MULTIPLE_VARIANT_WARNING_THRESHOLD and filterLowMultipleVariant in
frontend/src/scenes/experiments/utils.ts; Exposures.tsx in frontend/src/scenes/experiments/ExperimentView. -->

**Mechanism.** Multi-variant users are dropped, but the smaller variant loses a _larger fraction_ of its
assignments than the larger variant. Multi-device / multi-session / signup-flow users tend to be
high-intent — so the smaller variant keeps a low-intent slice and looks worse than it should. This is
asymmetric exclusion bias, not a UI bug.

**Recommend (in this order):**

1. **Switch to an equal split.** See `configuring-experiment-rollout`. On a draft experiment this is
   free. Mid-run it's an anti-pattern — prefer reset or end+restart over changing the split mid-run.
   The banner's own "Adjust distribution" button opens the split editor on the running experiment.
   A user who followed it changed the split mid-run: read the flag's history before any other cause (E3 in `mid-run-changes.md`).
2. **Switch `multiple_variant_handling` to `"first_seen"`.** See `configuring-experiment-analytics`.
   Mid-run this is the low-disruption option — no users switch variants, all already-collected data
   stays in the analysis. `first_seen` is **less biased than `exclude` for this specific shape**, not
   unbiased: it counts the first variant a user saw and ignores later ones, which still
   asymmetrically discounts engaged multi-session users. There is no clean fix for the underlying
   problem; the trade-off is between which bias the user prefers.

The experiment's settings and the public docs call Exclude the recommended handling.
That holds for an even split, and a user may quote it: the banner is the product's own exception for uneven splits.

## A2 — Sample ratio mismatch (SRM) [HIGH]

**Evidence.** `exposures.sample_ratio_mismatch` holds the p-value of a chi-squared test and the expected count per variant.

- The test runs once the variants with a rollout above 0% hold 100 exposures together.
- With fewer than two variants above 0% there is no test, and the value is null.
  That is the state after a ship and after a split edited to 100/0.
  Judge such an experiment by the split of the run ("Changes after launch" in `diagnostic-snapshot.md`).
- The page flags a mismatch at **p < 0.001**.
  The server returns the p-value and applies no threshold.
- The expected counts follow the flag's split **as it is now**.
  They are rescaled for a holdout.
  `$multiple`, the holdout and excluded variants are left out.
- After a split change the test compares the whole run with the new split, so a mismatch is the expected reading.
  Read A6 before anything else in that case.

MUST read the product's value.
MUST NOT run the test on event counts of your own: raw exposure events include test accounts, responses that are no variant, repeated events of one person and events outside the analysis window.

<!-- Source for maintainers (may rot): _calculate_srm and SRM_MINIMUM_SAMPLE_SIZE in
products/experiments/backend/hogql_queries/experiment_exposures_query_runner.py; hasSampleRatioMismatch in
products/experiments/frontend/health/exposureHealth.ts. -->

**What it means.** The distribution of exposed people differs from the flag's current split by more than chance allows.
Either the split changed during the run (cause 1), or something biases the assignment or the capture of exposures.
A visible gap on a small sample is not a mismatch until the test says so, and a mismatch on a small sample is still a mismatch: the test already accounts for the sample size.
The exception is a single reading that clears on the next day's data, which happens about once in a thousand readings by construction.

**Causes, cheapest evidence first.**
Surface each cause the evidence supports (Step 3 of `SKILL.md`).

1. **The flag changed after launch.**
   _Evidence:_ a change of the flag's `filters` after `start_date` in `experiment-activity`.
   Which edits move people, and which do not: A6.
2. **Exposure events are lost or sent unevenly between the arms** `[MEDIUM]`.
   The flag assigns evenly and the event does not arrive evenly: a redirect, an exposure placed after the arms diverge, a flag read before flags load.
   It is the most frequent cause of a mismatch that no flag change explains.
   See A9.
3. **Part of the audience gets no variant.**
   Responses of `false` or an empty value are no exposures, and the people who drop out are not a random share.
   The flag decides whether a person gets a variant apart from which variant, so a `false` from the flag removes people from every arm alike.
   It moves the split only when something ties the loss to one arm, such as the application's own fallback on a custom exposure event, or a pinned condition that still matches without a device id (A10).
   See A10.
4. **A release condition pins a variant.**
   _Evidence:_ a `variant` in `feature_flag.filters.groups[]` that is one of the flag's variant keys.
   See A7.
5. **Server and client evaluate the flag differently** `[MEDIUM]`.
   A bootstrapped value against a later evaluation (A4).
   A server that evaluates locally keeps the old definition for its polling interval after a flag edit.
   A flag with persistence across authentication is not evaluated locally: the SDK falls back to a remote call, so the two paths can answer at different times with different inputs.
   With `strictLocalEvaluation` or `onlyEvaluateLocally` set in posthog-node there is no remote call, and the call returns no value, which is no exposure.
   _Evidence:_ exposures per variant by library (snapshot query), `feature_flag.ensure_experience_continuity`, and whether the user's servers evaluate locally.
6. **Bots on server-side evaluation** `[LOW]`.
   The public docs rank this first.
   As a cause of a directional mismatch it is weak: one crawler is one identifier and counts once.
   It matters when a crawler sends a new identifier with every request.
   _Evidence:_ the share of server-side libraries among the exposures, and exposed people with no later event.
   _Fix path:_ the "Filter Bot Events" transformation (a data pipeline transformation) applies its built-in bot lists to browser events only.
   For events from a server SDK it filters only what the user adds as custom user-agent patterns or IP prefixes.
   With "Keep events where the useragent is not set?" at No, it also drops every event without the user-agent property (`$raw_user_agent` by default), and posthog-node sets that property only when the code passes it.
   The more reliable fix is to not evaluate the flag for requests the server already knows to be bots.

   <!-- Source for maintainers (may rot): nodejs/src/cdp/templates/_transformations/bot-detection/bot-detection.template.ts
   (is_browser_traffic). The public docs rank bots first:
   https://posthog.com/docs/experiments/troubleshooting#diagnosing-sample-ratio-mismatch-srm -->

**What does not cause a mismatch.**

- **Repeated exposure events of one person.**
  The experiment counts each person once, at the first exposure.
  A server SDK that sends the event again after a restart or after its dedup cache fills up changes the event count, not the split.
- **Ad-blockers and network loss.**
  Both arms lose alike.
  The sample shrinks, and a [reverse proxy](https://posthog.com/docs/advanced/proxy) recovers part of it.
- **A holdout.**
  The expected counts are rescaled for it.
- **People in more than one variant, on an even split.**
  They leave both arms alike.
  On an uneven split see A1.

**Fix paths change the flag.**
An agent can edit a flag over MCP.
On a running experiment every such edit is a mid-run change (A6, and Step 4 of `SKILL.md`): explain the effect and get the user's decision before any edit.

## A3 — Identity fragmentation (users in both control and test) [MEDIUM]

**This is an identity problem, not a bias problem.**
One human has two or more distinct ids.
Each id is hashed by itself, so each can land in a different variant.

- When the ids are linked to one person, the analysis sees one person with two variants and counts the person as `$multiple`.
- When the ids were never linked, the analysis sees two persons with one variant each.
  Nothing in the exposure data shows it.

**Evidence.**

- **The count.** `exposures.total_exposures['$multiple']`.
  No event carries `$multiple`.
  The analysis computes it per person, and only from the flag's current variant keys: a response of `false`, an empty response or an old key never makes a person `$multiple`.
- **Under `first_seen` handling** the count is not reported.
  The query below is then the only source.
- **Ids per person.** In the raw-responses query of the snapshot, `distinct_ids / persons` above 1 for a variant means that people evaluated the flag under several linked ids.
  That is the precondition for a flip.
  It says nothing about ids that were never linked.
- **The people**, when the cause has to be named.
  Start with one day on a large project.
  The query finds only people with two variants inside its window, so an empty result on a short window does not rule out A3:

  ```sql
  -- People whose exposure events carry more than one variant key
  SELECT
      person_id,
      uniq(properties.$feature_flag_response) AS variants_seen,
      uniq(distinct_id) AS distinct_ids,
      groupUniqArray(properties.$feature_flag_response) AS variants
  FROM events
  WHERE event = '<resolved_exposure_event>'
    AND properties.$feature_flag = '<flag-key>'
    AND properties.$feature_flag_response IN ('<variant-key-1>', '<variant-key-2>')
    AND timestamp >= toDateTime('<window_start>', 'UTC')
    AND timestamp < toDateTime('<window_end>', 'UTC')
  GROUP BY person_id
  HAVING variants_seen > 1
  ORDER BY variants_seen DESC, distinct_ids DESC
  LIMIT 20
  ```

- **One person's exposure events**, to tell the causes apart:

  ```sql
  SELECT
      timestamp,
      distinct_id,
      properties.$feature_flag_response AS response,
      properties.$lib AS lib
  FROM events
  WHERE event = '<resolved_exposure_event>'
    AND properties.$feature_flag = '<flag-key>'
    AND person_id = '<person_id>'
    AND timestamp >= toDateTime('<window_start>', 'UTC')
    AND timestamp < toDateTime('<window_end>', 'UTC')
  ORDER BY timestamp
  LIMIT 50
  ```

  - Different `distinct_id`s: an identity cause from the list below.
  - The same `distinct_id`, and a flag edit between the two timestamps: A6.
  - The same `distinct_id`, no edit, different libraries: server and client disagree (A4, A10).

  A response of `false` has no `$experiment_exposure` row: when `resolved_exposure_event` is `$experiment_exposure`, run the query on `$feature_flag_called` to see a step to no variant.

**Common causes:**

- `reset()` was called between sessions (other than on logout)
- `identify()` ran **after** the flag was already evaluated
- Cross-device usage without identity stitching
- Cookies cleared between visits, incognito / stealth browsing
- Anonymous → identified transition without flag persistence enabled
- The same user has different anonymous IDs client-side vs server-side, so the flag hash bucket
  differs
- Native mobile auth flows where the flag is read before the SDK identifies the user, or where
  authentication crosses an SDK boundary (e.g. web → in-app webview)

**A note on what's fundamentally fixable vs not.** Stitched-identity issues from `identify()`
ordering, cross-domain cookies, and bootstrap timing are real bugs that can be fixed. Multi-device
usage and incognito / stealth browsing are _not_ fixable from PostHog's side — and the users who
exhibit them tend to be more engaged on average, so excluding the `$multiple` bucket pulls a
non-random slice out of the analysis. There is no clean fix; the recommendation is to _contain_ the
problem (scope exposure to the relevant flow so the denominator stays meaningful) rather than
eliminate it.

**Recommend:**

- Audit `identify()` and `reset()` ordering — `reset()` only on explicit logout, `identify()` before
  flag evaluation.
  Persistence across authentication carries a variant from anonymous to identified, not back: after `reset()` the next evaluation is a new draw.
- For experiments spanning logged-out → logged-in flows, consider one of:
  - **Persist flag across authentication steps** (tradeoffs: requires `person_profiles: 'always'`,
    incompatible with local evaluation and bootstrapping, adds slight latency)
  - **Device-ID bucketing** — appropriate for landing/marketing/anonymous flows. Keeps the variant
    stable across the anonymous→identified transition without the flag-persistence tradeoffs. Many
    users don't realize this option exists; surface it explicitly when the symptom is cross-auth
    bucketing.
    Two limits.
    An evaluation without a device id gets no variant (the flag returns `false`), which is the usual case for a server-side call that passes none (A10).
    The exception is a release condition at a rollout of 100% that pins a variant: it still matches, and returns the pinned variant.
    And it cannot be combined with persistence across authentication: the API refuses the pair.
- For pre-auth experiments, ensure cookies/localStorage persistence is configured (cookies preferred
  for cross-subdomain).
- For mobile flows, consider evaluating the flag server-side (local evaluation) once the user is
  authenticated rather than on first app open.

## A4 — Bootstrap × `/flags` variant disagreement [MEDIUM]

Specific scenario: server-rendered app with bootstrapping enabled. The `$multiple` share in this
shape can become substantial — well above the trickle you'd expect from normal cross-device traffic
alone. Website-only flags (no bootstrap) are unaffected.

**Mechanism.** Two shapes.

- **Different identifiers.** The server bootstraps flags using the server-known `distinct_id`, but the bootstrap
  payload doesn't include `distinctID` — so `posthog-js` initializes with whatever's in persistence (often
  the anonymous ID). The bootstrap value gets reported under the anonymous ID; then `posthog-js` asks
  the flag service with whatever ID it has after `identify()`. When the IDs differ, the hashes differ,
  and one person sends exposure events for two variants.
  On a flag that buckets on the device id the identifier does not change at `identify()`, so this shape needs different device ids.
- **Different inputs** `[MEDIUM]`. The bootstrap values come from the user's own backend, which evaluates the flag with the properties it passes.
  A property in another type or format than the stored one (a timestamp as a string against a stored number), or a variant set by hand, matches on one side only.
  The bootstrap-sourced exposure carries a variant, and the next evaluation returns another variant or `false`.
  The user sees the new experience for a moment and then loses it.

**Evidence.** The exposure event carries two source properties:

- `$used_bootstrap_value` — `true` when the value was read before the flags request of that page load answered.
  That is a bootstrap value, and also a value cached from an earlier page load.
  `$feature_flag_bootstrapped_response` holds what the bootstrap payload said for the flag, and is null without one.
- `locally_evaluated` — `true` when the event came from server-side local evaluation.

The signature is one person with an event read before the flags request answered and another event for the same flag, with different variants.
`$used_bootstrap_value` is usually not a materialized column, so this query reads the full properties of every row: keep the window to one day.
The comparison with `true` needs the property typed Boolean in the project, which is the usual case.
If the query fails on a type error, write the two conditions as `toString(properties.$used_bootstrap_value) = 'true'` and `ifNull(toString(properties.$used_bootstrap_value), '') != 'true'`.

```sql
SELECT
    person_id,
    groupUniqArrayIf(properties.$feature_flag_response, properties.$used_bootstrap_value = true) AS bootstrap_variants,
    groupUniqArrayIf(properties.$feature_flag_response, ifNull(properties.$used_bootstrap_value, false) = false) AS other_variants
FROM events
WHERE event = '<resolved_exposure_event>'
  AND properties.$feature_flag = '<flag-key>'
  AND properties.$feature_flag_response IN ('<variant-key-1>', '<variant-key-2>')
  AND timestamp >= toDateTime('<window_start>', 'UTC')
  AND timestamp < toDateTime('<window_end>', 'UTC')
GROUP BY person_id
HAVING length(bootstrap_variants) > 0
   AND length(other_variants) > 0
   AND arraySort(bootstrap_variants) != arraySort(other_variants)
LIMIT 20
```

Rows here distinguish A4 from A3: A3 is identity fragmentation regardless of
source, A4 is specifically the bootstrap mismatch.
A stale cached value and a flag edit between two page loads give the same rows: confirm with `$feature_flag_bootstrapped_response` on the event, and with the flag's history.
If the query returns no rows _and_
no events for the flag have `$used_bootstrap_value = true` anywhere, bootstrap is likely not in
play and A4 is unlikely — but absence isn't definitive (older SDKs may not stamp the property).
Cross-check by asking whether the user's app is server-rendered with bootstrapping enabled.
For the second shape, the non-bootstrap response is often `false`: drop the variant filter from the query to see it, and query `$feature_flag_called`, because `$experiment_exposure` holds no `false` response.

**Recommend:**

- Pass `distinctID` in the bootstrap payload when the server already knows the identity (e.g. logged-in
  users).
- Bootstrap should be used together with server-side local evaluation, not alone.
- Pass person properties to the evaluation in the type the release conditions compare against.

## A5 — Flag/experiment state inconsistency [HIGH]

The experiment view shows one warning banner for a state in which the experiment and its flag disagree.
Five states exist, checked from `experiment-get` alone:

| Banner caption                                                              | State                                                                                                                                       | What the banner says to do                                                                 |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| "The experiment is paused"                                                  | Launched, no end date, the flag is disabled. `status` is `paused`                                                                           | Resume or end the experiment                                                               |
| "The experiment is running, but no new users are being exposed"             | Running, every release condition has a rollout of 0%                                                                                        | End with a conclusion, or increase the rollout. People exposed earlier stay in the results |
| "The experiment is running, but all users see a single variant"             | Running, the first release condition matches everyone at 100%, and one variant holds 100% of the split                                      | End with a conclusion, or adjust the variant distribution                                  |
| "The experiment is not running, but users are exposed to multiple variants" | Ended, the flag is active, more than one variant is above 0%, and a release condition is above 0%                                           | Disable the flag, or resume the experiment                                                 |
| "The experiment is not running, but users are exposed to multiple variants" | Not launched (also after a reset), not archived, the flag is active, more than one variant is above 0%, and a release condition is above 0% | Disable the flag, or start the experiment                                                  |

"Adjust the variant distribution" on a running experiment is a change of the split, with what that does to the people already exposed (E3 in `mid-run-changes.md`).
Say so before the user restores a split.

<!-- Source for maintainers (may rot): ExperimentWarningBanners.tsx in frontend/src/scenes/experiments/ExperimentView,
experimentWarning in experimentLogic.tsx, isSingleVariantShipped in products/experiments/frontend/scenes/experimentsLogic.ts. -->

What the banners do not cover:

- **A pinned variant.** A release condition that forces one variant shows no banner (A7b).
- **A shipped variant.** A ship ends the experiment, and the single-variant banner checks running experiments only (E7 in `mid-run-changes.md`).
- **Frozen exposure.** `status` is `exposure_frozen`, and no banner appears (E16 in `mid-run-changes.md`).
- **A deleted flag.**

**A flag that was active before launch.**
Exposures before `start_date` are outside the analysis, and the hash is the same before and after launch, so they do not put people in more than one variant.
The risk is the SDK's deduplication: a returning person who already sent the exposure event before launch may not send it again (B3 in `empty-experiment.md`).

Use `managing-experiment-lifecycle` for the correct lifecycle action.

## A6 — Mid-run flag edits that rebucket already-exposed users [MEDIUM]

A person's variant follows from three things: the flag key, the identifier the flag buckets on, and the boundaries of the variant split.
The variant key is not an input: a variant is a slot in the split, and the key is its label.
The rollout of a release condition is drawn separately, so it decides whether a person is in, never which variant.

So flag edits after launch differ in what they do to a person who is already exposed:

| Edit after launch                                                                  | Moves the person to another variant?                                                                                                                                                                                                                | What the data shows                                                                                 |
| ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| The variant split changes. Also: one variant to 0%, or the variants reordered      | **Yes**, everyone whose draw lies between an old and a new boundary. That includes people of variants the edit did not touch                                                                                                                        | The same person under a second variant key: `$multiple` under `exclude`. A 0% variant stops growing |
| The bucketing identifier changes, or persistence across authentication is switched | **Yes**, for the people whose identifier changes. A persistence switch moves only those whose stored or anonymous id differs from their `distinct_id`. A new identifier is a new draw, and about half keep their variant by chance on a 50/50 split | `$multiple` rises from the day of the edit                                                          |
| A release condition is added, tightened, or its rollout changes                    | **No**. People move in or out. Out means the flag returns `false`, which is no variant                                                                                                                                                              | More or fewer new exposures. No `$multiple` from this edit alone                                    |
| The same, when the condition a person now matches pins a variant                   | **Yes**, to the pinned variant                                                                                                                                                                                                                      | See A7                                                                                              |
| A variant key is renamed                                                           | **No**. The same slot gets a new label. The flag API rejects the rename while the experiment runs                                                                                                                                                   | Exposures under the old key leave the analysis, because only current keys count                     |
| The flag's key is renamed                                                          | **Yes**. The key is an input of the draw, so everyone gets a new one. The flag API allows it while the experiment runs                                                                                                                              | Exposures sent before the rename carry the old key and leave the experiment                         |

<!-- Source for maintainers (may rot): get_hash, hashed_identifier, check_rollout and get_matching_variant in
rust/feature-flags/src/flags/flag_matching.rs; select_variant in rust/feature-flags/src/flags/v1_bucketing.rs;
the variant-key guard in FeatureFlagSerializer, products/feature_flags/backend/api/feature_flag.py. -->

**Evidence.** `experiment-activity` returns the changes of the experiment and of its linked flag, each with the values before and after.
Look for a change of the flag's `filters` after `start_date`, and compare `multivariate.variants`, `groups` and the bucketing identifier on both sides.
The same rows are in `feature-flags-activity-retrieve`, and in `advanced-activity-logs-list` when `fields` is left out or includes `detail.changes`.
`advanced-activity-logs-list` is offered only on a plan with audit logs.

**What an edit does not prove.**
A split change explains the people who were exposed on both sides of it.
People in more than one variant who were exposed only before or only after the edit have another cause, usually A3.
State the edit and its date. Do not attribute the whole `$multiple` share to it.

**Recommend:** treat a split change and an identifier change as contamination from the edit on.
Reset and relaunch is the cleaner fix.
Switching `multiple_variant_handling` to `first_seen` is the low-disruption mid-run option (per A1).
A rollout change alone needs no repair (E1 and E2 in `mid-run-changes.md`).

## A7 — Non-randomized assignment via release conditions [MEDIUM]

If the user is using release conditions to target specific cohorts to specific variants (e.g. iOS
users see test, Android users see control), the resulting assignment is **not random**. PostHog's
statistics assume randomization, so this invalidates the standard significance interpretation.

PostHog doesn't prevent this in the UI — but the user should understand that significance calculations
are misleading in this setup.
Nothing in the analysis leaves the pinned people out.

**Verify directly.** In `experiment-get`'s response, scan
`feature_flag.filters.groups[]` for any entry where `variant` is one of the flag's variant keys. That field is the
per-release-group variant override: any user matching that group's `properties[]` is forced to
that variant rather than being randomly bucketed. A `variant: null` (or missing field) means the
group is randomized normally and A7 doesn't apply.

Three rules decide who is pinned:

- Release conditions are evaluated in their stored order, and the first match wins.
  A pinned condition forces only the people who matched no earlier condition.
- A `variant` that is not one of the flag's variant keys is ignored, and the person is bucketed normally.
- A holdout is evaluated before every release condition.
  People in the holdout are not pinned.

When the override exists, also check whether the targeted cohort overlaps the project's
test-account exclusion list (B7 in `empty-experiment.md` says where to read it). If the cohort is _in_ the exclusion list and `exposure_criteria.filterTestAccounts` is not `false`, those users are filtered
out of the analysis and the override is mostly a no-op for the metric (they were never going to
count). If the cohort is _not_ excluded (e.g. an external partner's email domain), the override
contaminates the variant assignment for real users.

When the exclusion runs through a dynamic cohort, it lags `[LOW]`.
The flag evaluates the person's properties live, and the analysis usually reads the cohort's stored membership, which is recalculated on a schedule.
For some projects the analysis computes a fast cohort at query time, and then there is no lag.
People who are pinned today and not yet in the stored cohort count in the pinned arm.
Exclude on the person property itself in both places.

**Recommend:** if they need to compare cohorts, run separate experiments per cohort, or use a single
random assignment and analyze the cohorts as breakdowns of the same experiment (with the multiple-
comparisons caveats from `references/interpretation.md`). If the override exists by accident
(left over from QA / pre-launch validation), remove it: set `variant: null` on the affected
release group, or delete the group entirely. On a young experiment with little accumulated data,
reset + relaunch after the edit; on an experiment with significant clean data from before the
issue was noticed, treat the post-launch window as contaminated and consider end + relaunch.

### A7b — A forced-variant group starves the other arm [HIGH]

The cohort-vs-cohort case above invalidates significance but still collects both variants. A worse
shape is a forced-variant release group whose `properties` are broad (or empty) at high rollout: it
captures most or all of the population, so the _other_ variant receives almost no analyzable
exposures. Two shapes:

- **Unconditional catch-all forcing one variant.** A release group with **empty `properties[]`**
  (matches everyone) and a pinned `variant` at `rollout_percentage: 100`. Every user who doesn't match
  an earlier, narrower group falls through to it and is forced to that variant; the randomized
  `multivariate` split never applies. One arm is orders of magnitude larger than the other, and the
  small arm holds leftovers from earlier flag versions.
- **"All new users" cohort forcing one variant, with no control path.** A release group like
  `created_at_unix >= <ts>` → `variant: test` at 100%, where **no release group leaves `variant: null`
  and no group forces the other variant**. Every new account is forced to `test`; the `control` arm
  stops receiving new assignments and starves over time. Control collapses from a balanced share to
  a trickle within weeks of the forced group being added, while test keeps growing.

**Detect (config-only, from `experiment-get`).** Enumerate `feature_flag.filters.groups[]` and for each
read `variant`, `properties` (an empty array = catch-all matching everyone), and `rollout_percentage`.
Red flags, any of:

- a group with `variant` set **and** broad/empty `properties` at high `rollout_percentage`;
- **no** group with `variant: null` or with a `variant` that is not one of the flag's variant keys, i.e. nothing is randomized at all;
- every variant-pinned group forces the **same** variant — i.e. there is no release path to the other arm.

No banner covers this shape.
The single-variant banner of A5 reads the variant split, and a pinned group leaves the split untouched.

**Confirm from exposures, and use the trend to read intent.** `exposures.total_exposures` shows the
starved arm immediately as one variant's persons being orders of magnitude below the other. Then read
the daily series (`exposures.timeseries`, cumulative by the day of first exposure); the shape tells you
what happened and is worth pulling _before_ you characterize it:

- **Ran balanced, then one arm collapses** — both arms roughly even for a period, then one variant's
  new assignments drop toward ~0 from a specific date. The experiment ran as a real A/B and was then
  **rolled out** via the flag. The balanced window is the valid result.
- **One arm never received meaningful traffic** — the minority variant is ≈ internal pins / a trickle
  from the start, never a real share. It was served one variant from the start; it likely never ran
  as a randomized A/B at all.

This is distinct from the diagnostic-snapshot "plateau" (where the _application_ stopped firing the
flag) — here the app still fires; the flag _config_ forces the variant, so the cause is visible in
`feature_flag.filters.groups[]`, not just the event stream.

**Calibrate before reporting — this usually mirrors a rollout, not a bug.** A broad set forcing a
variant at 100% is most often a **deliberate rollout** done through the flag instead of the experiment
UI (or a default being forced), with the experiment left in `running` status — not an accident. Two
things sharpen the read:

- **Which variant is forced.** Forcing `test` (the new behaviour) = the new feature was rolled out to
  everyone. Forcing `control` (the status quo) = the _default_ was served to everyone, i.e. the feature
  was effectively **not** shipped — worth surfacing as a question, since it's easy to pin the wrong
  variant ("did you intend users to get the new experience, or the status quo?").
- **The exposure trend above** — ran-then-rolled-out vs never-randomized.

Whatever the intent, while the flag forces a variant the experiment **cannot produce a valid
control-vs-test readout**, and its results page should not be read as an A/B. Recommend **concluding the
experiment** (read any pre-rollout balanced window as the result); if it was genuinely accidental,
removing the forced-variant group(s) and resetting restores randomization. Surface the finding and
confirm intent rather than asserting the experiment is "broken" (consistent with Step 4's
don't-assume-intent guidance in `SKILL.md`).

## A8 — Migrating the `distinct_id` strategy during a running experiment [HIGH]

If the user is changing how `distinct_id` is sent (e.g. anonymous → identified user ID, or
email-as-ID → stable user ID, or a different identifier altogether) while an experiment is running,
the affected people are drawn again the next time the flag is evaluated.
The variant comes from a hash of the flag key and the identifier the flag buckets on.
For a flag that buckets on the person, without persistence across authentication, that identifier is the `distinct_id`: a new id is a new draw, and on a 50/50 split about half of the affected people land in the other variant.

**Not affected:** a flag that buckets on the device id, and a group-aggregated flag.
Their identifier does not change.

**What the data shows.**
When the old and the new id are linked to one person, the person counts as `$multiple`.
When they are not linked, the analysis sees a second person, and nothing flags it.
The migration is a change in the user's code, so no activity log shows it.

**Recommend:**

- Finish or end the running experiment **before** the identifier migration, then start a fresh
  experiment under the new strategy.
- If they have to migrate during the run, expect inflated `$multiple` and treat the affected window
  as contaminated — use `reset` + relaunch once the migration is complete.
- An "experience continuity" / flag-persistence approach can paper over anonymous → identified
  transitions but is not a general substitute for the migration above (see A3 tradeoffs).

## A9 — Exposure events are lost or sent unevenly between the arms [MEDIUM]

**Symptom (in the user's vocabulary):** "the split is 58/42 and should be 50/50", "one variant gets fewer users every day", "our own analytics show an even split and PostHog does not".
Often with the mismatch warning, sometimes with a p-value that is low and not yet below the threshold.

**Behavior.** The flag assigns evenly.
The exposure event does not arrive evenly, because the arms differ in what happens around the moment the event is sent:

- **One arm navigates away.**
  The variant redirects or reloads the page right after the flag is read, and the browser leaves before the SDK sends its queue.
- **The exposure sits behind the divergence.**
  The event is sent on a page, in a component or after a step that one arm reaches more often, later or never.
- **One code path reads the flag early.**
  The code reads the flag before the SDK has loaded the flags and falls back to a hardcoded variant, or it reads the flag through a call that sends no exposure (B1 in `empty-experiment.md`).
  In posthog-js an early read returns nothing only when no flags are cached from an earlier page load, so this loss falls on people with no cached flags, mostly first visits.
- **One arm is slower or fails more often**, so people leave before the event is sent.
- **A cached page carries the assignment** `[LOW]`.
  A page that is cached with a variant or an identifier inside hands one assignment to many browsers.
- **The exposure is recorded before anything is rendered.**
  A server or an edge function records the exposure, and a share of those requests never renders a page: prefetches, bots, blocked browsers.
  The split of exposures is even, and the arms still differ in who arrives.
  The sample ratio test does not see this shape.

**Evidence to gather.**

- **Where the gap sits.** Exposures per variant by day and by library (query in `diagnostic-snapshot.md`).
  A gap in one library, or from one day on, names the code path or the deploy.
  The same query by page shows an exposure that one arm sends from a page the other arm never reaches.
- **The exposure criteria first.** A filter in `exposure_criteria.exposure_config.properties` that only one arm's events can match gives the same picture, and is a setting, not code (B12 in `empty-experiment.md`).
- **New against returning people.** A gap among returning people only has two candidates: this entry, and the SDK that does not send the event again for a person who already sent it (B3 in `empty-experiment.md`).
  No tool splits exposures this way: add `person.created_at < toDateTime('<start_date>', 'UTC') AS returning` to the SELECT and the GROUP BY of the "By day and library" query in `diagnostic-snapshot.md`, and compare the arms within each group.
  B3 removes returning people from every arm in proportion, so a gap in one arm points here.
- **With a custom exposure event:** the split of the flag calls against the split of the custom event.
  Even flag calls and an uneven custom event put the loss between the flag read and the exposure.
- **The code around the flag read in each arm:** a redirect, a reload, a fallback value, a different component.
  This is a question for the user when the repository is not at hand.

**Co-occurs with:** A2 (this is its most frequent cause), A10, and B8 in `empty-experiment.md`.

**Recommendation.** Send the exposure at a point that both arms pass before they diverge.

- A custom exposure event at the common entry, for example the page view of the landing URL.
  It needs the variant in `$feature/<flag-key>` (B4 in `empty-experiment.md`).
- An exposure from the server at assignment, when the arms diverge in the browser.
- Wait for flags to load before the first read, and send no fallback variant.

The results collected so far carry the bias.
After the fix, reset and relaunch, or move the start of the analysis to the fix.

## A10 — Part of the audience gets no variant from the flag [MEDIUM]

**Symptom (in the user's vocabulary):** "most responses on the flag are `false`", "users saw the new UI for a second and then lost it", "far fewer exposures than visitors on that page", "control is much bigger than it should be".

**Behavior.** Only an exposure whose response is one of the flag's variant keys counts.
A response of `false`, an empty response, or a key that is no variant is no exposure, and nothing warns about it.
The people who get no variant are rarely a random share, so the people who stay are a biased sample, and the arms can lose different shares.

Why an evaluation returns no variant:

- **The flag's inputs are not there yet.**
  A release condition reads a person property that the backend sets (a sign-up date, a plan, an app version).
  A client that evaluates before the property is stored cannot match.
  New users in onboarding are hit most.
  With `person_profiles: 'identified_only'`, anonymous visitors have no stored person properties: the flag sees only what the client sends with the call.
- **Client and server hold different values** (A4, second shape).
- **Device bucketing without a device id.**
  A flag that buckets on the device id returns `false` for a call that carries none, which is the usual case for a server-side call.
  A release condition at a rollout of 100% that pins a variant still matches without a device id, so such calls carry only the pinned variant.
- **A group-aggregated flag without the group.**
  A flag that is aggregated by a group type returns `false` for a call that carries no key for that group type.
- **The flag is read before flags load**, or before a consent step lets the SDK load them.
  In posthog-js the read returns nothing only when no flags are cached from an earlier page load: a returning visitor gets the cached value.
- **The application's own fallback** `[MEDIUM]`.
  Code that reports "no variant" as `control` puts everyone outside the rollout into control, in every count that the application fills: the user's own analytics, and a custom exposure event that carries the application's value.
  Control there holds every person the flag gives no variant, on top of its own share of the people with a variant.
  The default exposure event is not affected: its response stays `false` and is no exposure.
- **A holdout.**
  People in a holdout get `holdout-<id>` in place of a variant.
  That is intended: they are outside the experiment.

**Evidence to gather.**

- **The responses of `$feature_flag_called` by day and by library** ("By day and library" in `diagnostic-snapshot.md`, with `$feature_flag_called` as the event): the share that is no variant key, and whether it sits in one library.
  `$experiment_exposure` holds no `false` or empty response, so it cannot show these rows.
- **`feature_flag.filters.groups[].properties`:** a condition on a property that is set after sign-up, or by the backend.
- **`feature_flag.bucketing_identifier`.**
- A `false` share that equals what the release conditions exclude by design is not a finding.

**Co-occurs with:** A2, A4, A9, and B10 in `empty-experiment.md`.

**Recommendation,** in order of preference:

1. Send the exposure from the place that knows the variant the user got.
2. Put the variant on the exposure event explicitly.
3. Make the flag's inputs available before the evaluation: pass the person properties with the call, and wait for flags to load.
4. Avoid release conditions on data that does not exist at evaluation time.
