# XB scorecard — luna-xhigh-2 (frozen PR 75215, clean room, inline skills)

|                                       | XB                                      |
| ------------------------------------- | --------------------------------------- |
| run                                   | luna-xhigh-2                            |
| wall-clock                            | 2185s (36.4 min)                        |
| chunks / review units                 | 4 / 13                                  |
| raw → dedup → kept (validator)        | 27 → 22 → 19                            |
| findings judged (post-dedup)          | 22 (0 unscored)                         |
| real findings (reviewer side)         | 14/22 (64%)                             |
| real clusters found                   | 6 [1, 2, 6, 39, 57, 58]                 |
| new real issues (not in registry)     | 4 ['XB1', 'XB6', 'XB9', 'XB18']         |
| kept that were real (precision)       | 13/19 (68%)                             |
| real findings kept (recall)           | 13/14 (93%)                             |
| not-real findings dropped             | 2/8 (25%)                               |
| findings with NO verdict              | 0                                       |
| review + blind-spot cost              | $1.87 (388 calls, gpt-5.6-luna @ xhigh) |
| validation cost                       | $1.07 (156 calls, gpt-5.6-luna)         |
| cost per verdict                      | $0.049                                  |
| one-shots (selection + dedup, Sonnet) | $0.21                                   |
| TOTAL gateway cost                    | $3.15                                   |

## Per-finding

| id   | cluster | real | kept | severity (truth) | prio (validator→) | title                                                                |
| ---- | ------- | ---- | ---- | ---------------- | ----------------- | -------------------------------------------------------------------- |
| XB1  | –       | yes  | yes  | should_fix       | must_fix          | Reject malformed PR URLs before selecting a PR                       |
| XB2  | 31      | no   | yes  | –                | must_fix          | Recheck the inbox toggle inside the Celery task                      |
| XB3  | –       | no   | no   | –                | consider          | Distinguish opt-out from missing reviewer assignment                 |
| XB4  | 6       | yes  | yes  | should_fix       | must_fix          | Verify Inbox PR identity before relaxing hard gates                  |
| XB5  | 58      | no   | yes  | –                | should_fix        | Do not drop reviews when the broker is unavailable                   |
| XB6  | –       | yes  | yes  | consider         | should_fix        | Pin the reviewability check to a consistent database                 |
| XB7  | 58      | yes  | yes  | should_fix       | should_fix        | Make the initial review hand-off durable                             |
| XB8  | –       | no   | yes  | –                | must_fix          | Keep self-driving re-reviews limited to draft PRs                    |
| XB9  | –       | yes  | yes  | must_fix         | must_fix          | Serialize repo disabling with inbox run creation                     |
| XB10 | 1       | yes  | yes  | must_fix         | must_fix          | must_fix: The documented task filter skips real self-driving runs    |
| XB11 | 2       | yes  | yes  | should_fix       | must_fix          | must_fix: The initial entry does not enforce the provenance boundary |
| XB12 | 2       | yes  | yes  | should_fix       | must_fix          | Validate the PR before enabling the Inbox approval path              |
| XB13 | 31      | no   | yes  | –                | must_fix          | Recheck the toggle before starting and publishing                    |
| XB14 | 2       | yes  | yes  | should_fix       | must_fix          | Bind the receiver review to a verified implementation run            |
| XB15 | 1       | yes  | yes  | must_fix         | must_fix          | Use a server-owned marker for implementation runs                    |
| XB16 | 6       | yes  | yes  | should_fix       | must_fix          | Validate the PR before enabling the self-driving bypass              |
| XB17 | 3       | no   | no   | –                | should_fix        | Require a real boolean for the security-sensitive flag               |
| XB18 | –       | yes  | yes  | must_fix         | must_fix          | Allow actual Inbox implementation tasks                              |
| XB19 | 57      | yes  | no   | should_fix       | must_fix          | Honor any opted-in assigned reviewer                                 |
| XB20 | 39      | yes  | yes  | should_fix       | should_fix        | Scope the task lookup before selecting a run                         |
| XB21 | 9       | no   | yes  | –                | should_fix        | Coalesce repeated receiver jobs before fetching GitHub               |
| XB22 | 76      | no   | yes  | –                | must_fix          | Pin toggle reads to the writer                                       |
