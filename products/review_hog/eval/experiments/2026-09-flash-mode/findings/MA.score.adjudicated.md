# MA scorecard — luna-medium-1 (frozen PR 75215, clean room, inline skills)

|                                       | MA                                      |
| ------------------------------------- | --------------------------------------- |
| run                                   | luna-medium-1                           |
| wall-clock                            | 555s (9.2 min)                          |
| chunks / review units                 | 4 / 12                                  |
| raw → dedup → kept (validator)        | 14 → 11 → 9                             |
| findings judged (post-dedup)          | 11 (0 unscored)                         |
| real findings (reviewer side)         | 4/11 (36%)                              |
| real clusters found                   | 3 [2, 6, 39]                            |
| new real issues (not in registry)     | 0 []                                    |
| kept that were real (precision)       | 4/9 (44%)                               |
| real findings kept (recall)           | 4/4 (100%)                              |
| not-real findings dropped             | 2/7 (29%)                               |
| findings with NO verdict              | 0                                       |
| review + blind-spot cost              | $0.34 (93 calls, gpt-5.6-luna @ medium) |
| validation cost                       | $0.14 (56 calls, gpt-5.6-luna)          |
| cost per verdict                      | $0.013                                  |
| one-shots (selection + dedup, Sonnet) | $0.06                                   |
| TOTAL gateway cost                    | $0.54                                   |

## Per-finding

| id   | cluster | real | kept | severity (truth) | prio (validator→) | title                                                           |
| ---- | ------- | ---- | ---- | ---------------- | ----------------- | --------------------------------------------------------------- |
| MA1  | 6       | yes  | yes  | should_fix       | must_fix          | Enforce bot and draft invariants for self-driving reviews       |
| MA2  | 18      | no   | yes  | –                | should_fix        | Only report GitHub configurations as Stamphog-connected         |
| MA3  | 3       | no   | no   | –                | must_fix          | Validate the self-driving flag strictly                         |
| MA4  | 74      | no   | yes  | –                | should_fix        | suppress human ownership signals for self-driving PRs           |
| MA5  | 9       | no   | yes  | –                | should_fix        | Avoid queueing duplicate Stamphog jobs on every output save     |
| MA6  | 2       | yes  | yes  | should_fix       | must_fix          | Enforce provenance before stamping inbox reviews                |
| MA7  | 2       | yes  | yes  | should_fix       | must_fix          | must_fix: Revalidate the PR before granting the inbox carve-out |
| MA8  | 58      | no   | yes  | –                | should_fix        | Do not silently lose the initial Stamphog review                |
| MA9  | 39      | yes  | yes  | should_fix       | should_fix        | Apply team scoping before selecting the task run                |
| MA10 | –       | no   | no   | –                | should_fix        | Add an index for head-based review-run deduplication            |
| MA11 | 42      | no   | yes  | –                | must_fix          | must_fix: Serialize receiver deduplication per pull request     |
