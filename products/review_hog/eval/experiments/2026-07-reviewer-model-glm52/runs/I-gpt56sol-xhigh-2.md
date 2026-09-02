# Reviewer-quality run — `I-gpt56sol-xhigh-2`

- **Dumped:** 2026-07-31T00:58:59+00:00
- **Report id:** `019fb590-9def-713e-aa38-4ec12d787067` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `1341596e721880256a1afb79bbc881364d00e302` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1937s (32.3 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 13           | 14         | 13          | 4                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model           | stage                       | gens    | fresh in      | cache write | cache read     | output      | >200K gens | true $     | gw $       |
| --------------- | --------------------------- | ------- | ------------- | ----------- | -------------- | ----------- | ---------- | ---------- | ---------- |
| claude-opus-4-8 | validation                  | 107     | 67,303        | 506,841     | 11,475,708     | 144,002     | 8          | $12.84     | $12.84     |
| gpt-5.6-sol     | review                      | 66      | 3,210,045     | 0           | 0              | 18,506      | 0          | —          | $4.93      |
| gpt-5.6-sol     | blind-spot                  | 22      | 1,041,118     | 0           | 0              | 5,719       | 0          | —          | $1.87      |
| claude-sonnet-5 | dedup                       | 1       | 7,624         | 0           | 0              | 3,110       | 0          | $0.05      | $0.05      |
| claude-sonnet-5 | other:perspective_selection | 1       | 5,981         | 0           | 0              | 460         | 0          | $0.02      | $0.02      |
| **total**       |                             | **197** | **4,332,071** | **506,841** | **11,475,708** | **171,797** | **8**      | **$12.91** | **$19.71** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = -0.0%.
- `true $` total excludes unpriced model `gpt-5.6-sol` (88 gen(s), gw $6.80).
- naive method (all prompt tokens at input price): $63.91 — 5.0× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $15.3451 over 197 gen(s) (true $9.2693, Δ +65.5%)
  - · of which cache read: $7.4245 over 178 gen(s) (true $5.7379, Δ +29.4%)
  - · of which cache write: $3.1678 over 107 gen(s) (true $3.1678, Δ +0.0%)
  - · of which fresh (derived): $4.7528 over 197 gen(s) (true $0.3637, Δ +1206.7%)
  - output: $4.3625 over 197 gen(s) (true $3.6357, Δ +20.0%)
- 8 gen(s) ran with >200K-token prompts; the gateway map prices these models flat, so no long-context premium is included in either column.

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | step                | first gen | t1 cache read | t1 cache write | models          |
| --------- | ------------------- | --------- | ------------- | -------------- | --------------- |
| …3d3cd137 | issues-review-p2-c3 | 00:27:20  | 0             | 0              | gpt-5.6-sol     |
| …e4c46a57 | issues-review-p3-c2 | 00:27:20  | 0             | 0              | gpt-5.6-sol     |
| …ede8c6f2 | issues-review-p3-c3 | 00:27:21  | 0             | 0              | gpt-5.6-sol     |
| …0ac846a5 | issues-review-p1-c1 | 00:27:22  | 0             | 0              | gpt-5.6-sol     |
| …4edd1967 | issues-review-p1-c3 | 00:27:22  | 0             | 0              | gpt-5.6-sol     |
| …9c3edeed | issues-review-p2-c1 | 00:27:23  | 0             | 0              | gpt-5.6-sol     |
| …2d2a8264 | issues-review-p2-c2 | 00:27:23  | 0             | 0              | gpt-5.6-sol     |
| …f7294063 | issues-review-p1-c2 | 00:27:25  | 0             | 0              | gpt-5.6-sol     |
| …92ec51a0 | issues-review-p3-c1 | 00:27:26  | 0             | 0              | gpt-5.6-sol     |
| …daf638d0 | issues-review-p2-c2 | 00:30:35  | 0             | 0              | gpt-5.6-sol     |
| …f6426874 | blind-spots-c1      | 00:32:16  | 0             | 0              | gpt-5.6-sol     |
| …d2b91524 | blind-spots-c2      | 00:32:16  | 0             | 0              | gpt-5.6-sol     |
| …dc1c7d5d | blind-spots-c3      | 00:32:18  | 0             | 0              | gpt-5.6-sol     |
| …0ea358e1 | blind-spots-c4      | 00:34:12  | 0             | 0              | gpt-5.6-sol     |
| …4c0f1a02 | validation-c3       | 00:37:24  | 0             | 37,043         | claude-opus-4-8 |
| …ec2c31c0 | validation-c2       | 00:37:25  | 0             | 37,524         | claude-opus-4-8 |
| …125d04dc | validation-c1       | 00:37:26  | 17,141        | 20,251         | claude-opus-4-8 |

- units with turn-1 cache_read > 0: **1/17** (report the distribution, not a median).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 6s       |
| review wave (perspectives)  | 4m 55s   |
| blind-spot sweep            | 4m 02s   |
| dedup (incl. combine/clean) | 34s      |
| validation                  | 22m 35s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 8m 58s — the reviewer-model speed comparison number.
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
| 3    | 1     | review-hog-perspective-performance-reliability | 1          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 3    | 3     | review-hog-perspective-performance-reliability | 1          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | review-hog-blind-spots-general                 | 1          |
| 1000 | 4     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] should_fix · best_practice — products/stamphog/backend/facade/api.py:146-153

**Fire-and-forget facade performs a synchronous, failure-propagating broker call**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Despite being described as fire-and-forget, `.delay()` synchronously contacts the Celery broker. Broker latency blocks the TaskRun save path, and a broker outage raises into the receiver and can fail the originating save. Dispatch can also occur before an enclosing database transaction commits, allowing the worker to race or outlive a rollback.
- **Suggestion:** Schedule dispatch with `transaction.on_commit()` and put the broker call behind explicit best-effort error handling and logging if review enqueue failure must not break TaskRun persistence. If delivery must be guaranteed, use the repository's durable outbox pattern instead of swallowing the broker error.
- **Validator:** - **Checked:** The sole production caller of `queue_inbox_pr_review` (`_start_stamphog_review` in products/review_hog/backend/receivers.py) and the receiver `handle_task_run_saved` that invokes it; grepped the diff for every reference to confirm no other call path exists.
- **Found:** Dispatch is scheduled **only** via `transaction.on_commit(lambda: _start_stamphog_review(...))` (receivers.py, diff L203-211) — the exact fix the finding recommends. on_commit callbacks fire after a successful commit and are discarded on rollback, so the worker cannot race or outlive a rollback, nor run before the commit.
- **Found:** `_start_stamphog_review` already wraps the facade call in `try/except Exception` with `logger.exception(...)` (diff L278-288), and the enclosing `handle_task_run_saved` is itself in a try/except (diff L213-214). A broker outage therefore cannot raise into the receiver or fail the originating save — refuting the finding's central risk claim.
- **Found:** A dedicated test, `test_stamphog_queue_failure_never_raises_into_the_save_path` (diff L377-388), locks this contract in; the pattern matches CLAUDE.md's endorsed `transaction.on_commit()` Celery-dispatch guidance.
- **Impact:** Both suggested remediations (`transaction.on_commit()` + best-effort error handling/logging) are already implemented, and the failure scenarios (broken save, pre-commit dispatch, rollback race) are unreachable. The only literally-true sub-claim — that `.delay()` does a synchronous broker publish on the post-commit thread — is the standard, intentional design (heavy GitHub/DB work is offloded into the Celery task precisely to keep the save path light) and is not a defect. Drops under 'already handled' and 'wrong/unreproducible'.

### [❌ dismissed] should_fix · performance — tools/pr-approval-agent/review_local.py:324-324

**Self-driving reviews still perform expensive author-familiarity analysis**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Allowing bot-authored self-driving PRs past this gate sends T1 reviews through `_attach_familiarity`, which can run git history analysis across up to 30 files. This work is wasted for machine authors and may add substantial latency; the new prompt also states that author familiarity carries no signal, yet any computed familiarity is still rendered alongside that statement.
- **Suggestion:** Skip `_attach_familiarity` when `pipeline.self_driving` is true, and keep `classification["familiarity"]` unset for this path. Consider also avoiding the upstream merged-PR lookup for self-driving runs.
- **Validator:** - **Checked:** `_attach_familiarity` in `review_local.py`, its call site in `run()`, and where `context["author_pr_numbers"]` originates in the server (`activities.py fetch_review_context`).
- **Found:** `_attach_familiarity` (`review_local.py:301-303`) does `raw_prs = context.get("author_pr_numbers")` then `if not raw_prs: return` — it short-circuits before `_ensure_diff_path()`/`_familiarity_offline` (the git-blame-over-files work), so an empty list means zero git analysis.
- **Found:** The server sets `author_pr_numbers = []` for self-driving runs: `activities.py` computes `is_inbox_review = bool((run.output or {}).get("inbox_review"))` and `author_pr_numbers = client.get_author_merged_pr_numbers(...) if author and not is_inbox_review else []`. The very same `inbox_review` provenance drives `self_driving_review=bool(output.get("inbox_review"))`, so `self_driving=True` ⇒ `author_pr_numbers=[]` by construction. The integration test asserts `context["author_pr_numbers"] == []` for the self-driving path.
- **Found:** With familiarity never computed, `classification["familiarity"]` stays `None`, and `reviewer.py:643-645` `_format_familiarity` returns `""` — the no-signal provenance block is not accompanied by any rendered familiarity.
- **Impact:** The premise is mistaken ("Wrong / unreproducible"): the expensive merged-PR lookup is already skipped upstream (exactly the reviewer's own "consider also" suggestion) and `_attach_familiarity` is a guaranteed no-op for self-driving runs, so there is no wasted git analysis, no added latency, and no conflicting familiarity text. Nothing to fix.

### [❌ dismissed] should_fix · best_practice — products/review_hog/backend/receivers.py:225-234

**Transient broker failures permanently drop the initial Stamphog review**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The on-commit callback ultimately publishes the Stamphog job, but `_start_stamphog_review` catches every publishing failure and only logs it. Once the transaction commits, nothing retries this handoff, so a temporary broker outage or timeout silently leaves an opted-in Inbox PR unreviewed. This is especially risky because later webhook handling depends on the initial review having recorded the PR as Inbox-originated.
- **Suggestion:** Make the handoff durable or retryable. Prefer recording an idempotent dispatch/outbox row in the transaction and having a retrying worker publish it. At minimum, configure bounded Celery publish retries and propagate failure to a retry-capable caller instead of swallowing it. Keep `task_run_id` as the idempotency key so retries cannot create duplicate reviews.
- **Validator:** - **Checked:** The full PR-head `receivers.py` (`_start_stamphog_review`, lines 210-234; the `transaction.on_commit` dispatch, 126-139) and the stamphog side it hands off to — `queue_inbox_pr_review` / `process_inbox_pr_review` and the webhook carve-out `_inbox_rereview_carve_out` in `products/stamphog/backend/tasks/tasks.py`.
- **Found:** The finding's escalating premise ("later webhook handling depends on the initial review having recorded the PR as Inbox-originated") is false. `_inbox_rereview_carve_out` re-identifies the PR as self-driving from scratch on every head-changing delivery: it calls `find_signal_implementation_run(team_id, repository, pr_url, head_branch)` against the **tasks** facade and re-checks the toggle via the registered resolver (`resolver(repo_config.team_id, run.signal_report_id, run.task_created_by_id)`). It reads nothing the initial `process_inbox_pr_review` leg persisted — provenance is re-derived from the tasks TaskRun, not from any stored Stamphog run.
- **Found:** So a dropped initial publish is self-healing, not "permanent": the next push (`synchronize`/`reopen`) re-triggers the independent webhook path, and repeat `output`-touching TaskRun saves re-fire the receiver (docstring lines 76-79). The initial Celery task is also durable once published — it has internal `.retry(...)` on config-resolution/fetch/rate-limit failures (tasks.py ~1382-1398). The only unguarded step is the `.delay()` broker publish itself.
- **Impact:** The residual failure is narrow and low-impact: a transient broker blip at the exact on-commit moment AND no subsequent push to that PR AND no further output save — a skipped initial review on one draft PR, recoverable on the next commit, not data loss or a security hole. The swallow-and-log is a deliberate, documented invariant ("the broker being down must never surface into the saver") on a hot `TaskRun` save path where raising would break tasks' own save. The proposed transactional-outbox + retrying-worker is heavyweight for that residual, on an experiment-gated per-user feature. With the finding's central "permanent drop" / webhook-dependency claims mistaken, this lands on the drop side (precision over recall).

### [✅ VALID] must_fix · bug — products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py:7-9

**Migration creates a conflicting leaf in the review_hog graph**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** This migration depends directly on 0018, but the app already has a different 0019 migration followed by migrations through 0024. Adding this file creates two leaf branches, preventing Django from determining a single migration path and causing migration-conflict checks or deployment to fail.
- **Suggestion:** Rebase the migration onto the current leaf, rename it to the next available number (for example 0025), update its dependency to 0024_reviewreport_published_head_shas, and update max_migration.txt accordingly. Run the migration conflict check and sqlmigrate afterward.
- **Validator:** - **Checked:** Fetched the PR head tree (SHA 1341596e) migration files and `max_migration.txt`, and compared against master's `products/review_hog/backend/migrations/` graph.
- **Found:** PR adds `0019_reviewusersettings_stamphog_review_inbox_prs.py` with `dependencies = [("review_hog", "0018_backfill_urgency_threshold_to_consider")]` and sets `max_migration.txt` to that name. Master already contains `0019_reviewreport_author_login_and_more.py` — which also depends on `0018` (line 8) — continuing through `0024_reviewreport_published_head_shas`, with `max_migration.txt` = `0024_reviewreport_published_head_shas`. The PR's migrations tree only spans 0018 → new 0019, i.e. it was branched before the 0019–0024 chain landed.
- **Found:** On merge into master, two migrations both depend on `0018`, producing two leaf nodes (`0024_...` and `0019_...stamphog`). `gh pr view` reports `mergeStateStatus: DIRTY`, confirming the `max_migration.txt` collision at the git level too.
- **Impact:** Django `makemigrations --check` reports "multiple leaf nodes in the migration graph" and PostHog's django-linear-migrations `max_migration.txt` CI check fails; the schema change cannot deploy until the file is renumbered onto the current leaf (0025, depending on 0024) and `max_migration.txt` updated. This is the exact contract/deployment break the finding names, and the fix in the suggestion is correct. must_fix is the right severity.

### [❌ dismissed] should_fix · security — tools/pr-approval-agent/review_local.py:316-321

**Fail closed when parsing the privileged review flag**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `bool(context.get("self_driving_review"))` treats every non-empty value as enabled, including strings such as `"false"` or `"0"`. This flag bypasses both the bot-author and draft safety gates, so accepting malformed truthy values weakens an authorization boundary.
- **Suggestion:** Require the JSON value to be the literal boolean `true`, for example `self_driving=context.get("self_driving_review") is True`, or validate the complete hosted context against a typed schema and reject invalid flag types.
- **Validator:** - **Checked:** The flagged expression `bool(context.get("self_driving_review"))` in `review_local.py`'s `run()`, and traced where `context` and this key originate.
- **Found:** `review_local.py:391` loads the context via `json.loads(Path(args.context).read_text())` — a JSON file the server writes. The writer (`products/stamphog/backend/logic/reviewer.py` `build_reviewer_invocation`, param typed `self_driving_review: bool = False`) stores `"self_driving_review": self_driving_review`, and its caller in `activities.py` passes `bool(output.get("inbox_review"))` — a genuine Python bool. The integration test asserts `context["self_driving_review"] is True`, and `_selfdriving_context` either sets the key to bool `True` or omits it.
- **Found:** A JSON boolean deserializes to Python `True`/`False`; the key is absent for every Action-shaped context. So the value reaching `bool(...)` is only ever `True`, `False`, or `None` — never a string. `bool(True)=True`, `bool(False)=False`, `bool(None)=False` all behave correctly and already fail closed for false/missing.
- **Impact:** The "malformed truthy string" premise (`"false"`, `"0"`) cannot occur given the double `bool()` wrapping and JSON round-trip, so `is True` would change the outcome for no value that can actually reach this line. The only way to inject a string would be to already control the sandbox context file — at which point an attacker writes literal `true` and the fail-closed check stops nothing. This is defensive paranoia against an input the upstream types and call sites rule out, and the suggested "typed schema" validation is overengineering — both drop per the criteria.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1142-1191

**Initial inbox review does not verify the PR belongs to the task**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The worker trusts the queued `pr_url`, extracts any configured repository from it, fetches that PR, and stamps it as an inbox review without validating the supplied task/signal IDs, the PR's head repository, or bot authorship. Because `self_driving_review` bypasses the normal bot, draft, review-mode, and author-permission gates, a forged or poisoned task output could cause an unrelated human or fork PR in any configured team repository to receive a privileged Stamphog review and potentially an approval.
- **Suggestion:** Before creating the run, resolve `task_run_id` through the team-scoped tasks facade and require it to match `signal_report_id`, the configured repository, and the fetched PR URL or head branch. Also require the fetched PR's head repository to equal the base repository and verify the expected self-driving bot author. Fail closed unless every check succeeds; ideally expose one facade method that performs this complete team-scoped linkage validation.
- **Validator:** - **Checked:** `process_inbox_pr_review` (tasks.py diff L1061-1176) against its sibling `_inbox_rereview_carve_out` (diff L862-933); the engine's `self_driving` gate relaxations (`review_pr.py` diff L1977, L1999); and the write path for `output.pr_url`.
- **Found (real asymmetry):** the initial leg gates only on repo-config + PR `state==open` + `head_sha`; it never checks head repository (fork), never checks bot authorship, and never calls `find_signal_implementation_run`. The webhook leg deliberately does all three, including an explicit `head_repo == repo` fork check whose comment says a branch match could otherwise bind an unrelated fork PR (diff L891-896).
- **Found (gate bypass reaches an approval):** `self_driving` relaxes the bot-author and draft gates in the engine, and the engine has no fork/author-association gate of its own (those live only in the webhook Celery pre-filter the initial leg skips). The end-to-end test `test_inbox_review_approves_a_selfdriving_draft_pr_end_to_end` (diff L1259-1297) confirms this leg posts a real GitHub APPROVE.
- **Found (poisoning is reachable, not hypothetical):** `output.pr_url` is settable via authenticated, team-scoped endpoints `set_output` / `partial_update` on `TaskRunViewSet` (scope `task:write`); `validate_set_output` only enforces `task.json_schema` (absent on signal-implementation tasks) and `set_task_run_output` stores any `pr_url` unrestricted. The webhook backstop's fork-safety (`products/tasks/backend/webhooks.py:181-186`) does not apply on this API path, so a `task:write` holder can point a non-internal signal-report run's `pr_url` at any open PR (including a fork/untrusted PR) in a Stamphog-connected repo.
- **Impact:** with an opted-in resolved reviewer, a poisoned `output.pr_url` routes an arbitrary human/fork PR through the self-driving carve-out, bypassing the fork/bot/draft/review-mode/write-permission guards Stamphog enforces everywhere else and potentially landing a real bot approval that satisfies required reviews — a trust-boundary bypass in an approval-granting path the product's own invariants require to be fail-closed. Meets the security 'keep' bar with a concrete trigger and consequence.
- **Note on remediation:** linkage-by-`pr_url` alone is insufficient (the attacker controls the field the lookup keys on), but the finding also calls for verifying the fetched PR's head repo == base and the expected bot author — those are the effective, low-cost checks the sibling leg already performs, so the fix direction is sound and not overengineering.

### [❌ dismissed] must_fix · bug — products/review_hog/backend/receivers.py:122-124,151-155

**Stamphog opt-in checks only one assignee instead of any assigned user**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The PR promises a Stamphog review when at least one assigned reviewer opts in, but `_resolve_assigned_reviewer` selects the task creator or first resolved reviewer before the Stamphog setting is checked. If that user is opted out while another assignee is opted in, both the initial review and webhook re-review are skipped. This makes assignment order determine whether the feature runs.
- **Suggestion:** Resolve Stamphog eligibility across all assigned reviewers. Preserve creator precedence when that creator is opted in; otherwise select the first resolved assignee with `stamphog_review_inbox_prs` enabled. Use that same resolver for both the initial dispatch and webhook re-check, while retaining the existing single-reviewer behavior for ReviewHog.
- **Validator:** - **Checked:** The PR-head `receivers.py` gating (`_resolve_assigned_reviewer` 159-207; both toggles checked on the one resolved reviewer at 114-139; `resolve_stamphog_acting_reviewer` 144-156) and the PR's own tests in `products/review_hog/backend/tests/test_inbox_trigger.py`.
- **Found:** The single-acting-reviewer gate is the deliberate, documented design, not an accident. `_resolve_assigned_reviewer`'s docstring (lines 160-173) states the acting reviewer is creator-when-assigned else first-resolved, and "their `review_inbox_prs` / `stamphog_review_inbox_prs` toggles gate the respective reviews," citing "maintainer decisions, 2026-07-02/03." The module docstring (17-23) frames the stamphog toggle as "a second, independent toggle" carried by "the same resolved acting reviewer."
- **Found:** Tests explicitly lock in the exact behavior the finding calls a bug. `test_opted_out_canonical_reviewer_blocks_the_review` asserts that when the canonical reviewer (bob) is opted out but a later assignee (alice) opts in, **no review runs** — comment: "a later reviewer's opt-in must not hijack whose options the review runs with." `test_non_assigned_requester_follows_the_canonical_reviewer` codifies the same rule. `test_the_two_toggles_gate_their_reviews_independently` verifies both toggles resolve off "the one acting reviewer."
- **Impact:** The finding's suggested fix ("select the first resolved assignee with `stamphog_review_inbox_prs` enabled") would directly reverse this tested maintainer decision and split Stamphog's eligibility model away from ReviewHog's (which shares `_resolve_assigned_reviewer`), making the two toggles resolve differently. The reviewer's observation rests on the PR description's loose prose ("any assigned user"); the actual, intended, test-covered behavior gates on the single canonical acting reviewer. Premise-is-intended-design → drop (precision over recall). Any real gap here is at most PR-description wording, not a code defect ReviewHog should surface.

### [✅ VALID] should_fix (validator→consider) · bug — products/tasks/backend/facade/api.py:503-505

**Team scoping is applied after an unscoped, nondeterministic task-run lookup**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `find_task_run` searches TaskRun rows across all teams and returns the first matching URL or repository/branch row; only afterward does this facade reject a result from another team. If multiple teams have runs referring to the same repository and PR URL or branch, the unscoped lookup can select the other team's row and return `None` even though the requested team has a valid matching run. Branch lookup also has no ordering, making the outcome unstable.
- **Suggestion:** Perform the `team_id` restriction inside the TaskRun query. For example, extend `find_task_run` with an optional team scope and apply `filter(team_id=team_id)` before ordering and `.first()`, or implement the lookup directly in this facade with the same matching precedence and deterministic ordering.
- **Validator:** - **Checked:** `find_task_run` (products/tasks/backend/webhooks.py:28-84) and how `find_signal_implementation_run` (facade/api.py diff L1714-1716) consumes it, plus the caller `_inbox_rereview_carve_out` (tasks.py diff L909-918) and its skip path.
- **Found (mechanism is real):** `find_task_run` scopes by `repository` (iexact) but not by team; the pr_url leg orders by `terminal_rank, -created_at`, and both branch legs call `.first()` with no `order_by` — so branch matching is nondeterministic, and the team check happens only afterward as `run.team_id != team_id → None`. A cross-team row that sorts first therefore yields a false negative for a team that does have a matching run.
- **Found (security property intact):** the post-filter fails closed — it never returns another team's run, so this is a completeness/determinism defect, not an IDOR/tenant-isolation leak.
- **Found (trigger is rare):** a collision needs the same repository connected to two teams. The pr_url leg is practically unreachable for this — a PR URL is globally unique and lands in exactly one run's `output.pr_url` (agent server records its own run; the webhook backstop records a single matched run), so two teams sharing the same `output.pr_url` essentially cannot occur. The branch leg is the only real vector and is only reached when the pr_url leg misses; the sole caller passes `pr_url=pr.html_url` on head-changing deliveries for an already-open PR, so the URL is normally already recorded and the pr_url leg wins.
- **Impact:** worst case is a missed self-driving re-review under a rare cross-team same-repo collision, and it fails safe — `_inbox_rereview_carve_out` returns empty and the skip path still dismisses any standing approval (diff L967-985), so no stale approval survives and nothing unsafe is posted.
- **Priority:** real and cheaply fixable (scope `team_id` inside the query, add deterministic ordering to the branch legs), but the fail-safe outcome gated on a near-unreachable cross-team collision on a globally-unique key doesn't rise to should_fix — recording as `consider`.

### [❌ dismissed] should_fix · bug — tools/pr-approval-agent/reviewer.py:568-568

**Self-driving reviews still include bot-author familiarity signals**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The prompt appends both `familiarity_block` and `self_driving_block`. Hosted runs still call `_attach_familiarity`, so a bot with merged PR history can receive a non-empty familiarity block immediately before text stating that author familiarity and merged-PR history carry no signal. This contradicts the intended replacement behavior and can influence the reviewer using evidence the new provenance block explicitly declares irrelevant.
- **Suggestion:** Suppress familiarity for self-driving runs. For example, skip `_attach_familiarity` when `pipeline.self_driving` is true, or make `_build_review_prompt` render `familiarity_block = ""` whenever `cl.get("self_driving")` is true. Add coverage using a self-driving classification with non-empty familiarity to verify only the provenance block appears.
- **Validator:** - **Checked:** The prompt assembly `{constraint}{familiarity_block}{self_driving_block}` (reviewer.py:568), `_format_familiarity` (reviewer.py:635-645), `_attach_familiarity` (review_local.py:299-303), and the server coupling in `activities.py` that determines whether familiarity can ever be non-empty for a self-driving run.
- **Found:** `run_review_in_sandbox` reads both signals from the SAME `run.output` object: `author_pr_numbers = output.get("author_pr_numbers", [])` (activities.py:396) and `self_driving_review=bool(output.get("inbox_review"))` (PR diff line 1227). `fetch_review_context` sets `author_pr_numbers = ... if author and not is_inbox_review else []` where `is_inbox_review = bool((run.output or {}).get("inbox_review"))` (PR diff lines 1215-1216). So `self_driving=True` ⟺ `inbox_review` truthy ⟹ `author_pr_numbers=[]`, always, within one run.
- **Found:** With `author_pr_numbers=[]`, `_attach_familiarity` returns at `if not raw_prs: return` (review_local.py:302-303) before computing anything, leaving `classification["familiarity"]=None`, and `_format_familiarity` returns `""` for `None` (reviewer.py:643-645). The end-to-end self-driving test asserts `context["author_pr_numbers"] == []`.
- **Impact:** The stated contradiction — a non-empty familiarity block sitting next to the "familiarity carries no signal" provenance text — cannot occur for hosted self-driving runs; `familiarity_block` is always `""` there, so appending both blocks is harmless. The premise ("a bot with merged PR history can receive a non-empty familiarity block") is unreproducible given the server coupling. Adding a redundant `familiarity_block=""` guard keyed on `self_driving` is defensive future-proofing against a state the code already rules out — drop per the criteria.

### [❌ dismissed] should_fix · performance — products/tasks/backend/facade/api.py:505-505

**Replica lag can permanently suppress inbox re-reviews**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The new re-review gate calls `find_task_run` through the default read router. This lookup runs after writes to the task/run and determines whether a webhook is recognized as self-driving. If a replica has not received those writes yet, it returns `None`; the webhook path then treats the PR as ordinary, marks the delivery processed, and never retries the lookup. A transient replica delay therefore becomes a permanently missed review.
- **Suggestion:** Pin this gating lookup to the writer, for example by adding a database alias parameter to `find_task_run` and using `TaskRun.objects.using(router.db_for_write(TaskRun))` for each query in this facade path. This matches the writer-pinned reads already used before Stamphog run creation.
- **Validator:** - **Checked:** DB routing for `TaskRun` (`products/db_routing.yaml`, `posthog/product_db_router.py`, `posthog/dbrouter.py`), the sole caller `_inbox_rereview_carve_out`, `find_task_run`'s match legs (`webhooks.py:28-84`), and the skip path's approval handling.
- **Found (premise not in place):** `tasks` is not routed to a product DB — `products/db_routing.yaml` lists only `stamphog`/`visual_review`/`warehouse_sources_queue`. `TaskRun` reads go through `ReplicaRouter.db_for_read`, which returns `"default"` (primary) for any model not in the `READ_REPLICA_OPT_IN` env list (`posthog/dbrouter.py:22-31`). The stamphog writer-pin invariant the finding cites applies because stamphog's product DB always reads a replica; that does not transfer to a main-DB model.
- **Found (convention):** `find_task_run` is the same function the primary webhook path (`handle_pull_request_event`) already uses for run recognition, and it is not writer-pinned — evidence the product does not treat `TaskRun` reads as replica-lagged.
- **Found (mechanism defeated):** `find_signal_implementation_run` passes both `pr_url` and `head_branch`; the branch leg matches `TaskRun.branch`, set at run creation. A lagged `output.pr_url` write therefore cannot yield `None`. Only a fully-unreplicated run row (created within the ~<100ms lag) could, which cannot coincide with a `synchronize`/`reopen`/base-retarget delivery on an already-open PR — the only deliveries the carve-out handles (`opened` is excluded).
- **Impact:** the described replica-read is not established for this main-DB model, the trigger is practically unreachable, and even a hypothetical miss fails safe (stale approval dismissed on the skip path, diff L967-985) and self-heals on the next push — so it is neither permanent nor unsafe. Speculative + unreachable + fail-safe ⇒ below the keep bar.

### [✅ VALID] must_fix · bug — products/review_hog/backend/receivers.py:111-138

**Inbox implementation runs are rejected before either review is queued**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The new ReviewHog and Stamphog dispatch logic is unreachable for the self-driving Inbox flow. `products/signals/backend/auto_start.py` creates implementation tasks with `internal=True`, while this receiver returns earlier when `task.internal` is true. Consequently, saving the PR URL for the intended Inbox task queues neither review, regardless of either toggle.
- **Suggestion:** Replace the blanket `task.internal` rejection with a positive check that identifies the report's implementation task, such as the recorded implementation task/run association or the task's signal-report origin and implementation stage. Continue excluding research, repository-selection, and custom-agent plumbing tasks.
- **Validator:** - **Checked:** How the self-driving implementation task is created (`products/signals/backend/auto_start.py`), whether `internal` flows through unchanged (`products/tasks/backend/facade/api.py`, `products/tasks/backend/models.py`), every creator of a signals implementation task, and the receiver gate at PR-head `receivers.py:104`.
- **Found:** `auto_start.py:310-327` creates the PR-opening implementation task — `title="Implementation: …"`, `ai_stage="implementation"`, `interaction_origin="signal_report"` (comment: "Makes the agent auto-push and open a draft PR") — with an explicit `internal=True` (comment: "Internal so the run stays out of the default task list"). The flag passes through unchanged: `create_and_run_task(internal=…)` → `Task.create_and_run(internal=…)` → the `Task.internal` column (facade `api.py:888`, model `models.py`). A grep for `ai_stage="implementation"` + `interaction_origin="signal_report"` shows `auto_start.py` is the _only_ producer of this task; the other pipeline tasks are also internal (`repo_selection/agent.py:468` `internal=True`). No production code ever sets a signal-report task's `internal=False` — only `seed_inbox_data.py:279` and the test helper (`_task(internal=False)`).
- **Found:** The receiver's guard `if task.internal: return` (PR-head `receivers.py:104`) sits before both the ReviewHog (`review_inbox_prs`) and Stamphog (`stamphog_review_inbox_prs`) dispatches, and its justifying comment — "the auto-start implementation task is the only non-internal signal-report task" — is directly contradicted by `auto_start.py:327`.
- **Impact:** For the self-driving flow the PR targets (Case 1: bot opens a draft PR, its run saves `output.pr_url`), `instance.task.internal` is `True`, so the receiver early-returns and queues **neither** review regardless of either toggle. This is the feature's primary path, not an edge case — a genuine correctness/reachability bug. The suggested fix is grounded: `auto_start.py:337` already writes a `SignalReportTask` implementation-run association (`record_implementation_task`) that could serve as the positive identifier instead of the `internal` heuristic. The gate predates this PR, but the new Stamphog dispatch inherits the same unreachability, so must_fix stands.

### [❌ dismissed] must_fix · bug — products/stamphog/backend/tasks/tasks.py:1182-1192

**Queued initial reviews ignore toggle changes before execution**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The asynchronous task trusts the opt-in resolved before dispatch and stamps the supplied acting_user_id without checking the current setting. If the task is delayed or retried after that reviewer disables inbox reviews, it can still start a review and potentially approve the PR, unlike the webhook path which deliberately re-resolves the toggle for every delivery.
- **Suggestion:** Before creating or resuming an inbox ReviewRun, call the registered acting-reviewer resolver with team_id, signal_report_id, and the task creator identity obtained from a verified task run. Stop without reviewing when it returns None, and use the newly resolved user ID in the provenance rather than the queued value.
- **Validator:** - **Checked:** the initial leg `process_inbox_pr_review` (tasks.py diff L1061-1176) against the webhook carve-out's per-delivery toggle re-resolution; the receiver's dispatch-time check (`receivers.py` diff L186-211); the task's retry config (diff L1091-1096); and the role of the toggle vs. the stale-approval safety net.
- **Found (window is tiny and the check just happened):** the receiver evaluates `settings.stamphog_review_inbox_prs` and only then schedules the Celery dispatch on commit, so the initial review runs seconds later (retries add ~5s, or ≥60s on rate-limit, max 3). The reviewer would have to disable the toggle inside that narrow window, having affirmatively enabled it at the moment their self-driving PR opened.
- **Found (asymmetry is by design, not oversight):** the webhook path re-resolves because it handles deliveries across the PR's entire lifetime (Case 3 — the toggle can flip days later); the initial leg is a one-shot at open time where the toggle was just checked. The author explicitly split these (carve-out docstring: 'the initial review is the receiver leg's job') and handles toggle-off-mid-PR through dismissal on the next head-changing delivery, stating 'safety is never preference-gated' (diff L878-883).
- **Found (core invariant intact):** an initial approval is pinned to the head it actually reviewed, so it never violates the 'no approval over unreviewed commits' invariant; and if the reviewer has since opted out, the next push's skip-path retraction dismisses it. The stamped `acting_user_id` is provenance/attribution only — it grants no privilege.
- **Impact:** the sole gap is honoring a user _preference_ changed within a seconds-to-few-minutes race, where the approval already reflects a genuine review and is dismissed on the next push. That is a speculative, low-impact defensive check on a preference — not a correctness/security defect real inputs will meaningfully hit. The must_fix 'potentially approve' framing overstates it; falls below the keep bar.

### [❌ dismissed] should_fix · best_practice — tools/pr-approval-agent/reviewer.py:568-568

**Self-driving prompt still includes human-author ownership signals**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The prompt still renders the ownership block before the self-driving provenance block. For bot authors, `_summarize_ownership` will commonly set `author_on_owning_team` to false, producing `Author is NOT on the owning team`, immediately before the new block says org membership carries no signal. This contradictory trusted context can make the reviewer treat machine authorship as a reason to escalate or refuse, despite the carve-out intending to judge the diff independently.
- **Suggestion:** Keep path ownership and suggested owners, but suppress the author-team-membership note when `self_driving` is true, for example by passing that flag into `_format_ownership` and omitting only the `author_on_owning_team` branch.
- **Validator:** - **Checked:** `_format_ownership` (reviewer.py:683-700), `_summarize_ownership` (review_pr.py:602-635), the `author_on_owning_team` computation, and the provenance text in `_format_self_driving` (PR diff).
- **Found:** The finding's factual premise holds: for a bot author on team-owned paths, `check_team_membership` matches no team, so `_summarize_ownership` sets `author_on_owning_team=False` (review_pr.py:634) and appends "author <bot> is not on any owning team" (line 629), and `_format_ownership` emits "NOTE: Author is NOT on the owning team" (reviewer.py:696-697). Ownership is not gated on `self_driving`, so this text does render before the provenance block.
- **Found (mitigation):** The provenance block explicitly names and neutralizes this very signal — "The author is a machine user, so author familiarity, org membership, and merged-PR history carry no signal here — judge the diff strictly on its own merits" — and is rendered immediately after the ownership block. The prompt already instructs the model to disregard membership; this is deliberate design, not an oversight (familiarity was suppressed by data, membership is neutralized by directive).
- **Impact:** The only residual risk is the LLM weighting "not on owning team" as an escalation reason despite an explicit adjacent instruction to ignore org membership — a speculative instruction-following failure with no deterministic wrong-output, on an unmeasured prompt-quality axis. The path-ownership content is legitimately retained; suppressing just the membership note is prompt-tuning taste. Per the criteria (speculative what-if, already-handled by the provenance directive, precision-over-recall on the fence), this does not meet the bar.
