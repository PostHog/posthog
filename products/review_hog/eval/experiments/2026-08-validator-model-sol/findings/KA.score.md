## Sol validator, run 1 (master tree), final: 14 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 5    | 0        |
| dropped | 4    | 5        |

- kept-are-real (precision): 5/5 = 100%
- real-are-kept (recall): 5/9 = 56%
- not-real-dropped: 5/5 = 100%

- KA1 drop not sev=- prio=must_fix The queued review does not recheck the reviewer toggle
- KA2 drop REAL sev=must_fix prio=must_fix Webhook carve-out can bind writable run fields to any bot PR
- KA3 drop not sev=- prio=must_fix Truthy non-boolean values bypass security gates
- KA4 keep REAL sev=should_fix prio=must_fix Stamphog ignores opt-ins from non-acting reviewers
- KA5 drop not sev=- prio=should_fix An unscoped lookup can hide the matching team run
- KA6 keep REAL sev=consider prio=must_fix Self-driving flag can approve a human-authored draft
- KA7 keep REAL sev=consider prio=should_fix Do not treat every self-driving review as a draft
- KA8 drop not sev=- prio=must_fix Self-driving reviews still receive bot familiarity signals
- KA9 keep REAL sev=should_fix prio=should_fix The documented task type contradicts the implementation
- KA10 drop REAL sev=must_fix prio=must_fix Initial review trusts a caller-writable PR URL
- KA11 drop REAL sev=should_fix prio=must_fix Run lookup does not enforce the self-driving implementation
- KA12 keep REAL sev=consider prio=should_fix Commit-hook failure can skip an independent review
- KA13 drop not sev=- prio=should_fix A broker outage permanently loses the initial Stamphog revie
- KA14 drop REAL sev=consider prio=should_fix Scope the task-run lookup before querying
