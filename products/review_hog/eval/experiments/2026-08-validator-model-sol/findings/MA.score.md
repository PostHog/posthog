## Sol @ xhigh validator, Sol reviewer @ xhigh (M1): 19 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 11   | 7        |
| dropped | 1    | 0        |

- kept-are-real (precision): 11/18 = 61%
- real-are-kept (recall): 11/12 = 92%
- not-real-dropped: 0/7 = 0%

- MA1 keep REAL sev=should_fix prio=must_fix Carve-out failures bypass approval retraction
- MA2 keep not sev=- prio=must_fix Child environment access reaches parent Stamphog settings
- MA3 keep REAL sev=consider prio=should_fix The trusted prompt always states that the PR is a draft
- MA4 keep not sev=- prio=should_fix Broker failures can lose the initial review
- MA5 drop REAL sev=should_fix prio=must_fix One opted-out reviewer blocks other opted-in reviewers
- MA6 keep REAL sev=must_fix prio=must_fix Caller-writable PR URLs can activate the trusted carve-out
- MA7 keep REAL sev=must_fix prio=must_fix Untrusted TaskRun output can authorize an unrelated PR
- MA8 keep REAL sev=must_fix prio=must_fix Initial review trusts a caller-controlled PR URL
- MA9 keep REAL sev=must_fix prio=must_fix Caller-writable task fields cannot prove PR provenance
- MA10 keep REAL sev=must_fix prio=must_fix Authenticate self-driving provenance before bypassing approv
- MA11 keep REAL sev=should_fix prio=must_fix The Stamphog gate ignores opted-in secondary reviewers
- MA12 keep not sev=- prio=must_fix Team filters run after candidate selection
- MA13 keep REAL sev=should_fix prio=must_fix Resolver failures can leave stale approvals active
- MA14 keep not sev=- prio=should_fix Broker failures permanently lose initial reviews
- MA15 keep not sev=- prio=should_fix Temporal outages can strand queued runs
- MA16 keep REAL sev=should_fix prio=must_fix Production self-driving tasks never reach the new dispatch
- MA17 keep not sev=- prio=should_fix Parent team IDs block child-environment re-reviews
- MA18 keep not sev=- prio=must_fix The queued task does not recheck the reviewer toggle
- MA19 keep REAL sev=should_fix prio=should_fix Failed and canceled task runs remain eligible for re-review
