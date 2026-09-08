## Opus 4.8 validator on W (July per-finding verdicts): 13 scored, 0 unscored

|         | real | not real |
| ------- | ---- | -------- |
| kept    | 4    | 0        |
| dropped | 0    | 9        |

- kept-are-real (precision): 4/4 = 100%
- real-are-kept (recall): 4/4 = 100%
- not-real-dropped: 9/9 = 100%

- W1 drop not sev=not_an_issue prio=should_fix Fire-and-forget facade performs a synchronous, failure-propa
- W2 drop not sev=not_an_issue prio=should_fix Self-driving reviews still perform expensive author-familiar
- W3 drop not sev=not_an_issue prio=should_fix Transient broker failures permanently drop the initial Stamp
- W4 keep REAL sev=must_fix prio=must_fix Migration creates a conflicting leaf in the review_hog graph
- W5 drop not sev=not_an_issue prio=should_fix Fail closed when parsing the privileged review flag
- W6 keep REAL sev=must_fix prio=must_fix Initial inbox review does not verify the PR belongs to the t
- W7 drop not sev=not_an_issue prio=must_fix Stamphog opt-in checks only one assignee instead of any assi
- W8 keep REAL sev=consider prio=consider Team scoping is applied after an unscoped, nondeterministic
- W9 drop not sev=not_an_issue prio=should_fix Self-driving reviews still include bot-author familiarity si
- W10 drop not sev=not_an_issue prio=should_fix Replica lag can permanently suppress inbox re-reviews
- W11 keep REAL sev=should_fix prio=must_fix Inbox implementation runs are rejected before either review
- W12 drop not sev=not_an_issue prio=must_fix Queued initial reviews ignore toggle changes before executio
- W13 drop not sev=not_an_issue prio=should_fix Self-driving prompt still includes human-author ownership si
