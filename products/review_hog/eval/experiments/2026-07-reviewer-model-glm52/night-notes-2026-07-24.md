# Overnight 4-way extension — working notes (2026-07-24)

Working notes for the C/D arms; folded into FINAL_REPORT.md at the end of the night. Timestamps UTC.

## Run C1 (`C-gpt55-xhigh-1`, report `019f9122-…8cf5`, 22:39–23:54, 4548s) — HARD FAIL #1

Dump: `runs/C-gpt55-xhigh-1.md` (funnel 4 chunks / 7 units / 10 raw / 7 dedup / 0 valid). Run "finished" green but is not a valid arm-C data point: perspective coverage of chunks 1 and 2 was lost entirely — only chunk 3 (`tools/pr-approval-agent`) got perspective reviews.

**Root cause — deterministic model refusals.** Every failed perspective attempt (14 of 17) ended with ACP `stopReason: "refusal"` ~90–130s into the turn (from S3 turn logs, `_posthog/turn_complete`):

| chunk | perspective attempts | refused | completed |
| ----- | -------------------- | ------- | --------- |
| c1 (review_hog backend + generated TS) | 4 | 4 | 0 |
| c2 (stamphog backend/facade) | 4 | 4 | 0 |
| c3 (pr-approval-agent tools) | 6 | 3 | 3 |
| c4 (docs) | 0 (selector pruned) | — | — |
| blind-spots c1–c4 | 4 | 0 | 4 |

gpt-5.5's provider-side safety layer declines the perspective-review turn on the security-heavy chunks (the PR's provenance/spoofing/token-gating code), with or without the perspective skill loaded. Blind-spot prompts (audit the wave's findings for gaps) never refused. Validation (opus-4-8, Claude adapter) unaffected.

**Secondary findings (ops/product bugs, independent of verdict):**

1. **Refusal → 30-min hang:** `poll_for_turn` (products/tasks `custom_prompt_internals.py`, `MAX_POLL_SECONDS=1800`) does not treat a completed-with-refusal turn as terminal; each refused unit burned the full 1800s window, then Temporal retried once (final attempt skips). A ~90s refusal cost ~62 min of wall-clock per unit. Fix: treat `stopReason: refusal` as a terminal turn failure.
2. **Codex MCP flakiness:** 9 of 21 Codex sessions never got the `posthog` MCP tools (`posthog/exec` absent; agent: "MCP skill reader is not exposed in this session") and fell back to local `.agents/skills` (incl. `security-audit`). Not correlated with refusal (refusals happened with MCP present too), but those sessions review without the perspective skill → invalid arm data even absent refusals.
3. **Codex telemetry gap:** agent-side usage shows OpenAI cached reads (e.g. 65,920 of 71,483 input) but `$ai_generation` reports `cache_read=0` for all gpt-5.5 gens → gateway prices the full input as fresh; gw$ for Codex runs is overstated, and `dump_result.py`'s `true $` can't price gpt-5.5 at all (unpriced model).
4. Both turn logs end with `Direct artifact upload failed … fetch failed` + `Discarding handoff checkpoint … packBytes:120193428` — 120MB handoff pack upload fails in Modal sandboxes (pre-existing? noise? worth a look).

**Decision:** per the agreed failure policy (hard-fail → retry once; two hard fails → skip to D), C run #2 launched 00:09:52 UTC as the policy retry (`C-gpt55-xhigh-2`, start epoch 1784851792). Expected outcome: same refusals (content-deterministic); if so, arm C closes as DNF and arm D starts.

## Run C2 (`C-gpt55-xhigh-2`, report `019f9175-…ce0c`, 00:09–01:35, 5143s) — VALID (with caveats)

Dump: `runs/C-gpt55-xhigh-2.md` (4 chunks / 12 units / 14 raw / 10 dedup / 2 valid, 0 model switches, review stage 69m01s, gens 379, gw $36.10 — overstated by the Codex cache-telemetry gap; true cost unpriceable from `$ai_generation`).

The retry ladder went to a **third attempt** this run, and refusals proved attempt-stochastic rather than absolute: attempt 1 refused 8/8 (~2.5 min in), attempt 2 refused 6/8 (p2-c3, p1-c3 completed), attempt 3 completed 6/6 (01:13–01:15, resumed sessions). Full perspective coverage of chunks 1–3 resulted (8 selected pairs; the selector picked 8 this run vs 9 in C1).

**Caveats to carry into judging/report:**

- 4 of 8 perspective units (p1-c2, p2-c2, p3-c2, p1-c3) completed in sessions that never had MCP → reviewed WITHOUT their perspective skill (local `.agents/skills` fallback).
- Reviews were assembled across refusal-interrupted resumed sessions (cumulative ~20–30 gens/unit); depth is thin vs Sonnet/GLM units (raw 1–2 issues/unit).
- Refusal tally across both C runs: 22 of 25 first/second perspective attempts refused; 17/17 on first attempts.

Arm C status: C1 = hard fail, C2 = valid-with-caveats. **C3 top-up skipped** (decided 02:30 UTC): C2's caveats (skill-less units, resume-assembled reviews) would dominate any stability comparison, the refusal behavior is already characterized across 25 attempts, and the failure policy's spirit is "don't burn the night".

## Run D1 (`D-opus48-xhigh-1`, report `019f91c6-…f556`, 01:39–02:24, 2724s) — VALID, clean

Dump: `runs/D-opus48-xhigh-1.md` (4 chunks / 13 units / 14 raw / 14 dedup / 1 valid, 0 switches). Fastest run of the experiment: 45.4 min wall, review stage 26m22s. Zero unit loss, zero retries. Opus is selective (~1 raw issue/unit) and expensive: true $57.52 (gens 388). Purity probe: all review + blind gens on `claude-opus-4-8` (fallback indistinguishable by construction — noted).

## Run D2 (`D-opus48-xhigh-2`, report `019f91f1-…28d4`, 02:25–03:09, 2645s) — VALID, clean

Dump: `runs/D-opus48-xhigh-2.md` (4 chunks / 12 units / 16 raw / 16 dedup / 1 valid, 0 switches,
review stage 24m16s, 44.1 min wall, true $52.26). Same profile as D1: zero retries, purity clean.

## Judging prep (done during C2)

- PR worktree: `<scratchpad>/pr72680_tree` @ `1341596e` (HTTPS fetch).
- Diff: `<scratchpad>/pr72680.diff` (2222 lines, via `rtk proxy gh pr diff`).
- Blind sets regenerated: X=A1 (20), Y=B1 (17), P=A2 (24), Q=B2 (19) in `<scratchpad>/judge/`; new
  R=C1 (7), T=C2 (10), U=D1 (14), V=D2 (16).

## Judging (03:4x–04:1x UTC)

Workflow `wf_606fa251-156`: 47 adversarial verifiers (R/T/U/V, effort high, against the worktree) +
incremental clusterer (56 clusters over all 8 sets, every id covered exactly once) + 3-lens blind
panel over M1=X+P / M2=Y+Q / M3=R+T / M4=U+V. Evidence: `judge-fourway.json`. First invocation
silently spawned ZERO verifiers — the Workflow `args` arrived JSON-stringified, `setCounts[s]`
became undefined, and the judges ranked on unverified sets; caught via `agent_count=4`, fixed with a
defensive parse + count assertion, resumed (clusterer cache-replayed, judges re-ran). Lesson recorded
in memory.

Results and verdict: see FINAL_REPORT.md § 4-way extension. Experiment hacks reverted 03:20 UTC
(backend tree byte-identical to master); DB wiped after every dump; nothing committed.
