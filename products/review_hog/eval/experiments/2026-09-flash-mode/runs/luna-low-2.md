# Reviewer-quality run — `luna-low-2`

- **Dumped:** 2026-09-17T00:12:55+00:00
- **Report id:** `01a0aca6-ef83-73e3-ae9e-11c451eae896` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 961s (16.0 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 13           | 8          | 8           | 7                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 6s       |
| review wave (perspectives)  | 8m 02s   |
| blind-spot sweep            | 2m 53s   |
| dedup (incl. combine/clean) | 29s      |
| validation                  | 3m 59s   |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 10m 55s — the reviewer-model speed comparison number.
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
| 2    | 3     | ?                                              | 0          |
| 3    | 1     | review-hog-perspective-performance-reliability | 1          |
| 3    | 2     | review-hog-perspective-performance-reliability | 1          |
| 3    | 3     | review-hog-perspective-performance-reliability | 1          |
| 1000 | 1     | ?                                              | 0          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] must_fix — tools/pr-approval-agent/review_local.py:321-321

**Validate the self-driving flag as a strict boolean**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `bool(context.get("self_driving_review"))` enables the carve-out for any truthy JSON value. For example, a string such as `"false"` enables bot-author and draft bypasses. This flag controls security-sensitive review gates, so permissive coercion can cause an incorrectly marked run to approve a bot-authored draft PR.
- **Suggestion:** Require the value to be exactly `True`, or reject the context when it is present with a non-boolean type. For example: `self_driving = context.get("self_driving_review", False); if not isinstance(self_driving, bool): raise ValueError("self_driving_review must be a boolean")`; then pass `self_driving=self_driving`.
- **Validator:** - **Checked:** Traced `self_driving_review` from `products/stamphog/backend/temporal/activities.py:451` through `products/stamphog/backend/logic/reviewer.py:101` and `products/stamphog/backend/logic/reviewer.py:131` into `tools/pr-approval-agent/review_local.py:321`.
- **Found:** The hosted caller sets the value with `bool(output.get("inbox_review"))`, so the context JSON contains only a JSON boolean. The Action path does not set this field. The engine defaults the flag to false when the field is absent.
- **Impact:** A string such as `"false"` is not produced by the current server flow or by PR data. The suggested issue depends on tampering with or bypassing the server-created context, so it does not meet the validation bar for a reachable security defect.

### [✅ VALID] must_fix · security — products/review_hog/backend/receivers.py:114-138

**Validate that the queued PR belongs to the Inbox implementation**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** This queues Stamphog for every `output.pr_url` from a non-internal task after only checking the user's toggle. The queued Stamphog task resolves the repository from the URL and checks that a repository configuration exists, but it does not verify that the PR is bot-authored, belongs to the task's repository, or matches the task's implementation run. A stale, incorrect, or manually supplied `pr_url` can therefore trigger a Stamphog review for an unrelated open PR. This does not match the stated requirement that the background job verify the PR is genuinely an Inbox PR from the team's bot and repository.
- **Suggestion:** Pass the task repository and implementation identity to the Stamphog facade, then validate the fetched PR before creating a review: require the expected repository, a repo-native head, the expected bot author, and a matching signal implementation run. Reuse the same positive-identification checks used by `_inbox_rereview_carve_out` so the initial queue and webhook re-review paths enforce the same invariant.
- **Validator:** - **Checked:** Traced `handle_task_run_saved` and `_start_stamphog_review` in `products/review_hog/backend/receivers.py`, then inspected `queue_inbox_pr_review` and `process_inbox_pr_review` in `products/stamphog/backend/facade/api.py` and `products/stamphog/backend/tasks/tasks.py`.
- **Found:** `products/review_hog/backend/receivers.py:126-138` queues the job after only checking `settings.stamphog_review_inbox_prs` and the presence of `pr_url`. `products/stamphog/backend/tasks/tasks.py:1137-1153` validates only the team-scoped repository configuration. `products/stamphog/backend/tasks/tasks.py:1159-1173` fetches the PR and checks that it is open, but does not validate its author, native head repository, or linkage to `signal_report_id` and `task_run_id` before creating the run at `products/stamphog/backend/tasks/tasks.py:1217-1229`.
- **Found:** The webhook path already applies these positive-identification checks in `products/stamphog/backend/tasks/tasks.py:164-205`: it requires a bot author, a repo-native head, a matching task-facade implementation run for the repository and PR or branch, and the acting-reviewer resolver. The initial queue path does not reuse those checks.
- **Impact:** A task output containing a stale or incorrect open PR URL can cause Stamphog to create and run a review for an unrelated PR in a configured repository when the toggle is enabled. This breaks the Inbox-only review invariant and can produce an unintended GitHub review or approval. The issue is actionable and meets the must-fix bar.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1115,1150

**Validate the PR against the task repository before queueing**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The initial inbox task accepts only `team_id`, `pr_url`, and `task_run_id`. It resolves the repository from `pr_url` and never verifies that the linked task run belongs to that repository. A signal task can therefore queue a Stamphog review for a PR URL that does not match the task's configured repository. This breaks the self-driving PR identity guarantee and can review an unrelated PR.
- **Suggestion:** Load `task_run_id` through a team-scoped tasks facade and require its signal report, non-internal status, and repository to match the parsed PR repository before fetching or creating the review run. Pass the repository identity from the receiver as an additional checked field, or expose a facade method that performs this validation atomically.
- **Validator:** - **Checked:** Traced `review_hog.backend.receivers._start_stamphog_review`, `queue_inbox_pr_review`, `process_inbox_pr_review`, and `find_signal_implementation_run`. Reviewed the repository matching in `products/tasks/backend/webhooks.py:29` and the webhook carve-out in `products/stamphog/backend/tasks/tasks.py:151`.
- **Found:** `process_inbox_pr_review` parses `pr_url` and selects `StamphogRepoConfig` using only that parsed repository at `products/stamphog/backend/tasks/tasks.py:1129-1150`. It stores the supplied `signal_report_id` and `task_run_id` in review provenance at `products/stamphog/backend/tasks/tasks.py:1176-1180`, but never loads or validates `task_run_id`. The receiver passes the task run ID and PR URL independently at `products/review_hog/backend/receivers.py:215-231`. The existing repository and signal-report checks in `find_signal_implementation_run` at `products/tasks/backend/facade/api.py:484-514` are used by the webhook path only, not by this initial receiver path.
- **Impact:** A mismatched PR URL can reach the Celery task with valid team and toggle inputs. The task can then fetch and create a review for the URL's repository while recording provenance from a different signal implementation run. Stamphog may review and publish a verdict for an unrelated PR, which breaks the self-driving PR identity boundary.
- **Priority:** The `must_fix` priority is appropriate because this can cause an incorrect automated review and approval on a PR that is not associated with the Inbox task.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:221-228

**Catch deferred import failures in the commit callback**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The deferred `facade.api` import runs outside the `try` block. If the Stamphog module cannot load because of a deployment or import error, the `transaction.on_commit` callback raises after the database commit. This can surface as a failed request even though the save succeeded.
- **Suggestion:** Move the deferred import inside the `try` block, or wrap the entire function body in the existing error handler. Keep the callback failure isolated from the TaskRun save path.
- **Validator:** - **Checked:** Traced the `transaction.on_commit` registration in `products/review_hog/backend/receivers.py:126-138`, the callback body in `_start_stamphog_review`, and Django's default commit-callback behavior.
- **Found:** The deferred import at `products/review_hog/backend/receivers.py:222` executes before the `try` block at `products/review_hog/backend/receivers.py:224`. The exception handler therefore covers `queue_inbox_pr_review(...)` failures but not import failures. The callback is registered with the default non-robust behavior at `products/review_hog/backend/receivers.py:132`, so an import exception can propagate from the commit callback after the database transaction has committed.
- **Impact:** A transient deployment or module-loading failure can make the save request report an error even though the `TaskRun` write succeeded. It can also prevent later commit callbacks from running. Moving the import inside the existing handler keeps the fire-and-forget receiver failure-isolated as its docstring requires.

### [✅ VALID] should_fix · bug — products/stamphog/backend/facade/api.py:128-157

**Retry failed Celery dispatches for the initial inbox review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** This dispatch is fire-and-forget. If the broker is unavailable or the publish fails, `process_inbox_pr_review.delay(...)` raises and the receiver catches the exception without retrying the receiver or persisting an outbox record. The initial review is then lost because no GitHub webhook redelivery is required for this path.
- **Suggestion:** Use a durable handoff. Either retry the receiver when `.delay()` fails, or persist an outbox record and enqueue it with an `on_commit`/reliable dispatcher. Add monitoring for permanently failed dispatches so a missed inbox review is visible.
- **Validator:** - **Checked:** Traced the initial inbox review from `products/review_hog/backend/receivers.py:116-137` through `_start_stamphog_review` and `queue_inbox_pr_review`. Checked the exception handling around the Celery publish and whether another redelivery path exists for this receiver leg.
- **Found:** `queue_inbox_pr_review` calls `process_inbox_pr_review.delay(...)` directly at `products/stamphog/backend/facade/api.py:149-155`. The receiver invokes this from an `on_commit` callback at `products/review_hog/backend/receivers.py:131-137`. `_start_stamphog_review` catches every publish exception and only logs it at `products/review_hog/backend/receivers.py:224-234`; it does not retry or persist the payload.
- **Impact:** A transient broker or publish failure after the task run save completes leaves no queued job and no durable record to replay. The receiver has no later event that guarantees another attempt for the initial draft review, so the configured inbox review can be silently lost. This is a concrete reliability defect in the new entry path.
- **Priority:** The `should_fix` priority is appropriate because the failure loses a requested review, but it does not affect ordinary webhook-triggered reviews or corrupt existing review data.

### [✅ VALID] must_fix · compatibility — tools/pr-approval-agent/review_pr.py:587-590

**Do not run approval flow on draft pull requests**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The self-driving path now reviews draft pull requests and can produce an approval verdict. GitHub does not allow approving a draft pull request, so the later approval step can fail for every self-driving draft PR. This can leave Inbox tasks without the expected approval and cause repeated retries.
- **Suggestion:** Verify the GitHub review API behavior for drafts and handle this state explicitly. Either defer the approval until the PR becomes ready, or post a non-approval result while draft and record that the approval must be retried after the PR is marked ready.
- **Validator:** - **Checked:** Traced the self-driving draft path from `Pipeline.__init__` and `Pipeline._check_prerequisites` through `post_verdict` and the GitHub review client.
- **Found:** `tools/pr-approval-agent/review_pr.py:587-590` allows drafts when `self.self_driving` is true. The resulting `APPROVED` verdict reaches `products/stamphog/backend/temporal/activities.py:723-745`, which calls `client.post_approve_review(...)` without checking whether the pull request is still a draft.
- **Found:** The approval branch marks the run completed only after the GitHub call succeeds. It has no draft-specific fallback or retry state for an approval rejected by GitHub.
- **Impact:** Self-driving draft reviews can fail during verdict posting instead of producing the expected Inbox result. Temporal retries can repeat the same rejected approval request while the pull request remains a draft. The draft-time approval contract therefore needs an explicit implementation and GitHub behavior check.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1178-1186

**Revalidate the inbox PR before creating the initial review**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The initial task trusts the PR URL, team ID, signal report ID, task run ID, and acting user ID supplied by the receiver. After fetching the PR, it does not verify that the PR is bot-authored, uses a repository-native head, or still matches the signals implementation run identified by `signal_report_id` and `task_run_id`. A malformed or stale TaskRun output could therefore cause Stamphog to review an unrelated human PR and post an approval under the inbox carve-out.
- **Suggestion:** After fetching the PR, apply the same positive-identification checks as the webhook path: require bot authorship, require `head.repo.full_name` to match the configured repository, and resolve `find_signal_implementation_run` for the fetched PR and head branch. Require the returned run and signal report to match the task arguments before creating the `ReviewRun`; otherwise return without reviewing.
- **Validator:** - **Checked:** Traced the receiver inputs into `process_inbox_pr_review`, the GitHub fetch, the provenance written to `ReviewRun`, and the engine's self-driving review gates. Compared these checks with `_inbox_rereview_carve_out` at `products/stamphog/backend/tasks/tasks.py:151-217`.
- **Found:** After fetching the PR, `process_inbox_pr_review` checks only that the PR is open and has a head SHA at `products/stamphog/backend/tasks/tasks.py:1167-1174`. It does not call `_is_bot_authored`, compare `head.repo.full_name` with the configured repository, or resolve the supplied `task_run_id` and `signal_report_id` against the fetched PR. It then writes `inbox_review` provenance from the caller's values at `products/stamphog/backend/tasks/tasks.py:1176-1180` and creates the review run at `products/stamphog/backend/tasks/tasks.py:1217-1234`.
- **Found:** The engine uses inbox provenance to enable the self-driving review path, while the webhook path explicitly requires bot authorship, repository-native heads, and a matching signals implementation run at `products/stamphog/backend/tasks/tasks.py:151-217`. The initial path lacks these equivalent identity checks.
- **Impact:** A stale or mismatched PR URL can cause the worker to fetch an open human-authored or fork PR and mark it as an inbox review. The inbox provenance can then bypass normal bot and draft restrictions, allowing Stamphog to publish an automated verdict or approval for code that the identified signals task did not produce. This is a concrete security and correctness failure at the initial review boundary.

### [✅ VALID] should_fix · bug — products/stamphog/backend/tasks/tasks.py:1176-1181

**Re-check the opt-in toggle before creating the initial review**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The task trusts the acting_user_id and creates the review without checking whether that user's stamphog_review_inbox_prs toggle is still enabled. The receiver checks the toggle before queueing, but Celery can run later, after the user opts out. This can start a review after the user disabled the feature.
- **Suggestion:** Resolve the current acting reviewer and toggle again before building inbox_review or creating the ReviewRun. If the toggle is off, log and return without creating a run. Reuse the existing ReviewHog resolver through the inversion hook so the initial and webhook paths apply the same gate.
- **Validator:** - **Checked:** Traced the toggle check in `products/review_hog/backend/receivers.py`, the Celery handoff, `process_inbox_pr_review`, and the existing toggle resolver used by the webhook path.
- **Found:** The receiver checks `settings.stamphog_review_inbox_prs` before registering the callback at `products/review_hog/backend/receivers.py:131-137`, then passes `acting_user_id` to the queued task at `products/review_hog/backend/receivers.py:224-231`. `queue_inbox_pr_review` forwards that value without another check at `products/stamphog/backend/facade/api.py:128-155`. `process_inbox_pr_review` records it in `inbox_review` and creates the run at `products/stamphog/backend/tasks/tasks.py:1176-1234` without consulting the current setting.
- **Found:** The webhook path explicitly re-resolves the acting reviewer and toggle through `resolve_stamphog_acting_reviewer` before allowing a re-review at `products/stamphog/backend/tasks/tasks.py:202-217` and `products/review_hog/backend/receivers.py:143-158`. The initial receiver path has no equivalent re-check after the asynchronous handoff.
- **Impact:** If the user disables the setting after the receiver callback queues the task but before Celery executes it, the task still creates and starts an inbox review. This violates the feature's opt-out behavior and can produce a review after the user disabled the feature. The issue is a real asynchronous state race and merits the proposed re-check.
