# Significance & interpretation traps

How to read PostHog experiment results without falling into common interpretation pitfalls.

Read the statistics settings before any result (Step 1 of `SKILL.md`): the method, the confidence level, sequential testing, CUPED and the baseline variant.
C5 to C7 cover the method and the confidence level. C13 covers sequential testing, CUPED and the baseline variant.

## Contents

- C1 — Peeking / early stopping
- C2 — Low-volume variance (looks broken but isn't)
- C3 — A/A test showing significance
- C4 — Multiple comparisons (no correction across variants or metrics)
- C5 — Bayesian interpretation traps
- C6 — Frequentist interpretation traps
- C7 — Bayesian vs Frequentist confusion (overlapping intervals, p-values)
- C8 — Inconclusive but trending — when is it ok to ship?
- C9 — "Significance reached" notification is not a green light to ship
- C10 — Ship-variant choice does not consider any metric result
- C11 — External calculator disagrees with PostHog
- C12 — "Target reached" on the running-time estimate is not a result
- C13 — Statistics settings that change how a result reads (sequential testing, CUPED, baseline variant)

## C1 — Peeking / early stopping [HIGH]

Watching results live and ending the experiment the moment it looks significant **inflates false
positives** — you're giving randomness more chances to look significant.

**The exception: sequential testing.**
A Frequentist experiment with sequential testing on keeps its false-positive rate at the chosen level however often the result is read (C13).
The peeking warning does not apply to it.
Bayesian experiments have no sequential mode.

**Evidence.** All of it is in `experiment-get` and the stored results:

- **Age:** `start_date` against now.
- **Sample:** the exposed total across all variants against `running_time_calculation.recommended_sample_size`.
  That target is a total for all variants, not a number per variant.
- **Time:** `running_time_calculation.recommended_running_time`.
  On a launched experiment it is the number of days still missing at the current exposure rate, as of the last time someone opened the experiment, and 0 once the target is reached.
  It is not the planned length of the run.
  Three cases hold the whole estimated length instead: an estimate from numbers the user typed (`exposure_estimate_config.conversionRateInputType` is `manual`), a value written when the experiment was created that no page load has replaced since, and a value saved by a page load in the first day of the run or before 100 exposures, when no later page load has replaced it (C12).
  Judge progress by the sample, not by this number.
- **Method:** `stats_config.method`, and `stats_config.frequentist.sequential_testing_enabled`.
  A missing `method` reads as Bayesian.
  When the experiment does not set `sequential_testing_enabled`, the project default applies (C13).
- **Floor:** a variant with fewer than 50 exposures has no result at all (C2).

**Say it unprompted.**

**MUST state the experiment's age and its share of the target sample before any reading of a result,** when the experiment is below its target sample and sequential testing is off.
One day into a run, the honest first sentence is that the result is not readable yet.
When the experiment has no target, state the age and the exposures per variant, and say that no target was set.

**MUST NOT withhold the numbers or refuse the question.**
Give the current estimate, labeled as early, and say when it becomes readable.

In the early days of the experiment, significance can flip back and forth a lot: the floor of 50 exposures per variant is where analysis starts, not where it becomes stable.

**Recommend:**

- Predetermine duration _before_ launching. Use the running-time calculator on the experiment.
- Or turn on sequential testing before launch, when the team wants to read results continuously.
- Frequentist: PostHog uses α=0.05 by default → a single metric has ~5% chance of false-positive
  significance even when nothing changed.
- Don't treat 0.05 as a hard cliff. It's a convention, not a meaningful threshold by itself —
  results just below and just above are close to equivalent in evidence.

## C2 — Low-volume variance (looks broken but isn't) [MEDIUM]

**Symptom:** few hundred or fewer exposures per variant; the visible split looks badly off (a
roughly 2-to-1 skew at a few dozen exposures can be chance alone: 30 against 16 gives a p-value near 0.04, far from the 0.001 that the product flags).

**Mechanism:** With low samples per variant (rule of thumb: under a thousand), the visible split can
swing widely from the configured ratio — deterministic-hash variance is large at small samples.
PostHog's calculations account for this; the visible ratio is not a bug.
Whether a split is a real mismatch is the sample ratio test's call, not the eye's (A2 in `bias-and-skew.md`).

**Validity gates** `[HIGH]`. A variant gets no result, and the metric reads "Not enough data yet", until:

- the variant has at least **50 exposures**;
- for a funnel or retention metric, the variant has at least **5 conversions**;
- for a ratio metric, the denominator is not zero;
- the baseline variant's total is not zero.

A Bayesian funnel result additionally needs at least 5 people who converted and 5 who did not, in each variant.
So a variant where almost everyone converted reports nothing either.
The same check applies to a Bayesian mean metric with a `threshold` (5 people who reached it and 5 who did not), and not to a funnel that CUPED adjusts.

The stored results name the failed gate in `validation_failures` (table in `diagnostic-snapshot.md`).
Some checks give no result and leave `validation_failures` empty: the Bayesian 5-and-5 check above, a baseline mean below zero under Bayesian, and a metric whose values do not vary.
The variant then has no interval, no significance and no entry that says why.
The fix is the same for all: more exposures, or accept that the result isn't ready.

<!-- Source for maintainers (may rot):
- validate_variant_result in products/experiments/backend/hogql_queries/utils.py;
- _validate_normal_approximation in products/experiments/stats/bayesian/tests.py. -->

**Recommend:** wait. Run longer or increase rollout.
The gates are where analysis starts.
The sample the experiment needs is the running-time calculator's target (C12).

## C3 — A/A test showing significance [MEDIUM]

A/A tests _should_ rarely show significance. If the user reports their A/A test is showing a
significant difference, work through:

1. **Is it random chance?** With a correct methodology, a share of
   metric-variant pairs in an A/A test will look significant by chance.
   With multiple metrics × multiple variant pairs, _expect_ some to flicker
   significant. C4 below has the rates.
   A result read early and often adds to it (C1).
2. **Is the exposure the same for both arms?** Two arms that serve the same experience can still differ in how the exposure event is sent or who arrives after it: an exposure recorded on the server before anything is rendered, an exposure event that one path sends more reliably.
   Even exposure counts do not rule this out (A9 in `bias-and-skew.md`).
3. **Is it exposure handling?** On an uneven split with `multiple_variant_handling = "exclude"`, people in more than one variant leave the smaller arm in a larger share (A1 in `bias-and-skew.md`).
   On an even split they leave both arms alike.
4. **Is the implementation correct?** A large multiple-fold gap between equal-sized variants is
   **extremely unlikely** to be random — instrumentation is the more likely cause. A specific
   shape worth checking: **data-warehouse-source metrics where per-user exposures are joined to a
   per-group warehouse table** (`ExperimentDataWarehouseNode` with `events_join_key: $group_<n>`
   on the exposure side and `data_warehouse_join_key` on a group-keyed metric table). The join
   gives each exposed user all rows of that user's group, so a `sum`
   metric over-counts proportional to per-group user count. If user counts are balanced but per-group
   user counts aren't, the sum can swing widely even on a true A/A — and the test reads that as
   significant. _Detect:_ the metric's definition in `experiment-get`: a warehouse source whose join key is a group key, on an experiment that is aggregated by person.
   _Sanity check:_ re-aggregate the warehouse table by
   org/group once (deduped) and compare to the per-user sum; a large gap confirms repeated-row
   inflation.
5. **Is it a legacy experiment?** An experiment with legacy metrics runs on the older engine (E13 in `mid-run-changes.md`).
   Migrate it before reading an A/A result.

**Recommend:** if chance and exposure do not explain the result, investigate instrumentation rather than
assuming the methodology is wrong.

## C4 — Multiple comparisons (no correction across variants or metrics) [HIGH]

PostHog **does not** apply multiple-comparisons correction:

- Across variants — each test variant is compared to the baseline independently
- Across metrics — each metric is tested independently

So with many metrics or many variants, the chance of _some_ spurious significance grows.

- **Frequentist** at α=0.05 (the default): with 5 independent metrics, the chance of at least one false positive
  is ~23%; with 10 metrics, ~40%.
- **Bayesian**: a result is significant when the chance to win is above the confidence level **or** below one minus it.
  At the default 95% that is two tails of 5% each, so about one comparison in ten is marked significant when nothing changed, and the chance of at least one among 5 metrics is about 40%.

(Confidence level is configurable — see C6.)

**Recommend:**

- Define a small set of planned, hypothesis-driven metrics up front.
- Treat results as a **pattern** across planned metrics, not a single "gotcha" significant metric.
- Add guardrail metrics as secondary, not primary.
- An unexpected metric that turns significant is a hypothesis for a follow-up experiment with that metric as the primary, not a reason to ship.
- Be especially wary of metrics added after seeing data — that's p-hacking. See `mid-run-changes.md`.

## C5 — Bayesian interpretation traps [HIGH]

PostHog defaults to Bayesian, unless the project's default method says otherwise (C7). Common misreads:

- **"96% chance to win"** is about _direction_ (test is better than the baseline), **not** the magnitude of
  the lift. Read the **credible interval** alongside it.
- **The threshold is the confidence level.**
  A result is significant when the chance to win is above the level, or below one minus it.
  96% is significant at 90% and at 95%, and not at 99%.
  At 95%, a chance to win below 5% is a significant loss.
- **A metric whose goal is a decrease** (`goal: "decrease"` on the metric).
  The page shows one minus the stored value, so that a high chance to win always means "better".
  The stored `chance_to_win` is not inverted: on such a metric a stored value below 5% is a significant win.
- **"Significant, and the interval still crosses zero."**
  Significance uses the chance to win, a one-sided value.
  The interval shown is two-sided at the same level.
  At 95%, a chance to win between 95% and 97.5% is significant while the 95% interval still includes zero.
  Both statements are correct. The result is borderline.
  The page's own help says otherwise: the tooltip of the interval column and the "How to read" tooltip say that a result is significant when the interval does not cross 0%.
  That is the Frequentist rule.
  Under Bayesian, the "Significant" column and the "Won" or "Lost" tag follow the chance to win.
- **Don't ship the moment chance-to-win flips green** — early flips are within the noise band (C1).
- **Flat priors.** PostHog uses a non-informative prior. Early swings
  aren't the prior pushing things around — they're the data being sparse.
- **The displayed effect is relative** to the baseline: 10% against 12% conversion reads as +20%.
- **Legacy experiments.** An experiment with legacy metrics (`is_legacy` in `experiment-get`) uses an older engine with
  different multivariate semantics and different significance gates. See E13 in `mid-run-changes.md`, and PostHog's
  [legacy-methodology docs page](https://posthog.com/docs/experiments/legacy-methodology).

<!-- Source for maintainers (may rot): is_decisive in products/experiments/stats/bayesian/tests.py;
credible_interval in products/experiments/stats/bayesian/utils.py. -->

## C6 — Frequentist interpretation traps [HIGH]

PostHog has Frequentist support. Set in `stats_config.method`. Quick rules:

- The confidence interval **doesn't cross 0** → significant vs the baseline. It **crosses 0** → not significant.
- PostHog uses **Welch's t-test** as the default — it handles unequal variance between groups, unlike
  Student's t-test (which assumes equal variance).
  With sequential testing on, a sequential test replaces it (C13).
- α = 0.05 by default → ~5% chance of false-positive on a single metric.
- **Confidence level is configurable per project (and per experiment).** The values offered are 90%, 95%
  and 99%. The project default is `default_experiment_confidence_level`.
  It is copied into a new experiment at creation, as `stats_config.frequentist.alpha` and `stats_config.bayesian.ci_level`, so a later change of the default does not move existing experiments.
  The interval column's title reads "Credible interval (95%)" or "Confidence interval (95%)" at every level, and the "How to read" tooltip says 95% too.
  The interval itself is computed at the experiment's level.
  If a user reports a p-value of 0.07 as "significant", they're
  likely on the 90% setting; check before debugging the math.
- Significance is per-metric. With many metrics, expect some to flicker in/out as the sample grows.

## C7 — Bayesian vs Frequentist confusion (overlapping intervals, p-values) [MEDIUM]

A frequent source of confusion:

- **Overlapping intervals do not imply non-significance, under either method.** Two intervals drawn per variant can overlap while the difference between the variants is significant.
  The page does not draw per-variant intervals: each test variant has one interval, of its difference from the baseline.
  Under Frequentist, that interval decides: it does not cross 0 exactly when the result is significant (C6).
  Under Bayesian, significance is determined by win probability, so that interval can still cross 0 on a significant result (C5).
- **p-values don't apply in Bayesian.** A question about "p < 0.05" is a frequentist frame. If the
  experiment is on Bayesian, redirect to win probability + credible interval.
- **The method is a per-experiment setting with a project default.**
  A new experiment takes the project's default method at creation.
  Read `stats_config.method` of the experiment. Do not assume Bayesian.

## C8 — Inconclusive but trending — when is it ok to ship? [MEDIUM]

Shipping an inconclusive result can be defensible when all of these hold:

- A clear primary metric improvement _without_ a guardrail regression
- Strong qualitative conviction (replays, user feedback, intuition)
- The cost of being wrong is low (e.g. easy to roll back via the flag)

Do **not** ship if the timeseries chart shows a sustained regression — point-in-time
significance can flip, but a sustained downward trend on the timeseries is a stronger signal
than a snapshot reading.

Recommend the user open the experiment's _timeseries_ view (per metric) — point-in-time significance can
flip, but a sustained trend is a stronger signal than a snapshot reading. The agent can also pull
this directly via `experiment-timeseries-results`, with the metric's `uuid` and `fingerprint` from `experiment-get` (a shared metric carries both in `saved_metrics[].query`).
In the series, look for a single day that carries the whole effect: one unusual day can make a flat experiment look significant.

For the qualitative part (replays / intuition), invoke the
`posthog:analyzing-experiment-session-replays` skill — it surfaces variant-level replay patterns and
is the right tool when the call is "primary metric is up, no guardrail regression, do we ship?"

## C9 — "Significance reached" notification is not a green light to ship [HIGH]

PostHog can mark a metric as significant and send a notification well before the experiment has
accumulated enough data for the result to be stable. The verdict can revert as the sample grows,
and no notification is sent when it does.
Treat the notification as a _prompt to review_, not an _instruction to ship_.

The notification is an opt-in destination on the experiment's Settings tab.
It is sent from the scheduled calculation, each time a variant turns from not significant to significant against the calculation before.
A result that reverts and comes back is announced again.
Its only gates are the validity gates of C2: no minimum number of days, no check against the planned sample.
The scheduled calculation covers only experiments with status `running` that started in the last 60 days, and no legacy metric: outside that, no notification is sent.

Before acting on a significance notification, check **all of**:

- **Participants per variant.** The gate is 50 exposures per variant, and 5 conversions for a funnel or retention metric. That's
  a floor for analysis, not a sufficiency bar for shipping. Aim for the target sample of the running-time
  calculator.
- **Days running.** For high-stakes ships, wait at least a full week before acting on a
  significance flag — shorter windows can swing as the sample grows. This is a working norm,
  not a product-enforced threshold.
- **Pre-planned duration.** If the experiment hasn't reached the length the team planned, the significance
  is "current best estimate", not "settled".
  The experiment stores no planned end date: compare the exposed total with the target sample (C1), or ask the user what the team planned.
  Sequential testing is the exception (C13).
- **Variant balance and `$multiple` share.** If a bias or skew diagnostic (`bias-and-skew.md`) is in play, the
  significance verdict is suspect regardless of how large the gap looks.
- **Secondary metrics.** See C10.

When a previously-significant result reverts to not-significant, that's not a bug — it's the same
analysis updated with more exposures. Explain the difference between _signal seen so far_ and
_result confirmed_.

## C10 — Ship-variant choice does not consider any metric result [HIGH]

The End-experiment modal opens with the "Variant to keep" selector empty, so ending the experiment
rolls out nothing unless the user picks a variant. Nothing behind that pick reads the results:
there is no significance check, no primary-metric direction check, and no guardrail check. The
"End experiment" button is gated by **selecting a conclusion** (won / lost / inconclusive / stopped
early / invalid), _not_ by the variant selector.
The modal keeps a picked variant while the page stays open, so a user who picked one earlier and comes back ships that variant, unexamined.

The modal also asks **how** to release the chosen variant, with two radio options:

- **Roll out to the experiment population** (default, recommended) — variant distribution flips
  to 100/0 for the chosen variant; the flag's existing release conditions and per-user variant
  overrides are preserved. Only users already in the experiment's population see the variant.
- **Roll out to all users** — additionally prepends a catch-all release condition that overrides
  existing release conditions and per-user overrides. Anyone hitting the flag gets the chosen
  variant.

The release-mode choice doesn't read metrics either; the safer "experiment population" option is
the default.

<!-- Source for maintainers (may rot): FinishExperimentModal in
frontend/src/scenes/experiments/ExperimentView/ExperimentModals.tsx. Verify before citing. -->

**Recommend:** before clicking "End experiment", do three things:

1. **Manually review every metric** — primary direction and significance, plus every secondary /
   guardrail metric. The product names no winner for the experiment: the "Won" and "Lost" tags on the page are per metric.
2. **Explicitly choose the variant to keep** after reviewing the metrics, or leave the selector empty to end without shipping.
3. **Confirm the release mode matches intent** — "experiment population" keeps the variant scoped
   to current targeting; "all users" overrides existing release conditions and per-user overrides.
   The default is the safer choice; flag any non-default selection back to the user explicitly.

If any guardrail is trending negative, or the primary isn't actually significant, the safe move
is to keep control rather than ship the test variant. This matters most for sophisticated
users who set guardrails for a reason.

## C11 — External calculator disagrees with PostHog [MEDIUM]

A common case: conversion counts from the experiment page get pasted into an online A/B
calculator, or another AI assistant is asked for the numbers, and the answer differs from PostHog's
("not significant" vs "significant", a different count, a different winner).

Three questions to ask before debugging stats:

1. **Which methodology?** PostHog is **Bayesian by default**. Most online calculators are
   Frequentist. The two answer different questions; they will not agree on borderline cases. If the
   user wants a Frequentist comparison, change `stats_config.method` and re-read (see C6).
2. **Are the inputs actually the same?** The numbers on the experiment page are post-scope —
   `$multiple` excluded, test accounts filtered, exposure-bounded date range, per-user aggregation
   for means, the conversion window applied. An online calculator gets none of that — if
   the user typed in raw event counts they grabbed from SQL, the calculator and PostHog are
   computing on **different populations**, and disagreement is expected.
   An assistant that counts a metric's events without the experiment's scope answers a different question too (D1 in `numbers-vs-sql.md`).
3. **Does the experiment adjust the values?** Outlier handling, CUPED and sequential testing change the estimate or the interval (C13).
   No calculator on raw counts reproduces them.

After confirming both methodology and inputs match, if the disagreement persists, treat it as a
real anomaly worth investigating with the experiment URL.

## C12 — "Target reached" on the running-time estimate is not a result [MEDIUM]

**Symptom (in the user's vocabulary):** "the experiment says complete but nothing is significant", "it finished within days and we had planned for weeks", "it reads 'Target reached' while every metric still says 'Not enough data yet'".

**Behavior** `[HIGH]`. The duration display next to the experiment's status is an estimate of sample size.
It reads "~N days left" while the exposures are below the target, and "Target reached" once they are at or above it.
Older versions read "Complete".
On an ended experiment "Complete" is the status tag: every ended experiment carries it, and the duration display is hidden.
Read `status` first when the user says "complete".

- The target is the sample needed to detect the **minimum detectable effect** with about 80% power at 95% confidence.
- The estimate uses the **first primary metric** only.
- The minimum detectable effect is the project's default, and 30% where none is set.
  A 30% effect needs a small sample, so the target is reached within days on a busy surface.
- "Target reached" says that an effect of that size would probably have shown.
  It says nothing about significance, and it does not end the experiment.

<!-- Source for maintainers (may rot): ExperimentRemainingTime.tsx in
products/experiments/frontend/components/ExperimentMetaBar; runningTimeLogic.ts in
frontend/src/scenes/experiments/RunningTimeCalculator. -->

**Evidence to gather.** `running_time_calculation` in `experiment-get`:

- `recommended_sample_size` — the target, a total across all variants.
- `recommended_running_time` — the days still missing at the current exposure rate, and 0 once the target is reached.
  A value far beyond the time the team will run the experiment (many months, years) means that the target is out of reach at this traffic: the experiment cannot detect an effect of that size in a useful time (C8).
- `exposure_estimate_config.conversionRateInputType` — `manual` means that the user typed the baseline and the daily exposures.
  Both numbers above then come from that input: `recommended_running_time` is the whole estimated length, not the days left, and neither number is updated during the run.
  The same holds for numbers that were written when the experiment was created, through the API or by an agent, until someone opens the launched experiment.
  A page load in the first day of the run, or before 100 exposures, also saves the whole estimated length, until a later page load replaces it.
  A `recommended_running_time` above 0 on an experiment whose exposures have passed the target is one of these cases, or a value saved by a page load before the target was reached.
- `minimum_detectable_effect` — the experiment's own value, or the project default that was copied in when the experiment was created.
  When it is absent the project default applies.
  `experiment-setup-context` returns that default (`team_defaults`) where the tool is available. Otherwise ask the user.

In automatic mode the product estimates the target again from the experiment's own data whenever someone opens the page of a launched experiment, and saves it.
So the target moves during the run, and the label a user saw last week can differ from today's stored numbers.
Compare the minimum detectable effect with the effect the user hopes for.

**Co-occurs with:** C1 (the same people read results early), C2.

**Recommendation.**

- Explain the label first: a target for sample size, not a verdict.
- When the minimum detectable effect is far above a realistic effect, the target is too small.
  Lower it to the smallest effect worth shipping for: the required sample grows with the inverse square, so half the effect needs four times the sample.
- When the decision metric is not the first primary metric, the estimate is for the wrong metric.
- The rule of thumb behind the calculator: the sample per variant is about 16 × variance / (absolute effect)².
  For a conversion rate the variance is p × (1 − p).

## C13 — Statistics settings that change how a result reads (sequential testing, CUPED, baseline variant) [HIGH]

Three settings change what the numbers on the page mean.
Each is set on the experiment.
Sequential testing and CUPED fall back to the project default where the experiment does not set them. The baseline falls back to `control`.

**Sequential testing** (`stats_config.frequentist.sequential_testing_enabled`). Frequentist only.

- The p-value and the interval stay valid however often the result is read.
  C1's peeking warning does not apply.
- The price is a wider interval than a fixed-horizon test gives on the same data.
  "The calculator says significant and PostHog does not" is expected (C11).
- The interval narrows as the sample grows.
  Its extra width over a fixed-horizon interval is smallest when the two arms of a comparison together hold about the tuning parameter's sample size (`sequential_tuning_parameter`, default 5,000 or the project's default), and larger far from it.
  An experiment with a much larger sample and the default value has a wider interval than it needs.
- A p-value of exactly 1.000 is normal `[MEDIUM]`: the value stays at 1 until the evidence crosses a threshold.

**CUPED** (`stats_config.cuped.enabled`).

- It adjusts the metric values with each person's behavior before exposure, and narrows the interval when that behavior predicts the metric.
- It does not change who is in the experiment or which events count.
- The effect and the interval come from adjusted values, so no query on raw events and no calculator reproduces them (D1 in `numbers-vs-sql.md`).
- It applies to mean metrics and to ordered funnels. Ratio and retention metrics are never adjusted.
  A mean metric with a `threshold`, a mean metric on a session property (such as `$session_duration`) and a funnel with a data-warehouse step are not adjusted either.
- It reads a look-back window before each exposure (14 days by default), which makes the calculation heavier.

**Baseline variant** (`stats_config.baseline_variant_key`).

- Every comparison is against the baseline. That is `control`, or the flag's first variant when it has no `control`, unless the experiment names another variant.
- After a change of the baseline every delta, interval and significance is recalculated against the new one, and the baseline itself shows no delta.
  "Control shows a lift" and "all signs flipped" are this setting.

<!-- Source for maintainers (may rot): _resolve_sequential_settings in products/experiments/backend/hogql_queries/utils.py;
products/experiments/backend/hogql_queries/cuped_config.py; get_baseline_variant_key in
products/experiments/backend/hogql_queries/__init__.py. -->

**Evidence to gather.** `stats_config` in `experiment-get`, and the experiment's change history when a result moved without new data: a setting changed on the page recalculates the whole run (D8 in `numbers-vs-sql.md`).
What a missing key means depends on the key:

- A missing `method` reads as Bayesian, and a missing confidence level as 95%.
  The project's defaults for both are copied into an experiment when it is created.
- `frequentist.sequential_testing_enabled` and `cuped` fall back to the project's current default.

`experiment-setup-context` returns the project's defaults (`team_defaults`) where that tool is available.
Otherwise ask the user to read the project's experiment settings.
A p-value of exactly 1.000 on a metric of a Frequentist experiment is a sign of sequential testing. A p-value below 1 does not rule it out.
