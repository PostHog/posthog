# Pulling the data

Run this sequence read-only before diagnosing or asking the customer anything.
It produces the numbers you will cite back to them. This file is self-contained for the fixed
data-pull sequence: it carries the customer-support subset of the queries, the edge cases each
one needs, and the numbers each cause needs.

## 1. Config — `posthog:experiment-get`

Pull these fields; they are inputs to almost every cause:

- `parameters.feature_flag_variants[].rollout_percentage` — the configured **split**.
- `parameters.rollout_percentage` — the overall **rollout** (% of users entering the test).
- `exposure_criteria.multiple_variant_handling` — `"exclude"` (default) or `"first_seen"`.
- `exposure_criteria.exposure_config.event` — set means a **custom exposure event** (changes
  the query below); absent means the default `$feature_flag_called`.
- `exposure_criteria.filterTestAccounts` — defaults to true.
- `feature_flag.filters.groups[]` — per group read `variant`, `properties`,
  `rollout_percentage`. Any non-null `variant` is a forced assignment (not randomized).
- `feature_flag.filters.multivariate.variants[]` — the variant keys **and their stored order**;
  the offline hash-recomputation test walks them in this order, so read it from the _live_ flag.
- `feature_flag.ensure_experience_continuity` — if `true`, assignment hashes a stored override key,
  so the offline hash test is unreliable (see the decisive test below).
- `feature_flag.filters.aggregation_group_type_index` — if set, the experiment is
  **group-aggregated** (randomizes and counts groups, not persons); see the note below.
- `feature_flag.bucketing_identifier` — if `"device_id"`, the flag buckets on the **device ID**
  (`$device_id`), not `distinct_id`, so the offline recompute must hash `$device_id` (see the
  device-ID note below). Only applies to person-aggregated flags — group aggregation takes
  precedence. Absent / `"distinct_id"` is the default.
- `feature_flag.filters.holdout` — if present, a **global holdout** deterministically excludes a
  slice of users from the experiment (see the holdout note below). Cross-check with
  `posthog:experiment-holdouts-list`.
- Flag dependencies — a property of type `flag` inside `feature_flag.filters.groups[].properties`
  means this flag **depends on another flag** and fails _closed_ when the parent isn't matched (see
  the dependency note below). List dependents with `posthog:feature-flags-dependent-flags-retrieve`.
- `feature_flag.active`, status, `start_date`, `end_date`, `stats_config`.

**Group-aggregated experiments.** When `aggregation_group_type_index` is set, the flag buckets and
counts _groups_ (e.g. companies), not persons. Everywhere below that uses `person_id` as the unit,
count the group key instead (the `$group_<index>` / `$groups` value the flag aggregates on), and the
offline recompute in the [decisive test](#the-decisive-test-recompute-assignment-offline) hashes that
group key rather than `distinct_id`. Counting persons on a group-aggregated experiment overstates N
and can manufacture an SRM that isn't there.

**Device-ID bucketing.** When `feature_flag.bucketing_identifier == "device_id"`, a person-aggregated
flag hashes the **device ID** (the `$device_id` on the exposure event), not the `distinct_id` — so a
single person keeps one variant across logins, but the same person on a second device can land in the
other arm. The [decisive test](#the-decisive-test-recompute-assignment-offline) must therefore hash
`$device_id`, not `distinct_id`: hashing `distinct_id` makes correctly-assigned users look like
disagreements and misreads a capture-side SRM as assignment-side. Production falls back to
`distinct_id` when `$device_id` is empty, so export `coalesce(nullIf($device_id, ''), distinct_id)` to
mirror it. Group aggregation takes precedence over this (a group flag hashes the group key).

**Holdouts.** A global holdout deterministically excludes a slice of users (hashed separately with a
`holdout-` prefix) from the experiment; those users are recorded with a `holdout-<id>` response, not
`control`/`test`. Because the holdout hash is independent of the variant hash, it removes users
**evenly from both arms** — so it lowers the analyzable N but does _not_ create a directional SRM.
When the customer says "fewer users than I expected," a holdout is a common benign answer: count the
`holdout-<id>` bucket in the §3 breakdown against the shortfall before hunting for a bug.

**Flag dependencies.** A flag can gate on another flag via a property of type `flag` in its release
conditions. Dependencies **fail closed**: a user who doesn't match the parent evaluates to `false`
(no variant) rather than being randomized. So a dependency can both _shrink_ a population (users drop
to `false`) and _skew_ it if the parent's own rollout correlates with anything. Detect with
`posthog:feature-flags-dependent-flags-retrieve` or the type-`flag` property in `filters.groups[]`; the fix
(widen/align the parent, or drop the dependency) is in the customer's flag config.

## 2. Metrics + exposure totals — `posthog:experiment-results-get`

Returns per-variant exposure totals and metric results in one call:

- `exposures.total_exposures[variant]` — including the `$multiple` bucket (users exposed to
  more than one variant). **`$multiple` share = `total_exposures["$multiple"] / sum(all)`.**
- `exposures.timeseries[]` — daily `exposure_counts` per variant, for trajectory/flat-tail.
- `metrics.primary.results[]` / `metrics.secondary.results[]` — each row carries `index`, a `metric`
  summary, and `data` (the primary/secondary object itself also has a `count`); a `data: null` row is
  failed-or-not-yet-computed, not necessarily broken. PostHog precomputes results on a schedule, so a
  recently launched or edited experiment returns `data: null` placeholders that fill in on their own;
  transient query load produces the same shape. Disambiguate transient from a real failure before you
  report it: re-pull the cached results a while later, or force one recompute with
  `posthog:experiment-results-get { refresh: true }`. If the rows then populate, the earlier nulls
  were transient. If a row stays `null` after a successful force-refresh, that metric genuinely fails
  to compute — inspect its definition (a `mean` metric over a missing property, a zero baseline, or a
  malformed funnel). A large null count on its own is not severity: an experiment with many secondary
  metrics shows the most warming placeholders, and they clear.

## 3. Exposure shape — `posthog:execute-sql`

Default exposure event:

```sql
SELECT
  properties.$feature_flag_response AS variant,
  count() AS exposure_events,
  count(DISTINCT person_id) AS persons,
  count(DISTINCT distinct_id) AS distinct_ids,
  min(timestamp) AS first_seen,
  max(timestamp) AS last_seen
FROM events
WHERE event = '$feature_flag_called'
  AND properties.$feature_flag = '<flag-key>'
  AND timestamp >= '<start_date>'
GROUP BY variant
ORDER BY exposure_events DESC
```

**`exposure_events` is not the SRM input.** It counts raw `$feature_flag_called` events, and one
user fires as many as their app evaluates the flag — a variant that re-renders or adds a route reads
it more often, so the event ratio drifts from the person ratio with nothing wrong. Use this column
for volume and liveness (is anything arriving, has one arm gone quiet), and take the SRM counts from
§2's `total_exposures`, which is already one row per person. See the chi-squared section in §4.

If `exposure_criteria.exposure_config.event` is set, adjust the query above: filter on the custom
event instead of `$feature_flag_called`, and read the variant from `properties.$feature/<flag-key>`
instead of `$feature_flag_response`. A custom exposure event does not carry `$feature_flag` or
`$feature_flag_response` — the SDK stamps `$feature/<flag-key>` onto the event instead — so querying
it with `$feature_flag_response` returns zero rows even when capture is healthy.

A `holdout-<id>` row (if the experiment has a holdout) is expected and correctly excluded from the
control/test split — its count is the size of the holdout, useful for explaining a population
shortfall (see the holdout note in §1).

Ignore `$feature_flag_response = false / None / null` rows: `$feature_flag_called` fires on
every evaluation, including users who didn't bucket into the test. They aren't a balance
signal (PostHog's own analysis filters them out). The exception is when _every_ row is
`None`/`false` — that's a missing-exposures symptom (a flag dependency failing closed lands users
here too). **Second exception — a capture-side SRM:**
when one arm is short, this bucket's _volume_ (broken down by `$lib`/surface, and checked against
the short-arm gap) can be the mechanism rather than noise — users who read the flag before it
loaded get `false`/`undefined` and are dropped from their arm instead of showing up wrong. The
[SRM localization](#localizing-a-confirmed-srm-assignment-vs-capture) queries below quantify it.

## 4. The numbers each cause needs

| Cause                                     | The number that confirms it                                                                                                                        |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Uneven split + Exclude bias               | uneven `rollout_percentage` split **and** `$multiple` share > 0.1% (banner threshold), handling = `exclude`                                        |
| Sample ratio mismatch                     | chi-squared p < 0.001 on §2's per-person `total_exposures` (see below); only meaningful once totals are healthy                                    |
| Assignment override (assignment-side SRM) | the reassignment component carries the gap in the decisive test below; then localize with the SDK split / bootstrap mix below                      |
| Capture-by-surface (capture-side SRM)     | a `$pathname`/`$screen_name` where one variant's share jumps to ~100% while other paths sit near the split                                         |
| Flag read before load (capture-side SRM)  | `false`/`null` person count near the short-arm gap and concentrated on that arm's `$lib`/surface                                                   |
| Pre-launch skew                           | the same directional skew _before_ `start_date` ⇒ points at assignment, not capture                                                                |
| Bootstrap-inherited variant               | `$used_bootstrap_value = true` concentrated on the heavier arm                                                                                     |
| Identity fragmentation                    | `distinct_ids / persons` > ~1.2 for a variant, or persons under multiple variants                                                                  |
| No randomization / forced variant         | a `feature_flag.filters.groups[]` entry with non-null `variant` + broad `properties`                                                               |
| Mid-run rebucketing                       | residual exposures for a 0%-configured variant + a flag `filters` diff after `start_date`                                                          |
| Missing exposures                         | total exposures ~0, or a variant `last_seen` days behind the other, or a flat timeseries tail                                                      |
| Test-account exclusion                    | count of exposures matching the project's test-account filter                                                                                      |
| Holdout population loss                   | size of the `holdout-<id>` bucket vs the expected-minus-actual N (removes users evenly, no directional SRM)                                        |
| Flag dependency (fail-closed)             | `false` responses concentrated on users failing a type-`flag` release condition; `posthog:feature-flags-dependent-flags-retrieve` names the parent |
| Capture disabled                          | exposures ~0 while the flag is demonstrably read — `send_feature_flag_events`/events-off in the SDK config, not a wrong accessor                   |

### Sample ratio mismatch (SRM) — chi-squared

**Count people, not events.** The unit is one row per person at first exposure — take `Oᵢ` from §2's
`exposures.total_exposures[variant]`, which the product already collapses per person, _not_ from
§3's `exposure_events`. The test assumes each user is one independent draw from the split; raw
`$feature_flag_called` counts break that, because events-per-user varies by arm. Running χ² on event
counts inflates it and manufactures an SRM on a perfectly balanced experiment — which then sends the
decisive test below to ~100% agreement and the diagnosis off hunting a capture-side surface split
that was never there. On a group-aggregated experiment the unit is the group key, not the person
(see §1).

Compare those observed counts to the configured split. For observed counts `Oᵢ` with total
`N` and configured proportions `pᵢ`, expected `Eᵢ = N·pᵢ`, and
`χ² = Σ (Oᵢ − Eᵢ)² / Eᵢ` with `k − 1` degrees of freedom. Flag SRM only at **p < 0.001**.
Don't call SRM below ~1,000 exposed persons/variant — small-sample variance dominates. Exclude the
`$multiple` bucket from this test (it isn't a variant). For a two-variant split the equivalent
z-test is `z = (O₁ − E₁) / sqrt(N·p₁·(1−p₁))`; |z| ≳ 6 is the ~4.7e-11 range and unmistakable.
**Multivariate (3+ arms):** the chi-squared test above already generalizes (`k − 1` d.o.f.), and
`srm_check.py` and every localization query below take N variant keys — the two-arm z-test is just
shorthand. With 3+ arms, read _which_ arm carries the χ² by comparing each `(Oᵢ − Eᵢ)² / Eᵢ` term,
then localize that arm.

**Back-check the split you're testing against.** PostHog's SRM check reads the expected
proportions from the _live_ flag's `multivariate.variants`, not a stored copy on the experiment.
If in doubt, ask which configured split reproduces the observed p — only one will (e.g.
832 vs 1,123 gives p ≈ 4.7e-11 under 50/50, but p ≈ 0.03 under 45/55 and no SRM at all under
43/57). Matching the p pins down the split the customer is actually running.

### Localizing a confirmed SRM (assignment vs capture)

Run these only _after_ SRM is confirmed. First run the **decisive test** below to pick the half,
then run the matching queries: a **capture** verdict sends you to the surface / dropped-`false` /
SDK queries, an **assignment** verdict to the SDK / bootstrap queries. All queries
collapse to one row per person at first exposure, mirroring the product; substitute the two real
variant keys. They assume the default exposure event — for a custom exposure event, swap the event
filter and read the variant from `properties.$feature/<flag-key>` instead (as in §3), and for a
group-aggregated flag count the group key rather than `person_id` (see §1).

#### The decisive test: recompute assignment offline

Recompute each user's variant from the flag hash, then split the gap between the **recorded** split
and the **configured** split into the only two places it can come from. For each variant, over a
sample of `n` identifiers, with `expected = n × configured share`:

```text
recorded − expected  =  (predicted − expected)  +  (recorded − predicted)
  the observed gap        selection component       reassignment component
                          ⇒ CAPTURE-side            ⇒ ASSIGNMENT-side
```

That's an identity, not a heuristic — the two components always sum to the gap. `predicted` is the
hash-recomputed variant, so:

- **Selection carries the gap** ⇒ the users who got _recorded_ were already a skewed draw before
  assignment is even considered — **capture-side**. Localize with the surface / dropped-`false` /
  SDK queries below.
- **Reassignment carries the gap** ⇒ something overrode assignment at serve time — **assignment-side**.
  Localize with the SDK / bootstrap queries below; suspect stale local-eval, an inherited bootstrap
  value, a forced release-condition variant, or a mid-run rehash.

**Don't route on the raw agreement percentage.** A handful of scattered disagreements can't produce a
_directional_ SRM, so agreement alone doesn't separate the halves: a large capture-side skew sitting
under ~2% of unrelated override noise reads as "98% agreement" and looks assignment-side, when
selection is carrying the entire gap. The share of the gap each component explains is the number that
routes; `srm_check.py` prints both, each with its own significance test, and refuses to name a side
when neither dominates.

**The algorithm** — verified byte-exact against PostHog's implementation in
`rust/feature-flags/src/flags/flag_matching.rs` (`get_matching_variant`) and `flag_matching_utils.rs`
(`calculate_hash`). Don't eyeball it — the salt is easy to get wrong:

1. `hash_key = f"{flag_key}.{identifier}variant"` — note the `.` after the key **and** the literal
   `variant` salt. (The plain rollout gate hashes with an _empty_ salt; the variant walk uses
   `"variant"`. Using the wrong salt is the classic reimplementation bug.) `identifier` is the
   `distinct_id` by default — the **group key** when the flag is group-aggregated, or the **device
   ID** (`$device_id`) when `feature_flag.bucketing_identifier == "device_id"` (see §1). Hashing the
   wrong one inverts the verdict.
2. `h = int(sha1(hash_key).hexdigest()[:15], 16) / 0xfffffffffffffff` — a float in `[0, 1)`.
3. Walk `filters.multivariate.variants` **in stored order**, accumulating `rollout_percentage / 100`
   into a cumulative bound; the first variant with `h < cumulative` is the assigned variant.

Don't hand-run this — the bundled [`srm_check.py`](../scripts/srm_check.py) implements it.
`--selftest` replays the repo's golden hash vectors first, so you confirm the reimplementation
matches this build before trusting a verdict:

Save the flag's `filters.multivariate.variants` array to a file and pass the path — that preserves
stored order and keeps the variant keys out of the shell:

```bash
./srm_check.py --selftest
./srm_check.py --flag-key <flag-key> --variants-file variants.json --csv exposures.csv
```

**Never interpolate variant keys into the command line.** Variant keys are charset-validated in the
PostHog UI but _not_ by the API, so a key on a flag that reached you through a ticket can contain
shell metacharacters or quote characters. `--variants-file` reads them as JSON, so they stay data.
The `--variants control=50,test=50` form is a convenience for keys you have already read and
eyeballed; don't build it by substituting values you haven't looked at.

**Constraints:**

- **Not pure SQL.** SHA1 isn't in HogQL's whitelist, so this runs outside the database. Export the
  sample below and feed it to the script; a deterministic `cityHash64` sample of 800 gives SE ~1.8pp,
  enough to separate 50/50 from 57/43. `distinct_id`s are often emails — keep them customer-side.
- **Order- and split-sensitive.** The walk depends on the exact array order and percentages in the
  _live_ flag's `filters.multivariate.variants`; a wrong order silently inverts the prediction. Pass
  them to `--variants` in stored order.
- **Population must match the SRM.** The SRM is computed per _person_ with the `$multiple` bucket
  excluded, so the export restricts to that same analyzable population — otherwise the agreement rate
  describes a different set of users than the gap you're explaining. Under `first_seen` handling no
  one is excluded, so drop the `IN (SELECT ...)` filter. The excluded `$multiple` persons are a
  finding in their own right, not a rounding error: size them from §2's `total_exposures`, since a
  large bucket on an uneven split is the bias-banner cause.
- **Ambiguous identifiers are evidence, not noise.** `variants_seen > 1` marks an identifier that
  recorded more than one variant over time — the mid-run-rehash and bootstrap-inheritance signature.
  Collapsing it with `argMin` would keep the earliest row and hide the disagreement entirely, so the
  export carries the count and the script reports it separately instead of averaging it away.
- **Per-identifier weighting.** One person with several `distinct_id`s contributes several rows, so
  fragmented persons are upweighted relative to the per-person SRM. Cross-check against the
  `distinct_ids / persons` ratio from §3 — well above 1 means the agreement rate is identifier-weighted
  and the sample is not a clean stand-in for the person-level population.
- **Identifier must match production.** The recompute is only valid if you hash the identifier
  production hashed — the **group key** for group flags, `$device_id` for device-bucketed flags
  (`bucketing_identifier == "device_id"`), otherwise `distinct_id` (see §1). Hash the wrong one and
  correctly-assigned users read as disagreements, so a clean assignment looks assignment-side. The
  script guards the worst case: agreement that can't beat the rate a coin flip would reach on this
  split (50% on 50/50) means the recompute carries no signal at all, and it reports the test as
  inapplicable rather than blaming assignment. A subtler mismatch still slips through — sanity
  guard: if agreement is far below 100% _everywhere_ — including a slice you already know is balanced,
  or the pre-launch window — suspect a wrong identifier (or continuity, below) before concluding
  assignment-side.
- **Experience continuity.** If `ensure_experience_continuity = true`, assignment hashes a stored
  override key you can't reconstruct from the identifier, so this test is unreliable — skip it and
  lean on the capture-side checks plus the activity log.

```sql
-- Deterministic sample for the offline recompute (n=800 → SE ~1.8pp; drop LIMIT for all rows).
-- One row per hashed identifier, restricted to the SRM-analyzable population so the agreement
-- rate describes the same users the SRM gap is computed over.
-- Custom exposure event: filter that event and read the variant from properties.$feature/<flag-key>.
-- Group-aggregated flag: export the group key instead of distinct_id, and group person_variant by it.
-- Device-ID bucketing (bucketing_identifier == "device_id"): select
--   coalesce(nullIf(properties.$device_id, ''), distinct_id) AS distinct_id instead — production
--   hashed the device id, so hashing distinct_id would fabricate disagreements.
WITH person_variants AS (
    SELECT person_id,
           -- Mirrors multiple_variant_handling = 'exclude' (the default).
           -- For 'first_seen': argMin(properties.$feature_flag_response, timestamp)
           if(uniqExact(properties.$feature_flag_response) > 1, '$multiple',
              any(properties.$feature_flag_response)) AS variant
    FROM events
    WHERE event = '$feature_flag_called'
      AND properties.$feature_flag = '<flag-key>'
      AND properties.$feature_flag_response IN ('<variant_a>', '<variant_b>')
      AND timestamp >= '<start_date>'
    GROUP BY person_id
)
SELECT distinct_id,
       argMin(properties.$feature_flag_response, timestamp) AS recorded_variant,
       uniqExact(properties.$feature_flag_response) AS variants_seen
FROM events
WHERE event = '$feature_flag_called'
  AND properties.$feature_flag = '<flag-key>'
  AND properties.$feature_flag_response IN ('<variant_a>', '<variant_b>')
  AND timestamp >= '<start_date>'
  -- Drop this filter under 'first seen' handling, which excludes no one.
  AND person_id IN (SELECT person_id FROM person_variants WHERE variant != '$multiple')
GROUP BY distinct_id
ORDER BY cityHash64(distinct_id)
LIMIT 800
```

#### Localization queries

**Daily first-exposure ratio** — flat = standing/structural bias; a step change on one day = a
change made then (cross-check `posthog:feature-flags-activity-retrieve` for that date).

```sql
WITH first_exposures AS (
    SELECT person_id,
           if(uniqExact(properties.$feature_flag_response) > 1, '$multiple',
              any(properties.$feature_flag_response)) AS variant,
           toDate(min(timestamp)) AS first_day
    FROM events
    WHERE event = '$feature_flag_called'
      AND properties.$feature_flag = '<flag-key>'
      AND properties.$feature_flag_response IN ('<variant_a>', '<variant_b>')
      AND timestamp >= '<start_date>'
    GROUP BY person_id
)
SELECT first_day,
       countIf(variant = '<variant_a>') AS a,
       countIf(variant = '<variant_b>') AS b,
       round(countIf(variant = '<variant_a>') / greatest(countIf(variant = '<variant_b>'), 1), 3) AS a_over_b
FROM first_exposures
GROUP BY first_day
ORDER BY first_day
```

_Pre-launch variant:_ rerun with `timestamp` bounded to the window **before** `start_date` (and
without the `IN (...)` filter, so `false`/`null` show). If the flag was live pre-launch and the
same directional skew is already present — before anyone saw the new UX — the cause is
**assignment**, not capture.

**First-exposure surface split (capture-by-surface).** Some paths ~50% and others ~100% one
variant ⇒ that arm reaches a surface the other can't. Swap `$pathname` for `$current_url` if too
coarse, or `$screen_name` for native apps.

```sql
WITH first_exposure AS (
    SELECT person_id,
           argMin(properties.$feature_flag_response, timestamp) AS variant,
           argMin(properties.$pathname, timestamp) AS first_path
    FROM events
    WHERE event = '$feature_flag_called'
      AND properties.$feature_flag = '<flag-key>'
      AND properties.$feature_flag_response IN ('<variant_a>', '<variant_b>')
      AND timestamp >= '<start_date>'
    GROUP BY person_id
)
SELECT coalesce(first_path, '(none)') AS path,
       countIf(variant = '<variant_a>') AS a,
       countIf(variant = '<variant_b>') AS b,
       count() AS total,
       round(countIf(variant = '<variant_a>') / count() * 100, 1) AS pct_a
FROM first_exposure
GROUP BY path
ORDER BY total DESC
LIMIT 40
```

**Dropped `false`/`null` bucket by SDK.** If a variant is short by ~N persons and the `false`/`null`
person count is near N and concentrated on one `$lib`/surface, flag-read timing is the lead.

```sql
SELECT coalesce(toString(properties.$feature_flag_response), 'null') AS response,
       coalesce(properties.$lib, '(none)') AS lib,
       count() AS exposure_events,
       count(DISTINCT person_id) AS persons
FROM events
WHERE event = '$feature_flag_called'
  AND properties.$feature_flag = '<flag-key>'
  AND timestamp >= '<start_date>'
GROUP BY response, lib
ORDER BY exposure_events DESC
LIMIT 30
```

**SDK split** — a server SDK on a stale local-eval definition shows as a skewed server row
(`$lib` = `posthog-python`/`-node`/`-ruby`/`-go`/`-php`) beside a clean web row. Group the
first-exposure variant by `$lib` / `$lib_version`.

**Bootstrap / local-eval mix per variant** — group the exposure rows by
`properties.$used_bootstrap_value` and `properties.locally_evaluated`. `$used_bootstrap_value =
true` concentrated on the heavier arm is the signature of a bootstrap value inherited onto a fresh
`distinct_id` instead of being hashed (an assignment-side cause; see `bias-and-skew.md` A4).

### Query gotchas

- **Timezone.** HogQL compares `timestamp` in the **project timezone**, not UTC. A launch bound
  written as UTC can be off by the project's offset (e.g. an hour on Europe/London) — verify the
  total exposures the query returns matches `posthog:experiment-results-get` before trusting any slice.
- **Property access.** If the parser rejects `properties.$feature_flag`, use
  `properties['$feature_flag']`.
- **Escape every value you substitute into a placeholder.** `<flag-key>`, `<variant_a>`,
  `<start_date>` and any `distinct_id` land inside single-quoted SQL literals, and
  `posthog:execute-sql` takes no bound parameters — so a value carrying a `'` closes the literal
  early and the rest is parsed as SQL. `distinct_id`s are whatever the SDK sent, and variant keys
  are charset-validated only in the UI, so neither is safe to paste raw. HogQL escapes a quote as
  `\'` and a backslash as `\\` inside a literal; apply that to the value before substituting. A
  `distinct_id` like `x' OR 1=1 --` otherwise silently widens the predicate to every user in the
  project and you diagnose against the wrong rows.
- **Attributing edits.** The `posthog:advanced-activity-logs-list` "feature flag updated" row does **not**
  carry the flag key — use `posthog:feature-flags-activity-retrieve { id: <feature_flag_id> }` for the
  field-level diff when you need to prove _which_ flag changed.

## 5. Change history

- **`posthog:feature-flags-activity-retrieve { id: <feature_flag_id> }`** — flag edits with
  field-level diffs. Most "why did the numbers change?" surprises are a variant/rollout/
  condition change visible here.
- **`posthog:advanced-activity-logs-list { scopes: ["Experiment"], item_ids: [<experiment_id>] }`** —
  experiment-level timeline (who/when; no change diff, so use it for _when_, not _what_).

## Handing off

If a number disproves a cause, drop it; if it confirms one, lead the reply with that evidence.
Convert every internal number to the customer's language before quoting it — see
[customer-reply.md](customer-reply.md).
