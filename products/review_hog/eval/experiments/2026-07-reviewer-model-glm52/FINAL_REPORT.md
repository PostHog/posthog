# FINAL REPORT — reviewer-model comparison for the perspective-review step

**Question:** is `@cf/zai-org/glm-5.2` better than `claude-sonnet-5` at applying ReviewHog's review
perspectives? Everything else held constant (validator Opus 4.8 @ xhigh, one-shots Sonnet, pinned
4-chunk split, zero-comment clean room, PR frozen at `1341596e`). Setup and decisions: [PLAN.md](./PLAN.md).

> **Extended overnight 2026-07-24 to a 4-way comparison** — two more arms on the identical setup:
> `gpt-5.5` @ xhigh via Codex (arm C) and `claude-opus-4-8` @ xhigh via Claude (arm D), 2 runs each.
> The A/B analysis below is unchanged; the extension is in [§ 4-way extension](#4-way-extension-2026-07-24-gpt-55-codex-and-opus-48)
> and the recommendation at the end covers all four models. **The 4-way verdict does not change the
> A/B one: `claude-sonnet-5` @ xhigh stays.** Opus 4.8 is ~1.5× faster but ranked last by all three
> blind judges; gpt-5.5 is operationally unusable in this pipeline (provider-side refusals).

**Verdict: not better — different, and on balance Sonnet 5 stays.** The blind panel split 2-1 for GLM
on lenses (recall-reliability and impact for GLM, precision for Sonnet, all moderate margins), but the
trade-off it describes favors keeping Sonnet as the sole perspective reviewer today: Sonnet finds twice
the confirmed-real breadth at ~1.6× the precision, run-stably, and materially cheaper. GLM's genuine
edge — repeatably landing the deepest catches — is real but comes wrapped in an 80% noise rate and a
40-100% higher finder-stage cost (no prompt caching on the Cloudflare path). Recommendation and the
conditions that would flip it are at the end.

## Runs

Two runs per arm (adaptive design: round 1 split → round 2 triggered). Labels map to dumps in `runs/`.

|                                      | A1 (Sonnet) | A2 (Sonnet) | B1 (GLM) | B2 (GLM) |
| ------------------------------------ | ----------- | ----------- | -------- | -------- |
| Finder units                         | 13          | 12          | 12       | 13       |
| Raw → dedup → pipeline-valid         | 25→20→3     | 26→24→5     | 21→17→2  | 24→19→2  |
| **Independently verified real**      | **7/20**    | **7/24**    | **3/17** | **4/19** |
| …of which must_fix / should_fix      | 0 / 4       | 1 / 1       | 1 / 0    | 2 / 0    |
| Review stage (selection→last finder) | 44m38s      | 30m11s      | 42m41s   | 65m39s   |
| Finder-stage cost                    | ~$28.92¹    | ~$30¹       | $41.62²  | $49.51²  |
| Total run cost                       | $46.52      | $56.47      | ~$55.04  | ~$63.92  |
| Model purity (finder gens)           | ~80%³       | ~80%³       | **100%** | **100%** |
| Turn parse failures (retried)        | 1           | 3           | 0        | 0        |

¹ Includes Opus-fallback bleed (see caveats). ² GLM is unpriced at the gateway (`gw $0.00`); computed
from token counts × litellm CF pricing ($1.40/M in, $4.40/M out) — **zero cache reads**, all input fresh.
³ 3 units per Sonnet run silently switched to Opus mid-session (SDK `fallbackModel` rescue).

## Verification & judging method

Every post-dedup finding (73 total) was independently adversarially verified by its own agent against
the real PR tree (worktree at the reviewed head), refutation-first. A cross-set clusterer grouped the
73 findings into 53 underlying issues. Three blind judges (recall-reliability / precision / impact)
scored model "S" vs "G" over both runs each, weighting repeatable catches over single-run luck.
Evidence: `judge-round1.json`, `judge-setP.json`, `judge-final.json`.

## What the evidence says

**Sonnet = breadth + precision + stability.** 14 confirmed-real findings across 44 (31.8% precision)
vs GLM's 7 across 36 (19.4%). Rate is stable per run (7/20, 7/24 vs 3/17, 4/19). Six distinct
confirmed must_fix/should_fix issues vs GLM's four confirmations over three issues.

**GLM = repeatable depth.** GLM owns 3 of the pool's 4 confirmed must_fix verdicts, and caught the
single most valuable bug — the `task.internal` predicate that dead-ends the webhook re-review leg for
100% of production self-driving PRs, with the PR's own tests locking the broken behavior in — in
**both** of its runs (Y5, Q5). Sonnet caught it in only one of two (P12; A1 missed it). GLM's Q18
(receiver-leg linkage spoofing via agent-controlled `output.pr_url`) is the other unique-depth
must_fix; Sonnet's matching finding (X20) reached should_fix framing.

**Low overlap.** Only 16 of 53 issue clusters were found by both models; the finder sets are largely
complementary. The union of both models' confirmed-real issues is materially larger than either alone.

**Pipeline validator vs independent verification.** The strict Opus validator passed 3/5/2/2 findings
per run; the independent verifiers confirmed 7/7/3/4 as real. The validator's picks only partially
track verified-real — worth its own calibration experiment (see follow-ups).

## Confirmed real issues in PR #72680 (act on these regardless of the experiment)

- **must_fix — `task.internal` kills the webhook re-review leg** (Y5/Q5/P12): `find_signal_implementation_run`
  rejects `internal=True` tasks, but production self-driving runs are created with `internal=True`
  (`signals/backend/auto_start.py`); tests fixture `internal=False`, masking it.
- **must_fix — receiver leg stamps `inbox_review` with no positive PR↔run linkage** (Q18/X20/P10):
  agent-controlled `output.pr_url` (branch-matched webhook backstop) can bind a human-authored PR into
  the trusted self-driving path (X3 confirmed the downstream: `_format_self_driving` then renders false
  TRUSTED provenance claims on a path that mints real approvals).
- **should_fix** — X7, X9, P8 (see `judge-round1.json` / `judge-setP.json` for evidence), plus the
  confirmed considers (P4, P13, P17, P19, X12, X17, X19, Q12, Q19).

## Caveats

- **Opus contamination in the Sonnet arm**: every Sonnet run had ~3 units partially rescued onto
  Opus 4.8 by the SDK's always-on `fallbackModel` (~20% of finder gens). Sonnet's numbers are
  strictly "Sonnet with prod's rescue behavior"; pure-Sonnet would likely be slightly weaker. GLM ran
  100% pure both times.
- **Effort pin unverified for GLM**: the CF/Modal translation sets `drop_params=True`; `MAX` vs `HIGH`
  may be cosmetic. Not resolved in this experiment.
- **GLM cost has no gateway pricing**: `$ai_total_cost_usd` is 0.00 for GLM gens — dashboards will
  under-report; fixed only when the gateway prices `@cf/` models in the callback.
- Selection is not pinned, so unit rosters varied 12-13 across runs (chunk split was pinned).
- Single PR, single repo, N=2 per arm. Directional, not definitive.

## Incidents during the experiment (fixes/bugs worth follow-up)

1. **Tainted first A1** (`A-sonnet5-xhigh-1-tainted.md`): nodemon worker restarts mid-run double-executed
   every wave unit (zombie sandboxes kept billing). Lesson: never touch repo `*.py` while a run is live.
2. **False-success empty reviews**: B1's first attempt "finished" green with 0 findings while every
   unit had failed with `403 Model not allowed for product 'background_agents'` — the tasks runner
   returned a validated-empty `IssuesReview` from auth-failed sessions, defeating ReviewHog's
   failure floor. **Real bug, needs a fix in the tasks runner / executor contract.**
3. **`background_agents` allowlist drift**: it lacks `gpt-5.5` too — the old Codex review pin would
   403→silently-fall-back-to-Opus in prod today. The routing fix (below) sidesteps it for ReviewHog.

## Durable changes shipped with this experiment (kept in tree)

- Gateway: `review_hog` product now has an explicit model allowlist (glm-5.2, sonnet-5, opus-4-8, gpt-5.5).
- Agent (`posthog/code` repo): `resolveGatewayProduct` routes `originProduct === "review_hog"` to the
  `review_hog` gateway product instead of piggybacking `background_agents`.
- `eval/scripts/dump_result.py`: per-stage wall-clock timing table (+ `review_stage` in `DUMP_OK`).

## 4-way extension (2026-07-24): gpt-5.5 (Codex) and Opus 4.8

Overnight extension on the identical harness (same PR @ `1341596e`, same pinned chunks, same
zero-comment mock, same Opus validator). Arm C = `CODEX`/`gpt-5.5`/`XHIGH`/`"full-access"`; arm D =
`CLAUDE`/`claude-opus-4-8`/`XHIGH`. Blind sets R (C1), T (C2), U (D1), V (D2); one adversarial
verifier per finding against the PR worktree (same protocol as rounds 1–2, verdicts in
[judge-fourway.json](./judge-fourway.json)); clusters extended incrementally over all 8 sets
(56 clusters, 127+80 ids); 3-lens blind panel over four anonymous models M1=X+P, M2=Y+Q, M3=R+T,
M4=U+V. Per-run ops detail: [night-notes-2026-07-24.md](./night-notes-2026-07-24.md).

### Arm C was a partial DNF: gpt-5.5 refuses the review turn

Every failed arm-C perspective unit ended with ACP `stopReason: "refusal"` ~90–130s into the turn —
gpt-5.5's provider-side safety layer declining ReviewHog's review prompt. **First-attempt refusal
rate: 17/17** across both runs; chunks 1–2 (the PR's provenance/security code) refused 8/8 in C1.
Refusals are attempt-stochastic, not content-absolute: C2's retry ladder reached a third attempt and
all remaining units completed, giving C2 full coverage. C1 never recovered chunks 1–2 → hard fail
(dump kept as evidence; its set R still entered judging). Compounding caveats in C2: 4 of 8
perspective units ran in sandboxes that never got MCP (Codex MCP flake) and reviewed **without their
perspective skill**; unit reviews were assembled across refusal-interrupted resumed sessions.

### Runs C/D

|                                      | C1 (gpt-5.5)                    | C2 (gpt-5.5)     | D1 (Opus 4.8) | D2 (Opus 4.8) |
| ------------------------------------ | ------------------------------- | ---------------- | ------------- | ------------- |
| Status                               | **hard fail** (chunks 1–2 lost) | valid w/ caveats | valid, clean  | valid, clean  |
| Finder units                         | 7                               | 12               | 13            | 12            |
| Raw → dedup → pipeline-valid         | 10→7→0                          | 14→10→2          | 14→14→1       | 16→16→1       |
| **Independently verified real**      | **0/7**                         | **3/10**         | **2/14**      | **3/16**      |
| …of which must_fix / should_fix      | 0 / 0                           | 2 / 0            | 0 / 1         | 0 / 1         |
| Review stage (selection→last finder) | 63m35s¹                         | 69m01s¹          | **26m22s**    | **24m16s**    |
| Finder-stage cost                    | $13.28²                         | $24.26²          | $44.37        | $40.40        |
| Total run cost                       | ~$21                            | ~$36             | $57.52        | $52.26        |
| Model purity (finder gens)           | 100%                            | 100%             | 100%³         | 100%³         |
| Unit retries                         | 8 (refusals)                    | 14 (refusals)    | 0             | 0             |

¹ Dominated by the refusal→poll-timeout product bug (below), not review work.
² Gateway-priced; overstated — OpenAI-side cache reads (~90% of input on warm turns) never reach
`$ai_generation` (telemetry gap below), and `true $` can't price gpt-5.5 at all.
³ For arm D, silent SDK fallback is `claude-opus-4-8` too — indistinguishable by construction.

### 4-way scoreboard (identical counting rule across all 8 runs)

| model             | verified real | precision | must_fix / should_fix / consider | review stage | finder cost/run |
| ----------------- | ------------- | --------- | -------------------------------- | ------------ | --------------- |
| M1 Sonnet 5 (X+P) | 14/44         | 31.8%     | 1 / 5 / 8                        | 30–45m       | ~$29–31         |
| M2 GLM 5.2 (Y+Q)  | 7/36          | 19.4%     | 3 / 1 / 3                        | 43–66m       | ~$42–50         |
| M3 gpt-5.5 (R+T)  | 3/17          | 17.6%     | 2 / 0 / 1                        | n/a¹         | ~$13–24²        |
| M4 Opus 4.8 (U+V) | 5/30          | 16.7%     | 0 / 2 / 2⁴                       | **24–26m**   | ~$40–44         |

⁴ Plus one anomalous verdict (V13: `is_real=true` + severity `not_an_issue` — real-but-trivial).

**Blind panel (3 lenses over M1–M4):**

- **Recall & reliability:** M2 > M1 > M3 > M4 (M2>M1 narrow — M1 wins raw recall, M2 owns the only
  must_fix caught reliably in both runs).
- **Precision:** M1 > M2 > M3 > M4 (decisive for M1: 31.8% vs 19.4%, stable across runs).
- **Impact & actionability:** M2 > M1 > M3 > M4 (narrow, contested).

**M4 (Opus) ranked last on all three lenses** despite being the fastest and 100%-clean operationally:
it is selective (≈1 raw finding/unit, zero dedup merges) but its selections mostly failed verification,
it produced zero confirmed must_fix, and it missed the flagship `task.internal` bug in both runs
(cluster `Y5/P12/Q5/T10`). Its reliable catches (receiver-linkage `U2/V3`, config double-resolve,
carve-out retry blocking) were mostly shared with other models.

**M3 (gpt-5.5) is a paradox:** its one valid run caught BOTH heavy must_fix bugs (T7 receiver-linkage,
T10 `task.internal`) — the only single run to do so — but its other run verified 0/7 real, and the
operational failure mode (refusals, MCP flake) makes it unusable in this pipeline regardless.

### New product bugs found by the extension (independent of verdict)

1. **Model refusal → 30-min hang:** `poll_for_turn` (`products/tasks/.../custom_prompt_internals.py`,
   `MAX_POLL_SECONDS=1800`) doesn't treat a turn completed with `stopReason: "refusal"` as terminal;
   each refused ~90s turn burned a full 1800s poll window before the retry fired. A refusal should
   fail the turn immediately.
2. **Codex MCP flakiness:** 9/21 Codex sandboxes in C1 (and several in C2) never got the `posthog`
   MCP server's tools (`posthog/exec` absent; agent logs "MCP skill reader is not exposed in this
   session") and silently reviewed without the perspective skill, falling back to local
   `.agents/skills`. Needs a hard preflight: no MCP tools → fail the turn, don't improvise.
3. **Codex cache-telemetry gap:** agent-side usage reports OpenAI cached reads (e.g. 65,920 of
   71,483 input tokens) but `$ai_generation` records `cache_read=0` for every gpt-5.5 gen — cost
   attribution over-prices Codex runs and hides caching efficiency.
4. **120MB handoff-pack uploads fail:** every Codex turn log ends with `Direct artifact upload
failed … fetch failed` + `Discarding handoff checkpoint (packBytes≈120MB)` — the handoff
   checkpoint never survives; worth a look independent of this experiment.

## Recommendation

Keep **`claude-sonnet-5` @ `xhigh`** as the perspective reviewer — now confirmed against four models.
For the two new arms specifically:

- **Opus 4.8 @ xhigh: no.** The speed win is real (24–26 min review stage vs Sonnet’s 30–45; ~45 min full runs vs ~67–85;
  fastest wall-clock runs of the experiment at ~45 min) and it runs operationally clean, but as a
  _reviewer_ it delivered the worst verified yield of the four (5/30, zero must_fix, flagship bug
  missed twice) at ~40% higher finder cost than Sonnet. All three blind judges ranked it last. If
  review latency ever becomes the binding constraint, revisit with a recall-oriented prompt/skill
  tune — selectivity, not capability, looks like the limiter.
- **gpt-5.5 via Codex: no, on operational grounds.** 17/17 first-attempt refusals on this PR's
  security-heavy content, plus Codex MCP flakiness, make it unusable in this pipeline today. Its
  depth-per-finding when it does run (both heavy must_fixes in one run) suggests re-testing only
  after the refusal behavior changes upstream and the runner fails fast on refusals (bug 1 above).

Revisit GLM 5.2 if any of these change:

1. **Prompt caching lands on the GLM path** — the cost disadvantage (its biggest practical negative)
   inverts: GLM's raw token flow is smaller than Sonnet's.
2. **A "deep-catch" slot exists** — GLM as an _additional_ blind-spot/perspective lens (not a
   replacement) is the strongest configuration this data supports: low overlap + repeatable depth
   means the union catches more; cost of one extra unit per chunk is the trade.
3. **Validator calibration improves** — GLM's noise (80%) currently survives dedup and burns validator
   time; a cheaper pre-validator triage would change its economics.

## Round 4 (2026-07-30): GPT 5.6 Luna and Terra

Same frozen diff, new target: **PR #75215**, a draft copy of #72680 frozen at `1341596e` (the
original PR moved on to fixes). Same pinned chunks, same zero-comment mock, same Opus validator.
Arm G = `CODEX`/`gpt-5.6-luna`/`XHIGH`/`"full-access"`, arm H = `CODEX`/`gpt-5.6-terra` (same
config). Blind sets M (G1), K (G2), J (H1), L (H2); one adversarial refutation-first verifier per
finding against the worktree (verdicts in [judge-round4.json](./judge-round4.json)); clusters
extended incrementally over all 12 sets (56 → 62); 3-lens blind panel over six anonymous models.
This round ran with working local `$ai_generation` telemetry (see ops notes), so Codex costs are
cache-aware for the first time — `true $` below prices OpenAI cache reads properly.

### Runs G/H

|                                 | G1 (Luna)     | G2 (Luna)     | H1 (Terra)   | H2 (Terra)    |
| ------------------------------- | ------------- | ------------- | ------------ | ------------- |
| Status                          | valid¹        | valid         | valid²       | valid         |
| Raw → dedup → pipeline-valid    | 16→14→3       | 16→14→2       | 8→6→3        | 11→10→3       |
| **Independently verified real** | **3/14**      | **1/14**      | **2/6**      | **4/10**      |
| …of which must_fix              | 0             | 1             | 1            | 3             |
| Review stage                    | 41m39s¹       | 19m49s        | 33m19s²      | **8m04s**     |
| Total run cost (true / gw)      | $11.82/$16.20 | $13.84/$17.67 | $8.88/$14.34 | $12.47/$18.17 |
| Unit retries (fake refusals)    | 24            | ~9            | 9            | ~0            |

¹ ² Wall-clock inflated by one gen-silent retry riding the 30-min poll budget (G1 `p2-c1`, H1
`p3-c1`; H1's unit was lost, 8/9 — under the fan-out floor). Clean-path Terra (H2) reviewed the
whole PR in **8 minutes**.

### Six-model blind scoreboard (verified findings, both runs pooled)

| Model        | Real/Total | Precision | must_fix | Clusters (of 62) | ~Review time | ~Cost/run |
| ------------ | ---------- | --------- | -------- | ---------------- | ------------ | --------- |
| M1 Sonnet 5  | 14/44      | 31.8%     | 1        | **36**           | ~35m         | ~$50      |
| M2 GLM 5.2   | 7/36       | 19.4%     | 3        | 31               | ~55m         | ~$60      |
| M3 gpt-5.5   | 3/17       | 17.6%     | 2        | 13               | ~30m         | ~$25      |
| M4 Opus 4.8  | 4/30       | 13.3%     | 0        | 17               | ~25m         | ~$55      |
| M5 **Luna**  | 4/28       | 14.3%     | 1        | 17               | ~25m         | **~$13**  |
| M6 **Terra** | 6/16       | **37.5%** | **4**    | 11               | **~15m**     | **~$11**  |

Time and cost are close-enough normalized estimates, not exact: representative clean-path review
time (gpt-5.5's excludes the since-fixed refusal-hang tax; the 5.6 arms' one-straggler runs ran
longer) and roughly de-distorted per-run cost (rounds 1–3 were gateway/list-priced with known
skews; Luna/Terra are cache-aware `true $`). Exact per-run figures live in each round's run table.

Judge rankings (blind, one lens each):

- **Recall:** M1 > M2 > M6 > M5 ≈ M4 > M3 — Sonnet still dominates coverage (14 reals over 14
  distinct clusters, 5 of them solo catches).
- **Precision:** **M6 > M1** > M2 > M3 > M5 > M4 — Terra is the panel's best signal-to-noise:
  16 findings emitted, 6 real.
- **Impact:** **M6 > M2** > M1 > M3 > M5 > M4 — Terra's 4 verified must_fix from 16 findings is
  the densest heavy-catch rate ever recorded in this experiment, including the receiver-leg
  approval-redirect hole from both sides (L4 dispatch + L6 worker) and a migration-leaf CI blocker
  (J5 + L3, shared only with Luna's K6) that all four earlier models missed.

### What round 4 changes

- **Terra is the new runner-up and the efficiency frontier.** Best precision, best impact, ~$10/run
  (3–5× cheaper than the Claude arms), and the fastest clean review ever (8m04s). Its weakness is
  recall (11 clusters) — it finds little, but what it finds is disproportionately real and heavy.
- **Luna is not competitive despite the price.** Its Sonnet-like volume (16 raw/run) collapsed
  under adversarial verification (4/28 real, second-worst precision). The pipeline validator's
  "valid" counts (3/2) flattered it; the deeper verifier pass did not.
- **Sonnet 5 @ xhigh stays the default reviewer.** Recall is the pipeline's primary job and Sonnet's
  36-cluster coverage is untouched; it is also second on precision.
- **The "gpt-5.5 refusal storm" was never a safety refusal.** Round 4 proved the mechanism: the
  codex-app-server maps `TurnStatus:"failed"` → ACP `"refusal"`, and BOTH 5.6 arms had ~100% of
  first attempts "refuse" simultaneously ~90s in with **zero tokens billed** — a client-side
  failure (likely the MCP-connect race at boot, amplified by 9 concurrent sandboxes), which
  staggered retries then clear. The round-3 C-arm narrative should be read accordingly. The
  refusal fail-fast fix (landed this round in products/tasks, with regression tests) is what makes
  Codex arms viable at all: each fake refusal now costs ~90s instead of a 30-minute poll timeout.
- **Config worth exploring next:** Terra as a cheap high-signal second-opinion unit (or blind-spot
  lens) alongside Sonnet's wave — the union would have caught every verified must_fix this round
  at a fraction of a second Sonnet pass.

## Round 5 (2026-07-31): Sonnet 5 stability check + GPT 5.6 Sol

Same frozen target (**PR #75215** @ `1341596e`), same pinned chunks, zero-comment mock, and Opus
validator. Two questions: **(1)** were Sonnet's round-1 numbers two lucky rolls? — answered with two
fresh Sonnet runs (A3/A4, blind sets N/O) verified and clustered but **excluded from the panel** so
every ranked model keeps a uniform 2-run basis; **(2)** does GPT 5.6 Sol justify its price at xhigh?
— arm I = `CODEX`/`gpt-5.6-sol`/`XHIGH`/`"full-access"` (sets S/W), full protocol, panel re-ranked
with Sol as the seventh model. One refutation-first verifier per finding against the frozen worktree
(73 verifiers, 0 errors); clusters extended 62 → 74; verdicts in
[judge-round5.json](./judge-round5.json).

### Runs A3/A4 (Sonnet stability) and I1/I2 (Sol)

|                                 | A3 (Sonnet) | A4 (Sonnet) | I1 (Sol)     | I2 (Sol)      |
| ------------------------------- | ----------- | ----------- | ------------ | ------------- |
| Status                          | valid¹      | valid       | valid        | valid         |
| Raw → dedup → pipeline-valid    | 28→23→2     | 30→26→4     | 14→11→2      | 14→13→4       |
| **Independently verified real** | **7/23**    | **7/26**    | **4/11**     | **4/13**      |
| …of which must_fix              | 2           | 1           | 1            | 2             |
| Review stage                    | n/a¹        | 31m58s      | **7m02s**    | 8m58s         |
| Total run cost (true / gw)      | $38.62      | $38.68      | $9.40/$17.31 | $12.91/$19.71 |
| Unit retries (fake refusals)    | —           | —           | 17           | 16            |

¹ The host machine slept ~6.5h mid-run; Temporal recovered the interrupted unit on wake and the run
completed cleanly. Findings and cost are valid; wall-clock is meaningless and excluded. A4 ran on a
healthy stack and carries the representative Sonnet timings.

### Sonnet stability annex: the round-1 numbers were not luck

Four Sonnet runs now exist across two rounds, and the verified-real count is **exactly 7 in every
one of them**: X 7/20, P 7/24, N 7/23, O 7/26 — pooled 28/93 (30.1%), with the original pair at
31.8% and the stability pair at 28.6%. Volume (20–26 findings post-dedup), precision class, and
cluster coverage (36 for X+P vs 33 for N+O, 18 shared) all reproduce. The half-shared cluster
overlap is partly run-to-run variance in _which_ issues Sonnet surfaces and partly **target drift**:
rounds 1–3 reviewed live #72680 before the freeze, where some of today's issues did not exist.

The drift matters for one round-4 claim: the migration-0019 leaf conflict (CI blocker) that round 4
called a Terra/Luna exclusive was caught by **both** Sonnet stability runs as must_fix (N9, O7) —
rounds 1–3 models never saw it because it post-dates their review target. On the frozen PR, Sonnet
catches it. A3 also caught the receiver-leg linkage hole as must_fix (N10); A4's touch on that
cluster did not survive verification.

### Seven-model blind scoreboard (verified findings, both runs pooled)

| Model       | Real/Total | Precision | must_fix | Clusters (of 74) | ~Review time | ~Cost/run |
| ----------- | ---------- | --------- | -------- | ---------------- | ------------ | --------- |
| M1 Sonnet 5 | 14/44      | 31.8%     | 1        | **36**           | ~35m         | ~$40      |
| M2 GLM 5.2  | 7/36       | 19.4%     | 3        | 31               | ~55m         | ~$60      |
| M3 gpt-5.5  | 3/17       | 17.6%     | 2        | 13               | ~30m         | ~$25      |
| M4 Opus 4.8 | 4/30       | 13.3%     | 0        | 17               | ~25m         | ~$55      |
| M5 Luna     | 4/28       | 14.3%     | 1        | 17               | ~25m         | ~$13      |
| M6 Terra    | 6/16       | **37.5%** | **4**    | 11               | ~15m         | ~$11      |
| M7 **Sol**  | 8/24       | 33.3%     | 3        | 16               | **~8m**      | **~$11**  |

Same normalization caveats as round 4. Sonnet's ~cost drops from ~$50 to ~$40: the two cache-aware
stability runs both priced at $38.6 true, showing the round-1 estimate carried list-price skew.
Sol's ~8m is honest — both runs were straggler-free (7m02s / 8m58s review stage).

Judge rankings (blind, one lens each; M1..M6 verified data unchanged from round 4):

- **Recall:** M1 > **M7** > M2 > M6 > M4 > M5 > M3 — Sonnet remains the runaway winner (14 reals
  over 14 distinct real clusters, 5 solo); Sol takes second with 8 reals over 7 real clusters,
  beating GLM.
- **Precision:** M6 > **M7** > M1 > M2 > M3 > M5 > M4 — Terra keeps the crown (37.5%), Sol close
  behind (33.3%), Sonnet third; the judge singled out the bottom four for fabricated findings,
  which Sol avoided entirely.
- **Impact:** **M7 > M6** > M2 > M1 > M3 > M5 > M4 — no model owns an exclusive must_fix; every
  must_fix maps to three heavy clusters (A: dead carve-out `internal=True` leg; B: receiver-leg
  provenance/no-PR-linkage; C: migration-0019 conflict). **Sol is the only model with verified
  findings on all three** (S2+W4 must_fix on C in both runs, W6 must_fix on B, W11 should_fix on
  A) plus the unique security-adjacent S10 (branch fallback binding an unrelated run as
  self-driving).

### What round 5 changes

- **Sonnet 5 @ xhigh is confirmed, not lucky.** Four runs, four times exactly 7 verified reals,
  stable volume, stable precision class, untouched recall crown. It stays the default reviewer.
- **Sol displaces Terra as the Codex champion and the efficiency frontier.** Same ~$11 true cost
  class, faster still (~8m clean in both runs), better recall than Terra (16 vs 11 clusters),
  near-Terra precision, and the panel's #1 impact — the only model to touch all three heavy
  clusters with verified findings. Terra's remaining edge is pure precision density (4 must_fix in
  16 emissions).
- **Round-4 correction:** the migration-0019 CI blocker was never a 5.6-family exclusive — Sonnet
  catches it on the frozen target (both stability runs, must_fix). The claim was an artifact of
  rounds 1–3 reviewing the pre-freeze PR.
- **The second-opinion slot now belongs to Sol.** The round-4 idea (Terra as a cheap high-signal
  lens beside Sonnet's wave) upgrades: Sonnet + Sol union covers every verified must_fix cluster
  this round at ~$11 over Sonnet's ~$40, with Sol also contributing the unique S10 catch.
- **Codex boot-storm tax persists but is survivable:** 17 and 16 fake-refusal first attempts per
  Sol run, all cleared by the fail-fast retries with zero straggler runs — the fix landed in
  round 4 is doing its job.

## Round 6 (2026-07-31): sequential Sol — does injected memory make a second run additive?

Round 5 showed a blind second Sol run mostly re-treads the first (S2→W4 dup, ~3 new reals). Round 6
tests the production shape instead: **arm J** ran Sol twice on the same report with **no DB wipe**,
separated by an empty commit (`a7fb363`, identical tree — the real "new commits → new turn"
trigger), so turn 2 ran as `run_index=2` with the pipeline's **native prior-findings injection**
(`<already_covered_findings_for_chunk>`, DB-sourced, publication-independent — verified present in
all 9 of J2's unit prompts before the wave spent money). Blind sets Z (J1) and E (J2, own-turn
findings only; the dump funnel is cumulative across turns). Verdicts in
[judge-round6.json](./judge-round6.json); clusters 74 → 76.

### Runs J1/J2

|                                 | J1 (Sol, blind) | J2 (Sol + injected memory) |
| ------------------------------- | --------------- | -------------------------- |
| Own-turn raw → dedup → valid    | 11→10→3         | 4→4→3¹                     |
| **Independently verified real** | 3/10            | **3/4 (75%)**              |
| …of which must_fix              | 1               | **2**                      |
| Re-reports of turn 1            | —               | **0**                      |
| Review stage                    | 6m59s           | 8m23s                      |
| True cost                       | $9.56           | **$6.10**                  |

¹ The J2 dump's funnel line reads cumulatively across turns (15→14→6); turn-2's own emissions were
4 raw, all surviving dedup, 3 passing the pipeline validator.

### What the sequential pair found

J2's three verified reals all land in clusters J1 never touched — zero overlap, zero anchoring:

- **E1 (must_fix, brand-new cluster):** the webhook carve-out accepts **any** GitHub bot as the
  self-driving author (`_is_bot_authored` any-Bot floor) — no prior run-set across all seven
  models had surfaced it (cluster #75 of 76).
- **E2 (must_fix):** the migration-0019 CI conflict — which J1's blind pass had _missed_ this
  time; the injection filled J1's gap rather than confining J2 to J1's map.
- **E4 (should_fix):** receiver-leg dedupe excludes FAILED runs → persistent retry loop —
  previously caught only by Sonnet.

J1's own reals: Z8 (must_fix, receiver-leg linkage hole), Z3 (should_fix, the single-acting-
reviewer gate contradicting the PR's thrice-stated any-opted-in spec), Z6 (consider, stale draft
sentence). Pair union: **6 distinct real clusters, 3 must_fix, $15.66 true, ~48 min wall.**

### What round 6 changes

- **The injection works exactly as intended.** Blind repeat runs duplicate (round 5); with memory,
  emission-level duplication was zero and the second turn went where the first hadn't. The
  "5.6 reach limit" hypothesis from round 5 is dead — the reach limit was per-run, not per-model.
- **Marginal Sol turns are absurdly cheap signal:** turn 2 cost $6.10 and returned 3 verified
  reals including 2 must_fix — the best verified-real-per-dollar of the whole experiment
  (0.49 reals/$; one Sonnet run is ~0.18).
- **"Run Sol until dry" becomes a plausible deep-review mode**, and the production re-review path
  already does this for free on every new push — each re-review turn should be expected to add,
  not repeat.
- Caveats: J1 was the weakest blind Sol single yet (3/10 vs 4/11 and 4/13) — single PR, single
  pair, so the per-run variance is real; and the pair's union recall (6 clusters) still sits
  below a single Sonnet run's 7 reals — Sonnet's breadth remains unmatched per-run.

### Updated recommendation

Unchanged core: **Sonnet 5 @ xhigh keeps the wave.** The second-opinion slot stays **Sol**, now
with evidence that its turns compound under the pipeline's native memory: Sonnet wave + Sol lens
on the first review, and Sol's re-review turns keep paying for themselves on every subsequent push.
