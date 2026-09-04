## Sonnet 5 @ xhigh validator, Sol reviewer @ xhigh (N1): 22 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 8    | 8        |
| dropped | 3    | 3        |

- kept-are-real (precision): 8/16 = 50%
- real-are-kept (recall): 8/11 = 73%
- not-real-dropped: 3/11 = 27%

- NA1 keep REAL sev=should_fix prio=must_fix The toggle ignores opted-in secondary assignees
- NA2 keep REAL sev=consider prio=should_fix Trusted prompt reports a ready PR as draft
- NA3 drop not sev=- prio=should_fix A Stamphog outage can delay every settings response
- NA4 keep not sev=- prio=should_fix Persist the review handoff before publishing
- NA5 drop REAL sev=must_fix prio=consider The carve-out accepts any bot identity
- NA6 keep not sev=- prio=should_fix Use late acknowledgement for the idempotent task
- NA7 keep REAL sev=must_fix prio=must_fix The initial path does not verify that the task produced the
- NA8 drop not sev=- prio=consider The documented toggle gate conflicts with the feature contra
- NA9 keep not sev=- prio=should_fix A queued initial review can run after opt-out
- NA10 keep REAL sev=must_fix prio=must_fix Initial inbox reviews trust a caller-controlled PR URL
- NA11 keep REAL sev=must_fix prio=must_fix Webhook linkage trusts a user-writable PR URL
- NA12 drop not sev=- prio=must_fix Truthy JSON can enable the approval carve-out
- NA13 drop REAL sev=should_fix prio=must_fix Stamphog ignores opted-in secondary reviewers
- NA14 keep REAL sev=should_fix prio=must_fix Internal implementation runs never qualify
- NA15 keep not sev=- prio=should_fix The queue callback imports the full Stamphog worker stack
- NA16 keep not sev=- prio=should_fix A broker failure permanently drops the initial review
- NA17 keep not sev=- prio=consider Repeated output saves create duplicate GitHub fetches
- NA18 keep not sev=- prio=should_fix Apply TaskRun scope before selecting a row
- NA19 keep REAL sev=consider prio=should_fix Resolve equal GitHub timestamps before superseding
- NA20 keep REAL sev=consider prio=should_fix ReviewHog startup runs before the Stamphog-first dispatch
- NA21 keep not sev=- prio=should_fix Re-check the opt-in inside the delayed task
- NA22 drop REAL sev=must_fix prio=must_fix Bind the carve-out to the fetched PR
