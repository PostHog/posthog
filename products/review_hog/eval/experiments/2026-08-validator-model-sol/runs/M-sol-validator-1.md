# Reviewer-quality run — `M-sol-validator-1`

- **Dumped:** 2026-08-26T02:38:34+00:00
- **Report id:** `01a03bc9-2dc0-7639-8103-8ef2da18ffdf` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 2455s (40.9 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 12           | 24         | 19          | 18               |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 18s      |
| review wave (perspectives)  | 16m 59s  |
| blind-spot sweep            | 8m 57s   |
| dedup (incl. combine/clean) | 1m 38s   |
| validation                  | 12m 45s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 25m 57s — the reviewer-model speed comparison number.
- Derived from artefact `created_at` (persisted on completion); only meaningful for fresh, non-resumed runs.

## Chunking

- **chunk 1** (8 files): products/review_hog/backend/models.py, products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py, products/review_hog/backend/api/settings.py, products/review_hog/backend/receivers.py, products/review_hog/frontend/CodeReviewScene.tsx, products/review_hog/frontend/generated/api.schemas.ts, products/review_hog/frontend/generated/api.zod.ts, services/mcp/src/api/generated.ts
- **chunk 2** (8 files): products/stamphog/backend/facade/api.py, products/stamphog/backend/facade/inbox_hooks.py, products/stamphog/backend/tasks/tasks.py, products/stamphog/backend/temporal/activities.py, products/stamphog/backend/logic/reviewer.py, products/tasks/backend/facade/api.py, products/tasks/backend/facade/contracts.py, tach.toml
- **chunk 3** (4 files): tools/pr-approval-agent/review_pr.py, tools/pr-approval-agent/review_local.py, tools/pr-approval-agent/reviewer.py, tools/pr-approval-agent/version.py
- **chunk 4** (2 files): products/stamphog/AGENTS.md, products/stamphog/README.md

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 2          |
| 1    | 2     | review-hog-perspective-contracts-security      | 3          |
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 3          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 2          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 3          |
| 1000 | 1     | review-hog-blind-spots-general                 | 2          |
| 1000 | 2     | review-hog-blind-spots-general                 | 3          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | review-hog-blind-spots-general                 | 1          |

## Findings (post-dedup) with validator verdict

### [✅ VALID] must_fix · bug — products/stamphog/backend/tasks/tasks.py:873-881

**Carve-out failures bypass approval retraction**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `_inbox_rereview_carve_out` runs several database queries before the skip path retracts stale approvals. If one query fails, this handler retries before `_retract_stale_approvals_on_skip` runs. The task stops after three short retries. An approval for the previous head can then remain active on unreviewed commits.
- **Suggestion:** Retract stale approvals before resolving the carve-out for every head-changing skipped PR. The retraction is idempotent, so an opted-in workflow can run it again. Reuse the resolved repo config to avoid a second query.
- **Validator:** - **Checked:** Traced `process_pull_request_event`, `_inbox_rereview_carve_out`, its data lookups, and both approval dismissal paths.
- **Found:** `_inbox_rereview_carve_out` queries the repo config, task run, reviewer assignment, and user settings at `products/stamphog/backend/tasks/tasks.py:179-205`. Retraction starts only at `products/stamphog/backend/tasks/tasks.py:887-898`.
- **Found:** An exception exits through `retry()` at `products/stamphog/backend/tasks/tasks.py:877-879`. The task permits only three retries at `products/stamphog/backend/tasks/tasks.py:809`.
- **Found:** The webhook returns before the task runs at `products/stamphog/backend/presentation/webhooks.py:61-64`. GitHub therefore does not provide another delivery after task retries stop.
- **Found:** The dismissal helper is idempotent at `products/stamphog/backend/logic/approvals.py:37-40`. An early dismissal can safely run before the later workflow dismissal.
- **Impact:** A Tasks or ReviewHog database failure can leave an old approval active while Stamphog and GitHub remain available. That approval can satisfy a required review for commits that Stamphog did not review.

### [✅ VALID] must_fix · security — products/review_hog/backend/api/settings.py:58-65,71-78

**Child environment access reaches parent Stamphog settings**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The endpoint stores settings under the canonical parent team, but its default permissions authorize the team from the URL. The new fields read the parent team's Stamphog state and control approvals for parent repositories. A user with child-only access can use the child URL to read parent connection state and change parent-owned behavior. Stamphog's viewsets add a canonical-team permission for this exact boundary.
- **Suggestion:** Authorize the requester against resolve_effective_team_id(self.team_id) before serialization or PATCH. Check canonical-team membership and token scope. Extract or reproduce the policy used by StamphogCanonicalTeamAccessPermission without importing Stamphog presentation code.
- **Validator:** - **Checked:** `TeamMemberAccessPermission` checks the URL team (`posthog/api/routing.py:296-304`, `posthog/permissions.py:214-238`). Child and parent access can differ (`posthog/user_permissions.py:201-272`).
- **Found:** `_get_or_create()` converts the child ID to its parent ID (`products/review_hog/backend/api/settings.py:98-105`). `get_stamphog_connected()` then queries Stamphog with that parent ID (`products/review_hog/backend/api/settings.py:71-81`).
- **Found:** PATCH saves `stamphog_review_inbox_prs` on the parent-scoped row (`products/review_hog/backend/api/settings.py:130-137`). The receiver reads that row and can queue a parent-team review (`products/review_hog/backend/receivers.py:111-139`).
- **Found:** Stamphog adds `StamphogCanonicalTeamAccessPermission` for this boundary (`products/stamphog/backend/presentation/views.py:107-143`). Its test confirms that child scope alone must not grant parent access (`products/stamphog/backend/tests/test_api.py:108-130`).
- **Checked:** `scope_object = "INTERNAL"` currently rejects PAK and OAuth requests (`products/review_hog/backend/api/settings.py:93`, `posthog/permissions.py:514-515`, `posthog/permissions.py:598-602`). Session-authenticated child-only users remain affected.
- **Impact:** A child-only user can learn the parent's Stamphog connection state. The user can also enable reviews that may post approvals to parent repositories.

### [✅ VALID] should_fix · bug — tools/pr-approval-agent/reviewer.py:695-700

**The trusted prompt always states that the PR is a draft**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The self-driving path also handles synchronize and reopen events after a PR becomes ready. This block always tells the model that the PR is a draft. The statement is false for those reviews. The prompt does not include the actual draft value in its trusted context.
- **Suggestion:** Pass `pr.draft` to `_format_self_driving`. Render the draft-specific text only when it is true. Omit that text or state that the PR is ready when it is false.
- **Validator:** - **Checked:** Traced the self-driving flag from webhook handling through context loading and prompt construction.
- **Found:** `products/stamphog/backend/tasks/tasks.py:160` includes later `synchronize` and `reopened` events. The gate at `products/stamphog/backend/tasks/tasks.py:167` does not require a draft PR.
- **Found:** `products/stamphog/backend/temporal/activities.py:220` fetches the current PR state. `tools/pr-approval-agent/review_local.py:197` stores its actual draft value.
- **Found:** `tools/pr-approval-agent/reviewer.py:506` passes only `cl` to `_format_self_driving`. The text at `tools/pr-approval-agent/reviewer.py:698` therefore always reports a draft.
- **Impact:** A push after `ready_for_review` gives the model false trusted context. This can affect its approval decision for a real supported event path.

### [✅ VALID] should_fix · bug — products/stamphog/backend/facade/api.py:149-155

**Broker failures can lose the initial review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `queue_inbox_pr_review` publishes directly to Celery after the caller's TaskRun transaction commits. The caller logs broker failures and lets the save succeed. No durable row records the missing dispatch. The `opened` webhook path also rejects this bot draft, so a one-commit PR can miss its only initial review.
- **Suggestion:** Persist a pending inbox-review dispatch in the TaskRun transaction. Let a worker or periodic sweeper publish it until Celery accepts it. As a smaller backstop, let the `opened` webhook create the head-keyed run when the receiver dispatch is missing.
- **Validator:** - **Checked:** Traced the TaskRun receiver, the facade dispatch, repeat output saves, and all Stamphog webhook actions.
- **Found:** The receiver registers `_start_stamphog_review` after commit at `products/review_hog/backend/receivers.py:126-139`. That function catches every dispatch error at `products/review_hog/backend/receivers.py:224-234`.
- **Found:** `queue_inbox_pr_review` only calls `.delay()` at `products/stamphog/backend/facade/api.py:147-155`. It creates no durable state before that call.
- **Found:** The webhook carve-out rejects `opened` events at `products/stamphog/backend/tasks/tasks.py:167-168`. The normal path then skips the bot draft at `products/stamphog/backend/tasks/tasks.py:870-912`.
- **Found:** The Tasks webhook saves the PR URL only when it is missing at `products/tasks/backend/webhooks.py:203-213`. It cannot retry dispatch after the first save already stored that URL.
- **Impact:** A broker outage can leave a successful PR URL save with no Stamphog run. A one-commit bot draft has no guaranteed later event that repairs this loss.

### [❌ dismissed] must_fix — products/stamphog/backend/tasks/tasks.py:201-207

**One opted-out reviewer blocks other opted-in reviewers**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The registered resolver selects one acting reviewer before it checks the toggle. If that reviewer opts out, it returns None even when another assigned reviewer opts in. This path then skips the review and reports a full opt-out. The stated behavior requires any assigned reviewer to enable the review.
- **Suggestion:** Resolve all assigned reviewers and select an opted-in reviewer. Prefer the task creator when that user is assigned and opted in. Otherwise, select the first opted-in assignee. Return None only when no assigned reviewer opts in. Use the same rule for the initial and webhook paths.
- **Validator:** - **Checked:** Traced reviewer selection, both Stamphog toggle checks, the recorded product decision, and multi-reviewer tests.
- **Found:** `_resolve_assigned_reviewer` deliberately selects the assigned task creator or the first resolved assignee at `products/review_hog/backend/receivers.py:159-207`.
- **Found:** Both trigger paths check only that selected user's toggle at `products/review_hog/backend/receivers.py:111-126` and `products/review_hog/backend/receivers.py:144-156`.
- **Found:** The product decision says a non-acting reviewer's opt-in must not replace the acting reviewer at `products/review_hog/DECISIONS.md:2668-2683`.
- **Found:** `test_opted_out_canonical_reviewer_blocks_the_review` enforces this behavior at `products/review_hog/backend/tests/test_inbox_trigger.py:228-238`.
- **Impact:** The suggested selection rule would reverse an explicit ownership rule. The current code follows the documented contract and its regression test.

### [✅ VALID] must_fix · security — products/stamphog/AGENTS.md:84-87,98-99

**Caller-writable PR URLs can activate the trusted carve-out**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The new invariant says that only verified TaskRun links set `self_driving_review`. The code does not enforce this contract. `TaskRun.output.pr_url` is caller-writable. Team members can control signal-report tasks through `task_control_q`. The initial path trusts this URL without reloading `task_run_id` or verifying the task repository, native head repository, or bot author. The webhook path also matches this writable URL through `find_signal_implementation_run`. An opted-in reviewer can therefore cause Stamphog to bypass trust gates and approve a PR that the run did not create.
- **Suggestion:** Use a server-attested PR-to-run binding before creating `ReviewRun`. Reload the TaskRun through the tasks facade with team scope. Verify the signal report, task type, repository, native head, expected bot author, and attested PR or branch. Make `find_signal_implementation_run` use the same attested binding. Add a regression test that writes another PR URL through the task API and confirms that no review starts.
- **Validator:** - **Checked:** I traced task-run output writes, task-control rules, the inbox receiver, and the webhook lookup.
- **Found:** `task_control_q` grants every team member control of signal tasks (`products/tasks/backend/visibility.py:30`). Both output paths accept a caller's `pr_url`; only `pr_merged` is protected (`products/tasks/backend/facade/api.py:1764`, `products/tasks/backend/facade/api.py:2038`, `products/tasks/backend/facade/api.py:2147`).
- **Found:** The receiver forwards `output["pr_url"]` after task-shape and preference checks (`products/review_hog/backend/receivers.py:92`). `process_inbox_pr_review` does not reload `task_run_id`. It stamps `inbox_review` directly from its arguments after basic PR checks (`products/stamphog/backend/tasks/tasks.py:1130`, `products/stamphog/backend/tasks/tasks.py:1176`).
- **Found:** The webhook lookup also trusts an exact `TaskRun.output.pr_url` match (`products/tasks/backend/webhooks.py:36`). Its remaining checks cover team scope, signal linkage, and internal status only (`products/tasks/backend/facade/api.py:484`).
- **Impact:** A team member can bind another open PR to an eligible signal run. The initial path can also accept a fork or an unexpected author. `post_verdict` can submit an APPROVE review for that run (`products/stamphog/backend/temporal/activities.py:723`). This crosses the task permission boundary into a GitHub approval.

### [✅ VALID] must_fix · security — products/review_hog/backend/receivers.py:126-138

**Untrusted TaskRun output can authorize an unrelated PR**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** TaskRun.output.pr_url is user-writable. This path forwards it after checking only the task shape and the user toggle. It does not prove that the PR belongs to task.repository or that this TaskRun produced it. Stamphog then marks the run as an Inbox review. This mark bypasses the usual draft, bot, review-mode, and author-permission gates. A caller can target another PR that the team's GitHub App can access. Stamphog can then post a real approval to unrelated code.
- **Suggestion:** Validate the fetched PR in the durable Stamphog task before it creates Inbox provenance. Call find_signal_implementation_run with the fetched repository, URL, and repo-native head branch. Require its run_id, team_id, and signal_report_id to match the queued values. Also require the expected bot author and reject fork heads. Add a cheap task.repository check here, but keep the durable task as the security boundary.
- **Validator:** - **Checked:** `TaskRunUpdateSerializer` accepts caller-supplied `output` and `branch` values (`products/tasks/backend/presentation/serializers.py:167-180`). Signal-report tasks are controllable by team members (`products/tasks/backend/visibility.py:22-46`).
- **Found:** The receiver does not compare `pr_url` with `task.repository`. It forwards the supplied URL when the assigned reviewer opted in (`products/review_hog/backend/receivers.py:92-138`).
- **Found:** `process_inbox_pr_review()` accepts any open PR with a head SHA in a synced, enabled team repository (`products/stamphog/backend/tasks/tasks.py:1130-1174`). It does not verify the task, report, author, head repository, or fork status.
- **Found:** The task then writes `inbox_review` provenance and starts the workflow (`products/stamphog/backend/tasks/tasks.py:1176-1234`). The webhook path performs the missing linkage and fork checks (`products/stamphog/backend/tasks/tasks.py:144-215`).
- **Found:** The workflow converts this provenance into `self_driving_review` (`products/stamphog/backend/temporal/activities.py:448-452`). The integration test confirms that this path can post an approval (`products/stamphog/backend/tests/test_integration.py:1385-1423`).
- **Checked:** The target needs an enabled, synced `StamphogRepoConfig`; GitHub App access alone is insufficient (`products/stamphog/backend/tasks/tasks.py:1136-1153`). Unrelated PRs in configured repositories remain reachable.
- **Found:** `find_signal_implementation_run()` alone cannot prove provenance. It first matches the caller-writable `TaskRun.output.pr_url` (`products/tasks/backend/facade/api.py:484-516`, `products/tasks/backend/webhooks.py:29-59`). Matching the queued run ID would therefore accept the planted URL. The fix needs an independent trusted link, plus author and fork checks.
- **Impact:** A task controller can grant trusted Inbox provenance to unrelated code. A passing review can post a GitHub approval.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1158-1181,1223-1229

**Initial review trusts a caller-controlled PR URL**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** TaskRun.output is writable through authenticated task endpoints. Any team member can control SIGNAL_REPORT tasks. The receiver forwards output.pr_url into this task. This code checks only that the team has a repository config and that the PR is open. It never validates task_run_id or the task repository. It also does not require the expected bot author or a repository-native head. The inbox_review flag then bypasses normal review and permission gates. A caller can request an App approval for any open PR in a connected repository.
- **Suggestion:** Treat the Celery payload as untrusted. Load task_run_id through a team-scoped facade. Verify the implementation run, report, repository, and PR binding. Require the expected bot author and a repository-native head. Resolve the acting reviewer and current toggle in the task. Stamp inbox_review only after all checks pass.
- **Validator:** - **Checked:** Traced TaskRun write access, output validation, the receiver, the initial review task, the engine flag, and approval posting.
- **Found:** `task_control_q` grants team members control of `SIGNAL_REPORT` tasks at `products/tasks/backend/visibility.py:30-46`.
- **Found:** Caller output can set `pr_url`. `_apply_caller_output` protects only `pr_merged` at `products/tasks/backend/facade/api.py:1764-1788`.
- **Found:** The receiver forwards that URL after checking the task shape and one reviewer's toggle at `products/review_hog/backend/receivers.py:92-139`.
- **Found:** `process_inbox_pr_review` derives the repository from the URL. It checks only the repository config, PR state, and head SHA at `products/stamphog/backend/tasks/tasks.py:1130-1181`.
- **Found:** The task does not validate `task_run_id`, the task repository, the PR author, or the head repository before stamping provenance at `products/stamphog/backend/tasks/tasks.py:1176-1229`.
- **Found:** That provenance enables the self-driving bypass at `products/stamphog/backend/temporal/activities.py:448-451`. The workflow can then post an approval at `products/stamphog/backend/temporal/activities.py:723-746`.
- **Impact:** A project member with task write access can target an unrelated open PR in a connected repository. Stamphog can post an App approval without the required task-to-PR authorization.

### [✅ VALID] must_fix · security — products/tasks/backend/facade/api.py:504-509

**Caller-writable task fields cannot prove PR provenance**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** find_task_run prioritizes output.pr_url. Both output and branch are writable through the TaskRun API. This facade uses that result as proof that the run produced the PR. It checks only signal_report_id and internal. A team member can attach an arbitrary bot PR to a signal task. Later webhooks can then bypass review-mode and author-permission gates when an assigned reviewer enabled the toggle.
- **Suggestion:** Use a server-owned PR binding as the authorization proof. Write it only after a verified GitHub event matches a server-owned expected branch or PR creation record. Require the implementation relationship, team, and repository. Do not authorize this carve-out from caller-writable output or branch fields.
- **Validator:** - **Checked:** Traced PR matching, TaskRun write access, facade checks, webhook carve-out checks, and the later review gates.
- **Found:** `find_task_run` first trusts `output.pr_url` at `products/tasks/backend/webhooks.py:36-59`. Its fallback trusts `TaskRun.branch` at `products/tasks/backend/webhooks.py:61-76`.
- **Found:** The TaskRun API accepts caller-provided `output` and `branch` at `products/tasks/backend/presentation/serializers.py:167-180`.
- **Found:** Team members can control `SIGNAL_REPORT` tasks through `task_control_q` at `products/tasks/backend/visibility.py:30-46`.
- **Found:** `find_signal_implementation_run` checks only the team, `signal_report_id`, and `internal` after matching at `products/tasks/backend/facade/api.py:484-516`.
- **Found:** The webhook path treats that result as provenance at `products/stamphog/backend/tasks/tasks.py:191-215`. It then bypasses review mode and author permission at `products/stamphog/backend/tasks/tasks.py:941-969`.
- **Impact:** A project member can bind an unrelated same-repository bot PR to a signal task. A later head-changing webhook can cause an App approval without the normal authorization gates.

### [✅ VALID] must_fix · security — tools/pr-approval-agent/review_local.py:316-324

**Authenticate self-driving provenance before bypassing approval gates**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The entry point treats any truthy `self_driving_review` value as trusted provenance. This value disables the bot-author refusal and draft gate. The repository treats `TaskRun.output.pr_url` as user-writable. The initial Inbox path can create this flag without checking the task repository, bot identity, or fork status. A user could route another accessible PR through the relaxed path and obtain a real GitHub approval.
- **Suggestion:** Derive this flag only after server-side checks of the source TaskRun and fetched PR. Match the persisted TaskRun and signal report. Require the PR repository to equal `task.repository`. Reject forks and require the expected PostHog Code App author. Pass `self_driving_review=True` only after all checks succeed. Also use `context.get("self_driving_review") is True` so malformed JSON fails closed. Add tests for a user-supplied URL, a fork, a human author, and another bot.
- **Validator:** - **Checked:** Traced `TaskRun.output.pr_url` through the Inbox receiver, hosted review, engine gates, and GitHub review posting.
- **Found:** `products/tasks/backend/presentation/serializers.py:179` accepts caller-supplied output. The policy at `products/tasks/backend/facade/api.py:1770` protects only `pr_merged`, not `pr_url`.
- **Found:** `products/review_hog/backend/receivers.py:92` reads this URL. The dispatch at `products/review_hog/backend/receivers.py:126` does not pass `task.repository` for validation.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1130` derives the repository from the supplied URL. It stamps provenance at `products/stamphog/backend/tasks/tasks.py:1176` without checking the task repository, author, or fork status.
- **Found:** `tools/pr-approval-agent/review_local.py:321` enables the bypass for any truthy value. `products/stamphog/backend/temporal/activities.py:745` can then post an app-authenticated approval.
- **Impact:** A user who controls an opted-in Signals task can substitute another PR in an enabled repository. An approved verdict becomes a real GitHub approval.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:111-126,151-155

**The Stamphog gate ignores opted-in secondary reviewers**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The code selects one acting reviewer before it reads the new toggle. It applies only that user's toggle to both trigger paths. A later assigned reviewer can opt in, but no review runs. This conflicts with the requirement that any opted-in assigned reviewer enables Stamphog.
- **Suggestion:** Resolve all assigned users for the Stamphog gate. Prefer the task creator when that assigned user is enabled. Otherwise, select the first enabled assigned user. Use this selection for the initial review and later re-reviews. Keep ReviewHog's existing single-reviewer rule separate.
- **Validator:** - **Checked:** Signals can assign up to three reviewers (`products/signals/backend/report_generation/resolve_reviewers.py:113-183`). The Inbox filter matches a user in any list position (`products/signals/backend/views.py:887-916`).
- **Found:** `_resolve_assigned_reviewer()` reduces the list to the assigned task creator or the first resolved user (`products/review_hog/backend/receivers.py:159-207`). It does not inspect the other users' Stamphog settings.
- **Found:** The initial trigger loads only that user's settings (`products/review_hog/backend/receivers.py:111-138`). The webhook resolver repeats the same selection (`products/review_hog/backend/receivers.py:144-156`).
- **Found:** The toggle promises to review self-driving implementations from the requesting user's Inbox (`products/review_hog/frontend/CodeReviewScene.tsx:1053-1062`). A secondary assignee sees the report in that Inbox but their enabled toggle has no effect.
- **Checked:** Existing multi-reviewer tests cover ReviewHog's canonical acting-user rule (`products/review_hog/backend/tests/test_inbox_trigger.py:205-267`). They do not cover a secondary-only Stamphog opt-in.
- **Impact:** A secondary assigned reviewer can enable Stamphog and still receive no initial review or later re-review. This breaks the new toggle's central behavior.

### [✅ VALID] must_fix · bug — products/tasks/backend/facade/api.py:504-508

**Team filters run after candidate selection**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `find_task_run` chooses one candidate before this facade applies the team and self-driving filters. Its URL and branch queries search all teams. A newer run from another team or a manual task can hide the valid run. The function then returns `None`, so later pushes skip the expected rereview.
- **Suggestion:** Filter by `team_id`, repository, non-internal task, and signal report before ranking candidates. Preserve the active-run ordering after these filters. Return a DTO only from the filtered query.
- **Validator:** - **Checked:** Traced candidate ranking, facade filters, webhook callers, and existing linkage tests.
- **Found:** The URL leg ranks all repository matches before returning one row at `products/tasks/backend/webhooks.py:36-59`. It has no team or task-shape filter.
- **Found:** The branch leg also selects one repository-wide candidate before any team filter at `products/tasks/backend/webhooks.py:61-78`.
- **Found:** The facade rejects that single candidate after selection at `products/tasks/backend/facade/api.py:504-509`. It does not search for another qualifying run.
- **Found:** `_inbox_rereview_carve_out` treats a `None` result as an ordinary bot PR at `products/stamphog/backend/tasks/tasks.py:191-200`.
- **Impact:** A newer manual or other-team run can hide a valid signal run with the same PR URL. The next push then misses its configured re-review. An unrelated tenant can also influence this selection.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:151-154

**Resolver failures can leave stale approvals active**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The resolver lets database errors escape. Stamphog calls this hook before its opt-out path retracts an earlier approval. The webhook task retries only three times. A longer error leaves the old approval active on the new commit.
- **Suggestion:** Catch lookup errors, log the team and report IDs, and return `None`. Stamphog then runs its stale-approval retraction path. Schedule any review retry only after retraction succeeds.
- **Validator:** - **Checked:** `resolve_stamphog_acting_reviewer()` performs reviewer and settings database lookups without error handling (`products/review_hog/backend/receivers.py:144-155`, `products/review_hog/backend/receivers.py:180-207`).
- **Found:** Stamphog calls this resolver before the head-change retraction path (`products/stamphog/backend/tasks/tasks.py:201-207`). An exception reaches the outer retry handler (`products/stamphog/backend/tasks/tasks.py:870-879`).
- **Found:** `process_pull_request_event` stops after three retries (`products/stamphog/backend/tasks/tasks.py:809-810`). Exhaustion prevents the skip path from retracting the approval (`products/stamphog/backend/tasks/tasks.py:881-903`).
- **Found:** Returning no acting user enters the safe opt-out path. The existing test confirms that this path retracts the prior approval (`products/stamphog/backend/tests/test_tasks.py:795-827`).
- **Impact:** A database outage across all attempts can leave an approval attached after a head change. That approval can cover commits Stamphog never reviewed.
- **Checked:** The durable task should retract before it retries the resolver failure. Treating the failure only as a permanent opt-out would safely retract but could lose a legitimate re-review.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:224-234

**Broker failures permanently lose initial reviews**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The callback catches every Celery publish error and only writes a log. No durable state records the missed dispatch. The opened webhook skips these bot-authored draft PRs, so a broker outage can leave the PR unreviewed forever.
- **Suggestion:** Persist a pending dispatch with the trigger transaction. Let a scheduled worker retry publication and mark it sent only after Celery accepts the message.
- **Validator:** - **Checked:** The transaction callback calls `_start_stamphog_review()` after the TaskRun save (`products/review_hog/backend/receivers.py:126-138`). Its broad exception handler prevents the failure from reaching any retrying caller (`products/review_hog/backend/receivers.py:224-234`).
- **Found:** `queue_inbox_pr_review()` only calls Celery's `.delay()` (`products/stamphog/backend/facade/api.py:128-155`). No row records a failed publication.
- **Found:** Stamphog creates the durable `ReviewRun` only after the Celery task starts (`products/stamphog/backend/tasks/tasks.py:1176-1234`). The task's retry policy cannot help when publication itself fails.
- **Found:** The webhook carve-out excludes the initial `opened` action (`products/stamphog/backend/tasks/tasks.py:144-168`). The ordinary path then rejects the bot-authored draft (`products/stamphog/backend/tasks/tasks.py:865-912`).
- **Checked:** A later output save or head change can incidentally retry the flow. Neither event is guaranteed after the initial publication failure.
- **Impact:** A broker outage can leave an opted-in PR without a review or a durable retry marker. The failure remains permanent when no later triggering event occurs.

### [✅ VALID] should_fix · bug — products/stamphog/backend/tasks/tasks.py:1107-1109,1212-1214,1233-1237

**Temporal outages can strand queued runs**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** A Temporal start failure raises through `on_commit` and triggers a Celery retry after the `ReviewRun` commits. The task gives up after three retries with a five-second delay. It leaves the row in `QUEUED`, and no periodic code restarts or fails stale rows. Without another TaskRun save, the review stays queued forever.
- **Suggestion:** Add durable recovery for stale `QUEUED` runs. A periodic task can restart old rows and mark them `FAILED` after a bounded age. Also use exponential backoff long enough for a normal Temporal outage.
- **Validator:** - **Checked:** Traced transaction commit behavior, workflow start errors, Celery retries, receiver refires, and Stamphog periodic tasks.
- **Found:** The task commits a `QUEUED` row before its `on_commit` workflow start at `products/stamphog/backend/tasks/tasks.py:1185-1234`.
- **Found:** A workflow start error reaches the task retry handler at `products/stamphog/backend/tasks/tasks.py:1235-1237`.
- **Found:** Each retry finds the same `QUEUED` row and retries the start at `products/stamphog/backend/tasks/tasks.py:1202-1214`.
- **Found:** The task allows three retries with a five-second delay at `products/stamphog/backend/tasks/tasks.py:1109`. No final failure path updates the row.
- **Found:** Stamphog's periodic schedule contains only the digest schedule at `products/stamphog/backend/tasks/schedules.py:1-13`. No job recovers stale review runs.
- **Found:** Recovery also occurs on a later TaskRun output save, but other saves are ignored at `products/review_hog/backend/tests/test_inbox_trigger.py:178-191`.
- **Impact:** A Temporal outage longer than the retry window leaves the initial review permanently `QUEUED`. The user receives no verdict unless another output save happens.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:126-138

**Production self-driving tasks never reach the new dispatch**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** This dispatch follows the `task.internal` return. Signals auto-start creates self-driving implementation tasks with `internal=True`. The dispatch therefore never runs for the main production case. The Stamphog webhook lookup repeats this rejection, so later deliveries cannot recover.
- **Suggestion:** Identify implementation tasks through the canonical `SignalReportTask.relationship == "implementation"` link. Allow linked internal tasks while rejecting other pipeline tasks. Test with the production `internal=True` task shape.
- **Validator:** - **Checked:** Production auto-start explicitly creates implementation tasks with `internal=True` (`products/signals/backend/auto_start.py:244-265`). Its test asserts this value (`products/signals/backend/test/test_auto_start.py:214-264`).
- **Found:** The receiver returns for every internal task before either review dispatch (`products/review_hog/backend/receivers.py:97-105`). The production implementation task therefore never reaches the new Stamphog branch.
- **Found:** The later webhook path cannot recover. `find_signal_implementation_run()` also rejects every internal task (`products/tasks/backend/facade/api.py:484-509`).
- **Found:** Production records implementation identity through a `SignalReportTask` row with `relationship="implementation"` (`products/signals/backend/auto_start.py:269-276`, `products/signals/backend/task_run_artefacts.py:100-135`). Pipeline tasks use other relationships.
- **Checked:** Receiver tests default implementation tasks to `internal=False` (`products/review_hog/backend/tests/test_inbox_trigger.py:61-80`). They therefore miss the production shape.
- **Impact:** Automatically started self-driving PRs receive neither the initial Stamphog review nor webhook re-reviews. This disables the feature's main production path.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:144-154

**Parent team IDs block child-environment re-reviews**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** Stamphog passes the canonical parent team ID to this resolver. Signals can store reports and runs under a child environment. The resolver then searches for reviewer artefacts under the wrong team. The tasks facade also rejects the raw child team ID. A push dismisses the old approval but never starts a new review.
- **Suggestion:** Match TaskRuns by canonical team equivalence. Then pass `run.team_id` to this resolver for the Signals artefact lookup. Add a child-environment test for the initial review and a synchronize event.
- **Validator:** - **Checked:** `SignalReport` and `TaskRun` store the supplied team directly (`products/signals/backend/models.py:184-202`, `products/tasks/backend/models.py:1076-1080`). Signal reports remain scoped to the URL environment (`products/signals/backend/views.py:732-749`).
- **Found:** Stamphog models convert child team IDs to the canonical parent on save (`posthog/models/scoping/product_mixin.py:86-96`). The repository configuration therefore carries the parent ID.
- **Found:** The webhook passes that parent ID to `find_signal_implementation_run()` and requires exact equality (`products/stamphog/backend/tasks/tasks.py:179-205`). The facade rejects a matching child run because its raw ID differs (`products/tasks/backend/facade/api.py:504-509`).
- **Found:** If the run check accepts canonical equivalence, the resolver still receives the parent ID. Its artefact query requires exact `team_id` equality and misses child data (`products/review_hog/backend/receivers.py:180-187`).
- **Found:** The initial receiver uses the raw TaskRun team ID (`products/review_hog/backend/receivers.py:111-138`). A child-environment initial review can therefore succeed while its later webhook re-review fails.
- **Impact:** A head change treats the PR as unidentified. Stamphog retracts the prior approval but does not review the new head (`products/stamphog/backend/tasks/tasks.py:870-912`).

### [✅ VALID] must_fix · bug — products/stamphog/backend/tasks/tasks.py:1176-1180,1211-1214,1223-1229

**The queued task does not recheck the reviewer toggle**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The receiver checks the toggle before it queues this task. This task trusts that old result. A delayed or retried task can start a review after the reviewer disables the toggle or loses the assignment. The workflow can then post a GitHub approval after the opt-out.
- **Suggestion:** Load the validated TaskRun and call the registered resolver before dedupe and run creation. Stop when it returns None. Store the current returned user ID in the provenance. Apply the same check before restarting an existing QUEUED run.
- **Validator:** - **Checked:** Traced the receiver gate, queued payload, task retries, dedupe recovery, registered resolver, and workflow start.
- **Found:** The receiver resolves the assignment and toggle once before dispatch at `products/review_hog/backend/receivers.py:111-139`.
- **Found:** `process_inbox_pr_review` does not call the resolver or load current settings. It copies the supplied user ID into provenance at `products/stamphog/backend/tasks/tasks.py:1176-1181`.
- **Found:** The task restarts an existing `QUEUED` run without another gate check at `products/stamphog/backend/tasks/tasks.py:1211-1214`.
- **Found:** The webhook re-review path does check the current resolver at `products/stamphog/backend/tasks/tasks.py:201-207`.
- **Found:** ReviewHog also rechecks its inbox toggle at workflow resolution time at `products/review_hog/backend/temporal/workflow.py:424-436`.
- **Impact:** A delayed task can start after the selected reviewer disables the toggle or loses the assignment. The resulting workflow can still post a real GitHub approval.

### [✅ VALID] should_fix · bug — products/tasks/backend/facade/api.py:504-509

**Failed and canceled task runs remain eligible for re-review**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** find_task_run can return a FAILED or CANCELLED run from its PR URL lookup. This facade does not reject that state. A later push can therefore receive the self-driving carve-out and an approval. The initial receiver treats these runs as abandoned and skips them.
- **Suggestion:** Reject TaskRun.Status.FAILED and TaskRun.Status.CANCELLED before returning the DTO. Apply this filter inside the team-scoped candidate query. Keep COMPLETED eligible because the receiver supports that state.
- **Validator:** - **Checked:** Traced TaskRun status handling in the initial receiver, candidate lookup, facade filters, and webhook carve-out.
- **Found:** `find_task_run` groups `COMPLETED`, `FAILED`, and `CANCELLED` as terminal candidates at `products/tasks/backend/webhooks.py:26-56`. It can return any of them.
- **Found:** The branch lookup has no status filter at `products/tasks/backend/webhooks.py:61-78`.
- **Found:** `find_signal_implementation_run` checks the team, signal report, and `internal` flag only at `products/tasks/backend/facade/api.py:504-509`.
- **Found:** The initial receiver explicitly rejects `FAILED` and `CANCELLED` runs at `products/review_hog/backend/receivers.py:90-91`. Its tests define those runs as abandoned at `products/review_hog/backend/tests/test_inbox_trigger.py:193-203`.
- **Found:** The webhook path accepts the returned DTO without a status check at `products/stamphog/backend/tasks/tasks.py:191-215`.
- **Impact:** A failed or canceled implementation can regain automatic review after a later push. Stamphog can then approve work that the initial trigger treats as abandoned.
