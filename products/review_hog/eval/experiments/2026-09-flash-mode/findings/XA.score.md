# XA scorecard — luna-xhigh-1 (frozen PR 75215, clean room, inline skills)

|                                       | XA                                      |
| ------------------------------------- | --------------------------------------- |
| run                                   | luna-xhigh-1                            |
| wall-clock                            | 2160s (36.0 min)                        |
| chunks / review units                 | 4 / 13                                  |
| raw → dedup → kept (validator)        | 32 → 22 → 20                            |
| findings judged (post-dedup)          | 22 (0 unscored)                         |
| real findings (reviewer side)         | 15/22 (68%)                             |
| real clusters found                   | 8 [2, 6, 18, 31, 36, 39, 58, 75]        |
| new real issues (not in registry)     | 4 ['XA6', 'XA11', 'XA15', 'XA22']       |
| kept that were real (precision)       | 15/20 (75%)                             |
| real findings kept (recall)           | 15/15 (100%)                            |
| not-real findings dropped             | 2/7 (29%)                               |
| findings with NO verdict              | 0                                       |
| review + blind-spot cost              | $2.12 (370 calls, gpt-5.6-luna @ xhigh) |
| validation cost                       | $1.11 (157 calls, gpt-5.6-luna)         |
| cost per verdict                      | $0.050                                  |
| one-shots (selection + dedup, Sonnet) | $0.26                                   |
| TOTAL gateway cost                    | $3.49                                   |

## Per-finding

| id   | cluster | real | kept | severity (truth) | prio (validator→) | title                                                               |
| ---- | ------- | ---- | ---- | ---------------- | ----------------- | ------------------------------------------------------------------- |
| XA1  | 75      | yes  | yes  | must_fix         | must_fix          | Restrict the webhook carve-out to the PostHog Code bot              |
| XA2  | 6       | yes  | yes  | must_fix         | must_fix          | Validate the self-driving PR shape before bypassing hard gates      |
| XA3  | 18      | yes  | yes  | consider         | should_fix        | Align the connected flag with the worker's config resolution        |
| XA4  | 4       | no   | no   | –                | should_fix        | Suppress author familiarity for self-driving prompts                |
| XA5  | 58      | yes  | yes  | should_fix       | should_fix        | Broker errors can lose the initial review                           |
| XA6  | –       | yes  | yes  | must_fix         | must_fix          | Re-check the repo config before creating the run                    |
| XA7  | 2       | yes  | yes  | must_fix         | must_fix          | Enforce inbox provenance before enabling the carve-out              |
| XA8  | –       | no   | yes  | –                | should_fix        | Align the webhook bot check with the documented bot set             |
| XA9  | 2       | yes  | yes  | must_fix         | must_fix          | Validate the task and PR before enabling the self-driving carve-out |
| XA10 | 31      | yes  | yes  | should_fix       | should_fix        | Re-check the inbox toggle in the Celery task                        |
| XA11 | –       | yes  | yes  | must_fix         | must_fix          | Allow Inbox implementation tasks to reach the new dispatch          |
| XA12 | 39      | yes  | yes  | should_fix       | should_fix        | Filter task runs before selecting the first webhook match           |
| XA13 | 2       | yes  | yes  | must_fix         | must_fix          | Validate the PR before enabling the carve-out                       |
| XA14 | 9       | no   | yes  | –                | should_fix        | Repeated saves enqueue duplicate Stamphog tasks                     |
| XA15 | –       | yes  | yes  | consider         | should_fix        | Connection status can be stale after setup                          |
| XA16 | –       | no   | yes  | –                | must_fix          | pin the supersession lock to the writer database                    |
| XA17 | 36      | yes  | yes  | should_fix       | should_fix        | deduplicate receiver and webhook reviews by head                    |
| XA18 | 58      | yes  | yes  | should_fix       | should_fix        | recover queued runs after the Temporal hand-off fails               |
| XA19 | –       | no   | yes  | –                | should_fix        | Avoid unnecessary LLM runs for pending migration checks             |
| XA20 | –       | no   | yes  | –                | must_fix          | Do not review Inbox PRs after they become ready                     |
| XA21 | 76      | no   | no   | –                | must_fix          | Pin toggle reads before queuing approval reviews                    |
| XA22 | –       | yes  | yes  | should_fix       | should_fix        | Redeliver the task when a worker is lost                            |
