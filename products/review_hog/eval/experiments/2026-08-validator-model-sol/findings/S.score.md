## Opus 4.8 validator on S (July per-finding verdicts): 11 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 2    | 0        |
| dropped | 2    | 7        |

- kept-are-real (precision): 2/2 = 100%
- real-are-kept (recall): 2/4 = 50%
- not-real-dropped: 7/7 = 100%

- S1 drop not sev=not_an_issue prio=must_fix Security-sensitive flag accepts arbitrary truthy values
- S2 keep REAL sev=must_fix prio=must_fix Migration introduces a conflicting 0019 leaf
- S3 drop not sev=not_an_issue prio=should_fix Self-driving reviews can still include bot familiarity signa
- S4 drop not sev=not_an_issue prio=must_fix Initial inbox path can mark an unrelated PR as self-driving
- S5 drop not sev=consider prio=should_fix Team scoping is applied only after a cross-tenant TaskRun qu
- S6 drop not sev=not_an_issue prio=must_fix Only one assignee's opt-in is considered
- S7 drop REAL sev=consider prio=should_fix A ReviewHog callback failure can prevent the independent Sta
- S8 drop not sev=not_an_issue prio=must_fix Head-keyed deduplication does not serialize concurrent task
- S9 drop REAL sev=consider prio=should_fix Unmatched bot PRs can trigger an unindexed TaskRun branch sc
- S10 keep REAL sev=consider prio=consider Branch fallback can authorize a different PR
- S11 drop not sev=not_an_issue prio=should_fix Queued initial reviews ignore later opt-out
