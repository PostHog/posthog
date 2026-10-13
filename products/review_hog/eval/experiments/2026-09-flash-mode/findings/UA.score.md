# UA scorecard — luna-low-1 (frozen PR 75215, clean room, inline skills)

|                                       | UA                                   |
| ------------------------------------- | ------------------------------------ |
| run                                   | luna-low-1                           |
| wall-clock                            | 840s (14.0 min)                      |
| chunks / review units                 | 4 / 12                               |
| raw → dedup → kept (validator)        | 9 → 9 → 8                            |
| findings judged (post-dedup)          | 9 (0 unscored)                       |
| real findings (reviewer side)         | 2/9 (22%)                            |
| real clusters found                   | 2 [39, 58]                           |
| new real issues (not in registry)     | 0 []                                 |
| kept that were real (precision)       | 2/8 (25%)                            |
| real findings kept (recall)           | 2/2 (100%)                           |
| not-real findings dropped             | 1/7 (14%)                            |
| findings with NO verdict              | 0                                    |
| review + blind-spot cost              | $0.20 (60 calls, gpt-5.6-luna @ low) |
| validation cost                       | $0.06 (28 calls, gpt-5.6-luna)       |
| cost per verdict                      | $0.007                               |
| one-shots (selection + dedup, Sonnet) | $0.04                                |
| TOTAL gateway cost                    | $0.30                                |

## Per-finding

| id  | cluster | real | kept | severity (truth) | prio (validator→) | title                                                                     |
| --- | ------- | ---- | ---- | ---------------- | ----------------- | ------------------------------------------------------------------------- |
| UA1 | 6       | no   | no   | –                | must_fix          | Do not bypass the draft gate for non-bot authors                          |
| UA2 | 18      | no   | yes  | –                | should_fix        | Restrict the connection flag to GitHub repositories                       |
| UA3 | 39      | yes  | yes  | should_fix       | must_fix          | Scope the task lookup before selecting the newest run                     |
| UA4 | 4       | no   | yes  | –                | should_fix        | Skip author familiarity for self-driving reviews                          |
| UA5 | 9       | no   | yes  | –                | should_fix        | avoid queueing duplicate GitHub fetch jobs                                |
| UA6 | 58      | no   | yes  | –                | should_fix        | do not lose the initial review when the broker is unavailable             |
| UA7 | 2       | no   | yes  | –                | must_fix          | Validate the PR against the originating implementation run                |
| UA8 | –       | no   | yes  | –                | should_fix        | Add an index for head-based run deduplication                             |
| UA9 | 58      | yes  | yes  | should_fix       | must_fix          | Do not permanently lose the initial review after three transient failures |
