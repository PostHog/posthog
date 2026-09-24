# MB scorecard — luna-medium-2 (frozen PR 75215, clean room, inline skills)

|                                       | MB                                       |
| ------------------------------------- | ---------------------------------------- |
| run                                   | luna-medium-2                            |
| wall-clock                            | 710s (11.8 min)                          |
| chunks / review units                 | 4 / 13                                   |
| raw → dedup → kept (validator)        | 15 → 11 → 10                             |
| findings judged (post-dedup)          | 11 (0 unscored)                          |
| real findings (reviewer side)         | 6/11 (55%)                               |
| real clusters found                   | 3 [2, 6, 58]                             |
| new real issues (not in registry)     | 0 []                                     |
| kept that were real (precision)       | 6/10 (60%)                               |
| real findings kept (recall)           | 6/6 (100%)                               |
| not-real findings dropped             | 1/5 (20%)                                |
| findings with NO verdict              | 0                                        |
| review + blind-spot cost              | $0.40 (112 calls, gpt-5.6-luna @ medium) |
| validation cost                       | $0.11 (41 calls, gpt-5.6-luna)           |
| cost per verdict                      | $0.010                                   |
| one-shots (selection + dedup, Sonnet) | $0.12                                    |
| TOTAL gateway cost                    | $0.64                                    |

## Per-finding

| id   | cluster | real | kept | severity (truth) | prio (validator→) | title                                                          |
| ---- | ------- | ---- | ---- | ---------------- | ----------------- | -------------------------------------------------------------- |
| MB1  | 6       | yes  | yes  | must_fix         | must_fix          | Bind the carve-out to bot authors                              |
| MB2  | 57      | no   | yes  | –                | should_fix        | Honor the toggle of any assigned reviewer                      |
| MB3  | 4       | no   | yes  | –                | should_fix        | Do not include author familiarity for self-driving reviews     |
| MB4  | 58      | yes  | yes  | should_fix       | must_fix          | Prevent broker failures from losing the initial review         |
| MB5  | 18      | no   | yes  | –                | should_fix        | Match the connection check to supported GitHub repositories    |
| MB6  | –       | no   | no   | –                | must_fix          | Do not re-review bot PRs after they leave draft state          |
| MB7  | 2       | yes  | yes  | must_fix         | must_fix          | must verify inbox provenance before enabling the carve-out     |
| MB8  | 2       | yes  | yes  | must_fix         | must_fix          | Revalidate the PR before enabling the self-driving bypass      |
| MB9  | 58      | yes  | yes  | should_fix       | should_fix        | Retry failed Stamphog task submission                          |
| MB10 | 58      | yes  | yes  | should_fix       | must_fix          | Do not permanently drop reviews after three transient failures |
| MB11 | 9       | no   | yes  | –                | should_fix        | Coalesce repeated receiver jobs before fetching GitHub         |
