# ReviewHog — e2e run log (pseudo-evals)

Purpose: record every end-to-end `run_review` so we can tell whether a prompt/code change
**actually moved review quality**, instead of iterating blind.

## How to read / add entries

- One entry per run, **newest first**.
- **Sample PR = [#63625](https://github.com/PostHog/posthog/pull/63625)** (`posthog-code/fix-stickiness-dw-timestamp-field`,
  a data-warehouse `timestamp_field` bugfix, 6 files / +180-1). It is **non-fork** (sandbox checkout works)
  and **stale** — its head `243ddf40295c` has been frozen since 2026-06-15 — so every run reviews
  **identical code** and a change in findings reflects a change in _the reviewer_, not the PR. Keep using a
  frozen PR until the **step-14 head_sha pin** lands (review a fixed commit instead of "current head").
- The **codebase-state label** = what changed in the reviewer (prompt/code) + the `signals/reviewhog`
  working state ("uncommitted" while iterating). Quality is only comparable across runs at the **same**
  reviewed `head_sha`.
- The agent appends an entry after each run (reads `ReviewReport` + `ReviewReportArtefact` on team 1);
  `python manage.py reset_review_hog --yes` clears DB state between fresh runs.

> Reset to the #63625 baseline on 2026-06-25 (the earlier bootstrap runs were against #65862, a live
> branch that moved mid-iteration — not reproducible, so cleared).

---

## 2026-06-25 · baseline — PR #63625 @ `243ddf40295c`

- **ReviewHog under test:** step 11 (A-lite agnostic prompts + trimmed context) **+** `combine_issues`
  id re-stamp fix. `signals/reviewhog`, uncommitted working tree.
- **Pipeline:** 9/9 stages. 1 chunk (small PR). Artefacts: `chunk_analysis` 1, `perspective_result` 3 (3×1).
- **Findings:** 1 · **Validator:** **1 kept / 0 dropped** · report body 2,173 chars.

| #   | perspective         | prio       | file:line                       | finding                                                                                                                                                                | verdict       |
| --- | ------------------- | ---------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| 1   | Logic & Correctness | should_fix | hogql/database/database.py:1478 | remapped `timestamp_field` now triggers `get_table` for view-namespace tables that previously skipped it → `DoesNotExist` turns a successful build into a hard failure | ✅ kept · bug |
