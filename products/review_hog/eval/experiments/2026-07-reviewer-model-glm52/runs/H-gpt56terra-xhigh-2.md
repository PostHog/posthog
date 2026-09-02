# Reviewer-quality run — `H-gpt56terra-xhigh-2`

- **Dumped:** 2026-07-30T14:26:18+00:00
- **Report id:** `019fb34f-1d26-7355-b8d3-9d248a5f7382` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `1341596e721880256a1afb79bbc881364d00e302` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1849s (30.8 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-terra` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 13           | 11         | 10          | 3                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model           | stage                       | gens    | fresh in      | cache write | cache read    | output      | >200K gens | true $     | gw $       |
| --------------- | --------------------------- | ------- | ------------- | ----------- | ------------- | ----------- | ---------- | ---------- | ---------- |
| claude-opus-4-8 | validation                  | 98      | 89,531        | 581,480     | 9,909,389     | 135,036     | 3          | $12.41     | $12.41     |
| gpt-5.6-terra   | review                      | 99      | 5,403,492     | 0           | 0             | 33,121      | 0          | —          | $4.09      |
| gpt-5.6-terra   | blind-spot                  | 41      | 2,675,142     | 0           | 0             | 12,880      | 0          | —          | $1.62      |
| claude-sonnet-5 | dedup                       | 1       | 6,555         | 0           | 0             | 2,346       | 0          | $0.04      | $0.04      |
| claude-sonnet-5 | other:perspective_selection | 1       | 5,981         | 0           | 0             | 506         | 0          | $0.02      | $0.02      |
| gpt-5.6-terra   | other                       | 18      | 0             | 0           | 0             | 0           | 0          | —          | $0.00      |
| **total**       |                             | **258** | **8,180,701** | **581,480** | **9,909,389** | **183,889** | **3**      | **$12.47** | **$18.17** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = +0.0%.
- `true $` total excludes unpriced model `gpt-5.6-terra` (158 gen(s), gw $5.71).
- naive method (all prompt tokens at input price): $56.33 — 4.5× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $14.0800 over 258 gen(s) (true $9.0617, Δ +55.4%)
  - · of which cache read: $6.6412 over 217 gen(s) (true $4.9547, Δ +34.0%)
  - · of which cache write: $3.6342 over 98 gen(s) (true $3.6342, Δ +0.0%)
  - · of which fresh (derived): $3.8046 over 258 gen(s) (true $0.4727, Δ +704.8%)
  - output: $4.0944 over 258 gen(s) (true $3.4044, Δ +20.3%)
- 3 gen(s) ran with >200K-token prompts; the gateway map prices these models flat, so no long-context premium is included in either column.

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | step                | first gen | t1 cache read | t1 cache write | models          |
| --------- | ------------------- | --------- | ------------- | -------------- | --------------- |
| …e4525e54 | issues-review-p1-c1 | 13:56:28  | 0             | 0              | gpt-5.6-terra   |
| …07479a57 | issues-review-p3-c1 | 13:56:29  | 0             | 0              | gpt-5.6-terra   |
| …8aa2db59 | issues-review-p1-c2 | 13:56:30  | 0             | 0              | gpt-5.6-terra   |
| …d473268f | issues-review-p3-c2 | 13:56:32  | 0             | 0              | gpt-5.6-terra   |
| …0cfc5bae | issues-review-p1-c3 | 13:56:33  | 0             | 0              | gpt-5.6-terra   |
| …1456e131 | issues-review-p3-c3 | 13:56:35  | 0             | 0              | gpt-5.6-terra   |
| …2c355ad5 | issues-review-p2-c3 | 13:56:35  | 0             | 0              | gpt-5.6-terra   |
| …c85e1dcc | issues-review-p2-c1 | 13:56:52  | 0             | 0              | gpt-5.6-terra   |
| …b8f46018 | issues-review-p2-c2 | 13:57:14  | 0             | 0              | gpt-5.6-terra   |
| …aaa56694 | issues-review-p2-c2 | 13:59:13  | 0             | 0              | gpt-5.6-terra   |
| …d90c8e13 | issues-review-p3-c2 | 13:59:15  | 0             | 0              | gpt-5.6-terra   |
| …4ec205eb | issues-review-p3-c3 | 13:59:20  | 0             | 0              | gpt-5.6-terra   |
| …30843af8 | issues-review-p3-c1 | 13:59:21  | 0             | 0              | gpt-5.6-terra   |
| …50a73a9b | issues-review-p2-c1 | 13:59:27  | 0             | 0              | gpt-5.6-terra   |
| …de2b5903 | blind-spots-c3      | 14:01:28  | 0             | 0              | gpt-5.6-terra   |
| …85ea81a3 | blind-spots-c2      | 14:01:29  | 0             | 0              | gpt-5.6-terra   |
| …abd5ca8b | blind-spots-c1      | 14:01:32  | 0             | 0              | gpt-5.6-terra   |
| …c7aca92b | blind-spots-c4      | 14:01:49  | 0             | 0              | gpt-5.6-terra   |
| …ac4b02c7 | validation-c3       | 14:05:05  | 0             | 37,006         | claude-opus-4-8 |
| …219e01a4 | validation-c1       | 14:05:05  | 0             | 37,320         | claude-opus-4-8 |
| …0ef6e565 | validation-c4       | 14:05:06  | 17,141        | 19,534         | claude-opus-4-8 |
| …a159aaf0 | validation-c2       | 14:05:15  | 17,141        | 20,662         | claude-opus-4-8 |

- units with turn-1 cache_read > 0: **2/22** (report the distribution, not a median).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 6s       |
| review wave (perspectives)  | 5m 06s   |
| blind-spot sweep            | 2m 58s   |
| dedup (incl. combine/clean) | 24s      |
| validation                  | 21m 29s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 8m 04s — the reviewer-model speed comparison number.
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
| 1    | 2     | review-hog-perspective-contracts-security      | 2          |
| 1    | 3     | ?                                              | 0          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 1          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 3    | 3     | ?                                              | 0          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | ?                                              | 0          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | review-hog-blind-spots-general                 | 1          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] must_fix · bug — products/review_hog/backend/receivers.py:144-153

**Select an opted-in assignee for Stamphog**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The Stamphog resolver first selects one canonical acting reviewer, then checks only that user's toggle. This contradicts the feature contract that Stamphog should run when at least one assigned reviewer has opted in: if the task creator (or first resolved assignee) is opted out while another assigned reviewer is opted in, both the initial dispatch and webhook re-reviews are skipped.
- **Suggestion:** Resolve the assigned reviewers first, then choose an assignee with `stamphog_review_inbox_prs=True` (preserving the existing creator/ordering preference among opted-in users). Use that same resolver for the initial TaskRun dispatch as well as the webhook hook, so both paths honor the any-assignee opt-in rule.
- **Validator:** - **Checked:** The real PR diff for `products/review_hog/backend/receivers.py` (`_resolve_assigned_reviewer`, `resolve_stamphog_acting_reviewer`, and the `handle_task_run_saved` dispatch), plus the pre-existing acting-reviewer contract in `products/review_hog/backend/tests/test_inbox_trigger.py` on master, and the stamphog facade `queue_inbox_pr_review`.
- **Found:** The single-canonical-acting-reviewer gate is a deliberate, tested invariant, not an accident. Master's `test_opted_out_canonical_reviewer_blocks_the_review` asserts exactly the scenario the issue calls a bug — reviewers `["bob","alice"]`, bob (canonical) opted out, alice opted in → `mock_start.assert_not_called()` — with the comment "The canonical assignee's toggle is THE gate ... a later reviewer's opt-in must not hijack whose options the review runs with." The stamphog leg reuses this exact resolution: `resolve_stamphog_acting_reviewer`'s docstring says "Same acting-reviewer resolution as this module's own trigger," and the PR's own test comment reads "the two toggles on the one acting reviewer gate their reviews independently."
- **Found:** The gate is not separable from identity as the suggestion assumes. `queue_inbox_pr_review(..., acting_user_id=...)` runs the stamphog review under one specific user's identity/config, just like ReviewHog. The suggestion's "choose an assignee with `stamphog_review_inbox_prs=True` (preserving the creator/ordering preference among opted-in users)" is precisely the "hijack" the maintainer decision (documented, 2026-07-02/03) forbids: it would either run under a canonical user who didn't opt in, or re-pick the canonical acting reviewer based on opt-in status — breaking the tested ReviewHog selection.
- **Impact:** The finding rests on treating the PR description's loose phrase "at least one of the assigned users has stamphog_review_inbox_prs enabled" as the authoritative contract. The actual code-level contract — encoded in comments and existing tests — is the single-canonical-acting-reviewer model. The flagged behavior is intended, so this is a mistaken-premise finding (precision-over-recall: drop), not a correctness or contract break.

### [✅ VALID] should_fix · security — tools/pr-approval-agent/review_pr.py:475-477

**Suppress author familiarity for self-driving reviews**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** Setting `classification["self_driving"]` does not actually replace the human-author trust signal. `run()` still calls `_maybe_compute_familiarity()` before every LLM review, and for T1 self-driving PRs it stores the bot account's git-history familiarity in `classification["familiarity"]`. The prompt therefore renders the normal “Author familiarity” block immediately before the new provenance block, despite the latter claiming familiarity is deliberately absent. A long-lived machine account can consequently be presented as familiar with modified code and influence the review verdict.
- **Suggestion:** When `self_driving` is enabled, skip `_maybe_compute_familiarity()` (or explicitly leave `classification["familiarity"]` as `None`) so `_format_familiarity()` renders nothing. Keep provenance as the sole author-related context for this path.
- **Validator:** - **Checked:** Working tree is master (PR 75215 not checked out), so I verified against `gh pr diff 75215` combined with the unchanged `familiarity.py`/`reviewer.py` code. Traced the self-driving path through `Pipeline.run()` → `_maybe_compute_familiarity()` → `_compute_familiarity()` → `compute_familiarity()` → `Reviewer._build_review_prompt()`.
- **Found:** The PR relaxes only the bot-author refusal and draft gate. `run()` still calls `_maybe_compute_familiarity()` unconditionally before `_llm_review()` (`review_pr.py:240-242`). `_maybe_compute_familiarity()` (`review_pr.py:510-521`) is untouched by the PR and, for `tier == "T1-agent"`, writes the signal into `classification["familiarity"]` with **no `self_driving` guard**. `_compute_familiarity()` passes `author_login=pr.author` — the bot login — into `compute_familiarity()` (`review_pr.py:523-534`).
- **Found:** `compute_familiarity()` returns a populated object whenever `gh pr list --author <bot> --state merged` succeeds (`familiarity.py:88,438-520`); band is MODERATE/STRONG once the bot has merged PRs overlapping the touched paths. `_format_familiarity()` then renders the full "Author familiarity with the changed code … band STRONG; author last-touched X% of the lines …; N merged PRs in these paths" block for any non-NONE band (`reviewer.py:643-680`). The prompt appends both blocks — `{familiarity_block}{self_driving_block}` — while the new provenance block asserts "author familiarity, org membership, and merged-PR history carry no signal here" (`_format_self_driving`). The two TRUSTED blocks directly contradict, and the PR's own `__init__` comment states self_driving should make the prompt "carry the provenance instead of human-author trust signals" — intent not delivered.
- **Impact:** For the common case (a self-driving code PR classified T1-agent), a long-lived machine account that has accrued merged-PR history in the touched paths is presented to the reviewer LLM as familiar/trusted. Per `familiarity.py`'s own docstring the signal exists so "ownership norms can treat strong familiarity like owning-team membership" — i.e. it nudges toward approval, which is exactly the machine-account trust-laundering the bot-author refusal (and this carve-out's provenance framing) is meant to prevent on an auto-approval path. Reachable and realistic, not a contrived edge case.
- **Found:** The PR's tests do not catch this: `test_prompt_provenance_renders_only_for_self_driving_runs` hardcodes `familiarity: None`, and `test_self_driving_flag_reviews_the_bot_authored_draft` stubs `_llm_review` with an empty diff — so the familiarity/provenance interaction is untested and the defect ships live. The suggested fix (skip `_maybe_compute_familiarity()` or force `classification["familiarity"]=None` when `self_driving`) is correct and self-contained.

### [✅ VALID] must_fix · bug — products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py:7-9

**Rebase this migration onto the current leaf**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The app already has `0019_reviewreport_author_login_and_more.py`, and `max_migration.txt` identifies it as the current leaf. Depending on `0018` here creates two migration leaves; subsequent `makemigrations` reports conflicting migrations and blocks normal migration development.
- **Suggestion:** Rename this migration to `0020_...`, depend on `0019_reviewreport_author_login_and_more`, and update `products/review_hog/backend/migrations/max_migration.txt` to the new migration name.
- **Validator:** - **Checked:** The PR's migration file and `max_migration.txt` patch against the current `master` state of `products/review_hog/backend/migrations/` (directory listing, `max_migration.txt`, and the dependency block of the master `0019`).
- **Found:** The conflict is real on master, not hypothetical. Master's `max_migration.txt` reads `0019_reviewreport_author_login_and_more`, and that file exists with `dependencies = [("review_hog", "0018_backfill_urgency_threshold_to_consider")]`. The PR adds `0019_reviewusersettings_stamphog_review_inbox_prs.py` (L7-9) depending on the _same_ `0018_backfill_urgency_threshold_to_consider`, and rewrites `max_migration.txt` from `0018...` to the stamphog name. Two migrations therefore branch off `0018` → two leaf nodes.
- **Impact:** Once this branch takes in master, Django's migration-graph check reports "Conflicting migrations detected; multiple leaf nodes" — `makemigrations --check` and the repo's `max_migration.txt` CI guard fail, and `migrate` refuses without a merge migration, blocking the PR and normal migration development. The PR's own `mergeable_state: "dirty"` is consistent with the `max_migration.txt` git conflict (master `...author_login` vs PR `...stamphog`). This is a concrete reliability/build-breaking defect that will occur, not speculation.
- **Priority:** `must_fix` is correct — the suggested fix (renumber to `0020_...`, depend on `0019_reviewreport_author_login_and_more`, point `max_migration.txt` at the new name) is the standard resolution and is required for the branch to merge.

### [❌ dismissed] must_fix · security — products/review_hog/backend/receivers.py:124-138

**Validate the initial inbox PR before granting the carve-out**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** This dispatch passes only a PR URL and IDs to Stamphog. The queued initial-review path fetches that URL and stamps it as `inbox_review`, but does not receive or verify the task repository, head repository, or expected bot author. That provenance enables the engine's self-driving carve-out, which bypasses its normal bot/draft/author-trust gates. A self-driving task output that points at another open PR in a configured repository can therefore cause Stamphog to review and potentially approve a PR that was not created by that Inbox task.
- **Suggestion:** Pass the task repository (and preferably the run identity for a server-side lookup) into the queue task, then verify the fetched PR is repo-native, belongs to that exact repository, and is authored by the expected App bot before setting `inbox_review` or starting a review. Treat any mismatch as a no-op.
- **Validator:** - **Checked:** `process_inbox_pr_review` (the initial leg) in `products/stamphog/backend/tasks/tasks.py`, the webhook re-review leg `_inbox_rereview_carve_out` in the same file, `find_signal_implementation_run` in `products/tasks/backend/facade/api.py`, and both writers of `TaskRun.output['pr_url']` (`products/tasks/backend/webhooks.py` `find_task_run` / `_record_run_pr_url`, and the agent-server path described in `receivers.py`'s module docstring).
- **Found:** The premise is factually right that the initial leg does no bot-author/fork/task-linkage recheck — it derives the repo from the URL via `_parse_pr_url`, resolves a synced+enabled config, fetches the PR, and stamps `inbox_review`. But the two legs have different trust anchors, and the checks are only load-bearing for the webhook leg. `_inbox_rereview_carve_out` verifies `_is_bot_authored`, fork-safety (`head_repo == repo`), and `find_signal_implementation_run` precisely because it is the entry point for _arbitrary_ incoming PR webhook events. The initial leg is not: `handle_task_run_saved` fires only for a non-internal task with a `signal_report_id` (receivers.py L82-89), and the `pr_url` it forwards is that already-identified self-driving run's own recorded `output.pr_url`.
- **Found:** The trigger the issue needs — `output.pr_url` pointing at a PR _not_ created by the task (a human/fork PR the carve-out could then approve) — is ruled out by both writers. The webhook backstop records `output.pr_url` only when `head_repo_full_name == repository_full_name` (fork-safe) and the run matched within `task.repository` (webhooks.py:179-186), and the agent-server path records the PR the App bot actually opened for the task (repo-native, bot-authored). So the stored field the initial leg trusts already carries the bot-authored + repo-native + task-linked invariants the issue asks to re-verify.
- **Impact:** For the described escalation to occur, a _trusted_ producer (agent server / webhook backstop) would have to write a foreign PR URL onto the run — a what-if against an upstream-guaranteed invariant, not a reachable path via any shown call site. This is the same trust in `output.pr_url` the pre-existing ReviewHog inbox leg already relies on, so no new reachable attack surface is introduced. Tenant isolation is independently enforced (`for_team` scoping + `find_signal_implementation_run`'s `team_id` recheck), bounding any blast radius to within-tenant even if the invariant were violated. Under precision-over-recall this is defensive/speculative hardening rather than a demonstrable auth-bypass, so it does not meet the keep bar.

### [❌ dismissed] must_fix · documentation — products/stamphog/README.md:14

**Do not document the inbox StampHog integration before it exists**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** This says the inbox receiver calls a `queue_inbox_pr_review` StampHog facade and that later webhook deliveries use an inbox carve-out, but neither that facade nor `facade/inbox_hooks.py` exists in this checkout. The actual StampHog webhook path still unconditionally rejects draft and bot-authored PRs in `_review_skip_reason`, and the existing inbox receiver starts a ReviewHog workflow instead. Users following this documentation will enable a toggle and expect reviews that can never run.
- **Suggestion:** Land the documented facade, provenance flag, resolver, and webhook/engine exceptions in the same change, or remove this carve-out documentation until those paths are implemented. Keep the setting name and entry point aligned with the implemented API.
- **Validator:** - **Checked:** The PR diff for all files the finding names — `products/stamphog/backend/facade/api.py`, `facade/inbox_hooks.py`, `backend/tasks/tasks.py` (`_review_skip_reason`), and `products/review_hog/backend/receivers.py` — plus the migration/model/engine/test files, via `gh pr diff 75215`.
- **Found:** The facade IS added — `+def queue_inbox_pr_review(` in `facade/api.py` (diff ~L687), and `facade/inbox_hooks.py` is a brand-new file (`new file mode 100644 ... products/stamphog/backend/facade/inbox_hooks.py`, diff L720-725) exporting `register_inbox_acting_reviewer_resolver`/`get_inbox_acting_reviewer_resolver`. The reviewer's core premise ('neither that facade nor `facade/inbox_hooks.py` exists in this checkout') is factually wrong against the PR.
- **Found:** `_review_skip_reason` no longer 'unconditionally rejects' bots — the PR DELETES the `user.get("type") == "Bot"` lines from it (diff L943-944) and the handler overrides the skip: `carve_out = _inbox_rereview_carve_out(...)` then `if skip_reason is not None and inbox_review is None:` (diff L956-967). Draft/bot carve-out is implemented via `_InboxCarveOut`/`_inbox_rereview_carve_out`.
- **Found:** The receiver does not run ReviewHog 'instead' — `receivers.py` gates the ReviewHog leg on `settings.review_inbox_prs` AND adds `_start_stamphog_review(...)` → `queue_inbox_pr_review` gated on `settings.stamphog_review_inbox_prs`, and registers `resolve_stamphog_acting_reviewer` via `register_inbox_acting_reviewer_resolver` at `connect()`.
- **Found:** The provenance flag, migration, and tests all land in the same PR: `stamphog_review_inbox_prs` BooleanField (models.py), migration `0019_reviewusersettings_stamphog_review_inbox_prs`, and coverage in `test_inbox_trigger.py`/`test_tasks.py`/`test_integration.py`. Doc names/entry points match the implemented API (`queue_inbox_pr_review`, `stamphog_review_inbox_prs`, `facade/inbox_hooks.py`).
- **Impact:** The finding is a false positive: the documented facade, resolver, provenance flag, webhook carve-out, and engine/skip exceptions are all implemented within this same PR, so users following the docs will not 'enable a toggle and expect reviews that can never run.' The reviewer's premise reproduces only against an incomplete tree — my own checkout resolved the PR head sha `1341596e` as a 'bad object' (stuck at master `d24a844e`), which is the likely source of the stale-checkout error. Does not meet the bar (Wrong / unreproducible).

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1125-1245

**Verify inbox provenance before bypassing normal PR trust gates**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The initial-review worker treats all of its arguments as trusted. It resolves only a team-owned repo config and fetches the referenced PR; it never verifies that `task_run_id` and `signal_report_id` identify a non-internal signals implementation run for this team, that the run produced this exact PR, or that the PR is bot-authored with a repo-native head. Consequently, any caller that can cause a TaskRun output/receiver invocation with a GitHub URL can mint an `inbox_review` run for an arbitrary PR in a configured repository. That provenance enables the engine's bot/draft carve-out and bypasses the normal author-association, review-mode, and write-permission protections, potentially allowing an approval on an untrusted fork or unrelated PR.
- **Suggestion:** Before creating or restarting a run, fetch and validate the supplied run through `find_signal_implementation_run` (and require its run ID and signal report ID to equal the task arguments), then require the fetched PR to be bot-authored and `pr.head.repo.full_name` to equal the configured repository. Return without creating a run when any check fails. This should mirror the positive-identification checks already used by `_inbox_rereview_carve_out`.
- **Validator:** - **Checked:** Compared `process_inbox_pr_review` (PR tasks.py:1109-1245) against the webhook carve-out `_inbox_rereview_carve_out` (tasks.py:144-215); traced the engine gate in temporal/activities.py; traced the caller `handle_task_run_saved`/`_start_stamphog_review` (review_hog receivers.py:70-140, 205-230); traced both writers of `output.pr_url` (agent output API `set_task_run_output` in tasks/facade/api.py:2203 and the webhook backstop in tasks/webhooks.py:130-198); read `find_signal_implementation_run` (tasks/facade/api.py:484-516).
- **Found:** The receiver leg stamps `inbox_review` provenance from the caller args + fetched PR with none of the positive-identification the webhook leg performs — no `_is_bot_authored`, no `head.repo.full_name == repo` fork check, no `find_signal_implementation_run` run→PR linkage. `self_driving_review=bool(output.get("inbox_review"))` (activities.py:451) is the _sole_ gate unlocking the engine's bot/draft carve-out, and its own comment (activities.py:448-450) asserts "both trigger paths stamp only after positively linking the PR to a signals implementation run" — false for this leg.
- **Found:** `output.pr_url` is explicitly caller-controlled (api.py:5768) and `set_task_run_output` (api.py:2203-2226) persists it with no repo-native/fork/authorship validation. The backstop's fork check (webhooks.py:180-186) guards only the _backstop_ write, not the agent output-API write — so my earlier hypothesis that fork URLs can't reach `output.pr_url` does not hold for the agent path.
- **Found (reviewer overstatement, non-fatal):** The caller binds `task_run_id`/`signal_report_id` to the run's own real values and already enforces `not task.internal` + signal-report + assigned-reviewer (receivers.py:95-140), so those IDs aren't attacker-supplied. But the _PR→run linkage_ and bot/fork gates remain absent, which is the real defect.
- **Impact:** An actor controlling `output.pr_url` on a qualifying run (a non-internal signal-report run with an opted-in assigned reviewer — reachable via the agent output API over untrusted signal content, the codebase's modeled prompt-injection surface) can aim a gate-bypassing, approval-capable `self_driving` review at an arbitrary or fork PR in any team-configured Stamphog repo. An APPROVE posts a real GitHub approval that can satisfy required reviews with zero humans — exactly the harm the fork/author-association gates and the webhook leg's positive-identification exist to prevent, and a break of the product's documented central approval invariant. Suggested fix (mirror the webhook leg: `find_signal_implementation_run` with matching run/report IDs + bot-author + repo-native head) is on point.

### [❌ dismissed] should_fix — products/stamphog/backend/tasks/tasks.py:1107-1110

**Re-check the opt-in when the asynchronous task executes**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The opt-in is checked before Celery dispatch, but the task can execute or retry after that reviewer has disabled the toggle. `process_inbox_pr_review` receives `acting_user_id` but never consults the registered resolver or otherwise confirms that the user is still authorized. A queued initial review can therefore run after the user has revoked the preference that is intended to gate these reviews.
- **Suggestion:** At the start of the task, resolve the current acting reviewer using the inbox hook and the supplied team/report/run context. Abort unless it still resolves to the expected acting user (or otherwise explicitly represents a currently opted-in authorized reviewer).
- **Validator:** - **Checked:** `process_inbox_pr_review` (tasks.py:1109-1245) for any execution-time toggle re-check; the receiver's dispatch-time gate (review_hog receivers.py:126 `settings.stamphog_review_inbox_prs`); the webhook re-review re-check (tasks.py:201-207); the carve-out docstring's stance on preference vs safety (tasks.py:147-166); and what happens to an approval posted after opt-out (tasks.py:894-908 opt-out skip retraction; the ready_for_review note in the carve-out docstring).
- **Found:** The observation is factually correct — the task consumes `acting_user_id` only to stamp provenance (tasks.py:1180) and never re-resolves the toggle; retries (`max_retries=3`, rate-limit `countdown=max(retry_after,60)`) can widen the dispatch→execute window to ~a minute.
- **Found (defeating):** The toggle is a _preference_, not a safety gate — tasks.py:165 states "safety is never preference-gated." The review only ever runs on the team's own positively-identified self-driving bot draft, and any approval is head-pinned to the exact reviewed head, so it never stands over unreviewed code (the product's central invariant holds regardless of the toggle). A later push after opt-out dismisses the approval through the webhook skip path's `opted_out` branch (`_retract_stale_approvals_on_skip`, tasks.py:894-908).
- **Impact:** The only durable residual case (opt-out landing inside the seconds-to-~minute race AND the draft flipping ready with no intervening push) produces a _valid_ approval over code that was actually reviewed at that head — a momentary preference violation on the team's own PR, with no safety, correctness, or data consequence. That is a narrow, low-impact timing edge case, and the reviewer's authorization/security framing misreads the toggle's role; under precision-over-recall this does not meet the bar.

### [❌ dismissed] should_fix — products/stamphog/backend/tasks/tasks.py:1196-1217

**Serialize head-key deduplication with a PullRequest lock or uniqueness constraint**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The comment says the `select_for_update()` query serializes racing receiver fires, but it locks only matching `ReviewRun` rows. When two tasks process the first review for a head concurrently, there is no existing row to lock, and `ReviewRun` has no uniqueness constraint on `(pull_request, head_sha)`. Both transactions can therefore observe `existing is None`, create separate queued runs, and start duplicate reviews for the same commit.
- **Suggestion:** Lock the `PullRequest` row before querying/creating runs (for example, re-fetch it with `select_for_update()` inside the transaction), or add and handle a database uniqueness constraint for the PR/head identity. Keep the existing-run recovery behavior after acquiring that serialization point.
- **Validator:** - **Checked:** `ReviewRun` model constraints (models.py:140-170), `PullRequest` constraints (models.py:120), `_upsert_pull_request` (tasks.py:319-363), the transaction ordering in `process_inbox_pr_review` (tasks.py:1185-1234), and the webhook path's documented serialization (tasks.py:894-898).
- **Found:** The reviewer is right on the narrow facts — `select_for_update().filter(pull_request=…, head_sha=…)` locks zero rows for the first review of a head, and there is no `(pull_request, head_sha)` uniqueness (models.py:143-170; the only unique field is `delivery_id`, and inbox runs set `delivery_id=None`, tasks.py:1227).
- **Found (decisive):** Serialization is not supposed to come from that query — it comes from `_upsert_pull_request`, which runs first inside the same `transaction.atomic(using=run_write_db)` block (tasks.py:1185-1186). For an existing PR row its clock-gated UPDATE (tasks.py:349-354) takes the `PullRequest` row lock, held to commit; for a new PR row, `get_or_create`'s INSERT blocks on `unique_stamphog_pull_request` (`team_id, repo_config, pr_number`, models.py:120). A second concurrent task blocks there until the first commits, then its existing-run query (tasks.py:1202-1210, READ COMMITTED) sees the winner's committed run and returns. This is the identical mechanism the webhook leg documents and depends on (tasks.py:894-898).
- **Impact:** No duplicate runs for realistic inputs, so the reliability defect the finding describes does not occur. The only unserialized path is `incoming_updated_at is None` (tasks.py:346-348 early-returns before the UPDATE lock) together with a pre-existing PR row — reachable only if the GitHub-fetched PR has no parseable `updated_at`, which never happens for a real PR. The suggested PullRequest lock duplicates protection already in place. Premise mistaken (and the residual is a never-gonna-happen edge) → does not meet the bar.

### [❌ dismissed] should_fix — products/stamphog/backend/tasks/tasks.py:1107-1108

**Retain initial reviews across longer GitHub or Temporal outages**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** This receiver-leg task has no webhook redelivery or other durable recovery path, but it stops retrying after three retries. A GitHub rate-limit window, temporary API outage, or Temporal outage that lasts beyond those attempts permanently loses the initial inbox review; subsequent TaskRun saves are not guaranteed. This is particularly likely for rate limits because the task explicitly waits for GitHub's retry delay before consuming another limited retry.
- **Suggestion:** Use a retry policy appropriate for a durable asynchronous handoff (for example, bounded exponential backoff over a substantially longer window), or persist a recoverable pending-review record that a periodic job can resume. Keep the existing head-keyed dedupe so recovery does not create duplicate reviews.
- **Validator:** - **Checked:** The retry decorator and every retry site in `process_inbox_pr_review` (tasks.py:1109, 1150, 1162, 1165, 1237); the same policy on the sibling webhook tasks (tasks.py:721, 809, 974); the documented recovery model (tasks.py:1124-1128, 1155-1157); the head-keyed re-fire/QUEUED-restart path (tasks.py:1211-1214); and whether any periodic resweep exists (schedules.py wires only the daily digest crontab).
- **Found:** `max_retries=3, default_retry_delay=5` is confirmed — but it is byte-for-byte the retry policy the already-shipped webhook leg `process_pull_request_event` uses (tasks.py:809), so the inbox leg mirrors an accepted pattern, not a new defect. The rate-limit path adapts its countdown to GitHub's `retry_after` (`max(e.retry_after or 0, 60)`, tasks.py:1162), so a single retry that sleeps the window succeeds next attempt — the finding's 'particularly likely for rate limits' is largely defused.
- **Found:** Recovery paths exist beyond the 3 retries: the receiver re-fires on every later `output`-touching TaskRun save carrying the PR URL (including the run-completion save) and the head-keyed dedupe restarts a still-QUEUED run (tasks.py:1211-1214); later pushes re-review through the webhook carve-out. So 'permanently loses' overstates the outcome.
- **Impact:** Worst case is a missed draft-time stamphog pre-review on an experimental, per-user opt-in feature during a sustained (> retry-window) GitHub/Temporal outage — degraded experience only. A review that never runs posts nothing, so there is no stale-approval/safety exposure and no data or correctness impact, and the feature degrades gracefully (next output save or push re-triggers; ReviewHog/human review still apply). Combined with the deliberate, documented retry-don't-drop tradeoff (tasks.py:1155-1157), the suggestion is a robustness enhancement to a system-wide pattern rather than a fix for a user-affecting defect — below the bar under precision-over-recall.

### [❌ dismissed] should_fix — products/stamphog/backend/tasks/tasks.py:1140-1152

**Coalesce repeated receiver dispatches before fetching GitHub**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The TaskRun receiver intentionally re-fires whenever output carrying the PR URL is saved, and every resulting Celery task performs a GitHub GET before it can discover the existing head-keyed run. There is no queue-side debounce or cache, so routine follow-up/output saves can create an unbounded stream of duplicate jobs and GitHub requests for an unchanged PR. At scale this wastes workers and egress budget and can itself trigger the rate-limit failure path.
- **Suggestion:** Add a short-lived per-team/run/PR coalescing key around enqueueing or the initial GitHub fetch, releasing it on failure. The window should only collapse bursty duplicate saves; webhook deliveries should remain the primary path for prompt head-change re-reviews, while a later receiver save can still recover a missed webhook.
- **Validator:** - **Checked:** The receiver's dispatch guards (`handle_task_run_saved` in review_hog/receivers.py — the `"output" not in update_fields` filter, non-internal, signal-report, assigned-reviewer, and `stamphog_review_inbox_prs` gates); the fetch-before-dedupe rationale (tasks.py:1155-1157); the head-keyed dedupe/early-return (tasks.py:1202-1221); and whether any pre-fetch cache already exists.
- **Found:** Dispatches are bounded by output-carrying saves on a non-internal signal-report run with an opted-in reviewer — a handful per run, not the 'unbounded stream' claimed. Saves that don't touch `output` (status flips, log appends via `append_task_run_log`) are filtered out before dispatch. Each redundant dispatch is one read-only `get_pr` GET (tasks.py:1159) plus a dedupe that returns early once a live/delivered run exists.
- **Found:** The fetch necessarily precedes the dedupe because the dedupe key is the PR's current head, which only GitHub knows (tasks.py:1157) — so dedupe-without-fetch requires exactly the cache the finding proposes; the reviewer is right that no such cache exists today.
- **Impact:** A few redundant read-only GitHub reads per PR on an experimental, per-user opt-in feature — negligible against the GitHub App rate budget and dwarfed by the review's own API traffic (files/reviews/checks/clone/post). Not N+1, quadratic, or unbounded on realistic inputs; the rate-limit-trigger claim is speculative and, if ever reached, is absorbed by the existing adaptive retry (tasks.py:1160-1162). This is a future-scaling micro-optimization rather than a defect that bites at real scale — below the bar under precision-over-recall.
