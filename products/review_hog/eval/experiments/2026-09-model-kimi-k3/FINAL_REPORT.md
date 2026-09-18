# FINAL REPORT — Kimi K3 as ReviewHog reviewer and validator

**Date:** 2026-09-01/02 (runs 2026-09-01 18:21 UTC – 2026-09-02 06:36 UTC, autonomous).
**Question:** can `moonshotai/kimi-k3` (via Modal, claude adapter, effort `max` — its ceiling) replace either half of the prod pair (Sol xhigh reviewer / Opus 5 xhigh validator)?
**Answer: no to both** — but with a different failure profile than GLM 5.3 Flash. As reviewer it is junk-heavy with a low real-rate (0%, 20%, 0% across three runs — ~8% real overall) and almost nothing survives validation (published 0, 1, 0). As validator it is cheap and — unlike GLM — never leaves a finding unverdicted, but it keeps too much junk (25% precision), and the whole validator arm is weakened by a harness problem below.

## ⚠️ Read this before trusting the numbers

Two caveats, both documented in `FINDINGS.md`:

1. **The validator arm's Sol reviewer ran at `low`, not the pinned `xhigh` (FINDINGS 7).** kimi-k3 is not in the published npm `@posthog/agent`, so this experiment must build the agent from the local monorepo overlay. GLM instead used the released npm agent, whose Sol reviewer ran at true `xhigh`. In the locally-built agent the codex effort resolves to `low` (the gateway `model/list` does not advertise `xhigh` for `gpt-5.6-sol`, so `SessionConfigState` falls back to `low`). Confirmed real, not a mislabel: Sol here did ~$4–6 / 8–11 findings vs GLM's Sol@xhigh ~$27 / ~22 findings. **Consequence:** the V-arm finding sets are smaller and junkier than the 08-26 Sol@xhigh validator controls, so Kimi-validator precision/recall are **not directly comparable** to LA/LB/MA/MB/NA/NB. Coverage and keep/drop behavior still are.
2. **V2's chunk c4 was validated by an Opus fallback, not Kimi (FINDINGS 9).** Kimi's c4 validation session died (4 no-op calls) and the agent-server fell back to `claude-opus-4-8` to finish — so 1 of V2's 11 findings carries an Opus verdict. V1 was all-Kimi (the clean validator run).

**One thing that went _better_ than GLM:** Kimi bridges the pipeline's `skill-get(...)` prompt on the MCP server's default exec-only surface (smoke turn 3: `skill_found: true`). So Kimi needs **no `x-posthog-mcp-mode: tools` override** and carries **no MCP comparability caveat** — it ran on the same MCP surface as the 08-26 controls.

## Setup

Same clean room as the GLM (07-31 / 08-26 / 08-31) experiments: frozen PR 75215 @ `a7fb363b` (tree `1341596e`), comments mocked to none, pinned 4 chunks / 22 files, team 1 / user 1, DB-only (no publish), local stack + ngrok, Modal sandboxes, `MAX_CONCURRENT_SANDBOXES=4`. Four serial runs alternating arms:

| Run        | Reviewer                                | Validator                 |
| ---------- | --------------------------------------- | ------------------------- |
| R1, R2, R3 | **Kimi K3 @ max** (claude adapter)      | Opus 5 @ xhigh (prod pin) |
| V1, V2     | Sol @ **low** (pinned xhigh — caveat 1) | **Kimi K3 @ max**         |

Effort guard: every gateway call verified per stage via the Kafka AI-usage topic; all Kimi stages ran `max`, Opus `xhigh`, and (the problem) Sol `low`. Truth protocol: each of the 66 post-dedup findings scored by an independent agent — match to the 76-cluster registry and reuse a unanimous verdict, else refutation-first fresh verification against a worktree at `1341596e` (40 fresh-verified, 26 cluster-reuse; 8 of 66 findings real). Scorecards: `findings/{R1,R2,V1,V2}.score.md`.

## Kimi as reviewer (R1, R2, R3): junk-heavy, low real-rate

|                                  | R1            | R2             | R3            | GLM reviewer | Controls (Sol xhigh) |
| -------------------------------- | ------------- | -------------- | ------------- | ------------ | -------------------- |
| findings (post-dedup)            | 22            | 25             | 19            | 12–14        | 19–23                |
| real findings (truth)            | **0/22 (0%)** | **5/25 (20%)** | **0/19 (0%)** | 7–33%        | 47–65%               |
| survived Opus (publishable real) | **0**         | **1**          | **0**         | 0            | 6–12                 |
| review + blind-spot cost         | $13.83        | $12.81         | $13.80        | ~$1.8        | ~$26                 |

Across three runs Kimi emitted **66 findings, only 5 real (~8%)**, with a real-rate that swings 0% → 20% → 0%. That sits in GLM's weak band and far below the 47–65% every Sol/Opus reviewer holds — R1 and R3 replicate at 0%. R2 was the one interesting run: Kimi surfaced a genuine **must_fix** (an inbox carve-out that bypasses the fork and author-trust gates) plus three more real issues — but **Opus validation dropped 4 of the 5**, publishing exactly 1. So publish output across the three runs was **0, 1, 0**: even when Kimi finds a real problem the pinned funnel usually drops it, and ~92% of what it emits is not real. Cost is Sonnet-class (~$13–14 review side per run, ~7× GLM); heavy prompt caching (18–21M cache-read) is the only thing keeping it there.

## Kimi as validator (V1, V2): no holes, but low precision — and the arm is caveated

|                                 | V1 (Kimi v1)  | V2 (Kimi v2)  | GLM validator | Controls |
| ------------------------------- | ------------- | ------------- | ------------- | -------- |
| reviewer real-rate (input)      | 2/8 (25%)     | 1/11 (9%)     | 62–64%        | 50–65%   |
| kept                            | 4             | 4             | 7–15          | 11–22    |
| precision (kept that were real) | **1/4 (25%)** | **1/4 (25%)** | 60–86%        | 50–82%   |
| recall (real kept)              | 1/2 (50%)     | 1/1 (100%)    | 43–69%        | 73–100%  |
| junk dropped                    | 3/6 (50%)     | 7/10 (70%)    | 25–88%        | 0–27%    |
| findings with NO verdict        | **0**         | **0**         | 1 / **12**    | 0        |
| validation cost                 | $2.25         | $3.40         | $0.4–1.0      | $10–24   |

The headline positive: **Kimi never leaves a finding unverdicted** — 0 no-verdict holes in both runs. That was GLM V2's disqualifier (12 of 22 findings never judged). Kimi is also cheap ($0.02–0.05/verdict range). But two problems remain:

1. **Low precision — it keeps too much junk.** In both runs Kimi kept 4 findings of which only 1 was real (25% precision). Given the input was mostly junk (Sol@low produced 9–25% real), a validator's main job is to drop it; Kimi dropped only 50–70%. Every control drops junk harder.
2. **The comparison is not clean.** The reviewer ran at `low` (caveat 1), so the input finding sets (8, 11) are smaller and junkier than the controls' (~22 at 50–65% real). And V2's "no hole" was partly the Opus fallback rescuing chunk c4 (caveat 2) — Kimi's own session died there. So the coverage win is real for V1 (all-Kimi) but softened for V2.

The recall swing (50% → 100%) and the tiny real-finding counts (2, 1) mean the recall numbers carry little signal. What is solid: **Kimi validates every finding (no holes) but is not selective enough (25% precision)**, on a caveated, junkier-than-control input.

## Bugs / gotchas found on the way

- **Local agent overlay needs `pnpm build`, and `pnpm install` first** — a new claude-adapter model added to `models.ts` src does nothing until `packages/agent/dist/` is rebuilt; a failed build `rimraf`s the dist and silently falls back to the npm agent (FINDINGS 1–2). Cost the first smoke.
- **The local-overlay codex reviewer runs at `low`, not the pin** (FINDINGS 7) — the core caveat above.
- **A Kimi validator chunk session can die and fall back to `claude-opus-4-8`** (FINDINGS 9) — check the validation guard per chunk, not just the stage total.
- **Kimi is Modal-served** (not Baseten like GLM): needs `LLM_GATEWAY_MODAL_KIMI_API_BASE` (with `/v1`) + the `wk-`/`ws-` proxy-auth pair, not the `ak-`/`as-` API token (FINDINGS 3).

## Cost

Total ~**$107** for the five runs (R1 $27.2, R2 $34.9, R3 $26.9, V1 $7.2, V2 $10.9) — far under the $250–350 a clean Sol@xhigh V arm would have cost, because Sol ran cheap at `low`. Kimi itself: ~$13–14 per reviewer run (@ max, heavy caching), ~$2–3 per validator run.

## Recommendation

1. **Keep the prod pins**: Sol @ xhigh reviewer, Opus 5 @ xhigh validator. Kimi K3 joins neither seat — as reviewer it is junk-heavy with a low real-rate; as validator it is cheap and hole-free but imprecise, on a caveated comparison.
2. **If the validator question is worth settling cleanly**, redo the V arm with Sol at true `xhigh`. Cheapest fix: make the gateway `model/list` advertise `xhigh`/`max` for `gpt-5.6-sol` (no agent change); alternatives are fixing the agent's codex effort resolution or sed-patching kimi into the published npm agent's dist so the released codex path is kept. All three are in FINDINGS 7.
3. **If a future model is retried through the local overlay**, always break the effort/model guard down **per stage and per chunk** — a reviewer silently at `low` and a validator chunk silently on the fallback model both hide in the stage-family totals.
