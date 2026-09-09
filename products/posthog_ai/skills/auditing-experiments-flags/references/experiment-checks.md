# Experiment checks

Run these checks against each experiment fetched via `experiment-get`.
`experiment-list` returns a thin summary that omits the fields below, so it resolves IDs only.

For each check, the "Look at" section tells you which fields to inspect on the experiment object.
The "Findings" section lists what to report and at what severity.

---

## 1. Metric setup

Verifies the experiment has a valid primary metric configuration.

**Look at**: `metrics`, `metrics_secondary`, `saved_metrics`

Shared metrics arrive in `saved_metrics`, classified by each entry's `metadata.type`.
An entry counts as primary when `metadata.type` is `primary` or absent, and as secondary otherwise.
Count these alongside the inline metrics.

**Findings**:

- **No metrics at all**: `metrics`, `metrics_secondary`, and `saved_metrics` are all empty or missing.
  - Severity: CRITICAL · Category: Correctness
  - Report: "This experiment has no metrics configured. Results cannot be measured."
  - Action: Add at least one primary metric before launching.

- **Secondary metrics only**: The experiment has no primary metric (`metrics` is empty and no `saved_metrics` entry counts as primary) but does have a secondary one, in `metrics_secondary` or in a `saved_metrics` entry that counts as secondary.
  - Severity: WARNING · Category: Process
  - Report: "This experiment has secondary metrics but no primary metric. There is no primary success criterion."
  - Action: Promote one secondary metric to primary or add a new primary metric.

---

## 2. Flag integration

Verifies the experiment's linked feature flag is valid and correctly configured.

**Look at**: `feature_flag` (the linked flag object or ID), `start_date`, `end_date`, `status`.
Fetch the flag via `feature-flag-get-definition` if only an ID is available.

**Findings**:

- **Missing flag**: `feature_flag` is null or missing.
  - Severity: CRITICAL · Category: Correctness
  - Report: "This experiment has no linked feature flag. Traffic cannot be split."
  - Action: Create and link a feature flag.

- **Paused mid-run**: The experiment is running (`start_date` is set and `end_date` is null) but the linked flag has `active` false.
  Prefer the experiment's own `status` field when the payload carries it: this is the `paused` value.
  - Severity: WARNING · Category: Correctness
  - Report: "This experiment is running but its linked feature flag is inactive, so traffic is not being split."
  - Action: Re-enable the flag to resume, or end the experiment.

- **Deleted flag**: The linked flag has `deleted` set to true.
  - Severity: CRITICAL · Category: Correctness
  - Report: "The linked feature flag has been deleted."
  - Action: Create a new flag and re-link it, or archive the experiment.

Note: An inactive flag on its own is not a finding, so do not report one without the running check above.
The product creates the linked flag inactive for every draft and activates it at launch, and archiving an experiment can disable its flag on purpose.
Both states are correct, and a stale draft is already reported by check 3.

Note: Do not compare the experiment's `parameters.feature_flag_variants` with the flag's `filters.multivariate.variants`.
The API builds the first from the second on every read, so the two always agree and the comparison reports nothing.
Variant and rollout changes are detected from the activity log in check 7.

Note: The experiment records `conclusion` as a status only (won, lost, inconclusive, stopped_early, or invalid) and never records which variant it recommends.
An `end_date` also does not imply a conclusion, because ending an experiment can leave `conclusion` null.
So there is no intended variant to compare the flag's rollout against.

---

## 3. Lifecycle

Checks for experiments stuck in unproductive states.

**Look at**: `created_at`, `start_date`, `end_date`, `description` (for hypothesis)

**Findings**:

- **Stale draft**: `start_date` is null (never launched) and `created_at` is more than 7 days ago.
  - Severity: INFO · Category: Cleanup
  - Report: "This experiment has been in draft for N days without being launched."
  - Action: Launch the experiment or delete it.

- **No hypothesis**: `description` is empty or missing, and the experiment has been launched (`start_date` is set).
  - Severity: INFO · Category: Process
  - Report: "This launched experiment has no hypothesis documented in its description."
  - Action: Add a hypothesis to document what you expect to learn.

---

## 4. Stopped with active flag

Checks for experiments that have ended but whose flags are still active and splitting.

**Look at**: `end_date`, `archived`, and the linked flag's `active` status and variant rollout.

**Findings**:

- **Ended but flag still active and splitting**: `end_date` is set (experiment ended), but the linked flag is still `active: true` and has multiple variants with non-zero rollout percentages.
  - Severity: WARNING · Category: Waste
  - Report: "This experiment ended on [date] but its flag is still actively splitting traffic."
  - Action: Roll out the winning variant at 100% or disable the flag.

---

## 5. Minimum duration

Checks whether a running experiment has collected enough data.

**Look at**: `start_date`, `end_date`

**Findings**:

- **Very short run**: `start_date` is set, `end_date` is set, and the duration is less than 7 days.
  - Severity: WARNING · Category: Process
  - Report: "This experiment ran for only N days. Results may not be statistically significant."
  - Action: Consider whether the sample size was sufficient before drawing conclusions.

- **Short run**: Duration is between 7 and 14 days.
  - Severity: INFO · Category: Process
  - Report: "This experiment ran for N days. Consider whether the sample size is sufficient."
  - Action: Review statistical significance before concluding.

---

## 6. Stats config

Checks for unusual statistical configuration.

**Look at**: `start_date`, `end_date` (or current date if still running), `parameters.stats_config`

**Findings**:

- **Long-running experiment**: The experiment has been running for more than 30 days (calculated from `start_date` to `end_date` or today if still running).
  - Severity: INFO · Category: Process
  - Report: "This experiment has been running for N days. Long-running experiments can accumulate confounding factors."
  - Action: Review whether this experiment still needs to run or if a conclusion can be drawn.

---

## 7. Activity history

Checks for flag modifications that may have affected experiment integrity.
**These checks require activity logs. If activity logs are not available, skip this entire check and note it was skipped.**

**Look at**: Activity log entries for the linked feature flag, filtered by the experiment's run period (`start_date` to `end_date` or today).

The activity endpoint returns the 10 newest entries per page, ordered newest first.
Page it with `limit` and `page` until `next` is null, or until the oldest entry you read predates the experiment's run period.
One unpaginated call reads only the 10 newest entries, so it can miss every in-window change on a flag that was modified after the experiment ended.
Report the activity checks as partial if a page fails.

**Findings**:

- **Pre-run flag changes**: The flag was modified between experiment creation and launch.
  - Severity: INFO · Category: Process
  - Report: "The flag was modified N times before the experiment launched."
  - Action: Informational — verify the flag was in the intended state at launch.

- **Mid-run rollout changes**: The flag's rollout percentages were changed while the experiment was running.
  - Severity: WARNING · Category: Correctness
  - Report: "The flag's rollout percentages were changed during the experiment run."
  - Action: This may have affected results. Note the change date and consider its impact on the data.

- **Mid-run variant changes**: Variants were added or removed from the flag while the experiment was running.
  - Severity: CRITICAL · Category: Correctness
  - Report: "Variants were added or removed from the flag during the experiment run."
  - Action: This likely invalidated the experiment. Consider restarting with a clean flag.

- **Mid-run flag toggles**: The flag was toggled on/off during the experiment run.
  - Severity: WARNING · Category: Correctness
  - Report: "The flag was toggled on/off during the experiment run, creating periods with no traffic splitting."
  - Action: Review whether the interruption affected results significantly.

- **Mid-run targeting changes**: The flag's targeting conditions (properties, groups) were modified during the run.
  - Severity: WARNING · Category: Correctness
  - Report: "The flag's targeting conditions were changed mid-experiment, altering the eligible population."
  - Action: Review whether the targeting change affected the experiment's statistical validity.
