# Reviewer-quality run — `V2-glm-validator`

- **Dumped:** 2026-09-01T01:26:05+00:00
- **Report id:** `01a05a6d-ea01-7572-a284-307d709d9352` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 2411s (40.2 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 12           | 29         | 22          | 7                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 18s      |
| review wave (perspectives)  | 17m 33s  |
| blind-spot sweep            | 9m 15s   |
| dedup (incl. combine/clean) | 3m 33s   |
| validation                  | 9m 16s   |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 26m 48s — the reviewer-model speed comparison number.
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
| 2    | 2     | review-hog-perspective-logic-correctness       | 4          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 2          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 6          |
| 1000 | 1     | review-hog-blind-spots-general                 | 2          |
| 1000 | 2     | review-hog-blind-spots-general                 | 3          |
| 1000 | 3     | review-hog-blind-spots-general                 | 1          |
| 1000 | 4     | review-hog-blind-spots-general                 | 2          |

## Findings (post-dedup) with validator verdict

### [— no-verdict] should_fix — products/stamphog/backend/facade/api.py:149-155

**A broker outage permanently drops the initial review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The facade publishes after the TaskRun transaction commits. `_start_stamphog_review` catches publish failures and only writes a log. No database record or scheduled sweep retries this handoff.
- **Suggestion:** Persist an idempotent outbox record with the TaskRun update. Add a scheduled sweep that republishes pending records by ID.

### [— no-verdict] should_fix — products/stamphog/backend/facade/inbox_hooks.py:20-22

**The toggle gate checks one assignee instead of any assignee**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The resolver contract checks the selected acting reviewer only. The webhook gate treats `None` as a global opt-out. If the first assignee is off and a later assignee is on, no review runs. This conflicts with the stated rule that any assigned user's opt-in enables Stamphog.
- **Suggestion:** Resolve all assigned organization members before applying the toggle. Prefer the task creator when that assigned user opted in. Otherwise, select the first opted-in assignee. Use this rule for both the initial receiver and webhook resolver.

### [✅ VALID] should_fix (validator→consider) · best_practice — products/review_hog/backend/receivers.py:225-234

**A broker failure permanently drops the initial review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The handler catches every broker publish failure after the TaskRun output commits. It only writes a log. No durable record remains, and the TaskRun might never save again. Celery retries cannot run because the broker never accepted the task. The pull request then misses its initial Stamphog review permanently.
- **Suggestion:** Persist an idempotent pending-dispatch row before calling the broker. Use the task run and PR URL as its stable key. Publish by row ID after commit. Add a periodic worker that retries pending rows, like the existing EmailOutboxMessage flow. Mark the row sent only after the broker accepts the task.
- **Validator:** - **Checked:** `queue_inbox_pr_review` (products/stamphog/backend/facade/api.py:149) calls `process_inbox_pr_review.delay()`; the publish happens inside `_start_stamphog_review`'s try/except (products/review_hog/backend/receivers.py:224-234), which logs and returns. I traced recovery paths: the TaskRun receiver re-fires on every later output save, and `process_inbox_pr_review` dedupes on the PR's current head so a retried dispatch still reviews (products/stamphog/backend/tasks/tasks.py:1180-1204). I also read the webhook re-review path: `_inbox_rereview_carve_out` handles synchronize / reopen / base retarget (products/stamphog/backend/tasks/tasks.py:144-215).
- **Found:** The claim "never reviews again" is overstated. A later push re-reviews through the webhook carve-out, and any later TaskRun output save re-fires the dispatch with head-keyed dedupe. Celery's publish retry policy also absorbs short broker blips before this code even sees an error. But the initial draft-time review — the feature's stated purpose (tasks.py:1111-1115: "the verdict must land while the PR is still a draft") — is lost with only a log line when a sustained broker outage coincides with the dispatch, and no later push is guaranteed on a draft bot PR.
- **Found:** The same loss mode already exists for the sibling dispatch in this file: `_start_review` swallows a Temporal failure the same way (products/review_hog/backend/receivers.py:261-273), by documented design ("the broker being down must never surface into the saver", receivers.py:213). Fixing only the stamphog leg leaves the primary review leg identical; fixing both means a durable outbox spanning two products.
- **Impact:** A sustained broker outage during the narrow dispatch window silently skips the initial stamphog review. The feature degrades to its pre-PR state for that PR; no user data is lost, and later pushes still get reviewed. The proposed outbox-plus-worker is a cross-product infrastructure addition for a rare event on an opt-in experimental toggle, and it would need to cover the identical Temporal leg to be consistent.
- **Priority:** The concern is real and worth the author knowing, but the probability is low, recovery paths exist, the pattern matches the file's deliberate fire-and-forget design, and the proposed remedy is heavyweight. Downgrading from should_fix to consider.

### [— no-verdict] must_fix — products/stamphog/backend/tasks/tasks.py:873-879

**Carve-out failures block stale approval dismissal**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The exception path retries before the code reaches `_retract_stale_approvals_on_skip`. Celery drops the delivery after its retries fail. A previous approval can then remain active after unreviewed commits arrive. A partial database outage can cause this state.
- **Suggestion:** Dismiss old approvals before the optional carve-out lookup. Alternatively, perform the idempotent dismissal in this exception handler before calling `retry`.

### [— no-verdict] should_fix — products/stamphog/backend/tasks/tasks.py:1109-1112

**A worker crash can lose the initial review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Celery uses early acknowledgement because this task does not set `acks_late`. A worker crash before row creation loses the initial review. A crash after commit can leave a queued run without a workflow.
- **Suggestion:** Set `acks_late=True` and `reject_on_worker_lost=True` on the task. The existing head-based dedupe makes redelivery safe.

### [— no-verdict] consider — products/stamphog/backend/temporal/activities.py:173-176

**Self-driving attribution misses failure paths**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The new property only reaches events emitted inside the sandbox. `stamphog_review_failed` omits it. Failures before sandbox creation produce only logs. Dashboards cannot compare failure rates for inbox reviews and normal reviews.
- **Suggestion:** Add `stamphog_self_driving_review` to the hosted failure event from `run.output`. Emit an outcome event when the initial task fails before creating a `ReviewRun`.

### [— no-verdict] should_fix — products/stamphog/backend/tasks/tasks.py:191-205

**Child environments fail the team identity checks**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** StamphogRepoConfig stores the canonical parent team ID. TaskRun stores the selected child environment ID. The facade rejects these raw IDs as unequal. This caller repeats that check and sends the parent ID to a resolver that queries child-scoped signal artefacts. Later pushes from child environments therefore lose the inbox carve-out and skip review.
- **Suggestion:** Compare canonical IDs for ownership, but preserve the TaskRun team ID for signal artefact lookup. Return both IDs in SignalImplementationRunDTO. Use the canonical ID for repo checks and the raw ID for the resolver. Add a child-environment regression test.

### [❌ dismissed] must_fix · security — products/stamphog/AGENTS.md:84-99

**The carve-out trusts caller-controlled PR linkage**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** These lines say that both trigger paths verify the link between the PR and the TaskRun. The implementation does not provide that guarantee. `process_inbox_pr_review` trusts supplied identifiers and stamps `inbox_review` after finding an enabled repository and an open PR. The webhook path also accepts `TaskRun.output.pr_url` through `find_signal_implementation_run`. That field is caller-writable, and every team member can control signal-report tasks. A caller can point a qualifying run at another accessible PR. The self-driving flag then bypasses several approval gates without the documented linkage.
- **Suggestion:** Store the PR link in a server-owned, webhook-attested field, and make both paths use it. Load `task_run_id` through the Tasks facade. Verify the team, signal report, repository, PR URL, and repo-native head before setting `inbox_review`. Do not trust provenance fields supplied to the Celery task.
- **Validator:** - **Checked:** Traced both trigger paths end to end. Receiver leg: `products/review_hog/backend/receivers.py:112-140` resolves the acting reviewer via `_resolve_assigned_reviewer`, loads `ReviewUserSettings`, and only then calls `queue_inbox_pr_review` — there is no endpoint or payload field that lets a caller reach it with chosen identifiers. Webhook leg: `products/stamphog/backend/tasks/tasks.py:144-215` (`_inbox_rereview_carve_out`) takes `pr` from the HMAC-verified GitHub delivery and feeds `pr.get("html_url")` to `find_signal_implementation_run` (`products/tasks/backend/facade/api.py:484-516`), which re-checks `run.team_id != team_id → None`, `task.signal_report_id is None → None`, `task.internal → None`. The `pr_url` in `TaskRun.output` is written by the agent server or by the webhook backstop (`products/tasks/backend/webhooks.py:29-100`), never from user input, and `find_task_run` matches on it as a query key, not a trust anchor.
- **Found:** The claim's core premises do not hold. (1) 'Caller-controlled PR linkage': the `pr_url` reaching `find_signal_implementation_run` originates from a signature-verified GitHub webhook payload or server-observed agent state; a team member can create tasks, but a task only becomes a signal run with `signal_report_id` set and `internal=False`, and the carve-out still requires the full chain — synced+enabled config for that exact repository, team match, a registered resolver, and an opted-in acting reviewer. (2) 'Bypasses several approval gates': the carve-out relaxes exactly two gates (bot-author refusal, draft prerequisite) by documented design (`products/stamphog/AGENTS.md:80-113`, 'the one exception'), and its own gate set — team scope, non-internal task, signal report, enabled config, toggle opt-in — is applied on every entry path, including the re-review leg. The 'team members can control signal-report tasks' framing describes intended product behavior, not an escalation primitive: a crafted task cannot be steered at another team's run because the team scope is re-verified inside the facade.
- **Impact:** No attacker-reachable path exists where the identifiers passed to `process_inbox_pr_review` are caller-chosen, so no approval gate is bypassed and no unreviewed PR can be approved. The remaining kernel — 'the Celery task's kwargs are raw identifiers, so a future caller could pass unattested values' — is intra-app function-contract guidance already stated in the docstrings (`queue_inbox_pr_review`'s and `process_inbox_pr_review`'s docstrings both state the caller must have resolved the reviewer and checked the toggle), and it is exactly the 'defensive-coding paranoia' class the validation criteria exclude. Nothing here is user-affecting or a real correctness/security defect.

### [❌ dismissed] should_fix — products/stamphog/README.md:14-14

**The toggle gate ignores other opted-in assignees**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The PR promises a review when any assigned reviewer enables the toggle. This text documents a single acting reviewer instead. `_resolve_assigned_reviewer` selects the assigned task creator or the first resolved reviewer. Callers check only that user's toggle. Another assigned reviewer can enable the toggle and still receive no initial or follow-up review.
- **Suggestion:** Select from all opted-in assigned reviewers. Prefer an opted-in task creator, then the first opted-in assignee for deterministic behavior. Use the same selection rule for initial and webhook reviews, and document that rule here.
- **Validator:** - **Checked:** The claimed gap against the actual selection code. `products/review_hog/backend/receivers.py:159-207` (`_resolve_assigned_reviewer`) resolves the report's latest `suggested_reviewers` artefact, maps GitHub logins to org users via `resolve_org_github_login_to_users`, and picks the acting reviewer deterministically: the task's own `created_by` user **if they are among the resolved reviewers**, else the **first** resolved reviewer (`receivers.py:206`). Both consumers — the inbox trigger (`receivers.py:111-125`) and the stamphog re-review hook (`resolve_stamphog_acting_reviewer`, `receivers.py:144-156`) — then check exactly that one user's toggle (`review_inbox_prs` / `stamphog_review_inbox_prs`, `receivers.py:115` and `:154`).
- **Found:** The premise is a documented design decision, not an omission. The resolver's docstring (`receivers.py:160-173`) records the maintainer decision of 2026-07-02/03 that a **single canonical acting reviewer** governs each run — the task's own user when assigned, otherwise the first resolved reviewer — so that exactly one person's settings (toggle, perspectives, validator, urgency threshold) drive the review. This is deliberate: multiple independently-trusted assignees each gating the same run would make review behavior nondeterministic (whose settings apply?) and would let a user who never requested the implementation silently cause or veto a review of someone else's task. The claim's scenario — a secondary assignee enables the toggle and 'receives no review' — misdescribes the system: the review still runs whenever the _acting_ reviewer opts in; a non-acting assignee's toggle is simply not an input, which is the intended attribution model, and their own review activity (comments, their own tasks) is unaffected.
- **Impact:** No user-facing defect, no gate bypassed, no lost review: the toggle gate is exercised against the one reviewer whose preferences are defined to govern, and every other assignee's opt-in continues to work for the tasks they themselves create. Adopting the suggestion would override a documented maintainer decision and introduce the nondeterminism the rule exists to prevent. At most this is a product-design discussion to raise with the review_hog owners, not a change this PR must make.

### [— no-verdict] must_fix — products/stamphog/backend/tasks/tasks.py:1130-1181,1223-1229

**Initial inbox review trusts caller-controlled provenance**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** TaskRun.output.pr_url is caller-writable, but this worker never loads task_run_id or signal_report_id. It only checks that the team configured the URL's repository. It does not check the task repository, head repository, branch, or exact bot author. It also trusts acting_user_id and the earlier toggle result. The worker then stamps inbox_review, which bypasses the bot and draft gates. A task writer can target an unrelated open PR and cause a real approval.
- **Suggestion:** Load the exact TaskRun by team and ID through the tasks facade. Verify its signal report, non-internal task, repository, and server-owned PR binding. Require a repo-native head and the expected app bot author. Re-resolve the current reviewer and toggle. Only then create inbox_review. Use the existing strict GitHub URL parser instead of the regex search.

### [— no-verdict] must_fix — products/tasks/backend/facade/api.py:484-515

**Webhook carve-out uses writable fields as security evidence**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** find_task_run treats TaskRun.output.pr_url and TaskRun.branch as proof that a run produced the PR. Public TaskRun update routes let callers change both fields. Signal-report tasks are team-controllable. A caller can point a linked run at an unrelated repo-native bot PR. The next webhook marks that PR self-driving and skips the bot, review-mode, and author-permission gates.
- **Suggestion:** Use a server-owned PR binding that clients cannot patch. Create it through an authenticated task-agent callback or a server-generated per-run branch. Match that binding by team, repository, PR number, and head before returning the DTO. Do not use output.pr_url or TaskRun.branch as authorization evidence. Add public-update regression tests for both fields.

### [✅ VALID] must_fix (validator→should_fix) · bug — products/review_hog/backend/receivers.py:111-126,144-156

**Only one reviewer controls the any-reviewer toggle**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `_resolve_assigned_reviewer` returns the assigned task creator or the first resolved reviewer. Both new Stamphog paths check only that user's setting. If the first reviewer opted out and a later reviewer opted in, the initial review does not run. A later webhook also reports an opt-out and can dismiss the existing approval. This conflicts with the required behavior that any assigned reviewer can enable Stamphog.
- **Suggestion:** Resolve the ordered assigned reviewer list once. Keep the current single-reviewer rule for ReviewHog. For Stamphog, select the assigned task creator when enabled. Otherwise select the first assigned reviewer with `stamphog_review_inbox_prs` enabled. Reuse this selection in the webhook resolver. Add tests where only a later reviewer opted in and where all reviewers opted out.
- **Validator:** - **Checked:** I read the PR's `_resolve_assigned_reviewer` (products/review_hog/backend/receivers.py:159-207): it returns a single user — the task creator when they are among the resolved reviewers, otherwise the first resolved reviewer. I then traced both consumers: the trigger gates both toggles on that one user's settings (receivers.py:114-138), and the webhook resolver `resolve_stamphog_acting_reviewer` (receivers.py:144-156) checks only that same user's `stamphog_review_inbox_prs`. I traced what a `None` return does downstream in the webhook leg: `_inbox_rereview_carve_out` maps it to `opted_out=True` (products/stamphog/backend/tasks/tasks.py:205-207), which routes the head-changing push to the dismissal path with `_INBOX_OPT_OUT_DISMISS_MESSAGE` (tasks.py:880-899).
- **Found:** The PR's own description states the gate as "at least one of the assigned users has `stamphog_review_inbox_prs` enabled", but the implementation checks exactly one reviewer. So a report whose first reviewer opted out and a later reviewer opted in gets no initial review, and once a review exists, a canonical-reviewer opt-out dismisses its approval while another assignee is still opted in. I also compared against `origin/master`, where this exact fix already exists: `_pick_stamphog_reviewer` selects any opted-in reviewer (preferred-else-first) and its docstring states the rationale — "narrowing to one reviewer would drop reviews the other assignees asked for" — while `resolve_stamphog_acting_reviewer` there keeps the webhook leg gate-consistent with it.
- **Found:** The trigger and webhook legs are at least mutually consistent in this PR (both use the same single-reviewer rule), so no path grants an approval nobody opted in for. The failure direction is conservative: suppressed reviews and dismissed approvals, never an unreviewed approval surviving.
- **Impact:** A real, reachable behavior mismatch with the feature's stated intent whenever two assigned reviewers disagree on the toggle — the multi-reviewer case is the normal case for inbox reports. Not merge-blocking though: it is behind a per-user opt-in experiment, no data loss or security exposure, and the divergence errs on the safe side. The suggested fix (ordered list, any-opted-in selection shared by both legs) is small and matches what master already ships.
- **Priority:** Downgrading from must_fix to should_fix: genuine correctness gap against the stated behavior, but conservative in effect and feature-flagged.

### [— no-verdict] should_fix — products/tasks/backend/facade/api.py:504-509

**Qualification filters run after an unrelated row can win**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `find_task_run` selects one row before this facade checks `team_id`, `signal_report_id`, and `internal`. Duplicate PR URLs and branches can exist across teams or task types. An unrelated row can win the selection. The facade then returns `None`, even when a qualifying signal run exists.
- **Suggestion:** Apply the team and signal-task filters before ordering and selecting. Preserve the active-run preference for URL matches. Define a deterministic order for branch matches.

### [❌ dismissed] must_fix · code_quality — tools/pr-approval-agent/reviewer.py:568,683-701

**Self-driving instructions conflict with the system prompt**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The system prompt says every bot author needs human review. It also treats the `stamphog` label as a confidence signal. This flow has a bot author and no label. `_format_self_driving()` adds its exception only to the lower-priority user prompt. The model can therefore refuse every intended review or use a confidence signal that does not exist.
- **Suggestion:** Add a conditional self-driving section to the system prompt. Define verified self-driving provenance as the bot-author exception. State that these runs receive no label confidence. Keep the existing system prompt unchanged for other runs. Test the composed system and user prompts in both modes.
- **Validator:** - **Checked:** reviewer.py:568,586,692-702 (where \_format_self_driving() output lands and what it states), reviewer.py:593 (the untrusted-content marker), review_pr.py:209,225,590 (the self_driving flag waiving the bot-author and draft gates), test_reviewer.py:235,254 (prompt-identity and both-mode tests), test_review_pr.py:569-592 and test_review_local.py:282-295 (carve-out behavior across both modes).- **Found:** The issue's decisive premise is false: the self-driving provenance block is interpolated at reviewer.py:568 into the TRUSTED context region, before the '--- BEGIN UNTRUSTED CONTENT ---' marker at reviewer.py:593 — not into the 'lower-priority user prompt'. Both failure modes it predicts are already structurally prevented: Pipeline(self_driving=True) waives the bot-author refusal (review_pr.py:225) and the draft prerequisite (review_pr.py:590), and the block text itself declares the author-trust signals inapplicable ('author familiarity, org membership, and merged-PR history carry no signal here'). The label-confidence concern is void for this flow: Inbox PRs never receive the stamphog label (Case 4), and the provenance block renders only when cl['self_driving'] is set, so there is no confidence signal in the prompt for the model to misuse.- **Impact:** The suggested change duplicates behavior the code already implements and guards with tests. Adding a 'no label confidence' sentence would document a condition that cannot arise in this flow, which falls under the skill's drop criteria (speculative/noise). Dropped.- **Priority:** Not set — the finding is dismissed outright rather than re-graded.

### [✅ VALID] should_fix · bug — tools/pr-approval-agent/reviewer.py:699-700

**Ready self-driving PRs are reported as drafts**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The prompt always says that the PR is a draft. A self-driving PR can become ready before a later push starts another review. The trusted prompt then reports false state for this supported path.
- **Suggestion:** Pass `pr.draft` to `_format_self_driving()`. Include the draft sentence only when the value is true. Add a test for a push after the PR becomes ready.
- **Validator:** - **Checked:** reviewer.py:683-703 (\_format_self_driving hardcodes the 'It is a draft on purpose…' sentence and never reads pr.draft), reviewer.py:449-463 (\_build_review_prompt composes the block into the trusted prompt without draft state), github.py:24 and github.py:591 plus review_local.py:197 (PRData.draft exists and is populated on every fetch path), pr-approval-agent.yml:33 and :251,254 (ready_for_review + synchronize re-review paths that reach the prompt with draft=False), test_reviewer.py:235 (existing test covers the flag on/off but not the draft-state gate).
- **Found:** \_format_self_driving() emits 'It is a draft on purpose' unconditionally, while PRData.draft (github.py:24) holds the actual state. For the supported path where a self-driving PR is marked ready and a later push triggers re-review (pr-approval-agent.yml:33,251), the trusted prompt is built with draft=False but still tells the reviewer the PR is a draft — false state in the trusted region.
- **Impact:** The reviewer is trusted context that the verdict leans on; feeding it a false draft claim can skew the verdict on a path the workflow explicitly supports. Gating the draft sentence on pr.draft removes the falsehood with no effect on any other prompt (the block still renders empty for non-self-driving runs).
- **Priority:** Keep the reviewer's should_fix — a real correctness defect in trusted-prompt state, but not security or data loss.

### [✅ VALID] should_fix (validator→consider) · bug — products/review_hog/backend/api/settings.py:71-82

**A transient lookup error leaves the switch disabled until reload**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Every lookup error becomes a successful response with stamphog_connected set to false. The frontend treats false as a confirmed missing connection and disables the switch. The successful request does not trigger its failure retry. The switch stays disabled after the database recovers until another settings request occurs.
- **Suggestion:** Return an unavailable state when the lookup raises. Make stamphog_connected nullable, or add a connection status field. Show a temporary error for the unavailable state and retry loadSettings with bounded backoff. Use false only when a successful query finds no configuration.
- **Validator:** - **Checked:** I read `get_stamphog_connected` (products/review_hog/backend/api/settings.py:71-81) — any exception from `has_reviewable_repo_config` is logged and converted to `False` inside a 200 response. I verified the call reaches a separate product database: `products/db_routing.yaml:2-3` routes the stamphog app to its own Postgres DB with the fail-open engine and circuit breaker (posthog/settings/data_stores.py:176-189, posthog/db_backends/failopen/base.py:28-44), so a product-DB outage fails fast while the settings endpoint itself succeeds. On the frontend I read the switch gating (products/review_hog/frontend/CodeReviewScene.tsx:1063-1066) and the load flow (products/review_hog/frontend/reviewHogSettingsLogic.ts:444-455, 646-656).
- **Found:** The claimed mechanism is accurate. A transient product-DB error yields `stamphog_connected: false` in a successful response, so `initialLoadFailed` stays false and the retry banner (products/review_hog/frontend/CodeReviewScene.tsx:1589-1593) never appears; `loadSettings` only re-fires on scene mount or after an `updateSettings` call. The switch then renders disabled with the message "Connect a repository to Stamphog first" even though a config exists. Two mitigating behaviors I confirmed: an already-on switch stays interactive (the disabled branch requires `!stamphog_review_inbox_prs`), and the wrong state self-heals on the next scene mount, since `loadAll` re-fetches the whole serializer including the flag.
- **Found:** The degradation is deliberate and documented in the code (settings.py:73-76: "False is the safe degradation — the toggle renders disabled until the read recovers"), the error is logged server-side via `logger.exception`, and the failure direction is safe — it can never enable the toggle, only disable it.
- **Impact:** A user viewing the settings page during a product-DB blip sees a misleading "not set up" message for the rest of that page view; navigation or reload corrects it. No data loss, no wrong review behavior, no lasting effect. The proposed fix (nullable status plus retry backoff) adds schema and loader complexity for a rare, self-healing, opt-in experiment surface.
- **Priority:** Downgrading from should_fix to consider: the mechanism is real but the consequence is a transient cosmetic mislabel on a failure path the code consciously accepts.

### [— no-verdict] should_fix — products/stamphog/backend/tasks/tasks.py:1202-1208

**Failed same-head reviews have no retry limit**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The dedupe excludes all `FAILED` runs. Each later TaskRun output save queues this task again. A deterministic failure can consume GitHub, Temporal, and LLM capacity without a limit.
- **Suggestion:** Add a per-head retry budget with exponential backoff. Retry transient failures only. Require a new head or manual action after the budget expires.

### [✅ VALID] must_fix (validator→should_fix) · bug — products/review_hog/backend/receivers.py:111-114,126-139

**Opt-out skips the stale-approval fallback**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** `process_inbox_pr_review` is the documented fallback when a synchronize webhook is lost. This receiver queues that task only when one resolved reviewer still has the toggle enabled. If the reviewer opts out, a later output save at a new head queues no Stamphog work. The same gap occurs when reviewer resolution returns `None`. The old approval then stays active over commits that Stamphog did not review. That approval can satisfy a required review.
- **Suggestion:** After validating the task-to-PR link, queue a durable reconciliation job for every PR save. The job must fetch the current head and dismiss old-head approvals before it checks the toggle. It should create a review only when a current reviewer opted in. Add a regression test for a lost synchronize webhook after an opted-out reviewer pushes a new head.
- **Validator:** - **Checked:** I traced the webhook opt-out path first: on a delivered `synchronize`, `_inbox_rereview_carve_out` resolves opt-out (`resolver` returns None → `_InboxCarveOut(opted_out=True)`, products/stamphog/backend/tasks/tasks.py:205-207), and the skip path then calls `_retract_stale_approvals_on_skip` with `_INBOX_OPT_OUT_DISMISS_MESSAGE` (tasks.py:877-901), so a delivered webhook does dismiss the stale approval. I then checked the fallback leg: `process_inbox_pr_review`'s docstring explicitly names itself the fallback for "a lost synchronize" (tasks.py:1120-1124), and it re-checks the toggle only via the receiver, which queues it only when `settings.stamphog_review_inbox_prs` is on (products/review_hog/backend/receivers.py:126-139) and only when `_resolve_assigned_reviewer` returns a user (receivers.py:111-113).
- **Found:** The gap is real and asymmetric: the webhook path treats dismissal as "never preference-gated" (tasks.py:163-164), but the fallback leg inverts that — after an opt-out (or a resolution that returns None), a later TaskRun output save at a new head queues nothing, so the head-keyed dismissal sweep that normally runs inside the review never fires. A stale Stamphog approval then remains attached to commits nobody reviewed, which the code treats as a serious hazard everywhere else (dedicated retraction paths with retries at tasks.py:481-516, merge-time head checks at tasks.py:565-575).
- **Found:** The trigger is compound and rare: it needs the synchronize webhook (or every retry window) lost AND no later webhook-eligible event AND an opted-out resolved reviewer. The opted-in mirror case is covered — the same receiver fire queues `process_inbox_pr_review`, which fetches the current head and reviews it (tasks.py:1136-1160). Only the dismissal responsibility is dropped.
- **Impact:** In that compound scenario a stale approval can satisfy a branch-protection review over unreviewed code — the exact outcome the PR's Case 3 promises cannot happen ("the old approval is dismissed anyway"). But it requires a sustained webhook delivery failure, the webhook normally handles this correctly, and the feature is an opt-in experiment. The suggested remedy (a durable reconciliation job on every PR save) is heavyweight for the residual risk.
- **Priority:** Downgrading from must_fix to should_fix: a genuine safety-consistency hole in a documented fallback, but gated behind a rare compound failure and an experiment flag.

### [✅ VALID] should_fix · bug — products/review_hog/backend/api/settings.py:71-78

**Connection status accepts an unusable credential owner**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** `get_stamphog_connected` reports the result of `has_reviewable_repo_config`. That facade only checks that `connected_by_user_id` is non-null. The field is a plain cross-database integer, so user deletion or deactivation leaves it set. The settings API then reports true and enables the switch. Every review fails later because `_mint_reviewer_gateway_token` requires that user to exist and be active.
- **Suggestion:** Make the facade use the same credential-owner test as `_mint_reviewer_gateway_token`. Return true only when an enabled, synced config references an active `User`. Add API cases for missing and inactive users.
- **Validator:** - **Checked:** I read `has_reviewable_repo_config` (products/stamphog/backend/facade/api.py:120-125): its only user condition is `connected_by_user_id__isnull=False`, and `connected_by_user_id` is a plain `BigIntegerField` on a separate product database (products/stamphog/backend/models.py:48), so it cannot FK-cascade on user deletion. I read `_mint_reviewer_gateway_token` (products/stamphog/backend/temporal/activities.py:123-133), which requires the connected user to exist AND be `is_active=True` at review time.
- **Found:** The two checks genuinely diverge. If the connecting user is deleted or deactivated after a sync, the settings flag keeps reporting `true` and the UI enables the switch, while every review attempt fails at mint time with "The user who connected this installation is missing or deactivated" (activities.py:130-133). The docstring itself calls this "fails closed" (activities.py:120-121). No other stamphog code re-validates the user's active state — I grepped all `connected_by_user_id` and `is_active` uses.
- **Found:** The mismatch self-heals in the normal lifecycle: any team member re-running the sync flow re-stamps `connected_by_user_id` to themselves (products/stamphog/backend/presentation/views.py:457-466, "the original installer may be long gone"), and the failure mode is an opaque review error, not a security hole — nothing is approved or posted without a valid token.
- **Impact:** A user who enables the switch while the flag says connected gets reviews that always fail, with the only server signal a logged exception. Recoverable by any re-sync, low probability (requires losing exactly the connecting user), and the suggested alignment of the facade's test with the mint-time check is small and strictly consistent. But this is a UI accuracy issue on an opt-in experiment surface: no data loss, no security exposure, and the runtime already fails closed as designed.
- **Priority:** Keeping the reviewer's should_fix: a real cross-database consistency gap with a concrete user-visible consequence, though not merge-blocking.

### [— no-verdict] must_fix — products/tasks/backend/facade/api.py:507-509

**The gate rejects the self-driving tasks it must identify**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** Signals creates automatic implementation tasks with internal=True in products/signals/backend/auto_start.py. This new condition rejects every one of those tasks. The ReviewHog save receiver also rejects them before it queues the initial review. Thus the target self-driving PRs receive no initial review and no webhook re-review.
- **Suggestion:** Use the signals implementation association that record_implementation_task writes instead of Task.internal. Update this facade and the save receiver together. Add a test that uses the actual internal=True auto-start task shape.

### [— no-verdict] should_fix — products/stamphog/backend/tasks/tasks.py:1202-1209

**An older completed run can hide the latest failed review**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The query removes FAILED and SUPERSEDED rows before it selects the newest run. A newer failed re-review can share a head with an older completed run. The older row then stops the retry path. This occurs when a same-head reopen or base-retarget review dismisses the previous approval and then fails. A later receiver save leaves the current diff without a new verdict.
- **Suggestion:** Select and lock the newest row for the head without a status filter. Restart it when it is QUEUED. Create a replacement when it is FAILED or SUPERSEDED. Treat other newest statuses as handled. Add a regression test with an older completed run and a newer failed run.

### [✅ VALID] should_fix · bug — tools/pr-approval-agent/review_local.py:316-324

**Self-driving retries get stranded on the current head**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** This path has no `stamphog` label. The engine can still return `WAIT`, `ERROR`, or a temporary migration gate result. The hosted workflow stores these results as terminal runs. `process_inbox_pr_review` then treats that head as already reviewed. Check-run completion also does not restart the review. A temporary reviewer or CI delay can therefore prevent a completed review until another commit arrives.
- **Suggestion:** Make self-driving retry outcomes recover at the same head. Keep `WAIT` and `ERROR` retryable. Schedule another run after the reviewer clears or the migration check completes. Use the Inbox provenance to preserve existing label-driven behavior for normal reviews.
- **Validator:** - **Checked:** products/stamphog/backend/tasks/tasks.py:1207-1213 (dedupe restarts only QUEUED runs; GATED/FAILED heads short-circuit as already-reviewed), tools/pr-approval-agent/review_local.py:310-360 (run() returns WAIT when the bot-wait budget expires; exceptions are not converted to a retryable outcome), tools/pr-approval-agent/reviewer.py:157 and :706-707 (BOT_REVIEW_WAIT_BUDGET_SECONDS and the 'retryable reviewer failure' comment distinguishing retryable from non-retryable), products/stamphog/backend/temporal/constants.py:78-80 (SANDBOX_RETRY_POLICY maximum_attempts=1, comment confirms transient failure intentionally fails the run), products/stamphog/backend/temporal/activities.py:721-722 and products/stamphog/backend/facade/enums.py:31-33 (WAIT→GATED and both statuses in TERMINAL_STATUSES), products/stamphog/backend/tasks/tasks.py:1110 and :1212 (process_inbox_pr_review re-fires per TaskRun save but dedupe keys on current head, so a stranded head is never revisited).
- **Found:** The issue is factually accurate on every claim. A transient sandbox outcome — a bot review still in flight after the 300s budget, a one-attempt sandbox failure, or a pending migration check — is persisted as a terminal ReviewRun (GATED or FAILED, both in TERMINAL_STATUSES per facade/enums.py:31-33). The head-keyed dedupe at tasks.py:1207-1213 only restarts runs in QUEUED status, so it treats those heads as already reviewed and never re-reviews them. The inbox path applies no stamphog label that could re-trigger review (label is the gate only for human PRs), and process_inbox_pr_review re-fires on TaskRun saves but the dedupe short-circuits before any new run is created for an already-terminal head.
- **Impact:** A temporary reviewer delay or CI hiccup permanently blocks the review verdict for that head; the self-driving PR sits without a review until an unrelated commit creates a new head. This defeats the feature's core guarantee that inbox PRs get reviewed at triage time. Making transient outcomes recoverable at the same head (retry WAIT/ERROR before persisting terminal status, and schedule a follow-up attempt when the reviewer clears or the migration check completes) restores that guarantee without changing label-driven behavior for normal reviews, which the inbox provenance flag already separates (review_local.py:309-312).
- **Priority:** Keep the reviewer's should_fix — a real liveness defect in the reviewed feature's recovery path, but not a security or data-loss issue.
