# Remediation actions

For each finding type, recommend the appropriate action.
Phase 1 is read-only — all actions require the user to make changes manually.

## Experiment actions

| Finding                                | Action                                                                                                                     |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| No metrics configured                  | Add at least one primary metric before launching. Link to the experiment's metrics tab.                                    |
| Secondary metrics only                 | Promote one metric to primary or add a new primary metric.                                                                 |
| Missing feature flag                   | Create and link a feature flag to this experiment.                                                                         |
| Inactive (paused) flag                 | Re-enable the linked feature flag, or end the experiment if it's no longer needed.                                         |
| Deleted flag                           | The experiment's flag was deleted. Create a new flag and re-link, or archive the experiment.                               |
| Uneven variant split                   | Adjust variant rollout percentages on the linked flag to match the experiment's expected split.                            |
| Variant mismatch                       | Align the variants between the experiment and its linked flag — they must use the same variant keys.                       |
| Conclusion contradicts shipped variant | Review the experiment conclusion and the flag's current state. Either update the conclusion or change the flag to match.   |
| Concluded but still splitting          | The experiment has a conclusion but the flag is still splitting traffic. Roll out the winning variant or disable the flag. |
| Stale draft                            | This experiment has been in draft for over 7 days. Either launch it or delete it.                                          |
| No hypothesis                          | Add a hypothesis to document what you expect to learn.                                                                     |
| Stopped with active flag               | The experiment has ended but its flag is still active. Roll out the winning variant or disable the flag.                   |
| Running less than 7 days               | Wait for at least 7 days of data before drawing conclusions.                                                               |
| Long-running experiment (>30 days)     | Review whether this experiment still needs to run. Consider concluding it or adjusting the timeline.                       |

## Flag actions

| Finding                                 | Action                                                                                                                                                     |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Fully rolled out (100%, no conditions)  | This flag always evaluates to the same value. Remove it from code and hardcode the value.                                                                  |
| Stale by usage (not called in 30+ days) | This flag isn't being evaluated. Remove it from code or investigate why it's not being called.                                                             |
| Stale draft (inactive, 30+ days old)    | This flag was created but never activated. Delete it or activate it.                                                                                       |
| Orphaned experiment flag                | All linked experiments are completed. Roll out the winning variant or disable the flag.                                                                    |
| Variant sum != 100%                     | The multivariate rollout percentages don't add up to 100%. Adjust the variant percentages.                                                                 |
| Dead variant (0% rollout)               | A variant has 0% rollout on a non-experiment flag. Either give it traffic or remove it.                                                                    |
| Dead condition (0% rollout)             | A release condition has 0% rollout. Either increase it or remove the condition.                                                                            |
| Manual rollout on experiment flag       | An experiment flag has manual rollout overrides. This can invalidate experiment results. Remove manual overrides and let the experiment control the split. |
| Toggle instability (>3 toggles)         | This flag has been toggled on/off many times. Consider whether the flag is being used as intended.                                                         |
| High config churn                       | This flag is being modified very frequently. Consider stabilizing the configuration.                                                                       |
