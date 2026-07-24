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
