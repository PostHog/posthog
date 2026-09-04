## Opus 5 @ xhigh, Sol reviewer @ xhigh (L1): 23 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 9    | 2        |
| dropped | 3    | 9        |

- kept-are-real (precision): 9/11 = 82%
- real-are-kept (recall): 9/12 = 75%
- not-real-dropped: 9/11 = 82%

- LA1 drop not sev=- prio=should_fix A broker failure permanently loses the initial review
- LA2 drop not sev=- prio=must_fix The PR URL parser accepts non-GitHub hosts
- LA3 keep REAL sev=consider prio=consider The trusted prompt always claims the PR is a draft
- LA4 keep REAL sev=should_fix prio=should_fix Dependency outages can leave stale approvals active
- LA5 drop not sev=- prio=should_fix Broker failures permanently lose initial review requests
- LA6 drop not sev=- prio=should_fix Worker loss or short outages can strand initial reviews
- LA7 keep REAL sev=consider prio=consider Expose Stamphog repository coverage in the switch
- LA8 drop REAL sev=consider prio=should_fix Do not order different heads by equal timestamps
- LA9 drop not sev=- prio=should_fix Self-driving mode does not suppress author familiarity
- LA10 drop not sev=- prio=must_fix Initial inbox path does not verify the claimed provenance
- LA11 keep REAL sev=must_fix prio=must_fix Verify trusted PR provenance before enabling approval bypass
- LA12 drop not sev=- prio=must_fix Revoke approval authority when the reviewer loses project ac
- LA13 keep REAL sev=must_fix prio=must_fix Validate the PR before granting self-driving privileges
- LA14 keep REAL sev=must_fix prio=must_fix Verify the PostHog Code bot identity
- LA15 keep REAL sev=must_fix prio=must_fix Do not use mutable task attribution as authorization
- LA16 keep not sev=- prio=must_fix Apply the team scope before selecting a run
- LA17 drop REAL sev=should_fix prio=must_fix Stamphog ignores opt-ins from secondary assigned reviewers
- LA18 keep REAL sev=should_fix prio=must_fix The lookup rejects production self-driving tasks
- LA19 keep REAL sev=must_fix prio=must_fix The carve-out is not bound to the expected PR shape
- LA20 drop not sev=- prio=should_fix Queued reviews do not recheck the opt-in
- LA21 drop REAL sev=consider prio=should_fix Branch fallback can scan the task-run table
- LA22 drop not sev=- prio=must_fix Pin approval gate reads to the writer
- LA23 keep not sev=- prio=should_fix Preserve the source environment during re-review lookup
