# VA scorecard — Sol (gpt-5.6-sol) reviewer @ xhigh, GLM 5.3 Flash validator @ max (frozen PR 75215)

Usage source: `runs/V1-glm-validator.ai_usage.json`.
Truth: registry clusters + reused prior verdicts (sol-experiment KA/KB, validator-model-sol LA/LB) + fresh verification (`findings/verify/`).

## Metrics

|                                   | VA (Sol xhigh reviewer, GLM 5.3 Flash max validator) |
| --------------------------------- | ---------------------------------------------------- |
| findings judged                   | 21                                                   |
| real findings (reviewer side)     | 13/21 (62%)                                          |
| new real issues                   | 2 (VA3, VA21)                                        |
| real clusters found               | 9                                                    |
| kept                              | 15                                                   |
| kept that were real               | 9/15 (60%)                                           |
| real findings kept (recall)       | 9/13 (69%)                                           |
| not-real findings dropped         | 2/8 (25%)                                            |
| validation LLM calls              | 328                                                  |
| validation cost (gateway)         | $1.05                                                |
| cost per verdict                  | $0.05                                                |
| review + blind-spot cost          | $26.80 (349 calls)                                   |
| effort seen (review / validation) | xhigh / max                                          |

## Per-finding

| id   | cluster | real | kept | note                                                                                                            |
| ---- | ------- | ---- | ---- | --------------------------------------------------------------------------------------------------------------- |
| VA1  | 7       | no   | yes  | Settings serializer cross-DB read; registry cluster 7 rates it not real, validator upheld it as should_fix.     |
| VA2  | 58      | yes  | yes  | Fresh-verified: inbox dispatch has no durable intent, broker outage silently drops the review. Correct keep.    |
| VA3  | -       | yes  | yes  | New real (LB20 match): opt-out path never supersedes live runs, stale approval can land. Kept, downgraded.      |
| VA4  | 2       | no   | no   | Provenance-contract claim refuted (KB5): caller invariants hold by construction. Correct dismissal.             |
| VA5  | 18      | no   | yes  | Missing provider=github filter; registry cluster 18 rates it not real, validator kept it.                       |
| VA6  | 2       | yes  | yes  | Fresh-verified: attacker-writable output.pr_url reaches the queue unattested. Kept, downgraded to should_fix.   |
| VA7  | 2       | yes  | yes  | Same cluster-2 missing-linkage kernel (KA10 real); kept but adjusted down to consider.                          |
| VA8  | 31      | no   | yes  | Enqueue-time-only toggle check; registry cluster 31 rates it not real, validator kept it as must_fix.           |
| VA9  | 73      | yes  | yes  | Agent-mutable fields drive the approval authorization (cluster 73). Correct must_fix keep.                      |
| VA10 | 39      | no   | yes  | Cross-team shadow fails closed (KA5 refutation); validator kept it anyway.                                      |
| VA11 | 57      | yes  | no   | Real per KA4 (secondary opted-in reviewer ignored); validator dismissed it as speculative preference.           |
| VA12 | 1       | yes  | no   | Real must_fix (internal=True kills the carve-out, fresh-verified); no validator verdict recorded, so dropped.   |
| VA13 | 2       | yes  | no   | Real per LA19 (flag relaxes both hard gates with no bot/fork check); validator's rebuttal cites absent checks.  |
| VA14 | 70      | yes  | yes  | System-prompt bot-author showstopper defeats the user-prompt flag. Correct must_fix keep.                       |
| VA15 | 35      | yes  | yes  | Static "draft on purpose" text is false on post-ready re-reviews. Correct keep.                                 |
| VA16 | 58      | no   | no   | Broker-loss variant refuted (KA13: publish retries + deliberate receiver refire). Correct dismissal.            |
| VA17 | -       | no   | yes  | Early-ack loss is recovered by refire and dedupe (LA6); validator kept it anyway.                               |
| VA18 | 58      | no   | yes  | Short-retry-window claim refuted (LA6/KB4: refire + head-keyed dedupe recover); validator kept it.              |
| VA19 | 23      | yes  | yes  | Unindexed TaskRun.branch fallback scans on bot-PR webhook misses (cluster 23). Correct keep.                    |
| VA20 | 29      | yes  | yes  | Fresh-verified: resolver failure past 202-ack blocks retraction with no redelivery. Kept, downgraded.           |
| VA21 | -       | yes  | no   | New real (fresh-verified): stamphog-label readiness claim is false for label-less self-driving runs; dismissed. |

## Notes

- Validator effort ran at `max` (GLM 5.3 Flash), reviewer at `xhigh`; perspective_selection + dedup (claude-sonnet-5, $0.22, 2 calls) counted in neither bucket, matching the xhigh_summary convention.
- Validation was near-free ($1.05 vs $10.53-$24.35 for prior validators) but filtered poorly in both directions: it dropped 4 of 13 real findings (VA11, VA12, VA13, VA21 — including one with no recorded verdict at all) while passing 6 of 8 not-real ones.
