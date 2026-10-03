# RA scorecard — GLM 5.3 Flash reviewer @ max, Opus 5 validator @ xhigh (R1, frozen PR 75215)

|                                   | RA (R1-glm-reviewer) |
| --------------------------------- | -------------------- |
| findings judged                   | 14                   |
| real findings (reviewer side)     | 1/14 (7%)            |
| new real issues                   | 1 (RA5)              |
| real clusters found               | 0                    |
| kept                              | 0                    |
| kept that were real               | 0/0 (–)              |
| real findings kept (recall)       | 0/1 (0%)             |
| not-real findings dropped         | 13/13 (100%)         |
| validation LLM calls              | 75                   |
| validation cost (gateway)         | $7.09                |
| cost per verdict                  | $0.51                |
| review + blind-spot cost          | $1.82 (537 calls)    |
| effort seen (review / validation) | max / xhigh          |

Costs exclude the Sonnet selection and dedup one-shots (≤ $0.07), same convention as the sol-experiment summary.
One blind-spots-c2 call reported `high` effort; every other review-side call reported `max`.
RA8, RA11, and RA12 land in known clusters (7, 24, 5), but all three clusters are registry not-real, so real clusters found = 0.

## Per-finding

| id   | cluster | real | kept | note                                                                                                                      |
| ---- | ------- | ---- | ---- | ------------------------------------------------------------------------------------------------------------------------- |
| RA1  | –       | no   | no   | Praise of the keyword-only kwarg plus a speculative enum suggestion; names no defect.                                     |
| RA2  | –       | no   | no   | Requested anti-injection sentence already exists twice (ANTI_INJECTION_NOTICE + block's own close).                       |
| RA3  | –       | no   | no   | Confirms the version bump follows the documented rule; no defect.                                                         |
| RA4  | –       | no   | no   | Premise wrong: the on_commit lambda at tasks.py:1214 captures existing_run_id — the variable is live.                     |
| RA5  | –       | REAL | no   | Genuine gap: `cast(Any, task).retry` idiom is unexplained (19 uses); validator over-dropped it as a repo convention.      |
| RA6  | –       | no   | no   | tasks.py:201 guards `resolver is None`; Django's app lifecycle enforces registration order.                               |
| RA7  | –       | no   | no   | No late-binding bug: one receiver invocation per save, closure cells never rebound.                                       |
| RA8  | 7       | no   | no   | Matches known cluster 7, itself registry not-real; index-backed probe, self-negating suggestion.                          |
| RA9  | 51      | no   | no   | Matches known cluster 51, not-real; logger.exception keeps class/traceback, fail-soft is deliberate.                      |
| RA10 | –       | no   | no   | default/db_default pairing is the mandated house convention, not redundancy.                                              |
| RA11 | 24      | no   | no   | Matches known cluster 24, not-real; classification.self_driving is serialized on every run.                               |
| RA12 | 5       | no   | no   | Matches known cluster 5, not-real; the flag shares the whole context file's trust boundary, linkage verified server-side. |
| RA13 | –       | no   | no   | Claimed inline copy does not exist; the inbox path calls the same \_upsert_pull_request helper.                           |
| RA14 | –       | no   | no   | Every anchor wrong; the local comment already names the reader-lag invariant.                                             |
