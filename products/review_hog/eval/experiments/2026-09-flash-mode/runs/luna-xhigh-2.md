# Reviewer-quality run — `luna-xhigh-2`

- **Dumped:** 2026-09-17T20:29:49+00:00
- **Report id:** `01a0b0ee-5688-78c9-a9f2-36604abaa4a4` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 2185s (36.4 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 13           | 27         | 22          | 19               |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 6s       |
| review wave (perspectives)  | 15m 25s  |
| blind-spot sweep            | 8m 13s   |
| dedup (incl. combine/clean) | 2m 54s   |
| validation                  | 9m 34s   |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 23m 38s — the reviewer-model speed comparison number.
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
| 1    | 2     | review-hog-perspective-contracts-security      | 4          |
| 1    | 3     | review-hog-perspective-contracts-security      | 2          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 3          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 4          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 2          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 3          |
| 3    | 3     | ?                                              | 0          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | review-hog-blind-spots-general                 | 2          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | review-hog-blind-spots-general                 | 2          |

## Findings (post-dedup) with validator verdict

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:113-121

**Reject malformed PR URLs before selecting a PR**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The parser uses search() and accepts a digit prefix. For example, https://github.com/acme/widgets/pull/42abc becomes PR 42. The worker can then review a different pull request from the value that triggered the task.
- **Suggestion:** Use a strict URL match with a path boundary after the number. Also compare the fetched PR number and URL with the parsed values before creating the ReviewRun.
- **Validator:** - **Checked:** Read `_parse_pr_url`, `process_inbox_pr_review`, `_upsert_pull_request`, and `StamphogGitHubClient.get_pr`.
- **Found:** `_PR_URL_RE` uses `search()` and has no boundary after `(\d+)` at products/stamphog/backend/tasks/tasks.py:113-121. The task passes the parsed number directly to GitHub at products/stamphog/backend/tasks/tasks.py:1155-1159. It creates the `ReviewRun` from the fetched payload without comparing its number or URL at products/stamphog/backend/tasks/tasks.py:1223-1230.
- **Found:** `TaskRunSetOutputRequestSerializer` accepts arbitrary JSON at products/tasks/backend/presentation/serializers.py:671-674, and the receiver forwards `output.pr_url` to this task at products/review_hog/backend/receivers.py:126-137. Existing input validation does not prevent the malformed value.
- **Impact:** A value such as `/pull/42abc` selects PR 42. The worker can then store and review that fetched PR under inbox provenance. This can produce an approval for code different from the task output. The issue is a real correctness and security boundary failure, so the strict parser and fetched-identity check should be kept.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1176-1181

**Recheck the inbox toggle inside the Celery task**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** ReviewHog checks the toggle before it calls delay(). Celery can run this task after the user turns the toggle off. The task does not call the registered resolver again before creating a review run, so it can still post an approval after opt-out.
- **Suggestion:** Resolve the linked implementation run and call get_inbox_acting_reviewer_resolver immediately before fetch and run creation. Require the returned user ID to match acting_user_id, and return without creating a run when the resolver returns None.
- **Validator:** - **Checked:** Traced `handle_task_run_saved` through `transaction.on_commit`, `_start_stamphog_review`, `queue_inbox_pr_review`, and `process_inbox_pr_review`. I also checked the resolver and the GitHub approval activity.
- **Found:** The receiver reads `stamphog_review_inbox_prs` at products/review_hog/backend/receivers.py:114-126 and queues the Celery task at products/review_hog/backend/receivers.py:130-138. The resolver checks the current setting at products/review_hog/backend/receivers.py:144-156, but the initial task never calls it. The task stamps the original `acting_user_id` at products/stamphog/backend/tasks/tasks.py:1176-1181 and creates the `ReviewRun` at products/stamphog/backend/tasks/tasks.py:1223-1230.
- **Found:** The resolver is used for later webhook re-reviews at products/stamphog/backend/tasks/tasks.py:201-207. The initial run can reach `post_approve_review` at products/stamphog/backend/temporal/activities.py:744-746.
- **Impact:** A toggle change after task enqueue does not stop the pending initial review. The task can create a run and post a GitHub approval after the user opts out. This is a real authorization race and meets the must-fix bar.

### [❌ dismissed] consider — products/stamphog/backend/tasks/tasks.py:201-207

**Distinguish opt-out from missing reviewer assignment**

_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The resolver returns None both when the toggle is off and when no reviewer resolves. This code maps both cases to opted_out=True. The skip path then tells users that no reviewer has the toggle enabled even when no reviewer was assigned.
- **Suggestion:** Return a result that distinguishes toggle_off from no_reviewer, and use the opt-out dismissal message only for toggle_off.
- **Validator:** - **Checked:** Read the resolver contract at products/review_hog/backend/receivers.py:144-173 and the skip-message branch at products/stamphog/backend/tasks/tasks.py:894-908.
- **Found:** The resolver returns `None` when no reviewers resolve and when the canonical reviewer has the toggle off at products/review_hog/backend/receivers.py:151-156. The opt-out message says that no reviewer currently has the setting enabled at products/stamphog/backend/tasks/tasks.py:70-73. That statement remains true when no reviewer is assigned to the PR.
- **Found:** Both branches still dismiss stale approvals and prevent a new run at products/stamphog/backend/tasks/tasks.py:881-898. The only additional difference is the log reason at products/stamphog/backend/tasks/tasks.py:904-908.
- **Impact:** The current behavior does not cause an incorrect review, missed dismissal, or state change. A more detailed distinction could improve wording and diagnostics, but this is a low-value copy refinement that does not meet the validation bar.

### [✅ VALID] must_fix · security — tools/pr-approval-agent/review_pr.py:225-225,590-590

**Verify Inbox PR identity before relaxing hard gates**

_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** When self_driving is true, these conditions skip the only bot-author and draft checks. They do not verify the expected PostHog Code bot, a same-repository head, or the task repository. A wrongly linked or forked PR can therefore reach the approval path.
- **Suggestion:** Validate the exact repository, head.repo.full_name, and expected bot identity before writing inbox_review or self_driving_review. Add a shared defense-in-depth check that refuses self-driving runs when author_is_bot is false.
- **Validator:** - **Checked:** Traced the initial Inbox path from `TaskRun.output["pr_url"]` through `process_inbox_pr_review` and the hosted reviewer context.
- **Found:** `products/review_hog/backend/receivers.py:106-137` forwards the stored PR URL without matching it to the task repository. `products/stamphog/backend/tasks/tasks.py:1155-1181` checks only that the fetched PR is open and has a head SHA. It does not check the author, head repository, or task linkage before creating `inbox_review` at `products/stamphog/backend/tasks/tasks.py:1223-1229`.
- **Found:** `products/stamphog/backend/temporal/activities.py:448-451` converts that unverified provenance into `self_driving_review`. `tools/pr-approval-agent/review_pr.py:225` and `tools/pr-approval-agent/review_pr.py:590` then bypass the bot-author and draft gates.
- **Found:** Task callers can write `output.pr_url` through `products/tasks/backend/facade/api.py:2139-2154`. The caller-output guard protects `pr_merged`, but it does not validate the PR repository.
- **Found:** The later webhook path has the required checks at `products/stamphog/backend/tasks/tasks.py:169-199`, but the initial Inbox path does not use that path or the task-linkage facade.
- **Impact:** A wrongly linked URL can create a self-driving review for an unrelated bot or fork PR that the team's GitHub installation can access. The reviewer can then approve that PR with the relaxed gates. This is a security and approval-integrity failure, so the issue meets the must-fix bar.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:224-234

**Do not drop reviews when the broker is unavailable**

_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The callback catches enqueue failures and only logs them. If the broker is temporarily unavailable, no process_inbox_pr_review task exists. The draft PR's opened webhook is skipped, so the initial review can be lost permanently. The task's retries cannot help because it never started.
- **Suggestion:** Create a durable dispatch record in the committed transaction and let a retrying worker enqueue it. Make the record idempotent by TaskRun and PR URL, while keeping the save callback non-blocking.
- **Validator:** - **Checked:** Traced the TaskRun receiver, the Stamphog facade, all `process_inbox_pr_review` call sites, and the draft PR webhook path.
- **Found:** `products/review_hog/backend/receivers.py:224-234` catches enqueue errors and only logs them. `products/stamphog/backend/facade/api.py:149-155` publishes directly with `.delay`. No durable record exists before publication.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1109-1112` defines retries for `process_inbox_pr_review`, but those retries run only after Celery accepts the task. They cannot run when `.delay` fails.
- **Found:** `products/stamphog/backend/tasks/tasks.py:167-168` excludes `opened` events from the inbox carve-out. The draft path then skips the webhook review at `products/stamphog/backend/tasks/tasks.py:865-881`. The initial review depends on `process_inbox_pr_review`, as documented at `products/stamphog/backend/tasks/tasks.py:160-162`.
- **Impact:** A broker failure during the single output save can leave a committed PR URL with no task and no retry marker. Later TaskRun saves are not guaranteed. The initial draft review can therefore be lost permanently. This is a concrete reliability defect that affects the feature's promised initial review flow.

### [✅ VALID] should_fix · bug — products/stamphog/backend/facade/api.py:120-124

**Pin the reviewability check to a consistent database**

_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** In production, product database reads use stamphog_db_reader while sync writes use stamphog_db_writer. Immediately after a successful sync, this query can return false and make the UI disable the toggle even though the repository is ready.
- **Suggestion:** Run this gating query on router.db_for_write(StamphogRepoConfig), or add a short read-after-write cache. The task path already pins similar gating reads to the writer.
- **Validator:** - **Checked:** Traced `has_reviewable_repo_config`, the product database router, the Stamphog sync write path, and the settings UI that consumes `stamphog_connected`.
- **Found:** `StamphogRepoConfig` uses the `stamphog` product route at products/db_routing.yaml:2-3. In production, `ProductDBRouter.db_for_read` selects `stamphog_db_reader` and `db_for_write` selects `stamphog_db_writer` at posthog/product_db_router.py:27-41. The query at products/stamphog/backend/facade/api.py:120-124 does not pin a database.
- **Found:** The sync flow writes repository rows through the writer at products/stamphog/backend/presentation/views.py:298-307. The database settings explicitly allow a separate reader and warn that immediate reads may be inconsistent at posthog/settings/data_stores.py:217-220 and posthog/settings/data_stores.py:264-267.
- **Found:** The settings serializer calls this query on every response at products/review_hog/backend/api/settings.py:72-80. The frontend disables an off toggle when `stamphog_connected` is false at products/review_hog/frontend/CodeReviewScene.tsx:1059-1067.
- **Impact:** A settings request during replica lag can report false after a successful sync. The UI then disables the opt-in toggle until the replica catches up or the user refreshes. This is a real reliability and onboarding defect, so the suggested writer pin is worth keeping.

### [✅ VALID] should_fix · bug — products/stamphog/backend/tasks/tasks.py:1109-1112

**Make the initial review hand-off durable**

_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The initial review depends on a broker publish from queue_inbox_pr_review. If publishing fails, or the process exits after the TaskRun transaction commits but before the callback publishes, no pending intent remains. The task's three retries only apply after Celery accepts the message. A draft opened event is skipped by the webhook path, so this review can be lost permanently.
- **Suggestion:** Persist an outbox or pending-review marker before dispatch and add a periodic reconciler. Keep the task idempotent and use producer retries for short broker failures, but rely on the persisted intent for process and broker recovery.
- **Validator:** - **Checked:** Traced the TaskRun save transaction, the `transaction.on_commit` callback, the broker dispatch, Celery retry behavior, and the webhook paths that can trigger a later review.
- **Found:** The TaskRun output is committed inside `transaction.atomic()` at products/tasks/backend/facade/api.py:2028-2076. The receiver registers the Stamphog dispatch only after that commit at products/review_hog/backend/receivers.py:126-139. The facade only calls `process_inbox_pr_review.delay()` at products/stamphog/backend/facade/api.py:128-155.
- **Found:** `_start_stamphog_review` catches broker errors and only logs them at products/review_hog/backend/receivers.py:224-234. The `max_retries=3` setting applies to `process_inbox_pr_review` after Celery accepts the message at products/stamphog/backend/tasks/tasks.py:1109-1112. No durable dispatch record or reconciler exists in this path.
- **Found:** The webhook carve-out is deliberately limited to later synchronize, reopen, and base-retarget events at products/stamphog/backend/tasks/tasks.py:160-168. A bot-authored draft is skipped before run creation when the carve-out returns empty at products/stamphog/backend/tasks/tasks.py:865-881.
- **Impact:** The TaskRun output remains persisted, but nothing consumes it after a lost broker publish or process exit before the callback runs. A draft PR with no later qualifying webhook can remain without its initial review. This is a real reliability gap, so the durable hand-off should be kept.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:167-172

**Keep self-driving re-reviews limited to draft PRs**

_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The carve-out never checks `pr.get("draft")`. After an Inbox PR becomes ready, a later synchronize, reopen, or base-retarget event still enables `self_driving_review`. The engine can then approve a bot-authored ready PR.
- **Suggestion:** Require `pr.get("draft")` before returning provenance. If it is false, return an empty `_InboxCarveOut` and let the normal bot-author path skip the event.
- **Validator:** - **Checked:** Traced `_review_skip_reason`, `_inbox_rereview_carve_out`, the webhook run creation path, and the engine gates that consume `self_driving_review`.
- **Found:** `_review_skip_reason` checks `draft` only at products/stamphog/backend/tasks/tasks.py:226-230. For a ready bot PR, `skip_reason` is `bot_author`. The carve-out then proceeds for synchronize, reopen, or base retarget because products/stamphog/backend/tasks/tasks.py:167-172 checks the action and bot author but not `pr.get("draft")`.
- **Found:** A successful carve-out sets `inbox_review` and bypasses the normal mode and author gates at products/stamphog/backend/tasks/tasks.py:941-969. The run stores that provenance at products/stamphog/backend/tasks/tasks.py:1056-1064, and the temporal activity converts it into `self_driving_review` at products/stamphog/backend/temporal/activities.py:448-451.
- **Found:** The engine skips the bot-author refusal when `self_driving` is true at tools/pr-approval-agent/review_local.py:314-325. Its draft prerequisite also passes for self-driving runs at tools/pr-approval-agent/review_pr.py:584-592. The repository contract limits this exception to the draft-time Inbox review at products/stamphog/AGENTS.md:92-99.
- **Impact:** A later qualifying webhook can create a self-driving run for a ready bot PR and auto-approve it. This widens the deliberate bot-author exception beyond its draft-only scope and can satisfy branch protection with an unintended automated approval. The issue meets the must-fix bar.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1183-1186

**Serialize repo disabling with inbox run creation**

_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The task reads an enabled config before a GitHub call, then creates the review run later without locking or re-reading the config. If an administrator disables the repo during that call, the disable handler can finish before this run exists. The task then starts a run from the stale enabled object, and the workflow can post an approval after disabling.
- **Suggestion:** Inside this writer transaction, lock the config with `select_for_update()` and re-check `enabled`, `installation_id`, and `connected_by_user_id` before creating the run. A disable must either wait and supersede the new run or make this task exit.
- **Validator:** - **Checked:** Traced the initial task's config read, GitHub fetch, writer transaction, repository disable path, and workflow status gates.
- **Found:** The task reads an enabled, synced config at products/stamphog/backend/tasks/tasks.py:1140-1147, performs the GitHub call at products/stamphog/backend/tasks/tasks.py:1155-1165, and only opens a transaction for PR and run writes at products/stamphog/backend/tasks/tasks.py:1182-1186. It does not lock or re-read `StamphogRepoConfig` before creating the run at products/stamphog/backend/tasks/tasks.py:1223-1230.
- **Found:** Disabling a repository saves the config and then supersedes only runs that already exist at products/stamphog/backend/presentation/views.py:236-250. The code explicitly states that workflows do not re-check `enabled` and rely on `SUPERSEDED` status instead at products/stamphog/backend/presentation/views.py:242-245.
- **Found:** The workflow reloads the run and checks its status, but it does not check the repository configuration at products/stamphog/backend/temporal/activities.py:97-106 and products/stamphog/backend/temporal/activities.py:377-429.
- **Impact:** A disable can commit and supersede zero runs while this task is between its config read and run creation. The task can then create a queued run from the stale enabled state, and the workflow can continue because the new run was not marked `SUPERSEDED`. This can post an approval after repository disable. The issue is a real safety race and meets the must-fix bar.

### [✅ VALID] must_fix · bug — products/stamphog/AGENTS.md:84-86

**must_fix: The documented task filter skips real self-driving runs**

_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The documented non-internal requirement excludes the real self-driving implementation task. The auto-start path creates this task with internal=True. The receiver and the tasks facade both reject internal tasks. The initial review and later webhook re-reviews therefore never start for production auto-start runs.
- **Suggestion:** Align the producer and both trigger paths. Use a durable implementation-task marker instead of the internal visibility flag, or change the producer consistently. Add an end-to-end test that covers the real auto-start path and a later synchronize event.
- **Validator:** - **Checked:** `products/signals/backend/auto_start.py:244-265`, `products/review_hog/backend/receivers.py:97-105`, and `products/tasks/backend/facade/api.py:484-509`.
- **Found:** The production auto-start path creates the implementation task with `signal_report_id=report_id` and `internal=True` at `products/signals/backend/auto_start.py:254-261`. The receiver returns when `task.internal` is true at `products/review_hog/backend/receivers.py:104-105`. The tasks facade also returns `None` for internal tasks at `products/tasks/backend/facade/api.py:507-509`.
- **Found:** The webhook carve-out requires that facade match before it can create inbox provenance at `products/stamphog/backend/tasks/tasks.py:191-214`.
- **Impact:** Production auto-start PRs skip both the initial receiver review and later webhook re-reviews. The existing positive receiver tests default tasks to `internal=False` at `products/review_hog/backend/tests/test_inbox_trigger.py:61-80`, so they do not cover the real producer path.

### [✅ VALID] must_fix · security — products/stamphog/AGENTS.md:89-99

**must_fix: The initial entry does not enforce the provenance boundary**

_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The claim that only positively verified inbox provenance enables the engine flag is not true for the receiver leg. The receiver forwards a caller-controlled output.pr_url, and process_inbox_pr_review checks only that the fetched PR is open before stamping inbox_review. It does not check the expected PostHog Code bot, a repository-native head, or draft state. A writable TaskRun output can point this side door at a human or fork PR, which then bypasses the bot, draft, author-permission, and review-mode gates.
- **Suggestion:** In process_inbox_pr_review, resolve task_run_id through the tasks facade and bind the PR to that run's team, report, repository, and implementation identity. Before creating the run, require the expected bot author, a repository-native head, and the intended draft state. Stamp inbox_review only after these checks, and test human and fork PRs.
- **Validator:** - **Checked:** `products/review_hog/backend/receivers.py:92-137`, `products/stamphog/backend/facade/api.py:128-155`, and `products/stamphog/backend/tasks/tasks.py:1130-1230`.
- **Found:** The receiver copies `output["pr_url"]` into the queue request at `products/review_hog/backend/receivers.py:130-137`. The facade forwards that value without validation at `products/stamphog/backend/facade/api.py:149-155`. The Celery task checks only that the fetched PR is open and has a head SHA at `products/stamphog/backend/tasks/tasks.py:1158-1174`, then stamps `inbox_review` at `products/stamphog/backend/tasks/tasks.py:1176-1180` and `products/stamphog/backend/tasks/tasks.py:1223-1229`.
- **Found:** The initial path does not call `_is_bot_authored`, does not compare `head.repo.full_name` with the configured repository, and does not require a draft PR. Those checks exist only in the webhook carve-out at `products/stamphog/backend/tasks/tasks.py:169-178`.
- **Found:** A caller can write `TaskRun.output` through the `set_output` action at `products/tasks/backend/presentation/views/api.py:1092-1118`. The facade accepts the caller's `pr_url` at `products/tasks/backend/facade/api.py:2139-2154`. Signal-report tasks are controllable by team members through `task_control_q` at `products/tasks/backend/visibility.py:30-46`.
- **Found:** Hosted review behavior enables the self-driving carve-out from `ReviewRun.output["inbox_review"]` at `products/stamphog/backend/temporal/activities.py:448-451`. That flag bypasses the bot-author refusal and draft prerequisite at `tools/pr-approval-agent/review_local.py:314-326` and `tools/pr-approval-agent/review_pr.py:584-591`.
- **Impact:** A writable task output can send an open human or fork PR through the trusted inbox path. The path can create a self-driving review and potentially post an approval without the normal identity, fork, author-permission, or review-mode gates. This is a real provenance and security boundary failure.

### [✅ VALID] must_fix · security — products/review_hog/backend/receivers.py:126-138

**Validate the PR before enabling the Inbox approval path**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The callback treats any `TaskRun.output.pr_url` from a non-internal Signals task as an Inbox PR. It does not prove that the URL belongs to the task repository, task run, or bot-created draft. The worker then stamps `inbox_review`, which enables the bot and draft exception and can publish an approval for an unrelated human or fork PR.
- **Suggestion:** Validate this in `process_inbox_pr_review` before creating a run. Load `task_run_id` within `team_id`, require the task, report, repository, and URL to match, and require the fetched PR to be an open draft from the expected bot with a repository-native head. Stamp `inbox_review` only after these checks.
- **Validator:** - **Checked:** Traced the receiver gates, all `TaskRun.output` writers, the Stamphog queue task, and the engine gates controlled by `inbox_review`.
- **Found:** `products/review_hog/backend/receivers.py:97-105` checks only `signal_report_id` and `internal`. The Stamphog path receives `pr_url` at `products/review_hog/backend/receivers.py:126-138`. The task repository is not used to validate that URL.
- **Found:** `products/tasks/backend/facade/api.py:2123-2136` validates output only against an optional task JSON schema. `products/tasks/backend/facade/api.py:2139-2154` persists caller-provided output without binding `pr_url` to the task repository or a GitHub event.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1130-1147` resolves the repository from the URL. `products/stamphog/backend/tasks/tasks.py:1151-1169` checks only that the configured repository exists and that the fetched PR is open. It does not load `task_run_id`, compare the task or report, or check the PR's draft status, author, or head repository.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1176-1180` stamps `inbox_review` after those checks. `products/stamphog/backend/temporal/activities.py:448-451` converts that field into `self_driving_review`. The engine then bypasses the bot-author refusal at `tools/pr-approval-agent/review_local.py:314-330` and the draft prerequisite at `tools/pr-approval-agent/review_pr.py:584-591`.
- **Impact:** An open human or fork PR in a configured repository can receive the trusted Inbox provenance when a signal task contains its URL. The review can then run through the self-driving approval path and may publish an approval for code that the task did not produce. This is a concrete security boundary failure, so the suggested validation should be kept.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:126-138

**Recheck the toggle before starting and publishing**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The callback reads `stamphog_review_inbox_prs` before queuing the Celery task. The initial worker does not recheck the current setting before creating or publishing a review. A user can turn the switch off while the task waits, but the task can still publish an approval.
- **Suggestion:** Re-resolve the acting reviewer and read `stamphog_review_inbox_prs` in the worker before creating `ReviewRun`. Check the setting again before publishing the verdict, or cancel the queued run when the setting is off. Keep stale-approval dismissal independent of this gate.
- **Validator:** - **Checked:** Traced the toggle read in the receiver, the initial Celery task, the later webhook resolver, and the Temporal verdict publisher.
- **Found:** `products/review_hog/backend/receivers.py:114-126` reads `stamphog_review_inbox_prs` before registering the callback. The callback passes the captured identity at `products/review_hog/backend/receivers.py:131-138`.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1130-1169` checks the repository and PR state but never reads `ReviewUserSettings`. It creates the Inbox review at `products/stamphog/backend/tasks/tasks.py:1223-1234` without another toggle check.
- **Found:** The resolver in `products/review_hog/backend/receivers.py:144-156` is used by the later webhook carve-out at `products/stamphog/backend/tasks/tasks.py:201-215`. It does not protect the initial queued task.
- **Found:** `products/stamphog/backend/temporal/activities.py:662-685` checks only supersession and head changes before publishing. The approval write occurs at `products/stamphog/backend/temporal/activities.py:723-752`, with no toggle check.
- **Impact:** If a user disables the toggle after the receiver queues the task, the worker can still create an Inbox review and publish an approval. The later webhook check does not cover this pending initial run. This breaks the opt-out behavior during a real queue or review delay.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1130-1159

**Bind the receiver review to a verified implementation run**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The task trusts pr_url, signal_report_id, task_run_id, and acting_user_id from the caller. It only checks for an enabled config matching the URL repository. It does not verify the task repository, the implementation run, the bot author, or the head repository. A task output can therefore point this self-driving carve-out at an unrelated open PR, including a human or fork PR.
- **Suggestion:** Reload the implementation run through the tasks facade and require its team, run ID, report ID, and repository to match the queued values. After get_pr, require the expected bot author and a repo-native head before creating the inbox-provenance run.
- **Validator:** - **Checked:** Traced the TaskRun receiver, the initial queue facade, the existing `find_signal_implementation_run` verifier, the GitHub fetch gates, and the engine behavior for inbox provenance.
- **Found:** The receiver forwards `pr_url`, `signal_report_id`, `task_run_id`, and `acting_user_id` from the TaskRun context at products/review_hog/backend/receivers.py:92-106 and products/review_hog/backend/receivers.py:126-138. The queue facade passes them directly to Celery at products/stamphog/backend/facade/api.py:128-155.
- **Found:** The existing verifier positively matches a signals implementation run, enforces team scope, and rejects unlinked or internal runs at products/tasks/backend/facade/api.py:484-516. The initial task never calls it. It only selects an enabled config for the repository parsed from `pr_url` at products/stamphog/backend/tasks/tasks.py:1130-1147.
- **Found:** After fetching GitHub data, the initial task checks only that the PR is open and has a head SHA at products/stamphog/backend/tasks/tasks.py:1155-1174. It does not check the fetched PR's author, draft state, head repository, task repository, or identity against the queued values before stamping inbox provenance at products/stamphog/backend/tasks/tasks.py:1176-1181 and creating the run at products/stamphog/backend/tasks/tasks.py:1223-1230.
- **Found:** Inbox provenance enables `self_driving_review` at products/stamphog/backend/temporal/activities.py:448-451. That flag bypasses the bot-author refusal in tools/pr-approval-agent/review_local.py:314-326 and tools/pr-approval-agent/review_pr.py:221-226.
- **Impact:** A TaskRun output can target another open PR in a repository configured for the same team, including a human-authored or fork-head PR. The initial task can then stamp self-driving provenance and run the automated approval path without verified linkage to the implementation run. This is a real authorization boundary failure and meets the must-fix bar.

### [✅ VALID] must_fix · security — products/tasks/backend/facade/api.py:484-509

**Use a server-owned marker for implementation runs**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The facade identifies an implementation run only by signal_report_id and internal=False. The Signals auto-start path creates the implementation task with internal=True and ai_stage=implementation, so the intended task is rejected and the feature cannot trigger. Removing the internal check would admit client-created signal-report tasks that satisfy the same condition.
- **Suggestion:** Require a server-owned implementation marker, such as the implementation relationship or run state ai_stage=implementation, together with the origin, report, repository, and team checks. Keep other internal tasks excluded.
- **Validator:** - **Checked:** Read `find_signal_implementation_run`, the Signals auto-start creator, the server-owned task/report relationship, and the callers that use this facade for inbox re-reviews.
- **Found:** The Signals auto-start path creates the implementation task with `origin_product=SIGNAL_REPORT`, `signal_report_id`, `ai_stage="implementation"`, and `internal=True` at products/signals/backend/auto_start.py:244-265. The facade rejects every task with `task.internal` at products/tasks/backend/facade/api.py:504-509.
- **Found:** The auto-start path records a dedicated implementation relationship under the report lock at products/signals/backend/auto_start.py:269-275. The generic `internal` field only means that a task is hidden from normal task lists at products/tasks/backend/models.py:207-210, so it is not a sufficient implementation identity.
- **Found:** The webhook carve-out depends on this facade result before it stamps inbox provenance at products/stamphog/backend/tasks/tasks.py:191-207. A `None` result leaves the bot PR on the normal skip path, so later self-driving re-reviews cannot run.
- **Impact:** The current predicate rejects the real Signals implementation task. Removing the `internal` check alone would admit other signal-report tasks without proving that they are the server-created implementation task. A server-owned implementation relationship or equivalent marker is required to restore the feature without widening the automation boundary. This meets the must-fix bar.

### [✅ VALID] must_fix · security — tools/pr-approval-agent/review_local.py:321-324

**Validate the PR before enabling the self-driving bypass**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** A true self_driving_review value is enough to bypass the bot-author refusal and the draft gate. The engine does not verify that the current PR is bot-authored or that its head comes from the configured repository. A human or fork PR can therefore receive the self-driving treatment if the server stamps the marker incorrectly.
- **Suggestion:** Fail closed unless the linked task, bot author, base repository, and head repository all match the current PR. Validate these facts before persisting inbox_review and check the bot and repository invariants again in the sandbox.
- **Validator:** - **Checked:** Traced `self_driving_review` from the hosted activity into `review_local.run`, then checked how `PRData.author_is_bot` and repository metadata are built.
- **Found:** `tools/pr-approval-agent/review_local.py:321-324` passes the flag directly to `Pipeline` and refuses the author only when the flag is false. A true flag skips the bot check. The prerequisite draft check also skips when `Pipeline.self_driving` is true.
- **Found:** `products/stamphog/backend/temporal/activities.py:448-451` sets the flag from `ReviewRun.output["inbox_review"]`. The initial path writes that marker at `products/stamphog/backend/tasks/tasks.py:1176-1181` and `products/stamphog/backend/tasks/tasks.py:1223-1229` after checking only that the PR is open and has a head SHA at `products/stamphog/backend/tasks/tasks.py:1166-1174`.
- **Found:** The initial path does not check `pr.user`, `pr.head.repo.full_name`, or the PR base repository. The stricter bot, head-repository, and task-linkage checks at `products/stamphog/backend/tasks/tasks.py:169-199` apply only to later webhook re-reviews.
- **Impact:** A bad or stale server marker can make the sandbox approve a human-authored or fork PR. The sandbox already has the current author data in `PRData.author_is_bot`, and the raw context contains the GitHub repository fields, so a fail-closed defense is feasible. This is an approval-integrity security gap and meets the must-fix bar.

### [❌ dismissed] should_fix — tools/pr-approval-agent/review_local.py:321

**Require a real boolean for the security-sensitive flag**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** bool(context.get("self_driving_review")) treats any non-empty value such as the string "false" as enabled. This makes malformed context fail open and can activate the bot and draft gate bypass.
- **Suggestion:** Accept the carve-out only when context.get("self_driving_review") is True. Reject or disable the run when the field has any other type, and add coverage for string and numeric values.
- **Validator:** - **Checked:** Traced every production call to `build_reviewer_invocation` and the construction of the sandbox context JSON.
- **Found:** The only production caller passes `self_driving_review=bool(output.get("inbox_review"))` at `products/stamphog/backend/temporal/activities.py:434-451`. `build_reviewer_invocation` stores that already-normalized value in the context at `products/stamphog/backend/logic/reviewer.py:101-131`.
- **Found:** The server writes `inbox_review` as a dictionary at `products/stamphog/backend/tasks/tasks.py:1176-1181` and `products/stamphog/backend/tasks/tasks.py:1223-1229`, or leaves it absent. These paths cannot produce the string `"false"` or a numeric value for `self_driving_review`.
- **Impact:** `bool(context.get("self_driving_review"))` would accept malformed values if a caller invoked `review_local.run` directly with such a context. The hosted production path always serializes a real boolean before the sandbox receives it, so the proposed trigger is not reachable through current call sites. This is defensive hardening, not a confirmed bug that meets the validation bar.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:126-138

**Allow actual Inbox implementation tasks**

_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The receiver returns earlier when `task.internal` is true. The production Signals auto-start path creates implementation tasks with `internal=True`. The new Stamphog review is therefore never queued. Later webhook reviews also reject these tasks.
- **Suggestion:** Align the Inbox implementation predicate across task creation, this receiver, and `find_signal_implementation_run`. Allow the real implementation task while excluding research and repository-selection tasks.
- **Validator:** - **Checked:** Traced the production Signals auto-start path, the receiver guard, the webhook linkage facade, and the task-purpose recording code.
- **Found:** `products/signals/backend/auto_start.py:244-265` creates the actual implementation task with `origin_product=SIGNAL_REPORT`, `signal_report_id`, `interaction_origin="signal_report"`, and `internal=True`. The comment at `products/signals/backend/auto_start.py:260-261` says this hides the task from the default task list.
- **Found:** `products/review_hog/backend/receivers.py:97-105` returns for every internal task. This excludes the production implementation run before either review queue can be registered.
- **Found:** `products/tasks/backend/facade/api.py:504-509` applies the same `task.internal` rejection in `find_signal_implementation_run`. Later webhook deliveries therefore cannot identify this implementation run either.
- **Found:** `products/signals/backend/task_run_artefacts.py:100-135` records the implementation purpose separately through `TASK_RUN_TYPE_IMPLEMENTATION` and the `SignalReportTask` gate. The current `internal` value cannot distinguish implementation work from research and repository-selection work.
- **Impact:** The production Inbox implementation task is hidden from review by both trigger paths. The new Stamphog Inbox flow does not run for the task type it targets. This is a direct logic bug that makes the feature ineffective in production.

### [❌ dismissed] must_fix — products/review_hog/backend/receivers.py:111-126

**Honor any opted-in assigned reviewer**

_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `_resolve_assigned_reviewer` returns one reviewer, and that user's `stamphog_review_inbox_prs` value gates the review. If that reviewer is off but another assigned reviewer is on, no Stamphog review starts. This does not match the stated any-assigned-reviewer behavior.
- **Suggestion:** Resolve the assigned users separately for this toggle. Queue when any assigned org user has the toggle enabled, and pass the selected enabled user as `acting_user_id` for initial and later reviews.
- **Validator:** - **Checked:** Traced `_resolve_assigned_reviewer`, the documented Inbox assignment decision, the regression tests, and the Stamphog webhook resolver.
- **Found:** `products/review_hog/backend/receivers.py:164-170` defines one canonical acting reviewer. It uses the task creator only when that user is assigned. Otherwise, it uses the first resolved reviewer and applies that user's toggles and review options.
- **Found:** `products/review_hog/DECISIONS.md:2668-2681` explicitly says that a non-acting reviewer's opt-in must not change the acting reviewer. It also says that an opted-out acting reviewer causes the run to skip.
- **Found:** `products/review_hog/backend/tests/test_inbox_trigger.py:205-238` verifies both behaviors. The tests select the first resolved reviewer and reject the review when that canonical reviewer is off, even when another assigned reviewer is on. `products/review_hog/backend/tests/test_inbox_trigger.py:240-252` verifies the separate assigned-requester override.
- **Found:** The later Stamphog path also calls the same resolver at `products/stamphog/backend/tasks/tasks.py:201-213`, so initial and later reviews use the same intentional acting-reviewer policy.
- **Impact:** The suggested change would replace an established canonical-reviewer rule with a different any-assigned-reviewer rule. It would let a non-acting reviewer’s toggle and review options control a run. The claimed defect is therefore not present under the codebase’s documented contract.

### [✅ VALID] should_fix · bug — products/tasks/backend/facade/api.py:504-506

**Scope the task lookup before selecting a run**

_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** find_task_run searches all teams and selects one run before this function checks run.team_id. The branch fallback is used when a PR URL is absent. A branch collision across teams can select another team's run and make the correct team miss the review.
- **Suggestion:** Pass team_id into find_task_run and filter both lookup paths before first(). Keep the repository comparison case-insensitive and apply deterministic ordering.
- **Validator:** - **Checked:** Reviewed `find_task_run` in `products/tasks/backend/webhooks.py:29-98`, its call in `products/tasks/backend/facade/api.py:484-518`, and the existing repository and branch matching tests.
- **Found:** Both lookup paths call `.first()` without filtering by `team_id`. The facade checks `run.team_id != team_id` only after that row is selected at `products/tasks/backend/facade/api.py:504-506`.
- **Found:** If another team has an earlier matching branch and repository, the lookup returns that row. The facade then returns `None` and does not search for a matching run in the requested team.
- **Impact:** A cross-team branch collision can prevent the correct self-driving implementation run from being found. Filtering by `team_id` before `.first()` fixes the correctness and tenant-scoping problem.

### [✅ VALID] should_fix · performance — products/stamphog/backend/tasks/tasks.py:1155-1159

**Coalesce repeated receiver jobs before fetching GitHub**

_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The receiver queues this task for every TaskRun output save that contains the PR URL. The task fetches the current PR before checking the current-head dedupe. Repeated saves therefore create repeated Celery jobs and GitHub requests even when a completed run already exists, which can consume worker capacity and GitHub rate limits.
- **Suggestion:** Coalesce pending jobs before get_pr with a short Redis lease keyed by task_run_id and pr_url, or persist a dispatch marker. Let the lease expire so a later missed webhook can still backstop a new head, and keep the database dedupe as the final guard.
- **Validator:** - **Checked:** Reviewed the `TaskRun` save receiver, the `queue_inbox_pr_review` facade, the output persistence path, and the receiver task's fetch and dedupe order.
- **Found:** `products/review_hog/backend/receivers.py:75-89` runs on every relevant output save and does not compare the PR URL with the previous value. With the toggle enabled, `products/review_hog/backend/receivers.py:126-139` queues the Celery task for each such save, and `products/stamphog/backend/facade/api.py:149-155` publishes each job.
- **Found:** `products/tasks/backend/facade/api.py:2139-2154` saves the output field, so repeated output writes can reach this receiver even when the PR URL is unchanged. `process_inbox_pr_review` fetches GitHub at `products/stamphog/backend/tasks/tasks.py:1155-1159`, while its current-head dedupe runs later at `products/stamphog/backend/tasks/tasks.py:1198-1210`.
- **Impact:** Repeated saves create redundant Celery messages and one GitHub request per accepted job before the database dedupe returns. The deterministic workflow identity does not prevent this pre-dedupe fetch, so repeated saves can consume worker capacity and GitHub rate-limit budget at real scale.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:111-126

**Pin toggle reads to the writer**

_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** ReviewUserSettings.load uses the normal read route. A read replica can return an old toggle after a user changes it. The new Stamphog path can then skip an opted-in review or queue one after opt-out. The latter can lead to an approval after the user disabled the feature.
- **Suggestion:** Pin the settings read to router.db_for_write(ReviewUserSettings). Also pin the latest reviewer-assignment artefact read to its writer before enqueueing or re-reviewing.
- **Validator:** - **Checked:** Traced the settings write path, receiver gates, reviewer-assignment lookup, and database router configuration.
- **Found:** `ReviewUserSettings.load` queries through the default manager at `products/review_hog/backend/models.py:311-314`. `_resolve_assigned_reviewer` reads the latest `SignalReportArtefact` at `products/review_hog/backend/receivers.py:180-187`. `ReplicaRouter` routes opted-in model reads to `replica` at `posthog/dbrouter.py:22-31`, and `posthog/settings/data_stores.py:121-127` enables that router when a read replica exists. The opt-in model list comes from `READ_REPLICA_OPT_IN` at `posthog/settings/data_stores.py:264-272`.
- **Found:** These reads control dispatch and re-review decisions at `products/review_hog/backend/receivers.py:111-126` and `products/review_hog/backend/receivers.py:151-155`. The router documents replica lag and read-after-write inconsistency at `posthog/dbrouter.py:17-19`. Stamphog also requires writer-pinned reads for decisions that gate side effects at `products/stamphog/AGENTS.md:59-64`.
- **Impact:** With the read replica enabled and either model opted in, a recent toggle or reviewer assignment can be invisible to the receiver. The code can then skip an enabled review or enqueue a review after an opt-out. Because the decision gates a GitHub review, this is a real reliability and correctness defect, not a defensive-only concern.
