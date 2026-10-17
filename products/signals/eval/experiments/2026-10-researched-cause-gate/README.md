# Researched-cause gate: mixed findings

## Question

After research, the PR-specificity gate receives the report summary as the researched cause.
Does the gate keep a finding out when the finding repeats the researched symptom but also reports a different problem?

## Cases

`fixtures/cases.json` holds one researched group and six new signals. All text is invented.

- The group: an expected 404 that the frontend handles, and that replay scanners misread as a blank page.
- Four signals must start their own report: three report the 404 next to a different blank UI, and one reports a 404 on a different endpoint.
- Two signals must join: a plain repeat of the 404, and a symptom that the researched cause explains.

The mixed cases are the hard ones.
The researched summary says that earlier "blank page" claims were scanner misreads.
Without a rule for this, the gate reads every blank-UI claim next to the 404 as already explained.

## Results

`claude-sonnet-5-5` at medium effort, five runs per case. See `results/summary.json`.

| Case                                | Expected | Before | After |
| ----------------------------------- | -------- | ------ | ----- |
| `roster_skeleton_blamed_on_404`     | reject   | 0/5    | 5/5   |
| `roster_skeleton_next_to_404`       | reject   | 3/5    | 5/5   |
| `other_blank_section_blamed_on_404` | reject   | 0/5    | 5/5   |
| `same_404_on_another_endpoint`      | reject   | 5/5    | 5/5   |
| `repeat_of_researched_404`          | accept   | 5/5    | 5/5   |
| `symptom_the_research_explains`     | accept   | 5/5    | 5/5   |

The rule change applies only to groups that have a researched cause.
The grouping e2e eval has no research step, so it does not cover this rule.

## Rerun

```bash
DEBUG=1 PYTHONPATH=. python products/signals/eval/experiments/2026-10-researched-cause-gate/run_trial.py
DEBUG=1 PYTHONPATH=. python products/signals/eval/experiments/2026-10-researched-cause-gate/run_trial.py --ref <commit-before-the-change>
```
