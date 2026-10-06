# Surprises after mid-run changes (incl. lifecycle and retention quirks)

Anything that changed _after_ the experiment was launched, plus the retention-metric and long-term
quirks that produce unexpected counts even without an explicit change.

**Find the change first.** `experiment-activity` lists what changed on the experiment and on its flag, with the values before and after and the time (see "Changes after launch" in `diagnostic-snapshot.md`).
The flag's changes are in that list only when the caller has access to the flag: a list without any flag entry is no evidence that the flag did not change.
Most entries below start from one row of that list.

**An interruption can bias the result.**
Pausing, freezing, unfreezing and resuming all change who gets the variant, or when, while the analysis keeps treating the run as one continuous window.
Say so whenever the history shows one: E9 for pause and resume, E16 for freeze and unfreeze.

## Contents

- E1 — Increasing rollout (safe)
- E2 — Decreasing rollout (caution)
- E3 — Changing the variant split (anti-pattern)
- E4 — Adding/removing variants (blocked, but historical traces)
- E5 — Changing exposure criteria mid-run
- E6 — Adding metrics mid-run (p-hacking)
- E7 — Shipping a variant rewrites the flag (ending alone does not)
- E8 — Reset clears results, not the flag
- E9 — Pause forces control on existing test users
- E10 — Retention metric: start event must occur after exposure
- E11 — "Matured users" filtering
- E12 — Long-term vs short-term metric divergence
- E13 — Editability locks (legacy experiments, ended experiments)
- E14 — Cleaning up the flag after the experiment
- E15 — Restarting an experiment with new variants
- E16 — Freezing and unfreezing exposure
- E17 — The start date was changed after launch

## E1 — Increasing rollout (safe) [HIGH]

No users switch variants; new users are added cleanly. Generally the only change safe to make on a
running experiment.

This is the rollout percentage of an existing release condition.
Adding a release condition, or one that pins a variant, is a different edit (A6 and A7 in `bias-and-skew.md`).
One exception: the first release condition that matches a person decides.
When a later release condition pins a variant, raising an earlier one moves the people it now takes in from the pinned variant to the hashed one.

A rollout that was raised after a launch at a small internal share leaves the early people in the results.
When those are internal users, reset the analysis after the raise.

## E2 — Decreasing rollout (caution) [MEDIUM]

Users currently in a test variant who fall outside the new rollout will switch back to the default
experience (if they stay active of course). This is a visible UX disruption — the feature they had disappears.
The flag returns `false` for them, which is no variant, so they do not count as exposed to a second variant.
This holds when no later release condition matches them.
The flag tries its release conditions in order, so a later condition that matches serves them a variant again: the same hashed one, or the one that condition pins.
With `early_exit` on in the flag's `filters`, a person outside the rollout of a matching condition gets `false` at once.

Their data also becomes
harder to interpret statistically. Their prior exposures _stay counted_ against
the test variant in the analysis. The numerator and denominator already include them. Reducing
rollout doesn't retroactively un-bucket; it only stops new exposures and flips re-evaluations. The
metric reading after a rollback mixes "pre-rollback test behavior" with "post-rollback default
behavior" for the same users — which is what makes it harder to interpret, not a loss of data.

**Recommend:** if the user wants to reduce rollout to _contain blast radius_ on a problem variant, stop serving the variant in a way that also closes the analysis.
Ending the experiment alone does not do that: it fixes the results at the end date and leaves the flag serving every variant.
Ship the control variant (E7).
A pause (E9) stops serving every variant while the team decides. It does not close the analysis.
If they genuinely want to shrink exposure while keeping the experiment alive, treat metric readings from
the rollback window onward as mixed and discount them when drawing conclusions.

## E3 — Changing the variant split (anti-pattern) [HIGH]

Moves bucket boundaries; users may be reassigned between variants. Reassigned users who come back and send an exposure under the new variant become `$multiple` users, who then
get excluded (default) or attributed to first-seen. Either way, introduces bias.
The product allows the edit on a running experiment, with a warning only.

After a split change the sample ratio test compares the whole run against the new split, and can report a mismatch that the assignment never had (A2 in `bias-and-skew.md`), depending on how far the counts of the run sit from the new split.

**Recommend:** reset the experiment if early; end and start a new one if significant data exists.
Where the data before the change is not worth keeping, moving the start date to the change is the smaller step (E17).
No tool changes the start date: the user changes it on the experiment page.

**Not an anti-pattern: the documented rollout.**
A filter of the form `timestamp < '<cutoff>'` in the exposure criteria closes the analysis to people exposed after the cutoff.
With that filter in place, a later change of the flag to roll a variant out does not touch the analyzed population.
Its metric events still count until the end date, or until each person's conversion window closes, and after the rollout part of that population gets the rolled-out variant.
Results that run past the rollout mix in the rolled-out experience: check the end date and the conversion window.
Read `exposure_criteria.exposure_config.properties` before calling a split change contamination.

**Related shape — the flag's split at launch isn't what the user thinks.** When a user reports
"one variant has no traffic at all" or "the split doesn't match what I configured", the cause is
sometimes not a _mid-run_ change but a _pre-launch_ edit that wasn't visible from the experiment
view.

**Verify directly.** The flag's history in `experiment-activity` (or `feature-flags-activity-retrieve { id: <feature_flag_id> }`) returns the
edit history with diffs, newest first and one page at a time (`limit`, `page`).
Scan the changes of `filters` and
read `multivariate.variants` in the `after` of the last such change _before_ `start_date`.
That value is the split the
experiment actually launched with.
Without a change before `start_date`, the flag launched with the split it was created with: the entry that created the flag carries no values, so read the `before` of the first `filters` change after `start_date`, or the current flag when `filters` never changed.
If the launch split doesn't match `feature_flag.filters.multivariate.variants` as the
user described setting it, the launch state itself is the cause — no mid-run change is needed to
explain the missing-variant data.

Fix path: same as E3 generally — reset + relaunch on a young experiment with little data; end +
relaunch on one with significant accumulated data. Set the flag's variants to the intended split
_before_ clicking launch on the relaunch.

## E4 — Adding/removing variants (blocked, but historical traces) [HIGH]

What is blocked on a launched experiment:

- The experiment itself rejects a change of the number or the keys of its variants.
- The flag rejects removing or renaming a variant key while a linked experiment runs.

What is not blocked: adding a variant on the flag, and changing the percentages (E3).
If a variant was added or removed that way, or before the block existed, expect `$multiple` exposures
in the data from people who came back after the change.
The analysis reads the variant keys from the flag as it is now: exposures of a removed key leave the results, and a person seen under a removed key and a remaining one counts under the remaining one.

**Dropping an arm from the analysis.**
An experiment can list `excluded_variants`.
Those arms are still served, and they are left out of the results and of the sample ratio test.
It is the supported way to stop analyzing an arm without touching the flag.

**Recommend:** treat the post-change window as contaminated. Reset (E8) and relaunch if the
contamination dominates the run, or end + start a new experiment with a fresh flag (E15) if
significant clean data exists from before the change.

## E5 — Changing exposure criteria mid-run [HIGH]

Edits to exposure criteria after launch can produce surprises — exposure event swap, multivariate
handling change, a new filter, or test-account filter toggle all change _which_ events count. Two specific cases:

- Switching `multiple_variant_handling` from `exclude` → `first_seen` mid-run is the **low-disruption
  way to mitigate uneven-split exclusion bias** on already-collected data. No users switch variants;
  all data stays.
- Other exposure-criteria changes re-process historical exposures under the new criteria, which can
  shift numbers without any actual change in user behavior. Communicate this to the user before they
  panic.
  A new filter that nothing can match empties the experiment (B12 in `empty-experiment.md`).

If the user is also changing how `distinct_id` is sent (e.g. anonymous → identified, email → user
ID), that's a different shape — see `bias-and-skew.md` A8. Identifier migration mid-run re-buckets
users; exposure-criteria edits don't.

## E6 — Adding metrics mid-run (p-hacking) [MEDIUM]

Choosing what to measure _after_ seeing data biases your results. Each additional metric is another
result to interpret, and with no multiple-comparisons correction (see `interpretation.md`), the chance
of _some_ metric looking significant by chance grows.

If the user is hunting for a significant metric after the fact, that's p-hacking — not a real result.
Swapping the primary metric after reading results is the same thing.

**Note:** retroactive metric _addition_ is technically supported (the metric is calculated for the full
experiment duration), but using it to fish for significance is a methodology problem, not a tool
limitation.

An edit of a shared metric changes that metric in every experiment that uses it, finished ones included (D13 in `numbers-vs-sql.md`).

## E7 — Shipping a variant rewrites the flag (ending alone does not) [HIGH]

**Ending** an experiment sets its end date and leaves the flag untouched: every variant keeps being served, and exposure events keep arriving.

**Shipping** a variant rewrites the linked feature flag's variant distribution: the chosen variant
gets 100% of the variant distribution, every other variant goes to 0%. The flow has two release
modes — pick carefully:

- **Roll out to the experiment population (default, recommended).** Existing release conditions on
  the flag are preserved untouched. The chosen variant is served only to users who already match
  those conditions, and per-user variant overrides continue to apply. No catch-all release
  condition is added.
  A release condition with a rollout below 100% keeps its rollout: the rest of its audience gets no variant, as before.
  "We shipped the variant and some users still don't see it" is this.
  A release condition that pins another variant, and a holdout, keep their people off the shipped variant too.
- **Roll out to all users (explicit opt-in).** In addition to the variant-distribution flip,
  a catch-all release condition is _prepended_ to the flag's release groups with the literal
  description _"Added automatically when the experiment was ended to keep only one variant."_ This
  overrides existing release conditions and bypasses per-user variant overrides — anyone hitting
  the flag now gets the chosen variant.
  Holdout people are the exception: the holdout is evaluated before any release condition, so they keep `holdout-<id>`.
  On a flag of an early access feature, the people who opted in or out keep that answer, without a variant, for the same reason.

Both modes flip the active variant ratio to e.g. 0/100.
The catch-all release condition is the discriminator between modes.
A ship also removes an exposure freeze (E16), and it keeps a holdout in place.
A ship never switches the flag on: on a paused experiment the flag stays off after the ship, and nobody gets the shipped variant.
The ship also ends the experiment, so Resume is no longer offered: the flag is switched on from its own page.

**If the flag distribution suddenly flipped**: a ship is the most likely cause.
A metric edit and an end without a variant do not touch the flag.

**Verify directly.** In `experiment-activity`, a newer ship has an entry `variant_shipped` on the experiment that names the variant.
An older ship has none: the flag's change of `filters` that puts one variant at 100% is then the only evidence, and that variant is the shipped one.
That entry sits at the moment of the end when the ship ended the experiment, and later when the variant was shipped after the end.
An end with a variant picked in the End-experiment modal is a ship, whether or not the user thinks of it as one (C10 in `interpretation.md`).
The flag's entry at the same time shows a change of `filters`:

- A `multivariate.variants[]` diff showing the rollout flip (typical signature: 50/50 → 0/100) → E7 is confirmed.
- Additionally, look at the first release condition in `after.groups[]`: empty `properties`, a rollout of 100, and a `description` of
  _"Added automatically when the experiment was ended to keep only one variant."_ If present, this
  was a **"roll out to all users"** ship and the new release condition overrides the flag's prior
  targeting and per-user overrides. If absent, this was a **"roll out to
  the experiment population"** ship — the variant distribution flipped but targeting is intact.
  The release groups are unchanged then, except on a flag that still carries an exposure freeze (E16): there both modes also remove the snapshot cohort condition from every group, so only the catch-all tells the modes apart.

<!-- Source for maintainers (may rot): _roll_out_variant in products/feature_flags/backend/facade/api.py (the
description is set on the release group itself); ExperimentService.ship_variant and end_experiment in
products/experiments/backend/experiment_service.py. -->

The MCP tool that performs this rewrite is `experiment-ship-variant`. It takes
`release_to_everyone: bool` (defaults to `false` = "roll out to the experiment population"); the
agent should confirm the release mode with the user before invoking, in addition to the variant key.

**Default to control on ambiguous ships.** If the user is unsure which variant to ship — primary
unclear, secondaries mixed, or they're still investigating — recommend shipping **control**.
Accidentally rolling out control is a no-op; accidentally rolling out a test variant flips the
variant distribution to a not-validated change. If the user _also_ picks "roll out to all users",
the blast radius extends past the experiment's existing population — discourage this combination
when the user sounds uncertain.

## E8 — Reset clears results, not the flag [HIGH]

Reset ("Reset analysis" in the app) returns the experiment to draft and clears `start_date`, `end_date`, the conclusion with its comment, and `archived`.
**Events already captured still exist** but won't be applied to the experiment unless `start_date` is
set appropriately after relaunching. The feature flag is left untouched — users continue seeing their
assigned variants during the reset window.
One exception: an exposure freeze is removed, so the flag serves its original release conditions again (E16).
A flag that is off at the reset (a paused experiment) stays off and serves nobody until the relaunch switches it on.

After a relaunch on the same flag, people keep the variant they had.
Those who come back may send no new exposure event `[MEDIUM]`: the SDKs deduplicate it, and their response has not changed (B3 in `empty-experiment.md`).

**Use case:** suspected bias in the existing data, and the user wants to start a clean comparison.
Reset + adjust + relaunch is the right path.

## E9 — Pause forces control on existing test users [HIGH]

Pause sets the flag's `active=false`. The flag stops returning a variant, so users fall
back to the application default — typically control. Test users effectively switch back to control
during the pause window. No new exposures are counted while paused.
`status` reads `paused`.

Resume reactivates the flag.
People get the same variant as before the pause, unless the flag's variants or release conditions were edited during the pause (the flag's entries in `experiment-activity`).
A frozen experiment resumes frozen, and `status` reads `exposure_frozen` again.

**Implication: the pause biases the result** `[MEDIUM]`.
The analysis has no notion of a pause.
Metric events during the pause keep counting toward the variant of each person's first exposure, although nobody received the test experience in that window.
With a conversion window on the metric, this reaches only the people whose window overlaps the pause.
The test arm's result is diluted toward control by the length of the pause, relative to the run.
Nothing in the product warns about this.

**Evidence.** The pause and resume times in `experiment-activity`: the entries of the experiment, and the changes of the flag's `active` field.
An older pause has no entry of the experiment: its only trace is the flag's change, which is missing when the caller has no access to the flag.

**Recommend:** when interpreting results that span a pause window, state the pause dates and explain that the
metric data during that window mixes test-variant users with control-like behavior. If the pause
was long relative to the run, consider reset + relaunch over interpreting the contaminated data.

## E10 — Retention metric: start event must occur after exposure [HIGH]

A retention metric has one of two starts.
Read `start_event` of the metric first.

**A custom start event** (the default for a new metric).
The **start event must occur at or after the user's first exposure**, and within the conversion window after it when the metric has one.
This
is the same design as all other metric types — the analysis question is "what is the effect of this
feature _after_ a user sees it?"

`start_handling` (`FIRST_SEEN` vs `LAST_SEEN`) does _not_ relax this. It only picks _which_
post-exposure start event anchors the retention window when a user has multiple.
Pre-exposure start events are dropped before the choice is made.
Users whose only start events are pre-exposure are excluded
entirely — they don't appear in the retention denominator.

**The experiment's exposure as the start** (`start_event` of kind `ExperimentExposureNode`, "Experiment exposure" in the editor).
Retention counts from each person's first exposure, and every exposed person is in the denominator.
The exception is `only_count_matured_users` (E11): people whose retention window has not ended since their first exposure are left out.
`start_handling` and a conversion window do not apply.

In both, the completion must be another event than the one that started the window, and retention windows in days or hours compare calendar days or hours.
The editor offers only those two units.
A window in another unit, set through the API, compares exact timestamps.

<!-- Source for maintainers (may rot): build_retention_query, build_start_after_exposure_predicate and
build_start_event_timestamp_expr in products/experiments/backend/hogql_queries/experiment_retention_query_builder.py. -->

An alternate question — "does this feature change the standard _pre-anchored_ retention metric?",
where the start event can be before exposure — isn't supported on experiments. The workaround is to
track that metric separately in product analytics.

**If retention undercounts unexpectedly:** with a custom start event, confirm that the start event has post-exposure
occurrences for the affected users.
When the user wants every exposed person in the denominator, the exposure start is the fix.

**If the number does not fit the name:** compare the metric's definition with what the user means by retention (D13 in `numbers-vs-sql.md`).

## E11 — "Matured users" filtering [HIGH]

An experiment-wide setting, `only_count_matured_users`, shown as "Require completed conversion or retention window".
With it on, each metric that has a conversion window leaves out the people whose window has not elapsed since their first exposure.
A retention metric uses the end of its retention window instead, counted from each person's start event, or from the first exposure when the exposure is the start (E10).
Metrics without a window are not affected.
A project default decides its value for new experiments.

**Implication:** turning this on **reduces** the user count in the analysis (recent users excluded) but
makes per-user metric values more comparable across cohorts. If the user count drops unexpectedly,
or differs between metrics of one experiment, check this setting and each metric's window.

## E12 — Long-term vs short-term metric divergence [MEDIUM]

Primary (short-term) and secondary (long-term) metrics moving in different directions is **normal** —
a checkout-flow change might lift conversion now but hurt retention later.

**Recommend:**

- Keep the short-term metric as primary and long-term as secondary — don't promote long-term to primary
  just because it disagrees.
- To keep measuring the people already enrolled while no new ones enter, freeze exposure (E16).
- Use a **holdout** for sustained measurement across experiments.
  A holdout is a share of people, drawn by hash at every flag evaluation, who get `holdout-<id>` in place of a variant and are outside the experiment's results.
  Compare them with everyone else in an insight broken down by the flag's value.
- For deeper segment analysis, add a breakdown to the metric (D3 in `numbers-vs-sql.md`), or use
  session replays to see what behavior differs between variants.

**Holdouts under local evaluation** `[MEDIUM]`.
A server SDK that evaluates flags locally and predates holdout support puts holdout people into the regular variants.
_Evidence:_ the share of `holdout-<id>` responses is below the configured share, and the gap sits in one library (by-library query in `diagnostic-snapshot.md`).
_Fix:_ update the SDK.

## E13 — Editability locks (legacy experiments, ended experiments) [HIGH]

- **Legacy experiments** (`is_legacy: true` in `experiment-get`) — only the name, the description and the end date can be edited.
  A "This is a legacy experiment. Metrics can no longer be edited." notice appears in the UI.
  Where it is rolled out, a second notice says that legacy results will stop being available.
- **Launched experiments** — the variant keys can't be edited (E4). If
  edits are needed, duplicate (E15), or reset (E8) and re-launch.

If the user is fighting an editability lock, that's a sign the experiment should be migrated, duplicated or reset
rather than worked around.

**What makes an experiment legacy.**

- `is_legacy` is the one field to read.
- Behind it: a metric of kind `ExperimentFunnelsQuery` or `ExperimentTrendsQuery` (not `ExperimentMetric`), inline or through a shared metric.

A legacy experiment's results are not readable through `experiment-results-get`.
Don't confuse this with a `data: null` row on a **non-legacy** experiment — that is a query that failed in one call.
See "Metric rows with `data: null`" in `diagnostic-snapshot.md`.

Fix path: **migrate the experiment** with `experiment-migrate`.
It creates a new experiment with the same configuration and the metrics converted, on the same flag, so no new rollout is needed and people keep their variant.
The legacy experiment stays as it is.
Tell the user about the second experiment before migrating.
`experiment-duplicate` rejects a legacy experiment.
Alternatively, end the existing experiment with a documented conclusion if the original
hypothesis is no longer interesting.

## E14 — Cleaning up the flag after the experiment [HIGH]

What the link between an experiment and its flag allows:

- **Deleting the flag** is blocked only while the experiment runs.
  A draft, stopped or archived experiment does not block it, and the experiment keeps its results.
- **A deleted flag frees its key.**
  Restoring it later reclaims the key, or gets a numeric suffix (`my-flag-2`) when another flag took the key meanwhile.
  The application code then reads a key that is no longer this flag.
- **The flag cannot be unlinked** from the experiment.
- **Simplifying the flag** `[MEDIUM]`. Once the experiment has ended, the flag no longer protects its variant keys, so the variants can be removed on the flag itself.
  The ended experiment reads its variant keys from the flag: a removed variant leaves its results at the next calculation.
  On the flag's overview the edit control of the variants stays disabled while an experiment is linked. The flag's edit form is the way in.
- **Archiving** needs an ended experiment.

**Results that seem to be gone.**
Deleting an experiment hides its results. Deleting its flag does not: the experiment keeps its results.
Neither deletes an event.
A deleted flag can be restored from its page.
A deleted experiment can be restored too: the delete confirmation offers an undo, and an API update that sets `deleted` to false restores it, once its flag is restored.
The app has no list of deleted experiments, and `experiment-update` does not take `deleted`.

**Recommend:** before cleaning up, confirm the flag's future use. If the user expects to keep using
the flag for general rollout after the experiment ends, ship the variant (E7) — that leaves the flag in a usable state at the chosen rollout.
If they're done with the flag too,
keep the flag until the calling code has been removed.

## E15 — Restarting an experiment with new variants [MEDIUM]

The clean approach is:

1. **End** the existing experiment.
2. **Duplicate** it (`experiment-duplicate`), or create a new one.
   The duplicate is a new draft with the metrics and settings of the original, without its holdout and its excluded variants.
3. **Give it a new feature flag key.**
   A duplicate without a new key shares the original's flag, so a ship or a pause on one affects both.
4. Launch the new experiment under the new flag.

Why a new key and not a reset on the old flag:

- The same key gives every returning person the same draw as before, so the new run is not a fresh randomization for them.
- Returning people who already sent the exposure event may not send it again (B3 in `empty-experiment.md`).
- A changed set of variants on the old flag moves people between variants (E3).

The same three points explain a follow-up run that disagrees with the first one on the same flag: it is not an independent test.

Reusing the same flag with new variants on a new experiment is technically possible but tends to
produce confusing exposure histories. Only do this
if the user is explicit about wanting to keep historical bucketing comparable.

## E16 — Freezing and unfreezing exposure [HIGH]

**Symptom (in the user's vocabulary):** "exposures stopped growing and the experiment still says running", "after the freeze some users lost the variant", "can I freeze this experiment", "the freeze was refused".

**Behavior.** Freezing stops enrollment and keeps measuring.
PostHog saves the people exposed so far as a static cohort and narrows every release condition of the flag to that cohort.
The variant split and the end date stay untouched. `status` reads `exposure_frozen`, and no banner appears.

- New people get no variant.
- Enrolled people keep their variant, and their metric events keep counting.
- The cumulative exposure series goes flat. That is the intended effect.

**Where a freeze biases or breaks the run:**

- **People exposed just before the freeze** can miss the cohort.
  They count as exposed, and from the freeze on they get no variant.
- **Local evaluation.** A static cohort cannot be evaluated locally.
  A server SDK falls back to a remote call, and one that is set to evaluate only locally serves the flag's default to everyone, enrolled people included `[MEDIUM]`.
- **Release conditions edited or added after the freeze.**
  A variant override set later on a frozen release condition keeps that condition's cohort, so people outside the cohort still get no variant from it.
  An override set on a new release condition carries no cohort: that is the next case.
  A release condition added without the cohort reopens enrollment, and `status` reads `running` again.
- **Ending without shipping** leaves the flag narrowed to the cohort.
  Shipping a variant or resetting removes the freeze.
- **Unfreezing reopens enrollment.**
  People who enroll after it joined later and possibly under other conditions than the first group.
  Mixing both groups in one analysis can bias the result. The unfreeze dialog is the one place where the product itself warns about bias.
  The End dialog of a frozen experiment warns only that the flag stays narrowed to the cohort.

**When a freeze is refused:** a draft, an ended or a paused experiment; an experiment that is already frozen; a missing or deleted flag, or a flag without release conditions; a group-aggregated experiment; an experiment with a holdout or with early-access conditions in the older format (`super_groups` in the flag's `filters`); too many exposed people to save in one step; more than a small share of exposed people without a person profile, which rules out experiments on logged-out traffic; no exposures yet.

<!-- Source for maintainers (may rot): freeze_exposure and unfreeze_exposure in
products/experiments/backend/experiment_service.py; freeze_exposure_blocker and status_label in
products/experiments/backend/models/experiment.py.
Docs: https://posthog.com/docs/experiments/managing-lifecycle#freezing-exposure -->

**Evidence to gather.** `status` from `experiment-get`.
Every freeze and unfreeze in `experiment-activity`, with its time: a change of the flag's release conditions that adds the cohort to every condition, or removes it.
Newer ones also have a named entry on the experiment (`exposure_frozen`, `exposure_unfrozen`).
Older ones have only the flag's change, which is missing when the caller has no access to the flag.
Any other change of the flag's release conditions after the freeze.
Whether the user's servers evaluate flags locally.

**Co-occurs with:** E9, E12, and the plateau check in `empty-experiment.md`.

**Recommendation.**

- A plateau on a frozen experiment needs no fix.
- State the freeze and unfreeze dates with any result that spans them.
- Before an unfreeze, say that the two enrollment groups will be mixed.
  A user who only wanted to check the frozen results does not need to unfreeze.
- For a flag with many release conditions or overrides, freezing is fragile: every later edit of the flag has to keep the cohort condition.

## E17 — The start date was changed after launch [MEDIUM]

**Symptom (in the user's vocabulary):** "the numbers changed overnight and nobody touched the experiment", "people from launch day disappeared", "the experiment and the insight disagree since last week".

**Behavior.** The experiment analyzes exposures from `start_date` on.
An edit of the start date moves that boundary for the whole run:

- **Moved later:** people whose exposures all lie before the new start leave the experiment.
  A person exposed before and after counts from the first exposure inside the window, and their earlier metric events no longer count.
- **Moved earlier:** exposures from before the launch enter: internal testing, another split, another audience.

An insight on the same events ignores the experiment's start date, so the two disagree after such an edit.

**Evidence to gather.** Changes of `start_date` in `experiment-activity`, each with its old and new value.
A start date before the flag had its current split or audience (the flag's entries in the same history).

**Co-occurs with:** E3, E8.

**Recommendation.**
A start date moved to just after a fix is a legitimate way to cut a contaminated beginning: say what was cut.
The user makes this edit on the experiment page; no tool changes the start date.
A start date moved back to recover data brings in whatever the flag did then: check the flag's history for that period before trusting the result.
Repeated edits of the start date are a reason to reset and relaunch.
