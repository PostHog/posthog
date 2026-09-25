# SB scorecard — sol-low-2 (frozen PR 75215, clean room, inline skills)

|                                       | SB                                  |
| ------------------------------------- | ----------------------------------- |
| run                                   | sol-low-2                           |
| wall-clock                            | 1291s (21.5 min)                    |
| chunks / review units                 | 4 / 13                              |
| raw → dedup → kept (validator)        | 14 → 10 → 7                         |
| findings judged (post-dedup)          | 10 (0 unscored)                     |
| real findings (reviewer side)         | 5/10 (50%)                          |
| real clusters found                   | 5 [2, 6, 39, 57, 73]                |
| new real issues (not in registry)     | 0 []                                |
| kept that were real (precision)       | 4/7 (57%)                           |
| real findings kept (recall)           | 4/5 (80%)                           |
| not-real findings dropped             | 2/5 (40%)                           |
| findings with NO verdict              | 0                                   |
| review + blind-spot cost              | $5.67 (82 calls, gpt-5.6-sol @ low) |
| validation cost                       | $1.68 (33 calls, gpt-5.6-sol)       |
| cost per verdict                      | $0.168                              |
| one-shots (selection + dedup, Sonnet) | $0.09                               |
| TOTAL gateway cost                    | $7.43                               |

## Per-finding

| id   | cluster | real | kept | severity (truth) | prio (validator→) | title                                                        |
| ---- | ------- | ---- | ---- | ---------------- | ----------------- | ------------------------------------------------------------ |
| SB1  | 3       | no   | no   | –                | must_fix          | Reject non-boolean self-driving flags                        |
| SB2  | 16      | no   | no   | –                | should_fix        | The deferred import can still fail the save request          |
| SB3  | 58      | no   | yes  | –                | should_fix        | Broker failures can permanently lose the initial review      |
| SB4  | 6       | yes  | yes  | should_fix       | must_fix          | Limit the draft bypass to bot-authored PRs                   |
| SB5  | 39      | yes  | yes  | should_fix       | must_fix          | Team filtering happens after a global task-run lookup        |
| SB6  | 57      | yes  | no   | should_fix       | must_fix          | Only one assigned reviewer can enable Stamphog               |
| SB7  | 2       | yes  | yes  | should_fix       | must_fix          | Initial review does not verify self-driving provenance       |
| SB8  | 58      | no   | yes  | –                | should_fix        | Queue failures permanently lose the initial review           |
| SB9  | 31      | no   | yes  | –                | must_fix          | Recheck the opt-in before the queued review runs             |
| SB10 | 73      | yes  | yes  | should_fix       | must_fix          | Branch fallback can identify an unrelated PR as self-driving |
