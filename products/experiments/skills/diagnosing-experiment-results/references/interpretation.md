# Significance & interpretation traps

How to read PostHog experiment results without falling into common interpretation pitfalls.

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
- C10 — Ship-variant default does not consider any metric result
- C11 — External calculator disagrees with PostHog

## C1 — Peeking / early stopping [HIGH]

Watching results live and ending the experiment the moment it looks significant **inflates false
positives** — you're giving randomness more chances to look significant.

In Bayesian: PostHog applies a minimum-sample-size guard before analysis proceeds — a low
per-variant floor plus a proportion-validity rule of `np > 5` and `n(1-p) > 5` for
funnel/proportion metrics (legacy stats module: 100 exposures per variant via
`FF_DISTRIBUTION_THRESHOLD`). Early swings within that band are still noise — in the early days
of the experiment, significance can flip back and forth a lot.

**Recommend:**

- Predetermine duration _before_ launching. Use the running-time calculator on the experiment.
- For the duration calculator: shows "Pending" until at least 1 day **and** 100 exposures.
- Frequentist: PostHog uses α=0.05 by default → a single metric has ~5% chance of false-positive
  significance even when nothing changed.
- Don't treat 0.05 as a hard cliff. It's a convention, not a meaningful threshold by itself —
  results just below and just above are close to equivalent in evidence.

## C2 — Low-volume variance (looks broken but isn't) [MEDIUM]

**Symptom:** few hundred or fewer exposures per variant; the visible split looks badly off (a
roughly 2-to-1 skew at a few dozen exposures is well within normal noise).

**Mechanism:** With low samples per variant (rule of thumb: under a thousand), the visible split can
swing widely from the configured ratio — deterministic-hash variance is large at small samples.
PostHog's calculations account for this; the visible ratio is not a bug.

**Funnel/proportion-specific validity gates.** Beyond the per-variant exposure floor, funnel metrics
also need the normal approximation to hold:

- At least 5 conversions per variant.
- `n * p ≥ 5` _and_ `n * (1 - p) ≥ 5`, where `p` is the conversion rate.

If a variant has very few converters (or, symmetrically, almost everyone converted), the test will
refuse to report — not a bug. The fix is the same: more exposures, or accept that the result isn't
ready.

<!-- Source for maintainers:
- products/experiments/stats/frequentist/utils.py around the n*p / n*(1-p) check;
- products/experiments/stats/bayesian/tests.py mirrors the rule and raises StatisticError when successes < 5. -->

**Recommend:** wait. Run longer or increase rollout. Don't read estimates before the running-time
calculator threshold (≥1 day **and** ≥100 exposures).

## C3 — A/A test showing significance [MEDIUM]

A/A tests _should_ almost never show significance. If the user reports their A/A test is showing a
significant difference, work through:

1. **Which stats module is the experiment on?** Experiments created before January 2025 may be on
   the _legacy_ Bayesian module. The new module (rolled out January 2025) corrected several
   methodological issues that produced over-significant A/A tests in the legacy module — its A/A
   false-positive rate is much closer to the expected α.
2. **Is it actually random chance?** Even with a correct methodology, a small share of
   metric-variant pairs in an A/A test will look significant by chance (this is the false-positive
   rate, around α). With multiple metrics × multiple variant pairs, _expect_ some to flicker
   significant. C4 below.
3. **Is it actually different exposure handling?** If `multiple_variant_handling = "exclude"` and the
   A/A flag is producing `$multiple` users (from identity fragmentation, A3 in `bias-and-skew.md`),
   the asymmetric exclusion can produce real differences between two arms that should be identical.
4. **Is the implementation correct?** A large multiple-fold gap between equal-sized variants is
   **extremely unlikely** to be random — instrumentation is the more likely cause. A specific
   shape worth checking: **data-warehouse-source metrics where per-user exposures are joined to a
   per-group warehouse table** (`ExperimentDataWarehouseNode` with `events_join_key: $group_<n>`
   on the exposure side and `data_warehouse_join_key` on a group-keyed metric table). The LEFT
   JOIN duplicates each per-group row by the number of exposed users in that group, so a `sum`
   metric over-counts proportional to per-group user count. If user counts are balanced but per-group
   user counts aren't, the sum can swing 5–30% even on a true A/A — and Bayesian reads that as
   significant under the i.i.d. assumption. _Detect:_ read the generated `clickhouse_sql` from
   `experiment-results-get`, look for an `exposures` CTE joined per-user to a metric table where
   the metric is group-aggregated upstream. _Sanity check:_ re-aggregate the warehouse table by
   org/group once (deduped) and compare to the per-user sum; a large gap confirms repeated-row
   inflation.

**Recommend:** if conditions 1–3 don't explain the result, investigate instrumentation rather than
assuming the methodology is wrong.

## C4 — Multiple comparisons (no correction across variants or metrics) [HIGH]

PostHog **does not** apply multiple-comparisons correction:

- Across variants — each test variant is compared to control independently
- Across metrics — each metric is tested independently

So with many metrics or many variants, the chance of _some_ spurious significance grows. Concrete
math at α=0.05 (the default): with 5 independent metrics, the chance of at least one false-positive
is ~23%; with 10 metrics, ~40%. (Confidence level is configurable — see C6.)

**Recommend:**

- Define a small set of planned, hypothesis-driven metrics up front.
- Treat results as a **pattern** across planned metrics, not a single "gotcha" significant metric.
- Add guardrail metrics as secondary, not primary.
- Be especially wary of metrics added after seeing data — that's p-hacking. See `mid-run-changes.md`.

## C5 — Bayesian interpretation traps [HIGH]

PostHog defaults to Bayesian. Common misreads:

- **"96% chance to win"** is about _direction_ (test is better than control), **not** the magnitude of
  the lift. Read the **credible interval** alongside it.
- **Don't ship the moment chance-to-win flips green** — the minimum-sample guard means early flips are
  within the noise band.
- **Non-informative priors.** PostHog uses non-informative priors (mean 0, large variance). Early swings
  aren't the prior pushing things around — they're the data being sparse.
- **Legacy methodology (pre-2025 experiments).** Experiments created before January 2025 may use
  the legacy methodology (different multivariate semantics, different significance gates). If a
  user is reading results from an experiment in that window and the numbers look different than
  expected, see PostHog's
  [legacy-methodology docs page](https://posthog.com/docs/experiments/legacy-methodology).

## C6 — Frequentist interpretation traps [HIGH]

PostHog has Frequentist support (rolled out June 2025). Set in `stats_config`. Quick rules:

- 95% CI **doesn't cross 0** → significant vs control. CI **crosses 0** → not significant.
- PostHog uses **Welch's t-test** as the default — it handles unequal variance between groups, unlike
  Student's t-test (which assumes equal variance).
- α = 0.05 by default → ~5% chance of false-positive on a single metric.
- **Confidence level is configurable per team (and per experiment).** Valid values are `0.90`,
  `0.95`, `0.99` — set via `default_experiment_confidence_level` on the team or `confidence_level`
  on the experiment's `stats_config`. If a user reports a p-value of 0.07 as "significant", they're
  likely on the 90% setting; check before debugging the math.
- Significance is per-metric. With many metrics, expect some to flicker in/out as the sample grows.

## C7 — Bayesian vs Frequentist confusion [MEDIUM]

A frequent source of confusion:

- **Overlapping confidence intervals do not imply non-significance in Bayesian.** Overlapping intervals
  are a _frequentist_ heuristic. In Bayesian, significance is determined by win probability, so
  overlapping credible intervals can still indicate a clear winner.
- **p-values don't apply in Bayesian.** A question about "p < 0.05" is a frequentist frame. If the
  experiment is on Bayesian (default), redirect to win probability + credible interval.
- **Frequentist is opt-in.** Most experiments are Bayesian unless `stats_config` explicitly selects
  Frequentist.

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
this directly via `experiment-timeseries-results`.

For the qualitative part (replays / intuition), invoke the
`posthog:analyzing-experiment-session-replays` skill — it surfaces variant-level replay patterns and
is the right tool when the call is "primary metric is up, no guardrail regression, do we ship?"

## C9 — "Significance reached" notification is not a green light to ship [HIGH]

PostHog can mark a metric as significant and send a notification well before the experiment has
accumulated enough data for the result to be stable. The verdict can revert as the sample grows.
Treat the notification as a _prompt to review_, not an _instruction to ship_.

Before acting on a significance notification, check **all of**:

- **Participants per variant.** A minimum-sample guard runs before analysis — a low floor plus
  `np > 5` / `n(1-p) > 5` for proportions (legacy stats module: 100 exposures per variant). That's
  a floor for analysis, not a sufficiency bar for shipping. Aim for the number the running-time
  calculator produced when the experiment was set up.
- **Days running.** For high-stakes ships, wait at least a full week before acting on a
  significance flag — shorter windows can swing as the sample grows. This is a working norm,
  not a product-enforced threshold.
- **Pre-planned duration.** If the experiment hasn't reached its planned end date, the significance
  is "current best estimate", not "settled".
- **Variant balance and `$multiple %`.** If A/B/skew (`bias-and-skew.md`) is in play, the
  significance verdict is suspect regardless of how large the gap looks.
- **Secondary metrics.** See C10.

When a previously-significant banner reverts to not-significant, that's not a bug — it's the same
analysis updated with more exposures. Explain the difference between _signal seen so far_ and
_result confirmed_.

## C10 — Ship-variant default does not consider any metric result [HIGH]

The End-experiment modal pre-fills the "Variant to keep" selector with the **first non-control
variant** (`feature_flag_variants[1].key`) every time it opens. There is no significance check,
no primary-metric direction check, and no guardrail check feeding that default. The "End
experiment" button is gated by **selecting a conclusion** (won / lost / inconclusive / stopped
early), _not_ by touching the variant selector — so a user who picks a conclusion and clicks
through without re-examining the variant ships the position-default variant. The only way to end
without rewriting the flag is to manually clear the variant selector before clicking; the modal
does not prompt for this.

The modal also asks **how** to release the chosen variant, with two radio options:

- **Roll out to the experiment population** (default, recommended) — variant distribution flips
  to 100/0 for the chosen variant; the flag's existing release conditions and per-user variant
  overrides are preserved. Only users already in the experiment's population see the variant.
- **Roll out to all users** — additionally prepends a catch-all release condition that overrides
  existing release conditions and per-user overrides. Anyone hitting the flag gets the chosen
  variant.

The release-mode choice doesn't read metrics either; the safer "experiment population" option is
the default. If the user clicks through without re-examining, they get the safer behavior on
release mode but still the position-default _variant_ — those are independent risks.

<!-- Source for maintainers: FinishExperimentModal in
frontend/src/scenes/experiments/ExperimentView/components.tsx. Verify before citing. -->

**Recommend:** before clicking "End experiment", do three things:

1. **Manually review every metric** — primary direction and significance, plus every secondary /
   guardrail metric. The position-default is not a "winner".
2. **Explicitly choose the variant to keep** — either re-pick from the dropdown (after reviewing
   metrics) or clear it to end without shipping. Don't accept the pre-fill silently.
3. **Confirm the release mode matches intent** — "experiment population" keeps the variant scoped
   to current targeting; "all users" overrides existing release conditions and per-user overrides.
   The default is the safer choice; flag any non-default selection back to the user explicitly.

If any guardrail is trending negative, or the primary isn't actually significant, the safe move
is to keep control rather than ship the position-default. This matters most for sophisticated
users who set guardrails for a reason — they are exactly the population the default will mislead.

## C11 — External calculator disagrees with PostHog [MEDIUM]

A common case: conversion counts from the experiment page get pasted into an online A/B
calculator, which returns a different verdict ("not significant" vs PostHog's "significant", or
vice versa).

Two questions to ask before debugging stats:

1. **Which methodology?** PostHog is **Bayesian by default**. Most online calculators are
   Frequentist. The two answer different questions; they will not agree on borderline cases. If the
   user wants a Frequentist comparison, flip `stats_config` and re-read (see C6).
2. **Are the inputs actually the same?** The numbers on the experiment page are post-scope —
   `$multiple` excluded, test accounts filtered, exposure-bounded date range, per-user aggregation
   for trends, conversion-window applied for funnels. An online calculator gets none of that — if
   the user typed in raw event counts they grabbed from SQL, the calculator and PostHog are
   computing on **different populations**, and disagreement is expected.

After confirming both methodology and inputs match, if the disagreement persists, treat it as a
real anomaly worth investigating with the experiment URL.
