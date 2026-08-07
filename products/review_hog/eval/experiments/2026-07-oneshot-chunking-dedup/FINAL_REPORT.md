# One-shot chunking + dedup — final report

> 2 e2e runs + 1 offline chunker batch + 1 live-PR confirmation · frozen PR #62096 (head `ba725a89`) ·
> unpinned chunks · review + validation stages untouched (sonnet-5 @ xhigh, as prod) · one-shot stages on
> `claude-sonnet-5` @ xhigh via the LLM gateway with structured outputs. Judged per dump vs the old
> ReviewHog 10-finding yardstick (`../2026-07-reviewer-topology/fixtures/old_reviewhog_report.md`), raw
> output in `judge_results.json`. Runs 2026-07-03/04.
> **Judge calls are unreviewed by a human — see the notes fields in `judge_results.json` before acting on close calls.**

## TL;DR

1. **The one-shot mechanism works, on both sides of both gates.** Chunking ≤5k adds and dedup ≤50 findings ran as
   single gateway calls (verified per run via `ai_product=review_hog` + `ai_stage` stamps, no
   chunking/dedup sandbox tasks); the live PR #67419 (3217 adds, 61 raw findings) exercised one-shot
   chunking AND the >50 **sandbox fallback for dedup**, then published normally.
2. **The savings are time and reliability, not tokens.** Combine→clean→dedup→persist collapsed to
   **38–54s** (C1's dedup stage measured ≈ 10 min incl. sandbox provisioning); fetch→chunk-plan is
   **36–70s**. Both one-shot stages together cost ≈ **$0.29/run naive** (~50k in / ~4k out each). Schema
   failures: **0 by construction** (structured outputs) vs the 29% archived chunking schema-failure class.
3. **Quality held.** Funnels 13→11→10 and 18→14→9 valid (0 no-verdicts) — valid counts at or above every
   prior round. Old-10 coverage: 4 valid (ONESHOT-1: #2-half, #3, #5, #6 — #5's third-ever surface and
   #6's third-ever VALID) and 2 valid (ONESHOT-2: #2-full, #3), vs the sonnet round's B pair at 3 and 1.
   **Validated-junk count 0 in both runs** (every VALID finding judge-verified as factually accurate).
   Dedup cut ratios in line with archived behavior — no false-merge or rubber-stamp signal.
4. **One real regression signal: the one-shot chunker shatters small PRs.** Offline distribution 4,4,4,3,3
   chunks on the 497-add PR (fragments down to 16 adds) vs the sandbox chunker's 2–3; the in-pipeline
   draws (2, 3) were fine, and the 3217-add live PR got a clean 6-chunk plan. **User verdict: 4 chunks on
   ~500 adds is unambiguously too many** — cost risk (units = chunks × 4), not correctness risk (coverage
   was complete in all draws). Fix: prompt adjustment (size floor + count formula), applied post-round —
   **validated 2026-07-06: 5/5 fixture draws = 2 chunks, full coverage, zero fragments.**
5. **Watch item, outside this experiment's scope:** the sonnet-5 validator is volume-permissive (survival
   91% / 64% here, 86% on the live PR with 30 inline comments) even though nothing it passed on #62096 was
   junk. The user reverted `VALIDATION_MODEL` to `claude-opus-4-8` @ xhigh at round close.

## Setup

Implements `../../POTENTIAL_EXPERIMENTS.md` item 7 with user refinements. What changed vs prod: chunking
(within `CHUNKING_ONESHOT_MAX_ADDITIONS = 5000` reviewable adds) and dedup (within
`DEDUP_ONESHOT_MAX_FINDINGS = 50` issues) execute as one Messages call through
`get_async_anthropic_gateway_client(product="review_hog")` — adaptive thinking, `output_config.effort =
xhigh`, structured outputs from the stage's pydantic model, `ai_stage` stamps, Bedrock fallback off
(`reviewer/sandbox/direct_llm.py`). Above a gate: the previous sandbox path, byte-identical prompts.
Deliberate confound (end-state style): these stages also moved model, agent-default opus-4-8 @ high →
sonnet-5 @ xhigh. Review/validation stages untouched, so old-10 coverage deltas vs prior rounds reflect
review-pass variance and chunk-structure draws, not the one-shot change.

## Results

### Funnel, cost, time (per run)

| run       | chunks (draw) | units | raw→dedup→valid | fetch→chunk plan | wave-end→dedup done | total tok (in/out)  | wall-clock                    |
| --------- | ------------- | ----- | --------------- | ---------------- | ------------------- | ------------------- | ----------------------------- |
| ONESHOT-1 | 2 (unpinned)  | 8     | 13→11→**10**    | 47s/attempt \*   | **38s**             | 33.9M/230k sonnet-5 | 2374s incl. \* (eff ≈ 34 min) |
| ONESHOT-2 | 3 (unpinned)  | 12    | 18→14→**9**     | **36s**          | **54s**             | 53.1M/352k sonnet-5 | 1626s (27.1 min, clean)       |

\* ONESHOT-1's chunking attempt 1 was discarded by a mid-flight worker restart (user-initiated); Temporal
re-ran it after the 5-min heartbeat timeout — infra, not the path. Baselines: C1 (all-sonnet, pinned,
sandbox dedup/chunking) 18→11→7 at 43 min with a ~10-min dedup stage; B pair 17→11→6 / 18→14→6 at ~21 min
effective. Funnel comparison carries the unpinned-vs-pinned chunk-structure caveat.

### Old-10 coverage (judge, root-cause matched)

`V` = caught + validator-valid · `i` = caught, validator-dismissed · `.` = missed

```text
old# | O1  O2 |
  1  |  .   .  | never surfaced in any round (0/21 prior)
  2  |  V   V  | O1 = length half only; O2 = full root cause split across two VALID findings
  3  |  V   V  | caught by every run of every round
  4  |  .   .  | never surfaced (0/21 prior)
  5  |  V   .  | third-ever surface — VALID here (update_action step replacement not gated as dangerous)
  6  |  V   .  | third-ever VALID (unbounded compact list output)
  7  |  .   .  | surfaced once ever (B2, dismissed)
  8  |  .   .  | never surfaced (old must_fix)
  9  |  i   .  | validator dismissed with a sound pre-existing-pattern refutation
 10  |  .   .  | never surfaced (old must_fix)
```

The skill-content blind spots (#1, #4, #8, #10) persist unchanged — consistent with every prior round;
they live in the review stage, which this experiment didn't touch.

### New findings (judge-verified against diff + repo)

| run | new_plausible | of which validator-VALID | new_junk          | junk that passed validation |
| --- | ------------- | ------------------------ | ----------------- | --------------------------- |
| O1  | 6             | 6                        | 0                 | **0**                       |
| O2  | 6             | 6                        | 4 (all dismissed) | **0**                       |

Standouts (both runs, independently): the `list_actions` object-level access-control bypass (must_fix,
VALID, judge-verified vs `filter_queryset_by_access_level` precedent — note the sonnet-5 round's judges
split on a related finding family; this variant survived verification) and the `$autocapture`-only
element-filter silent degradation. O1's validator drew explicit judge praise: every VALID factually
accurate, one sound dismissal, and it caught that a finding's proposed fix wouldn't work.

### One-shot mechanics scoreboard

| check                       | result                                                                                |
| --------------------------- | ------------------------------------------------------------------------------------- |
| chunking one-shot ≤5k adds  | ✓ both runs + live PR (1 gen each, `review_hog/chunking`)                             |
| dedup one-shot ≤50 findings | ✓ both runs (1 gen each, `review_hog/dedup`)                                          |
| dedup sandbox fallback >50  | ✓ live PR #67419: 61 raw → sandbox dedup, zero `review_hog/dedup` gens                |
| schema failures             | 0 (structured outputs)                                                                |
| stage attribution           | ✓ `ai_product`/`ai_stage` stamps separate run stages from local cron noise            |
| live publish                | ✓ #67419 review posted (30 inline comments, pinned to head, `published_head_sha` set) |

### Chunker split distribution (the one regression signal)

One-shot draws on #62096 (497 reviewable adds): in-pipeline 2, 3; offline batch 4, 4, 4, 3, 3 — n=7 total
spread 2,3,3,3,4,4,4 with fragments down to 16 adds. Sandbox archive on the same PR: only ever 2 or 3
(~50/50 over 17 runs). At scale the effect vanished: the 3217-add live PR drew a clean 6-chunk plan
(~536 adds/chunk, vs 11 at the naive 300-add target). Coverage was complete in every draw. Post-round
prompt fix applied (explicit ~100-add floor + count-formula ceiling, shared by both paths) and
**validated 2026-07-06: 5/5 fixture draws = 2 chunks, full coverage, zero fragments** (`sample_oneshot_chunker_fixture.py`).

## Recommendation

**Adopt one-shot dedup now** — routing proven both sides of the gate, decisions in line with archived
behavior, 0 validated junk, ~10 min → <1 min of stage time, and two failure classes gone. **Adopt one-shot chunking too — the tuned prompt is validated** (5/5 draws at 2 chunks on #62096, no
fragments); `CHUNKING_ONESHOT_MAX_ADDITIONS = 0` remains the instant revert if live behavior surprises. Both paths are default-ON in the branch; adoption = committing it.

## Hand-offs

- **Validator round:** the sonnet validator's volume-permissiveness (91%/64%/86% survival) with zero
  validated junk on #62096 is a calibration datapoint, not a junk leak — but 30 inline comments on a live
  PR is a UX question. `VALIDATION_MODEL` reverted to `claude-opus-4-8` @ xhigh at round close (user).
- **Chunker prompt tune:** validated (5/5 clean draws). The fixture sampler makes future prompt iteration
  ~free and fully local — do not ship further prompt changes without a batch.
- **Skill-content round:** #1/#4/#8/#10 remain blind across yet another configuration — unchanged conclusion.
- **Infra:** two non-path incidents worth remembering: a worker restart mid-activity costs a 5-min
  heartbeat-timeout stall (one-shot calls are not resumable mid-flight; Temporal retries them whole), and
  the desktop-harness `LLM_GATEWAY_URL` override can misroute agent-shell scripts (worker unaffected).

## Cost totals (this round)

~87M in / ~580k out across 2 runs (naive ≈ $350, true cost far lower — cache reads dominate) + ~10 offline
chunker calls (~$1) + 2 judge agents. The one-shot stages themselves: ~$0.29/run naive.
