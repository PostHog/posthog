## Sonnet 5 @ xhigh validator, Sol reviewer @ xhigh (N2): 22 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 11   | 11       |
| dropped | 0    | 0        |

- kept-are-real (precision): 11/22 = 50%
- real-are-kept (recall): 11/11 = 100%
- not-real-dropped: 0/11 = 0%

- NB1 keep not sev=- prio=must_fix Authorize settings against the canonical team
- NB2 keep REAL sev=must_fix prio=must_fix The webhook carve-out accepts any bot author
- NB3 keep REAL sev=consider prio=should_fix Ready re-reviews get false trusted draft context
- NB4 keep not sev=- prio=should_fix Broker failures permanently drop initial Stamphog reviews
- NB5 keep not sev=- prio=should_fix Initial review dispatch has no durable record
- NB6 keep not sev=- prio=should_fix The hosted bypass list omits the author-association gate
- NB7 keep not sev=- prio=must_fix Require a recorded implementation relationship
- NB8 keep REAL sev=must_fix prio=must_fix Initial inbox reviews trust client-writable provenance
- NB9 keep REAL sev=must_fix prio=must_fix Webhook carve-out uses writable output as provenance
- NB10 keep REAL sev=must_fix prio=must_fix Do not authorize the carve-out with an unchecked truthy flag
- NB11 keep REAL sev=should_fix prio=must_fix Stamphog ignores opted-in secondary reviewers
- NB12 keep not sev=- prio=should_fix Post-selection filters can hide the qualifying signal run
- NB13 keep not sev=- prio=must_fix A disable race can create a review after repository opt-out
- NB14 keep REAL sev=consider prio=consider Base-retarget dismissal promises a review after opt-out
- NB15 keep not sev=- prio=should_fix Use late acknowledgements for the initial review task
- NB16 keep not sev=- prio=should_fix Exhausted retries can strand queued reviews
- NB17 keep REAL sev=consider prio=consider Index the TaskRun branch fallback
- NB18 keep REAL sev=should_fix prio=must_fix Fail closed when the webhook resolver cannot read settings
- NB19 keep not sev=- prio=must_fix Non-implementation signal tasks receive the carve-out
- NB20 keep REAL sev=should_fix prio=must_fix Failed and canceled runs still qualify for re-review
- NB21 keep REAL sev=consider prio=must_fix Opt-out can leave an untracked approval active
- NB22 keep not sev=- prio=must_fix Delayed initial tasks ignore a later toggle opt-out
