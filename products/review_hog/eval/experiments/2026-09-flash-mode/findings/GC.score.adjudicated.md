# GC scorecard — glm-high-1bc (frozen PR 75215, clean room, inline skills)

|                                       | GC                                              |
| ------------------------------------- | ----------------------------------------------- |
| run                                   | glm-high-1bc                                    |
| wall-clock                            | 5008s (83.5 min)                                |
| chunks / review units                 | 4 / 13                                          |
| raw → dedup → kept (validator)        | 46 → 36 → 13                                    |
| findings judged (post-dedup)          | 36 (0 unscored)                                 |
| real findings (reviewer side)         | 9/36 (25%)                                      |
| real clusters found                   | 6 [2, 8, 27, 35, 36, 57]                        |
| new real issues (not in registry)     | 3 ['GC3', 'GC32', 'GC34']                       |
| kept that were real (precision)       | 5/13 (38%)                                      |
| real findings kept (recall)           | 5/9 (56%)                                       |
| not-real findings dropped             | 18/27 (67%)                                     |
| findings with NO verdict              | 1                                               |
| review + blind-spot cost              | $1.15 (353 calls, zai-org/glm-5.3-flash @ high) |
| validation cost                       | $1.26 (433 calls, zai-org/glm-5.3-flash)        |
| cost per verdict                      | $0.036                                          |
| one-shots (selection + dedup, Sonnet) | $0.15                                           |
| TOTAL gateway cost                    | $2.56                                           |

## Per-finding

| id   | cluster | real | kept | severity (truth) | prio (validator→) | title                                                                                      |
| ---- | ------- | ---- | ---- | ---------------- | ----------------- | ------------------------------------------------------------------------------------------ |
| GC1  | 26      | no   | no   | –                | should_fix        | stamphog_review_inbox_prs can be enabled via API while no Stamphog repo is connected       |
| GC2  | 13      | no   | no   | –                | should_fix        | PR URL parser accepts lookalike hosts and injectable characters                            |
| GC3  | –       | yes  | yes  | consider         | consider          | tach comment claims facade-only enforcement the interface block does not provide           |
| GC4  | –       | no   | no   | –                | consider          | queue_inbox_pr_review dispatches without validating its inputs                             |
| GC5  | –       | no   | no   | –                | consider          | Relaxed-gate guard condition is duplicated across the two entry points                     |
| GC6  | –       | no   | no   | –                | consider          | Audit-trail comment overstates what the output records                                     |
| GC7  | 57      | yes  | no   | should_fix       | should_fix        | Stated gate 'at least one assigned user opted in' is not what the code implements          |
| GC8  | 41      | no   | yes  | –                | consider          | A FAILED run at the current head is re-created on every receiver refire, with no cap       |
| GC9  | 18      | no   | no   | –                | consider          | has_reviewable_repo_config omits the provider="github" filter every other repo-config quer |
| GC10 | 53      | no   | no   | –                | consider          | Opt-out dismissal copy also fires when the reviewer simply cannot be resolved, and on non- |
| GC11 | 44      | no   | yes  | –                | consider          | Run-creation failure log drops the exception message the sibling handlers include          |
| GC12 | 36      | yes  | yes  | consider         | should_fix        | Same-head race between the inbox leg and the webhook carve-out leg causes a duplicate sand |
| GC13 | 33      | no   | no   | –                | should_fix        | Carve-out resolution runs several uncached DB queries on every skipped bot or draft head-c |
| GC14 | 31      | no   | no   | –                | consider          | Receiver leg acts on a toggle decision made at dispatch time, unlike the webhook leg's per |
| GC15 | –       | no   | yes  | –                | consider          | README describes the receiver trigger as a single PR-open event, but it re-fires on every  |
| GC16 | –       | no   | yes  | –                | consider          | stamphog_connected reads the lagged product-DB reader, so a just-connected repo reports di |
| GC17 | 51      | no   | no   | –                | consider          | Broad except Exception in get_stamphog_connected logs a full ERROR traceback on every sett |
| GC18 | 2       | yes  | yes  | should_fix       | should_fix        | Receiver-leg review skips the positive-identification checks the webhook carve-out require |
| GC19 | 3       | no   | no   | –                | consider          | Carve-out flag is accepted from any truthy context value instead of a strict boolean       |
| GC20 | 27      | yes  | no   | consider         | consider          | Fail-soft stamphog_connected cannot be told apart from 'not connected', so an outage shows |
| GC21 | 8       | yes  | no   | consider         | consider          | UI gate is team-wide while the actual review gate is per-repository, enabling a switch tha |
| GC22 | 40      | no   | no   | –                | consider          | Webhook-leg resolver raises unguarded into the delivery retry path                         |
| GC23 | 4       | no   | no   | –                | should_fix        | Self-driving provenance block claims familiarity is absent, but the familiarity signal sti |
| GC24 | 35      | yes  | yes  | consider         | consider          | Provenance block asserts 'It is a draft on purpose' unconditionally, but the flagged PR ma |
| GC25 | 16      | no   | no   | –                | should_fix        | Deferred facade import sits outside the try block, so an import failure can raise into the |
| GC26 | 7       | no   | no   | –                | consider          | stamphog_connected runs an uncached cross-database query on every settings GET and PATCH   |
| GC27 | 58      | no   | no   | –                | consider          | A failed broker publish silently drops the initial stamphog review with no retry           |
| GC28 | –       | no   | no   | –                | consider          | Registered resolver logs nothing, so a toggle-off skip is indistinguishable from a resolut |
| GC29 | 58      | no   | yes  | –                | consider          | Rate-limit retries for the initial inbox review exhaust before GitHub's rate window ends,  |
| GC30 | 9       | no   | no   | –                | consider          | Receiver refires pay a GitHub API fetch before any dedupe check                            |
| GC31 | –       | no   | yes  | –                | consider          | Resolution failure is publicly reported as an opt-out in the dismissal comment             |
| GC32 | –       | yes  | yes  | consider         | consider          | stamphog_connected help_text describes UI behavior the switch deliberately does not implem |
| GC33 | 11      | no   | yes  | –                | consider          | Carve-out contract presents the acting reviewer as a stable identity, but the resolver re- |
| GC34 | –       | yes  | no   | consider         | consider          | Opening sentence describes only the webhook leg's identification as if it covered both leg |
| GC35 | –       | no   | yes  | –                | consider          | Deliberate draft-to-ready no-op is absent from the carve-out contract                      |
| GC36 | 3       | no   | no   | –                | consider          | self_driving_review context key is read with a truthiness check instead of a strict identi |
