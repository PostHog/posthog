# VB scorecard — Sol (gpt-5.6-sol) reviewer @ xhigh, GLM 5.3 Flash validator @ max (frozen PR 75215)

Usage source: `runs/V2-glm-validator.ai_usage.json`.
Truth: registry clusters + reused prior verdicts (sol-experiment KA/KB, validator-model-sol LA/LB) + fresh verification (`findings/verify/`).

## Metrics

|                                   | VB (Sol xhigh reviewer, GLM 5.3 Flash max validator) |
| --------------------------------- | ---------------------------------------------------- |
| findings judged                   | 22                                                   |
| real findings (reviewer side)     | 14/22 (64%)                                          |
| new real issues                   | 5 (VB7, VB18, VB19, VB21, VB22)                      |
| real clusters found               | 9                                                    |
| kept                              | 7                                                    |
| kept that were real               | 6/7 (86%)                                            |
| real findings kept (recall)       | 6/14 (43%)                                           |
| not-real findings dropped         | 7/8 (88%)                                            |
| validation LLM calls              | 159                                                  |
| validation cost (gateway)         | $0.42                                                |
| cost per verdict                  | $0.02                                                |
| review + blind-spot cost          | $27.29 (356 calls)                                   |
| effort seen (review / validation) | xhigh / max                                          |

## Per-finding

| id   | cluster | real | kept | note                                                                                                            |
| ---- | ------- | ---- | ---- | --------------------------------------------------------------------------------------------------------------- |
| VB1  | 58      | no   | no   | Broker fire-and-forget refuted (KA13: publish retries + receiver refire); dropped with no recorded verdict.     |
| VB2  | 57      | no   | no   | The claimed any-assignee rule does not exist; single acting reviewer is documented design. No verdict recorded. |
| VB3  | 58      | no   | yes  | Same refuted broker claim (KA13); validator kept it at consider despite refire + publish-retry recovery.        |
| VB4  | 29      | yes  | no   | Real (LA4): carve-out retry path runs before stale-approval retraction; no verdict recorded, real lost.         |
| VB5  | -       | no   | no   | Early-ack crash loss refuted (LA6: refire + QUEUED dedupe recover). Dropped with no recorded verdict.           |
| VB6  | 47      | no   | no   | Telemetry-completeness wish, not a reachable defect (LB1 refutation). Dropped with no recorded verdict.         |
| VB7  | -       | yes  | no   | New real (fresh): parent-vs-child team-ID mismatch silently kills the carve-out; no verdict recorded, lost.     |
| VB8  | 2       | no   | no   | Provenance claim refuted fresh (identity relation, HMAC webhook, team recheck). Correct reasoned dismissal.     |
| VB9  | 57      | no   | no   | Single-acting-reviewer gate is documented maintainer design. Correct reasoned dismissal.                        |
| VB10 | 2       | yes  | no   | Real must_fix (KA10: caller-writable output.pr_url reaches a real approval); no verdict recorded, lost.         |
| VB11 | 73      | yes  | no   | Real (cluster 73: writable pr_url/branch authorize self-driving binding); no verdict recorded, lost.            |
| VB12 | 57      | yes  | yes  | Confirmed single-reviewer-toggle defect (KA4). Correct keep, downgraded to should_fix.                          |
| VB13 | 39      | no   | no   | Cross-team shadow refuted fresh (fail-closed by construction, matches KA5). Correct reasoned dismissal.         |
| VB14 | 70      | yes  | no   | Real per cluster 70 (bot-author showstopper never carved out); validator's TRUSTED-region rebuttal wrongly won. |
| VB15 | 35      | yes  | yes  | Unconditional "draft on purpose" sentence is false on post-ready re-reviews. Correct keep.                      |
| VB16 | 27      | yes  | yes  | Fresh-verified: fail-soft false-in-200 disables the switch with no retry trigger. Kept, downgraded to consider. |
| VB17 | 41      | yes  | no   | Real (cluster 41: FAILED-run dedupe exclusion allows unbounded retries); no verdict recorded, lost.             |
| VB18 | -       | yes  | yes  | New real (fresh): toggle-gated fallback skips stale-approval dismissal after a lost webhook. Kept, downgraded.  |
| VB19 | -       | yes  | yes  | New real (fresh): connected flag survives user deactivation while token minting always fails. Correct keep.     |
| VB20 | 1       | yes  | no   | Real must_fix (KA9: internal=True rejects every production self-driving task); no verdict recorded, lost.       |
| VB21 | -       | yes  | no   | New real (LB2): older completed run masks a newer failed re-review, blocking retry; no verdict recorded, lost.  |
| VB22 | -       | yes  | yes  | New real (fresh): transient WAIT/ERROR outcomes persist as terminal, stranding the head. Correct keep.          |

## Notes

- Validator effort ran at `max` (GLM 5.3 Flash), reviewer at `xhigh`; perspective_selection + dedup (claude-sonnet-5, $0.27, 2 calls) counted in neither bucket, matching the xhigh_summary convention.
- Validation calls include 2 zero-token `claude-opus-4-8` rows with null cost in validation-c2 (155 GLM calls carried all the spend); GLM validation cost stayed near-free at $0.42.
- The dominant failure mode is silent: 12 of 22 findings never received a verdict at all, and 7 of the 8 lost reals (VB4, VB7, VB10, VB11, VB17, VB20, VB21) fell into that hole — including three must_fix truths. Kept-precision looks strong (86%) only because the validator kept so little; 43% recall is the worst of any validator arm so far.
