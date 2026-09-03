## Opus 5 @ xhigh, Sol reviewer @ medium (P2): 15 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 7    | 0        |
| dropped | 0    | 8        |

- kept-are-real (precision): 7/7 = 100%
- real-are-kept (recall): 7/7 = 100%
- not-real-dropped: 8/8 = 100%

- PB1 drop not sev=- prio=should_fix PR URL parser accepts non-GitHub and ambiguous URLs
- PB2 keep REAL sev=consider prio=consider The trusted prompt can report the wrong draft state
- PB3 drop not sev=- prio=should_fix Broker failures permanently lose the initial review
- PB4 drop not sev=- prio=should_fix Exhausted workflow-start retries leave runs queued forever
- PB5 keep REAL sev=consider prio=should_fix Opt-out path can leave a late approval active
- PB6 keep REAL sev=must_fix prio=must_fix The documented positive-linkage invariant is not enforced
- PB7 keep REAL sev=must_fix prio=must_fix Validate PR provenance before granting the inbox review carv
- PB8 keep REAL sev=must_fix prio=must_fix Untrusted task output enables the privileged review path
- PB9 keep REAL sev=must_fix prio=must_fix The carve-out trusts an unverified context value
- PB10 keep REAL sev=should_fix prio=must_fix The Stamphog gate ignores opted-in secondary reviewers
- PB11 drop not sev=- prio=should_fix Run eligibility is checked after selecting one candidate
- PB12 drop not sev=- prio=should_fix The side-effect gate can read a stale TaskRun
- PB13 drop not sev=- prio=should_fix Broker failures permanently drop the initial review
- PB14 drop not sev=- prio=should_fix Deferred import can escape the save path
- PB15 drop not sev=- prio=must_fix A queued review ignores a later opt-out
