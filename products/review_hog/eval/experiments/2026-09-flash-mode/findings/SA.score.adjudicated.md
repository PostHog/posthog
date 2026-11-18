# SA scorecard — sol-low-1 (frozen PR 75215, clean room, inline skills)

|                                       | SA                                  |
| ------------------------------------- | ----------------------------------- |
| run                                   | sol-low-1                           |
| wall-clock                            | 1201s (20.0 min)                    |
| chunks / review units                 | 4 / 12                              |
| raw → dedup → kept (validator)        | 11 → 9 → 7                          |
| findings judged (post-dedup)          | 9 (0 unscored)                      |
| real findings (reviewer side)         | 5/9 (56%)                           |
| real clusters found                   | 5 [2, 39, 57, 58, 73]               |
| new real issues (not in registry)     | 0 []                                |
| kept that were real (precision)       | 5/7 (71%)                           |
| real findings kept (recall)           | 5/5 (100%)                          |
| not-real findings dropped             | 2/4 (50%)                           |
| findings with NO verdict              | 0                                   |
| review + blind-spot cost              | $4.78 (63 calls, gpt-5.6-sol @ low) |
| validation cost                       | $1.70 (31 calls, gpt-5.6-sol)       |
| cost per verdict                      | $0.188                              |
| one-shots (selection + dedup, Sonnet) | $0.11                               |
| TOTAL gateway cost                    | $6.58                               |

## Per-finding

| id  | cluster | real | kept | severity (truth) | prio (validator→) | title                                                               |
| --- | ------- | ---- | ---- | ---------------- | ----------------- | ------------------------------------------------------------------- |
| SA1 | 3       | no   | no   | –                | should_fix        | Validate the gate flag as an exact JSON boolean                     |
| SA2 | 58      | no   | yes  | –                | should_fix        | A broker outage can permanently lose the initial Stamphog review    |
| SA3 | 51      | no   | no   | –                | consider          | A Stamphog database outage can create a settings-endpoint log storm |
| SA4 | 58      | no   | yes  | –                | should_fix        | Broker failure can permanently drop the initial review              |
| SA5 | 58      | yes  | yes  | consider         | should_fix        | Exhausted Temporal retries leave review runs queued forever         |
| SA6 | 2       | yes  | yes  | should_fix       | must_fix          | Initial review trusts unverified inbox provenance                   |
| SA7 | 57      | yes  | yes  | should_fix       | must_fix          | Stamphog checks only one assigned reviewer                          |
| SA8 | 39      | yes  | yes  | should_fix       | should_fix        | Team scope is applied after an unscoped run selection               |
| SA9 | 73      | yes  | yes  | consider         | must_fix          | Branch fallback can bind a different pull request                   |
