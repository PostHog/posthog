# Reviewer-quality run — `H-gpt56terra-xhigh-1`

- **Dumped:** 2026-07-30T13:16:49+00:00
- **Report id:** `019fb301-3383-7655-8707-db3c6a298dec` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `1341596e721880256a1afb79bbc881364d00e302` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 2784s (46.4 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-terra` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 9            | 8          | 6           | 3                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model           | stage                       | gens    | fresh in      | cache write | cache read    | output      | >200K gens | true $    | gw $       |
| --------------- | --------------------------- | ------- | ------------- | ----------- | ------------- | ----------- | ---------- | --------- | ---------- |
| claude-opus-4-8 | validation                  | 81      | 87,071        | 493,009     | 6,824,774     | 76,279      | 0          | $8.84     | $8.84      |
| gpt-5.6-terra   | review                      | 103     | 5,189,563     | 0           | 0             | 30,181      | 0          | —         | $4.08      |
| gpt-5.6-terra   | blind-spot                  | 35      | 1,953,506     | 0           | 0             | 12,481      | 0          | —         | $1.38      |
| claude-sonnet-5 | other:perspective_selection | 1       | 5,981         | 0           | 0             | 1,234       | 0          | $0.02     | $0.02      |
| claude-sonnet-5 | dedup                       | 1       | 5,646         | 0           | 0             | 765         | 0          | $0.02     | $0.02      |
| gpt-5.6-terra   | other                       | 41      | 0             | 0           | 0             | 0           | 0          | —         | $0.00      |
| **total**       |                             | **262** | **7,241,767** | **493,009** | **6,824,774** | **120,940** | **0**      | **$8.88** | **$14.34** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = -0.0%.
- `true $` total excludes unpriced model `gpt-5.6-terra` (179 gen(s), gw $5.47).
- naive method (all prompt tokens at input price): $38.97 — 4.4× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $11.7777 over 262 gen(s) (true $6.9523, Δ +69.4%)
  - · of which cache read: $4.8604 over 197 gen(s) (true $3.4124, Δ +42.4%)
  - · of which cache write: $3.0813 over 81 gen(s) (true $3.0813, Δ +0.0%)
  - · of which fresh (derived): $3.8360 over 262 gen(s) (true $0.4586, Δ +736.4%)
  - output: $2.5669 over 262 gen(s) (true $1.9270, Δ +33.2%)

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | step                | first gen | t1 cache read | t1 cache write | models          |
| --------- | ------------------- | --------- | ------------- | -------------- | --------------- |
| …1112e67a | issues-review-p3-c3 | 12:31:42  | 0             | 0              | gpt-5.6-terra   |
| …d805036a | issues-review-p2-c3 | 12:31:43  | 0             | 0              | gpt-5.6-terra   |
| …b5f39c1d | issues-review-p2-c1 | 12:31:44  | 0             | 0              | gpt-5.6-terra   |
| …fbcb0a3f | issues-review-p3-c2 | 12:31:45  | 0             | 0              | gpt-5.6-terra   |
| …79cace11 | issues-review-p1-c1 | 12:31:48  | 0             | 0              | gpt-5.6-terra   |
| …355c2238 | issues-review-p2-c2 | 12:31:51  | 0             | 0              | gpt-5.6-terra   |
| …491fb939 | issues-review-p1-c3 | 12:31:54  | 0             | 0              | gpt-5.6-terra   |
| …f6cb2e26 | issues-review-p1-c2 | 12:31:56  | 0             | 0              | gpt-5.6-terra   |
| …079f41ae | issues-review-p2-c3 | 12:34:50  | 0             | 0              | gpt-5.6-terra   |
| …4f219b0a | issues-review-p1-c3 | 12:34:50  | 0             | 0              | gpt-5.6-terra   |
| …f491a6e3 | issues-review-p3-c2 | 12:34:52  | 0             | 0              | gpt-5.6-terra   |
| …64f5746a | issues-review-p1-c2 | 12:34:52  | 0             | 0              | gpt-5.6-terra   |
| …68e02878 | issues-review-p2-c2 | 12:34:57  | 0             | 0              | gpt-5.6-terra   |
| …00546152 | issues-review-p2-c1 | 12:34:58  | 0             | 0              | gpt-5.6-terra   |
| …04e9772e | issues-review-p3-c3 | 12:35:03  | 0             | 0              | gpt-5.6-terra   |
| …39a69252 | issues-review-p1-c1 | 12:35:05  | 0             | 0              | gpt-5.6-terra   |
| …588c1e67 | blind-spots-c2      | 13:02:47  | 0             | 0              | gpt-5.6-terra   |
| …1678c58f | blind-spots-c3      | 13:02:49  | 0             | 0              | gpt-5.6-terra   |
| …a40b2d88 | blind-spots-c1      | 13:02:50  | 0             | 0              | gpt-5.6-terra   |
| …63284cfc | blind-spots-c4      | 13:02:51  | 0             | 0              | gpt-5.6-terra   |
| …6a250cb6 | validation-c4       | 13:04:56  | 17,141        | 19,423         | claude-opus-4-8 |
| …5c4f7432 | validation-c3       | 13:04:56  | 0             | 36,883         | claude-opus-4-8 |
| …5ff42468 | validation-c2       | 13:04:58  | 17,141        | 20,142         | claude-opus-4-8 |
| …fda5d326 | validation-c1       | 13:05:03  | 17,141        | 20,197         | claude-opus-4-8 |

- units with turn-1 cache_read > 0: **3/24** (report the distribution, not a median).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 15s      |
| review wave (perspectives)  | 6m 10s   |
| blind-spot sweep            | 27m 08s  |
| dedup (incl. combine/clean) | 9s       |
| validation                  | 11m 58s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 33m 19s — the reviewer-model speed comparison number.
- Derived from artefact `created_at` (persisted on completion); only meaningful for fresh, non-resumed runs.

## Chunking

- **chunk 1** (8 files): products/review_hog/backend/models.py, products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py, products/review_hog/backend/api/settings.py, products/review_hog/backend/receivers.py, products/review_hog/frontend/CodeReviewScene.tsx, products/review_hog/frontend/generated/api.schemas.ts, products/review_hog/frontend/generated/api.zod.ts, services/mcp/src/api/generated.ts
- **chunk 2** (8 files): products/stamphog/backend/facade/api.py, products/stamphog/backend/facade/inbox_hooks.py, products/stamphog/backend/tasks/tasks.py, products/stamphog/backend/temporal/activities.py, products/stamphog/backend/logic/reviewer.py, products/tasks/backend/facade/api.py, products/tasks/backend/facade/contracts.py, tach.toml
- **chunk 3** (4 files): tools/pr-approval-agent/review_pr.py, tools/pr-approval-agent/review_local.py, tools/pr-approval-agent/reviewer.py, tools/pr-approval-agent/version.py
- **chunk 4** (2 files): products/stamphog/AGENTS.md, products/stamphog/README.md

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 2     | review-hog-perspective-contracts-security      | 1          |
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 2     | review-hog-perspective-performance-reliability | 1          |
| 3    | 3     | ?                                              | 0          |
| 1000 | 1     | review-hog-blind-spots-general                 | 2          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | review-hog-blind-spots-general                 | 1          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] consider · documentation — products/stamphog/README.md:14

**Remove the em dash from user-facing documentation**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The new README copy uses an em dash before `gated by`. Repository copy guidance applies to docs and explicitly disallows em dashes, so this adds text that violates the documented writing standard.
- **Suggestion:** Split this into two sentences or use a colon, for example: "ReviewHog's inbox receiver calls the `queue_inbox_pr_review` facade. The acting reviewer's per-user `stamphog_review_inbox_prs` setting gates it."
- **Validator:** - **Checked:** the review-hog-validation-criteria skill (v1), the current `products/stamphog/README.md`, and whether a documentation em dash clears the ReviewHog bar.
- **Found:** The criteria enumerate "Pure style / taste — naming, formatting, comment wording ... with no behavioral difference. (Formatting is not a ReviewHog concern.)" as an explicit drop. This finding is an em dash before `gated by` in a README — zero correctness/security/data-loss/contract/performance/reliability impact, and no concrete trigger→consequence can be named (the skill's keep test).
- **Found:** The README is already written with em dashes as its house style: `README.md:3` ("approval**— not just comments"), `:9` ("Action** — runs"), `:10` ("Hosted\*\* ... — a GitHub App"), plus `:12`/`:20`. Flagging one em dash while the whole document uses them is inconsistent style noise, and this is developer-facing docs, not user-facing product copy.
- **Impact:** No user or codebase effect; keeping it is exactly the style noise the skill's precision-over-recall rule says to suppress. Drop.

### [❌ dismissed] must_fix · security — products/stamphog/backend/tasks/tasks.py:1107-1245

**Validate the initial inbox review against the actual task run and PR**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The initial-review task treats its queued `team_id`, `pr_url`, `signal_report_id`, `task_run_id`, and `acting_user_id` as trusted provenance. It only resolves a configured repository and fetches an open PR; it never verifies that the supplied run is the matching non-internal signal implementation run, that its signal report matches, or that the fetched PR is bot-authored with a repo-native head. Consequently, a task output containing an arbitrary PR URL for a configured repository can create a run stamped `inbox_review`, which makes the engine bypass its normal bot/draft, review-mode, and write-permission gates. This defeats the stated positive-identification boundary, including the fork-safety protection present on the webhook path.
- **Suggestion:** Before creating the run, resolve the task through the tasks facade and require its ID, team, signal report, and repository to match the queued values. Fetch the PR first and require its head repository to equal the configured repository and its author to be the expected bot. Re-resolve the current opted-in reviewer at execution time (rather than trusting the queued user ID), and only stamp `inbox_review` after all of these checks pass.
- **Validator:** - **Checked:** the full caller chain into `process_inbox_pr_review` — `handle_task_run_saved` → `_start_stamphog_review` → `queue_inbox_pr_review` (products/review_hog/backend/receivers.py), how `output.pr_url` is bound (products/tasks/backend/webhooks.py:221-227, metrics.py:344), and the webhook carve-out's checks (products/stamphog/backend/tasks/tasks.py:887-895).
- **Found:** the queued `team_id`/`signal_report_id`/`task_run_id`/`acting_user_id` are read straight off the saving `TaskRun` in `handle_task_run_saved`, which dispatches only after gating `task.signal_report_id is not None`, `not task.internal`, and an opted-in resolved reviewer. They are the identity of the very run that triggered the save, dispatched in-process by review_hog — not values a caller could forge — so 're-verify the run/signal report matches' guards nothing (the receiver leg doesn't even gate on them; they are stamped as provenance only).
- **Found:** `output.pr_url` is recorded by the trusted agent server observing the bot open its PR (webhooks.py:221-227), with a branch+repo webhook match as the only backstop. Self-driving PRs are bot-authored on repo-native branches by construction, so the fetched PR in the honest flow already satisfies `_is_bot_authored` and head-repo==base — the checks the finding wants are redundant with reality there.
- **Found:** the webhook leg re-checks bot-authorship + fork-safety because it starts from an _untrusted arbitrary PR event_ and must positively identify it; the receiver leg starts from a _trusted run save_ and reuses that run's own recorded URL. The finding conflates the two trust models.
- **Impact:** for the receiver leg to review a fork/human PR with gates bypassed, `output.pr_url` on a non-internal signal-report run would have to point at an attacker-beneficial PR. External actors cannot set that field on a victim team's run, and the observation-based binding ties it to a bot-opened repo-native PR; the remaining path is compromising PostHog's own internal implementation agent. That is a speculative internal-compromise / defense-in-depth 'what-if,' not a reachable exploit given the call sites — below the keep bar (precision over recall).

### [✅ VALID] must_fix (validator→should_fix) · security — tools/pr-approval-agent/reviewer.py:506,568

**Suppress bot familiarity instead of presenting contradictory trusted context**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** Self-driving reviews still run the normal author-familiarity calculation and include its positive result before this new provenance block. A long-lived bot can therefore be presented as a STRONG or MODERATE familiar author, and the rendered review body also advertises that signal, despite the new block saying author familiarity carries no signal. This weakens the intended trust boundary for the newly allowed bot-authored draft approvals.
- **Suggestion:** When `self_driving` is set, skip familiarity computation/attachment in both `review_pr.py` and `review_local.py` (and avoid rendering its review-body bullet), so the reviewer receives only the task-provenance trust signal for these runs.
- **Validator:** - **Checked:** `_build_review_prompt` (reviewer.py:505,567), the new `_format_self_driving` (reviewer.py:680–703), both familiarity attach paths (`review_pr.py:_maybe_compute_familiarity` 519–521 / run() 241; `review_local.py:_attach_familiarity` 299–309, called at 348), `compute_familiarity`/`_band` in familiarity.py, and gates.py.
- **Found:** The self-driving carve-out relaxes only the bot-author refusal and draft gate (review_pr.py:225, review_local.py patched run()); it does NOT gate familiarity. `familiarity_block` is computed at reviewer.py:505 and rendered at :567 immediately before `{self_driving_block}`. `_attach_familiarity` (review_local.py:299) attaches the signal for any `T1-agent` run when `author_pr_numbers` is present, with no `self_driving` check — so for a self-driving T1-agent review the prompt carries BOTH a familiarity block and a provenance block claiming familiarity 'carr[ies] no signal here.' The new docstring even states familiarity 'is deliberately absent' (reviewer.py:685), which the code does not enforce.
- **Found:** familiarity.py's module docstring says STRONG band exists 'so the ownership norms can treat strong familiarity like owning-team membership' — a posture-relaxing trust signal. `_band` (familiarity.py:407) grants STRONG on blame-overlap alone; a bot that repeatedly opens/merges PRs in the same paths (the feature's intended steady state) accrues blame overlap and prior-PR counts, yielding a positive band that contradicts the provenance instruction on exactly the machine-generated diffs the carve-out means to scrutinize.
- **Impact:** Genuine trust-boundary inconsistency in a security-sensitive carve-out that grants real GitHub approvals to bot drafts: two TRUSTED blocks assert opposite things, and the positive familiarity signal can relax the LLM's skepticism toward a bot diff. The premise ('familiarity still computed/rendered for self-driving') is confirmed true; only the magnitude (band value) is data-dependent.
- **Priority:** Downgrading must_fix → should_fix on concrete evidence of mitigation: familiarity is judgment-layer only (no reference in gates.py; `_maybe_compute_familiarity` only populates `classification`, never a gate), so it cannot deterministically force an unsafe approval; the provenance block explicitly tells the LLM familiarity 'carr[ies] no signal here — judge the diff strictly on its own merits,' giving a textual override; and a non-NONE band requires the server to inject `author_pr_numbers` plus accrued bot blame/PR overlap. Real and worth fixing (cheap: gate the attach/render on `not self_driving`), but not a hard deterministic hole that must block merge.

### [✅ VALID] must_fix (validator→should_fix) · bug — products/review_hog/backend/receivers.py:114-138,144-154

**Honor opt-in from any assigned reviewer**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The feature is intended to run when at least one assigned reviewer enables the Stamphog toggle, but `_resolve_assigned_reviewer` picks a single canonical/creator reviewer and both call sites only inspect that user's setting. If the first assignee is opted out and a later assigned reviewer is opted in, no initial review is queued and later push events are also skipped.
- **Suggestion:** Resolve the assigned reviewers as a collection for the Stamphog path and select an opted-in assignee (preserving the requester-first preference when applicable). Use that selected user as `acting_user_id` for both the initial dispatch and the webhook resolver, while retaining the existing single-reviewer behavior for ReviewHog if that is intentional.
- **Validator:** - **Checked:** The real PR diff (local checkout is stale — no stamphog code, migration 0019 is unrelated), tracing `_resolve_assigned_reviewer`, both call sites in `handle_task_run_saved`, the webhook `resolve_stamphog_acting_reviewer`, and the stamphog facade (`queue_inbox_pr_review`, `inbox_hooks.InboxActingReviewerResolver`).
- **Found:** `_resolve_assigned_reviewer` returns a single id — `acting = next((u for u in resolved if u.id == task_created_by_id), resolved[0]); return acting.id`. For self-driving inbox PRs the task creator is the GitHub-integration bot (per module docstring), so `task_created_by_id` matches no suggested reviewer → `acting = resolved[0]` (first-ordered). Both legs gate on that one user: `settings = ReviewUserSettings.load(team_id, acting_user_id); if pr_url is not None and settings.stamphog_review_inbox_prs:` for the initial dispatch, and `resolve_stamphog_acting_reviewer` re-checks the same single user's `stamphog_review_inbox_prs` on webhook re-review. The whole facade flows one `acting_user_id` (`InboxActingReviewerResolver = Callable[[int, str, int | None], int | None]`).
- **Impact:** Report suggesting `[alice, bob]` with alice (first) opted out and bob opted in → `acting = alice` → initial Stamphog dispatch skipped AND webhook re-reviews resolve to `None` → skipped. This is the normal multi-reviewer rollout case (Slack fans out to plural reviewers), and it contradicts the feature's stated gate ("at least one of the assigned users has `stamphog_review_inbox_prs` enabled"; Case 3's "nobody is opted in"). Concrete trigger and concrete consequence both nameable — a genuine logic gap, not speculative.
- **Priority:** Lowering must_fix → should_fix: the failure is a silent under-trigger in the fail-safe direction (no unwanted review published — the feature simply doesn't run), on a draft experiment branch, and the single-canonical-reviewer resolver is a deliberate, documented, shared mechanism (required for ReviewHog's per-user options). Worth surfacing so the author reconciles code vs. intent — the fix is contained (select an opted-in assignee for the stamphog path) — but it is not a blocking correctness/data-loss defect.

### [✅ VALID] must_fix · bug — products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py:7-8

**Rebase the migration on the existing 0019 leaf**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The repository already contains `0019_reviewreport_author_login_and_more`, also depending on `0018_backfill_urgency_threshold_to_consider` (and `max_migration.txt` names it as the current leaf). Adding another migration named `0019` with the same parent creates conflicting migration leaves, causing Django migration checks to fail.
- **Suggestion:** Rename this migration to the next available number and depend on the existing `0019_reviewreport_author_login_and_more` migration, then update `max_migration.txt` if required by the repository's migration tooling.
- **Validator:** - **Checked:** The PR's new migration (`0019_reviewusersettings_stamphog_review_inbox_prs.py`) dependency + its `max_migration.txt` diff, against the base checkout's existing `0019_reviewreport_author_login_and_more.py` and `max_migration.txt`.
- **Found:** PR migration declares `dependencies = [("review_hog", "0018_backfill_urgency_threshold_to_consider")]` (lines 7-8) and its `max_migration.txt` hunk rewrites `0018_backfill_urgency_threshold_to_consider` → `0019_reviewusersettings_stamphog_review_inbox_prs` — so the branch's merge-base leaf was still `0018`. Base/master already has `0019_reviewreport_author_login_and_more.py` whose `dependencies` (line 8) is the same `0018_backfill_urgency_threshold_to_consider`, and master's `max_migration.txt` = `0019_reviewreport_author_login_and_more`.
- **Impact:** On merge/rebase onto current master, two migrations parent on `0018` → two migration leaves for the `review_hog` app, so `makemigrations --check` / `migrate` fails, and `max_migration.txt` conflicts on its single line. PostHog uses `django-linear-migrations` (the `max_migration.txt` convention), which fails the build rather than auto-merging — a deterministic CI/merge-queue block. Concrete trigger (rebase onto a master that already landed `0019_reviewreport_...`) and concrete consequence (migration check failure) both confirmed; must_fix stands.

### [❌ dismissed] should_fix · bug — products/tasks/backend/facade/api.py:506-507

**Scope the task-run lookup before selecting a match**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** `find_task_run` searches all teams and returns only its first repository/PR match. The subsequent `run.team_id != team_id` check then returns `None` rather than continuing to a matching run in the requested team. A non-internal signal task in another team targeting the same repository and PR URL or branch can therefore prevent the legitimate team's bot draft from being recognized on later webhook deliveries, so opted-in users stop receiving re-reviews.
- **Suggestion:** Add `team_id` support to `find_task_run` (and apply it to every PR URL/branch query before ordering), or implement the lookup here with `TaskRun.objects.filter(team_id=team_id, ...)`. This ensures ordering happens only among the requesting team's candidate runs.
- **Validator:** - **Checked:** `find_signal_implementation_run` (products/tasks/backend/facade/api.py, new in this PR), the `find_task_run` it delegates to (products/tasks/backend/webhooks.py:29-95), and the sole production caller `_inbox_rereview_carve_out` (products/stamphog/backend/tasks/tasks.py, diff line 909).
- **Found:** `find_task_run` tries the `pr_url` leg first and returns before the branch leg is reached (webhooks.py:38-59). A GitHub PR `html_url` is globally unique to one physical PR, recorded by the single run that created it, so the `pr_url` leg resolves to the correct team's run — `run.team_id != team_id` cannot mismatch here. The only documented duplicate-`pr_url` case is a same-team wizard resume, disambiguated by the terminal-rank ordering (webhooks.py:39-42).
- **Found:** the only caller passes both `pr_url` and `head_branch` and is gated to `synchronize`/`reopened`/base-retarget actions only (`_HEAD_CHANGING_ACTIONS = {"synchronize","reopened"}`, tasks.py:46) — all post-creation deliveries. By then the PR exists and its URL was saved onto the task (that save wakes the initial listener), so the run's `output.pr_url` is set and the `pr_url` leg matches. The branch fallback never governs this path. The initial review is a separate receiver leg (`process_inbox_pr_review`) that does not call this function.
- **Impact:** the described failure needs either two teams' runs sharing the same globally-unique PR URL (does not occur), or the `pr_url` leg to miss _and_ two distinct tenants on the identical repository holding non-wizard runs with an identical branch string (self-driving branches carry `secrets.token_hex(3)` random suffixes). That is a stack of practically-unreachable conditions on a path that `pr_url` already resolves correctly — a speculative what-if, not a reachable defect. The facade is additionally fail-closed (explicit team check plus a caller-side belt-and-braces recheck).
