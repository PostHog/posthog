# Is a downstream effect real or noise?

**Symptom:** a funnel step the feature doesn't touch (e.g. `event page → checkout`) shows a lift,
often while the step it _does_ touch is flat. The customer suspects a measurement bug.

## Why that leg isn't a clean comparison

A rate measured between two mid-funnel steps only counts users who already reached the earlier step,
and reaching it happens _after_ randomization and can be nudged by the treatment. So the leg compares
two groups shaped by the experiment, not the randomized groups, and a gap can appear there with no
real effect on the downstream action. It can even read _more_ significant than the honest metric,
because it's a smaller, more-selected denominator.

**Trust the randomized endpoint — exposure → final step, counting everyone assigned — over any rate
measured between two mid-funnel steps.** PostHog computes significance from the first step to the last
step for exactly this reason (see `numbers-vs-sql.md` D2 in the `diagnosing-experiment-results`
library).

## Three checks — any one failing points to noise

1. **Non-user split.** Recompute the effect among users who never fired the feature-interaction
   event. If the _between-variant_ gap is still there, the feature can't be causing it. State it as a
   between-variant comparison restricted to non-users — _not_ "non-users convert more".
2. **Dose-response.** Rank the variants by actual feature usage. A real effect is strongest where the
   feature is used most; an effect that's absent in the high-usage arm and present in a barely-used
   arm is not causal.
3. **Cohort stability.** Split the outcome by week of first exposure. A real effect holds its sign and
   rough size across cohorts; one that flips ahead/behind or lives in a single cohort is noise.

## Recommend

Report the randomized exposure → outcome number (with its win probability) as the verdict, explain
the conditioning trap in plain terms, and — if the checks point to noise — advise against shipping on
the downstream figure and to keep running to the pre-planned sample.
