# ReviewHog — e2e run log (pseudo-evals)

Purpose: record every end-to-end `run_review` so we can tell whether a prompt/code change
**actually moved review quality**, instead of iterating blind.

## How to read / add entries

- One entry per run, **newest first**.
- **Sample PR = [#63625](https://github.com/PostHog/posthog/pull/63625)** (`posthog-code/fix-stickiness-dw-timestamp-field`,
  a data-warehouse `timestamp_field` bugfix, 6 files / +180-1). It is **non-fork** (sandbox checkout works)
  and **stale** — its head `243ddf40295c` has been frozen since 2026-06-15 — so every run reviews
  **identical code** and a change in findings reflects a change in _the reviewer_, not the PR. Keep using a
  frozen PR until the **step-16 head_sha pin** lands (review a fixed commit instead of "current head").
- The **codebase-state label** = what changed in the reviewer (prompt/code) + the `signals/reviewhog`
  working state ("uncommitted" while iterating). Quality is only comparable across runs at the **same**
  reviewed `head_sha`.
- The agent appends an entry after each run (reads `ReviewReport` + `ReviewReportArtefact` on team 1);
  `python manage.py reset_review_hog --yes` clears DB state between fresh runs.

> Reset to the #63625 baseline on 2026-06-25 (the earlier bootstrap runs were against #65862, a live
> branch that moved mid-iteration — not reproducible, so cleared).

---

## 2026-06-29 · #66456 same-SHA re-trigger — early-exit gate validated (true no-op)

- **Change under test:** new early-exit gate in `ReviewPRWorkflow` — return the report id right after fetch when
  `ReviewMeta.already_published` (`published_head_sha == head_sha`: this exact head already reviewed **and**
  posted). Skips sync-skills / schema-gen / chunk / analyze / review / dedup / validate / build / publish.
- **Run:** `run_review --pr-url …/66456 --team-id 1 --user-id 1 --publish`, exit 0, report `019f0581-646e-…`
  (same living report as the 2026-06-26 publish). Head unchanged since Friday (`9575669d…`, confirmed live via
  `gh pr view`); `published_head_sha == head_sha` in the DB.
- **Result — true no-op, proven 3 ways:** (1) **Temporal history** for `review-pr:1:PostHog/posthog:66456` shows
  only `validate_github_integration_activity` + `fetch_pr_data_activity` scheduled, then
  `WorkflowExecutionCompleted` — no downstream stage ran. (2) `run_count` stayed **1** (finalize never ran),
  `updated_at` unchanged. (3) PR comment counts unchanged (5 inline / 3 issue) — nothing posted; no sandbox cost.
- **Why this is the realistic prod case:** the production label trigger is always `publish=True`, so after the
  first successful publish a re-trigger at the same head (a re-label, `ready_for_review`, or a no-op
  `synchronize`) is gated here. A **no-publish** eval run is never gated (no published head) — the frozen-PR eval
  loop still recomputes to measure reviewer changes.
- **New comments at an unchanged head:** counted + logged at fetch (`new_comment_count`) but do **not** force a
  turn yet (decision 2026-06-29 — revisit with the "fix the issues" action plane; see ARCHITECTURE.md Stage 5b).
- **NEXT — Scenario 2 (SHA changed):** push a tiny change to #66456 to move the head, re-run `--publish` → expect
  a full re-review (re-chunk/analyze/review at the new head) + a **fresh** published review pinned to the new head,
  **no** promo re-post, deduped against our own prior inline comments.

## 2026-06-26 · #66456 publish — surfaced two publish-path gaps

- **Run:** `run_review --pr-url …/66456 --team-id 1 --user-id 1 --publish`, exit 0, report `019f0581-646e-…`.
  Pipeline ran fully (7 chunks → 7 post-dedup findings + 7 verdicts; **2 valid `SHOULD_FIX`** on `posthog/email.py`).
- **Symptom:** nothing posted to the PR; `published_head_sha` was `None`.
- **Root cause #1 (publish flag dropped):** the Temporal history for `review-pr:1:PostHog/posthog:66456` has **one**
  execution whose **start input was `publish=False`** (`publish_review_activity` scheduled 0×). A **no-publish** run
  was already in flight; the `--publish` invocation joined it via `id_conflict_policy=USE_EXISTING` and blocked on
  it, so `publish=True` never reached a workflow. USE_EXISTING is correct for the prod label trigger, a CLI footgun
  here. Not a code defect — `_publish` posts fine (published the report directly afterward: body + 1 inline comment
  - once-per-report promo, `published_head_sha` then set).
- **Root cause #2 (off-diff valid finding dropped):** of the 2 valid findings, `email.py:276` had **no resolvable
  diff position** → skipped; only `email.py:104` posted inline. If **all** valid findings were off-diff,
  `publish_review` would return `False` and post **nothing** (not even the body). Both gaps written up as next
  steps in `ARCHITECTURE.md` → Stage 5b → _Publish-path gaps_.

## 2026-06-26 · Stage 5 — production label trigger (BUILT, not e2e'd)

- **What landed (Phases 1–4):** non-blocking `start_review_pr_workflow` + per-run `publish` flag (retired
  `PUBLISH_REVIEW_ENABLED`) + `--publish` on `run_review`; PAT → **GitHub App installation token** for fetch + publish
  (worker no longer needs `GITHUB_TOKEN`); fork rejection (`PRMetadata.is_fork`, non-retryable, pre-report);
  `head_sha`-pinned publish; shared-secret endpoint `POST /api/review_hog/trigger`; `.github/workflows/review-hog.yml`.
- **Adversarial review** (4-dimension finder → per-finding skeptic verify): 11 raw → **7 confirmed → 4 distinct**, all
  **fixed**: (A) re-trigger/`synchronize` raised `WorkflowAlreadyStartedError` → unhandled **500 / red CI check** →
  fixed with `id_conflict_policy=USE_EXISTING`; (B) `_installation_token` marked transient GitHub failures
  non-retryable → made retryable (missing-integration still fails fast in the validate activity); (C) `get_commit`
  head_sha pin outside the try defeated the body-only fallback → made best-effort (post unpinned on failure); (D)
  publish non-idempotent under at-least-once retries → **`ReviewReport.published_head_sha` watermark** (skip re-publish
  same head; promo comment once per report). Migration `0005_reviewreport_published_head_sha`.
- **Tests:** 224 product tests + ruff + tach green. New: `test_trigger_api.py` (10), `test_publish_review.py` (4),
  `test_publish_idempotency.py` (4), publish-gate cases in `test_temporal_workflow.py`, fork-flag in
  `test_github_meta.py`. (Local note: run product tests with `SANDBOX_PROVIDER=modal` — the local `.env`'s
  `MODAL_DOCKER` + `DEBUG=False` makes the tasks sandbox module raise at import during full route discovery.)
- **e2e via `manage.py run_review --publish` on #63625 (team 1/user 1), exit 0, report `019f0419…`:** full 9-stage
  pipeline ran in the worker; **fetch resolved the installation token for team 1 (no `GITHUB_TOKEN` env)** ✅, fork gate
  passed (non-fork), 1 chunk → analyze + 3 perspectives. **1 raw finding** (Logic & Correctness `database.py:1625`),
  perspectives 2/3 found 0 → 1 post-dedup finding → validator marked it **`is_valid:False`** (dropped, "bug" but not
  surfaced) ⇒ **0 publishable ⇒ nothing posted to the PR** (correct). Confirmed via the installation token: no
  ReviewHog review/promo on #63625. So the live `create_review` HTTP path is **not** exercised end-to-end until a
  finding survives validation (it is covered by `test_publish_review`). NOTE: #63625's head has moved to `2f1a8aee…`
  (was frozen `243ddf40295c`), so it's no longer the old baseline code.
- **Bug the e2e exposed + fixed:** `_publish` set `published_head_sha` even on a no-op publish (0 publishable),
  "poisoning" the head — a later turn with a valid finding at the same head would `skip`, and the one-time promo was
  consumed. Fix: `publish_review` returns whether it posted; `_publish` records the watermark **only on an actual
  post**. (Worker must be restarted to pick this up — the #63625 run above used the pre-fix worker code.)
- **e2e via `manage.py run_review --publish` on #66168 (team 1/user 1), exit 0, report `019f0428…` — FULL PUBLISH:**
  7 chunks; 23 raw issues → 20 post-dedup → 20 validated → **6 `is_valid:True`** (oauth.py, run_wizard.py,
  wizard_pr_agent_prompt.md). **Posted to the PR as `posthog-local-dev[bot]`** (verified by reading GitHub back via the
  installation token): a `COMMENTED` review **pinned to `commit 4e71e3328eb6` = the reviewed `head_sha`** (head_sha pin
  ✅), inline comments on the valid findings, and **1** "ReviewHog Alpha" promo comment (once-per-report gate ✅).
  `published_head_sha == head_sha` ✅. This is the first end-to-end exercise of the live `create_review` HTTP path +
  installation-token publish + head_sha pin + promo gate on a real PR. Next: Stage 5b (push a new commit to a labeled
  PR → re-review → confirm the dedup skips ReviewHog's own prior inline comments).

---

## 2026-06-25 · audit fixes — resilience (retries / 70% floor) — PR #63625 @ `243ddf40295c`

- **ReviewHog under test:** post-audit resilience fixes — sandbox failures now **raise** so Temporal
  retries actually fire (the executor no longer swallows them to `None`), dedup no longer
  bare-`RuntimeError`-aborts, a **70% fan-out failure floor** fails the run on a near-total wipeout
  instead of finalizing an empty report as success, and all activities + child workflows + the parent
  retry uniformly. `signals/reviewhog`, uncommitted. **Fresh run (DB reset first)** so the whole
  pipeline re-ran — no resume.
- **Pipeline (exit 0, every stage):** `commit` 1 · `pr_snapshot` 1 · `chunk_set` 1 (1 chunk) ·
  `chunk_analysis` 1 · `perspective_result` **3/3** (no best-effort drops) · `issue_finding` 2 ·
  `validation_verdict` 2. Final: **status idle · run_count 1 · body 4,793 chars**. Publish gated off.
- **Findings:** 2 (both `hogql/database/database.py:1478`, the recurring hotspot) · **Validator: 0
  kept / 2 dropped** — same criteria-driven outcome as the step-13/15 baseline. The clean signal: the
  failure-path refactor is **behavior-preserving** — every stage ran, full 3-perspective fan-out, the
  same finding hotspot, and the same validator behavior as the in-process and step-15 runs.

| #   | perspective               | prio       | file:line                       | verdict                                            |
| --- | ------------------------- | ---------- | ------------------------------- | -------------------------------------------------- |
| 1   | Contracts & Security      | should_fix | hogql/database/database.py:1478 | ❌ dropped · "intended rebinding, not a contract"  |
| 2   | Performance & Reliability | should_fix | hogql/database/database.py:1478 | ❌ dropped · "relies on an unwrapped DoesNotExist" |

## 2026-06-25 · step 15 — Temporal single-turn workflow — PR #63625 @ `243ddf40295c`

- **ReviewHog under test:** step 15 — the whole pipeline is now a Temporal `ReviewPRWorkflow` (parent +
  3 fan-out child workflows + activities; everything by-reference via the new `pr_snapshot` artefact;
  identity threaded explicitly, contextvar gone). `run_review` triggers + **blocks** on the workflow.
  `signals/reviewhog`, uncommitted working tree.
- **Ran end-to-end through Temporal (exit 0)** — the workflow executed in the `video-export` worker
  (DEBUG-collapsed to `development-task-queue`), confirming `review-pr` + the 3 children are registered.
  `pr_snapshot:1` proves the fetch activity ran and the stage activities reloaded PR inputs from the DB.
- **Resume worked:** head unchanged, so `chunk_set:1` / `chunk_analysis:1` / `perspective_result:3` were
  reused from the prior turn's rows — **no redundant sandbox calls**; only dedup + validate hit the
  sandbox this turn (the documented recompute boundary). Final: `status idle · run_count 3 · body 4,448
chars`. Publish gated off.
- **Findings:** 1 this turn · **Validator:** **0 kept / 1 dropped** — same criteria-driven outcome as the
  step-13 baseline (the `database.py:1478` finding dropped as "practically unreachable"). The kept/dropped
  flips run-to-run on the frozen head (LLM nondeterminism); the clean signal is that **the Temporal
  pipeline is behavior-preserving** — same stages, same finding, same validator behavior as in-process.

## 2026-06-25 · step 13 — validator-as-pulled-skill — PR #63625 @ `243ddf40295c`

- **ReviewHog under test:** step 13 — the validation keep/drop **criteria moved to a pulled LLMA skill**
  (`review-hog-validation-criteria`); `issue_validation` prompt is criteria-agnostic; both review skill sets
  collapsed to one `review_hog` category / "Code review" tab. `signals/reviewhog`, uncommitted working tree.
- **Pipeline:** 9/9 stages (exit 0). 1 chunk. Artefacts: `chunk_analysis` 1, `perspective_result` 2
  (one perspective×chunk dropped — best-effort, Modal flakiness), `issue_finding` 1, `validation_verdict` 1.
  Report body 4,448 chars.
- **Skill pull confirmed:** the validator agent's `skill-get` for `review-hog-validation-criteria` returned
  `success:true / isError:false` ("Launching skill: …"); no `SkillNotFound`/permission error — the sandbox MCP
  served the skill live from the DB (no restart needed).
- **Findings:** 1 · **Validator:** **0 kept / 1 dropped** (criteria-driven).

| #   | perspective               | prio       | file:line                       | finding                                                                                                          | verdict                                      |
| --- | ------------------------- | ---------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| 1   | Performance & Reliability | should_fix | hogql/database/database.py:1478 | broadened guard now reaches a raising `get_table()` for previously short-circuited tables → potential hard crash | ❌ dropped · bug · "practically unreachable" |

> **Behavior change vs baseline:** the baseline (criteria-less validator) **kept** a finding on this same
> `database.py:1478`; the criteria-driven validator **drops** it as _"practically unreachable"_ — reasoning that
> directly tracks the new criteria skill ("trace whether the problem can actually be reached; drop
> never-gonna-happen edge cases"). The surviving perspective + finding vary run-to-run (LLM nondeterminism on the
> same head), so the clean signal here is the validator applying team-owned criteria, not the finding count.

## 2026-06-25 · baseline — PR #63625 @ `243ddf40295c`

- **ReviewHog under test:** step 11 (A-lite agnostic prompts + trimmed context) **+** `combine_issues`
  id re-stamp fix. `signals/reviewhog`, uncommitted working tree.
- **Pipeline:** 9/9 stages. 1 chunk (small PR). Artefacts: `chunk_analysis` 1, `perspective_result` 3 (3×1).
- **Findings:** 1 · **Validator:** **1 kept / 0 dropped** · report body 2,173 chars.

| #   | perspective         | prio       | file:line                       | finding                                                                                                                                                                | verdict       |
| --- | ------------------- | ---------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| 1   | Logic & Correctness | should_fix | hogql/database/database.py:1478 | remapped `timestamp_field` now triggers `get_table` for view-namespace tables that previously skipped it → `DoesNotExist` turns a successful build into a hard failure | ✅ kept · bug |
