# Experiment checks

Run these checks against each experiment fetched via `read_data("experiments", id)` or `list_data("experiments")`.

For each check, the "Look at" section tells you which fields to inspect on the experiment object.
The "Findings" section lists what to report and at what severity.

---

## 1. Metric setup

Verifies the experiment has a valid primary metric configuration.

**Look at**: `metrics`, `metrics_secondary`

**Findings**:

- **No metrics at all**: Both `metrics` and `metrics_secondary` are empty or missing.
  - Severity: CRITICAL · Category: Correctness
  - Report: "This experiment has no metrics configured. Results cannot be measured."
  - Action: Add at least one primary metric before launching.

- **Secondary metrics only**: `metrics` is empty but `metrics_secondary` has entries.
  - Severity: WARNING · Category: Process
  - Report: "This experiment has secondary metrics but no primary metric. There is no primary success criterion."
  - Action: Promote one secondary metric to primary or add a new primary metric.

---

## 2. Flag integration

Verifies the experiment's linked feature flag is valid and correctly configured.

**Look at**: `feature_flag` (the linked flag object or ID), and fetch the flag via `read_data("feature_flags", feature_flag_id)` if only an ID is available.

**Findings**:

- **Missing flag**: `feature_flag` is null or missing.
  - Severity: CRITICAL · Category: Correctness
  - Report: "This experiment has no linked feature flag. Traffic cannot be split."
  - Action: Create and link a feature flag.

- **Inactive flag**: The linked flag exists but `active` is false.
  - Severity: WARNING · Category: Correctness
  - Report: "The linked feature flag is inactive (paused). Traffic is not being split."
  - Action: Re-enable the flag or end the experiment.

- **Deleted flag**: The linked flag has `deleted` set to true.
  - Severity: CRITICAL · Category: Correctness
  - Report: "The linked feature flag has been deleted."
  - Action: Create a new flag and re-link it, or archive the experiment.

- **Uneven variant split**: The linked flag's variant rollout percentages differ from the experiment's expected split by more than 5 percentage points.
  Compare the flag's `filters.multivariate.variants` rollout percentages to the experiment's `parameters.feature_flag_variants`.
  - Severity: WARNING · Category: Correctness
  - Report: "Variant rollout percentages on the flag don't match the experiment's expected split."
  - Action: Adjust the flag's variant percentages to match the experiment configuration.

- **Variant mismatch**: The variant keys in the experiment's `parameters.feature_flag_variants` don't match the variant keys in the flag's `filters.multivariate.variants`.
  - Severity: CRITICAL · Category: Correctness
  - Report: "Variant keys differ between the experiment and its linked flag."
  - Action: Align variant keys between the experiment and its flag.

---

## 3. State consistency

Checks for contradictions between an experiment's conclusion and its current flag state.

**Look at**: `end_date` (non-null means concluded), `archived`, `parameters.recommended_variant`, and the linked flag's active state and variant configuration.

**Findings**:

- **Conclusion contradicts shipped variant**: The experiment concluded with a recommended variant (in `parameters.recommended_variant`), but the flag is rolled out to a _different_ variant at 100%.
  - Severity: WARNING · Category: Correctness
  - Report: "The experiment concluded recommending variant 'X' but the flag is rolled out to variant 'Y'."
  - Action: Review and align the flag's rollout with the experiment conclusion.

- **Concluded but still splitting**: The experiment has an `end_date` (it's concluded) but the linked flag still has multiple variants with non-zero rollout (traffic is still being split).
  - Severity: WARNING · Category: Waste
  - Report: "This experiment has concluded but its flag is still splitting traffic between variants."
  - Action: Roll out the winning variant or disable the flag.

---

## 4. Lifecycle

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

## 5. Stopped with active flag

Checks for experiments that have ended but whose flags are still active and splitting.

**Look at**: `end_date`, `archived`, and the linked flag's `active` status and variant rollout.

**Findings**:

- **Ended but flag still active and splitting**: `end_date` is set (experiment ended), but the linked flag is still `active: true` and has multiple variants with non-zero rollout percentages.
  - Severity: WARNING · Category: Waste
  - Report: "This experiment ended on [date] but its flag is still actively splitting traffic."
  - Action: Roll out the winning variant at 100% or disable the flag.

Note: This is related to but distinct from "concluded but still splitting" in check 3.
Check 3 focuses on the contradiction with the conclusion; this check focuses on the resource waste of an ended experiment still consuming flag evaluations.

---

## 6. Minimum duration

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

## 7. Stats config

Checks for unusual statistical configuration.

**Look at**: `start_date`, `end_date` (or current date if still running), `parameters.stats_config`

**Findings**:

- **Long-running experiment**: The experiment has been running for more than 30 days (calculated from `start_date` to `end_date` or today if still running).
  - Severity: INFO · Category: Process
  - Report: "This experiment has been running for N days. Long-running experiments can accumulate confounding factors."
  - Action: Review whether this experiment still needs to run or if a conclusion can be drawn.

---

## 8. Activity history

Checks for flag modifications that may have affected experiment integrity.
**These checks require activity logs. If activity logs are not available, skip this entire check and note it was skipped.**

**Look at**: Activity log entries for the linked feature flag, filtered by the experiment's run period (`start_date` to `end_date` or today).

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
