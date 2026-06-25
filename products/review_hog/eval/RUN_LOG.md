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
