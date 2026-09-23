## Opus 5 @ xhigh, Sol reviewer @ medium (P1): 14 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 6    | 0        |
| dropped | 1    | 7        |

- kept-are-real (precision): 6/6 = 100%
- real-are-kept (recall): 6/7 = 86%
- not-real-dropped: 7/7 = 100%

- PA1 keep REAL sev=must_fix prio=should_fix Any bot can qualify through the branch fallback
- PA2 keep REAL sev=consider prio=should_fix The trusted prompt reports ready pull requests as drafts
- PA3 drop not sev=- prio=should_fix Fail-soft database check can flood error logs
- PA4 drop not sev=- prio=should_fix The initial review handoff can be lost when the broker is un
- PA5 drop not sev=- prio=should_fix A worker crash can discard the initial review task
- PA6 keep REAL sev=should_fix prio=should_fix A resolver failure can leave a stale approval active
- PA7 drop not sev=- prio=should_fix The toggle gate does not match the promised assignee behavio
- PA8 keep REAL sev=must_fix prio=must_fix The initial task trusts caller-supplied PR provenance
- PA9 drop not sev=- prio=should_fix The worker does not recheck the review opt-in
- PA10 keep REAL sev=must_fix prio=must_fix The carve-out trusts an unvalidated boolean
- PA11 keep REAL sev=must_fix prio=must_fix Inbox provenance is granted without verifying the pull reque
- PA12 drop REAL sev=should_fix prio=must_fix The Stamphog gate ignores later opted-in assignees
- PA13 drop not sev=- prio=should_fix Post-filtering an unscoped run can hide a valid match
- PA14 drop not sev=- prio=should_fix Initial Stamphog dispatch can be lost permanently
