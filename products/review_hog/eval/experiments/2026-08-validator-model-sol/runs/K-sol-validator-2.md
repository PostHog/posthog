# Reviewer-quality run — `K-sol-validator-2`

- **Dumped:** 2026-08-25T19:02:25+00:00
- **Report id:** `01a03a33-78b6-79ea-a35b-d97a111c082c` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1691s (28.2 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 12           | 14         | 10          | 8                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 19s      |
| review wave (perspectives)  | 3m 36s   |
| blind-spot sweep            | 3m 07s   |
| dedup (incl. combine/clean) | 1m 53s   |
| validation                  | 18m 56s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 6m 43s — the reviewer-model speed comparison number.
- Derived from artefact `created_at` (persisted on completion); only meaningful for fresh, non-resumed runs.

## Chunking

- **chunk 1** (8 files): products/review_hog/backend/models.py, products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py, products/review_hog/backend/api/settings.py, products/review_hog/backend/receivers.py, products/review_hog/frontend/CodeReviewScene.tsx, products/review_hog/frontend/generated/api.schemas.ts, products/review_hog/frontend/generated/api.zod.ts, services/mcp/src/api/generated.ts
- **chunk 2** (8 files): products/stamphog/backend/facade/api.py, products/stamphog/backend/facade/inbox_hooks.py, products/stamphog/backend/tasks/tasks.py, products/stamphog/backend/temporal/activities.py, products/stamphog/backend/logic/reviewer.py, products/tasks/backend/facade/api.py, products/tasks/backend/facade/contracts.py, tach.toml
- **chunk 3** (4 files): tools/pr-approval-agent/review_pr.py, tools/pr-approval-agent/review_local.py, tools/pr-approval-agent/reviewer.py, tools/pr-approval-agent/version.py
- **chunk 4** (2 files): products/stamphog/AGENTS.md, products/stamphog/README.md

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 1          |
| 1    | 2     | review-hog-perspective-contracts-security      | 1          |
| 1    | 3     | ?                                              | 0          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | review-hog-blind-spots-general                 | 1          |

## Findings (post-dedup) with validator verdict

### [✅ VALID] must_fix · bug — products/tasks/backend/facade/api.py:504-506

**Post-query team filtering can hide the correct task run**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `find_task_run` searches all teams and selects one row before this facade checks `team_id`. If another team has the same PR URL or repository and branch, that row can win the query. The facade then returns `None` even when the requested team has a matching run. This prevents valid self-driving PR re-reviews.
- **Suggestion:** Apply `team_id` inside the query before ordering and calling `.first()`. Add a team-scoped parameter to `find_task_run`, or implement the lookup in this facade with `TaskRun.objects.filter(team_id=team_id, ...)`. Cover duplicate PR URL and branch matches across two teams.
- **Validator:** - **Checked:** I traced the facade lookup into `find_task_run` and its StampHog caller.
- **Found:** `products/tasks/backend/webhooks.py:41-56` selects one PR URL match across all teams. `products/tasks/backend/webhooks.py:68-75` does the same for a repository and branch match.
- **Found:** `products/tasks/backend/facade/api.py:504-506` checks `team_id` only after `find_task_run` returns one row.
- **Impact:** A matching row from another team makes `products/stamphog/backend/tasks/tasks.py:191-200` reject a valid inbox re-review. This is a reachable correctness bug because teams can use the same repository and branch names.

### [✅ VALID] should_fix · bug — tools/pr-approval-agent/reviewer.py:697-699

**Trusted prompt can report the wrong draft state**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The provenance block always states that the PR is a draft. A later push can start another self-driving review after the PR becomes ready. The trusted prompt then gives the reviewer false state information.
- **Suggestion:** Build the draft guidance from `pr.draft`. Include these sentences only when the PR is currently a draft.
- **Validator:** - **Checked:** I traced `pr.draft`, the trusted prompt builder, and self-driving review triggers.
- **Found:** `_format_self_driving` receives only `cl` and always adds the draft claim at `tools/pr-approval-agent/reviewer.py:683-701`. `_build_review_prompt` has the current `pr` at `tools/pr-approval-agent/reviewer.py:506`.
- **Found:** A ready PR can receive another self-driving review after a later push. The rereview scope includes `synchronize` at `products/stamphog/backend/tasks/tasks.py:160-163`, and the run keeps `self_driving_review` at `products/stamphog/backend/temporal/activities.py:448-451`.
- **Impact:** The trusted prompt can contradict the current GitHub state. This false fact can affect the model's review judgment. The prompt should add draft guidance only when `pr.draft` is true.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:225-235

**Broker failures permanently lose the initial review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The code catches a broker publish failure after the TaskRun transaction commits. No retry or durable record remains. A temporary broker outage can permanently lose the initial review because bot draft PRs do not enter the normal webhook path.
- **Suggestion:** Use a transactional outbox or another durable dispatch record. Retry failed publishes outside the TaskRun save path, and mark the record complete only after the broker accepts the task.
- **Validator:** - **Checked:** I traced the transaction callback, Celery publish, receiver retry paths, and Stamphog webhook filters.
- **Found:** `products/review_hog/backend/receivers.py:133` registers the publish only as an `on_commit` callback. `_start_stamphog_review` catches the final publish error at `products/review_hog/backend/receivers.py:225-236`.
- **Found:** `products/stamphog/backend/facade/api.py:149` calls `.delay()` before any durable task record exists. Celery task retries start only after the broker accepts this message.
- **Found:** The webhook carve-out excludes the initial event at `products/stamphog/backend/tasks/tasks.py:161`. Later TaskRun saves also skip when `update_fields` omits `output` at `products/review_hog/backend/receivers.py:81-85`.
- **Impact:** A broker failure can leave an opted-in draft PR without its initial review. No stored state guarantees a later retry.

### [✅ VALID] should_fix · bug — products/stamphog/backend/tasks/tasks.py:1109-1112,1215-1235

**Exhausted retries can leave a review run queued forever**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The task commits a QUEUED run before it starts the Temporal workflow. A start failure retries the task, but the task stops after three retries. The run stays QUEUED after the final failure. No later save must occur to restart it.
- **Suggestion:** Add durable recovery for stale QUEUED runs. For example, schedule a reconciliation task or mark the run as failed after the final retry and emit an alert. Add a metric for queued runs that have no workflow.
- **Validator:** - **Checked:** I traced the inbox task, its retry limit, the transaction callback, and all recovery paths for queued runs.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1223-1234` commits the queued row before `_start_review_workflow` runs. The callback exception reaches the retry handler at `products/stamphog/backend/tasks/tasks.py:1235-1237`.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1109` limits the task to three retries. The code does not update the run after the last start failure.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1211-1221` restarts the run only if the receiver task runs again. I found no scheduled recovery for old queued runs.
- **Impact:** A persistent or repeated Temporal start failure leaves the initial inbox review queued with no workflow. The PR can then receive no review until another external event runs this path.

### [❌ dismissed] should_fix · documentation — products/stamphog/AGENTS.md:97-101

**Documented linkage check does not exist on the initial review path**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The text says both trigger paths verify task linkage before they stamp `ReviewRun.output["inbox_review"]`. The webhook path calls `find_signal_implementation_run`, but `process_inbox_pr_review` trusts the IDs supplied through `queue_inbox_pr_review`. It does not load the TaskRun or confirm that the PR belongs to that run. A new internal caller can therefore enable the bot and draft exceptions without the documented check.
- **Suggestion:** Verify `task_run_id`, `signal_report_id`, team, repository, and PR linkage inside `process_inbox_pr_review` before it stamps the provenance. If the receiver is the intended trust boundary, update this section to state that fact and do not describe the initial path as linkage-verified.
- **Validator:** - **Checked:** I traced all callers of `queue_inbox_pr_review` and `process_inbox_pr_review`.
- **Found:** The receiver reads the PR URL and run ID from the saved `TaskRun` at `products/review_hog/backend/receivers.py:92-104`. It rejects runs without a signal report and rejects internal tasks.
- **Found:** The receiver checks the assigned reviewer and toggle at `products/review_hog/backend/receivers.py:111-137`. It then supplies IDs from the same task and run.
- **Found:** The facade documents this caller contract at `products/stamphog/backend/facade/api.py:128-154`. No other production caller uses this entry point.
- **Impact:** The current initial path verifies linkage before it queues the task. A hypothetical future caller that breaks the documented internal contract does not meet the review bar.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1158-1181

**Revalidate inbox provenance before granting the review carve-out**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The queued task trusts `team_id`, `task_run_id`, `signal_report_id`, `acting_user_id`, and `pr_url`. It only checks that the repository has an enabled configuration and that the PR is open. Task output is agent-controlled and can contain another PR URL. The task then marks that PR as an inbox review. This bypasses the bot, draft, fork, task-linkage, and current opt-in checks. Stamphog can post a real approval to an unrelated PR in the configured repository.
- **Suggestion:** Before creating the run, load `task_run_id` through a team-scoped tasks facade. Require its signal report, repository, and stored PR URL to match the supplied values. Resolve the acting reviewer and their current toggle again. After the GitHub fetch, require a bot author and require `pr.head.repo.full_name` to equal `repo_config.repository`. Return without creating a run when any check fails.
- **Validator:** - **Checked:** I traced the task parameters from the `TaskRun` save receiver through the review workflow and GitHub approval path.
- **Found:** `products/review_hog/backend/receivers.py:92-138` accepts `output.pr_url` and queues it without checking the task repository. The codebase states that `output.pr_url` is user-writable at `products/tasks/backend/temporal/code_workstreams/activities/load_pr_urls.py:23-31`.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1130-1174` checks only the URL shape, repository configuration, PR state, and head SHA. It does not reload the task run or check the PR author and head repository.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1176-1229` copies the unverified identifiers into inbox provenance. That provenance enables the self-driving carve-out at `products/stamphog/backend/temporal/activities.py:448-451`.
- **Found:** The normal webhook carve-out performs the missing bot, fork, task-linkage, and current toggle checks at `products/stamphog/backend/tasks/tasks.py:167-207`.
- **Impact:** A writable task output can direct the privileged inbox review path to an unrelated open PR in an enabled repository. The workflow can submit a GitHub approval at `products/stamphog/backend/temporal/activities.py:723-755`. This crosses an authorization boundary.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:126-138

**The receiver skips real self-driving implementation tasks**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** This dispatch cannot run for auto-started Inbox implementations. `products/signals/backend/auto_start.py` creates these tasks with `internal=True`. The guard at lines 104-105 returns before this new dispatch. The comment that calls the implementation task non-internal conflicts with the task creation code.
- **Suggestion:** Replace the `task.internal` guard with a check that identifies the implementation task by its product and stage. Permit the internal implementation task. Continue to reject research, repository selection, and custom-agent tasks.
- **Validator:** - **Checked:** I traced the auto-start task creation and the receiver gates before both review dispatches.
- **Found:** `products/signals/backend/auto_start.py:244-265` creates the implementation task with `ai_stage="implementation"` and `internal=True`.
- **Found:** `products/review_hog/backend/receivers.py:104-105` returns for every internal task. Both dispatch paths start after this guard at `products/review_hog/backend/receivers.py:115-139`.
- **Found:** The receiver tests create reviewable tasks with `internal=False` by default at `products/review_hog/backend/tests/test_inbox_trigger.py:61-80`. They do not model the auto-start configuration.
- **Impact:** Auto-started Inbox implementation tasks cannot start either review. This breaks the main user flow introduced by the change.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:111-126,144-156

**The toggle check ignores other assigned reviewers**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The feature must run when any assigned reviewer enables `stamphog_review_inbox_prs`. This code selects one acting reviewer first. It then checks only that user's setting. The initial review and webhook re-review both skip the PR when another assigned reviewer opted in.
- **Suggestion:** Resolve all assigned reviewers for the Stamphog gate. Select the task creator when that user is assigned and opted in. Otherwise, select the first assigned reviewer who opted in. Return no user only when no assigned reviewer enabled the toggle. Use this same selection for the initial dispatch and webhook resolver.
- **Validator:** - **Checked:** I traced reviewer resolution, both Stamphog toggle checks, and the behavior for reports with multiple assigned reviewers.
- **Found:** `_resolve_assigned_reviewer` selects the task creator or first resolved reviewer at `products/review_hog/backend/receivers.py:159-173`.
- **Found:** The initial path checks only that selected user's setting at `products/review_hog/backend/receivers.py:111-126`.
- **Found:** The webhook resolver repeats the same single-user check at `products/review_hog/backend/receivers.py:144-156`.
- **Found:** Suggested reviewer lists can contain up to three reviewers, as shown by `MAX_SUGGESTED_REVIEWERS` at `products/signals/backend/report_generation/resolve_reviewers.py:30`.
- **Impact:** One assigned reviewer's disabled setting can block another assigned reviewer's explicit opt-in. The initial review and all later reviews then skip the PR.

### [❌ dismissed] should_fix · performance — products/stamphog/backend/tasks/tasks.py:1149-1161

**Repeated saves cause a GitHub request before deduplication**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Each receiver call fetches the pull request before it checks for an existing review. TaskRun output saves can enqueue this task many times. These duplicate tasks consume GitHub rate limits and Celery capacity.
- **Suggestion:** Add a short deduplication lock for `(team_id, task_run_id, pr_url)` before the GitHub request. Keep the lock duration short so a later save can recover from a missed webhook.
- **Validator:** - **Checked:** I traced the save receiver, the GitHub fetch, the head-based deduplication, and the recovery tests.
- **Found:** `products/review_hog/backend/receivers.py:85-89` rejects saves that do not update `output`. Only eligible signal implementation runs with an enabled user toggle enqueue the task at `products/review_hog/backend/receivers.py:97-138`.
- **Found:** The task must fetch the current head before it can use the head-based lookup at `products/stamphog/backend/tasks/tasks.py:1155-1174` and `products/stamphog/backend/tasks/tasks.py:1202-1209`.
- **Found:** Repeat execution is an intentional recovery path. It restarts stranded runs and detects missed head changes, as tested at `products/stamphog/backend/tests/test_tasks.py:974-1020`.
- **Impact:** Each eligible output save causes one request, but the finding gives no evidence that this bounded cost causes a real capacity or rate-limit problem. A lock before the fetch can also delay the recovery behavior that requires the current GitHub head.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:126-138

**The queued review ignores a later opt-out**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** This code checks the toggle before it queues the Celery task. The worker does not check the toggle again. A user can disable the setting while the task waits in the queue. Stamphog can then review and approve the pull request after the user opted out.
- **Suggestion:** Check the current toggle in `process_inbox_pr_review` before the GitHub fetch and run creation. Pass enough task identity to resolve the current assigned reviewer through the registered resolver. Stop the task when no assigned reviewer is still opted in.
- **Validator:** - **Checked:** I traced the initial receiver dispatch, the Celery task, its retry paths, and the webhook resolver.
- **Found:** The receiver reads the setting before dispatch at `products/review_hog/backend/receivers.py:114-138`.
- **Found:** `process_inbox_pr_review` accepts that earlier user ID at `products/stamphog/backend/tasks/tasks.py:1109-1112`. It writes the ID into review provenance at `products/stamphog/backend/tasks/tasks.py:1176-1181` without a current settings check.
- **Found:** GitHub failures retry the task at `products/stamphog/backend/tasks/tasks.py:1155-1165`. These retries increase the time between the settings check and run creation.
- **Found:** The webhook path checks the registered resolver at execution time at `products/stamphog/backend/tasks/tasks.py:201-207`. The initial task does not use this resolver.
- **Impact:** The task can create a review run and post an approval after the user disables the feature. This violates the user's current review setting.
