# Interpreting experiment results

## Getting results

Start with `experiment-metrics-recalculation-latest-retrieve`.
It takes the experiment ID.
It returns the most recent terminal run: a completed run, or a failed run that still carries the metrics that succeeded.
Each entry carries per-variant exposures, sums, and `significant`.
The run also carries `query_to`, the data freshness cutoff the numbers were computed against.
Use `query_to` to tell the user how fresh the results are.

The interval and probability fields depend on the `method` field on each variant result.
Read `method` before you read them.

- `bayesian`: `chance_to_win` and `credible_interval`.
- `frequentist`: `p_value` and `confidence_interval`.

The other method's fields are absent, not null.
Their absence is not missing data.
When a statistic is null, read `validation_failures` on that variant.
A non-empty list means the statistics test did not run, and the list says why.

The entries are keyed by `metric_uuid`.
They do not carry the metric name, its primary or secondary role, or its goal direction.
Call `experiment-get` and map each `metric_uuid` to its metric before you interpret the numbers.

- Name and role: the `metrics` array holds the primary metrics, and `metrics_secondary` holds the secondary ones.
  A saved metric's role is in `saved_metrics[].metadata.type`.
- Goal: each metric's `goal` is `increase` or `decrease`.
  It says which direction is an improvement.

Without the goal you cannot tell an improvement from a regression.
A decrease on a `decrease` metric is a win, not a loss.

Check that the run is complete before you report anything.
The response can carry partial data, and a missing metric looks the same as a metric the experiment does not have.

- `status`: `failed` means at least one metric failed, and the run still carries the metrics that succeeded.
- `total_metrics`, `completed_metrics`, `failed_metrics`: compare them.
  When `completed_metrics` is less than `total_metrics`, some metrics are missing, failed, or still running.
- `metric_errors`: a map of `metric_uuid` to error detail for the metrics that failed.
  A failed metric also appears in `results` with `result: null`.
- `active_run`: a run is executing now.
  When the results come from an earlier terminal run, they are the previous numbers, not this run's.
  On the first ever run there is no earlier run, so `status` is `pending` and `results` is empty.
  Poll `active_run.id` with `experiment-metrics-recalculation-retrieve` for progress.
- `result_source`: `timeseries_fallback` means the experiment never completed a real run, and the numbers are a cold-start placeholder.
  It can cover fewer metrics than the experiment has, while still reading `completed`.
  Say so when you report them.
  A real run reads `recalculation`.

Do not report a winner or recommend shipping from a partial run.
Recommend shipping only when `status` is `completed`, `completed_metrics` equals `total_metrics`, `failed_metrics` is `0`, and `metric_errors` is empty.
When a metric is missing, failed, or pending, name that metric and do not decide from the metrics that did return.
For a `timeseries_fallback`, or when `query_to` is old, call `experiment-metrics-recalculation-create` and poll before a ship decision.

This call is a pure read and never starts a calculation, so the numbers can be stale.
When `query_to` is old, or the user wants fresh numbers, call `experiment-metrics-recalculation-create` and then poll.

A 404 has two causes, and each one needs a different answer.

- The experiment ID does not resolve in this project.
  Call `experiment-get` to check the ID.
  Say that the ID does not resolve.
  Do not report that the experiment has no results.
- The experiment resolves, but it has never completed a run.
  Nothing starts the first run on its own.
  Waiting produces nothing.
  For a launched experiment, call `experiment-metrics-recalculation-create`, then poll.
  For a draft experiment, say that results start after launch.

This 404 does not mean that the experiment is too young.
An experiment with results returns small numbers instead of a 404.

### Day-by-day history of one metric

Use `experiment-timeseries-results` only when the user asks how a single metric moved over the course of the experiment.
It needs `metric_uuid` and `fingerprint` from the experiment's `metrics` array, so call `experiment-get` first.
It covers one metric per call, so it cannot answer "is this winning?" across every metric.

## Statistical significance

- Only recommend shipping when results are statistically significant
- Bayesian experiments report probability of each variant being best
- Frequentist experiments report p-values and confidence intervals

Do NOT recommend shipping just because a variant is "winning" — check significance first.

## Sample size and runtime

- Experiments typically need 1-2 weeks minimum for reliable results
- Small sample sizes produce unreliable results — warn the user
- If the experiment just launched, set expectations about when results will be meaningful

## Multiple metrics

Each metric may tell a different story. Present the full picture:

- Primary metric improved but secondary degraded? Call it out.
- Some metrics significant, others not? Report honestly.
- Don't cherry-pick the metric that supports shipping.

## Decision framework

| Situation                                             | Recommendation                                               |
| ----------------------------------------------------- | ------------------------------------------------------------ |
| Clear winner, significant results, sufficient runtime | Ship the winning variant                                     |
| No significant difference after 2+ weeks              | End as inconclusive — the variants don't meaningfully differ |
| Primary improved but guardrail metric degraded        | Flag the trade-off, let the user decide                      |
| Results are borderline significant                    | Recommend continuing to run, or end as inconclusive          |
| Very early results (< 1 week)                         | Too early to draw conclusions — wait                         |

## What NOT to do

- Don't declare an experiment failed based on early results
- Don't recommend shipping based on borderline significance
- Don't ignore secondary/guardrail metrics when primary looks good
- If results are ambiguous, say so — let the user decide
