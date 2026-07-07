# Reviewer-quality run — `prod-68791-publish`

- **Dumped:** 2026-07-07T12:07:29+00:00
- **Report id:** `019f3c5c-1da3-7553-83e6-3795a6a09327` · **PR:** https://github.com/PostHog/posthog/pull/67451
- **Head:** `7984826d2f3492649ea42573b7398aa3cbcd7de7` · **run_count:** 0 · **status:** active
- **Wall-clock:** 3780s (63.0 min)

## Config snapshot

- runtime / model / effort: `claude` / `claude-sonnet-5` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 16           | 36         | 0           | 0                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model             | stage      | gens    | fresh in    | cache write   | cache read     | output      | >200K gens | true $     | gw $       |
| ----------------- | ---------- | ------- | ----------- | ------------- | -------------- | ----------- | ---------- | ---------- | ---------- |
| claude-sonnet-5   | review     | 553     | 613,279     | 3,402,919     | 55,970,518     | 552,412     | 0          | $26.45     | $26.34     |
| claude-opus-4-8   | validation | 124     | 81,633      | 723,061       | 13,834,335     | 185,587     | 7          | $16.48     | $16.48     |
| claude-sonnet-5   | blind-spot | 205     | 184,137     | 1,220,816     | 20,007,620     | 180,485     | 0          | $9.23      | $9.23      |
| claude-sonnet-4-6 | validation | 48      | 926         | 178,839       | 2,388,037      | 15,722      | 0          | $1.63      | $1.63      |
| claude-sonnet-5   | chunking   | 2       | 69,633      | 0             | 0              | 9,076       | 0          | $0.23      | $0.23      |
| claude-sonnet-5   | dedup      | 1       | 17,051      | 0             | 0              | 5,325       | 0          | $0.09      | $0.09      |
| **total**         |            | **933** | **966,659** | **5,525,635** | **92,200,510** | **948,607** | **7**      | **$54.11** | **$53.99** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = -0.2%.
- naive method (all prompt tokens at input price): $256.22 — 4.7× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $41.6756 over 933 gen(s) (true $41.7575, Δ -0.2%)
  - · of which cache read: $22.8292 over 908 gen(s) (true $22.8292, Δ +0.0%)
  - · of which cache write: $16.7491 over 921 gen(s) (true $16.7491, Δ +0.0%)
  - · of which fresh (derived): $2.0973 over 933 gen(s) (true $2.1791, Δ -3.8%)
  - output: $12.3169 over 933 gen(s) (true $12.3485, Δ -0.3%)
- 7 gen(s) ran with >200K-token prompts; the gateway map prices these models flat, so no long-context premium is included in either column.

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | step                | first gen | t1 cache read | t1 cache write | models                                        |
| --------- | ------------------- | --------- | ------------- | -------------- | --------------------------------------------- |
| …4215f066 | issues-review-p2-c3 | 11:02:44  | 37,120        | 20,784         | claude-sonnet-5                               |
| …6e252810 | issues-review-p1-c2 | 11:02:44  | 37,120        | 27,869         | claude-sonnet-5                               |
| …72eafea0 | issues-review-p2-c1 | 11:02:44  | 37,120        | 29,283         | claude-sonnet-5                               |
| …20e18866 | issues-review-p3-c2 | 11:02:45  | 37,120        | 27,870         | claude-sonnet-5                               |
| …e59afe1c | issues-review-p3-c1 | 11:02:46  | 37,120        | 29,283         | claude-sonnet-5                               |
| …31710ad9 | issues-review-p1-c3 | 11:02:46  | 37,120        | 20,783         | claude-sonnet-5                               |
| …ffa36075 | issues-review-p3-c3 | 11:02:46  | 37,120        | 20,784         | claude-sonnet-5                               |
| …a7d354fd | issues-review-p2-c2 | 11:02:47  | 37,120        | 27,870         | claude-sonnet-5                               |
| …175563f6 | issues-review-p1-c1 | 11:02:53  | 37,120        | 29,282         | claude-sonnet-5                               |
| …24aed664 | blind-spots-c2      | 11:12:36  | 37,120        | 32,674         | claude-sonnet-5                               |
| …fce88fd1 | blind-spots-c1      | 11:12:37  | 37,120        | 33,910         | claude-sonnet-5                               |
| …d1b2f54d | blind-spots-c3      | 11:12:38  | 37,120        | 22,628         | claude-sonnet-5                               |
| …45711dfe | validation-c2       | 11:22:00  | 0             | 40,719         | claude-opus-4-8                               |
| …6ad2104c | validation-c1       | 11:22:00  | 0             | 40,477         | claude-opus-4-8, claude-sonnet-4-6 ⚠️SWITCHED |
| …7d1b7b40 | validation-c3       | 11:22:04  | 24,755        | 15,283         | claude-opus-4-8                               |
| …1d14a509 | issues-review-p1-c4 | 11:37:24  | 0             | 54,996         | claude-sonnet-5                               |
| …77c11e6a | issues-review-p2-c2 | 11:37:24  | 0             | 59,531         | claude-sonnet-5                               |
| …38308a92 | issues-review-p3-c1 | 11:37:25  | 37,120        | 35,242         | claude-sonnet-5                               |
| …0bb45ae2 | issues-review-p1-c3 | 11:37:25  | 37,120        | 29,595         | claude-sonnet-5                               |
| …b0b1e4e3 | issues-review-p1-c1 | 11:37:26  | 37,120        | 35,241         | claude-sonnet-5                               |
| …625dc294 | issues-review-p2-c1 | 11:37:26  | 37,120        | 35,242         | claude-sonnet-5                               |
| …af5aa237 | issues-review-p2-c3 | 11:37:26  | 37,120        | 29,596         | claude-sonnet-5                               |
| …c9f00fcf | issues-review-p1-c2 | 11:37:27  | 37,120        | 22,410         | claude-sonnet-5                               |
| …31756379 | issues-review-p3-c2 | 11:37:28  | 37,120        | 22,411         | claude-sonnet-5                               |
| …d2f74ad0 | issues-review-p2-c4 | 11:37:33  | 37,120        | 17,877         | claude-sonnet-5                               |
| …62795e2a | issues-review-p3-c3 | 11:40:12  | 37,120        | 29,596         | claude-sonnet-5                               |
| …1be66b55 | issues-review-p3-c4 | 11:41:16  | 37,120        | 17,877         | claude-sonnet-5                               |
| …6bc704f3 | blind-spots-c2      | 11:51:14  | 0             | 65,609         | claude-sonnet-5                               |
| …1d41d298 | blind-spots-c1      | 11:51:15  | 0             | 77,202         | claude-sonnet-5                               |
| …d8b9b0bb | blind-spots-c3      | 11:51:16  | 37,120        | 34,208         | claude-sonnet-5                               |
| …d4a836ba | blind-spots-c4      | 11:51:16  | 37,120        | 20,596         | claude-sonnet-5                               |
| …db3de8a8 | validation-c2       | 11:51:54  | 0             | 40,642         | claude-opus-4-8                               |

- units with turn-1 cache_read > 0: **25/32** (report the distribution, not a median).
- ⚠️ 1 unit(s) switched models mid-session (overload rescue?) — cache sharing and cost pinning are broken for them: …6ad2104c

## Chunking

- **chunk 1** (9 files): products/posthog_ai/frontend/utils/composerModes.ts, products/posthog_ai/frontend/logics/runInteractionLogic.ts, products/posthog_ai/frontend/scenes/TaskTracker/taskTrackerSceneLogic.ts, products/posthog_ai/frontend/utils/composerModels.ts, products/posthog_ai/frontend/components/composer/ComposerModePicker.tsx, products/posthog_ai/frontend/components/composer/Composer.tsx, products/posthog_ai/frontend/components/composer/ComposerModelEffortPickers.tsx, products/posthog_ai/frontend/scenes/TaskTracker/components/TaskComposer.tsx, products/posthog_ai/frontend/scenes/TaskTracker/components/TaskRunChat.tsx
- **chunk 2** (1 files): products/posthog_ai/frontend/components/PlanApprovalActions.tsx
- **chunk 3** (4 files): products/posthog_ai/frontend/components/PlanCard.tsx, products/posthog_ai/frontend/components/PermissionInput.tsx, products/posthog_ai/frontend/policy/permissionUtils.ts, products/posthog_ai/frontend/components/tool/builtinToolRenderers.tsx
- **chunk 4** (1 files): products/posthog_ai/frontend/logics/runStreamLogic.ts

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 3          |
| 1    | 2     | review-hog-perspective-contracts-security      | 4          |
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 1    | 4     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 5          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 4          |
| 2    | 4     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 3    | 3     | review-hog-perspective-performance-reliability | 3          |
| 3    | 4     | review-hog-perspective-performance-reliability | 2          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | review-hog-blind-spots-general                 | 3          |
| 1000 | 3     | review-hog-blind-spots-general                 | 2          |
| 1000 | 4     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

_(no findings)_
