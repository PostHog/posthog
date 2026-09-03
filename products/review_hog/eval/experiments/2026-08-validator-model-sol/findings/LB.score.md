## Opus 5 @ xhigh, Sol reviewer @ xhigh (L2): 22 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 8    | 4        |
| dropped | 3    | 7        |

- kept-are-real (precision): 8/12 = 67%
- real-are-kept (recall): 8/11 = 73%
- not-real-dropped: 7/11 = 64%

- LB1 keep not sev=- prio=consider Self-driving attribution excludes failed reviews
- LB2 keep REAL sev=consider prio=consider An older completed run can hide the latest failed re-review
- LB3 keep REAL sev=consider prio=consider Trusted prompt always claims the PR is a draft
- LB4 drop not sev=- prio=should_fix The fail-soft check can delay requests and flood error logs
- LB5 keep not sev=- prio=should_fix Worker loss can permanently drop the initial review
- LB6 drop not sev=- prio=should_fix Broker failures lose the review request
- LB7 keep not sev=- prio=should_fix Child access can enable a parent project's approval toggle
- LB8 keep REAL sev=must_fix prio=must_fix Caller-writable PR URL can bypass Stamphog approval gates
- LB9 drop not sev=- prio=should_fix The PR URL parser accepts embedded GitHub URLs
- LB10 drop REAL sev=must_fix prio=must_fix Do not trust an unbound context flag to bypass approval gate
- LB11 keep REAL sev=should_fix prio=must_fix Stamphog ignores opted-in secondary reviewers
- LB12 keep REAL sev=must_fix prio=must_fix Self-driving provenance is granted before the PR is verified
- LB13 drop REAL sev=should_fix prio=should_fix Canceled implementation runs still qualify for the carve-out
- LB14 drop not sev=- prio=must_fix Report-linked discussion tasks are classified as implementat
- LB15 drop not sev=- prio=should_fix A broker failure permanently drops the initial review
- LB16 drop not sev=- prio=should_fix Eligibility filters run after selecting one task run
- LB17 drop REAL sev=should_fix prio=should_fix Record hosted WAIT outcomes for self-driving reviews
- LB18 keep not sev=- prio=should_fix Child-environment PRs never receive Stamphog re-reviews
- LB19 drop not sev=- prio=must_fix Former project members can remain approval reviewers
- LB20 keep REAL sev=consider prio=must_fix The opt-out path leaves the old review workflow active
- LB21 keep REAL sev=consider prio=must_fix The opt-out dismissal misses GitHub-only approvals
- LB22 keep REAL sev=should_fix prio=consider Hosted bot predicate omits posthog-bot
