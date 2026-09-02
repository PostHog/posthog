## Sol @ xhigh validator, Sol reviewer @ xhigh (M2): 20 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 12   | 6        |
| dropped | 1    | 1        |

- kept-are-real (precision): 12/18 = 67%
- real-are-kept (recall): 12/13 = 92%
- not-real-dropped: 1/7 = 14%

- MB1 keep not sev=- prio=must_fix Recheck the toggle when the queued task runs
- MB2 keep REAL sev=consider prio=should_fix Trusted prompt claims ready PRs are drafts
- MB3 keep not sev=- prio=should_fix A broker outage permanently drops the initial review
- MB4 drop not sev=- prio=should_fix Concurrent output saves can start duplicate reviews
- MB5 keep REAL sev=consider prio=must_fix Head-only dedupe accepts a changed base diff
- MB6 keep REAL sev=should_fix prio=should_fix Failed reviews can restart without a limit
- MB7 keep REAL sev=should_fix prio=must_fix Add the bot exception to the system prompt
- MB8 keep REAL sev=must_fix prio=must_fix Bind the gate bypass to verified PR provenance
- MB9 keep not sev=- prio=should_fix Initial review dispatch is not durable
- MB10 keep not sev=- prio=should_fix Worker loss can drop the review task
- MB11 drop REAL sev=should_fix prio=should_fix Check every assigned reviewer's opt-in
- MB12 keep REAL sev=consider prio=must_fix Opt-out dismissal misses approvals that exist only on GitHub
- MB13 keep REAL sev=consider prio=should_fix Equal GitHub timestamps can supersede the current run
- MB14 keep REAL sev=must_fix prio=must_fix Receiver path does not prove that the task created the PR
- MB15 keep REAL sev=must_fix prio=must_fix Do not trust caller-writable TaskRun output as approval prov
- MB16 keep REAL sev=must_fix prio=must_fix Initial inbox reviews trust a caller-controlled PR URL
- MB17 keep REAL sev=must_fix prio=must_fix The re-review gate treats writable task fields as proof
- MB18 keep not sev=- prio=must_fix Team scoping occurs after selecting a cross-tenant run
- MB19 keep REAL sev=should_fix prio=should_fix The Stamphog toggle ignores opted-in secondary reviewers
- MB20 keep not sev=- prio=must_fix Verify the task is an implementation task
