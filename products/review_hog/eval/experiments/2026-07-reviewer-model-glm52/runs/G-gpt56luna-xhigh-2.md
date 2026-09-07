# Reviewer-quality run — `G-gpt56luna-xhigh-2`

- **Dumped:** 2026-07-30T13:54:38+00:00
- **Report id:** `019fb32c-ae9e-7911-b66c-56f6259d79bc` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `1341596e721880256a1afb79bbc881364d00e302` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 2205s (36.8 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-luna` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 13           | 16         | 14          | 2                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model           | stage                       | gens    | fresh in       | cache write | cache read     | output      | >200K gens | true $     | gw $       |
| --------------- | --------------------------- | ------- | -------------- | ----------- | -------------- | ----------- | ---------- | ---------- | ---------- |
| claude-opus-4-8 | validation                  | 128     | 98,935         | 685,047     | 11,257,165     | 135,422     | 0          | $13.79     | $13.79     |
| gpt-5.6-luna    | review                      | 262     | 12,656,685     | 0           | 0              | 54,937      | 0          | —          | $3.34      |
| gpt-5.6-luna    | blind-spot                  | 41      | 2,073,184      | 0           | 0              | 10,859      | 0          | —          | $0.49      |
| claude-sonnet-5 | dedup                       | 1       | 6,560          | 0           | 0              | 1,916       | 0          | $0.03      | $0.03      |
| claude-sonnet-5 | other:perspective_selection | 1       | 5,981          | 0           | 0              | 552         | 0          | $0.02      | $0.02      |
| **total**       |                             | **433** | **14,841,345** | **685,047** | **11,257,165** | **203,686** | **0**      | **$13.84** | **$17.67** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = +0.0%.
- `true $` total excludes unpriced model `gpt-5.6-luna` (303 gen(s), gw $3.83).
- naive method (all prompt tokens at input price): $63.64 — 4.6× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $13.8691 over 433 gen(s) (true $10.4299, Δ +33.0%)
  - · of which cache read: $6.8831 over 377 gen(s) (true $5.6286, Δ +22.3%)
  - · of which cache write: $4.2815 over 116 gen(s) (true $4.2815, Δ +0.0%)
  - · of which fresh (derived): $2.7044 over 433 gen(s) (true $0.5198, Δ +420.3%)
  - output: $3.8050 over 433 gen(s) (true $3.4102, Δ +11.6%)

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | step                | first gen | t1 cache read | t1 cache write | models          |
| --------- | ------------------- | --------- | ------------- | -------------- | --------------- |
| …a0125960 | issues-review-p1-c3 | 13:19:02  | 0             | 0              | gpt-5.6-luna    |
| …424a3898 | issues-review-p1-c2 | 13:19:03  | 0             | 0              | gpt-5.6-luna    |
| …15f38e00 | issues-review-p1-c1 | 13:19:03  | 0             | 0              | gpt-5.6-luna    |
| …cafcd1ee | issues-review-p2-c2 | 13:19:03  | 0             | 0              | gpt-5.6-luna    |
| …55b8e044 | issues-review-p3-c2 | 13:19:04  | 0             | 0              | gpt-5.6-luna    |
| …4436954b | issues-review-p3-c1 | 13:19:04  | 0             | 0              | gpt-5.6-luna    |
| …1bb0d7af | issues-review-p3-c3 | 13:19:04  | 0             | 0              | gpt-5.6-luna    |
| …5ff91f72 | issues-review-p2-c3 | 13:19:04  | 0             | 0              | gpt-5.6-luna    |
| …eff28a6d | issues-review-p2-c1 | 13:19:08  | 0             | 0              | gpt-5.6-luna    |
| …0747fa56 | issues-review-p3-c1 | 13:22:03  | 0             | 0              | gpt-5.6-luna    |
| …ffbe675c | issues-review-p1-c1 | 13:22:03  | 0             | 0              | gpt-5.6-luna    |
| …051cc66e | issues-review-p2-c1 | 13:22:21  | 0             | 0              | gpt-5.6-luna    |
| …0fbcb0b0 | issues-review-p3-c2 | 13:22:22  | 0             | 0              | gpt-5.6-luna    |
| …f9939922 | issues-review-p2-c2 | 13:22:22  | 0             | 0              | gpt-5.6-luna    |
| …8dece515 | issues-review-p1-c2 | 13:22:22  | 0             | 0              | gpt-5.6-luna    |
| …bb5a7f81 | issues-review-p3-c3 | 13:22:23  | 0             | 0              | gpt-5.6-luna    |
| …8ac54491 | issues-review-p1-c3 | 13:22:24  | 0             | 0              | gpt-5.6-luna    |
| …1a7e764b | issues-review-p2-c3 | 13:22:24  | 0             | 0              | gpt-5.6-luna    |
| …1d443697 | issues-review-p3-c3 | 13:25:34  | 0             | 0              | gpt-5.6-luna    |
| …34a13a38 | issues-review-p2-c1 | 13:25:36  | 0             | 0              | gpt-5.6-luna    |
| …574d2492 | issues-review-p2-c3 | 13:25:36  | 0             | 0              | gpt-5.6-luna    |
| …9119acbf | issues-review-p2-c2 | 13:25:37  | 0             | 0              | gpt-5.6-luna    |
| …2a312922 | issues-review-p1-c2 | 13:25:38  | 0             | 0              | gpt-5.6-luna    |
| …1598c2d7 | issues-review-p1-c3 | 13:25:38  | 0             | 0              | gpt-5.6-luna    |
| …11875582 | issues-review-p3-c1 | 13:25:42  | 0             | 0              | gpt-5.6-luna    |
| …de2b3850 | issues-review-p3-c2 | 13:25:53  | 0             | 0              | gpt-5.6-luna    |
| …5361852b | issues-review-p3-c2 | 13:28:27  | 0             | 0              | gpt-5.6-luna    |
| …14c175c2 | issues-review-p1-c3 | 13:28:28  | 0             | 0              | gpt-5.6-luna    |
| …82a0212c | issues-review-p2-c2 | 13:28:36  | 0             | 0              | gpt-5.6-luna    |
| …1c6c9d6b | issues-review-p1-c2 | 13:28:37  | 0             | 0              | gpt-5.6-luna    |
| …b621bd00 | issues-review-p2-c1 | 13:28:37  | 0             | 0              | gpt-5.6-luna    |
| …735cffd4 | issues-review-p3-c3 | 13:28:43  | 0             | 0              | gpt-5.6-luna    |
| …e4daa5ea | issues-review-p3-c1 | 13:28:56  | 0             | 0              | gpt-5.6-luna    |
| …9425465a | blind-spots-c3      | 13:31:37  | 0             | 0              | gpt-5.6-luna    |
| …6f2b4074 | blind-spots-c2      | 13:31:38  | 0             | 0              | gpt-5.6-luna    |
| …86143e54 | blind-spots-c4      | 13:31:40  | 0             | 0              | gpt-5.6-luna    |
| …da2583ec | blind-spots-c1      | 13:36:45  | 0             | 0              | gpt-5.6-luna    |
| …9c6b5cd8 | validation-c1       | 13:39:14  | 0             | 37,280         | claude-opus-4-8 |
| …74a9928c | validation-c4       | 13:39:18  | 0             | 36,608         | claude-opus-4-8 |
| …e5adfbfe | validation-c3       | 13:39:20  | 0             | 36,912         | claude-opus-4-8 |
| …f71a1652 | validation-c2       | 13:39:23  | 0             | 37,255         | claude-opus-4-8 |

- units with turn-1 cache_read > 0: **0/41** (report the distribution, not a median).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 7s       |
| review wave (perspectives)  | 12m 56s  |
| blind-spot sweep            | 6m 53s   |
| dedup (incl. combine/clean) | 18s      |
| validation                  | 15m 58s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 19m 49s — the reviewer-model speed comparison number.
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
| 1    | 3     | review-hog-perspective-contracts-security      | 2          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 3    | 3     | review-hog-perspective-performance-reliability | 1          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | review-hog-blind-spots-general                 | 2          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/review_pr.py:587-590

**Restrict the draft bypass to bot-authored PRs**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The self_driving flag bypasses the draft prerequisite for any PR when enabled, but the intended carve-out is specifically for verified bot-authored Inbox PRs. If a trusted-context construction bug or misassociation sets this flag on a human draft PR, the engine will review and potentially approve it despite draft status.
- **Suggestion:** Derive an effective flag after fetching the PR that requires both trusted self-driving provenance and `pr.author_is_bot`, or fail closed when the flag and author type do not match. Use that effective value consistently for both gate relaxation and prompt provenance.
- **Validator:** - **Checked:** Traced every path that can set `Pipeline.self_driving`. The engine reads it in `review_local.run()` as `self_driving=bool(context.get("self_driving_review"))`, which is stamped in `products/stamphog/backend/temporal/activities.py` (`run_review_in_sandbox`) as `self_driving_review=bool(output.get("inbox_review"))`. So the flag is _only_ ever set when the `ReviewRun` carries inbox provenance, which is written on exactly two paths in `products/stamphog/backend/tasks/tasks.py`.
- **Found:** The webhook re-review path (`_inbox_rereview_carve_out`) hard-gates on author type before it will produce provenance: `if not _is_bot_authored(pr): return _InboxCarveOut()` — a human-authored PR can never receive `inbox_review` provenance there. The initial-review path (`process_inbox_pr_review`) has no explicit bot check but is only invoked via `queue_inbox_pr_review` from review_hog's TaskRun receiver, fed PR URLs from signal-implementation runs, which open PRs as the team's GitHub App machine user (bot) by construction. There is no real input by which a human draft PR reaches the engine with `self_driving=True`.
- **Impact:** The scenario the finding describes is explicitly conditioned on "a trusted-context construction bug or misassociation" — i.e. a hypothetical defect in the upstream provenance-stamping, not a reachable input. The suggested `effective = self_driving and pr.author_is_bot` recheck is a defense-in-depth belt-and-braces guard redundant with the bot-author restriction the parent callers already enforce (webhook explicitly; receiver by task-linkage invariant). Under the validation bar this is a speculative "what if"/defensive-paranoia item guarding against conditions ruled out by validation already in place — precision-over-recall says drop. Note also the bot-author-refusal half of the concern is moot for a human PR: `if self.pr.author_is_bot and not self.self_driving` is already a no-op when `author_is_bot` is False, so the only behavioral change for a hypothetical mis-flagged human PR is the draft gate, and even then a GitHub draft cannot be merged while draft.

### [❌ dismissed] must_fix · bug — products/review_hog/backend/receivers.py:144-158

**Honor the opt-in of any assigned reviewer**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The Stamphog resolver selects the canonical reviewer and checks only that user's `stamphog_review_inbox_prs` toggle. The stated behavior is to run Stamphog when at least one assigned reviewer has opted in, so a canonical reviewer who is opted out currently prevents an eligible assigned reviewer from enabling the review.
- **Suggestion:** Resolve the assigned reviewers once, then select an opted-in reviewer for the Stamphog leg, or add a separate resolver that checks the toggle across all resolved assigned users while preserving the intended acting-user selection for review configuration.
- **Validator:** - **Checked:** The real PR head (`1341596e`, fetched — the working tree was on base `d24a844e` and lacked the changes) for `products/review_hog/backend/receivers.py`, its tests (`tests/test_inbox_trigger.py`), the stamphog webhook consumer (`products/stamphog/backend/tasks/tasks.py`), and the inversion hook (`facade/inbox_hooks.py`).
- **Found:** The single-acting-reviewer model is the deliberate, documented design, not an oversight. `receivers.py` module docstring: "The same resolved acting reviewer carries a second, independent toggle: `stamphog_review_inbox_prs`". `_resolve_assigned_reviewer` returns exactly one `acting.id`, and `handle_task_run_saved` reads BOTH toggles off that one user's `ReviewUserSettings.load(team_id, acting_user_id)`. The webhook re-review path resolves the identical single acting reviewer (`tasks/tasks.py:205` via `get_inbox_acting_reviewer_resolver`), so "any assigned reviewer" is implemented nowhere.
- **Found:** Tests pin the flagged behavior as intended, not buggy. `test_opted_out_canonical_reviewer_blocks_the_review` asserts `mock_start.assert_not_called()` with the comment "a later reviewer's opt-in must not hijack whose options the review runs with" — the exact scenario the issue calls a bug. `test_the_two_toggles_gate_their_reviews_independently` is commented "the two toggles on **the one acting reviewer**." This mirrors the pre-existing `review_inbox_prs` gate (a documented maintainer decision, 2026-07-02/03).
- **Impact:** The issue's premise ("stated behavior is to run Stamphog when at least one assigned reviewer opted in") comes only from loose PR-body prose and is contradicted by the code's docstrings, the webhook leg, and explicit tests. Adopting the suggestion would break the pinned invariant that a non-canonical reviewer's opt-in must not enable a review under a different reviewer's identity. Per the criteria this is a mistaken-premise finding — drop it.

### [❌ dismissed] should_fix · best_practice — products/review_hog/backend/receivers.py:210-236

**do not silently lose the initial review when queue publishing fails**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** If the broker is unavailable, queue_inbox_pr_review raises before Celery accepts the task, but this helper catches and only logs the exception. Because the PR is bot-authored and draft, the normal Stamphog webhook path will not reliably provide another opportunity to create the initial review, so a transient broker failure can permanently drop the requested review. The task's retry policy cannot help when the task was never enqueued.
- **Suggestion:** Use a durable handoff or outbox/retry mechanism for the initial dispatch, recording the pending review before commit and retrying publication until it is accepted. At minimum, retain a durable pending marker that a later worker can reconcile instead of swallowing the enqueue failure.
- **Validator:** - **Checked:** The real PR head (`1341596e`) `_start_stamphog_review` (`products/review_hog/backend/receivers.py`), the facade `queue_inbox_pr_review` (`facade/api.py:128` — a bare `process_inbox_pr_review.delay()`), and the Stamphog webhook/task path (`products/stamphog/backend/tasks/tasks.py`).
- **Found:** The reviewer's webhook fact is right — the inbox carve-out is deliberately later-deliveries-only (`tasks.py:160`: "the initial review is the receiver leg's job"; `_inbox_rereview_carve_out` returns empty unless action is in `_HEAD_CHANGING_ACTIONS`/base-retarget), so the webhook does not create the initial review. But the "permanent loss" conclusion misses the documented recovery: `process_inbox_pr_review`'s docstring (`tasks.py:1124-1128`) states the durability model — "The receiver re-fires on every TaskRun output save carrying the PR URL, so dedupe keys on the PR's CURRENT head" — so a dropped `.delay()` is re-attempted on the next output save once the broker recovers. The receiver re-fires from two independent `pr_url` writers (`receivers.py:18-19`: the agent server AND the `tasks/webhooks.py` backstop).
- **Found:** The failure is not silently swallowed — it logs a full traceback (`review_hog_stamphog_inbox_review_queue_failed`) — and is the same deliberate fire-and-forget pattern as the sibling `_start_review` Temporal leg (module invariant: broker/Temporal down "must never surface into the saver"), which the reviewer did not flag.
- **Impact:** Permanent loss requires a compound rare scenario: transient broker outage at the exact dispatch AND no subsequent output-save re-fire AND no later head-change webhook. Consequence is a single dropped first-pass approve-first review (still covered by ReviewHog and human review) on an explicitly experimental feature. Per the criteria this is defensive/reliability paranoia against a rare transient failure with documented recovery, and the suggested durable outbox + reconciliation worker is overengineering for the scope — drop.

### [❌ dismissed] should_fix — products/tasks/backend/facade/api.py:500-501

**Apply team scoping inside the signal-run lookup**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `find_signal_implementation_run` calls `find_task_run` without passing `team_id`, then checks the single returned row's team afterward. For branch-based matching, a newer run from another team using the same repository and branch can be returned first, causing the correct self-driving run to be missed. The lookup also scans across tenants unnecessarily, which becomes more expensive as TaskRun volume grows.
- **Suggestion:** Extend `find_task_run` to accept and filter by `team_id` in both its PR URL and branch lookup querysets, and pass the team ID from this facade. Post-filtering the first result is not equivalent to tenant-scoped selection.
- **Validator:** - **Checked:** `find_signal_implementation_run` (products/tasks/backend/facade/api.py:484-516), the delegated `find_task_run` legs (products/tasks/backend/webhooks.py:29-98), TaskRun Meta (`ordering = ["-created_at"]`, models.py), the sole caller `_inbox_rereview_carve_out` (products/stamphog/backend/tasks/tasks.py:144-215), and the tasks webhook backstop `_record_run_pr_url` (webhooks.py:184-185, 203-213).
- **Found:** The branch leg (webhooks.py:64-76) is genuinely un-team-scoped and `.first()` returns newest-first, so the ordering premise is technically accurate. But the only caller invokes this exclusively on synchronize/reopen/base-retarget (tasks.py:167) and always passes `pr_url=pr.get("html_url")` (tasks.py:194). The pr_url leg filters on a globally-unique GitHub PR URL and runs first; the tasks backstop stamps `output.pr_url` on the initial `opened` delivery (webhooks.py:184), so on the later deliveries this carve-out actually handles, the pr_url leg resolves the run and the branch leg is not reached.
- **Found:** The cross-tenant _binding_ risk is already closed — api.py:505 returns None on `run.team_id != team_id`, so no other tenant's run can ever be bound. The only residual effect is a false negative (a skipped re-review), and it requires the branch leg to be hit AND two teams configured against the same GitHub repo AND both holding a TaskRun row with the _identical_ head-branch string. Self-driving branches are unique machine-generated names and a real PR head maps to a single git branch, so this collision is practically unreachable.
- **Impact:** Speculative, practically-unreachable edge case with low blast radius (one skipped re-review delivery, no data/security exposure). The performance angle also fails the "bites at real scale" bar: the branch leg already filters on the selective `branch`+`repository__iexact`, the pr_url leg on a unique value, and both run only on infrequent PR webhook deliveries — no N+1, unbounded scan, or hot path. Per precision-over-recall, this is a drop.

### [❌ dismissed] should_fix · performance — tools/pr-approval-agent/review_pr.py:202-209

**skip familiarity computation for self-driving bot PRs**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Enabling the self-driving path now allows bot-authored PRs to reach `_maybe_compute_familiarity()`, which performs a GitHub CLI request plus multiple bounded git operations. This work is unnecessary for machine authors, and the prompt explicitly says author familiarity carries no signal. It adds avoidable latency and can consume the review job's retry/time budget on every Inbox review.
- **Suggestion:** Short-circuit familiarity for self-driving reviews, for example by returning from `_maybe_compute_familiarity()` when `self.self_driving` is true, and apply the same condition in `review_local._attach_familiarity()` so both execution paths remain consistent.
- **Validator:** - **Checked:** How self-driving inbox reviews actually execute and whether they reach `_maybe_compute_familiarity()`. Traced both engine entrypoints — `review_pr.py::Pipeline.run()` (Action path) and `review_local.py::run()` (hosted sandbox path) — plus how `author_pr_numbers` is populated for inbox runs in `products/stamphog/backend/temporal/activities.py`.
- **Found:** Self-driving reviews run in the tokenless sandbox via `review_local.run()`, which does NOT call `Pipeline.run()` and never calls `_maybe_compute_familiarity()`. It calls `_attach_familiarity(pipeline, context)` (`review_local.py:348`), which short-circuits before any git work: `raw_prs = context.get("author_pr_numbers"); if not raw_prs: return` (`review_local.py:301-303`). The PR's own activities.py change sets `author_pr_numbers = ... if author and not is_inbox_review else []` — an empty list for every inbox review — so `_attach_familiarity` returns immediately with no `git blame`/`git log`.
- **Found:** The 'GitHub CLI request' the finding cites lives in `compute_familiarity`/`_fetch_author_pr_numbers`, reachable only via `Pipeline._compute_familiarity` on the Action path. The sandbox uses `_familiarity_offline` (injected PR numbers, zero `gh` calls), and `review_pr.py::main()` builds `Pipeline(..., dry_run=..., verbose=...)` with no `self_driving` argument (`review_pr.py:966`), so `Pipeline.run()` with `self_driving=True` occurs only in tests, never in the production inbox flow.
- **Impact:** The premise is mistaken on all counts: inbox reviews never hit `_maybe_compute_familiarity()`, issue no `gh` request in the sandbox, and their bounded git operations are already skipped because the server hands in an empty `author_pr_numbers`. The suggested short-circuit duplicates work the code already avoids, so there is no avoidable latency or retry/time-budget cost — 'wrong/unreproducible' and 'already handled elsewhere' → drop.

### [✅ VALID] must_fix · bug — products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py:1-17

**Use the next unique migration number**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** ReviewHog already has a different `0019_reviewreport_author_login_and_more` migration, so adding another `0019` creates a migration-name collision. The migration checks and `max_migration.txt` will also become inconsistent, preventing reliable migration execution and CI validation.
- **Suggestion:** Rename this migration to the next available number and update its dependency and `products/review_hog/backend/migrations/max_migration.txt` to match.
- **Validator:** - **Checked:** The review_hog migrations directory on both the PR head (`FETCH_HEAD`) and `origin/master`, plus both `0019` files' `dependencies` blocks and each side's `max_migration.txt`.
- **Found:** `origin/master` already ships `0019_reviewreport_author_login_and_more.py`, dependency `0018_backfill_urgency_threshold_to_consider`, and `max_migration.txt` = `0019_reviewreport_author_login_and_more`. The PR adds `0019_reviewusersettings_stamphog_review_inbox_prs.py` (`migrations/0019_...py:7-9`), which also depends on `0018...`, with `max_migration.txt` = `0019_reviewusersettings_stamphog_review_inbox_prs`. The branch is stale — it forked at `0018` and master gained its own `0019` afterward.
- **Found:** Two migrations numbered `0019` both rooted on `0018` create two leaf nodes in the review_hog graph → Django errors 'Conflicting migrations detected; multiple leaf nodes in the migration graph' and `makemigrations --check` fails; the single-line `max_migration.txt` values collide on merge, which PostHog's migration-lint CI check catches.
- **Impact:** After merge/rebase onto master, migrations cannot run and CI migration validation fails until the file is renumbered (e.g. `0020_...`), its dependency repointed to `0019_reviewreport_author_login_and_more`, and `max_migration.txt` updated. Concrete trigger and consequence both confirmed — a real contract/build break; `must_fix` stands.

### [❌ dismissed] must_fix — products/stamphog/backend/tasks/tasks.py:25-25

**Register the inbox reviewer resolver**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The webhook carve-out calls `get_inbox_acting_reviewer_resolver()`, but the repository contains no registration of a resolver via `register_inbox_acting_reviewer_resolver`. Consequently, the resolver is always `None`, so every synchronize/reopen/base-retarget delivery fails closed and self-driving inbox PRs are never re-reviewed after their initial review.
- **Suggestion:** Register `review_hog.backend.receivers._resolve_acting_reviewer` from `ReviewHogConfig.ready()` (or expose a dedicated registration function), and add an integration test proving that a qualifying inbox PR's synchronize event queues a new review.
- **Validator:** - **Checked:** the full registration chain the issue claims is missing — `get_inbox_acting_reviewer_resolver`/`register_inbox_acting_reviewer_resolver` (products/stamphog/backend/facade/inbox_hooks.py:24-33), every caller of the registration function repo-wide, `ReviewHogConfig.ready()` (products/review_hog/backend/apps.py:9-13), `receivers.connect()` (products/review_hog/backend/receivers.py:58-69), and INSTALLED_APPS.
- **Found:** the resolver IS registered. `ReviewHogConfig` is installed (posthog/settings/web.py:76); its `ready()` calls `receivers.connect()` (apps.py:13); `connect()` calls `register_inbox_acting_reviewer_resolver(resolve_stamphog_acting_reviewer)` (receivers.py:69), and `resolve_stamphog_acting_reviewer` is defined at receivers.py:144. So by app-ready `get_inbox_acting_reviewer_resolver()` returns a real callable, not `None`. This is exactly the wiring the suggestion asks to add — it already exists (registered from `connect()` rather than inline in `ready()`, which is equivalent). The `noqa`-free import at receivers.py:53 is deliberately import-light to avoid the dependency cycle the carve-out docstring describes.
- **Found:** the premise 'self-driving inbox PRs are never re-reviewed' does not hold — the fail-closed `resolver is None` branch (tasks.py:202-204) is only taken when review_hog is absent, which is not the deployed configuration.
- **Impact:** the finding is Wrong/unreproducible per the drop criteria — investigating the actual code shows the claimed bug does not exist. The secondary 'add an integration test' ask cannot carry the finding on its own (the test file already references the resolver slot at products/stamphog/backend/tests/test_tasks.py:30), and a missing-test nit does not meet the keep bar when the alleged must_fix bug is not real.

### [❌ dismissed] should_fix · documentation — products/stamphog/AGENTS.md:85-85,106-106

**Use the actual ReviewHog setting key**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The documented toggle is `stamphog_review_inbox_prs`, but the ReviewHog model and API expose the setting as `review_inbox_prs`. This name mismatch can lead implementers to query or add a nonexistent setting and makes the carve-out contract inaccurate.
- **Suggestion:** Replace `stamphog_review_inbox_prs` with the canonical `review_inbox_prs` field/API key, optionally describing it as the Stamphog inbox-review toggle in prose.
- **Validator:** - **Checked:** The claim that `stamphog_review_inbox_prs` is a nonexistent setting and that the canonical key is `review_inbox_prs`. Traced the PR diff across the model, serializer, migration, receivers, and frontend, plus the existing `review_inbox_prs` usages on `master`.
- **Found:** This PR _introduces_ `stamphog_review_inbox_prs` as a distinct new field, coexisting with the older `review_inbox_prs`. Both are declared on the same model: `products/review_hog/backend/models.py` keeps `review_inbox_prs = models.BooleanField(...)` and adds `stamphog_review_inbox_prs = models.BooleanField(default=False, db_default=False)`. The serializer exposes both (`products/review_hog/backend/api/settings.py` fields list gains `stamphog_review_inbox_prs`), migration `0019_reviewusersettings_stamphog_review_inbox_prs.py` creates the column, and the frontend/generated types (`CodeReviewScene.tsx`, `api.schemas.ts`, `api.zod.ts`) all carry it. The Stamphog gate keys on the new field: `receivers.py` uses `ReviewUserSettings.load(...).stamphog_review_inbox_prs`.
- **Found:** The two toggles are deliberately independent, asserted by tests: `test_inbox_trigger.py` parameterizes `stamphog_only` ({stamphog_review_inbox_prs: True} → stamphog runs, review_hog doesn't), `review_hog_only` ({review_inbox_prs: True} → the reverse), and a comment states "keying on review_inbox_prs would re-review for users who never opted into stamphog." The AGENTS.md carve-out text ("opted in via ReviewHog's per-user `stamphog_review_inbox_prs` toggle") is precisely correct — it is a ReviewHog per-user setting named `stamphog_review_inbox_prs`.
- **Impact:** The finding's premise is mistaken (Wrong/unreproducible). Applying the suggested fix — replacing `stamphog_review_inbox_prs` with `review_inbox_prs` — would document the wrong gate and contradict the code and tests, turning correct documentation into a regression. Does not meet the bar.

### [❌ dismissed] should_fix · documentation — products/stamphog/README.md:15-15

**Document an entry point that exists in the repository**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The README identifies `queue_inbox_pr_review` as the facade entry point, but no such function or symbol exists in the repository; the current inbox receiver calls `start_review_pr_workflow` directly. This leaves the documented integration path unusable for maintainers trying to trace or invoke it.
- **Suggestion:** Update the documentation to reference the actual facade/function and module path introduced by the implementation, or add and export `queue_inbox_pr_review` if that facade is part of the intended contract.
- **Validator:** - **Checked:** Whether `queue_inbox_pr_review` exists as a facade symbol and whether the inbox receiver calls `start_review_pr_workflow` directly instead, as the finding claims. Traced the PR diff for the definition, the import, the call site, and both symbols.
- **Found:** `queue_inbox_pr_review` is a real function defined by this PR in `products/stamphog/backend/facade/api.py` (`def queue_inbox_pr_review(*, team_id, pr_url, acting_user_id, signal_report_id, task_run_id)`), which delegates to the `process_inbox_pr_review` Celery task. The inbox receiver `_start_stamphog_review` in `products/review_hog/backend/receivers.py` imports it (`from products.stamphog.backend.facade.api import queue_inbox_pr_review`) and calls `queue_inbox_pr_review(...)`. The README's `queue_inbox_pr_review` reference is therefore accurate and traceable.
- **Found:** The finding conflates two distinct legs. `start_review_pr_workflow` is the ReviewHog leg (`_START = "products.review_hog.backend.temporal.client.start_review_pr_workflow"`, used by `_start_review`); the Stamphog inbox leg is a separate path that goes through `queue_inbox_pr_review` (`_STAMPHOG_QUEUE = "products.stamphog.backend.facade.api.queue_inbox_pr_review"`, used by `_start_stamphog_review`). They are not substitutes for each other. Tests in `test_inbox_trigger.py` patch each target independently.
- **Impact:** Premise is mistaken (Wrong/unreproducible) — the symbol exists, is imported and invoked, and the documented integration path is usable. The likely cause is that the reviewer searched a checkout without the PR's new files (the facade and receiver additions live in files this PR creates/modifies). Does not meet the bar.

### [❌ dismissed] should_fix · bug — products/review_hog/backend/receivers.py:111-115

**Honor the any-assignee Stamphog opt-in contract**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The receiver resolves a single canonical acting reviewer and checks only that user's Stamphog toggle. This means an Inbox PR assigned to multiple reviewers is skipped when the canonical reviewer has opted out, even if another assigned reviewer has opted in, contradicting the stated behavior that Stamphog runs when at least one assigned user enables it. The later webhook recheck uses the same single-user selection, so the mismatch persists on subsequent pushes.
- **Suggestion:** Resolve the full assigned reviewer set for the report, select an opted-in reviewer for the Stamphog leg when any exists, and pass that user to the queue/recheck path. Keep the existing canonical reviewer selection for the ReviewHog leg if its semantics must remain unchanged.
- **Validator:** - **Checked:** Re-confirmed against the PR head (`1341596e`): `_resolve_assigned_reviewer` (`receivers.py` — returns one `acting.id`), the two-toggle dispatch in `handle_task_run_saved`, the module docstring, `resolve_stamphog_acting_reviewer`, the webhook consumer `_inbox_rereview_carve_out` (`products/stamphog/backend/tasks/tasks.py`), and `tests/test_inbox_trigger.py`.
- **Found:** The single-acting-reviewer model is the deliberate, documented, test-pinned design, not a contract break. `receivers.py` module docstring: "The same resolved acting reviewer carries a second, independent toggle: `stamphog_review_inbox_prs`". `test_opted_out_canonical_reviewer_blocks_the_review` asserts the review does NOT run when the canonical reviewer is opted out (comment: "a later reviewer's opt-in must not hijack whose options the review runs with") — the exact scenario this finding calls a bug is the pinned intended behavior; `test_the_two_toggles_gate_their_reviews_independently` is commented "the two toggles on the one acting reviewer."
- **Found:** The added sub-claim — the webhook recheck reuses the single-user selection — is true but by design: `resolve_stamphog_acting_reviewer` wraps `_resolve_assigned_reviewer` ("Same acting-reviewer resolution as this module's own trigger"), so the initial and re-review legs intentionally agree on one acting reviewer. No "any assigned reviewer" path exists anywhere.
- **Impact:** The "at least one assigned user" contract lives only in loose PR-body prose, contradicted by the code's docstrings, the webhook leg, and explicit tests — so there is no real security/contract defect. This is the same mistaken-premise finding as issue `2-1-1` under a different perspective; adopting the suggestion would break the pinned invariant. Drop, consistent with the prior duplicate.

### [❌ dismissed] must_fix — products/stamphog/backend/tasks/tasks.py:1107-1245

**Validate the PR is actually the linked self-driving run**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The initial inbox task trusts `pr_url`, `signal_report_id`, and `task_run_id` supplied by the receiver, but never verifies that the fetched PR is repo-native, bot-authored, or actually linked to that specific signals implementation run. Any task output that contains an arbitrary PR URL could therefore trigger the inbox carve-out on an existing human or fork PR and bypass the normal bot, draft, author-association, and write-permission gates, potentially posting an automatic approval.
- **Suggestion:** After fetching the PR, enforce the same positive-identification checks as the webhook carve-out: require `head.repo.full_name` to match the configured repository, require the PR author to be the expected bot, and resolve the tasks facade by `team_id`, repository, and PR URL, rejecting unless its run ID and signal report ID match the task arguments. Ideally validate the task linkage before creating the `ReviewRun`, and only stamp `inbox_review` after all checks pass.
- **Validator:** - **Checked:** the full reachability chain into `process_inbox_pr_review` — its sole trigger `handle_task_run_saved` → `_start_stamphog_review` → `queue_inbox_pr_review` (products/review_hog/backend/receivers.py:98-139), every writer of `output.pr_url` in tasks (products/tasks/backend/webhooks.py:184-212), the repo-config gate inside the task (products/stamphog/backend/tasks/tasks.py:1138-1153), and the engine's self-driving flag wiring (products/stamphog/backend/temporal/activities.py:237-238,448-451).
- **Found:** the args the issue calls attacker-influenced are read off the triggering TaskRun itself. `handle_task_run_saved` only fires the stamphog leg for a run that is non-internal (receivers.py:104) and carries a signal report (receivers.py:98), and passes that run's OWN `output.pr_url` (receivers.py:93,130) with its own id/report (receivers.py:136-137). So the PR→run linkage is inherent in the trigger — the receiver leg starts from the verified run, unlike the webhook leg which must match an arbitrary inbound PR back to a run (why only the webhook leg needs `find_signal_implementation_run` + fork/bot checks).
- **Found:** `output.pr_url` is not attacker-controllable to point at a foreign PR. The webhook backstop that writes it (`_record_run_pr_url`) fires only on a repo-native match (`is_internal_branch`, webhooks.py:184), so a fork PR (head repo ≠ base) can never be recorded; the agent server records the bot's own opened PR. There is no external/untrusted write path to a signal-report run's `output`.
- **Found:** even granting a wrong URL, `process_inbox_pr_review` requires an enabled `StamphogRepoConfig` for `team_id` + the parsed repo (tasks.py:1140-1153), bounding any review to repos the team already controls; and the engine comment (activities.py:448-451) plus the receiver docstring ('bot-authored draft by construction', tasks.py:1116-1118) show the self-driving relaxation is a documented, intentional trust assumption resting on this invariant.
- **Impact:** dismissal — the 'arbitrary/fork PR bypass' is a speculative what-if that depends on a condition (attacker-set foreign `output.pr_url` on a non-internal signal-report run) the call sites and the repo-native write gate already rule out. The suggested fork/bot/facade re-checks are defensive redundancy over an upstream invariant the code upholds, which the precision-over-recall bar drops.

### [❌ dismissed] must_fix · code_quality — tools/pr-approval-agent/review_local.py:321-321

**Require a strict boolean for the self-driving flag**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `bool(context.get("self_driving_review"))` treats any non-empty value, including the string `"false"`, as `True`. A malformed or differently serialized context can therefore enable both relaxed gates and the trusted provenance prompt instead of defaulting closed as intended.
- **Suggestion:** Only enable the carve-out when the value is the JSON boolean `true`, for example `self_driving=context.get("self_driving_review") is True`; optionally reject other non-boolean values explicitly.
- **Validator:** - **Checked:** The producer of `context["self_driving_review"]` and the serialization path to `review_local.run()`. Traced `activities.py::run_review_in_sandbox` → `logic/reviewer.py::build_reviewer_invocation` → the JSON context file the engine reads via `json.loads`.
- **Found:** The value is a genuine Python `bool` at every hop: `activities.py` sets `self_driving_review=bool(output.get("inbox_review"))`; `build_reviewer_invocation(self_driving_review: bool = False)` (diff `logic/reviewer.py:767`) is typed `bool` and stores it verbatim in the context dict (`"self_driving_review": self_driving_review`, diff line 787). That dict is JSON-serialized to the context file and read back in `review_local.main()`, so `context.get("self_driving_review")` is only ever `True`, `False`, or `None` (absent). `bool(True)/bool(False)/bool(None)` are all correct.
- **Found:** The context file is written by the trusted hosted server, not the PR author — it is not attacker-controlled input. `json.dumps(False)` emits the JSON literal `false`, which `json.loads` restores to Python `False`, never the string `"false"`. No code path serializes this flag as a quoted string.
- **Impact:** The `bool("false") == True` scenario the finding relies on cannot occur given the typed-bool producer and JSON round-trip; for every input the real pipeline produces, `bool(x)` and `x is True` are identical. The suggestion is a marginal defensive hardening against a hypothetical malformed producer, not a fix for a reachable defect — speculative what-if ruled out by the types in place → drop.

### [❌ dismissed] should_fix · performance — products/review_hog/backend/receivers.py:114-138

**avoid dispatching duplicate Stamphog jobs for every output save**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Every TaskRun save that includes output can enqueue another Stamphog task, even when the PR URL has not changed. The queued task then fetches the PR from GitHub before deduplicating by its current head, so frequent agent/output saves can create redundant Celery work and GitHub API requests for the same PR.
- **Suggestion:** Coalesce dispatches before enqueueing, for example with a short-lived per-task-run/PR idempotency key or persisted last-dispatched target. Keep a bounded reconciliation path for missed synchronize webhooks rather than fetching and queueing on every unchanged output save.
- **Validator:** - **Checked:** `handle_task_run_saved`'s Stamphog dispatch guard + docstring in `receivers.py` (PR head `1341596e`) and the full `process_inbox_pr_review` body in `products/stamphog/backend/tasks/tasks.py:1110-1245` — fetch/dedupe ordering and where the sandbox workflow actually starts.
- **Found:** The reviewer's facts hold but the cost is bounded. The fetch runs before dedupe by necessity — code comment (`tasks.py:~1155`): "The fetch runs before the dedupe because the dedupe keys on the PR's current head, which only GitHub knows." But the expensive work is deduped: a head-keyed `select_for_update` lookup (`tasks.py:~1200`) returns a no-op when a live/delivered `ReviewRun` already exists at that `head_sha`; only a new head supersedes + creates + starts the workflow. So a same-head re-fire costs one `get_pr` + a couple of DB queries, not a redundant review.
- **Found:** This is deliberate and documented. `handle_task_run_saved` docstring: repeat saves "re-fire it deliberately" and "a same-head re-trigger costs one fetch (early-exit)"; `process_inbox_pr_review` docstring: "The receiver re-fires on every TaskRun output save carrying the PR URL, so dedupe keys on the PR's CURRENT head... a refire after a head the webhook leg never delivered — a lost synchronize — still reviews the new commits." The re-fire-and-fetch IS the missed-synchronize reconciliation the reviewer's suggestion says to keep.
- **Found:** The proposed pre-enqueue coalesce conflicts with the design and is largely infeasible: keying on PR URL / task_run would suppress legitimate re-reviews of new commits on the same PR, and the receiver can't cheaply know the head to dedupe on it — `TaskRun.output` carries `pr_url`/`head_branch`, not the commit SHA (the reason the fetch exists).
- **Impact:** Residual waste is a bounded `get_pr` + DB queries per same-head re-save on a low-volume, opt-in-only self-driving-PR flow — no N+1/quadratic/hot-path behavior, the costly sandbox path is already deduped, and the cheap-coalesce remedy would break the documented recovery. Does not meet the at-scale performance bar — drop.

### [✅ VALID] must_fix (validator→should_fix) · bug — products/stamphog/backend/tasks/tasks.py:1190-1207

**Prevent concurrent receiver tasks from creating duplicate reviews**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The `select_for_update()` is applied to `ReviewRun` rows after filtering by `head_sha`. When no run exists yet, the query locks nothing, so two receiver tasks fired concurrently for the same PR head can both observe no existing run, create separate queued runs, and start duplicate Temporal/LLM reviews.
- **Suggestion:** Serialize on the `PullRequest` row before checking for an existing head, or add a database uniqueness constraint on `(pull_request, head_sha)` and handle the resulting `IntegrityError` by resuming the winner. This should also prevent duplicate workflow starts under concurrent TaskRun output events.
- **Validator:** - **Checked:** the `ReviewRun` model's constraints (products/stamphog/backend/models.py:140-173), `_upsert_pull_request`'s locking (tasks.py:319-363), `_supersede_prior_runs` (tasks.py:415-432), `_start_review_workflow`'s id derivation (tasks.py:366-380), the trigger fan-out in `handle_task_run_saved` (products/review_hog/backend/receivers.py:82-139), and the `delivery_id` dedup path.
- **Found:** the flagged gap is real and nothing else closes it. `ReviewRun` has no `Meta.constraints` (models.py:140-173) — no `(pull_request, head_sha)` uniqueness — and its only unique column `delivery_id` is set to `None` on this leg (tasks.py:1227), so with Postgres allowing multiple NULLs the duplicate `create()` (tasks.py:1223) raises nothing. `_upsert_pull_request` uses `get_or_create` with no row lock (tasks.py:339), and `select_for_update().filter(pull_request=..., head_sha=...)` (tasks.py:1202) plus `_supersede_prior_runs` (tasks.py:424) lock nothing when neither run's row exists yet — the 'row lock serializes racing fires' comment (tasks.py:1198-1199) only holds once a row exists.
- **Found:** the two runs get distinct `review_run_id`s, and `_start_review_workflow` derives the Temporal workflow id from `review_run_id` (tasks.py:369), so both workflows start — no Temporal-level dedup.
- **Found:** concurrency is expected, not exotic — the receiver re-fires on every TaskRun output save carrying the PR URL (docstring tasks.py:1125; receivers.py:126-139 enqueues per save), and the slow `get_pr` sits outside the transaction (tasks.py:1158-1159), so two tasks tend to reach the short critical section together.
- **Impact:** two QUEUED runs → two sandbox/LLM reviews for the same head → wasted LLM cost and GitHub load, and possibly a duplicate non-approve comment. This meets the 'race condition / reliability defect' keep bar.
- **Priority:** lowered to should_fix — `post_verdict` adopts an existing head-pinned APPROVE rather than stacking a second (stamphog CLAUDE.md), so a double approval is prevented and the stale-approval invariant is not violated; the blast radius is duplicate work plus a possible duplicate comment, not data corruption, and the window is the short transaction.
