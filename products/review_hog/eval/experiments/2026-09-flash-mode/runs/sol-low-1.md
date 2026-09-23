# Reviewer-quality run — `sol-low-1`

- **Dumped:** 2026-09-17T00:33:44+00:00
- **Report id:** `01a0acb6-7bc3-7be6-9bdf-8d928195d4a2` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1201s (20.0 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 12           | 11         | 9           | 7                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 20s      |
| review wave (perspectives)  | 8m 19s   |
| blind-spot sweep            | 3m 13s   |
| dedup (incl. combine/clean) | 1m 32s   |
| validation                  | 5m 57s   |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 11m 32s — the reviewer-model speed comparison number.
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
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 3     | ?                                              | 0          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 1000 | 1     | ?                                              | 0          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] should_fix — tools/pr-approval-agent/review_local.py:321-321

**Validate the gate flag as an exact JSON boolean**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** This code uses Python truth conversion for a security-sensitive flag. Values such as "false", 1, or an object enable the bot and draft gate exceptions. A malformed context can therefore grant broader behavior than its value states.
- **Suggestion:** Require an exact JSON boolean. For example, use `context.get("self_driving_review") is True`. Reject other non-null values or keep the exception disabled. Apply the same strict check when the server creates and consumes this field.
- **Validator:** - **Checked:** I traced `self_driving_review` from the hosted server to the sandbox context.
- **Found:** `build_reviewer_invocation` accepts a typed `bool` and serializes it with `json.dumps` at `products/stamphog/backend/logic/reviewer.py:101-137`.
- **Found:** The caller derives that boolean from verified, stored inbox provenance at `products/stamphog/backend/temporal/activities.py:448-451`.
- **Found:** Untrusted PR data cannot set or change this context field. A malformed value requires control of the trusted server-generated context.
- **Impact:** The reported non-boolean inputs cannot occur through the production call path. An exact-type check would only defend against a compromised trusted boundary, so this does not meet the review bar.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:225-235

**A broker outage can permanently lose the initial Stamphog review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The callback catches a failed Celery publish and only writes a log. The TaskRun save then succeeds, and no durable record requests another publish. A later TaskRun save can trigger another attempt, but no later save is guaranteed. A short broker outage can therefore leave an opted-in pull request without its initial review.
- **Suggestion:** Store the pending dispatch in the database before commit. Process it with a retrying worker and mark it complete after Celery accepts the task. Keep the existing head-based deduplication in `process_inbox_pr_review` so repeated dispatch attempts remain safe.
- **Validator:** - **Checked:** I traced the `TaskRun` receiver, the Celery facade, and the worker retry logic.
- **Found:** `handle_task_run_saved` registers the dispatch only as an `on_commit` callback at `products/review_hog/backend/receivers.py:131`. It does not store a dispatch record.
- **Found:** `queue_inbox_pr_review` calls Celery `.delay()` directly at `products/stamphog/backend/facade/api.py:149`. `_start_stamphog_review` catches a publish error at `products/review_hog/backend/receivers.py:233`.
- **Found:** The worker retries failures after Celery accepts the message at `products/stamphog/backend/tasks/tasks.py:1148`. These retries cannot recover a failed initial publish.
- **Found:** A repeat attempt requires another eligible `TaskRun` output save at `products/review_hog/backend/receivers.py:85`. The code does not guarantee this save.
- **Impact:** A temporary broker failure can leave an opted-in pull request without its initial review. The database contains no pending work that a later process can recover.

### [❌ dismissed] consider · performance — products/review_hog/backend/api/settings.py:76-81

**A Stamphog database outage can create a settings-endpoint log storm**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Every settings response queries the Stamphog database. During an outage, every request logs a full exception before it returns `false`. The circuit breaker can reduce query time, but this handler still emits one stack trace for each request. This can flood logs and hide the original database failure.
- **Suggestion:** Log this failure through a rate-limited or sampled path. Add a counter for failed connectivity checks. If the Stamphog database layer already reports the exception, omit the repeated stack trace here.
- **Validator:** - **Checked:** I traced the settings endpoint, its frontend callers, and the product database circuit breaker.
- **Found:** The frontend loads these settings once when the Code review scene mounts at `products/review_hog/frontend/reviewHogSettingsLogic.ts:801`. It also calls the endpoint after a user changes a setting.
- **Found:** The review list polling does not reload the settings. Therefore, one open page does not produce repeated exceptions during an outage.
- **Found:** The circuit breaker rejects later connections without database I/O at `posthog/db_backends/failopen/base.py:34`. It also reports breaker state changes at `posthog/db_circuit_breaker.py:250`.
- **Impact:** The handler can log one stack trace for each scene load or settings update. This low-rate endpoint does not provide evidence for a log storm. Rate limiting and a new counter would add complexity for a minor operational case.

### [✅ VALID] should_fix · bug — products/stamphog/backend/facade/api.py:149-155

**Broker failure can permanently drop the initial review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** This function publishes the only initial-review task directly to Celery. The caller catches publish errors and only logs them. No durable record remains for a later retry. A temporary broker failure can therefore prevent the PR review permanently.
- **Suggestion:** Use a durable outbox or another retryable handoff. Store the review request in the same database transaction, then let a worker publish pending requests. At minimum, schedule a retry when the Celery publish fails.
- **Validator:** - **Checked:** I traced `queue_inbox_pr_review` and its caller in `products/review_hog/backend/receivers.py`.
- **Found:** `process_inbox_pr_review.delay` creates no database record before publication (`products/stamphog/backend/facade/api.py:149`).
- **Found:** `_start_stamphog_review` catches every publication error and only writes a log (`products/review_hog/backend/receivers.py:224-234`).
- **Found:** A later output save can publish the task again, but no code guarantees another save (`products/review_hog/backend/receivers.py:73-83`).
- **Impact:** If the broker rejects all publication retries and the run has no later output save, the initial review never starts. The worker cannot recover it because no durable request exists.

### [✅ VALID] should_fix · bug — products/stamphog/backend/tasks/tasks.py:1231-1237

**Exhausted Temporal retries leave review runs queued forever**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** A Temporal start failure leaves the committed ReviewRun in QUEUED state. The task retries only three times with a five-second delay. No periodic process recovers queued runs. A longer Temporal outage leaves the review stranded unless an unrelated TaskRun save starts this task again.
- **Suggestion:** Add durable recovery for old QUEUED runs. For example, schedule a reconciliation task that starts workflows for queued runs without an active workflow. Also use longer exponential backoff for Temporal outages and mark the run failed after the recovery limit.
- **Validator:** - **Checked:** I traced workflow startup, Celery retry settings, deduplication, webhook recovery, and scheduled tasks.
- **Found:** `process_inbox_pr_review` permits only three retries with a five-second delay (`products/stamphog/backend/tasks/tasks.py:1109`).
- **Found:** The transaction commits the `QUEUED` row before `_start_review_workflow` runs (`products/stamphog/backend/tasks/tasks.py:1223-1237`).
- **Found:** The exception path retries the task but does not change the run status (`products/stamphog/backend/tasks/tasks.py:1235-1237`).
- **Found:** The only restart path for this run requires another invocation of `process_inbox_pr_review` (`products/stamphog/backend/tasks/tasks.py:1202-1215`). No scheduled task scans old `QUEUED` runs.
- **Impact:** A Temporal outage that lasts through the retry window leaves the run in `QUEUED`. A PR with no later output save or head change receives no review.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1110-1176

**Initial review trusts unverified inbox provenance**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The task trusts all Celery arguments after it finds a team repo config. It does not verify that task_run_id produced this PR. It also does not verify the signal report, acting reviewer toggle, bot author, or repo-native head. A forged or stale task invocation can mark any open PR in the configured repo as self-driving. The engine then bypasses its bot and draft safety checks and can submit an approval.
- **Suggestion:** Resolve task_run_id inside this task with team scope. Require its stored PR URL, repository, signal_report_id, and acting reviewer to match the request. Recheck the current toggle through the registered resolver. After the GitHub fetch, require a bot author and require head.repo.full_name to equal the configured repository. Return without creating a ReviewRun if any check fails.
- **Validator:** - **Checked:** I traced the TaskRun write API, receiver gates, Celery task, workflow activities, and approval path.
- **Found:** Any team member can control a signal-report task (`products/tasks/backend/visibility.py:30-47`). The update API accepts caller-controlled `output` data (`products/tasks/backend/presentation/serializers.py:167-179`).
- **Found:** The receiver passes `output.pr_url` to Celery without matching it to the task repository (`products/review_hog/backend/receivers.py:91-137`).
- **Found:** `process_inbox_pr_review` uses `task_run_id`, `signal_report_id`, and `acting_user_id` only as stored provenance (`products/stamphog/backend/tasks/tasks.py:1176-1181`). It does not resolve the source run or recheck the toggle.
- **Found:** The task accepts any open PR returned by GitHub. It does not require a bot author or a repository-native head (`products/stamphog/backend/tasks/tasks.py:1153-1174`).
- **Found:** Any nonempty `inbox_review` value enables `self_driving_review`, which bypasses the engine safety gates (`products/stamphog/backend/temporal/activities.py:448-452`).
- **Impact:** A team member can change a signal task output to target an unrelated PR in a configured repository. Stamphog can then treat that PR as self-driving and submit an approval without the required provenance checks.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:111-126,144-155

**Stamphog checks only one assigned reviewer**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The feature must run when any assigned reviewer enables the Stamphog toggle. This code first selects one acting reviewer. It then checks only that user's setting. A primary reviewer with the toggle off blocks the review, even when another assigned reviewer opted in. The webhook resolver repeats this behavior, so later commits also skip review.
- **Suggestion:** Resolve all assigned reviewers for the Stamphog path. Prefer the task creator when that user is assigned and opted in. Otherwise, select the first assigned reviewer with `stamphog_review_inbox_prs` enabled. Use the same selection logic for the initial dispatch and webhook re-reviews. Add a regression test with two assignees where only the second assignee opted in.
- **Validator:** - **Checked:** I traced reviewer resolution for the initial dispatch and later webhook events. I also checked the multiple-reviewer tests.
- **Found:** `_resolve_assigned_reviewer` returns one user at `products/review_hog/backend/receivers.py:206`. It does not return all assigned users.
- **Found:** The initial Stamphog path reads only that user's settings at `products/review_hog/backend/receivers.py:114`. It checks the toggle at `products/review_hog/backend/receivers.py:126`.
- **Found:** The webhook resolver uses the same single user at `products/review_hog/backend/receivers.py:151`. It returns `None` when that user's toggle is off at `products/review_hog/backend/receivers.py:154`.
- **Found:** `test_opted_out_canonical_reviewer_blocks_the_review` at `products/review_hog/backend/tests/test_inbox_trigger.py:229` covers the ReviewHog toggle. No test defines this behavior for the separate Stamphog toggle.
- **Impact:** A report with multiple assigned reviewers can skip all Stamphog reviews when a later assigned reviewer opted in. This breaks the feature's opt-in behavior for both initial and later reviews.

### [✅ VALID] should_fix · bug — products/tasks/backend/facade/api.py:504-506

**Team scope is applied after an unscoped run selection**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `find_task_run` searches all teams and selects one run before this function checks `team_id`. A matching run from another team can win the query. The function then returns `None` even when the requested team has a valid matching run.
- **Suggestion:** Apply `team_id` inside the queries that select the task run. Add a team-scoped parameter to `find_task_run`, or implement the lookup here with `TaskRun.objects.filter(team_id=team_id, ...)` before ordering and selecting the first row.
- **Validator:** - **Checked:** I traced `find_signal_implementation_run`, `find_task_run`, model constraints, ordering, and existing tests.
- **Found:** `find_task_run` selects the preferred PR URL match across all teams (`products/tasks/backend/webhooks.py:29-59`). The branch lookup is also unscoped (`products/tasks/backend/webhooks.py:66-79`).
- **Found:** `find_signal_implementation_run` checks `run.team_id` only after that selection (`products/tasks/backend/facade/api.py:504-506`). It does not search again after a mismatch.
- **Found:** `TaskRun` has no uniqueness rule that prevents different teams from storing the same PR URL or branch (`products/tasks/backend/models.py:1063-1156`).
- **Impact:** A newer or non-terminal run from another team can win the global selection. The function then misses the requested team's valid run, so Stamphog rejects a legitimate self-driving re-review.

### [✅ VALID] must_fix · security — products/tasks/backend/facade/api.py:503-506

**Branch fallback can bind a different pull request**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The lookup supplies both the PR URL and the head branch. `find_task_run` falls back to the branch when the URL does not match. It can return a run whose `output.pr_url` points to a different PR on the same branch. The carve-out then treats the new bot PR as self-driving and can approve it.
- **Suggestion:** Reject a branch candidate when it has a non-empty `output.pr_url` that differs from `pr_url`. Prefer a dedicated team-scoped query that applies the signal-task filters before selecting one run.
- **Validator:** - **Checked:** I traced the PR URL lookup, branch fallback, self-driving carve-out, and workflow safety flag.
- **Found:** `find_task_run` uses the branch lookup after the PR URL lookup finds no match (`products/tasks/backend/webhooks.py:36-79`).
- **Found:** The branch query does not exclude a run whose `output.pr_url` identifies another PR. It also permits terminal runs (`products/tasks/backend/webhooks.py:66-79`).
- **Found:** `find_signal_implementation_run` accepts that branch candidate when its signal and team fields match (`products/tasks/backend/facade/api.py:503-518`).
- **Found:** The Stamphog caller converts this match into trusted inbox provenance (`products/stamphog/backend/tasks/tasks.py:191-215`).
- **Impact:** A bot PR can reuse a repository-native branch from an earlier signal run. Stamphog can bind the new PR to the old run, enable the self-driving safety bypass, and submit an approval.
