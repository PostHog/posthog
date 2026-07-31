# Bias & skew on a running experiment

Variant counts don't match the configured split, one variant looks biased, the in-app warning banner
appeared, or users are showing up under multiple variants.

## Before diagnosing

Pull three signals first:

1. **SRM result on the Exposures tab.** A green SRM check at ≥100 exposures rules out real
   imbalance — the visible split is normal small-sample variance (see C2 in `interpretation.md`).
   A red SRM means there is a real assignment or capture problem; proceed below.
2. **`$multiple` share.** If non-zero, identity fragmentation (A3/A4) is on the table.
3. **Configured split.** Read `experiment-get`'s
   `parameters.feature_flag_variants[].rollout_percentage` — uneven splits amplify whichever bias
   source is present.

If the symptom is "metric count is far smaller than exposures" (e.g. 10× or 100× gap), walk this
file before `numbers-vs-sql.md` — that shape of divergence is most often a bucketing / identity
problem (A3/A4), not a query-scope problem.

## Contents

- A1 — Multi-variant exclusion bias on uneven split (the in-app banner)
- A2 — Sample ratio mismatch (SRM)
- A3 — Identity fragmentation (users in both control and test)
- A4 — Bootstrap × `/decide` variant disagreement
- A5 — Flag/experiment state inconsistency
- A6 — Mid-run flag edits that rebucket already-exposed users
- A7 — Non-randomized assignment via release conditions (incl. forced-group arm starvation)
- A8 — Migrating the `distinct_id` strategy during a running experiment

## A1 — Multi-variant exclusion bias on uneven split [HIGH]

This is the in-app bias-warning banner's signal. Triggers when **all three** hold:

- `multiple_variant_handling == "exclude"` (the default)
- variant rollouts are uneven
- there are _any_ observed `$multiple` exposures (the backend warning fires above **0.1%**
  multi-variant share — `MULTIPLE_VARIANT_BIAS_THRESHOLD` in
  `products/experiments/backend/analysis_health.py`)

**The warning-vs-visible gap.** The backend warning banner fires at > 0.1% `$multiple` share, but
the Exposures tab in the UI hides the `$multiple` row when share is ≤ 0.5%
(`MULTIPLE_VARIANT_WARNING_THRESHOLD` in `frontend/src/scenes/experiments/utils.ts`). So a user
can see the bias-warning banner _while_ the Exposures tab shows a clean variant split with no
`$multiple` row — they'll ask "why is the warning firing when no users are in `$multiple`?". When
the user reports this disconnect, lead with: the warning is real; the row is hidden because the
share is between 0.1% and 0.5%. Pull the exact share from the Step 1.5 snapshot so the
explanation is concrete, not abstract.

**Mechanism.** Multi-variant users are dropped, but the smaller variant loses a _larger fraction_ of its
assignments than the larger variant. Multi-device / multi-session / signup-flow users tend to be
high-intent — so the smaller variant keeps a low-intent slice and looks worse than it should. This is
asymmetric exclusion bias, not a UI bug.

**Recommend (in this order):**

1. **Switch to an equal split.** See `configuring-experiment-rollout`. On a draft experiment this is
   free. Mid-run it's an anti-pattern — prefer reset or end+restart over changing the split mid-run.
2. **Switch `multiple_variant_handling` to `"first_seen"`.** See `configuring-experiment-analytics`.
   Mid-run this is the low-disruption option — no users switch variants, all already-collected data
   stays in the analysis. `first_seen` is **less biased than `exclude` for this specific shape**, not
   unbiased: it counts the first variant a user saw and ignores later ones, which still
   asymmetrically discounts engaged multi-session users. There is no clean fix for the underlying
   problem; the trade-off is between which bias the user prefers.

## A2 — Sample ratio mismatch (SRM) [HIGH]

Open the Exposures tab. PostHog runs a chi-squared test once total exposures ≥ 100 and flags SRM at
**p < 0.001**. The `$multiple` bucket is **excluded** from the SRM check (so a high `$multiple` share is
_not_ what triggers SRM — it's that the visible variants don't match the configured rollout).

**Verify directly.** The exposure-shape query from Step 1.5 already gives the counts. Compare observed
vs expected (using `parameters.feature_flag_variants[].rollout_percentage`) and apply χ². Treat
p < 0.001 as SRM.

**What it means.** The actual variant distribution differs significantly from the configured split —
something is biasing variant assignment or exposure capture. Note: low-volume variance can produce
splits that _look_ off without being SRM. The chi-squared test accounts for that, so trust the SRM check
over the visual ratio.

**Investigate, in order.** Each item has a _Detect_ (how the agent can verify it from MCP / by
asking) and a _Fix path_ (the specific action to recommend — the agent cannot mutate flag
conditions via MCP, only read them, so most fixes are precise guidance not direct action):

1. **Bot traffic hashing into a single variant.** Server-side flag evaluations from bots are
   deterministic by `distinct_id` — a single crawler hitting the same path repeatedly hashes into
   the same variant and skews the visible split. The public troubleshooting docs rank this as the

   _Detect:_ check whether the exposure events come from server-side evaluations (
   `$lib` values like `posthog-python`, `posthog-node`, `posthog-ruby`, `posthog-go`,
   `posthog-php`). High server-side share + no bot filter is the signature.

   _Fix path:_ enable the **Bot detector** Hog Function template at _Settings → Data pipeline →
   Transformations_. Filters known crawler user agents before ingestion. Cannot be enabled via
   MCP — guide the user to the UI.

   <!-- Source for maintainers: docs at https://posthog.com/docs/experiments/troubleshooting#diagnosing-sample-ratio-mismatch-srm
   (item 1, "ranked by frequency"). Template lives in
   posthog/api/test/__data__/hog_function_templates.json — search for "known_bot_filter_list". -->

2. **`identify()` timing.** Late `identify()` fragments users into multiple distinct_ids and skews
   exposure. (See A3 for the mechanism.)

   _Detect:_ the `distinct_ids / persons` ratio from Step 1.5 — noticeably > 1 is the signal.

   _Fix path:_ call `identify()` _before_ the flag is evaluated. Do not call `reset()` between
   sessions (only on logout). SDK code change — guide the user.

3. **Wrong evaluation method.** Single-flag accessors fire `$feature_flag_called`; bulk and
   payload-only accessors don't. See B1 in `empty-experiment.md` for the per-SDK table.

   _Detect:_ ask the user which method they call to read the flag.

   _Fix path:_ switch to `getFeatureFlag()` / `get_feature_flag()` / framework hook.

4. **Complex release conditions.** Property-based targeting can create uneven assignment when the
   property is missing or evaluates differently at flag-call time.

   _Detect:_ call `feature-flag-get-definition` and inspect `filters.groups[].properties` — does
   any condition reference a property that might be missing or late-loaded? Note that
   **non-randomized release conditions** (forced overrides) also produce pre-exposure bias.

   _Fix path:_ simplify conditions, or test with a clean 50/50 rollout and no property conditions
   to isolate. Cannot mutate flag conditions via MCP — guide the user.

5. **Ad-blockers / network drops.** Prevent flag calls from reaching PostHog at all.

   _Detect:_ indirect — partial-data hint. If the user's expected traffic is much higher than
   captured exposures and other causes are ruled out, this is the residual.

   _Fix path:_ set up a [reverse proxy](https://posthog.com/docs/advanced/proxy) so capture
   requests come from the user's own domain. Typical capture lift: 10–30%. Infrastructure
   change — guide the user.

6. **Bootstrap × `/decide` disagreement.** Server-rendered apps with bootstrap enabled can emit
   two `$feature_flag_called` events for the same person under different IDs. See A4.

   _Detect:_ the `$used_bootstrap_value` discriminator query in A4.

   _Fix path:_ pass `distinctID` in the bootstrap payload when the server knows the identity; use
   bootstrap with server-side local evaluation, not alone. Code change — guide the user.

7. **Server-side / local-evaluation drift.** Local-evaluation flag definitions refresh on an
   SDK-specific interval (typically tens of seconds). If the flag was edited mid-run, exposures
   captured during the refresh window use the old definition.

   _Detect:_ hard to verify from data alone — timing-based. Cross-check with
   `feature-flags-activity-retrieve` to find recent edits, then ask whether the user's
   server-side fleet is configured for local evaluation.

   _Fix path:_ lower the local-eval refresh interval, or avoid mid-run flag edits. Cannot reach
   via MCP — guide.

8. **Flag-persistence-across-auth (experience continuity).** This setting (`ensure_experience_continuity`
   on the flag) is incompatible with local evaluation; mixing them produces inconsistent
   assignments. Native mobile auth flows that combine both are particularly susceptible.

   _Detect:_ `feature-flag-get-definition` returns `ensure_experience_continuity`. If `true` _and_
   local evaluation is in use server-side, that's the conflict.

   _Fix path:_ pick one. For pre-auth experiments, **device-ID bucketing** is often the better
   fix (see A3) — this option is easy to miss; surface it explicitly. Flag mutation needed —
   cannot via MCP, guide the user.

9. **Flag-condition changes via the API.** The experiment UI locks flag conditions on a launched
   experiment, but the API does not enforce the same restriction. A tooling pipeline can quietly
   skew the split.

   _Detect:_ `feature-flags-activity-retrieve { id: <feature_flag_id> }` — scan
   `results[].detail.changes[]` for `field == "filters"` after the experiment's `start_date`. The
   diff shows the exact condition change.

   _Fix path:_ revert via the flag UI (cannot mutate flag conditions via MCP). If the change was
   substantial, treat the post-change window as contaminated and consider reset + relaunch.

10. **Server-side SDK dedup cache overflow [LOW].** Server-side SDKs (Node, Python) dedup exposure
    events using an in-memory cache of ~50,000 distinct `(distinct_id, flag, variant)` entries. On
    high-throughput servers, earlier entries are evicted and those users fire duplicate exposures
    after a worker restart — inflating one variant's count if traffic isn't symmetric across the
    fleet.

    _Detect:_ hard from data alone. Ask: roughly how many distinct users does each worker see
    between restarts? > 50k is the danger zone.

    _Fix path:_ shorter worker restart cadence, or fire `$feature_flag_called` yourself with a
    custom exposure event you control the dedup window for. Code/infra change — guide the user.

    <!-- Source for maintainers: docs at https://posthog.com/docs/experiments/troubleshooting#diagnosing-sample-ratio-mismatch-srm
    (item 4). Tagged [LOW] until directly verified. -->

## A3 — Identity fragmentation (users in both control and test) [MEDIUM]

**This is an identity problem, not a bias problem.** The user has two (or more) distinct_ids that
haven't been linked — PostHog sees them as separate persons, each correctly assigned a variant.
The symptom — same human appearing in both control and test — usually shows up as elevated
`$multiple` share.

**Verify directly.** Two signatures worth checking before recommending:

```sql
-- Persons exposed to more than one variant (excluding the synthetic $multiple bucket)
SELECT
  person_id,
  count(DISTINCT properties.$feature_flag_response) AS variants_seen,
  count(DISTINCT distinct_id) AS distinct_ids,
  groupArray(DISTINCT properties.$feature_flag_response) AS variants
FROM events
WHERE event = '$feature_flag_called'
  AND properties.$feature_flag = '<flag-key>'
  AND properties.$feature_flag_response != '$multiple'
  AND timestamp >= '<start_date>'
GROUP BY person_id
HAVING variants_seen > 1
ORDER BY variants_seen DESC
LIMIT 50
```

A non-trivial count of rows here, or a `distinct_ids / persons` ratio noticeably above 1 in the Step 1.5
snapshot, points at fragmentation. Pick one or two `person_id`s and use `persons-retrieve` to confirm
whether they look like cross-device/cross-auth journeys vs the SDK-ordering bugs below.

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
- For experiments spanning logged-out → logged-in flows, consider one of:
  - **Persist flag across authentication steps** (tradeoffs: requires `person_profiles: 'always'`,
    incompatible with local evaluation and bootstrapping, adds slight latency)
  - **Device-ID bucketing** — appropriate for landing/marketing/anonymous flows. Keeps the variant
    stable across the anonymous→identified transition without the flag-persistence tradeoffs. Many
    users don't realize this option exists; surface it explicitly when the symptom is cross-auth
    bucketing.
- For pre-auth experiments, ensure cookies/localStorage persistence is configured (cookies preferred
  for cross-subdomain).
- For mobile flows, consider evaluating the flag server-side (local evaluation) once the user is
  authenticated rather than on first app open.

## A4 — Bootstrap × `/decide` variant disagreement [MEDIUM]

Specific scenario: server-rendered app with bootstrapping enabled. The `$multiple` share in this
shape can become substantial — well above the trickle you'd expect from normal cross-device traffic
alone. Website-only flags (no bootstrap) are unaffected.

**Mechanism.** The server bootstraps flags using the server-known `distinct_id`, but the bootstrap
payload doesn't include `distinctID` — so `posthog-js` initializes with whatever's in persistence (often
the anonymous ID). The bootstrap value gets reported under the anonymous ID; then `posthog-js` calls
`/decide` with whatever ID it has after `identify()`. When the IDs differ,
`hash(anonymous_id) ≠ hash(user_id)` → different variant bucket → two `$feature_flag_called` events for
two variants.

**Verify directly.** `$feature_flag_called` carries two source-discriminator properties:

- `$used_bootstrap_value` — `true` when the event came from the client's bootstrap payload.
- `locally_evaluated` — `true` when the event came from server-side local evaluation.

A4's signature is a single person who emitted **both** a bootstrap-sourced event and a non-bootstrap
event for the same flag with **different** `$feature_flag_response` values:

```sql
WITH per_person AS (
  SELECT
    person_id,
    countDistinctIf(properties.$feature_flag_response, properties.$used_bootstrap_value = true) AS bootstrap_variants,
    countDistinctIf(properties.$feature_flag_response, properties.$used_bootstrap_value != true) AS non_bootstrap_variants,
    groupUniqArrayIf(properties.$feature_flag_response, properties.$used_bootstrap_value = true) AS bootstrap_variant_keys,
    groupUniqArrayIf(properties.$feature_flag_response, properties.$used_bootstrap_value != true) AS non_bootstrap_variant_keys
  FROM events
  WHERE event = '$feature_flag_called'
    AND properties.$feature_flag = '<flag-key>'
    AND properties.$feature_flag_response != '$multiple'
    AND timestamp >= '<start_date>'
  GROUP BY person_id
)
SELECT *
FROM per_person
WHERE bootstrap_variants > 0
  AND non_bootstrap_variants > 0
  AND bootstrap_variant_keys != non_bootstrap_variant_keys
LIMIT 50
```

Non-trivial row count here distinguishes A4 from A3: A3 is identity fragmentation regardless of
source, A4 is specifically the bootstrap-vs-`/decide` mismatch. If the query returns no rows _and_
no events for the flag have `$used_bootstrap_value = true` anywhere, bootstrap is likely not in
play and A4 is unlikely — but absence isn't definitive (older SDKs may not stamp the property).
Cross-check by asking whether the user's app is server-rendered with bootstrapping enabled.

**Recommend:**

- Pass `distinctID` in the bootstrap payload when the server already knows the identity (e.g. logged-in
  users).
- Bootstrap should be used together with server-side local evaluation, not alone.

## A5 — Flag/experiment state inconsistency [HIGH]

The experiment view shows a warning banner for any of these states. Each has a specific fix:

| State                                                             | What's happening                                                                                 | Action                                                             |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| Experiment paused                                                 | Users see control during the pause window, no new exposures                                      | Resume or end                                                      |
| Flag disabled, experiment running                                 | No users are bucketed                                                                            | Re-activate the flag, or end the experiment                        |
| Flag has 100% rollout to one variant                              | No A/B comparison happening                                                                      | End the experiment with a conclusion, or fix the flag distribution |
| Flag has 0% rollout                                               | No exposure data being collected                                                                 | Increase rollout, or end the experiment                            |
| Experiment ended, flag still active and serving multiple variants | Ongoing data contamination                                                                       | Disable the flag, or resume the experiment                         |
| Experiment not launched yet, flag already active                  | Users bucketed before official start (will appear as multi-variant once the experiment launches) | Launch, or disable the flag until launch                           |

Use `managing-experiment-lifecycle` for the correct lifecycle action.

## A6 — Mid-run flag edits that rebucket already-exposed users [MEDIUM]

Any flag edit that changes the inputs to the variant hash rebuckets already-exposed users on their
next flag evaluation. Affected users flip variants and get stamped `$multiple` on subsequent flag
calls — driving up the `$multiple` share and (depending on uneven-split + `exclude`) feeding A1.
The four common shapes:

- **Variant rollout change** — e.g. taking a variant from 10% to 0%. Users who were bucketed to
  the dropped variant get re-hashed into the remaining variants. Residual `$feature_flag_response`
  values for the dropped variant in the snapshot (despite a 0% configured rollout) are the
  fingerprint.
- **Bucketing identifier change** — user-bucketing ↔ device-bucketing; or changing
  `bucketing_identifier` on the flag. All assignments are re-bucketed because the hash input
  changes.
- **Release-condition change** — adding or tightening release conditions can change which group a
  user matches, leading the rollout-percentage logic to evaluate differently. Particularly visible
  when conditions reference late-loaded person properties.
- **Variant key rename** — renaming a variant key changes the hash input space and rebuckets
  everyone. Rare but high-impact.

**Detect.** `feature-flags-activity-retrieve { id: <feature_flag_id> }` is authoritative for the
diff (the higher-fidelity activity endpoint). `advanced-activity-logs-list { scopes: ["FeatureFlag"] }` only
shows _who/when_, not _what_ — but a cluster of edits around or after `start_date` is the
fingerprint to pursue further.

**Recommend:** treat any of these like changing the variant split mid-run — anti-pattern. The
already-collected data after the edit window is contaminated by re-bucketed users. Reset and
relaunch is the cleaner fix; switching `multiple_variant_handling` to `first_seen` is the
low-disruption mid-run option (per A1).

**Note on sticky flags + device bucketing:** these have known tradeoffs. Device bucketing is designed for
initially-anonymous users and is incompatible with the standard sticky-flag pattern (which stores a flag
value as a person property — anonymous users have no profile to attach it to). If the user wants both, it
requires `person_profiles: 'always'`, which is more expensive.

## A7 — Non-randomized assignment via release conditions [MEDIUM]

If the user is using release conditions to target specific cohorts to specific variants (e.g. iOS
users see test, Android users see control), the resulting assignment is **not random**. PostHog's
statistics assume randomization, so this invalidates the standard significance interpretation.

PostHog doesn't prevent this in the UI — but the user should understand that significance calculations
are misleading in this setup.

**Verify directly.** In `experiment-get`'s response, scan
`feature_flag.filters.groups[]` for any entry where `variant` is non-null. That field is the
per-release-group variant override: any user matching that group's `properties[]` is forced to
that variant rather than being randomly bucketed. A `variant: null` (or missing field) means the
group is randomized normally and A7 doesn't apply.

When the override exists, also check whether the targeted cohort overlaps the project's
test-account exclusion list. If the cohort is _in_ the exclusion list, those users are filtered
out of the analysis and the override is mostly a no-op for the metric (they were never going to
count). If the cohort is _not_ excluded (e.g. an external partner's email domain), the override
contaminates the variant assignment for real users.

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
exposures. Two shapes observed in practice:

- **Unconditional catch-all forcing one variant.** A release group with **empty `properties[]`**
  (matches everyone) and a pinned `variant` at `rollout_percentage: 100`. Every user who doesn't match
  an earlier, narrower group falls through to it and is forced to that variant; the randomized
  `multivariate` split never applies. Observed magnitude: one arm ≈ 5.2M persons vs the other ≈ 500
  (the residual on the starved arm being leftovers from earlier flag versions).
- **"All new users" cohort forcing one variant, with no control path.** A release group like
  `created_at_unix >= <ts>` → `variant: test` at 100%, where **no release group leaves `variant: null`
  and no group forces the other variant**. Every new account is forced to `test`; the `control` arm
  stops receiving new assignments and starves over time. Observed: control collapsed from a balanced
  ~15k/month to ~2/month within weeks of the forced group being added, while test scaled into the
  millions.

**Detect (config-only, from `experiment-get`).** Enumerate `feature_flag.filters.groups[]` and for each
read `variant`, `properties` (an empty array = catch-all matching everyone), and `rollout_percentage`.
Red flags, any of:

- a group with `variant` set **and** broad/empty `properties` at high `rollout_percentage`;
- **no** group with `variant: null` — i.e. nothing is randomized at all;
- every variant-pinned group forces the **same** variant — i.e. there is no release path to the other arm.

**Confirm from exposures, and use the trend to read intent.** Run the Step 1.5 exposure-shape query —
the starved arm shows up immediately as one variant's persons being orders of magnitude below the
other. Then add a monthly breakdown (`toStartOfMonth(timestamp)`); the shape tells you what happened
and is worth pulling _before_ you characterize it:

- **Ran balanced, then one arm collapses** — both arms roughly even for a period, then one variant's
  new assignments drop toward ~0 from a specific date. The experiment ran as a real A/B and was then
  **rolled out** via the flag. The balanced window is the valid result.
- **One arm never received meaningful traffic** — the minority variant is ≈ internal pins / a trickle
  from the start, never a real share (e.g. one arm in the hundreds while the other is in the millions).
  It was served one variant from the start; it likely never ran as a randomized A/B at all.

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
**every affected person re-buckets** the next time the flag is evaluated. The flag's variant
assignment is `hash(flag_key + distinct_id)` — different input, different bucket, possible variant
flip mid-experiment.

**Recommend:**

- Finish or end the running experiment **before** the identifier migration, then start a fresh
  experiment under the new strategy.
- If they have to migrate during the run, expect inflated `$multiple` and treat the affected window
  as contaminated — use `reset` + relaunch once the migration is complete.
- An "experience continuity" / flag-persistence approach can paper over anonymous → identified
  transitions but is not a general substitute for the migration above (see A3 tradeoffs).
