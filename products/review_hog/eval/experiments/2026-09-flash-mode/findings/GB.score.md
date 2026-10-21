# GB scorecard — glm-high-2 (frozen PR 75215, clean room, inline skills)

|                                       | GB                                              |
| ------------------------------------- | ----------------------------------------------- |
| run                                   | glm-high-2                                      |
| wall-clock                            | 4261s (71.0 min)                                |
| chunks / review units                 | 4 / 16                                          |
| raw → dedup → kept (validator)        | 55 → 35 → 14                                    |
| findings judged (post-dedup)          | 35 (0 unscored)                                 |
| real findings (reviewer side)         | 10/35 (29%)                                     |
| real clusters found                   | 7 [2, 5, 8, 27, 29, 31, 57]                     |
| new real issues (not in registry)     | 3 ['GB1', 'GB15', 'GB16']                       |
| kept that were real (precision)       | 10/14 (71%)                                     |
| real findings kept (recall)           | 10/10 (100%)                                    |
| not-real findings dropped             | 21/25 (84%)                                     |
| findings with NO verdict              | 0                                               |
| review + blind-spot cost              | $1.12 (385 calls, zai-org/glm-5.3-flash @ high) |
| validation cost                       | $0.99 (459 calls, zai-org/glm-5.3-flash)        |
| cost per verdict                      | $0.028                                          |
| one-shots (selection + dedup, Sonnet) | $0.30                                           |
| TOTAL gateway cost                    | $2.41                                           |

## Per-finding

| id   | cluster | real | kept | severity (truth) | prio (validator→) | title                                                                                      |
| ---- | ------- | ---- | ---- | ---------------- | ----------------- | ------------------------------------------------------------------------------------------ |
| GB1  | –       | yes  | yes  | consider         | consider          | Claim that bot authors are refused at the webhook pre-filter is imprecise for machine-user |
| GB2  | 57      | yes  | yes  | consider         | should_fix        | PR contract says "at least one assigned user opted in", but the code gates on the single a |
| GB3  | 8       | yes  | yes  | consider         | consider          | stamphog_connected is team-wide while the toggle takes effect per-repository, so "connecte |
| GB4  | 22      | no   | no   | –                | consider          | New identification contract builds on a model field marked deprecated                      |
| GB5  | –       | no   | no   | –                | consider          | Carve-out provenance carries an internal user id into run output with no documented exposu |
| GB6  | –       | no   | no   | –                | consider          | to_dict audit field records the flag but not the provenance it claims to audit             |
| GB7  | 13      | no   | no   | –                | consider          | \_parse_pr_url matches GitHub PR URLs anywhere inside a string                             |
| GB8  | 10      | no   | no   | –                | consider          | Carve-out path resolves the repo config twice on the writer database                       |
| GB9  | –       | no   | no   | –                | consider          | review_hog settings module eagerly imports the stamphog facade, putting stamphog model imp |
| GB10 | 29      | yes  | yes  | should_fix       | should_fix        | Carve-out retry is placed in front of the skip-path approval retraction, so a resolver out |
| GB11 | 51      | no   | yes  | –                | consider          | Broad except Exception in get_stamphog_connected turns any cross-product contract breakage |
| GB12 | –       | no   | no   | –                | should_fix        | Self-driving identification accepts an unvalidated, user-suppliable signal_report_id       |
| GB13 | 18      | no   | no   | –                | consider          | has_reviewable_repo_config matches configs differently from the review path                |
| GB14 | 3       | no   | no   | –                | should_fix        | self_driving_review flag accepts any truthy context value instead of validating the boolea |
| GB15 | –       | yes  | yes  | consider         | should_fix        | Carve-out invariant section omits the repo-native head requirement that keeps task linkage |
| GB16 | –       | yes  | yes  | should_fix       | should_fix        | Toggle stays enabled and looks healthy while Stamphog is disconnected, with no signal that |
| GB17 | 31      | yes  | yes  | consider         | consider          | Initial Stamphog review never re-checks the toggle at run time, so a mid-flight opt-out st |
| GB18 | 27      | yes  | yes  | consider         | consider          | Fail-soft `stamphog_connected` conflates 'not set up' with 'read failed', producing a misl |
| GB19 | 2       | yes  | yes  | should_fix       | should_fix        | Initial inbox review leg never verifies the PR is genuinely a self-driving PR before spend |
| GB20 | –       | no   | no   | –                | consider          | Resolver's None is conflated with opt-out, so 'nobody resolvable' reports and dismisses as |
| GB21 | 58      | no   | no   | –                | consider          | Retry budget is too small for a leg with no webhook redelivery behind it                   |
| GB22 | 4       | no   | no   | –                | should_fix        | Familiarity signal is not actually suppressed for self-driving runs, contradicting the pro |
| GB23 | 5       | yes  | yes  | consider         | consider          | Provenance block asserts draft and machine-author facts the engine never verifies for the  |
| GB24 | 72      | no   | no   | –                | consider          | Carve-out section does not state the synced-and-enabled repo config precondition           |
| GB25 | –       | no   | no   | –                | consider          | Carve-out section omits the receiver leg's failure behavior                                |
| GB26 | 9       | no   | yes  | –                | consider          | Stamphog review is re-queued on every TaskRun output save, so each refire costs a Celery t |
| GB27 | 58      | no   | yes  | –                | should_fix        | A failed broker publish silently loses the initial Stamphog review with no retry           |
| GB28 | 7       | no   | yes  | –                | consider          | stamphog_connected runs an uncached cross-database query on every settings read            |
| GB29 | 65      | no   | no   | –                | consider          | stamphog_connected is only computed at load, so a just-completed Stamphog connection leave |
| GB30 | 23      | no   | no   | –                | should_fix        | New carve-out caller triggers unindexed scans on the tasks branch-match leg for every bot  |
| GB31 | 41      | no   | no   | –                | should_fix        | Repeated receiver fires re-create review runs for a FAILED head with no cooldown           |
| GB32 | –       | no   | no   | –                | consider          | Missing resolver hides positively identified self-driving PRs in the skip logs             |
| GB33 | –       | no   | no   | –                | consider          | Bot-author gate predicate is duplicated between Pipeline.run and review_local.run          |
| GB34 | –       | no   | no   | –                | consider          | README understates when the webhook carve-out re-reviews                                   |
| GB35 | –       | no   | no   | –                | consider          | Section presents the receiver leg as initial-review-only; it is also a recurring re-review |
