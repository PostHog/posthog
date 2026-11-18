# UB scorecard — luna-low-2 (frozen PR 75215, clean room, inline skills)

|                                       | UB                                   |
| ------------------------------------- | ------------------------------------ |
| run                                   | luna-low-2                           |
| wall-clock                            | 961s (16.0 min)                      |
| chunks / review units                 | 4 / 13                               |
| raw → dedup → kept (validator)        | 8 → 8 → 7                            |
| findings judged (post-dedup)          | 8 (0 unscored)                       |
| real findings (reviewer side)         | 4/8 (50%)                            |
| real clusters found                   | 2 [2, 31]                            |
| new real issues (not in registry)     | 0 []                                 |
| kept that were real (precision)       | 4/7 (57%)                            |
| real findings kept (recall)           | 4/4 (100%)                           |
| not-real findings dropped             | 1/4 (25%)                            |
| findings with NO verdict              | 0                                    |
| review + blind-spot cost              | $0.21 (60 calls, gpt-5.6-luna @ low) |
| validation cost                       | $0.06 (23 calls, gpt-5.6-luna)       |
| cost per verdict                      | $0.007                               |
| one-shots (selection + dedup, Sonnet) | $0.03                                |
| TOTAL gateway cost                    | $0.30                                |

## Per-finding

| id  | cluster | real | kept | severity (truth) | prio (validator→) | title                                                           |
| --- | ------- | ---- | ---- | ---------------- | ----------------- | --------------------------------------------------------------- |
| UB1 | 3       | no   | no   | –                | must_fix          | Validate the self-driving flag as a strict boolean              |
| UB2 | 2       | yes  | yes  | must_fix         | must_fix          | Validate that the queued PR belongs to the Inbox implementation |
| UB3 | 2       | yes  | yes  | must_fix         | must_fix          | Validate the PR against the task repository before queueing     |
| UB4 | 16      | no   | yes  | –                | should_fix        | Catch deferred import failures in the commit callback           |
| UB5 | 58      | no   | yes  | –                | should_fix        | Retry failed Celery dispatches for the initial inbox review     |
| UB6 | –       | no   | yes  | –                | must_fix          | Do not run approval flow on draft pull requests                 |
| UB7 | 2       | yes  | yes  | should_fix       | must_fix          | Revalidate the inbox PR before creating the initial review      |
| UB8 | 31      | yes  | yes  | consider         | should_fix        | Re-check the opt-in toggle before creating the initial review   |
