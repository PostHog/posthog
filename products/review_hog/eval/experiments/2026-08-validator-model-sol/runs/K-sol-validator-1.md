# Reviewer-quality run — `K-sol-validator-1`

- **Dumped:** 2026-08-25T18:04:59+00:00
- **Report id:** `01a03a06-2d2e-73a7-9e7c-1ab81a3b3651` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1191s (19.9 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 12           | 16         | 14          | 5                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 18s      |
| review wave (perspectives)  | 3m 17s   |
| blind-spot sweep            | 10m 08s  |
| dedup (incl. combine/clean) | 49s      |
| validation                  | 4m 58s   |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 13m 26s — the reviewer-model speed comparison number.
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
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 3          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 1          |
| 1000 | 1     | ?                                              | 0          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | review-hog-blind-spots-general                 | 1          |
| 1000 | 4     | review-hog-blind-spots-general                 | 1          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] must_fix · bug — products/stamphog/backend/tasks/tasks.py:1107-1112,1163-1173

**The queued review does not recheck the reviewer toggle**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The task trusts the toggle result from queue time. A reviewer can disable inbox reviews before Celery executes this task, but the task still starts the review. This breaks the toggle gate.
- **Suggestion:** Resolve the acting reviewer again immediately before run creation. Stop when the resolver is absent or no assigned reviewer remains opted in. Use the returned user ID in the provenance.
- **Validator:** - **Checked:** I traced the queued task from run linkage through reviewer resolution and review creation.
- **Found:** The task calls the current resolver after it verifies the linked run at products/stamphog/backend/tasks/tasks.py:1462-1475.
- **Found:** A missing resolver or no opted-in reviewer stops the task before run creation at products/stamphog/backend/tasks/tasks.py:1476-1478.
- **Found:** Provenance uses the reviewer ID returned by this execution-time check at products/stamphog/backend/tasks/tasks.py:1480-1487.
- **Found:** The regression test confirms that a revoked opt-in creates no run and starts no workflow at products/stamphog/backend/tests/test_tasks.py:1080-1091.
- **Impact:** A reviewer who disables the toggle before Celery executes cannot start the queued review.

### [❌ dismissed] must_fix · security — products/stamphog/backend/tasks/tasks.py:157-196,967-969

**Webhook carve-out can bind writable run fields to any bot PR**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The carve-out accepts any GitHub bot and uses `find_signal_implementation_run` to match the PR. That facade searches fields such as the PR URL, run branch, and output head branches that task users or agents can set. A team member can point those fields at a repo-native bot PR and obtain the carve-out. The code then skips review mode and author write permission checks, so the resulting approval crosses an authorization boundary.
- **Suggestion:** Require the exact GitHub App machine-user login for this instance. Match the GitHub-reported head only against server-protected run state, preferably a pushed commit SHA. Do not use caller-writable PR URLs, branch columns, or output fields as proof that a run created the PR.
- **Validator:** - **Checked:** I traced the webhook carve-out, its run lookup, protected state fields, and security tests.
- **Found:** `_is_self_driving_pr` requires the configured App login and a repository-native head at products/stamphog/backend/tasks/tasks.py:160-181.
- **Found:** `find_signal_implementation_run` matches only `state.self_driving_head_branch` at products/tasks/backend/facade/api.py:694-747.
- **Found:** The API blocks changes to `self_driving_head_branch` at products/tasks/backend/facade/api.py:2181-2184.
- **Found:** The regression test proves that `output.pr_url`, `output.head_branch`, and `TaskRun.branch` cannot establish the link at products/tasks/backend/tests/test_webhooks.py:2000-2014.
- **Impact:** The reported path cannot use another bot or caller-writable run fields to obtain the authorization bypass.

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/review_local.py:321-321

**Truthy non-boolean values bypass security gates**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `bool()` accepts every non-empty string as true. For example, JSON value `"false"` enables the bot-author and draft gate bypass. This field controls an approval boundary, but this entry point does not validate its type.
- **Suggestion:** Require an exact JSON boolean with `context.get("self_driving_review") is True`. Reject invalid field types or treat them as false.
- **Validator:** - **Checked:** I traced the flag from its only producer through JSON serialization to `review_local.py:321`.
- **Found:** `activities.py:468` passes a Python `bool`. `reviewer.py:114` types the parameter as `bool`. `reviewer.py:152` stores it without conversion.
- **Found:** `test_integration.py:1801` confirms that the sandbox receives a JSON boolean. The other path omits the key.
- **Impact:** The value can only be `True`, `False`, or absent. For these values, `bool(value)` and `value is True` produce identical results. The reported bypass is not reachable.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:144-160

**Stamphog ignores opt-ins from non-acting reviewers**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The resolver selects one acting reviewer before it checks the Stamphog toggle. The PR requires a review when any assigned reviewer opts in. A secondary reviewer cannot enable Stamphog unless this function selects that reviewer. The initial trigger and later webhook checks both have this error.
- **Suggestion:** Resolve all assigned reviewers. Load their settings and select one reviewer whose `stamphog_review_inbox_prs` value is true. Keep the existing preferred-reviewer rule among opted-in reviewers for stable attribution. Add a test where the first reviewer opts out and a later reviewer opts in.
- **Validator:** - **Checked:** I traced the initial receiver and the webhook resolver on the PR branch.
- **Found:** `_resolve_assigned_reviewer` selects the creator or first reviewer at `products/review_hog/backend/receivers.py:203-207`.
- **Found:** The initial path checks only that user's setting at `products/review_hog/backend/receivers.py:111-126`. The webhook path repeats this check at `products/review_hog/backend/receivers.py:151-156`.
- **Impact:** A later assigned reviewer can opt in, but Stamphog never reviews the PR. This breaks the stated any-reviewer opt-in behavior.

### [❌ dismissed] should_fix · bug — products/tasks/backend/facade/api.py:501-503

**An unscoped lookup can hide the matching team run**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `find_task_run` searches all teams and returns one matching run. The later team check returns `None` if that run belongs to another team. It does not continue to the valid run for the requested team.
- **Suggestion:** Pass `team_ids=[team_id]` into `find_task_run`. This keeps the lookup scoped before it selects the first result.
- **Validator:** - **Checked:** I traced the current run lookup and its cross-team regression test.
- **Found:** `find_signal_implementation_run` applies `team_id=team_id` before `.first()` at products/tasks/backend/facade/api.py:730-741.
- **Found:** The later team check is defense in depth. It does not select the candidate at products/tasks/backend/facade/api.py:742-743.
- **Found:** The regression test confirms that another team's newer run cannot hide the requested team's run at products/tasks/backend/tests/test_webhooks.py:2045-2061.
- **Impact:** The lookup selects only runs from the requested team, so another team's run cannot shadow the valid result.

### [✅ VALID] must_fix · security — tools/pr-approval-agent/review_pr.py:225,587-590

**Self-driving flag can approve a human-authored draft**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The flag bypasses the draft gate without checking that the author is a bot. A mislabeled human draft can therefore reach approval. This behavior exceeds the stated bot-PR carve-out.
- **Suggestion:** Validate the invariant after loading the PR. Reject or clear `self_driving` when `pr.author_is_bot` is false. Apply the draft exception only when both conditions are true.
- **Validator:** - **Checked:** I traced both paths that set `self_driving=True` and the gates in `review_pr.py:225` and `review_pr.py:587-590`.
- **Found:** The initial Inbox path stamped `inbox_review` for any fetched open PR. It did not verify bot authorship before creating the review run.
- **Found:** `review_pr.py:587-590` then skipped the draft gate based only on `self_driving`. The engine already had `pr.author_is_bot` available.
- **Impact:** A human-authored draft selected by the initial Inbox path could reach a real approval. This is a reachable approval-boundary gap.

### [✅ VALID] should_fix · bug — products/stamphog/backend/temporal/activities.py:448-451

**Do not treat every self-driving review as a draft**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** This flag stays true after the PR becomes ready. A later push still tells the engine that the PR is intentionally a draft. The engine then receives false context and can discount valid review caution.
- **Suggestion:** Keep `self_driving_review` for the bot-author gate. Also pass the current `pr["draft"]` value. Make draft-specific guidance conditional on that value.
- **Validator:** - **Checked:** I traced the fetched GitHub PR state through the sandbox context and the engine prompt.
- **Found:** `fetch_review_context` stores the current GitHub PR object at products/stamphog/backend/temporal/activities.py:228-264.
- **Found:** The invocation derives `self_driving_review` only from persisted inbox provenance at products/stamphog/backend/temporal/activities.py:451-468. It does not use the current `pr["draft"]` value.
- **Found:** A later head change can re-review a ready self-driving PR at products/stamphog/backend/tasks/tasks.py:215-221.
- **Found:** The trusted prompt always says the PR is an intentional draft and ignores draft caution at products/stamphog/packages/pr-approval-agent/reviewer.py:787-806.
- **Impact:** After a ready PR receives a new commit, the reviewer receives false trusted context. This can make unfinished code appear acceptable and change the verdict.

### [❌ dismissed] must_fix · bug — tools/pr-approval-agent/reviewer.py:568-568

**Self-driving reviews still receive bot familiarity signals**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The prompt includes both `familiarity_block` and `self_driving_block`. A bot can have strong repository history, so this adds a false trust signal. The provenance text then says that this signal has no value. This conflict can bias an approval.
- **Suggestion:** Suppress `familiarity_block` when `cl["self_driving"]` is true. Prefer to also skip the familiarity calculation for these runs. Add a test with both fields set.
- **Validator:** - **Checked:** I traced the familiarity data from the hosted context builder through `_attach_familiarity` and `_format_familiarity`.
- **Found:** The server sets `author_pr_numbers` to an empty list for every Inbox review. The same `inbox_review` value enables `self_driving_review`.
- **Found:** `review_local.py:301-303` returns before familiarity calculation when that list is empty. `_format_familiarity` then returns an empty string.
- **Impact:** The two prompt blocks cannot contain conflicting signals through any current call path. The suggested test requires a state that the producer contract prevents.

### [✅ VALID] should_fix · documentation — products/stamphog/AGENTS.md:84-87

**The documented task type contradicts the implementation**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** This section says the carve-out requires a non-internal TaskRun. Signal report tasks use `internal=True`. The facade identifies them through `signal_report_id` and `ai_stage="implementation"`. This incorrect invariant can cause a future change to weaken or break the security gate.
- **Suggestion:** Replace “non-internal” with the exact implemented criteria. State that the task carries a signal report and that the run has `ai_stage="implementation"`. Do not use the `internal` field as an identification rule.
- **Validator:** - **Checked:** I traced the signal implementation task, receiver gate, and task facade.
- **Found:** `products/signals/backend/auto_start.py:393` creates the implementation task with `internal=True`.
- **Found:** `products/review_hog/backend/receivers.py:100-109` identifies the run by `signal_report_id` and `ai_stage="implementation"`.
- **Found:** `products/tasks/backend/facade/api.py:745-748` uses the same criteria and does not test `internal`.
- **Impact:** The documented invariant gives maintainers an incorrect security rule. A later change could reject valid runs or widen the carve-out.

### [❌ dismissed] must_fix · security — products/stamphog/backend/tasks/tasks.py:1128-1176

**Initial review trusts a caller-writable PR URL**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The task treats `pr_url`, `signal_report_id`, and `task_run_id` as trusted provenance. A team member can change `TaskRun.output.pr_url`. The job then fetches any open PR in an enabled repository and marks it as an Inbox review. This bypasses the bot, draft, fork, and author permission gates. The URL parser also accepts `github.com` inside another host because the regular expression is not anchored.
- **Suggestion:** Resolve `task_run_id` again inside this task. Require the same team, signal report, repository, implementation stage, active task, and server-protected branch or commit stamp. Compare the fetched PR head and repository with that protected state. Require the configured PostHog GitHub App bot as the author. Anchor the URL pattern to `^https://github\.com/` and reject trailing path data that is not allowed.
- **Validator:** - **Checked:** I traced URL parsing, GitHub identity checks, run linkage, provenance creation, and the related regression tests.
- **Found:** `_PR_URL_RE` anchors the URL to `https://github.com/` at products/stamphog/backend/tasks/tasks.py:128-139.
- **Found:** The task requires the configured App author and a repository-native head at products/stamphog/backend/tasks/tasks.py:1448-1452.
- **Found:** The task matches the GitHub head to protected run state and requires the supplied run ID at products/stamphog/backend/tasks/tasks.py:1453-1464.
- **Found:** The facade enforces the team, repository, active task, signal report, and implementation stage at products/tasks/backend/facade/api.py:694-748.
- **Found:** The task derives provenance from the verified result instead of the caller arguments at products/stamphog/backend/tasks/tasks.py:1480-1487.
- **Impact:** Changing `TaskRun.output.pr_url` cannot grant Inbox provenance to an arbitrary PR or bypass the review gates.

### [❌ dismissed] must_fix · security — products/tasks/backend/facade/api.py:504-510

**Run lookup does not enforce the self-driving implementation contract**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The facade only requires a signal report and `task.internal == False`. It can return research or repository-selection runs, failed or cancelled runs, and runs for soft-deleted tasks. These records do not prove that an active self-driving implementation created the PR, but callers use the DTO to grant the Inbox security carve-out.
- **Suggestion:** Require the server-stamped implementation stage, exclude failed and cancelled runs, and require `task.deleted == False`. Query with `team_id` before selecting a candidate. Return a DTO only after every self-driving invariant passes.
- **Validator:** - **Checked:** I traced the facade query, protected run fields, production auto-start shape, and rejection tests.
- **Found:** The query filters by `team_id`, protected head branch, repository, and `task__deleted=False` before selection at products/tasks/backend/facade/api.py:728-740.
- **Found:** It excludes failed and cancelled runs at products/tasks/backend/facade/api.py:737.
- **Found:** It requires a signal report and `ai_stage="implementation"` at products/tasks/backend/facade/api.py:744-748.
- **Found:** Tests reject research-stage, cross-team, failed, cancelled, and soft-deleted runs at products/tasks/backend/tests/test_webhooks.py:2016-2043.
- **Impact:** These non-implementation records cannot produce the DTO that grants the Inbox carve-out.

### [✅ VALID] should_fix · bug — products/review_hog/backend/receivers.py:114-138

**Commit-hook failure can skip an independent review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Django runs these commit hooks with `robust=False` by default. An uncaught error in the first hook stops later hooks. The deferred imports occur outside each helper's `try` block, so an import error can escape. The committed save can then report an error, and the Stamphog review can be skipped.
- **Suggestion:** Pass `robust=True` to both `transaction.on_commit` calls. Also move each deferred import inside its helper's `try` block. This keeps both dispatches independent and prevents post-commit errors from reaching the save caller.
- **Validator:** - **Checked:** I traced both commit hooks and both deferred helper imports on the PR branch.
- **Found:** Both `transaction.on_commit` calls use the default `robust=False` at `products/review_hog/backend/receivers.py:116-139`.
- **Found:** `_start_review` imports modules before its error handler at `products/review_hog/backend/receivers.py:251-261`. `_start_stamphog_review` does the same at `products/review_hog/backend/receivers.py:219-224`.
- **Impact:** An import failure from the first callback stops the second callback. It also escapes after a transaction commits. This breaks the stated independent dispatch behavior.

### [❌ dismissed] should_fix — products/review_hog/backend/receivers.py:210-236

**A broker outage permanently loses the initial Stamphog review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The helper logs a queue failure and then returns. No retry or durable record exists. The initial review creates the Inbox provenance that permits later bot and draft reviews. A transient broker failure can therefore leave this PR without any Stamphog review.
- **Suggestion:** Use a durable dispatch mechanism, such as a transactional outbox. At minimum, configure bounded broker publish retries and record a failure metric. Ensure a worker can retry the initial dispatch without another TaskRun save.
- **Validator:** - **Checked:** I traced the Celery publish path, the worker retries, and the later webhook path.
- **Found:** `queue_inbox_pr_review` uses Celery's `.delay()` at `products/stamphog/backend/facade/api.py:147-155`. Celery already retries broker publication three times by default.
- **Found:** A later push rebuilds Inbox provenance from the linked task at `products/stamphog/backend/tasks/tasks.py:144-214`. It does not require the initial review record.
- **Found:** Another TaskRun output save also queues the initial review again, as documented at `products/stamphog/backend/tasks/tasks.py:1123-1128`.
- **Impact:** Permanent loss requires an outage beyond the publish retries and no later output save or qualifying webhook. A transactional outbox does not meet the review bar for this residual case.

### [❌ dismissed] should_fix · performance — products/tasks/backend/facade/api.py:504-504

**Scope the task-run lookup before querying**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** This call omits `team_ids`. `find_task_run` can then scan the full task-run table several times. Each bot PR webhook adds this work to a hot path.
- **Suggestion:** Pass `team_ids=[team_id]` to `find_task_run`. This uses the indexed team field and avoids cross-team scans.
- **Validator:** - **Checked:** I traced the current facade lookup and its database filters.
- **Found:** The facade no longer calls the general `find_task_run` lookup at products/tasks/backend/facade/api.py:694-755.
- **Found:** It filters `TaskRun` by indexed `team_id` before ordering or selecting a result at products/tasks/backend/facade/api.py:730-740.
- **Impact:** This path does not scan task runs across all teams, so the reported hot-path cost is absent.
