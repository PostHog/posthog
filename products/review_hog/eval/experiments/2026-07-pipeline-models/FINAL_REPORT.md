# Pipeline-models experiment — final report: validator swap (C) and Fable-5-low pipeline (F) vs the Sonnet-review control (B)

> 3 new runs (C ×1, F ×2) + 2 reused controls (B, from `../2026-07-reviewer-model-sonnet5/`) · frozen PR #62096
> (head `ba725a89`) · pinned 3-chunk split, 12 units/run · review stage = sonnet-5 @ xhigh in B/C, fable-5 @ low in F ·
> validator = opus default (B) vs sonnet-5 @ xhigh (C) vs fable-5 @ low (F) · dedup/chunking on agent default everywhere.
> Judged per dump vs the old-10 yardstick + per-verdict correctness, raw output in `judge_results.json`. Runs 2026-07-03.
> **Judge calls are unreviewed by a human. One finding family carries a 3-3 cross-judge split — see "The disputed finding".**

## TL;DR

1. **Every validator model tested is precise; they differ at the margins, not the core.** Judge-assessed verdict
   accuracy: sonnet-5@xhigh ≈ 10.5/11 (C1), fable-5@low ≈ 15/17 and 12/13 (F1/F2), opus-default (B, prior round)
   similar. Across all five runs, essentially zero uncontested junk was published — the strict-validator property
   held under every model. The real differentiators: **C1's sonnet validator produced the first correct upward
   severity escalation ever observed** (team-scoping bug → must_fix, judge-verified; prior rounds noted the raise
   capability never fires), while **fable@low's two judged errors were both on genuinely contested calls** (#6's
   dismissal, the access-control family).
2. **Fable 5 @ low as the whole pipeline is a different operating point, and it replicates:** 25/24 raw findings
   (all-time records), 7/8 valid (8 = all-time high), in **15–16 minutes** (fastest full runs ever) at ~15–16M input
   tokens (⅓ of Sonnet's volume). The volume is a mix — judges verified 4–5 genuinely novel strong findings per run
   (two brand-new classes: `strict=False` property compilation silently over-matching; the get→update round-trip
   silently dropping property filters) — but old-yardstick coverage stays ordinary (3/10-ish valid) and the noise
   tail is real (5–7 junk per run, all validator-killed).
3. **Naive cost RANKING inverts on price, and the local tally can't settle it.** Naive $ (no cache split):
   F ≈ $155–164 > C1 ≈ $119 > B ≈ $87–101 — fable's $10/M input price eats its 3× token-volume win. But fable's
   cache-read price is $1/M, and agentic loops are cache-dominated, so F's TRUE cost could plausibly be the cheapest
   of all arms. **Do not adopt or reject F on cost until the dump tally splits cache reads** (follow-up below).
4. **The chunk-3 / chunk-2 yardstick blind spots persist across four model configurations** (opus-xhigh,
   sonnet-xhigh, sonnet-review+sonnet-validator, fable-low): #1, #4, #8, #10 missed in all 5 runs of this round
   (F1 near-missed #10 — right interpolation site, wrong defect, and its validator dismissed it with a factually
   wrong "React escapes strings" rationale while the judge verified the Markdown-image exfiltration vector is real).
   This is now conclusively a perspective-skill content problem, not a model or effort problem.

## Configuration and verification

| arm                 | review            | validator                       | runs | verified by                                                                  |
| ------------------- | ----------------- | ------------------------------- | ---- | ---------------------------------------------------------------------------- |
| B (control, reused) | sonnet-5 @ xhigh  | agent default (opus-4-8 @ high) | 2    | prior round ($ai_model split)                                                |
| C                   | sonnet-5 @ xhigh  | **sonnet-5 @ xhigh**            | 1    | generation time-windows: opus confined to dedup, validation phase all-sonnet |
| F                   | **fable-5 @ low** | **fable-5 @ low**               | 2    | per-model gens: 176/170 real-token fable, opus = 5/1 (dedup only), 0 errors  |

Instruments: `VALIDATION_*` constants + `start_sandbox_session` model kwargs (permanent plumbing, all-None default);
pinned chunks re-added for the round (removed after). Arm history: the first fable attempt (D1) is VOID — the local
gateway key's Anthropic workspace lacked data retention, every fable call 400'd (`model_not_available`), and the
agent's `fallbackModel` silently reran the whole run on Opus; caught only by the mandated `$ai_model` check, fixed by
a key swap, smoke-tested, and re-run as F1/F2. Full detail in PLAN.md's run log — **treat "the funnel looks normal"
as zero evidence of which model ran.**

## Results

### Funnel, cost, time

| run              | raw→dedup→valid | wall-clock                                       | pipeline tokens in/out | naive $ | validator survival |
| ---------------- | --------------- | ------------------------------------------------ | ---------------------- | ------- | ------------------ |
| B1 sonnet/opus   | 17→11→6         | 20.9 min                                         | 34.5M/240k + 2.9M/37k  | ~$87    | 55%                |
| B2 sonnet/opus   | 18→14→6         | ~21 min eff.                                     | 37.5M/295k + 4.4M/44k  | ~$101   | 43%                |
| C1 sonnet/sonnet | 18→11→**7**     | 43 min (noisy: shared worker; stages ≈ 17/10/15) | 49.9M/352k + 3.0M/27k  | ~$119   | 64%                |
| F1 fable/fable   | **25**→17→7     | **15.9 min**                                     | 15.8M/78k + 0.5M/4k    | ~$164\* | 41%                |
| F2 fable/fable   | 24→13→**8**     | **15.1 min**                                     | 15.0M/79k + 0.1M/4k    | ~$155\* | 62%                |

\* Naive = list price × raw token counts, no cache split. Fable's cache-read rate is $1/M vs $10/M fresh — the real
F cost is likely a fraction of the naive figure; the same applies (less dramatically) to the other arms. The naive
column is comparable across arms only under the (false) assumption of equal cache ratios.

### Old-10 coverage (this round, B shown for reference)

`V` valid · `i` surfaced-but-dismissed · `~` near-miss (right site, wrong defect) · `.` missed

```text
old# | B1  B2 | C1 | F1  F2 |
  1  |  .   . |  . |  .   . | never surfaced in any of 24 runs across 3 rounds
  2  |  V   i |  V |  V   V | F1 caught the trim half, F2/C1 the length half — the two halves now covered
  3  |  V   V |  V |  V   V | caught+valid in every run ever
  4  |  .   . |  . |  .   . | never surfaced
  5  |  .   . |  V |  i   . | C1 = 2nd-ever validation; F1 surfaced it, validator dismissed (judge: half-wrong)
  6  |  V   . |  . |  i   . | F1's dismissal judged WRONG (PR's own bounded-context claim doesn't hold)
  7  |  .   i |  i |  .   . | surfaced twice ever, dismissed both times
  8  |  .   . |  . |  .   . | never surfaced (old must_fix)
  9  |  i   . |  . |  i   V | 5 surfaces, 5 different verdict outcomes across validators — calibration coin-flip
 10  |  .   . |  . |  ~   . | F1 near-miss; its validator's dismissal rationale factually wrong (judge-verified vector)
```

### Validator head-to-head (the round's question)

| validator                 | runs  | judged verdict accuracy      | junk leaked                                           | notable behavior                                                                                                                                                                                                                     |
| ------------------------- | ----- | ---------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| opus-4-8 @ high (default) | B1,B2 | high (prior round)           | 0 uncontested                                         | killed #9 in B1 (root-cause-correct catch); split on the disputed family                                                                                                                                                             |
| **sonnet-5 @ xhigh**      | C1    | **≈10.5/11 — best observed** | 0                                                     | **first correct upward escalation** (consider→must_fix on the team-scoping bug, judge-verified); every load-bearing dismissal claim spot-checked true                                                                                |
| fable-5 @ low             | F1,F2 | ~15/17, 12/13                | 1 contested (the disputed family, F2's only must_fix) | argumentation precise and grounded (traced a ValueError to the exact generic `except`); errors cluster on genuinely hard calls (#6, #5-half, the disputed family); one dismissal rested on a false premise ("React escapes strings") |

## The disputed finding — needs human adjudication

The `list_actions` object-level access-control family has now been judged by six independent judges across two
rounds: **3 refute** (A1, B1, F2 — strongest: the viewer access floor shipped in the same commit that made actions
access-controlled, so blocking "none" rows can never exist and the REST list filter is a no-op for actions),
**3 validate** (A2, B2, F1 — strongest: `filter_queryset_by_access_level` excludes object-level-"none" ids
regardless of resource-level access, `ActionViewSet` includes `AccessControlViewSetMixin`, and the PR's own
`get_action` enforces `check_object_access`, so list-vs-get is internally inconsistent). Validators split the same
way across runs. Both camps cite real code. **This is the single most consequential open call of the experiment
(must_fix if real) and cannot be settled by more LLM opinions.**

## Recommendations

1. **Validator: promote `sonnet-5 @ xhigh` to adopt-candidate.** On n=1 it was the most accurate validator observed
   and the only one whose severity-escalation capability fired (correctly). Its cost adds ~15M in/run over the opus
   default (noise at these volumes) and its survival rate (64%) stayed in band — no rubber-stamping. Confirm on 1–2
   live PRs before flipping `VALIDATION_*` in prod (constants are parked at all-None = opus default).

   > **Decision postscript (2026-07-03):** the user adopted it immediately — `VALIDATION_*` flipped to
   > `claude-sonnet-5 @ xhigh` (flip-and-watch, same as the review flip). The whole review pipeline except
   > dedup/chunking now runs Sonnet 5 @ xhigh. Watch items on live reviews: verdict quality vs the Opus era,
   > junk leakage staying ~0, and the escalation behavior. Revert = the three `VALIDATION_*` constants to None.

2. **Fable-5 @ low: hold as a "fast sweep" candidate pending real cost data.** Fastest and highest-volume
   configuration with replicating results and genuinely novel verified finds — but naive pricing says it's the most
   expensive arm, and only a cache-aware token tally can settle whether it's actually the cheapest. **Next concrete
   step: extend `dump_result.py` to split `$ai_cache_read_input_tokens` per model** (one query change), then one
   re-run decides. Prod prerequisite regardless: the gateway allowlist entry for `claude-fable-5` (in tree today).
3. **Adjudicate the disputed access-control finding by hand** (a PostHog RBAC owner reading both arguments settles
   it in minutes). Whichever way it lands, feed the outcome to the validator round as a calibration case.
4. **The skill-content round is overdue** — four model configs, 24 runs, and #1/#4/#8/#10 (both old must_fix
   security findings among them) have never surfaced. No model/effort/validator change will find them; the
   perspective skills must hunt those grounds explicitly.
5. **File the fallback-observability issue on the agent repo:** a 100%-failing pinned model produced a
   normal-looking run on the fallback model with zero surfaced signal, twice this week (D1 here; A1's validator
   session death was the milder cousin). The agent should emit a loud "session fell back from configured model"
   marker; eval harnesses should keep the `$ai_model` check regardless.

## Addendum — arm G: sonnet-5 @ HIGH, both stages (×2, run after the report)

Added by the user post-adoption ("last two experiments"): the effort-tier question — does dropping the freshly
adopted all-Sonnet pipeline from xhigh to high keep quality at lower cost?

| run | raw→dedup→valid | wall-clock | sonnet tokens in/out | naive $ | old-10 valid   |
| --- | --------------- | ---------- | -------------------- | ------- | -------------- |
| G1  | 11→10→5         | 21.3 min   | 27.4M/198k           | ~$60    | 2 (#2, #3)     |
| G2  | 17→11→5         | 19.1 min   | 35.2M/224k           | ~$75    | 3 (#3, #5, #9) |

**Answer: no — the effort drop trades real findings for the savings.**

1. **Cost fell ~40%** vs xhigh (27–35M vs 50M in; gens 342/367 vs 508) — the saving is real and the biggest
   cost lever found for Sonnet.
2. **But discovery degraded, and the judges verified the losses are real findings, not noise:** valid fell to
   5/5 (xhigh: 6–7), G1's 11 raw was the lowest of any Sonnet run and included a dedup leak (old #3 kept twice),
   and G1's near-miss on old #8 is the sharpest illustration — the reviewer QUOTED the "DO NOT EXTEND THE
   TOOLKIT" warning and still concluded "add a feature flag" instead of the subagent capability-boundary defect.
   Deeper reasoning is precisely what turns that observation into the finding.
3. **Verdict quality held perfectly at high** (judged 10/10 and 11/11 correct) — effort buys review DEPTH, not
   validation judgment. If cost pressure ever demands a split config, review@xhigh + validation@high is the
   defensible combination, not high across the board.
4. The disputed access-control family gained one judge per camp (now **5-4**: refute A1/B1/C1/F2/G2 · validate
   A2/B2/F1/G1) — G2's judge added the strongest dismissal evidence yet (the deliberately commented-out
   `get_list_response_with_access_control` documents list-ACL as a product-wide decision), G1's judge the
   strongest validation evidence (REST list DOES filter via `routing.py:369-395`). Human adjudication stands.

**Recommendation: keep the adopted `xhigh` on both stages** (constants already reverted). The effort knob is
now measured: −40% cost for −1–2 valid findings and the loss of exactly the deep catches the reviewer exists for.

## Cost totals (this round)

~200M input / ~1.3M output tokens across C1+F1+F2+G1+G2 (+ the void D1 ≈ 5.5M opus) + 5 judge agents.
Naive ≈ $575; true cost substantially lower (cache-dominated). Wall-clock ≈ 2.5 h runs + orchestration.
