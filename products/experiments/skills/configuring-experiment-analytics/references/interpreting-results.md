# Interpreting experiment results

## Getting results

Use `experiment-timeseries-results` with the `metric_uuid` and `fingerprint` from the experiment's metrics array. Get the experiment first via `experiment-get` to find these values.

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
