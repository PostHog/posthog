# Reviewer-quality run — `luna-medium-mcp-1`

- **Dumped:** 2026-09-18T14:40:50+00:00
- **Report id:** `01a0b4eb-dbaa-7bb0-a155-6668beac80de` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 700s (11.7 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

The `gpt-5.6-sol` and `xhigh` values above are stale.
They repeat the report row's stored arm, not the arm this run used.
This run used `gpt-5.6-luna` at `medium` for review, blind-spot, and validation.
Selection and dedup used Sonnet.
Read the measured arm from [`luna-medium-mcp-1.usage.md`](luna-medium-mcp-1.usage.md) and [`luna-medium-mcp-1.provenance.json`](luna-medium-mcp-1.provenance.json).

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 12           | 16         | 12          | 9                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- **Captured gateway model cost:** $0.60319142 across 190 requests, from the [audited usage ledger](luna-medium-mcp-1.usage.md). The dump's separate ClickHouse lookup returned no `$ai_generation` events.

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 16s      |
| review wave (perspectives)  | 4m 33s   |
| blind-spot sweep            | 2m 22s   |
| dedup (incl. combine/clean) | 44s      |
| validation                  | 3m 32s   |

- **Review stage total (review wave + blind-spot, excluding selection):** 6m 55s — the reviewer-model speed comparison number.
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
| 1    | 2     | review-hog-perspective-contracts-security      | 2          |
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | review-hog-blind-spots-general                 | 1          |
| 1000 | 4     | review-hog-blind-spots-general                 | 1          |

## Findings (post-dedup) with validator verdict

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:210-236

**Do not silently lose the initial review when task enqueue fails**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** If the Celery broker is temporarily unavailable, queue_inbox_pr_review fails and the exception is only logged. The on_commit callback is then discarded, so the initial Stamphog review is lost unless another TaskRun output save happens later. This makes a transient broker failure silently remove the expected review.
- **Suggestion:** Use a durable outbox or retryable dispatch mechanism for the initial review. Record the pending review before commit and retry task publication until it succeeds, while retaining the worker's existing idempotency checks.
- **Validator:** - **Checked:** Traced the receiver's `transaction.on_commit` callback, the Stamphog facade, and the Celery task's retry behavior.
- **Found:** `products/review_hog/backend/receivers.py:224-234` catches every exception from `queue_inbox_pr_review` and only logs it. The callback registered at `products/review_hog/backend/receivers.py:131-138` has no retry or durable pending state.
- **Found:** `products/stamphog/backend/facade/api.py:149-155` calls `process_inbox_pr_review.delay(...)`. The task's retries at `products/stamphog/backend/tasks/tasks.py:1149-1165` apply only after Celery accepts the message, so they cannot recover a broker failure during `.delay()`.
- **Impact:** A broker outage during the post-commit dispatch can discard the only initial-review enqueue. A later TaskRun output save or webhook push may recover it, but neither is guaranteed, so a valid Inbox PR can remain without its expected initial review. This is a concrete reliability defect for the new review path.

### [✅ VALID] must_fix · bug — products/stamphog/backend/facade/api.py:143-152

**must_fix: do not lose reviews when broker dispatch fails**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The receiver calls this function from an on_commit callback, but a broker failure can prevent `.delay()` from publishing the task. The save has already committed, and no webhook retry exists for the initial inbox review. The review can therefore be lost permanently during a broker outage.
- **Suggestion:** Persist a durable outbox record in the same transaction as the TaskRun change, or use another retryable dispatch mechanism. A separate worker should publish the Celery task and retry until the record is acknowledged.
- **Validator:** - **Checked:** Traced the TaskRun save signal through `transaction.on_commit` at `products/review_hog/backend/receivers.py:126-139`, then followed `_start_stamphog_review` and `queue_inbox_pr_review` through the Celery dispatch path.
- **Found:** The database transaction commits before the callback invokes `process_inbox_pr_review.delay(...)` at `products/stamphog/backend/facade/api.py:149-155`. `_start_stamphog_review` catches every dispatch exception at `products/review_hog/backend/receivers.py:224-234`, logs it, and does not retry or persist the pending review. The initial inbox review has no GitHub webhook retry path; the task's own retry handling starts only after Celery has accepted and executed the task at `products/stamphog/backend/tasks/tasks.py:1150-1165`.
- **Impact:** If the broker is unavailable or publishing fails after the TaskRun save commits, the callback loses the review request permanently. The user receives no review, and later TaskRun saves may not occur, so the existing same-run trigger cannot recover it. A durable retryable dispatch mechanism is required for this reliability gap.

### [✅ VALID] should_fix · bug — products/stamphog/backend/tasks/tasks.py:1115-1118

**Re-check the inbox toggle before creating the review**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The task checks the reviewer toggle only before publishing the Celery job. A queued job or retry can run after the reviewer disables the toggle, but this code still creates and starts an approval review.
- **Suggestion:** Resolve the current acting reviewer through the registered inbox resolver before creating the ReviewRun, and stop when it returns no user or a different user than acting_user_id. Apply this check on retries as well.
- **Validator:** - **Checked:** Traced the initial receiver dispatch at `products/review_hog/backend/receivers.py:126-139`, the queued task entrypoint at `products/stamphog/backend/tasks/tasks.py:1110-1119`, and the existing toggle resolver at `products/review_hog/backend/receivers.py:144-156`.
- **Found:** The receiver checks `stamphog_review_inbox_prs` before publishing the Celery task, but `process_inbox_pr_review` trusts the passed `acting_user_id` and creates the run after only repository, PR-state, and head checks at `products/stamphog/backend/tasks/tasks.py:1141-1169`. The resolver explicitly defines the current toggle as the gate for new Stamphog runs at `products/review_hog/backend/receivers.py:144-156`. Existing coverage only verifies toggle rechecks for the webhook carve-out at `products/stamphog/backend/tests/test_tasks.py:796-809`, not for the receiver-leg task.
- **Impact:** A queued task or retry can execute after the acting reviewer disables the toggle and still create and start a review with inbox provenance. This can produce an approval after the user has opted out. Re-resolving the acting reviewer before run creation would close the stale-queue and retry paths.

### [✅ VALID] should_fix · bug — tools/pr-approval-agent/reviewer.py:568

**Suppress author familiarity for self-driving reviews**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The new provenance block says author familiarity has no signal, but self-driving T1 reviews still compute and render the familiarity block before this text. A bot with prior merged PRs can therefore receive a positive trust signal and influence approval, even though the prompt says to judge the diff without author history.
- **Suggestion:** Skip familiarity computation when `self_driving` is true in both the hosted and local paths, or make `_format_familiarity` return an empty string for self-driving reviews. Keep the provenance block as the only trusted context for the machine author.
- **Validator:** - **Checked:** Traced hosted and local self-driving review paths, familiarity attachment, and prompt rendering.
- **Found:** `Pipeline.run()` calls `_maybe_compute_familiarity()` for every LLM review at `tools/pr-approval-agent/review_pr.py:250-252`. `_maybe_compute_familiarity()` attaches the result to T1 classifications at `tools/pr-approval-agent/review_pr.py:532-534` without checking `self_driving`. The local path also attaches familiarity at `tools/pr-approval-agent/review_local.py:299-309` and calls it for self-driving reviews at `tools/pr-approval-agent/review_local.py:353-354`. `Reviewer._build_review_prompt()` renders that value at `tools/pr-approval-agent/reviewer.py:505` and `tools/pr-approval-agent/reviewer.py:568`, while `_format_familiarity()` includes prior merged PRs and author line ownership at `tools/pr-approval-agent/reviewer.py:659-681`.
- **Impact:** A T1 self-driving review with familiarity data receives author-history guidance in the trusted prompt region. This contradicts the provenance text at `tools/pr-approval-agent/reviewer.py:695-699` and can influence the verdict with a trust signal that the self-driving policy says has no value. The issue affects both supported execution paths and is a concrete correctness problem in review behavior.

### [✅ VALID] must_fix · security — products/stamphog/AGENTS.md:96-101

**Enforce the documented provenance at the receiver boundary**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The documentation says that only linkage-verified trigger paths can stamp inbox provenance and that every other bot PR is refused at every layer. However, `process_inbox_pr_review` accepts caller-supplied `acting_user_id`, `signal_report_id`, and `task_run_id`, then creates an inbox review after only checking the repository configuration and PR state. It does not revalidate the task linkage, toggle, bot author, or repository-native head. A different internal caller or a bug in the receiver could therefore create a carved-out review for an unrelated PR.
- **Suggestion:** Make `queue_inbox_pr_review` or `process_inbox_pr_review` resolve and validate the TaskRun through the tasks facade, recheck the acting user's toggle, and verify the fetched PR is bot-authored with a repository-native head linked to that run before creating `output["inbox_review"]`. Keep the documented provenance invariant true at the durable task boundary.
- **Validator:** - **Checked:** Traced `queue_inbox_pr_review`, its only current caller in `products/review_hog/backend/receivers.py`, and the durable `process_inbox_pr_review` task. Compared these checks with `find_signal_implementation_run` and the provenance invariant in `products/stamphog/AGENTS.md`.
- **Found:** `queue_inbox_pr_review` forwards all caller-supplied identity fields without validation at `products/stamphog/backend/facade/api.py:128-155`. `process_inbox_pr_review` validates only the repository configuration, fetched PR state, and head SHA at `products/stamphog/backend/tasks/tasks.py:1136-1174`, then persists the supplied values directly at `products/stamphog/backend/tasks/tasks.py:1176-1180` and `products/stamphog/backend/tasks/tasks.py:1220-1230`. The existing tasks facade already provides linkage and team checks in `products/tasks/backend/facade/api.py:484-516`.
- **Impact:** A stale, incorrect, or different internal enqueue path can create `ReviewRun.output["inbox_review"]` without proving that the PR belongs to the referenced self-driving run, that the PR is bot-authored with a repository-native head, or that the acting reviewer still has the toggle enabled. That persisted value enables the bot and draft bypass, so the documented provenance invariant is not enforced at the durable boundary. This is a real security and correctness gap, not a speculative caller concern.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1154-1154,1176-1176

**Validate the inbox PR before granting self-driving provenance**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The receiver-leg task trusts the caller-provided `pr_url`, `signal_report_id`, and `task_run_id`. It fetches only an open PR, then stamps `inbox_review` without verifying that the fetched PR is bot-authored, repository-native, or linked to the supplied self-driving task. A malformed or mismatched task output could therefore cause an arbitrary same-team PR to enter the bot-and-draft carve-out and receive an automatic approval.
- **Suggestion:** After fetching the PR, require `_is_bot_authored(pr)`, require its head repository to match `repository`, and call `find_signal_implementation_run` with the fetched PR data. Continue only when the returned run, signal report, and task identifiers match the task arguments. Return without creating a run when any check fails.
- **Validator:** - **Checked:** Traced the receiver inputs from `products/review_hog/backend/receivers.py:92-139`, the PR fetch and provenance construction in `products/stamphog/backend/tasks/tasks.py:1130-1180`, and the existing identity checks in `_inbox_rereview_carve_out` at `products/stamphog/backend/tasks/tasks.py:144-215`.
- **Found:** The receiver forwards `pr_url`, `signal_report_id`, and `task_run_id` from TaskRun output and metadata at `products/review_hog/backend/receivers.py:92-137`. The receiver-leg task fetches the URL's PR and checks only `state == "open"` at `products/stamphog/backend/tasks/tasks.py:1159-1169`, then copies the caller-provided identifiers directly into `inbox_review` at `products/stamphog/backend/tasks/tasks.py:1176-1180`. It does not apply the bot-author or repository-native checks already used at `products/stamphog/backend/tasks/tasks.py:169-178`, and it does not call `find_signal_implementation_run` before creating the run at `products/stamphog/backend/tasks/tasks.py:1223-1229`.
- **Impact:** A self-driving TaskRun can point to an unrelated open PR in the configured repository. The task would stamp that PR with inbox provenance, allowing the downstream engine to bypass the normal bot, draft, and author-permission gates and potentially post an automated approval on unrelated code. This is a reachable security and correctness failure, so the identity and provenance checks must happen before run creation.

### [❌ dismissed] must_fix — tools/pr-approval-agent/review_local.py:321-321

**Reject non-boolean self-driving flags**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** bool(context.get("self_driving_review")) enables the carve-out for any non-empty value, including strings such as "false" or attacker-controlled objects. This flag bypasses both the bot-author refusal and draft gate, so malformed context could allow an unintended bot draft review and approval.
- **Suggestion:** Require an exact boolean value, for example `self_driving=context.get("self_driving_review") is True`. Also validate the trusted provenance fields before enabling the carve-out.
- **Validator:** - **Checked:** Traced every producer of `self_driving_review`, the sandbox hand-off, and the provenance checks that create `inbox_review`.
- **Found:** `review_local.py:321` reads a context file assembled by the server, not PR-controlled content. `build_reviewer_invocation()` declares `self_driving_review` as a boolean and writes it at `products/stamphog/backend/logic/reviewer.py:101-132`. The hosted path derives it from the internally stored `inbox_review` marker at `products/stamphog/backend/temporal/activities.py:448-452`.
- **Found:** The webhook carve-out requires bot authorship, a non-fork repository head, an enabled connected repository, an exact team-scoped task match, and an opted-in acting reviewer at `products/stamphog/backend/tasks/tasks.py:169-213`. The initial inbox path also requires an enabled connected repository before creating a run at `products/stamphog/backend/tasks/tasks.py:1136-1153`, then stores the server-created provenance at `products/stamphog/backend/tasks/tasks.py:1176-1229`.
- **Impact:** A string such as `"false"` is truthy in isolation, but no reachable product path lets PR content or an external caller supply that value to the sandbox context. The context is a server-generated hand-off, and the provenance checks occur before the boolean reaches `review_local.py`. Requiring exact identity would be defensive hardening for malformed internal input, not a correctness or security defect that meets the validation bar. The additional request to validate provenance fields in the engine is redundant because the engine does not use those fields to authorize the carve-out.

### [❌ dismissed] should_fix · performance — products/review_hog/backend/receivers.py:124-138

**Avoid enqueueing duplicate Stamphog tasks for every output save**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Every TaskRun save that contains a PR URL schedules another Stamphog Celery task. TaskRun output can be saved repeatedly, and the receiver intentionally runs on each save. The task deduplicates only after fetching GitHub data and resolving the repository, so repeated saves can create a large queue and redundant GitHub requests.
- **Suggestion:** Deduplicate before dispatching the task with a stable key such as team, PR URL, and task run, or add a short-lived distributed lock/cache around the enqueue operation. Keep the database-level deduplication in the worker as a final safeguard.
- **Validator:** - **Checked:** Traced the receiver's save filters, the Stamphog worker's fetch and deduplication order, and the refire tests.
- **Found:** `products/review_hog/backend/receivers.py:75-79` documents that repeated output saves intentionally re-fire the receiver. `products/review_hog/backend/receivers.py:85-89` already ignores saves that do not update `output`.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1155-1157` fetches GitHub before deduplication because the current head is required for the dedupe key. `products/stamphog/backend/tasks/tasks.py:1198-1221` then uses a locked database lookup to avoid duplicate review runs and sandbox work.
- **Found:** `products/stamphog/backend/tests/test_tasks.py:992-1001` verifies that refiring is required to recover missed synchronize events and failed runs. A stable PR-level enqueue key could suppress a legitimate new-head review or recovery attempt.
- **Impact:** The design can perform a redundant GitHub fetch for repeated output saves, but the proposed pre-dispatch deduplication would conflict with required recovery and current-head behavior. The finding does not show a concrete scale failure beyond bounded redundant work, so it does not meet the validation bar.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:126-138

**Re-check the toggle before creating the initial Stamphog review**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The receiver checks `stamphog_review_inbox_prs` before enqueueing, but the Celery task can run later after the user disables the toggle. `process_inbox_pr_review` does not re-check the setting before creating and publishing the review, so disabling the toggle can still result in a new GitHub approval or comment.
- **Suggestion:** Pass the acting reviewer identity as the task already does, then re-read `ReviewUserSettings` in the queued task before creating the `ReviewRun`. Return without creating a run when `stamphog_review_inbox_prs` is false.
- **Validator:** - **Checked:** Traced the initial queue path, `process_inbox_pr_review`, and the separate webhook resolver used for later reviews.
- **Found:** `products/review_hog/backend/receivers.py:126-138` checks the toggle only when registering the post-commit callback. `products/stamphog/backend/tasks/tasks.py:1115-1119` records that the caller checked the toggle, but the task does not perform a current-settings check before its review-run creation at `products/stamphog/backend/tasks/tasks.py:1222-1230`.
- **Found:** Later webhook reviews use `resolve_stamphog_acting_reviewer`, which re-reads `ReviewUserSettings` at `products/review_hog/backend/receivers.py:151-155`. The initial task has no equivalent guard after the queue delay.
- **Impact:** A user can disable the toggle after the receiver schedules the task but before the worker runs. The task can then create and publish a Stamphog review despite the current opt-out, including a GitHub approval or comment. This is a reachable correctness and user-control bug in the new opt-in feature.

### [❌ dismissed] should_fix · bug — products/stamphog/backend/facade/api.py:123-126

**Limit the reviewable-config check to supported providers**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `has_reviewable_repo_config` treats every enabled, synced provider as reviewable, but the inbox task only resolves `provider="github"`. An enabled synced config for another provider can therefore make the Stamphog inbox toggle appear available even though enabling it always results in a no-op.
- **Suggestion:** Add `provider="github"` to the queryset, or use a shared supported-provider predicate so the UI capability check and the queue task stay aligned.
- **Validator:** - **Checked:** Reviewed `has_reviewable_repo_config`, all writers for `StamphogRepoConfig`, and the inbox task's provider filters.
- **Found:** The sync flow creates configurations with `provider="github"` at `products/stamphog/backend/presentation/views.py:307-309`. The inbox task also requires `provider="github"` at `products/stamphog/backend/tasks/tasks.py:1141-1145`. The public serializer makes `installation_id` read-only at `products/stamphog/backend/presentation/serializers.py:94-103`, so a manually created non-GitHub config cannot become synced through the supported API.
- **Impact:** A synced non-GitHub configuration is not reachable through the current product flows. Adding the filter would guard against unsupported or manually inserted data, but the suggested user-facing no-op requires a speculative state and does not meet the validation bar.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:111-114

**Check the Stamphog toggle for every assigned reviewer**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The resolver selects only the first resolved reviewer. The new feature is intended to run when at least one assigned reviewer enables Stamphog, but the current code skips Stamphog when the first reviewer is opted out and a later assigned reviewer is opted in.
- **Suggestion:** Resolve all assigned reviewers for the Stamphog leg and queue the review when any of them has `stamphog_review_inbox_prs` enabled. Apply the same rule in `resolve_stamphog_acting_reviewer` so later webhook reviews use the same eligibility logic.
- **Validator:** - **Checked:** Traced the TaskRun receiver, `_resolve_assigned_reviewer`, and the webhook resolver used by Stamphog.
- **Found:** `products/review_hog/backend/receivers.py:111-126` resolves one acting reviewer and checks only that user's Stamphog toggle. `products/review_hog/backend/receivers.py:197-206` resolves all assigned users but returns the first resolved user unless the task creator is assigned. `products/review_hog/backend/receivers.py:151-155` applies the same single-user result during webhook re-reviews.
- **Found:** The PR behavior requires Stamphog eligibility when any assigned reviewer has `stamphog_review_inbox_prs` enabled. With an opted-out canonical reviewer followed by an opted-in assigned reviewer, both the initial queue and later webhook review return without running Stamphog.
- **Impact:** This is a reachable correctness bug. Valid assigned reviewers can enable the feature but receive no Stamphog review for their Inbox PRs, and later pushes remain skipped under the same incorrect eligibility check.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1159-1170

**Validate the fetched PR before enabling the inbox carve-out**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The receiver task reviews any open PR returned for the configured repository. It does not verify that the PR is bot-authored or that its head repository is the configured repository. A fork PR or human PR can therefore receive inbox provenance and bypass the normal author, draft, and permission gates.
- **Suggestion:** After fetching the PR, require `_is_bot_authored(pr)` and compare `pr.head.repo.full_name` with `repo_config.repository`. Also validate the supplied task and signal identifiers against the fetched PR before creating the run.
- **Validator:** - **Checked:** Traced `process_inbox_pr_review` from `products/review_hog/backend/receivers.py:126-139`, inspected the fetched PR handling at `products/stamphog/backend/tasks/tasks.py:1130-1245`, and compared it with the stricter webhook carve-out at `products/stamphog/backend/tasks/tasks.py:144-215`.
- **Found:** The receiver forwards `pr_url`, `signal_report_id`, and `task_run_id` from the saved task output at `products/review_hog/backend/receivers.py:92-137`. The inbox task resolves only the configured base repository at `products/stamphog/backend/tasks/tasks.py:1141-1145`, fetches the PR at `products/stamphog/backend/tasks/tasks.py:1159`, checks only that its state is open at `products/stamphog/backend/tasks/tasks.py:1166-1169`, and then creates a run with inbox provenance at `products/stamphog/backend/tasks/tasks.py:1176-1180` and `1223-1229`. It does not call `_is_bot_authored`, compare `head.repo.full_name`, or re-confirm that the identifiers belong to the fetched PR. The existing webhook path performs both bot and head-repository checks at `products/stamphog/backend/tasks/tasks.py:169-178`.
- **Impact:** A saved self-driving task output that names a human-authored PR or a PR whose head comes from a fork can cause an inbox-provenance run. That provenance enables the downstream review flow to bypass the normal bot, draft, and author-permission gates, which can result in an automated review or approval on code unrelated to the self-driving task. This is a security and correctness defect with a concrete reachable trigger.
