# Surprises after mid-run changes (incl. lifecycle and retention quirks)

Anything that changed _after_ the experiment was launched, plus the retention-metric and long-term
quirks that produce unexpected counts even without an explicit change.

## Contents

- E1 — Increasing rollout (safe)
- E2 — Decreasing rollout (caution)
- E3 — Changing the variant split (anti-pattern)
- E4 — Adding/removing variants (blocked, but historical traces)
- E5 — Changing exposure criteria mid-run
- E6 — Adding metrics mid-run (p-hacking)
- E7 — "Ending" / "shipping a variant" rewrites the flag
- E8 — Reset clears results, not the flag
- E9 — Pause forces control on existing test users
- E10 — Retention metric: start event must occur after exposure
- E11 — "Matured users" filtering
- E12 — Long-term vs short-term metric divergence
- E13 — Editability locks (legacy experiments, ended experiments)
- E14 — Flag cleanup is limited after the experiment is archived
- E15 — Restarting an experiment with new variants

## E1 — Increasing rollout (safe) [HIGH]

No users switch variants; new users are added cleanly. Generally the only change safe to make on a
running experiment.

## E2 — Decreasing rollout (caution) [MEDIUM]

Users currently in a test variant who fall outside the new rollout will switch back to the default
experience (if they stay active of course). This is a visible UX disruption — the feature they had disappears.

Their data also becomes
harder to interpret statistically. Their prior exposures _stay counted_ against
the test variant in the analysis. The numerator and denominator already include them. Reducing
rollout doesn't retroactively un-bucket; it only stops new exposures and flips re-evaluations. The
metric reading after a rollback mixes "pre-rollback test behavior" with "post-rollback default
behavior" for the same users — which is what makes it harder to interpret, not a loss of data.

**Recommend:** if the user wants to reduce rollout to _contain blast radius_ on a problem variant, rather end
the experiment instead — that removes the variant cleanly and locks the result. If they
genuinely want to shrink exposure while keeping the experiment alive, treat metric readings from
the rollback window onward as mixed and discount them when drawing conclusions.

## E3 — Changing the variant split (anti-pattern) [HIGH]

Moves bucket boundaries; users may be reassigned between variants. Creates `$multiple` users, who then
get excluded (default) or attributed to first-seen. Either way, introduces bias.

**Recommend:** reset the experiment if early; end and start a new one if significant data exists.

**Related shape — the flag's split at launch isn't what the user thinks.** When a user reports
"one variant has no traffic at all" or "the split doesn't match what I configured", the cause is
sometimes not a _mid-run_ change but a _pre-launch_ edit that wasn't visible from the experiment
view.

**Verify directly.** `feature-flags-activity-retrieve { id: <feature_flag_id> }` returns the full
edit history with diffs. Scan `results[].detail.changes[]` for `field == "filters"` entries and
read the last `multivariate.variants[]` `before`/`after` pair _before_ the entry where
`field == "active"` flips `false → true` (the activation event). That value is the split the
experiment actually launched with. If it doesn't match `parameters.feature_flag_variants` as the
user described setting it, the launch state itself is the cause — no mid-run change is needed to
explain the missing-variant data.

Fix path: same as E3 generally — reset + relaunch on a young experiment with little data; end +
relaunch on one with significant accumulated data. Set the flag's variants to the intended split
_before_ clicking launch on the relaunch.

## E4 — Adding/removing variants (blocked, but historical traces) [HIGH]

PostHog blocks adding/removing variants on running experiments. If the user managed to do it
earlier (or directly via the flag UI before the block was in place), expect `$multiple` exposures
in the data.

**Recommend:** treat the post-change window as contaminated. Reset (E8) and relaunch if the
contamination dominates the run, or end + start a new experiment with a fresh flag (E15) if
significant clean data exists from before the change.

## E5 — Changing exposure criteria mid-run [HIGH]

Edits to exposure criteria after launch can produce surprises — exposure event swap, multivariate
handling change, or test-account filter toggle all change _which_ events count. Two specific cases:

- Switching `multiple_variant_handling` from `exclude` → `first_seen` mid-run is the **low-disruption
  way to mitigate uneven-split exclusion bias** on already-collected data. No users switch variants;
  all data stays.
- Other exposure-criteria changes re-process historical exposures under the new criteria, which can
  shift numbers without any actual change in user behavior. Communicate this to the user before they
  panic.

If the user is also changing how `distinct_id` is sent (e.g. anonymous → identified, email → user
ID), that's a different shape — see `bias-and-skew.md` A8. Identifier migration mid-run re-buckets
users; exposure-criteria edits don't.

## E6 — Adding metrics mid-run (p-hacking) [MEDIUM]

Choosing what to measure _after_ seeing data biases your results. Each additional metric is another
result to interpret, and with no multiple-comparisons correction (see `interpretation.md`), the chance
of _some_ metric looking significant by chance grows.

If the user is hunting for a significant metric after the fact, that's p-hacking — not a real result.

**Note:** retroactive metric _addition_ is technically supported (the metric is calculated for the full
experiment duration), but using it to fish for significance is a methodology problem, not a tool
limitation.

## E7 — "Ending" / "shipping a variant" rewrites the flag [HIGH]

Shipping a variant rewrites the linked feature flag's variant distribution: the chosen variant
gets 100% of the variant distribution, every other variant goes to 0%. The flow has two release
modes — pick carefully:

- **Roll out to the experiment population (default, recommended).** Existing release conditions on
  the flag are preserved untouched. The chosen variant is served only to users who already match
  those conditions, and per-user variant overrides continue to apply. No catch-all release
  condition is added.
- **Roll out to all users (explicit opt-in).** In addition to the variant-distribution flip,
  a catch-all release condition is _prepended_ to the flag's release groups with the literal
  description _"Added automatically when the experiment was ended to keep only one variant."_ This
  overrides existing release conditions and bypasses per-user variant overrides — anyone hitting
  the flag now gets the chosen variant.

Both modes flip the active variant ratio to e.g. 0/100 and mint a new flag version. The catch-all
release condition is the discriminator between modes.

**If the flag distribution suddenly flipped after a metric edit or end action**: this is the most
likely cause. Check the experiment's recent edits and any `ship_variant` calls. Recover by
adjusting the flag's release conditions back to the experiment split, or by resetting + relaunching
the experiment.

**Verify directly.** Call `feature-flags-activity-retrieve { id: <feature_flag_id>, limit, page }`.
Scan `results[].detail.changes[]` for `field == "filters"`:

- A `multivariate.variants[]` diff showing the rollout flip (typical signature: 50/50 → 0/100), and
  a separate `field == "version"` bump → E7 is confirmed.
- Additionally, look inside `after.groups[].properties[].description` for the literal string
  _"Added automatically when the experiment was ended to keep only one variant."_ If present, this
  was a **"roll out to all users"** ship and the new release condition overrides the flag's prior
  targeting and per-user overrides. If absent (release groups unchanged), this was a **"roll out to
  the experiment population"** ship — the variant distribution flipped but targeting is intact.

The MCP tool that performs this rewrite is `experiment-ship-variant`. It takes
`release_to_everyone: bool` (defaults to `false` = "roll out to the experiment population"); the
agent should confirm the release mode with the user before invoking, in addition to the variant key.

Note: `advanced-activity-logs-list { scopes: ["Experiment"], item_ids: [<id>] }` will _not_ tell you this — that
endpoint returns `activity: "updated"` with no change diff. Use the `feature-flags-activity-retrieve` tool.

**Default to control on ambiguous ships.** If the user is unsure which variant to ship — primary
unclear, secondaries mixed, or they're still investigating — recommend shipping **control**.
Accidentally rolling out control is a no-op; accidentally rolling out a test variant flips the
variant distribution to a not-validated change. If the user _also_ picks "roll out to all users",
the blast radius extends past the experiment's existing population — discourage this combination
when the user sounds uncertain.

## E8 — Reset clears results, not the flag [HIGH]

Reset returns the experiment to draft and clears `start_date`, `end_date`, `conclusion`, `archived`.
**Events already captured still exist** but won't be applied to the experiment unless `start_date` is
set appropriately after relaunching. The feature flag is left untouched — users continue seeing their
assigned variants during the reset window.

**Use case:** suspected bias in the existing data, and the user wants to start a clean comparison.
Reset + adjust + relaunch is the right path.

## E9 — Pause forces control on existing test users [HIGH]

Pause sets the flag's `active=false`. The flag stops returning a variant via `/decide`, so users fall
back to the application default — typically control. Test users effectively switch back to control
during the pause window. No new exposure events fire while paused.

**Implication:** if the user paused and then resumed, the test variant population had a window of
control-like behavior. Their data during the pause is mixed.

**Recommend:** when interpreting results that span a pause window, surface the pause dates from
the activity log (`advanced-activity-logs-list { scopes: ["Experiment"], item_ids: [<id>] }`) and explain that the
metric data during that window mixes test-variant users with control-like behavior. If the pause
was long relative to the run, consider reset + relaunch over interpreting the contaminated data.

## E10 — Retention metric: start event must occur after exposure [HIGH]

PostHog's retention metric for experiments requires the **start event to occur after the user's
first exposure**. This
is the same design as all other metric types — the analysis question is "what is the effect of this
feature _after_ a user sees it?"

**`start_handling` (`FIRST_SEEN` vs `LAST_SEEN`) does _not_ relax this.** It only picks _which_
post-exposure start event anchors the retention window when a user has multiple: `FIRST_SEEN` uses
`min(timestamp)`, `LAST_SEEN` uses `max(timestamp)` — but both are computed over events already
filtered to `timestamp >= first_exposure_time`. Pre-exposure start events are dropped before the
min/max ever runs.

<!-- Source for maintainers: _build_start_after_exposure_predicate and
_build_start_event_timestamp_expr in posthog/hogql_queries/experiments/experiment_query_builder.py. The CTE INNER JOINs on start_events, so users with
only pre-exposure start events are excluded entirely. -->

An alternate question — "does this feature change the standard _pre-anchored_ retention metric?",
where the start event can be before exposure — isn't supported on experiments. The workaround is to
track that metric separately in product analytics.

**If retention undercounts unexpectedly:** confirm that the start event has post-exposure
occurrences for the affected users. Users whose only start events are pre-exposure are excluded
entirely — they don't appear in the retention denominator.

## E11 — "Matured users" filtering [HIGH]

Some metrics now support a "Only count matured users" toggle — users whose exposure was at least N days
ago. Useful for retention/long-term metrics where freshly-exposed users haven't had time to convert
yet.

**Implication:** turning this on **reduces** the user count in the analysis (recent users excluded) but
makes per-user metric values more comparable across cohorts. If the user count drops unexpectedly,
check whether this toggle is enabled.

## E12 — Long-term vs short-term metric divergence [MEDIUM]

Primary (short-term) and secondary (long-term) metrics moving in different directions is **normal** —
a checkout-flow change might lift conversion now but hurt retention later.

**Recommend:**

- Keep the short-term metric as primary and long-term as secondary — don't promote long-term to primary
  just because it disagrees.
- Use **holdouts** for sustained measurement; compare outcomes over time across the holdout vs the
  rolled-out cohort.
- For deeper segment analysis, click "Explore results" → filter the funnel/trend by segment, or use
  session replays to see what behavior differs between variants.

## E13 — Editability locks (legacy experiments, ended experiments) [HIGH]

- **Legacy experiments** (created before the new query runner) — metrics can no longer be edited.
  A "This is a legacy experiment" notice appears in the UI. Duplicate the experiment to get it onto
  the new engine.
- **Ended experiments** — variant keys, exposure criteria, and traffic split can't be edited. If
  edits are needed, clone, or reset (E8) and re-launch.

If the user is fighting an editability lock, that's a sign the experiment should be cloned or reset
rather than worked around.

**Legacy fingerprint in `experiment-results-get`.** A common downstream symptom of the legacy-experiment
case is that the metric line is rendered but the per-variant result block is empty — `metrics.primary.count`
is non-zero, but the entry under `results[]` has no `chance_to_win`, no `credible_interval`, no
`significant`, no `step_counts`. Exposures are fully populated; only the metric output is missing.

Don't confuse this with a `data: null` row on a **non-legacy** experiment — that's usually transient
(precompute not yet landed, or load at snapshot time) and resolves on re-pull / force-refresh. See
"Reading metric result rows (`data: null`)" in `diagnostic-snapshot.md` to disambiguate before
concluding anything. The legacy fingerprint here is specifically an experiment with `is_legacy: true`
whose result block stays empty even after a force-refresh.

**Verify directly** (no interview needed). In `experiment-get`'s response:

- `metrics[].kind == "ExperimentFunnelsQuery"` or `"ExperimentTrendsQuery"` (not `"ExperimentMetric"`)
  — these are the legacy metric kinds.
- `filters.migrated_at` is set — the experiment was migrated from the pre-new-runner schema.
- `stats_config` is empty / missing the `method` field — new-runner experiments carry
  `stats_config.method: bayesian` (or `frequentist`).

When all three line up, the verdict is legacy methodology, not data corruption. Resaving the
metric on the legacy experiment is not supported.

Fix path: **duplicate the experiment** to land it on the new runner (the new copy will carry the
new metric kind and a populated `stats_config`); recreate the primary metric there; relaunch.
Alternatively, end the existing experiment with a documented conclusion if the original
hypothesis is no longer interesting — the legacy run can't be salvaged in place.

## E14 — Flag cleanup is limited after the experiment is archived [HIGH]

Once an experiment is archived, the feature flag stays bound to it:

- The flag cannot be converted back to a boolean.
- The flag cannot be unlinked from the archived experiment.
- The flag cannot be deleted while the link exists.

This forces either a code change (read a different flag going forward) or a new flag for follow-up
rollouts. There is no quick fix in the UI.

**Recommend:** before archiving, confirm the flag's future use. If the user expects to keep using
the flag for general rollout after the experiment ends, ship the variant (E7) rather than archive
— that leaves the flag in a usable state at the chosen rollout. If they're done with the flag too,
keep both the experiment and the flag intact until the calling code has been removed.

## E15 — Restarting an experiment with new variants [MEDIUM]

The "restart with different variants" pattern doesn't have a built-in flow. The clean approach is:

1. **End** the existing experiment (don't reset — reset reuses the same flag and prior `$multiple`
   exposures contaminate the new run).
2. **Clone** the experiment, or create a new one.
3. **Create a new feature flag** rather than reusing the previous one — this avoids inheriting
   cached `$feature_flag_called` events from users who saw the prior variants.
4. Launch the new experiment under the new flag.

Reusing the same flag with new variants on a new experiment is technically possible but tends to
produce confusing exposure histories and prior-variant attribution in the metric data. Only do this
if the user is explicit about wanting to keep historical bucketing comparable.
