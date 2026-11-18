# Reviewer-quality run — `luna-medium-1`

- **Dumped:** 2026-09-17T18:56:49+00:00
- **Report id:** `01a0b0b2-1627-7f19-8868-847bd786701e` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 555s (9.2 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 12           | 14         | 11          | 9                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 16s      |
| review wave (perspectives)  | 3m 42s   |
| blind-spot sweep            | 2m 02s   |
| dedup (incl. combine/clean) | 19s      |
| validation                  | 2m 42s   |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 5m 44s — the reviewer-model speed comparison number.
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
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 1000 | 1     | ?                                              | 0          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | review-hog-blind-spots-general                 | 1          |
| 1000 | 4     | review-hog-blind-spots-general                 | 1          |

## Findings (post-dedup) with validator verdict

### [✅ VALID] must_fix · bug — tools/pr-approval-agent/review_pr.py:225-225,587-590

**Enforce bot and draft invariants for self-driving reviews**

_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** When self_driving is true, the pipeline skips the bot-author refusal and draft prerequisite without checking that the PR is actually bot-authored and still a draft. A human-authored or ready PR with this flag is therefore reviewed under misleading machine-provenance guidance and bypasses both protections.
- **Suggestion:** Keep the carve-out narrow by validating the PR shape before relaxing the gates. Refuse or deny when self_driving is true but author_is_bot is false or draft is false, then apply the existing exceptions only to bot-authored draft PRs. Mirror this validation in review_local.py.
- **Validator:** - **Checked:** Traced the `self_driving` flag from pipeline construction through the bot-author gate, prerequisite gate, hosted context, and final audit output. Checked the webhook and initial Inbox review paths that set the flag.
- **Found:** `review_pr.py:225` refuses bot authors only when `self.self_driving` is false. `review_pr.py:590` skips the draft check whenever `self.self_driving` is true. No check confirms that the PR still has either property.
- **Found:** `products/stamphog/backend/tasks/tasks.py:162` states that a `ready_for_review` event does not invalidate a draft-time verdict, but a queued initial review can still fetch the current PR after its draft state changes. The engine would then review a ready PR under the self-driving provenance.
- **Impact:** The flag is intended for bot-authored draft PRs, but the engine does not enforce that invariant at its trust boundary. A race or malformed server state can bypass two hard gates and produce an approval for a PR shape outside the carve-out. This is a correctness and review-safety defect.

### [✅ VALID] should_fix · bug — products/review_hog/backend/api/settings.py:78-78

**Only report GitHub configurations as Stamphog-connected**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The connected flag reports true for any enabled Stamphog repository with an installation and connector, including configurations whose provider is not GitHub. The initial inbox task only resolves configurations with provider="github", so the UI can enable this switch while every queued review silently does nothing.
- **Suggestion:** Make has_reviewable_repo_config filter provider="github", or validate the provider at the API boundary and reject unsupported providers. The connected flag must describe a configuration that this inbox review path can actually use.
- **Validator:** - **Checked:** Read `ReviewUserSettingsSerializer`, `has_reviewable_repo_config`, the Stamphog repository model, the repository configuration API, and `process_inbox_pr_review`.
- **Found:** `has_reviewable_repo_config` filters only `enabled`, `connected_by_user_id`, and `installation_id` at products/stamphog/backend/facade/api.py:120-125. It does not filter `provider`.
- **Found:** `process_inbox_pr_review` resolves only GitHub configurations at products/stamphog/backend/tasks/tasks.py:1140-1146. It also calls the GitHub client at products/stamphog/backend/tasks/tasks.py:1159.
- **Found:** `StamphogRepoConfig.provider` accepts arbitrary values at products/stamphog/backend/models.py:26-29, and the create serializer does not restrict provider values at products/stamphog/backend/presentation/serializers.py:72-92.
- **Impact:** A connected non-GitHub configuration can make `stamphog_connected` true while the inbox task cannot resolve it. The UI can enable the toggle, but the queued review exits without creating a review. The flag should use the same GitHub capability check as the inbox path.

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/review_local.py:321-321

**Validate the self-driving flag strictly**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** bool(context.get("self_driving_review")) treats any non-empty value as true. For example, a malformed or tampered context containing "false" or 1 bypasses both the bot-author refusal and draft gate. This flag controls a security-sensitive carve-out, so truthiness is not sufficient validation.
- **Suggestion:** Accept the carve-out only when the value is the boolean True, for example `self_driving=context.get("self_driving_review") is True`. Consider rejecting invalid non-boolean values before constructing the pipeline.
- **Validator:** - **Checked:** Traced `self_driving_review` from `products/stamphog/backend/tasks/tasks.py` through `products/stamphog/backend/temporal/activities.py`, `products/stamphog/backend/logic/reviewer.py`, and `review_local.py`.
- **Found:** `activities.py:451` converts the server-side provenance value to a boolean before building the context. `reviewer.py:101` accepts a boolean flag, and `activities.py:1125` writes this server-generated JSON after the sandbox checkout is created.
- **Impact:** A PR author cannot modify this context value through PR contents. The suggested malformed values are not reachable through the production call path. This is defensive validation without a confirmed bug or security impact.

### [✅ VALID] should_fix · bug — tools/pr-approval-agent/reviewer.py:506-506

**suppress human ownership signals for self-driving PRs**

_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The self-driving block says that author organization membership has no signal, but the existing ownership block still includes author-team membership. In the hosted path, `_summarize_ownership()` can therefore tell the model that the machine author is not on the owning team immediately before this block says to ignore that fact. This gives the reviewer contradictory trust guidance and can incorrectly bias the verdict.
- **Suggestion:** When `self_driving` is enabled, omit the author membership lookup and the `author ... is not on any owning team` message from the ownership context. Keep only file ownership and cross-team information, which remain relevant to reviewing the diff.
- **Validator:** - **Checked:** Traced ownership computation in `review_pr.py` and prompt rendering in `reviewer.py` for self-driving runs.
- **Found:** `review_pr.py:631` checks the PR author against owning teams for every classified PR. `review_pr.py:645` adds `author ... is not on any owning team` when the author is not a member. `reviewer.py:562` renders this ownership block before `reviewer.py:568` adds the self-driving guidance.
- **Found:** `reviewer.py:697` states that author organization membership carries no signal for a machine author. The same trusted prompt therefore presents both the membership result and an instruction to ignore it.
- **Impact:** The prompt gives conflicting trust signals for the same fact. The ownership result is advisory, but it can still influence the model's verdict. Self-driving prompts should omit this author-specific lookup and message while retaining file ownership and cross-team information.

### [✅ VALID] should_fix · performance — products/review_hog/backend/receivers.py:120-137

**Avoid queueing duplicate Stamphog jobs on every output save**

_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The receiver queues a new Stamphog Celery task for every save whose output contains `pr_url`. The task deduplicates only after it fetches the PR from GitHub, so repeated TaskRun saves can create many redundant jobs and GitHub API requests for the same pull request. This can add queue load and consume rate-limit budget.
- **Suggestion:** Track the last dispatched PR target or use a durable idempotency key that coalesces pending jobs before the GitHub fetch. At minimum, deduplicate by `task_run_id` and PR URL before publishing another Celery task.
- **Validator:** - **Checked:** Read the TaskRun receiver, its save conditions, the Stamphog queue facade, the Celery task, and the database deduplication path.
- **Found:** `handle_task_run_saved` runs on each eligible save and schedules `_start_stamphog_review` whenever `pr_url` exists at products/review_hog/backend/receivers.py:126-138. The receiver documentation confirms that repeated saves intentionally re-fire at products/review_hog/backend/receivers.py:75-79.
- **Found:** `process_inbox_pr_review` fetches the pull request before it checks for an existing review run at products/stamphog/backend/tasks/tasks.py:1155-1159 and products/stamphog/backend/tasks/tasks.py:1198-1221. The database lock prevents duplicate review rows, but it does not prevent duplicate Celery jobs or GitHub requests.
- **Impact:** Repeated eligible saves can publish multiple jobs for the same TaskRun and pull request. Each job can consume queue capacity and perform a GitHub API fetch before the database deduplication takes effect. This is a real performance and reliability cost on the hot TaskRun save path.

### [✅ VALID] must_fix · security — products/stamphog/AGENTS.md:92-98

**Enforce provenance before stamping inbox reviews**

_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The documentation says that only linkage-verified paths can stamp inbox provenance. The initial `process_inbox_pr_review` task accepts `pr_url`, `signal_report_id`, and `task_run_id` from its caller, then stamps provenance without checking that the task produced this PR or that the PR is bot-authored. A caller or future integration could therefore grant the self-driving exception to an unrelated draft PR.
- **Suggestion:** Validate the fetched PR and task linkage inside the durable task before creating `ReviewRun`. Resolve the implementation run through the tasks facade, compare its run and report IDs with the task arguments, verify the PR belongs to the configured repository, and verify the expected bot author. Keep the documentation claim only after this boundary enforces it.
- **Validator:** - **Checked:** Traced `process_inbox_pr_review`, its only current caller, and `find_signal_implementation_run`.
- **Found:** `process_inbox_pr_review` writes caller-supplied `signal_report_id` and `task_run_id` into `ReviewRun.output` at products/stamphog/backend/tasks/tasks.py:1176-1180 and products/stamphog/backend/tasks/tasks.py:1223-1230. It checks only that the URL maps to an enabled repository config and that the fetched PR is open at products/stamphog/backend/tasks/tasks.py:1130-1153 and products/stamphog/backend/tasks/tasks.py:1158-1169. It does not validate task linkage or bot authorship. The caller checks those values before queueing at products/review_hog/backend/receivers.py:97-105 and products/review_hog/backend/receivers.py:126-138, but the durable task does not repeat the checks. The webhook path already uses `find_signal_implementation_run` for positive linkage at products/stamphog/backend/tasks/tasks.py:184-207, and that facade filters for a matching team, signal report, and non-internal task at products/tasks/backend/facade/api.py:484-509.
- **Impact:** A direct or future caller can cause an unrelated open PR to receive `ReviewRun.output["inbox_review"]`. The hosted server uses that field to enable the bot-author and draft carve-out, so this can grant self-driving review behavior without proven provenance. This violates the documented trust boundary at products/stamphog/AGENTS.md:97-100 and is a security issue.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1110-1174

**must_fix: Revalidate the PR before granting the inbox carve-out**

_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** This task trusts the queued `pr_url` and the caller's earlier checks. It resolves only a configured repository, fetches the referenced PR, and then creates an `inbox_review` run without checking that the PR is the linked self-driving task's PR, that its head repository is native, or that its author is the expected bot. A malformed or incorrect `output.pr_url` can therefore direct this bot-and-draft bypass at a human PR in a configured repository and allow Stamphog to post an approval.
- **Suggestion:** Before creating the run, re-resolve `find_signal_implementation_run` for `team_id`, the configured repository, the fetched PR URL, and its head branch. Also require the fetched PR to be bot-authored and require `head.repo.full_name` to equal the configured repository. Abort unless all checks pass.
- **Validator:** - **Checked:** I traced the receiver in products/review_hog/backend/receivers.py:126-138, the task output writer in products/tasks/backend/facade/api.py:2139-2154, and the initial review task in products/stamphog/backend/tasks/tasks.py:1110-1190.
- **Found:** The receiver queues this task for any saved `output.pr_url` after it checks only the task's signal report and the user's toggle. `set_task_run_output` accepts and persists caller-provided `pr_url` values. The task then selects a configured repository from the URL at products/stamphog/backend/tasks/tasks.py:1130-1153 and fetches the PR at products/stamphog/backend/tasks/tasks.py:1158-1159.
- **Found:** The task does not call `find_signal_implementation_run` after fetching the PR. It also does not check `_is_bot_authored(pr)` or compare `pr["head"]["repo"]["full_name"]` with `repo_config.repository` before stamping `output["inbox_review"]` and creating the run.
- **Impact:** A changed or incorrect `output.pr_url` can select another open PR in a configured repository. The task can stamp that PR as an inbox review, so the self-driving engine can bypass its bot-author and draft gates and post an approval for code that the linked task did not produce. This is a security boundary failure. The task must revalidate the task linkage, bot author, and native head repository before run creation.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:210-236

**Do not silently lose the initial Stamphog review**

_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** If publishing the Celery task fails, this function only logs the exception and drops the review. The initial PR is usually a draft bot PR, so the webhook path will not create a replacement review. The user can therefore enable the toggle and receive no review without any retry or durable record.
- **Suggestion:** Use a durable retry path for the initial queue, such as retrying the task publication through an outbox or recording a pending dispatch that a worker can retry. Keep the save path non-blocking, but ensure a transient broker failure cannot permanently lose the review.
- **Validator:** - **Checked:** Read the TaskRun receiver, the Stamphog facade, the Celery task, the webhook filters, and the queue-failure test.
- **Found:** `_start_stamphog_review` catches every queue exception and only logs it at products/review_hog/backend/receivers.py:224-234. The facade calls Celery `.delay()` directly at products/stamphog/backend/facade/api.py:147-155, so a broker failure can prevent task publication.
- **Found:** The receiver schedules this callback after the database commit at products/review_hog/backend/receivers.py:126-139. No database record or retry mechanism represents a failed dispatch.
- **Found:** The initial task is required for bot-authored draft pull requests because the webhook path skips those reviews at products/stamphog/backend/tasks/tasks.py:865-881. The webhook carve-out handles later deliveries, but it cannot replace an initial queue attempt when no later delivery occurs.
- **Impact:** A transient broker failure can permanently lose the initial review while the settings and TaskRun save both succeed. The existing test confirms that the failure is intentionally swallowed at products/review_hog/backend/tests/test_inbox_trigger.py:358-369, but it does not provide recovery. This is a real reliability defect.

### [✅ VALID] should_fix · bug — products/tasks/backend/facade/api.py:504-505

**Apply team scoping before selecting the task run**

_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** find_task_run selects one matching run across all teams before this function checks run.team_id. If another team has the newest matching PR URL or branch, the function returns None even when the requested team has a valid self-driving run. The team-scoping contract is therefore incorrect and can suppress valid re-reviews.
- **Suggestion:** Pass team_id into the lookup and filter TaskRun by that team before ordering and selecting a row. Apply the same filter to both the PR URL and branch lookup paths.
- **Validator:** - **Checked:** I traced `find_signal_implementation_run` at products/tasks/backend/facade/api.py:484-518 and both lookup paths in `find_task_run` at products/tasks/backend/webhooks.py:29-120.
- **Found:** `find_signal_implementation_run` calls `find_task_run` without `team_id` at products/tasks/backend/facade/api.py:504. `find_task_run` orders and selects a single matching run before the caller checks `run.team_id` at products/tasks/backend/facade/api.py:505.
- **Found:** The PR URL lookup can match runs from any team, and the branch lookup can also match runs from any team when teams use the same repository and branch name. The existing team check only rejects the selected row. It does not continue searching for a matching row in the requested team.
- **Impact:** If another team's newer matching run is selected first, the requested team's valid self-driving run returns `None`. The Stamphog inbox carve-out then skips a legitimate review. This is a real cross-tenant lookup correctness bug, so the lookup must apply `team_id` before ordering and selection.

### [❌ dismissed] should_fix · performance — products/stamphog/backend/tasks/tasks.py:1202-1209

**Add an index for head-based review-run deduplication**

_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The new receiver task runs this locked query on every TaskRun save that carries a PR URL. ReviewRun has no composite index for team_id, pull_request_id, and head_sha, so PostgreSQL must scan and lock the runs for the PR before applying the head and status filters. Review history grows with every push, which makes this path slower over time and increases lock contention during concurrent receiver or webhook deliveries.
- **Suggestion:** Add a migration with a composite index covering the scoped lookup, such as (team_id, pull_request_id, head_sha, created_at). Keep the status filter and ordering in the query, but let the index narrow the candidate rows before select_for_update().
- **Validator:** - **Checked:** I inspected the deduplication query at products/stamphog/backend/tasks/tasks.py:1202-1209 and the `ReviewRun` model definition and indexes in products/stamphog/backend/models.py:140-173.
- **Found:** `pull_request` is a Django `ForeignKey`, so PostgreSQL already has an index on `pull_request_id`. The query filters one `PullRequest` before it checks `head_sha` and status. The code does not scan all review history for every team.
- **Found:** The suggested issue provides no query plan, row-count evidence, or observed latency. A composite index could reduce filtering work for unusually large review histories, but the current code already narrows the query through the foreign-key index.
- **Impact:** This is a speculative optimization. The validation bar requires a performance problem that affects realistic scale, and the current evidence does not show that this query reaches that threshold.

### [✅ VALID] must_fix · bug — products/stamphog/backend/tasks/tasks.py:1202-1209

**must_fix: Serialize receiver deduplication per pull request**

_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** Two receiver tasks for the same PR head can both see no existing run before either transaction creates one. The first task then creates a run. The second task can wait in `_supersede_prior_runs`, supersede the first run, and create another run because it never repeats the deduplication query. This can start duplicate sandbox and LLM reviews for one commit.
- **Suggestion:** Lock the `PullRequest` row with `select_for_update()` immediately after `_upsert_pull_request`, then perform the head deduplication query while holding that lock. Alternatively, add a database uniqueness constraint for the active head identity and handle the resulting `IntegrityError` by restarting or reusing the winning run.
- **Validator:** - **Checked:** I traced `_upsert_pull_request` at products/stamphog/backend/tasks/tasks.py:319-362, the transaction at products/stamphog/backend/tasks/tasks.py:1185-1209, and the subsequent supersession and creation path at products/stamphog/backend/tasks/tasks.py:1222-1237.
- **Found:** `_upsert_pull_request` returns the `PullRequest` row without locking it. The deduplication query locks only rows that already match `head_sha` at products/stamphog/backend/tasks/tasks.py:1202-1209. It cannot lock the absence of a matching `ReviewRun`.
- **Found:** Two concurrent receiver tasks can both observe no matching run. After one task creates a run, the other can acquire the run lock in `_supersede_prior_runs`, mark that run as superseded, and create a second run. The receiver path uses `delivery_id=None`, so the delivery-id uniqueness recovery does not prevent this race.
- **Impact:** One PR head can start multiple review workflows. This can duplicate sandbox and LLM work and can produce conflicting review state for the same commit. Locking the `PullRequest` row before the deduplication query, or enforcing and handling a database-level active-head uniqueness rule, is required for correctness.
