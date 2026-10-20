# Reviewer-quality run — `luna-medium-2`

- **Dumped:** 2026-09-17T19:11:27+00:00
- **Report id:** `01a0b0bd-193d-72a3-bb2e-dca0703d3c79` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 710s (11.8 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 13           | 15         | 11          | 10               |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 7s       |
| review wave (perspectives)  | 5m 04s   |
| blind-spot sweep            | 2m 02s   |
| dedup (incl. combine/clean) | 1m 33s   |
| validation                  | 2m 52s   |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 7m 06s — the reviewer-model speed comparison number.
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
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 3          |
| 3    | 3     | ?                                              | 0          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | review-hog-blind-spots-general                 | 1          |

## Findings (post-dedup) with validator verdict

### [✅ VALID] must_fix · security — tools/pr-approval-agent/review_pr.py:225,587-590

**Bind the carve-out to bot authors**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `self_driving=True` bypasses the draft gate for every PR, not only bot-authored PRs. The pipeline then accepts and can approve a human-authored draft if the server marks the run as an Inbox review. The flag is not a substitute for verifying the PR author.
- **Suggestion:** Fail closed when `self_driving` is set for a non-bot PR, or derive a local `is_self_driving_bot = self.self_driving and self.pr.author_is_bot` value and use it for both the bot and draft gates. Apply the same check in `review_local.py` so both entrypoints enforce the contract.
- **Validator:** - **Checked:** Traced `self_driving` through `Pipeline.run`, `_check_prerequisites`, `review_local.run`, and the classification data passed to the reviewer.
- **Found:** `review_pr.py:225` skips the bot-author refusal whenever `self.self_driving` is true, without checking `self.pr.author_is_bot`. `review_pr.py:590` also skips the draft gate for the same flag. `review_local.py:321` copies `context["self_driving_review"]` directly into the pipeline, and `review_local.py:324` only refuses when the PR is a bot-authored PR and the flag is false.
- **Found:** The flag is also recorded as trusted classification state at `review_pr.py:477` and `review_pr.py:938`. A human-authored draft with the flag set therefore reaches the review stage and is presented as a self-driving review.
- **Impact:** Any caller or hosted context that sets `self_driving_review` for a human PR bypasses both intended carve-out gates and can produce an approval for a draft authored by a human. The entrypoints do not enforce the stated bot-only contract locally, so a server-side classification mistake becomes an approval-control failure.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:111-116

**Honor the toggle of any assigned reviewer**

_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The receiver resolves one canonical reviewer and checks only that user's toggle. If the first assigned reviewer is disabled but another assigned reviewer enabled Stamphog, no Stamphog review starts. This does not match the stated rule that at least one assigned reviewer enables the feature.
- **Suggestion:** Resolve the assigned reviewers separately for the Stamphog gate and queue the review when any assigned reviewer has `stamphog_review_inbox_prs` enabled. Keep the selected reviewer explicit in the review provenance so later webhook checks use the same assignment.
- **Validator:** - **Checked:** Reviewed `handle_task_run_saved`, `_resolve_assigned_reviewer`, `resolve_stamphog_acting_reviewer`, and the Stamphog webhook provenance path in `products/stamphog/backend/tasks/tasks.py`.
- **Found:** `products/review_hog/backend/receivers.py:111-114` resolves one reviewer and loads only that user's settings. `products/review_hog/backend/receivers.py:126-138` queues Stamphog only when that canonical user's `stamphog_review_inbox_prs` is enabled. `_resolve_assigned_reviewer` selects the first resolved reviewer at `products/review_hog/backend/receivers.py:167-170` when the task creator is not assigned. A second assigned reviewer with the toggle enabled cannot start Stamphog.
- **Found:** The webhook path at `products/review_hog/backend/receivers.py:151-155` repeats the same single-reviewer resolution, and `products/stamphog/backend/tasks/tasks.py:205-213` stores only the returned `acting_user_id` in provenance. Any fix must preserve the selected reviewer for later webhook checks.
- **Impact:** A report with multiple assigned reviewers can skip the initial Stamphog review even when one assigned reviewer opted in. This violates the PR's stated at-least-one opt-in rule and affects real Inbox PRs. The issue is a correctness bug worth addressing.

### [✅ VALID] should_fix · bug — tools/pr-approval-agent/reviewer.py:506-506

**Do not include author familiarity for self-driving reviews**

_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The self-driving provenance block says that author familiarity has no signal, but the prompt still renders the normal familiarity block. Both `_maybe_compute_familiarity` and `_attach_familiarity` populate `classification["familiarity"]` for T1 self-driving reviews. A strong or moderate familiarity result can therefore influence the LLM verdict and contradict the stated trust model.
- **Suggestion:** Skip familiarity computation for self-driving runs, or make `_build_review_prompt` omit `_format_familiarity(cl)` when `cl.get("self_driving")` is true. Apply the same rule in the offline and hosted paths so their prompts remain consistent.
- **Validator:** - **Checked:** Traced prompt construction in `reviewer.py` and familiarity population in both `review_pr.py` and `review_local.py`.
- **Found:** `reviewer.py:505` always calls `_format_familiarity(cl)`, and `reviewer.py:568` always inserts its result into the prompt before `_format_self_driving(cl)`. The self-driving text at `reviewer.py:687-698` says familiarity carries no signal, but it does not suppress the earlier block.
- **Found:** `review_pr.py:251` calls `_maybe_compute_familiarity()` for every LLM-reviewed run, and `review_pr.py:533-534` stores the result for T1 reviews. The offline path does the same at `review_local.py:353`, where `_attach_familiarity` stores the result before `_llm_review` builds the prompt.
- **Found:** `_format_familiarity` renders non-`NONE` bands with author history and prior ownership context at `reviewer.py:659-681`. That output is trusted prompt content and can affect the model's judgment.
- **Impact:** A T1 self-driving review can include a familiarity signal that the self-driving provenance block says must carry no signal. This creates inconsistent trust guidance and can bias the verdict using author history that the carve-out explicitly excludes. The same defect exists in hosted and offline execution paths.

### [✅ VALID] must_fix · bug — products/stamphog/backend/facade/api.py:149-155

**Prevent broker failures from losing the initial review**

_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The initial review is published with a single fire-and-forget `.delay()` call. If the broker is unavailable, this raises before the Celery task exists. The receiver catches that error and does not retry, so a PR can permanently miss its initial review when no later TaskRun save occurs.
- **Suggestion:** Use a durable handoff or retryable outbox for this dispatch. At minimum, retry the enqueue operation from a persisted event and expose a metric or alert for dispatch failures.
- **Validator:** - **Checked:** I traced the TaskRun receiver, its `transaction.on_commit` callback, the facade dispatch, and the Celery task retry settings.
- **Found:** `products/review_hog/backend/receivers.py:131-139` schedules the dispatch after commit. `products/review_hog/backend/receivers.py:224-234` catches enqueue errors and only logs them. `products/stamphog/backend/facade/api.py:149-155` calls `.delay()` directly. The `max_retries=3` setting at `products/stamphog/backend/tasks/tasks.py:1109` applies only after Celery creates the task, so it cannot retry a failed broker publish.
- **Impact:** A transient broker failure can leave the PR without an initial Stamphog review. Later TaskRun output saves are not guaranteed, so the review can remain missing without a durable retry path or failure alert.

### [✅ VALID] should_fix · bug — products/review_hog/backend/api/settings.py:71-78

**Match the connection check to supported GitHub repositories**

_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** `stamphog_connected` calls `has_reviewable_repo_config`, which treats any enabled, synced provider as reviewable. The Stamphog queue only accepts `provider="github"`. A synced non-GitHub config can therefore enable this switch even though every queued review becomes a no-op.
- **Suggestion:** Make `has_reviewable_repo_config` apply the same `provider="github"` filter as `process_inbox_pr_review`, or expose provider-specific support consistently before enabling the switch.
- **Validator:** - **Checked:** Reviewed `get_stamphog_connected`, `has_reviewable_repo_config`, `queue_inbox_pr_review`, and `process_inbox_pr_review`.
- **Found:** `products/review_hog/backend/api/settings.py:71-78` uses `has_reviewable_repo_config`. That query at `products/stamphog/backend/facade/api.py:120-124` checks only enabled, connected configurations and does not filter `provider`.
- **Found:** The actual Inbox review task at `products/stamphog/backend/tasks/tasks.py:1140-1146` requires `provider="github"`. It returns without creating a review at `products/stamphog/backend/tasks/tasks.py:1151-1153` when no matching GitHub configuration exists.
- **Impact:** A team with only a non-GitHub configuration sees `stamphog_connected=true`, so the UI enables the toggle, but every queued Inbox review becomes a silent no-op. The connection check does not describe a usable Stamphog Inbox review configuration. This is a user-visible correctness bug and meets the bar for keeping the issue.

### [❌ dismissed] must_fix — products/stamphog/backend/tasks/tasks.py:168-190

**Do not re-review bot PRs after they leave draft state**

_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The carve-out checks that the PR is bot-authored, but it does not require the PR to remain a draft. After a self-driving draft becomes ready, a later synchronize or reopened event still matches the task and enables the carve-out. This starts a new Stamphog review even though the intended behavior is to keep the original approval and skip later reviews after the draft becomes ready.
- **Suggestion:** Require `pr.get("draft")` before returning an inbox carve-out. Keep the existing webhook skip path for ready bot PRs so it can dismiss stale approvals on later head changes without creating a new review.
- **Validator:** - **Checked:** I traced `_inbox_rereview_carve_out`, `_review_skip_reason`, the event action filters, the stale-approval path, and the dedicated carve-out tests.
- **Found:** `products/stamphog/backend/tasks/tasks.py:160-165` defines `ready_for_review` as preserving the draft-time approval while later head-changing events still re-review. `products/stamphog/backend/tasks/tasks.py:167-168` limits the carve-out to `synchronize`, `reopened`, and base retarget events. `products/stamphog/backend/tests/test_tasks.py:830-847` explicitly expects `ready_for_review` not to queue a run and `synchronize` to queue one.
- **Found:** Without the carve-out, `products/stamphog/backend/tasks/tasks.py:226-231` skips bot PRs. The caller then enters the stale-approval dismissal path at `products/stamphog/backend/tasks/tasks.py:881-912`, so requiring the PR to remain a draft would both stop the intended re-review and retract the existing approval on later head changes.
- **Impact:** The suggested change conflicts with the documented product behavior and existing tests. The reported defect is not present.

### [✅ VALID] must_fix · security — products/stamphog/AGENTS.md:97-99

**must verify inbox provenance before enabling the carve-out**

_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** This states that only linkage-verified trigger paths can stamp `ReviewRun.output["inbox_review"]`, but `queue_inbox_pr_review` accepts the PR URL, task run ID, and signal report ID from its caller and `process_inbox_pr_review` stamps them without rechecking that the task facade links the PR to that run. A bad or future caller could therefore mark an arbitrary bot PR as self-driving and bypass the bot and draft gates.
- **Suggestion:** Validate the PR through the tasks facade inside the durable Stamphog task before creating the run. Require the returned run and team to match the supplied identifiers, require the repository-native head, and verify the PR is bot-authored and still open. Only then persist `inbox_review` provenance and set `self_driving_review`.
- **Validator:** - **Checked:** Traced `queue_inbox_pr_review`, its only current caller, and `process_inbox_pr_review` through the tasks facade and GitHub fetch.
- **Found:** `queue_inbox_pr_review` forwards caller-controlled `pr_url`, `signal_report_id`, and `task_run_id` directly to the Celery task at `products/stamphog/backend/facade/api.py:128-154`. `process_inbox_pr_review` validates only the repository configuration and open state at `products/stamphog/backend/tasks/tasks.py:1130-1169`, then persists those identifiers as `inbox_review` at `products/stamphog/backend/tasks/tasks.py:1176-1230`. It does not verify task linkage, team and run identity, bot authorship, or repository-native head.
- **Found:** The webhook path performs the required positive identification through `find_signal_implementation_run` and checks bot authorship and native head at `products/stamphog/backend/tasks/tasks.py:169-214`. The tasks facade documents that these checks identify the self-driving shape at `products/tasks/backend/facade/api.py:484-515`, but the receiver path does not call it before stamping provenance.
- **Impact:** A caller that supplies unrelated identifiers can create a provenance-marked run for an open PR and enable the bot and draft carve-outs. This violates the documented fail-closed provenance boundary and is a security issue because it can cause StampHog to review an arbitrary bot-authored PR.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1107-1183

**Revalidate the PR before enabling the self-driving bypass**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The Celery task trusts `pr_url`, `signal_report_id`, and `task_run_id` supplied by the receiver, then stamps `inbox_review` after fetching any open PR in the configured repository. It does not verify that the fetched PR is bot-authored, has a repository-native head, or still belongs to the specific signals implementation run. `inbox_review` enables `self_driving_review`, which bypasses the normal bot, draft, author-association, and write-permission gates. A malformed or tampered task output could therefore make Stamphog approve an unrelated PR as a self-driving PR.
- **Suggestion:** After fetching the PR, resolve the implementation run through `find_signal_implementation_run` using the fetched repository and exact PR URL, and require its `run_id`, `signal_report_id`, and team to match the task arguments. Also require the fetched PR to be bot-authored and its head repository to equal the configured repository before writing `inbox_review`. Treat any mismatch as a no-op and never start the self-driving workflow.
- **Validator:** - **Checked:** I traced the TaskRun receiver, the initial Celery task, the `find_signal_implementation_run` facade, and the fields used to create `ReviewRun.output["inbox_review"]`.
- **Found:** `products/review_hog/backend/receivers.py:92-137` forwards `pr_url` from `TaskRun.output` with the task's team, signal report, and run identifiers. It does not verify that the URL identifies the task's implementation PR. The existing identity check is available through `products/tasks/backend/facade/api.py:484-517`, but `process_inbox_pr_review` does not call it.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1130-1159` parses the supplied URL, selects a configured repository, and fetches the PR. `products/stamphog/backend/tasks/tasks.py:1166-1181` checks only that the PR is open and has a head SHA before stamping the supplied provenance. It does not check `user`, `head.repo.full_name`, `html_url`, `signal_report_id`, or `task_run_id` against a signals implementation run.
- **Impact:** The provenance at `products/stamphog/backend/tasks/tasks.py:1223-1229` enables the self-driving review path for any open PR selected by the supplied URL. A writable or compromised TaskRun output, or a malformed internal dispatch, could bind the trusted reviewer context to an unrelated PR and bypass the normal bot, draft, author, and permission checks. This is a security and authorization failure.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:225-234

**Retry failed Stamphog task submission**

_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** If the Celery broker is unavailable, `process_inbox_pr_review.delay()` fails. This handler catches the error and returns. The initial draft review is then lost because no webhook retry is guaranteed for it.
- **Suggestion:** Use a durable outbox or retryable submission path. Record the pending review before commit, then retry submission until Celery accepts the task. Keep the save path non-blocking.
- **Validator:** - **Checked:** Traced `_start_stamphog_review`, `queue_inbox_pr_review`, the Celery task, and the webhook trigger path. I also checked the receiver tests for queue failure behavior.
- **Found:** `products/review_hog/backend/receivers.py:224-234` catches every exception from `queue_inbox_pr_review` and only writes a log entry. `products/stamphog/backend/facade/api.py:149-155` calls `process_inbox_pr_review.delay()` without a retry or durable pending record.
- **Found:** The initial review task is the receiver leg at `products/stamphog/backend/tasks/tasks.py:1113-1119`. The webhook path handles later deliveries, while bot-authored draft PRs are filtered from the normal webhook flow before the initial review exists.
- **Found:** The receiver can run again on later `TaskRun` output saves, as documented at `products/stamphog/backend/tasks/tasks.py:1125-1128`, but no later save is guaranteed after a successful PR output save. The existing test at `products/review_hog/backend/tests/test_inbox_trigger.py:358-369` confirms that broker failure is intentionally swallowed without recovery.
- **Impact:** A transient broker failure after the database commit can permanently lose the only initial review attempt for a draft Inbox PR. No guaranteed webhook retry or receiver retry restores it. This is a real reliability defect for the feature's primary trigger and should be addressed.

### [✅ VALID] must_fix · bug — products/stamphog/backend/tasks/tasks.py:1107-1109

**Do not permanently drop reviews after three transient failures**

_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** This task has only three retries, but it is the only durable trigger for the initial inbox review and has no GitHub webhook redelivery. A short GitHub outage, rate-limit window, or database outage can exhaust the retries and leave the draft PR without a review permanently.
- **Suggestion:** Use a longer bounded retry policy with backoff, or persist the pending review for reconciliation after task exhaustion. Record a failure metric and alert when the task reaches its final retry.
- **Validator:** - **Checked:** I traced the task retry declaration, every retry call in `process_inbox_pr_review`, and the receiver path that can submit the task again.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1109` limits the task to three retries with a five-second default delay. Fetch failures retry at `products/stamphog/backend/tasks/tasks.py:1159-1165`, and database or workflow-start failures retry at `products/stamphog/backend/tasks/tasks.py:1235-1237`. Rate-limit retries use a delay of at least 60 seconds at `products/stamphog/backend/tasks/tasks.py:1160-1162`.
- **Found:** After Celery exhausts these retries, the task has no reconciliation or persistent pending state. The receiver can submit another attempt only when a later `TaskRun` output save occurs, as described by `products/stamphog/backend/tasks/tasks.py:1125-1128`; that save is not guaranteed after the PR URL is recorded.
- **Impact:** A GitHub rate-limit period, GitHub outage, or database outage that lasts beyond the retry window can permanently leave the initial draft review uncreated. This is a real reliability gap because the initial inbox path has no webhook redelivery fallback.

### [✅ VALID] should_fix · performance — products/stamphog/backend/tasks/tasks.py:1125-1127,1154-1165

**Coalesce repeated receiver jobs before fetching GitHub**

_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The receiver intentionally queues this task on every TaskRun output save, but deduplication happens only after `get_pr()` fetches the current PR. A run that saves output repeatedly therefore creates many Celery jobs and GitHub API calls for the same head, increasing rate-limit pressure and worker load.
- **Suggestion:** Add a short-lived per-team/PR deduplication key before the GitHub fetch, or coalesce jobs by PR while retaining a durable reconciliation path for missed synchronize events. Keep the database head check as the final correctness guard.
- **Validator:** - **Checked:** I traced the TaskRun output writer, the receiver's repeat-save behavior, the task's fetch order, and the head-based deduplication.
- **Found:** `products/tasks/backend/facade/api.py:2139-2154` saves `output` on every `set_task_run_output` call. `products/review_hog/backend/receivers.py:75-79` deliberately submits another review attempt for each output save with the same target.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1154-1159` calls `get_pr()` before checking for an existing run. The database dedupe starts only at `products/stamphog/backend/tasks/tasks.py:1198-1210`, after the GitHub request has already completed.
- **Impact:** Repeated output saves create duplicate Celery work and one GitHub fetch per job, even when the current head already has a handled run. Concurrent or frequent saves can waste worker capacity and consume GitHub API quota. This is a concrete performance issue on a hot TaskRun path, while the database dedupe remains necessary for correctness.
