---
name: diagnosing-experiment-results
description: "Diagnoses bias, anomalies, and strange-looking results on a specific PostHog experiment. Covers empty / 0-exposure experiments, sample ratio mismatch, identity fragmentation, multi-variant exposure, uneven-split exclusion bias, significance traps (peeking, A/A, Bayesian vs Frequentist), PostHog-vs-SQL discrepancies, and surprises after mid-run edits. Symptom-driven dispatch to the right diagnostic.\nTRIGGER when: user asks 'is my experiment biased?' or 'why 0 exposures?', references the bias banner, says a variant looks strange / wrong / off, sees significance flipping, notices PostHog numbers disagreeing with their SQL, sees an A/A test showing significance, or reports surprises after mid-run edits.\nDO NOT TRIGGER when: creating a new experiment (use creating-experiments), only configuring rollout (use configuring-experiment-rollout) or metrics (use configuring-experiment-analytics), or only asking lifecycle questions (use managing-experiment-lifecycle)."
---

# Diagnosing experiment results

This skill answers: **My PostHog experiment results look wrong, biased, or empty — what's going on?**

Match the user's complaint in the dispatch table, then read the matching reference file for the
diagnostic.

Each diagnostic in the reference files is tagged `[HIGH]`, `[MEDIUM]`, or `[LOW]` based on how
strongly it's verified — `[HIGH]` is verified directly in PostHog code, `[MEDIUM]` is partially or
team-source verified, `[LOW]` describes SDK/external behavior that wasn't verified here. Treat `[LOW]`
items as hypotheses to test, not facts to assert.

## Step 1 — Resolve the experiment

If the user refers to an experiment by name or description, load the `finding-experiments` skill first to
resolve it to a concrete ID.

Call `experiment-get` and pull these fields. They are inputs for almost every diagnostic:

- `parameters.feature_flag_variants[].rollout_percentage` — the variant split
- `parameters.rollout_percentage` — the overall rollout (% of users entering the experiment)
- `exposure_criteria.multiple_variant_handling` — defaults to `"exclude"` if absent
- `exposure_criteria.exposure_event` — `null` means default `$feature_flag_called`
- `exposure_criteria.filterTestAccounts` — defaults to `true`
- `feature_flag.active`, status (`draft` / `running` / `paused` / `stopped`), `start_date`, `end_date`
- `feature_flag.filters.groups[]` — for each group read `variant`, `properties`, and
  `rollout_percentage`. Any non-null `variant` is a forced-variant override on the matched cohort
  (release-condition assignment, not randomized) — surfaces A7. Watch for the severe shape (A7b): a
  variant-pinned group with broad/empty `properties` at high rollout, or no group left randomized
  (`variant: null`) / no release path to one arm — that starves the other variant (one arm gets ~0
  analyzable exposures). See `references/bias-and-skew.md`.
- `stats_config` — Bayesian (default) or Frequentist

## Step 1.5 — Pull a diagnostic snapshot (verify before asking)

Before asking the user clarifying questions, pull the diagnostic snapshot in
[references/diagnostic-snapshot.md](references/diagnostic-snapshot.md). Most diagnostics in this skill
can be confirmed or ruled out from that data without an interview.

## Step 2 — Match symptom to diagnostic

| User says...                                                                               | Diagnostic group                             |
| ------------------------------------------------------------------------------------------ | -------------------------------------------- |
| "Smaller variant looks biased" / banner says bias                                          | A — bias & skew                              |
| "Variant ratio doesn't match my split" / SRM warning                                       | A — bias & skew                              |
| "Why isn't it 50/50?" / "users in both groups"                                             | A — bias & skew                              |
| "Users in both control and test" / high `$multiple` %                                      | A — bias & skew                              |
| Multi-variant exposure on a server-rendered app                                            | A — bias & skew                              |
| Banner about feature-flag/experiment state mismatch                                        | A — bias & skew                              |
| "Migrating distinct_id" / "switching from anonymous to user_id" mid-run                    | A — bias & skew                              |
| Metric count is much smaller than exposures (e.g. 10× or 100× gap)                         | A — bias & skew (route here before D)        |
| "Experiment shows 0 / not enough data" / empty                                             | B — empty experiment                         |
| "Variant always undefined / false"                                                         | B — empty experiment                         |
| "$feature_flag_called fires but no exposures show up"                                      | B — empty experiment                         |
| "Experiment says running but exposures haven't moved in weeks/months"                      | B — empty experiment                         |
| "Significance keeps flipping as we run longer"                                             | C — interpretation traps                     |
| "Significance was declared, then it wasn't significant anymore"                            | C — interpretation traps                     |
| "30/16 split at 46 exposures, is this broken?"                                             | C — interpretation traps                     |
| "A/A test is showing significant results"                                                  | C — interpretation traps                     |
| "Many metrics — some significant, some not"                                                | C — interpretation traps                     |
| "Bayesian says 96% chance to win — should we ship?"                                        | C — interpretation traps                     |
| "Confidence intervals overlap — does that mean not significant?"                           | C — interpretation traps                     |
| "An external tool (significance calculator or AI agent) disagrees with PostHog"            | C — interpretation traps                     |
| "Should I ship? Primary is up but a secondary is down"                                     | C — interpretation traps                     |
| "PostHog numbers ≠ my SQL count"                                                           | D — numbers vs SQL                           |
| "Funnel says X% but my raw event count says Y"                                             | D — numbers vs SQL                           |
| "Sum of revenue looks wrong" / "breakdown shows 'none'"                                    | D — numbers vs SQL                           |
| "Recordings panel doesn't match the stats"                                                 | D — numbers vs SQL                           |
| "I applied a filter but the user count didn't change"                                      | D — numbers vs SQL                           |
| "I want to slice results by current person properties (as of now, not as of exposure)"     | D — numbers vs SQL                           |
| "Changed split / rollout / metric / criteria mid-run, now odd"                             | E — mid-run changes                          |
| "Ended/shipped — flag now flipped to 0/100 unexpectedly"                                   | E — mid-run changes                          |
| "Long-term metric moves opposite from primary"                                             | E — mid-run changes                          |
| "Retention metric counts users I didn't expect"                                            | E — mid-run changes                          |
| "Can't convert the feature flag back to a simple (boolean) flag after the experiment ends" | E — mid-run changes                          |
| "How do I restart an experiment with new variants?"                                        | E — mid-run changes                          |
| Metric line is rendered but the result block is empty / no chance-to-win or significance   | E — mid-run changes (E13 legacy methodology) |
| "Results won't load" / many metric rows show `data: null` (not a legacy experiment)        | Step 1.5 — diagnostic snapshot (null rows)   |

If the symptom is unclear, ask one clarifying question before picking. Most diagnostics have different fixes
— do not guess.

## Step 3 — Surface every diagnostic the evidence supports

After matching the symptom in Step 2 and reading the relevant reference file(s), list each diagnostic
that applies before recommending an action.

Surface co-occurring mechanisms independently — even when one is more salient, don't collapse them
into a single "wait" or "fix" recommendation. Different mechanisms have different fixes: a
_systematic_ bias (e.g. uneven-split + Exclude) doesn't resolve by waiting; a _statistical_ pattern
(e.g. small-sample variance) does. Bundling them leaves the bias in place after the user follows the
bundled advice.

Only list mechanisms that have a path to verification in the project state — config (from
`experiment-get`), snapshot data, activity log, or repo source. Config-derived mechanisms count: an
80/20 split with default `multiple_variant_handling="exclude"` is visible in `experiment-get` and is
therefore enumerable. Naming a mechanism with no source (e.g. SRM when the snapshot shows a clean
variant ratio) is not.

## Diagnostic groups

### A — Bias & skew

Variants don't look balanced, one variant looks biased, the in-app warning banner appeared, or users are
showing up under multiple variants. Covers the uneven-split + Exclude interaction, SRM, identity
fragmentation, bootstrap × `/decide` mismatch, and flag/experiment state inconsistency.

→ See [references/bias-and-skew.md](references/bias-and-skew.md)

### B — Empty experiment / 0 exposures / "not enough data"

A frequent pain point. Covers SDK call (wrong evaluation method, `identify()` timing, dedup),
exposure capture (custom event missing variant property, required properties, ad-blockers), and
exposure-criteria match (test-account filter, eligibility ordering, events firing before exposure).

→ See [references/empty-experiment.md](references/empty-experiment.md)

### C — Significance / interpretation traps

Significance flipping, A/A test showing significance, Bayesian vs Frequentist confusion, multiple
comparisons, low-volume variance, peeking / early stopping. Includes the legacy stats issue (A/A tests
historically over-fired before the new Bayesian module) and how the win-probability methodology changed in
Jan 2025 (single test vs control, not control vs all variants).

→ See [references/interpretation.md](references/interpretation.md)

### D — Numbers don't match (PostHog vs the user's SQL / raw count)

The experiment page applies an exposure scope, `$multiple` exclusion, test-account filter, and date range
that ad-hoc SQL almost never replicates. Covers funnel attribution (only first→last step counts for stats),
breakdowns (read from the exposure event, not the metric event), the "sum of revenue" mean-of-per-user
confusion, and the recordings-panel-vs-stats divergence.

→ See [references/numbers-vs-sql.md](references/numbers-vs-sql.md)

### E — Surprises after mid-run changes (incl. lifecycle and retention quirks)

Increasing rollout is safe; decreasing is caution; changing the variant split is an anti-pattern; adding
metrics mid-run is p-hacking; ship-variant can rewrite the flag in surprising ways; reset clears
results not the flag. Also covers retention-metric quirks (first-event-must-be-after-exposure design),
"matured users" filtering, and long-term vs short-term metric divergence.

→ See [references/mid-run-changes.md](references/mid-run-changes.md)

## Step 4 — Calibrate recommendations to experiment state

Surface diagnostics first (Step 3). Then recommend — but scope what you recommend to what the
experiment's current state permits.

- **Draft** — config changes are free; recommend and apply.
- **Running** — every change has a tradeoff. Explain the mid-run impact (anti-pattern? safe?
  user-visible?) before recommending. See `configuring-experiment-rollout` and its reference file
  `references/changing-distribution-after-launch.md` for the mid-run rules.
- **Stopped / archived** — the experiment AND its feature flag represent the documented outcome of
  the run. Recommendations are scoped to (a) interpretation of the existing data, (b) what to do for
  the _next_ experiment, or (c) explaining what happened.

On a stopped or archived experiment, don't preemptively offer reversal of a state mutation
(ship-variant flag rewrite, manual flag edit, reset, archive). If the user asks "why did X happen?",
explain X — don't append a "here's how to undo it" coda. That pattern assumes intent the user didn't
signal. Conditional offers like _"if this wasn't intended, you could…"_ or _"want me to revert it?"_
count as preemptive too — only the user explicitly naming the reversal action ("how do I undo this?",
"can I roll back ship-variant?", "how do I get the 50/50 split back?") is a request to surface
reversal mechanics.

Use consistent terminology: variant _split_ (between variants) is distinct from _rollout_ (overall %
entering); the `$feature_flag_called` exposure event is distinct from a _custom exposure event_; the
_Exclude_ / _First seen_ options control multivariate handling, not exposure.
