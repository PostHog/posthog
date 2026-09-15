# Reviewer-quality run — `K-sol-validator-3-max`

- **Dumped:** 2026-08-25T21:36:55+00:00
- **Report id:** `01a03aaa-bc4d-7c6d-ba33-20a87f55e8fc` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 3095s (51.6 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 13           | 10         | 7           | 6                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 15s      |
| review wave (perspectives)  | 33m 29s  |
| blind-spot sweep            | 2m 26s   |
| dedup (incl. combine/clean) | 1m 17s   |
| validation                  | 13m 50s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 35m 55s — the reviewer-model speed comparison number.
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
| 1    | 2     | review-hog-perspective-contracts-security      | 1          |
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 3     | ?                                              | 0          |
| 3    | 1     | review-hog-perspective-performance-reliability | 1          |
| 3    | 2     | review-hog-perspective-performance-reliability | 1          |
| 3    | 3     | ?                                              | 0          |
| 1000 | 1     | ?                                              | 0          |
| 1000 | 2     | ?                                              | 0          |
| 1000 | 3     | review-hog-blind-spots-general                 | 1          |
| 1000 | 4     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/review_local.py:321-321

**Validate the gate flag as a JSON boolean**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `bool()` enables the security carve-out for any truthy value. For example, the JSON string `"false"` bypasses the bot-author and draft gates. This input controls an approval policy boundary, so malformed context must fail closed.
- **Suggestion:** Require the exact JSON boolean: `self_driving=context.get("self_driving_review") is True`. Reject other present types or treat them as false. Add coverage for `"false"`, `1`, and non-empty objects.
- **Validator:** - **Checked:** I traced the flag from `products/stamphog/backend/temporal/activities.py:451` through `products/stamphog/backend/logic/reviewer.py:101` and `products/stamphog/backend/logic/reviewer.py:131`.
- **Found:** The activity converts persisted provenance to `bool` before it builds the context at `products/stamphog/backend/temporal/activities.py:451`. The builder accepts a `bool` and serializes it as a JSON boolean.
- **Found:** The server creates the context file. Pull request content cannot set `self_driving_review` directly.
- **Impact:** The reported string, number, and object values cannot reach `tools/pr-approval-agent/review_local.py:321` through the production call path. Exact-type validation would only defend against a broken trusted caller, so this finding does not meet the validation bar.

### [✅ VALID] must_fix · bug — products/tasks/backend/facade/api.py:507-513

**Post-filtering an unscoped task-run lookup can hide the correct run**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `find_task_run` searches all teams and all task types before this facade checks `team_id`, `signal_report_id`, and `internal`. The PR URL query selects the newest matching run. The branch query selects an unspecified first run. A run from another team or a manual task can win that query. The facade then returns `None` even when a valid signals implementation run also matches. Stamphog will skip later reviews for that valid run.
- **Suggestion:** Apply `team_id`, `task__signal_report_id__isnull=False`, and `task__internal=False` inside the lookup query. Add deterministic ordering for branch matches. A dedicated facade query is safer than calling the generic `find_task_run` and filtering one selected result afterward.
- **Validator:** - **Checked:** I traced `find_signal_implementation_run` into `find_task_run` and its StampHog caller.
- **Found:** `find_task_run` selects a run before applying the required team and task rules. The PR URL query only filters by URL and repository at `products/tasks/backend/webhooks.py:41-56`.
- **Found:** The branch query uses `.first()` without ordering at `products/tasks/backend/webhooks.py:68-75`. `TaskRun` does not enforce a unique repository and branch pair.
- **Found:** The facade rejects the selected run after the query at `products/tasks/backend/facade/api.py:504-509`. It does not search for another valid run.
- **Impact:** A colliding run can cause a false negative. The caller then returns an empty carve-out at `products/stamphog/backend/tasks/tasks.py:191-200`, so StampHog skips the valid re-review.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:225-234

**A broker failure permanently drops the initial review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The callback publishes the only initial review task. It catches the final broker error and stores no retry state. The TaskRun might not save again, so the review can be lost permanently.
- **Suggestion:** Create a durable dispatch record in the same database transaction. Process pending records with a retrying worker and mark each record after successful publication. Add a metric or alert for exhausted retries.
- **Validator:** - **Checked:** I traced the receiver, the facade, and the Celery task retry path.
- **Found:** `handle_task_run_saved` registers a one-time callback at `products/review_hog/backend/receivers.py:131`. `_start_stamphog_review` catches publication errors at `products/review_hog/backend/receivers.py:224-234`.
- **Found:** `queue_inbox_pr_review` calls `.delay()` at `products/stamphog/backend/facade/api.py:149`. The retries at `products/stamphog/backend/tasks/tasks.py:1109` only apply after the broker accepts the task.
- **Found:** No code records a pending dispatch before publication. A later `TaskRun` output save can retry the dispatch, but no code guarantees that save.
- **Impact:** A broker error during the callback can leave an eligible PR without its initial Stamphog review. The log records the error, but no process retries it.

### [✅ VALID] should_fix · bug — products/stamphog/backend/facade/api.py:151-157

**Broker failure can permanently lose the initial review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** This broker publish is the only hand-off for the initial review. The caller catches publish failures and only logs them. A broker outage after the database commit can therefore lose the review permanently. No later TaskRun save is guaranteed to retry the publish.
- **Suggestion:** Store a dispatch record in the same database transaction as the TaskRun update. Let a retryable worker publish pending records and mark them as sent. If an outbox is not available, add a durable retry mechanism for failed publishes instead of relying on another model save.
- **Validator:** - **Checked:** I traced the TaskRun signal, the transaction callback, the facade dispatch, and the Celery task retry policy.
- **Found:** The receiver schedules one publish after the database commit at `products/review_hog/backend/receivers.py:126-139`.
- **Found:** `_start_stamphog_review` catches every publish error and only writes a log at `products/review_hog/backend/receivers.py:224-234`.
- **Found:** Celery retries apply only after the broker accepts the task. The task declaration at `products/stamphog/backend/tasks/tasks.py:1109-1112` cannot retry a failed publish.
- **Found:** Later TaskRun output saves can repeat the dispatch at `products/review_hog/backend/receivers.py:72-89`, but the code does not guarantee another save.
- **Impact:** A broker failure can leave a completed PR without its initial review. The system stores no pending work that can recover the dispatch.

### [✅ VALID] should_fix · bug — tools/pr-approval-agent/reviewer.py:696-699

**Do not claim that every self-driving PR is a draft**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The trusted prompt says that the PR is a draft. A later synchronize event can review the same PR after it becomes ready. The model then receives false trusted context and must ignore the actual draft state.
- **Suggestion:** Make the draft guidance conditional on `pr.draft`. Alternatively, say that self-driving reviews can run on drafts without claiming that the current PR is a draft.
- **Validator:** - **Checked:** I traced later webhook reviews through `products/stamphog/backend/tasks/tasks.py:147` and the prompt construction in `tools/pr-approval-agent/reviewer.py:506`.
- **Found:** A `synchronize` event can use the self-driving carve-out after the PR becomes ready. `_inbox_rereview_carve_out` does not require `pr["draft"]` at `products/stamphog/backend/tasks/tasks.py:147`.
- **Found:** `_format_self_driving` receives only the classification. It always states that the current PR is a draft at `tools/pr-approval-agent/reviewer.py:698`.
- **Impact:** A push to a ready self-driving PR gives the model false trusted context. This context can affect the review verdict and reasoning.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1107-1178

**The initial review task trusts stale and unverified provenance**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The worker trusts `team_id`, `acting_user_id`, `signal_report_id`, `task_run_id`, and `pr_url` from the queued message. It only checks for a matching repo config and an open PR. It does not verify that the task run belongs to the team. It does not verify that the task run produced this PR. It also does not verify the bot author, the repo-native head, or the current reviewer toggle. A task output can therefore point to another PR in a configured repository. The worker can then create a privileged review with `self_driving_review` enabled. The toggle can also change before the worker starts, but the worker still runs the review.
- **Suggestion:** Resolve `task_run_id` again inside this worker through a team-scoped tasks facade. Verify its signal report, repository, and stored PR URL against the supplied values. After the GitHub fetch, require a bot author and require `head.repo.full_name` to match the configured repository. Call the registered reviewer resolver again and use its returned user ID. Stop if any check fails. Pass only stable identifiers in the Celery message where possible.
- **Validator:** - **Checked:** I traced the user-writable TaskRun output, the receiver, the worker checks, and the review engine context.
- **Found:** `output.pr_url` is user-writable, as documented at `products/tasks/backend/temporal/code_workstreams/activities/load_pr_urls.py:23-31`.
- **Found:** The worker resolves only the URL repository and team repo config at `products/stamphog/backend/tasks/tasks.py:1130-1153`. It never loads `task_run_id` or checks its stored data.
- **Found:** The worker checks only the PR state and head SHA at `products/stamphog/backend/tasks/tasks.py:1158-1174`. It does not check the author or head repository.
- **Found:** The worker copies the queued provenance into `inbox_review` at `products/stamphog/backend/tasks/tasks.py:1176-1181`. This value enables `self_driving_review` at `products/stamphog/backend/temporal/activities.py:448-451`.
- **Found:** The webhook path performs the missing bot, repo-native head, task linkage, and current toggle checks at `products/stamphog/backend/tasks/tasks.py:167-207`.
- **Impact:** A user can set a qualifying run's output to another open PR in a configured repository. The worker can then review that PR through the privileged self-driving path and post an approval without the normal trust checks.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:111-127,151-155

**Stamphog ignores enabled settings from secondary reviewers**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The code selects one acting reviewer before it checks the Stamphog setting. It skips the review when that user disabled Stamphog, even if another assigned reviewer enabled it. The webhook resolver repeats this behavior. This conflicts with the requirement that any opted-in assigned reviewer can enable the review.
- **Suggestion:** Resolve the Stamphog reviewer from all assigned reviewers. Prefer the task creator when that user is assigned and opted in. Otherwise, use the first assigned reviewer with `stamphog_review_inbox_prs` enabled. Use that reviewer for both the initial trigger and webhook re-reviews.
- **Validator:** - **Checked:** I traced reviewer selection for the initial trigger and webhook re-reviews. I also checked the multi-reviewer tests and product decisions.
- **Found:** `_resolve_assigned_reviewer` returns one canonical user at `products/review_hog/backend/receivers.py:202-207`. The initial trigger checks only that user's setting at `products/review_hog/backend/receivers.py:114-126`.
- **Found:** `resolve_stamphog_acting_reviewer` uses the same user and returns `None` when that user opted out at `products/review_hog/backend/receivers.py:151-155`.
- **Found:** The canonical-user rule at `products/review_hog/DECISIONS.md:2677-2681` defines ReviewHog option ownership. It does not establish the stated any-reviewer rule for the new Stamphog toggle.
- **Impact:** A valid assigned reviewer cannot enable Stamphog when the canonical reviewer keeps the setting off. Both the initial review and later re-reviews remain disabled.
