# FINAL REPORT — GLM 5.3 Flash as ReviewHog reviewer and validator

**Date:** 2026-09-01 (runs 2026-08-31 21:45 UTC – 2026-09-01 02:05 UTC, fully autonomous overnight).
**Question:** can `zai-org/glm-5.3-flash` (via Baseten, claude adapter, effort `max` — its maximum) replace either half of the prod pair (Sol xhigh reviewer / Opus 5 xhigh validator)?
**Answer: no to both.** As reviewer it finds almost nothing real (7–33% real vs the 47–65% band every other reviewer sits in), and nothing it found survived validation. As validator it is 10–50× cheaper than any alternative but unreliable: it silently skips findings (12 of 22 got no verdict at all in one run), its strictness swings run to run, and its recall (43–69%) lands at or below Opus with far worse junk filtering in the lax run.

## ⚠️ Read this before trusting the numbers

**Every GLM run here had an MCP crutch the control runs did not have.** GLM cannot bridge the pipeline's `skill-get(...)` prompt to the MCP server's default exec-only surface — it sees the `exec` tool and never calls it, so it would review **without its criteria skill** (i.e., blind) on an unmodified stack. For this experiment we forced classic per-tool mode with an `x-posthog-mcp-mode: tools` header (Alex's call, option a — see `FINDINGS.md` item 5). That gives GLM _easier_ skill-fetch mechanics than the 08-26 control runs had. Two consequences:

- The comparison is tilted **in GLM's favor**; its results below are its ceiling on this stack, not its floor.
- Shipping GLM in prod would require shipping the same tools-mode override (or new prompt plumbing for exec mode). Without it, GLM reviews blind.

The MCP scopes are unchanged from master (`llm_skill:read`, `user:read`). Mid-experiment a `project:read` addition was tried on the theory that the "missing scope: project:read" warning refused the handshake; a later investigation disproved that (the project fetch is best-effort, only `user:read` refuses — fixed earlier in #88697), and code review then found `GET /api/projects/<id>/` returns the team's unmasked `secret_api_token`, so granting it to an injectable session was dropped.

## Setup

Same clean room as the 07-31 reviewer and 08-26 validator experiments: frozen PR 75215 @ `a7fb363b` (tree `1341596e`), comments mocked to none, pinned 4 chunks / 22 files, team 1 / user 1, DB-only (no publish), local stack + ngrok, Modal sandboxes, `MAX_CONCURRENT_SANDBOXES=4`. Four serial runs alternating arms:

| Run              | Reviewer                                 | Validator                 |
| ---------------- | ---------------------------------------- | ------------------------- |
| RA (R1), RB (R2) | **GLM 5.3 Flash @ max** (claude adapter) | Opus 5 @ xhigh (prod pin) |
| VA (V1), VB (V2) | Sol @ xhigh / full-access (prod pin)     | **GLM 5.3 Flash @ max**   |

Effort guard: every gateway call verified per stage via the Kafka AI-usage topic (`kafka_ai_usage.py`); all GLM stages ran `max`, Sol `xhigh`, Opus `xhigh` in all four runs. Truth protocol: match to the 76-cluster registry, reuse unanimous registry verdicts and prior per-finding verdicts, refutation-first fresh verification against a worktree at `1341596e`. Scorecards: `findings/{RA,RB,VA,VB}.score.md`.

## GLM as reviewer (RA, RB): cheap and near-useless

|                               | RA (GLM r1) | RB (GLM r2) | Controls (Sol xhigh, L/M/N runs) | Sol medium (PA/PB) |
| ----------------------------- | ----------- | ----------- | -------------------------------- | ------------------ |
| findings judged (post-dedup)  | 14          | 12          | 19–23                            | 14–15              |
| real findings (reviewer side) | 1/14 (7%)   | 4/12 (33%)  | 47–65%                           | 47–50%             |
| new real issues               | 1           | 2           | 0–5                              | 0–1                |
| real clusters found           | 0           | 2           | 3–9                              | 3–6                |
| survived Opus validation      | **0**       | **0**       | 6–12 kept                        | 6–7 kept           |
| review + blind-spot cost      | $1.82       | $1.64       | ~$26                             | ~$10.50            |

The failure is substance, not just volume. GLM's dismissed findings are praise restated as findings, wrong-premise claims (a "dead variable" that is a live closure capture), suggestions the code already implements, and style nits. Its five real findings across both runs are all minor (an unexplained `cast(Any)` idiom, missing rationale in an evidence bundle, a dead alias, a cosmetic dead PR number, one config-UX bug). Opus dismissed all 26 findings across both runs with substantive, spot-checked rebuttals — 21/21 junk correctly dropped, and the 5 real-but-minor ones dropped too (mostly as style/wording; over-strict but low-cost given what they were). **Both GLM-reviewer runs would have published an empty review.** A ~$1.70 review that yields nothing still costs $6.60–7.10 in Opus validation to establish the nothing.

## GLM as validator (VA, VB): 10–50× cheaper, but it drops verdicts on the floor

|                                   | VA (GLM v1) | VB (GLM v2)    | LA/LB (Opus) | MA/MB (Sol) | NA/NB (Sonnet) |
| --------------------------------- | ----------- | -------------- | ------------ | ----------- | -------------- |
| reviewer real rate (sanity check) | 13/21 (62%) | 14/22 (64%)    | 50–52%       | 63–65%      | 50%            |
| kept                              | 15          | 7              | 11–12        | 18          | 16–22          |
| kept that were real (precision)   | 9/15 (60%)  | 6/7 (86%)      | 67–82%       | 61–67%      | 50%            |
| real findings kept (recall)       | 9/13 (69%)  | **6/14 (43%)** | 73–75%       | 92%         | 73–100%        |
| not-real findings dropped         | 2/8 (25%)   | 7/8 (88%)      | 64–82%       | 0–14%       | 0–27%          |
| findings with NO verdict          | 1           | **12**         | 0            | 0           | 0              |
| validation cost                   | $1.05       | $0.42          | $23–24       | $14–16      | $10–12         |
| cost per verdict                  | $0.05       | $0.02          | $1.06        | $0.72–0.80  | $0.48–0.53     |

The reviewer side replicated cleanly (62–64% real, in Sol's band), so the validator comparison is apples-to-apples. Two disqualifying problems:

1. **Silent coverage holes.** VB's headline "86% precision, 88% junk dropped" is an artifact: 12 of 22 findings never received a verdict at all, and 7 of its 8 lost real findings — including three must_fix truths (caller-writable `pr_url` reaching approval, `internal=True` killing the carve-out, the writable-binding authorization hole) — fell into that hole rather than being argued away. The Kafka trace shows what happened: validation-c2's session made 2 calls and died (plus two zero-token `claude-opus-4-8` rows — failed no-ops), where V1's equivalent chunk took 180 calls. A validator that skips findings fails open in the worst direction for a publish gate.
2. **Unstable judgment when it does judge.** VA kept 6 of 8 not-real findings (25% junk filtering — worse than every arm except Sol/Sonnet's known keep-everything bias) including two registry-refuted claims upheld as must_fix. VB flipped to strict. Same model, same effort, same PR, opposite posture.

The cost is genuinely remarkable — $0.02–0.05 per verdict vs Opus's $1.06 — and GLM's kept-verdict write-ups were coherent when they existed. But recall at 43–69% against Opus's stable 73–75%, plus the no-verdict hole, ends the argument. (The optional blind argumentation judge was skipped: the coverage hole dominates any write-up-quality signal.)

## Bugs found on the way

- **The "missing scope: project:read" warning is non-fatal** — first read as a handshake refusal, later disproven: the project fetch is best-effort, and the only scope whose absence refuses a session is `user:read` (#88697, already fixed). A `project:read` addition was tried, then dropped: it buys only attribution, but `GET /api/projects/<id>/` returns the team's unmasked `secret_api_token`, which an injectable session must not reach.
- **The skill-fetch prompt says `skill-get(...)` but non-allowlisted MCP clients get an exec-only surface** since #69629 — Claude/Codex models bridge the gap, GLM does not. Prompt wording or a tools-mode header needs to be a deliberate choice, not luck (FINDINGS item 5).
- Zero-token `claude-opus-4-8` rows can appear in the usage stream when a validation session's calls fail — watch for them as a session-death signature.

## Ops notes for the next experiment

`FINDINGS.md` items 1–13 carry the full list (Baseten exclusivity, tools-mode override, worker-wedge remedy, image rebuild costs, watchdog design — watch ngrok traffic age and skip Go zero timestamps, not harness-log mtime). The night itself ran clean: four runs, zero wedges, zero tunnel outages, all four effort/model guards green, scoring fanned out over 68 workflow agents with zero errors.

## Recommendation

1. **Keep the prod pins**: Sol @ xhigh reviewer, Opus 5 @ xhigh validator. GLM 5.3 Flash joins neither seat.
2. If MCP-session project attribution is wanted, do it server-side from the team id already on the token — never by granting the session `project:read`, which would expose the team's unmasked `secret_api_token` to an injectable agent.
3. If a future flash-class model is retried, budget the tools-mode question first (FINDINGS 5), and check validator **coverage** (every finding gets a verdict) before judging precision/recall — it is the metric the standard table hides.
