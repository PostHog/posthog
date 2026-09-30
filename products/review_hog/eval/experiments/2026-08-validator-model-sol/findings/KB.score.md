## Sol validator, run 2 (PR tree), final: 10 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 4    | 4        |
| dropped | 0    | 2        |

- kept-are-real (precision): 4/8 = 50%
- real-are-kept (recall): 4/4 = 100%
- not-real-dropped: 2/6 = 33%

- KB1 keep not sev=- prio=must_fix Post-query team filtering can hide the correct task run
- KB2 keep REAL sev=consider prio=should_fix Trusted prompt can report the wrong draft state
- KB3 keep not sev=- prio=should_fix Broker failures permanently lose the initial review
- KB4 keep not sev=- prio=should_fix Exhausted retries can leave a review run queued forever
- KB5 drop not sev=- prio=should_fix Documented linkage check does not exist on the initial revie
- KB6 keep REAL sev=must_fix prio=must_fix Revalidate inbox provenance before granting the review carve
- KB7 keep REAL sev=should_fix prio=must_fix The receiver skips real self-driving implementation tasks
- KB8 keep REAL sev=should_fix prio=must_fix The toggle check ignores other assigned reviewers
- KB9 drop not sev=- prio=should_fix Repeated saves cause a GitHub request before deduplication
- KB10 keep not sev=- prio=must_fix The queued review ignores a later opt-out
