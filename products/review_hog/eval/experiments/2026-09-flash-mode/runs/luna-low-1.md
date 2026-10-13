# Reviewer-quality run — `luna-low-1`

- **Dumped:** 2026-09-16T23:56:00+00:00
- **Report id:** `01a0ac99-3f3f-7b78-9c24-81868fa32fc2` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 840s (14.0 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 12           | 9          | 9           | 8                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 21s      |
| review wave (perspectives)  | 6m 14s   |
| blind-spot sweep            | 2m 45s   |
| dedup (incl. combine/clean) | 19s      |
| validation                  | 4m 07s   |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 9m 00s — the reviewer-model speed comparison number.
- Derived from artefact `created_at` (persisted on completion); only meaningful for fresh, non-resumed runs.

## Chunking

- **chunk 1** (8 files): products/review_hog/backend/models.py, products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py, products/review_hog/backend/api/settings.py, products/review_hog/backend/receivers.py, products/review_hog/frontend/CodeReviewScene.tsx, products/review_hog/frontend/generated/api.schemas.ts, products/review_hog/frontend/generated/api.zod.ts, services/mcp/src/api/generated.ts
- **chunk 2** (8 files): products/stamphog/backend/facade/api.py, products/stamphog/backend/facade/inbox_hooks.py, products/stamphog/backend/tasks/tasks.py, products/stamphog/backend/temporal/activities.py, products/stamphog/backend/logic/reviewer.py, products/tasks/backend/facade/api.py, products/tasks/backend/facade/contracts.py, tach.toml
- **chunk 3** (4 files): tools/pr-approval-agent/review_pr.py, tools/pr-approval-agent/review_local.py, tools/pr-approval-agent/reviewer.py, tools/pr-approval-agent/version.py
- **chunk 4** (2 files): products/stamphog/AGENTS.md, products/stamphog/README.md

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | ?                                              | 0          |
| 1    | 2     | review-hog-perspective-contracts-security      | 1          |
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 1000 | 1     | ?                                              | 0          |
| 1000 | 2     | ?                                              | 0          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/review_pr.py:587-590

**Do not bypass the draft gate for non-bot authors**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The self-driving flag disables the draft prerequisite for every PR, not only bot-authored PRs. If the flag is set incorrectly, a human-authored draft can receive an approval while the trusted prompt incorrectly states that the author is a machine user and that draft status is not a caution signal.
- **Suggestion:** Enforce the invariant at the gate boundary. For example, bypass the draft check only when `self.self_driving and pr.author_is_bot`, and reject or ignore `self_driving` for human-authored PRs. Apply the same validation in `review_local.py` so the offline and hosted paths cannot diverge.
- **Validator:** - **Checked:** I traced `self_driving_review` from `products/stamphog/backend/temporal/activities.py` into `review_local.py` and `Pipeline`, and checked the self-driving rules in `products/stamphog/AGENTS.md`.
- **Found:** `activities.py:451` sets the flag only from `output.get("inbox_review")`. The inbox provenance is created only by the linkage-verified trigger paths. `products/stamphog/AGENTS.md:92` documents that the flag defaults closed and that the server sets it exclusively from persisted inbox provenance.
- **Found:** `review_pr.py:225` and `review_local.py:324` apply the same flag to the bot-author gate. `review_pr.py:590` applies it to the draft gate. The offline and hosted paths therefore have matching behavior.
- **Impact:** No production call site passes `self_driving=True` for a human-authored PR. The proposed failure requires invalid or corrupted trusted server provenance. The current code already treats this provenance as the authorization boundary, so adding a second author check would be defensive hardening rather than a confirmed reachable bug. This does not meet the validation bar.

### [✅ VALID] should_fix · bug — products/review_hog/backend/api/settings.py:16-16

**Restrict the connection flag to GitHub repositories**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The UI uses `has_reviewable_repo_config` to enable the Stamphog toggle, but that query does not filter `provider="github"`. The queue worker later requires a GitHub config, so a team with an enabled, connected config for another provider can see the toggle as available even though no review can run.
- **Suggestion:** Make the connection check use the same provider constraint as `process_inbox_pr_review`, for example by filtering `provider="github"` in `has_reviewable_repo_config` or by exposing a provider-specific facade method.
- **Validator:** - **Checked:** Reviewed `get_stamphog_connected` in `products/review_hog/backend/api/settings.py:72-82`, `has_reviewable_repo_config` in `products/stamphog/backend/facade/api.py:112-123`, and the queue lookup in `products/stamphog/backend/tasks/tasks.py:1140-1147`.
- **Found:** `has_reviewable_repo_config` checks only `enabled`, `connected_by_user_id`, and `installation_id`. It does not constrain `provider`. The queue worker requires `provider="github"` before it can create a review. `StamphogRepoConfig.provider` is an explicit provider-scoped field in `products/stamphog/backend/models.py:24-29`, so non-GitHub configurations can satisfy the UI check.
- **Impact:** A team with only a connected, enabled non-GitHub configuration can see the Stamphog toggle as available, but an Inbox PR will be silently skipped by `process_inbox_pr_review`. This creates an incorrect UI state and prevents the enabled preference from producing the promised review. The issue is actionable and directly affects the new toggle's connection gate.

### [✅ VALID] must_fix · bug — products/tasks/backend/facade/api.py:504-504

**Scope the task lookup before selecting the newest run**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** find_task_run selects the newest matching PR URL or branch across all teams, then find_signal_implementation_run checks run.team_id afterward. If the same repository and PR URL have runs in multiple teams, a newer run from another team can be selected first and cause this function to return None, even when the requested team has a valid self-driving run. This can prevent legitimate Inbox PR reviews from starting.
- **Suggestion:** Add the team filter inside the lookup before ordering and selecting the run. For example, extend find_task_run with an optional team_id filter, or query the matching TaskRun rows directly with team_id=team_id before applying the existing URL/branch precedence.
- **Validator:** - **Checked:** Reviewed `find_signal_implementation_run` in `products/tasks/backend/facade/api.py:484-518`, `find_task_run` in `products/tasks/backend/webhooks.py:29-86`, and the caller in `products/stamphog/backend/tasks/tasks.py:189-203`.
- **Found:** `find_signal_implementation_run` calls `find_task_run` without `team_id` at `products/tasks/backend/facade/api.py:504`. The PR URL lookup in `products/tasks/backend/webhooks.py:39-57` selects one newest matching run before the facade checks `run.team_id` at `products/tasks/backend/facade/api.py:505`. The branch lookup also selects its first match without a team filter at `products/tasks/backend/webhooks.py:65-75`.
- **Impact:** If matching runs exist for the same repository and PR identity in different teams, the selected run can belong to another team. The facade then returns `None` and the Inbox carve-out exits at `products/stamphog/backend/tasks/tasks.py:201`, so a valid self-driving review for the requested team does not start. Team scoping must occur before ordering and selection.

### [✅ VALID] should_fix · bug — tools/pr-approval-agent/review_pr.py:475-477

**Skip author familiarity for self-driving reviews**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The self-driving flag is added to the classification, but self-driving T1 reviews still compute and render author familiarity. This can attribute the bot's git history to the generated diff, even though the prompt says author familiarity has no signal for machine-authored PRs. The reviewer may treat this misleading data as trust or ownership evidence.
- **Suggestion:** Skip familiarity computation when `self_driving` is true, or prevent it from being attached to `classification["familiarity"]` for this mode. Keep the signal available for telemetry only if needed, but do not render it in the self-driving prompt.
- **Validator:** - **Checked:** I traced `_maybe_compute_familiarity()` in `tools/pr-approval-agent/review_pr.py`, the classification field at `tools/pr-approval-agent/review_pr.py:475-477`, and prompt rendering in `tools/pr-approval-agent/reviewer.py`.
- **Found:** `_maybe_compute_familiarity()` always calls `_compute_familiarity()` and stores the result for every T1 review at `tools/pr-approval-agent/review_pr.py:523-534`. `reviewer.py:505-506` then formats both the familiarity block and the self-driving block. `_format_familiarity()` does not check `self_driving`, so it can render author familiarity before `_format_self_driving()` states that familiarity carries no signal.
- **Found:** The self-driving prompt explicitly says that author familiarity has no signal at `tools/pr-approval-agent/reviewer.py:683-699`. The same familiarity data also appears in the serialized classification at `tools/pr-approval-agent/review_pr.py:936`.
- **Impact:** A self-driving T1 review can receive contradictory trusted context. Git history data for the bot or changed paths can look like evidence about author trust or ownership, even though the self-driving mode says the reviewer must judge the diff alone. The issue is reachable for self-driving PRs classified as T1-agent and should be addressed by suppressing the prompt-facing familiarity field while preserving telemetry if needed.

### [✅ VALID] should_fix · performance — products/review_hog/backend/receivers.py:125-138

**avoid queueing duplicate GitHub fetch jobs**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Every TaskRun save that contains the same PR URL schedules another Stamphog Celery task. The deduplication happens only after the task fetches the PR from GitHub, so repeated output saves can create many broker messages and GitHub requests before the database lock removes duplicates. This can cause unnecessary rate-limit pressure and retry load.
- **Suggestion:** Track the last processed PR URL or head metadata before scheduling, or add an atomic enqueue/deduplication key at dispatch time. Keep the database-level deduplication in the worker as a race safeguard, but prevent repeated saves from creating duplicate external fetches.
- **Validator:** - **Checked:** Reviewed `handle_task_run_saved` in `products/review_hog/backend/receivers.py:65-173`, the `transaction.on_commit` dispatch at `products/review_hog/backend/receivers.py:125-138`, and the worker's later GitHub fetch and head-based deduplication in `products/stamphog/backend/tasks/tasks.py:1110-1175`.
- **Found:** The receiver intentionally runs for every saved `TaskRun` output that contains `pr_url`. Each qualifying save registers a separate `on_commit` callback, and `_start_stamphog_review` publishes a new Celery message. The worker does not know whether the message is a duplicate until it resolves the repository and calls `StamphogGitHubClient(...).get_pr(...)`.
- **Found:** The existing worker deduplication protects review-run creation and preserves valid recovery cases, including a failed run, a stranded queued run, and a missed webhook head. It does not prevent duplicate broker messages or duplicate GitHub reads for unchanged output.
- **Impact:** Repeated saves of the same `TaskRun` output can generate avoidable Celery work and GitHub API requests. This is a real performance and reliability risk on a hot save path, including unnecessary rate-limit and retry pressure. Dispatch-time deduplication should preserve the worker check as a race safeguard and still allow new heads and recovery cases.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:210-236

**do not lose the initial review when the broker is unavailable**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** If `process_inbox_pr_review.delay()` fails because the Celery broker is temporarily unavailable, this handler logs the exception and returns. The TaskRun save has already committed, and bot-authored draft PRs do not provide a webhook path that can recover the initial review, so the review is silently lost.
- **Suggestion:** Use a durable handoff, such as an outbox record created in the same transaction and a retrying dispatcher, or persist a retryable enqueue record when `.delay()` fails. The recovery path should retain the PR and task identifiers and retry until the initial review is queued.
- **Validator:** - **Checked:** Reviewed `_start_stamphog_review` in `products/review_hog/backend/receivers.py:210-236`, its `transaction.on_commit` caller in `products/review_hog/backend/receivers.py:125-138`, and the retry behavior of `process_inbox_pr_review` in `products/stamphog/backend/tasks/tasks.py:1110-1175`.
- **Found:** The queue call occurs after the `TaskRun` transaction commits. `_start_stamphog_review` catches every exception from `queue_inbox_pr_review` and only logs it at `products/review_hog/backend/receivers.py:232-236`. `queue_inbox_pr_review` calls Celery `.delay()`, so a broker connection or publish failure happens before a task exists and cannot be recovered by the worker's retry logic.
- **Found:** The receiver can run again on later `TaskRun` saves, but there is no durable record that a queue attempt failed. If no later save carries the PR URL, there is no remaining trigger for the initial review. The webhook path is explicitly limited to later head-changing events, while the initial bot-authored draft review is assigned to `process_inbox_pr_review`.
- **Impact:** A transient broker outage can permanently lose the initial review even though the source `TaskRun` save succeeded. This breaks the promised Inbox review flow and can leave a draft PR without the review needed for Inbox triage. A durable handoff or retryable dispatch record is warranted.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1110-1245

**Validate the PR against the originating implementation run**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The Celery task trusts `pr_url`, `signal_report_id`, and `task_run_id` supplied by the caller, but it never verifies that the fetched PR belongs to that specific non-internal Signals implementation run. Any caller that can invoke the facade can therefore create an `inbox_review` run for another PR in a configured repository. That provenance bypasses the normal bot, draft, review-mode, and write-permission gates, so a forged or stale task payload could trigger an unauthorized hosted review and GitHub approval.
- **Suggestion:** After fetching the PR, call `find_signal_implementation_run(team_id=team_id, repository=repository, pr_url=pr_url, head_branch=((pr.get("head") or {}).get("ref") or None))` and require a non-null result whose `run_id`, `signal_report_id`, and `task_id` match `task_run_id` and `signal_report_id`. Also require the fetched PR head repository to equal `repository`, as the webhook carve-out does. Return without creating a run when any identity check fails.
- **Validator:** - **Checked:** Reviewed `process_inbox_pr_review` in `products/stamphog/backend/tasks/tasks.py:1110-1245`, its only normal caller in `products/review_hog/backend/receivers.py:211-234`, and `queue_inbox_pr_review` in `products/stamphog/backend/facade/api.py:128-149`. I also checked how `inbox_review` provenance enables the hosted review path at `products/stamphog/backend/tasks/tasks.py:880-969` and `products/stamphog/backend/temporal/activities.py:175-238`.
- **Found:** `process_inbox_pr_review` parses and fetches the PR at `products/stamphog/backend/tasks/tasks.py:1137-1173`, then copies the caller-provided `signal_report_id` and `task_run_id` directly into `inbox_review` at `products/stamphog/backend/tasks/tasks.py:1176-1182`. No lookup connects those identifiers to the fetched PR, its head branch, or a non-internal Signals task before the run is created at `products/stamphog/backend/tasks/tasks.py:1225-1229`.
- **Found:** The provenance is trusted to bypass bot, draft, review-mode, and author-permission gates at `products/stamphog/backend/tasks/tasks.py:880-881`, `products/stamphog/backend/tasks/tasks.py:944`, and `products/stamphog/backend/tasks/tasks.py:967-969`. The temporal activity enables `self_driving_review` from the persisted `inbox_review` value at `products/stamphog/backend/temporal/activities.py:451`.
- **Found:** The normal receiver checks the toggle and resolves the acting reviewer before calling the facade at `products/review_hog/backend/receivers.py:211-234`, but `queue_inbox_pr_review` only dispatches the payload and performs no provenance validation at `products/stamphog/backend/facade/api.py:128-149`. The Celery task itself is therefore the final trust boundary for the identifiers it persists.
- **Impact:** A stale, malformed, or independently invoked payload can cause an open PR in the configured repository to receive trusted inbox provenance without proving that it came from the referenced self-driving implementation run. This can start the hosted review path for the wrong PR and may produce an unauthorized GitHub approval. The task should validate the run, signal report, repository-native head, and fetched PR identity before creating `ReviewRun`.
- **Priority:** `must_fix` is appropriate because the missing identity check crosses the explicit bot and draft safety boundary and can affect external GitHub state.

### [✅ VALID] should_fix · performance — products/stamphog/backend/tasks/tasks.py:1206-1213

**Add an index for head-based run deduplication**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The receiver task queries ReviewRun by pull_request, head_sha, status, and created_at for every TaskRun output save. ReviewRun has no index covering these fields, so this becomes an increasingly expensive scan as review history grows. Self-driving runs can trigger this query many times for the same PR.
- **Suggestion:** Add a migration with a composite index starting with pull_request_id and head_sha, and include the fields used for filtering or ordering where supported. Keep the query aligned with that index.
- **Validator:** - **Checked:** Reviewed the deduplication query in `products/stamphog/backend/tasks/tasks.py:1206-1213`, the `ReviewRun` model definition in `products/stamphog/backend/models.py:140-168`, and the existing `ReviewRun` indexes and constraints.
- **Found:** `ReviewRun` has no composite index covering `pull_request`, `head_sha`, and the deduplication ordering fields. The query applies equality filters on `pull_request` and `head_sha`, excludes terminal statuses, orders by `created_at`, and locks the first row with `select_for_update()` at `products/stamphog/backend/tasks/tasks.py:1206-1213`.
- **Found:** This query runs inside `process_inbox_pr_review`, which is retriggered when the receiver saves TaskRun output containing the PR URL, as described by the task flow at `products/stamphog/backend/tasks/tasks.py:1115-1122`. Review history remains on the same `PullRequest`, so the candidate rows can grow over time.
- **Impact:** Without a matching index, PostgreSQL may scan and sort an increasing number of `ReviewRun` rows for each receiver retry or refire. This adds latency and database load on a path that already uses a row lock and can run repeatedly for one PR. A composite index beginning with `pull_request_id` and `head_sha`, aligned with the status and ordering predicates, is an actionable performance improvement.
- **Priority:** `should_fix` is appropriate. The issue can degrade with accumulated review history, but it is a performance risk rather than an immediate correctness or security failure.

### [✅ VALID] must_fix · bug — products/stamphog/backend/tasks/tasks.py:1107-1110,1150-1165

**Do not permanently lose the initial review after three transient failures**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The initial inbox review has no webhook redelivery fallback, but the Celery task stops after three retries. A temporary GitHub, database, or Temporal outage can therefore permanently lose the review while the PR remains open. The receiver may not save another output after the failure, so no later task necessarily recreates it.
- **Suggestion:** Use a longer or bounded retry policy for this hand-off, or persist a retryable review request and reconcile it with a periodic task. Treat exhausted retries as an observable failed state that can be retried without requiring another TaskRun output save.
- **Validator:** - **Checked:** Reviewed the Celery declaration and retry paths for `process_inbox_pr_review` at `products/stamphog/backend/tasks/tasks.py:1107-1110` and `products/stamphog/backend/tasks/tasks.py:1150-1165`, plus the receiver dispatch path in `products/review_hog/backend/receivers.py:211-234`.
- **Found:** The task declares `max_retries=3` at `products/stamphog/backend/tasks/tasks.py:1107-1110`. GitHub fetch failures call `retry()` at `products/stamphog/backend/tasks/tasks.py:1150-1165`, and configuration, database, and run-creation failures also call `retry()` at `products/stamphog/backend/tasks/tasks.py:1141-1150` and `products/stamphog/backend/tasks/tasks.py:1234-1237`. Celery stops dispatching the task after the retry limit is exhausted.
- **Found:** The receiver invokes `queue_inbox_pr_review` as fire-and-forget at `products/review_hog/backend/receivers.py:211-234`. The initial review has no GitHub webhook delivery that can redeliver it, and the task only runs again when the receiver processes another qualifying TaskRun output save.
- **Impact:** A transient outage that lasts through the initial attempt and three retries can leave an open inbox PR without its initial review. If no later TaskRun output save occurs, the review is permanently missed even though the toggle and repository configuration remain valid. A durable retry or reconciliation path is needed for this hand-off.
- **Priority:** `must_fix` is appropriate because this is a reliability gap in the primary delivery path for the new feature, and recovery currently depends on an unrelated future event.
