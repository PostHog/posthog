# Reviewer-quality run — `glm-high-1`

- **Dumped:** 2026-09-16T22:29:03+00:00
- **Report id:** `01a0ac2e-336d-7891-ac53-1464c9206ea8` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 0 · **status:** active
- **Wall-clock:** 2641s (44.0 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 16           | 47         | 0           | 0                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 42m 22s  |
| chunking                    | 0s       |
| perspective selection       | —        |
| review wave (perspectives)  | —        |
| blind-spot sweep            | 16m 14s  |
| dedup (incl. combine/clean) | —        |
| validation                  | —        |

- **Review stage total (selection → last finder unit, wave + blind-spot):** — — the reviewer-model speed comparison number.
- Derived from artefact `created_at` (persisted on completion); only meaningful for fresh, non-resumed runs.

## Chunking

- **chunk 1** (8 files): products/review_hog/backend/models.py, products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py, products/review_hog/backend/api/settings.py, products/review_hog/backend/receivers.py, products/review_hog/frontend/CodeReviewScene.tsx, products/review_hog/frontend/generated/api.schemas.ts, products/review_hog/frontend/generated/api.zod.ts, services/mcp/src/api/generated.ts
- **chunk 2** (8 files): products/stamphog/backend/facade/api.py, products/stamphog/backend/facade/inbox_hooks.py, products/stamphog/backend/tasks/tasks.py, products/stamphog/backend/temporal/activities.py, products/stamphog/backend/logic/reviewer.py, products/tasks/backend/facade/api.py, products/tasks/backend/facade/contracts.py, tach.toml
- **chunk 3** (4 files): tools/pr-approval-agent/review_pr.py, tools/pr-approval-agent/review_local.py, tools/pr-approval-agent/reviewer.py, tools/pr-approval-agent/version.py
- **chunk 4** (2 files): products/stamphog/AGENTS.md, products/stamphog/README.md

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 3          |
| 1    | 2     | review-hog-perspective-contracts-security      | 4          |
| 1    | 3     | review-hog-perspective-contracts-security      | 5          |
| 1    | 4     | review-hog-perspective-contracts-security      | 3          |
| 2    | 1     | ?                                              | 0          |
| 2    | 2     | ?                                              | 0          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 3          |
| 2    | 4     | review-hog-perspective-logic-correctness       | 2          |
| 3    | 1     | review-hog-perspective-performance-reliability | 5          |
| 3    | 2     | review-hog-perspective-performance-reliability | 7          |
| 3    | 3     | review-hog-perspective-performance-reliability | 4          |
| 3    | 4     | ?                                              | 0          |
| 1000 | 1     | review-hog-blind-spots-general                 | 3          |
| 1000 | 2     | review-hog-blind-spots-general                 | 2          |
| 1000 | 3     | review-hog-blind-spots-general                 | 3          |
| 1000 | 4     | review-hog-blind-spots-general                 | 3          |

## Findings (post-dedup) with validator verdict

_(no findings)_
