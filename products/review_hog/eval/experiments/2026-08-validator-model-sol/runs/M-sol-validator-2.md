# Reviewer-quality run — `M-sol-validator-2`

- **Dumped:** 2026-08-26T04:27:20+00:00
- **Report id:** `01a03c27-34f9-7f70-b1d4-82c61b64f2ad` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 2792s (46.5 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 13           | 26         | 20          | 18               |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 15s      |
| review wave (perspectives)  | 13m 59s  |
| blind-spot sweep            | 13m 35s  |
| dedup (incl. combine/clean) | 2m 59s   |
| validation                  | 15m 26s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 27m 35s — the reviewer-model speed comparison number.
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
| 1    | 2     | review-hog-perspective-contracts-security      | 3          |
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 5          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 3          |
| 3    | 3     | ?                                              | 0          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | review-hog-blind-spots-general                 | 5          |
| 1000 | 3     | review-hog-blind-spots-general                 | 1          |
| 1000 | 4     | review-hog-blind-spots-general                 | 1          |

## Findings (post-dedup) with validator verdict

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1115-1117,1155-1181

**Recheck the toggle when the queued task runs**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The receiver checks the toggle before it publishes this Celery task. This task never checks it again and fetches the current PR head. A delayed task can therefore review a new head after the acting reviewer turns the toggle off. This conflicts with the specified opt-out behavior for later pushes.
- **Suggestion:** After verifying the TaskRun, call the registered resolver again immediately before run creation. Use the current acting user in provenance. If it returns `None`, skip creation and dismiss any approval from an older head.
- **Validator:** - **Checked:** I traced the toggle read, Celery handoff, current-head fetch, provenance, and opt-out dismissal behavior.
- **Found:** The receiver reads `stamphog_review_inbox_prs` only before publishing at `products/review_hog/backend/receivers.py:111-139`.
- **Found:** `process_inbox_pr_review` never calls the registered resolver. It trusts the queued `acting_user_id` and fetches the current head at `products/stamphog/backend/tasks/tasks.py:1158-1181`.
- **Found:** The task creates a new run with that stale authorization at `products/stamphog/backend/tasks/tasks.py:1222-1234`.
- **Found:** The webhook path does recheck the current toggle at `products/review_hog/backend/receivers.py:144-156`. The product contract states that disabling it stops new runs at `products/stamphog/AGENTS.md:100-109`.
- **Impact:** A delayed or retried task can review and approve a head after the reviewer disables the feature. This defeats revocation of an external approval capability.

### [✅ VALID] should_fix · bug — tools/pr-approval-agent/reviewer.py:699-700

**Trusted prompt claims ready PRs are drafts**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** Later synchronize reviews can run after the PR becomes ready. This trusted block still tells the model that the PR is a draft.
- **Suggestion:** Use state-independent text such as "This flow can review the PR while it is a draft." Alternatively, pass `pr.draft` and add this guidance only for drafts.
- **Validator:** - **Checked:** Traced current PR state from the GitHub fetch through webhook re-reviews and prompt construction.
- **Found:** `products/stamphog/backend/tasks/tasks.py:44-49` permits later `synchronize` reviews. A ready bot PR still enters the carve-out through `products/stamphog/backend/tasks/tasks.py:226-231` and `products/stamphog/backend/tasks/tasks.py:167-215`.
- **Found:** `tools/pr-approval-agent/review_local.py:197` records the current draft state. However, `tools/pr-approval-agent/reviewer.py:506` passes only the classification to `_format_self_driving`.
- **Found:** `tools/pr-approval-agent/reviewer.py:555-568` places this block in trusted context. `tools/pr-approval-agent/reviewer.py:683-700` therefore emits stale lifecycle information after the PR becomes ready.
- **Impact:** The model can apply draft-time assumptions during a review that can approve ready code. This is a reachable prompt correctness bug.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:224-234

**A broker outage permanently drops the initial review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** This code catches every queue publish failure and only writes a log. The task retry policy cannot recover because no task reached the broker. A temporary broker outage can permanently skip the only initial Stamphog review.
- **Suggestion:** Store a pending dispatch in the database before commit. Let a worker publish it and mark it sent. Keep the consumer idempotent. At minimum, add a bounded replay mechanism that runs outside the TaskRun save path.
- **Validator:** - **Checked:** I traced the commit callback, facade publish, Celery retry boundary, webhook path, receiver refire conditions, and replay mechanisms.
- **Found:** The receiver catches every dispatch exception without recording pending work at `products/review_hog/backend/receivers.py:210-234`.
- **Found:** `queue_inbox_pr_review` performs only `.delay()` at `products/stamphog/backend/facade/api.py:128-155`. No database state records an unsuccessful publish.
- **Found:** Consumer retries exist at `products/stamphog/backend/tasks/tasks.py:1109-1165`. They cannot run when the producer never delivers the task.
- **Found:** The receiver ignores later saves that do not update `output` at `products/review_hog/backend/receivers.py:85-89`. No code guarantees another output save.
- **Found:** The opened webhook does not rewrite an existing `pr_url` at `products/tasks/backend/webhooks.py:276-295`. The Stamphog webhook reserves initial reviews for the receiver at `products/stamphog/backend/tasks/tasks.py:160-168`.
- **Impact:** If `.delay()` exhausts its producer retries after the URL save, an unchanged draft has no future trigger. It never receives its initial review.

### [❌ dismissed] should_fix — products/review_hog/backend/receivers.py:126-138

**Concurrent output saves can start duplicate reviews**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Every matching output save queues a job. The agent server and webhook backstop can save the same PR at the same time. The consumer locks matching ReviewRun rows, but an empty result locks nothing. ReviewRun has no unique key for the pull request and head SHA. Two tasks can therefore create costly reviews and post duplicate GitHub results.
- **Suggestion:** Serialize the consumer on the PullRequest row before it checks and creates ReviewRun. Alternatively, enforce a database idempotency key that still permits explicit retries after failures. Add a concurrent dispatch test for this race.
- **Validator:** - **Checked:** I traced the transaction, PR upsert, database constraints, existing-run lookup, and workflow-start idempotency.
- **Found:** The consumer keeps the PR upsert, deduplication check, and ReviewRun creation in one writer transaction at `products/stamphog/backend/tasks/tasks.py:1182-1234`.
- **Found:** `_upsert_pull_request` updates the existing PullRequest row at `products/stamphog/backend/tasks/tasks.py:319-363`. This update locks that row until the surrounding transaction commits.
- **Found:** The webhook path documents and uses this same serialization guarantee at `products/stamphog/backend/tasks/tasks.py:1035-1044`.
- **Found:** Concurrent first inserts serialize through the unique PullRequest key at `products/stamphog/backend/models.py:118-123`. The second `get_or_create` continues after the first transaction commits.
- **Found:** The second consumer then finds the existing run at `products/stamphog/backend/tasks/tasks.py:1202-1221`. Any repeated workflow start uses the same run ID and is idempotent at `products/stamphog/backend/tasks/tasks.py:366-380`.
- **Impact:** The empty ReviewRun result does not expose the claimed race because the PullRequest row already serializes these consumers. At most, both consumers request the same workflow start.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1198-1221

**Head-only dedupe accepts a changed base diff**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** A base retarget changes the reviewed diff without changing `head_sha`. This dedupe treats the old completed run as current. If the retarget webhook is lost, a later receiver run leaves the old approval active over an unreviewed diff.
- **Suggestion:** Include the base SHA in the review identity. When the fetched base differs, dismiss the old approval and create a new run even when the head matches. Treat missing base identity on older runs as requiring a new review.
- **Validator:** - **Checked:** I traced review identity, base-retarget handling, receiver deduplication, and approval dismissal.
- **Found:** `ReviewRun` stores only `head_sha` as the reviewed commit identity at `products/stamphog/backend/models.py:140-163`. It stores no base SHA.
- **Found:** The webhook path explicitly treats a base retarget as a changed diff with an unchanged head at `products/stamphog/backend/tasks/tasks.py:832-860`. It dismisses every approval and starts another review.
- **Found:** The receiver dedupe queries only `pull_request` and `head_sha` at `products/stamphog/backend/tasks/tasks.py:1202-1209`. Any completed run at that head causes an immediate return at `products/stamphog/backend/tasks/tasks.py:1211-1221`.
- **Found:** The current base SHA is available from the fetched PR, but the task does not compare it with the prior reviewed base.
- **Impact:** After a missed retarget delivery, a later receiver run accepts the old verdict for a different diff. The old GitHub approval can remain valid over code Stamphog did not review.

### [✅ VALID] should_fix · performance — products/stamphog/backend/tasks/tasks.py:1202-1229

**Failed reviews can restart without a limit**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The query excludes every failed run. Each later `TaskRun.output` save can therefore create another workflow for the unchanged head. A deterministic failure can start unlimited sandbox runs beyond the Celery and Temporal retry limits.
- **Suggestion:** Limit same-head recovery attempts or add a cooldown. Permit one replacement for a failed run, then require a head change or manual retry. Add a test with repeated receiver calls after a deterministic failure.
- **Validator:** - **Checked:** I traced receiver dispatch, same-head deduplication, Temporal retry limits, and existing retry tests.
- **Found:** `process_inbox_pr_review` excludes `ReviewRun.Status.FAILED` from deduplication at products/stamphog/backend/tasks/tasks.py:1202. It then creates a new `ReviewRun` at products/stamphog/backend/tasks/tasks.py:1222.
- **Found:** The receiver dispatches again after each relevant `TaskRun.output` save at products/review_hog/backend/receivers.py:72. The test at products/stamphog/backend/tests/test_tasks.py:974 confirms that a failed same-head run is recreated.
- **Found:** Each new run gets a fresh workflow and retry budget. The code has no same-head attempt limit or cooldown.
- **Impact:** Repeated output saves after a deterministic failure can repeatedly start costly sandbox reviews. This bypasses the bounded retry policy.

### [✅ VALID] must_fix · bug — tools/pr-approval-agent/reviewer.py:683-703

**Add the bot exception to the system prompt**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The reviewer system prompt still says that every bot author is a showstopper and always needs human review. The new exception appears only in the user prompt. System instructions have higher priority. A compliant model can refuse or escalate the self-driving bot PRs that this change intends to approve.
- **Suggestion:** Put the verified self-driving exception in `REVIEWER_SYSTEM`, or append a conditional system prompt suffix for self-driving runs. Keep the general bot rule for all other runs. Add a test that checks the complete system and user prompts for conflicting instructions.
- **Validator:** - **Checked:** Traced both prompt layers into the SDK call and inspected the self-driving tests.
- **Found:** `.stamphog/review-guidance.md:16-23` defines every bot author as a showstopper that always needs human review.
- **Found:** `tools/pr-approval-agent/reviewer.py:190-210` loads that guidance. `tools/pr-approval-agent/reviewer.py:271-311` sends it as the system prompt.
- **Found:** `tools/pr-approval-agent/reviewer.py:506-568` adds the exception only to the user prompt. The SDK receives that prompt at `tools/pr-approval-agent/reviewer.py:394-395`.
- **Found:** `tools/pr-approval-agent/test_review_local.py:294-311` replaces the LLM call with an approval stub. It cannot detect the conflicting instructions.
- **Impact:** A compliant model can follow the higher-priority rule and reject every intended self-driving review. This can defeat the primary feature, so `must_fix` is appropriate.

### [✅ VALID] must_fix · security — tools/pr-approval-agent/review_local.py:316-324

**Bind the gate bypass to verified PR provenance**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** Any truthy `self_driving_review` value now disables the bot and draft gates. The initial Inbox path stamps this value without verifying the task run, task repository, head repository, or expected Code bot identity. A bad task output can reference an unrelated bot or fork PR in a connected repository. Stamphog can then post an approval for that PR.
- **Suggestion:** Verify the fetched PR before the server sets this flag. Load the exact task run in the same team. Match its signal report, repository, and PR URL. Require a repository-native head and the expected Code bot identity. Also accept only the literal JSON value `true` here, and fail closed for all other values.
- **Validator:** - **Checked:** Traced `TaskRun.output.pr_url` through the receiver, initial review task, sandbox context, engine gates, and GitHub verdict posting.
- **Found:** `products/review_hog/backend/receivers.py:92-138` accepts the run output URL and queues the initial review. `products/tasks/backend/presentation/serializers.py:167-180` permits arbitrary JSON output.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1130-1174` resolves the configuration from that URL. It checks only the PR state and head SHA after fetching the PR. It does not compare the task repository, head repository, or author identity.
- **Found:** `products/stamphog/backend/tasks/tasks.py:1176-1229` stamps `inbox_review` without reloading the named task run. `products/stamphog/backend/temporal/activities.py:448-451` then enables the carve-out from that stamp.
- **Found:** `tools/pr-approval-agent/review_local.py:321-324` and `tools/pr-approval-agent/review_pr.py:225-226` bypass the bot gate. `tools/pr-approval-agent/review_pr.py:584-591` also bypasses the draft gate.
- **Found:** The hosted caller serializes a Boolean value, so loose JSON truthiness is not the main hosted exploit. The unsafe provenance decision occurs before serialization.
- **Impact:** A bad run output can target an unrelated open PR in another enabled repository. `products/stamphog/backend/temporal/activities.py:723-746` can then post a GitHub approval for that PR. This is a real authorization gap and warrants the existing `must_fix` priority.

### [✅ VALID] should_fix · bug — products/stamphog/backend/facade/api.py:149-155

**Initial review dispatch is not durable**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `queue_inbox_pr_review` publishes directly to Celery. Its caller catches publish errors. A broker outage can lose the first review because no durable request remains.
- **Suggestion:** Store an inbox review request before publishing. Use a retrying dispatcher for pending requests. Mark each request complete only after Celery accepts it.
- **Validator:** - **Checked:** I traced the call from `handle_task_run_saved` to `process_inbox_pr_review`.
- **Found:** The receiver registers the dispatch only as an `on_commit` callback at `products/review_hog/backend/receivers.py:126-139`. It does not store a pending dispatch.
- **Found:** `_start_stamphog_review` catches every publish error at `products/review_hog/backend/receivers.py:224-234`. The facade calls `process_inbox_pr_review.delay()` directly at `products/stamphog/backend/facade/api.py:149-155`.
- **Found:** The task retries failures after Celery receives it at `products/stamphog/backend/tasks/tasks.py:1148-1165`. Those retries cannot run when the broker rejects the initial publish.
- **Impact:** A broker outage can leave the committed `TaskRun` without an initial review. A later output save can retry the dispatch, but no code guarantees that save. The webhook path cannot replace this trigger for the bot-authored draft, as documented at `products/stamphog/backend/tasks/tasks.py:1115-1119`.

### [✅ VALID] should_fix · bug — products/stamphog/backend/tasks/tasks.py:1109-1112

**Worker loss can drop the review task**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Celery uses early acknowledgment because this task does not set `acks_late`. A worker loss during the GitHub fetch or Temporal start drops the job.
- **Suggestion:** Set `acks_late=True` and `reject_on_worker_lost=True`. The head-SHA deduplication already makes task redelivery safe.
- **Validator:** - **Checked:** I inspected the task options, global Celery settings, execution steps, and redelivery guards.
- **Found:** The decorator at `products/stamphog/backend/tasks/tasks.py:1109-1112` does not override Celery's early acknowledgment. `posthog/settings/celery.py:8-30` has no global late-ack setting.
- **Found:** The task makes a GitHub request at `products/stamphog/backend/tasks/tasks.py:1158-1165`. It then creates the run and starts Temporal at `products/stamphog/backend/tasks/tasks.py:1182-1237`. A worker termination cannot reach the explicit retry handlers.
- **Found:** Redelivery is safe. The current-head check reuses an existing run at `products/stamphog/backend/tasks/tasks.py:1202-1214`. `_start_review_workflow` ignores a duplicate Temporal start at `products/stamphog/backend/tasks/tasks.py:366-380`.
- **Impact:** A worker crash after acknowledgment can silently remove the only initial review attempt. A later output save can trigger another attempt, but the code does not guarantee that save.

### [❌ dismissed] should_fix — products/stamphog/backend/tasks/tasks.py:201-207

**Check every assigned reviewer's opt-in**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The registered resolver checks only the task creator or first assigned reviewer. It returns `None` when that reviewer opted out, even if another assigned reviewer opted in. This conflicts with the requirement that any assigned user's opt-in enables the review.
- **Suggestion:** Select the task creator when that user opted in. Otherwise, select the first opted-in assigned reviewer. Use this rule for initial reviews and webhook rechecks. Add a test with two assigned reviewers and only the second reviewer opted in.
- **Validator:** - **Checked:** I traced the reviewer selection through the initial trigger and the webhook resolver.
- **Found:** `_resolve_assigned_reviewer` selects the assigned task creator or the first resolved reviewer at `products/review_hog/backend/receivers.py:159-207`. Both trigger paths use that same selection at `products/review_hog/backend/receivers.py:111-126` and `products/review_hog/backend/receivers.py:144-156`.
- **Found:** The product decision states that a non-acting reviewer's opt-in must not replace the acting reviewer at `products/review_hog/DECISIONS.md:2668-2681`.
- **Found:** `test_opted_out_canonical_reviewer_blocks_the_review` covers this exact case at `products/review_hog/backend/tests/test_inbox_trigger.py:228-238`. The assigned creator exception is covered at `products/review_hog/backend/tests/test_inbox_trigger.py:240-252`.
- **Impact:** The proposed selection would override the canonical reviewer's opt-out. It would start a review because a secondary reviewer enabled their own setting. That behavior conflicts with the documented ownership rule.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:887-898

**Opt-out dismissal misses approvals that exist only on GitHub**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** This path only dismisses approvals recorded in `ReviewRun.posted_review_id`. A worker can post an approval and fail before it saves that ID. The approval then exists only on GitHub. An opt-out starts no workflow, so the GitHub-side orphan sweep never runs. The stale approval can still satisfy branch protection after a push.
- **Suggestion:** Move the GitHub-side approval sweep into shared approval logic. Call it from this skip path after the database sweep. Keep approvals for the current head and dismiss older approvals. Add a test with an active GitHub approval and no `posted_review_id`.
- **Validator:** - **Checked:** I traced approval posting, persistence, skip-path dismissal, and Temporal retry recovery.
- **Found:** `post_verdict` posts the GitHub approval before it saves `posted_review_id` at `products/stamphog/backend/temporal/activities.py:744-753`. A worker failure can occur between these operations.
- **Found:** The skip helper calls only the database-keyed sweep at `products/stamphog/backend/tasks/tasks.py:483-516`. That sweep requires `posted_review_id` at `products/stamphog/backend/logic/approvals.py:31-53`.
- **Found:** The workflow has a GitHub-side sweep for approvals without database records at `products/stamphog/backend/temporal/activities.py:292-300`. The opt-out path returns without starting that workflow at `products/stamphog/backend/tasks/tasks.py:881-912`.
- **Found:** A retry after the head moves cannot recover this approval. `_dismiss_orphaned_approval` returns when the ID is missing at `products/stamphog/backend/temporal/activities.py:589-600`.
- **Impact:** The stale approval can authorize a merge of commits that Stamphog did not review. This violates the required invariant at `products/stamphog/AGENTS.md:7-20`.

### [✅ VALID] should_fix · bug — products/stamphog/backend/tasks/tasks.py:1190-1197

**Equal GitHub timestamps can supersede the current run**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The stale check accepts equal `updated_at` values. GitHub timestamps can give two updates in one second the same value. An old fetch can then overwrite the stored snapshot and supersede a newer webhook run. The old run later fails its head check, so the current head receives no verdict.
- **Suggestion:** When timestamps match but run heads differ, preserve the existing webhook run or fetch the current PR again. Add a race test with equal timestamps and different head SHAs.
- **Validator:** - **Checked:** I traced the payload clock, run supersession, workflow head guard, and race tests.
- **Found:** `_upsert_pull_request` accepts an equal timestamp and replaces stored fields at `products/stamphog/backend/tasks/tasks.py:349-358`.
- **Found:** The inbox stale check rejects only a strictly older timestamp at `products/stamphog/backend/tasks/tasks.py:1190-1197`. It then searches only for the fetched head at `products/stamphog/backend/tasks/tasks.py:1202-1209`.
- **Found:** When that head differs, `_supersede_prior_runs` marks every non-terminal current run as superseded at `products/stamphog/backend/tasks/tasks.py:415-432`. The task then creates a run for the stale head at `products/stamphog/backend/tasks/tasks.py:1222-1230`.
- **Found:** The stale run later stops when GitHub reports the current head at `products/stamphog/backend/temporal/activities.py:673-685`. This does not restore the superseded current run.
- **Found:** The existing inbox race test uses a strictly newer stored timestamp at `products/stamphog/backend/tests/test_tasks.py:1023-1047`. It does not cover equal timestamps with different heads.
- **Impact:** Two updates within one timestamp interval can cancel the correct review and start a review that cannot finish. The current head then has no verdict until another trigger occurs.

### [✅ VALID] must_fix · security — products/stamphog/AGENTS.md:85-86,98-101

**Receiver path does not prove that the task created the PR**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The documented linkage guarantee is false on the receiver path. `TaskRun.output["pr_url"]` is caller-writable. `process_inbox_pr_review` does not compare the URL with `Task.repository`. It also does not verify the head repository, branch, or bot identity. A task controller can point a qualifying run at an unrelated PR in a configured repository. Stamphog then stamps `inbox_review` and bypasses the normal trust gates. This can create a real approval for code that the task did not produce.
- **Suggestion:** Validate the PR inside `process_inbox_pr_review` before creating the review run. Load `task_run_id` through the tasks facade and require the expected team, task, report, and repository. Require a repository-native head, the task's attested work branch, and the expected PostHog Code bot identity. Fail closed before writing `inbox_review`. Add regression tests for unrelated PR URLs, different repositories, fork heads, human authors, and branch mismatches.
- **Validator:** - **Checked:** I traced `TaskRun.output` from the task API through the receiver, Celery task, review engine, and GitHub approval write.
- **Found:** `TaskRunUpdateSerializer` accepts caller-supplied `output` at products/tasks/backend/presentation/serializers.py:167. `set_task_run_output` also permits callers to replace `pr_url` at products/tasks/backend/facade/api.py:2139.
- **Found:** `task_control_q` lets every team member control `SIGNAL_REPORT` tasks at products/tasks/backend/visibility.py:30.
- **Found:** The receiver trusts `output["pr_url"]` and queues Stamphog after only task-shape and toggle checks at products/review_hog/backend/receivers.py:92.
- **Found:** `process_inbox_pr_review` derives the repository from that URL at products/stamphog/backend/tasks/tasks.py:1130. It does not load `task_run_id` or compare the PR with the task.
- **Found:** The GitHub checks only require an open PR and a non-empty head SHA at products/stamphog/backend/tasks/tasks.py:1166. This path does not check the head repository, branch, or author.
- **Found:** The webhook path performs the missing native-head and task-link checks at products/stamphog/backend/tasks/tasks.py:169 and products/stamphog/backend/tasks/tasks.py:191.
- **Impact:** The persisted marker enables `self_driving_review` at products/stamphog/backend/temporal/activities.py:448. `post_verdict` can then post an APPROVE review at products/stamphog/backend/temporal/activities.py:723.
- **Impact:** A task controller can trigger a real approval for unrelated code in any reviewable repository. That approval can satisfy branch protection. The end-to-end approval test confirms this path at products/stamphog/backend/tests/test_integration.py:1385.

### [✅ VALID] must_fix · security — products/review_hog/backend/receivers.py:126-137,225-231

**Do not trust caller-writable TaskRun output as approval provenance**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `pr_url` comes from `TaskRun.output`, which the task API lets callers replace. All project members can control `SIGNAL_REPORT` tasks through `task_control_q`. These lines forward that value to the approval path. `process_inbox_pr_review` does not verify the task-to-PR binding, a repo-native head, or the expected PostHog Code bot. Stamphog then bypasses its normal trust gates. A project member can point an eligible run at an unrelated PR and cause a real GitHub approval.
- **Suggestion:** Add an attested PR-binding contract to the Tasks facade. Resolve `task_run_id` under `team_id` and require the same signal report, task repository, and a non-internal Signals task. Store the verified PR link only after a signed GitHub webhook matches the repo-native head. Verify the expected bot identity from GitHub. Require this attestation before setting `output["inbox_review"]` in both the initial and webhook paths.
- **Validator:** - **Checked:** I traced both TaskRun output endpoints, the signal-task control rule, both Stamphog entry paths, and the GitHub approval activity.
- **Found:** `task_control_q` gives every team member control of `SIGNAL_REPORT` tasks at `products/tasks/backend/visibility.py:22-46`. Mutating run actions use this rule at `products/tasks/backend/presentation/views/api.py:837-869`.
- **Found:** Both run serializers accept arbitrary `output` JSON at `products/tasks/backend/presentation/serializers.py:167-180` and `products/tasks/backend/presentation/serializers.py:671-674`. The facade protects only `pr_merged`, so callers can replace `pr_url` at `products/tasks/backend/facade/api.py:1764-1788` and `products/tasks/backend/facade/api.py:2038-2044`.
- **Found:** The receiver reads that `pr_url` and queues Stamphog after only task-shape and toggle checks at `products/review_hog/backend/receivers.py:92-138`. It does not compare the PR repository or head with the task.
- **Found:** `process_inbox_pr_review` never loads `task_run_id`. It checks only the repository configuration, open state, and head SHA at `products/stamphog/backend/tasks/tasks.py:1130-1181`. It stores the supplied provenance at `products/stamphog/backend/tasks/tasks.py:1223-1229`.
- **Found:** The webhook path accepts any bot identity at `products/stamphog/backend/tasks/tasks.py:124-127`. Its task lookup returns an `output.pr_url` match before checking the branch at `products/tasks/backend/webhooks.py:29-78`.
- **Found:** Inbox provenance enables `self_driving_review` at `products/stamphog/backend/temporal/activities.py:434-451`. An approved verdict posts a GitHub approval at `products/stamphog/backend/temporal/activities.py:723-755`.
- **Impact:** A team member can bind an eligible run to another PR in a configured repository. If that PR passes review, Stamphog can post an approval without the intended provenance. This approval can satisfy a required-review rule.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1159-1180,1223-1229

**Initial inbox reviews trust a caller-controlled PR URL**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The task only checks that GitHub returns an open PR with a head SHA. It does not validate the supplied task, report, reviewer, repository, author, or head repository. Project members can write `TaskRun.output.pr_url` for team-controlled signal tasks. This path then stamps `inbox_review` and can post a real approval without the normal authorization gates.
- **Suggestion:** Load the exact TaskRun with `team_id` and `task_run_id`. Verify its report and repository. Require a server-attested PR binding, a bot author, a repo-native head, and a current reviewer opt-in before creating the ReviewRun.
- **Validator:** - **Checked:** I traced authenticated task writes through the receiver, Celery task, workflow context, and GitHub approval sink.
- **Found:** The task API permits users to create a task linked to any same-team signal report. `products/tasks/backend/tests/test_api.py:1307-1334` confirms this supported request.
- **Found:** The run output endpoint accepts caller JSON at `products/tasks/backend/presentation/serializers.py:671-674`. Its attestation protects only `pr_merged`, not `pr_url`, at `products/tasks/backend/facade/api.py:1764-1788`.
- **Found:** The receiver requires only a report link, a non-internal task, and the selected reviewer's setting at `products/review_hog/backend/receivers.py:92-139`. It does not bind the URL to the task repository.
- **Found:** `process_inbox_pr_review` never loads `task_run_id` or `signal_report_id`. It checks only the team repository config, open state, and head SHA at `products/stamphog/backend/tasks/tasks.py:1130-1180`.
- **Found:** The task stamps trusted inbox provenance at `products/stamphog/backend/tasks/tasks.py:1223-1229`. That provenance enables self-driving behavior at `products/stamphog/backend/temporal/activities.py:448-451`.
- **Impact:** A team member with `task:write` can target any open PR in a configured repository when the report's acting reviewer opted in. The GitHub App can then approve that PR without the normal author, fork, repository, and write-permission checks.

### [✅ VALID] must_fix · security — products/tasks/backend/facade/api.py:504-508

**The re-review gate treats writable task fields as proof**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `find_task_run` matches `TaskRun.output.pr_url` or `TaskRun.branch`. Authenticated project members can change both fields. The new predicate then only requires a signal report and `internal=False`. A member can bind a qualifying task to an unrelated native bot PR. A later webhook can then bypass the bot, draft, review-mode, and author-permission gates.
- **Suggestion:** Authorize this carve-out from a server-owned PR binding that public TaskRun update endpoints cannot change. Also verify the task is a signal implementation, not any task that has `signal_report_id`. Keep writable output and branch fields out of this authorization decision.
- **Validator:** - **Checked:** I traced task and run write APIs through the facade lookup and webhook carve-out.
- **Found:** `TaskRunUpdateSerializer` accepts both `branch` and `output` at `products/tasks/backend/presentation/serializers.py:167-180`. `update_task_run` persists these caller values at `products/tasks/backend/facade/api.py:2038-2075`.
- **Found:** `find_task_run` treats `output.pr_url` or `branch` plus repository as the run identity at `products/tasks/backend/webhooks.py:29-78`.
- **Found:** `find_signal_implementation_run` then checks only the team, `signal_report_id`, and `internal` at `products/tasks/backend/facade/api.py:504-509`. It does not check `origin_product`, an implementation relationship, or a server-owned binding.
- **Found:** Signal tasks are controllable by every team member at `products/tasks/backend/visibility.py:30-46`. The task API also permits repository and `internal` updates at `products/tasks/backend/presentation/serializers.py:412-461`.
- **Found:** A forged match receives inbox provenance and bypasses the draft, bot, review-mode, and author-permission gates at `products/stamphog/backend/tasks/tasks.py:867-969`.
- **Impact:** A member can bind a qualifying run to an unrelated native bot PR. A later GitHub event can make the App review and approve that PR under another reviewer's opt-in.

### [✅ VALID] must_fix · security — products/tasks/backend/facade/api.py:504-505

**Team scoping occurs after selecting a cross-tenant run**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `find_task_run` searches every tenant and selects one row before this function checks `team_id`. For PR URLs, it prefers the newest nonterminal run. Another tenant can create a newer matching run for a public PR. The correct tenant then receives `None`, which blocks its inbox re-reviews. This permits cross-tenant influence and breaks the facade's stated team-scoping contract.
- **Suggestion:** Pass `team_id` into `find_task_run`. Apply `TaskRun.objects.filter(team_id=team_id)` before every ordering and `.first()` operation. Keep the final team check as a safety check.
- **Validator:** - **Checked:** I traced query ordering, tenant checks, writable run fields, and the webhook consumer.
- **Found:** `find_task_run` queries all teams for `output.pr_url` and selects one row at `products/tasks/backend/webhooks.py:36-57`. It prefers newer non-terminal runs.
- **Found:** `find_signal_implementation_run` applies `team_id` only after that selection at `products/tasks/backend/facade/api.py:504-506`. A wrong-team result causes an immediate `None` instead of another scoped lookup.
- **Found:** An authenticated user can create a local run and set its `pr_url`. The output endpoint persists caller JSON at `products/tasks/backend/facade/api.py:2139-2154`.
- **Found:** The Stamphog consumer treats `None` as an unverified PR at `products/stamphog/backend/tasks/tasks.py:191-207`. It then skips the inbox re-review.
- **Impact:** A tenant can keep a newer non-terminal run for another tenant's public PR URL. Every later webhook can select that run and suppress the correct tenant's re-review. The final check prevents data disclosure, but it does not prevent this cross-tenant denial.

### [✅ VALID] must_fix (validator→should_fix) · bug — products/review_hog/backend/receivers.py:111-126,151-155

**The Stamphog toggle ignores opted-in secondary reviewers**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The receiver selects one acting reviewer before it reads either toggle. It checks only that user's `stamphog_review_inbox_prs` value. The PR requires Stamphog when any assigned reviewer opts in. If the selected reviewer is off and another assignee is on, this path skips the review. The webhook resolver repeats the same rule, so later pushes also skip.
- **Suggestion:** Resolve the ordered assigned reviewer list once. Keep the current canonical choice for ReviewHog. For Stamphog, prefer an opted-in assigned task creator. Otherwise, use the first opted-in assigned reviewer. Reuse that selection in `resolve_stamphog_acting_reviewer`. Add a multi-reviewer test with the first toggle off and the second toggle on.
- **Validator:** - **Checked:** I compared reviewer selection with Inbox assignment, settings copy, both Stamphog trigger paths, and the current tests.
- **Found:** Signals matches every listed reviewer in the Inbox filter at `products/signals/backend/views.py:887-916`. Secondary reviewers therefore receive the same assigned report.
- **Found:** The setting promises reviews for the user's Inbox pull requests at `products/review_hog/backend/api/settings.py:27-32`.
- **Found:** `_resolve_assigned_reviewer` returns only the assigned creator or first resolved reviewer at `products/review_hog/backend/receivers.py:197-207`. The initial path checks only that user's toggle at `products/review_hog/backend/receivers.py:111-138`.
- **Found:** The webhook resolver repeats the single-user check at `products/review_hog/backend/receivers.py:144-156`.
- **Found:** Multi-reviewer tests cover ReviewHog's canonical user at `products/review_hog/backend/tests/test_inbox_trigger.py:205-238`. Stamphog tests use one reviewer at `products/review_hog/backend/tests/test_inbox_trigger.py:313-343` and `products/review_hog/backend/tests/test_inbox_trigger.py:371-387`.
- **Impact:** A secondary assigned reviewer's enabled toggle has no effect when the selected reviewer is disabled. The initial review and later re-reviews both skip.
- **Priority:** `should_fix` fits because this safely omits automation for one multi-reviewer configuration. It does not create an unsafe approval or corrupt data.

### [✅ VALID] must_fix · security — products/tasks/backend/facade/api.py:507-509

**Verify the task is an implementation task**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The facade infers an implementation from `signal_report_id` and `internal=False`. The Tasks API also creates signal-report tasks with `discussion`, `research`, and free-form relationships. Those tasks have the same fields but are not self-driving implementations. A bot PR from one of these tasks receives the trusted carve-out.
- **Suggestion:** Require the unified Signals association with `product="signals"` and `type="implementation"`. Access it through a team-scoped Signals facade. Do not infer task purpose from `signal_report_id`.
- **Validator:** - **Checked:** I traced task relationship creation, the canonical purpose lookup, the facade predicate, and the Stamphog consumer.
- **Found:** Signals derives a task's purpose from the artefact `product` and `type`, not from `Task.signal_report_id`, at `products/signals/backend/task_run_artefacts.py:1-12` and `products/signals/backend/task_run_artefacts.py:86-97`.
- **Found:** The Tasks API supports `discussion`, `research`, and free-form relationships. Tests confirm these tasks have no implementation association at `products/tasks/backend/tests/test_api.py:1336-1386`.
- **Found:** `find_signal_implementation_run` checks only `signal_report_id` and `internal` at `products/tasks/backend/facade/api.py:507-509`. It never checks the Signals relationship.
- **Found:** A matching run receives trusted inbox provenance and bypasses the normal bot, draft, review-mode, and author-permission gates at `products/stamphog/backend/tasks/tasks.py:867-969`.
- **Impact:** A non-implementation task can make its bot PR eligible for a real GitHub approval. This grants the trusted self-driving exception to work that the Signals model does not classify as implementation work.
