## Sol @ max (K3): 7 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 3    | 3        |
| dropped | 0    | 1        |

- kept-are-real (precision): 3/6 = 50%
- real-are-kept (recall): 3/3 = 100%
- not-real-dropped: 1/4 = 25%

- KC1 drop not sev=- prio=must_fix Validate the gate flag as a JSON boolean
- KC2 keep not sev=- prio=must_fix Post-filtering an unscoped task-run lookup can hide the corr
- KC3 keep not sev=- prio=should_fix A broker failure permanently drops the initial review
- KC4 keep not sev=- prio=should_fix Broker failure can permanently lose the initial review
- KC5 keep REAL sev=consider prio=should_fix Do not claim that every self-driving PR is a draft
- KC6 keep REAL sev=must_fix prio=must_fix The initial review task trusts stale and unverified provenan
- KC7 keep REAL sev=should_fix prio=must_fix Stamphog ignores enabled settings from secondary reviewers
