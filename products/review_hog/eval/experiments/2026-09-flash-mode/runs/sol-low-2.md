# Reviewer-quality run — `sol-low-2`

- **Dumped:** 2026-09-17T00:56:00+00:00
- **Report id:** `01a0acc9-5143-7ac1-8aef-2b644cd63e34` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1291s (21.5 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 13           | 14         | 10          | 7                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 17s      |
| review wave (perspectives)  | 10m 30s  |
| blind-spot sweep            | 3m 30s   |
| dedup (incl. combine/clean) | 1m 00s   |
| validation                  | 5m 50s   |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 14m 01s — the reviewer-model speed comparison number.
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
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 3     | ?                                              | 0          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 3    | 3     | ?                                              | 0          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | review-hog-blind-spots-general                 | 1          |
| 1000 | 4     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/review_local.py:321-321

**Reject non-boolean self-driving flags**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The bool conversion enables the privileged carve-out for every non-empty value. For example, "false", "0", or an object becomes true. This bypasses the bot-author and draft gates if the context producer sends a malformed value.
- **Suggestion:** Require the JSON value to be the boolean true. Use `context.get("self_driving_review") is True`. Reject other value types or keep the carve-out disabled.
- **Validator:** - **Checked:** I traced the flag from `ReviewRun.output` through `products/stamphog/backend/temporal/activities.py:451` and `products/stamphog/backend/logic/reviewer.py:101-131`.
- **Found:** The hosted server converts trusted inbox provenance to a boolean before it creates the context. The typed `self_driving_review` parameter then writes that boolean to JSON.
- **Found:** The sandbox receives the server-created context file. Pull request content does not control this field.
- **Impact:** Values such as `"false"`, `"0"`, or an object cannot reach `tools/pr-approval-agent/review_local.py:321` through the production path. The proposed check only guards malformed manual input, so the issue does not meet the review bar.

### [❌ dismissed] should_fix — products/review_hog/backend/receivers.py:222-222

**The deferred import can still fail the save request**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The deferred import runs before the try block. An import error escapes the on-commit callback. This can return an error after the TaskRun transaction already committed.
- **Suggestion:** Move the import into the try block. Also register the callback with robust error handling so no dispatch failure escapes the save path.
- **Validator:** - **Checked:** I traced both production writers of `TaskRun.output` and the receiver callback.
- **Found:** `set_task_run_output` saves in autocommit mode at `products/tasks/backend/facade/api.py:2154`. Django runs the callback immediately. The outer handler catches the import error at `products/review_hog/backend/receivers.py:75-143`.
- **Found:** The webhook writer uses `transaction.atomic()` at `products/tasks/backend/webhooks.py:286-292`. Its enclosing `try` catches callback errors at `products/tasks/backend/webhooks.py:284-297`.
- **Impact:** The reported error does not escape either production save path. An unhandled error requires a new caller with an outer transaction and no error guard. That case is speculative.

### [✅ VALID] should_fix · bug — products/stamphog/backend/facade/api.py:149-156

**Broker failures can permanently lose the initial review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** This dispatch is the only path for the initial draft review. The caller catches broker errors and only writes a log. A broker outage can therefore lose the review permanently. GitHub does not redeliver this receiver event.
- **Suggestion:** Persist a dispatch record in the same transaction as the TaskRun update. Send it through an outbox worker with retries. At minimum, add a scheduled recovery task that finds eligible PRs without a ReviewRun and queues them again.
- **Validator:** - **Checked:** I traced the TaskRun receiver, the facade dispatch, and the Celery task retry paths.
- **Found:** `handle_task_run_saved` schedules one broker publish after commit at `products/review_hog/backend/receivers.py:126-139`.
- **Found:** `_start_stamphog_review` catches every publish error and only logs it at `products/review_hog/backend/receivers.py:224-234`.
- **Found:** `queue_inbox_pr_review` writes no durable state before `.delay()` at `products/stamphog/backend/facade/api.py:149-155`.
- **Found:** The retries at `products/stamphog/backend/tasks/tasks.py:1109-1237` apply only after the broker accepts the task.
- **Impact:** A broker publish failure leaves no task or `ReviewRun`. A later TaskRun save can retry the dispatch, but no later save is guaranteed. The initial review can remain missing.

### [✅ VALID] must_fix · security — tools/pr-approval-agent/review_pr.py:587-590

**Limit the draft bypass to bot-authored PRs**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The self-driving flag bypasses the draft gate for every author. A linked context for a human-authored draft can therefore reach review and receive an approval. The initial Inbox review path does not verify that GitHub reports a bot author before it sets this flag.
- **Suggestion:** Fail closed when `self_driving` is true but `pr.author_is_bot` is false. Also require the context producer to verify the bot author and repository-native head before it creates the review run.
- **Validator:** - **Checked:** I traced both paths that create `ReviewRun.output["inbox_review"]` and the engine gates that consume it.
- **Found:** The webhook path requires a bot author and a repository-native head at `products/stamphog/backend/tasks/tasks.py:169-178`.
- **Found:** The initial path checks only the PR state and head SHA at `products/stamphog/backend/tasks/tasks.py:1166-1174`. It does not check the author type or head repository before it stamps provenance.
- **Found:** `tools/pr-approval-agent/review_pr.py:590` skips the draft gate whenever `self_driving` is true. It does not also require `pr.author_is_bot`.
- **Impact:** A linked task that supplies a human-authored draft PR can create a privileged review run. That run can produce an approval before the author marks the PR ready.

### [✅ VALID] must_fix · security — products/tasks/backend/facade/api.py:503-506

**Team filtering happens after a global task-run lookup**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `find_task_run` searches all teams and returns one matching row. The facade checks `run.team_id` only after that global query selects a row. Another team can create a newer run with the same public PR URL or repository and branch. That row can hide the correct run and disable reviews for the owning team. This violates the facade's stated team-scoping contract and permits cross-tenant interference.
- **Suggestion:** Apply `team_id` inside every `TaskRun` query before ordering and selecting a row. Add `team_id` to `find_task_run`, or implement a team-scoped lookup in this facade. Keep the final team assertion as a defense-in-depth check.
- **Validator:** - **Checked:** I traced `find_signal_implementation_run`, `find_task_run`, and the Stamphog caller.
- **Found:** `find_signal_implementation_run` calls the global lookup before it checks `team_id` at `products/tasks/backend/facade/api.py:504-506`.
- **Found:** The PR lookup selects across all teams at `products/tasks/backend/webhooks.py:41-56`. It prefers the newest non-terminal matching run.
- **Found:** The branch lookup also selects across all teams at `products/tasks/backend/webhooks.py:68-75`. `TaskRun.Meta.ordering` prefers the newest run at `products/tasks/backend/models.py:1144-1146`.
- **Found:** Stamphog treats a rejected lookup as an unverified PR at `products/stamphog/backend/tasks/tasks.py:191-200`.
- **Impact:** A matching run from another team can win the global lookup. The later team check then rejects it without searching for the correct team's run. This lets one tenant stop another tenant's eligible re-review.

### [❌ dismissed] must_fix — products/review_hog/backend/receivers.py:111-126,150-156

**Only one assigned reviewer can enable Stamphog**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The PR requires a review when at least one assigned user enables the toggle. This code selects one acting reviewer before it checks the toggle. It skips the review when that user opts out, even if another assigned reviewer opts in. The webhook resolver repeats the same behavior, so later commits also skip review.
- **Suggestion:** Resolve all assigned reviewers and select an opted-in user. Preserve the current creator-first ordering among users who enabled `stamphog_review_inbox_prs`. Use the same selection for the initial receiver and the webhook resolver. Add a case where the first reviewer opts out and a second reviewer opts in.
- **Validator:** - **Checked:** I traced the acting-reviewer rules through the receiver, tests, model contract, Stamphog facade, and product decisions.
- **Found:** The task creator is canonical when assigned. Otherwise, the first resolved reviewer is canonical at `products/review_hog/backend/receivers.py:164-172`.
- **Found:** The locked design states that a non-acting reviewer must not replace the canonical reviewer at `products/review_hog/DECISIONS.md:2674-2681`.
- **Found:** Both inbox toggles belong to the same acting reviewer at `products/review_hog/backend/receivers.py:17-20`. The Stamphog facade requires this reviewer at `products/stamphog/backend/facade/api.py:128-140`.
- **Found:** The test at `products/review_hog/backend/tests/test_inbox_trigger.py:227-238` protects the canonical-reviewer rule when another assigned reviewer opts in.
- **Impact:** Selecting any opted-in reviewer would change the documented ownership rule. It could run a review under a secondary reviewer's preference when the canonical reviewer opted out.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1143-1176

**Initial review does not verify self-driving provenance**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The task trusts all provenance arguments from the earlier receiver. It only checks the repository config and the PR state. It does not verify `task_run_id`, `signal_report_id`, the task repository, the current reviewer toggle, bot authorship, or a repository-native head. It then marks the run as an inbox review. This mark bypasses the normal draft, bot, review-mode, and author-permission gates. A wrong or stale `TaskRun.output.pr_url` can therefore cause a real approval on a PR that is not a self-driving Inbox PR.
- **Suggestion:** Load the exact task run through a team-scoped tasks facade before creating the review. Verify its signal report, repository, and recorded PR URL against the fetched PR. Also verify that the fetched PR is bot-authored and has a repository-native head. Resolve the acting reviewer and their current toggle again. Return without creating a run if any check fails.
- **Validator:** - **Checked:** I traced the receiver, queued task, webhook carve-out, and sandbox gate.
- **Found:** The receiver reads `pr_url` from user-writable `TaskRun.output` at `products/review_hog/backend/receivers.py:92-94`.
- **Found:** The receiver checks the task shape and toggle at `products/review_hog/backend/receivers.py:97-126`. It does not verify that the URL identifies the task's PR.
- **Found:** `process_inbox_pr_review` validates only the repository config, open state, and head SHA at `products/stamphog/backend/tasks/tasks.py:1130-1174`.
- **Found:** The task copies the supplied identifiers into trusted provenance at `products/stamphog/backend/tasks/tasks.py:1176-1180`. It does not load `task_run_id` or resolve the current reviewer.
- **Found:** The webhook path performs the missing bot, native-head, task-link, team, and toggle checks at `products/stamphog/backend/tasks/tasks.py:167-207`.
- **Found:** The sandbox enables the self-driving bypass from any stored `inbox_review` value at `products/stamphog/backend/temporal/activities.py:448-451`.
- **Impact:** A wrong PR URL can mark an unrelated open PR as self-driving. That mark can bypass the normal approval gates and produce a GitHub approval without verified Inbox provenance.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:225-235

**Queue failures permanently lose the initial review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The callback catches a broker publish failure and only writes a log. The TaskRun might not save again. The initial Stamphog review is then permanently lost.
- **Suggestion:** Use a durable handoff that retries after broker failures. For example, persist an outbox record in the TaskRun transaction and let a retrying worker publish it.
- **Validator:** - **Checked:** I traced the handoff from the `TaskRun` save through the Celery task and its retry policy.
- **Found:** `_start_stamphog_review` catches every publish error and only logs it at `products/review_hog/backend/receivers.py:225-235`. It stores no retry state.
- **Found:** The output API performs one save at `products/tasks/backend/facade/api.py:2139-2154`. No later save is required.
- **Found:** `process_inbox_pr_review` retries downstream failures at `products/stamphog/backend/tasks/tasks.py:1111-1160`. These retries start only after the broker accepts the task.
- **Impact:** A broker outage can drop the only initial-review trigger. The saved PR then has no Stamphog verdict for Inbox triage.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:126-138

**Recheck the opt-in before the queued review runs**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The receiver checks the toggle only before it queues the Celery task. The task can run much later. If the user turns the toggle off during that delay, Stamphog can still review and approve the pull request.
- **Suggestion:** Reload the TaskRun in process_inbox_pr_review. Resolve the assigned reviewers and check their current stamphog_review_inbox_prs values before creating a ReviewRun. Stop the task when no assigned reviewer is still opted in.
- **Validator:** - **Checked:** I traced the toggle from the receiver through the queued task and the GitHub review path.
- **Found:** The receiver reads the toggle before dispatch at `products/review_hog/backend/receivers.py:126-138`.
- **Found:** The Celery task trusts the supplied `acting_user_id`. It does not read the current toggle before creating a `ReviewRun` at `products/stamphog/backend/tasks/tasks.py:1110-1234`.
- **Found:** GitHub rate-limit retries can delay the task by at least 60 seconds at `products/stamphog/backend/tasks/tasks.py:1158-1165`.
- **Found:** The webhook path rechecks the current toggle at `products/review_hog/backend/receivers.py:144-156`. The initial task has no equivalent check.
- **Impact:** A user can opt out before a delayed task starts, but the task can still create a review and post an approval. This bypasses the per-user gate for an external write.

### [✅ VALID] must_fix · security — products/tasks/backend/facade/api.py:499-506

**Branch fallback can identify an unrelated PR as self-driving**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The exact PR URL lookup can fail and then `find_task_run` uses the branch lookup. That lookup can return an old run or a run that already links to another PR. Branches can be reused, and one branch can target different base branches. The caller then treats the bot PR as self-driving and bypasses the normal review gates. Stamphog can post an approval for a PR that the signals run did not create.
- **Suggestion:** Use a dedicated team-scoped query for this security decision. Match the exact PR URL first. Use the branch fallback only for an active run whose output has no PR URL. Also filter the signal-report and non-internal task shape in that query.
- **Validator:** - **Checked:** I traced the exact URL lookup, branch fallback, facade filters, and Stamphog caller.
- **Found:** `find_task_run` falls back to the branch when the exact URL has no match at `products/tasks/backend/webhooks.py:36-64`.
- **Found:** The plain branch query accepts terminal runs and runs with another `output.pr_url` at `products/tasks/backend/webhooks.py:68-75`.
- **Found:** `TaskRun.Meta.ordering` selects the newest matching run at `products/tasks/backend/models.py:1144-1146`. It does not prove that the run created this PR.
- **Found:** The facade checks only the selected run's team and task shape at `products/tasks/backend/facade/api.py:504-509`.
- **Found:** Stamphog uses this result to grant the self-driving carve-out at `products/stamphog/backend/tasks/tasks.py:191-215`.
- **Impact:** A reused branch can link a new PR to an old signals run. Stamphog can then bypass the normal gates and approve a PR that the run did not create.
