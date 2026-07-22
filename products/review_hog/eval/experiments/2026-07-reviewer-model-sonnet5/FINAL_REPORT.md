# Reviewer-model experiment — final report: Opus 4.8 @ xhigh vs Sonnet 5 @ xhigh

> 4 runs · 2 arms · frozen PR #62096 (head `ba725a89`) · pinned 3-chunk split (12 units/run) · validator/dedup/chunking
> constant (agent default = Opus) · review stage only (wave perspectives + blind-spot units).
> Judged per dump vs the old ReviewHog 10-finding yardstick (`../2026-07-reviewer-topology/fixtures/old_reviewhog_report.md`),
> raw output in `judge_results.json`. Runs 2026-07-03.
> **Judge calls are unreviewed by a human — see the cross-judge divergence note in `judge_results.json` before acting on close calls.**

## TL;DR

1. **Quality parity.** Sonnet 5 @ xhigh matched Opus 4.8 @ xhigh on this PR: 6 dump-valid findings in BOTH Sonnet runs
   (replicating its own result, as only C7 had done before) vs 6 on Opus's clean run (its other run was infra-degraded).
   Old-yardstick coverage is statistically indistinguishable at this n (per-run valid: Opus 2, 2 · Sonnet 3, 1; arm-union
   valid 3 vs 3).
2. **Sonnet reads wider, shallower-per-turn: same units, ~1.7× the turns.** 337/425 generations per Sonnet run vs
   196/247 Opus, and ~1.8× the review-stage input tokens (34.5/37.5M vs ~16/19M). The 2.5× price advantage
   ($2/$10 vs $5/$25 per M) therefore compresses to **~15–25% naive savings per run** — real, but nowhere near the
   price-sheet 60%. (Naive = no cache split; the local token tally can't separate cache reads, so absolute $ are
   overstated for both arms; the ratio is the meaningful number.)
3. **Sonnet is consistently faster: ~21 min effective vs 24–25 min** — despite the extra turns. (B2's raw 39.5 min was an
   18-min sandbox-retry stall on one unit's first attempt — model-independent infra, verified in the workflow history.)
4. **Sonnet surfaced two historically-hard yardstick findings:** #6 (surfaced 8 times in the 17 topology runs, validator
   killed 7 — here it _passed validation_, B1) and **#7, which had never surfaced in any prior run of any topology**
   (B2, validator-dismissed). Meanwhile the round's single deepest finding — the `team=` vs project scoping must_fix,
   judge-verified against the repo — came from **Opus** (A2).
5. **The skill-content blind spots persist across model tiers.** #1, #4, #8, #10 (incl. both old must_fix security
   findings) were missed by every run in both arms — same conclusion as the topology round, now shown to be
   model-invariant at two capability tiers. The perspective-skill content round remains where those points live.

## Setup (what varied, what didn't)

One constant flipped between arms: `REVIEW_MODEL` (`reviewer/constants.py`) — `claude-opus-4-8` (arm A) vs
`claude-sonnet-5` (arm B), both at `xhigh`. It feeds only `review_chunk_activity`, so the wave perspectives AND
blind-spot units swap together while chunking/dedup/validation stay on the agent default (Opus) in both arms.
Chunk structure pinned to the C1-run-2/C6/C7 3-way split via a temporary `EXPERIMENT_PINNED_CHUNKS` instrument
(removed after the round). Enablement plumbing (permanent): `claude-sonnet-5` added to
`CLAUDE_REASONING_EFFORTS_BY_MODEL` in `products/tasks/backend/temporal/process_task/utils.py` — the agent package
and LLM gateway already supported it. Model verified live per run via the `$ai_model` split (silent-fallback guard):
337/425 sonnet-5 review generations, support stages on Opus as designed.

## Results

### Funnel, cost, time (per run)

| run         | raw→dedup→valid | review gens | review tokens in/out                  | naive $ (run) | wall-clock                                        |
| ----------- | --------------- | ----------- | ------------------------------------- | ------------- | ------------------------------------------------- |
| A1 opus-4-8 | 15→11→**3\***   | ~196        | ~16M/~200k (of 19.3M/219k total opus) | ~$102         | 24.1 min                                          |
| A2 opus-4-8 | 15→8→**6**      | ~247        | ~19M/~225k (of 23.0M/245k total opus) | ~$121         | 25.1 min                                          |
| B1 sonnet-5 | 17→11→**6**     | 337         | 34.5M/240k (+2.9M/37k opus support)   | ~$87          | 20.9 min                                          |
| B2 sonnet-5 | 18→14→**6**     | 425         | 37.5M/295k (+4.4M/44k opus support)   | ~$101         | 39.5 min (**~21 effective**, sandbox-retry stall) |

\* A1's validation-c1 warm session died on an upstream API timeout after 3 verdicts — 4 of 11 findings carry **no
verdict** (2 of them should_fix), so 3 is a floor, not a measurement. (Kept as-is per user decision; the repair —
re-run `run_review` before reset, skip-resume re-attempts only missing verdicts — is now step 5 of the loop in PLAN.md.)

### Old-10 coverage matrix

`V` = caught + validator-valid · `i` = caught, validator-dismissed · `n` = caught, no verdict (A1's dead session) · `.` = missed

```text
old# | A1  A2  B1  B2 |
  1  |  .   .   .   .  | never surfaced (also 0/17 in the topology round)
  2  |  n   .   V   i  | sonnet's V is the trim/duplicate half; length half died at validation in 2 runs
  3  |  V   V   V   V  | caught by every run (as in all 17 topology runs)
  4  |  .   .   .   .  | never surfaced (0/17 prior)
  5  |  V   .   .   .  | 2nd-ever surface (1/17 prior) — Opus
  6  |  .   .   V   .  | 2nd-ever VALID (validator killed it 7/8 in the topology round) — Sonnet
  7  |  .   .   .   i  | FIRST-EVER surface (0/17 prior) — Sonnet; validator dismissed
  8  |  .   .   .   .  | never surfaced (0/17 prior; old must_fix)
  9  |  i   V   i   .  | validator calibration coin-flip: same root cause, 3 different outcomes
 10  |  .   .   .   .  | never surfaced (0/17 prior; old must_fix)
```

### New findings (not in the old report)

| run | new_plausible (judge) | of which validator-VALID | new_junk |
| --- | --------------------- | ------------------------ | -------- |
| A1  | 4                     | 1 (+2 no-verdict)        | 3        |
| A2  | 4                     | 4                        | 2        |
| B1  | 3                     | 3                        | 3        |
| B2  | 5                     | 5                        | 5        |

Highlights: **A2 (Opus)** found the round's deepest issue — action tools filter `team=` (environment) where actions are
project-scoped, breaking multi-environment projects (must_fix, VALID, judge-verified against `RootTeamQuerySet`).
Both arms independently found the `$autocapture`-only element-matcher silent-drop and the pagination-tiebreaker bug.
**B2 (Sonnet)** found the `list_actions` missing-RBAC-queryset-filter leak (must_fix, VALID) — but the A1/B1 judges
refuted that same finding family (viewer access-level floor makes the leak unconstructible), and the validator itself
split 2-2 across runs; **needs human adjudication** before anyone acts on it. Sonnet's extra volume skews
consider-grade (status-label polish); its junk was reliably validator-dismissed (published precision unharmed).

## Interpretation

- **Same funnel shape, different texture.** Sonnet reviews with more, smaller turns (+72% generations in both runs —
  suspiciously constant) and produces more raw findings (17–18 vs 15) with a longer consider-grade tail; the strict
  validator normalizes both arms to the same 6 valid. Opus goes deeper per finding (the scoping must_fix); Sonnet
  sweeps wider (first-ever #7 surface, #6 surviving validation).
- **The cost story is turns, not price.** Anyone projecting "2.5× cheaper" from the price sheet will be wrong: at equal
  topology and effort, Sonnet 5 spends ~1.7–1.8× the tokens, netting ~15–25%. A cheaper-still configuration
  (sonnet-5 @ high, fewer turns) is the untested cost-floor — that's POTENTIAL_EXPERIMENTS item 3's arm-B/C logic and
  would be the next lever, not more xhigh runs.
- **Validator strictness remains the bigger quality lever** (unchanged from the topology round): across 4 runs it
  killed or downgraded root-cause-correct catches of #2, #6, #7, #9 seven times. The planned validator round is where
  1–2 coverage points per run are recoverable, regardless of review model.

## Recommendation

**Keep `claude-opus-4-8 @ xhigh` as the prod default for now; promote `claude-sonnet-5 @ xhigh` to validated
adopt-candidate.** Quality parity holds on n=2+2 on one PR, but the savings (~15–25%) are modest against the risk of
a single-PR eval, and the round's best finding came from Opus. Flip-worthy triggers: (a) review-stage cost becomes a
scaling constraint — then run the live-PR confirm round (1–2 real PRs, unpinned chunks, prod topology) per the
item-3 C-win path; or (b) the latency win (~15%) starts mattering for the Inbox auto-review loop. If cost is the
motive, test **sonnet-5 @ high** first — xhigh's extra turns are where the price edge goes to die.

Registry enablement (`claude-sonnet-5` in `CLAUDE_REASONING_EFFORTS_BY_MODEL`) ships regardless — it's parity with
the agent/gateway/PostHog Code and unblocks any future flip, Slack picker, or per-user choice.

> **Decision postscript (2026-07-03):** the user chose to flip prod to `claude-sonnet-5 @ xhigh` immediately
> (flip-and-watch: dogfood volume means the live-PR confirmation happens in prod, and the change is a one-constant
> revert). The recommendation above stands as the analysis of record; the flip supersedes its default-keep call.

## Hand-offs to other rounds

- **Validator round:** #6's B1 survival is the second-ever VALID for that finding — include it as a calibration case
  alongside the topology round's C3-1. #9's 3-way verdict split (V/i/i on identical root cause) is a clean
  positional/calibration probe.
- **Skill-content round:** #7 finally surfacing (B2) confirms it's _findable_ by a general sweep — its 0/17 history was
  partly volume, not pure skill blindness; #1/#4/#8/#10 remain genuinely skill-blind across both model tiers.
- **Infra:** two distinct one-per-round flakes hit again (validator-session upstream timeout → no-verdict findings;
  sandbox first-attempt failure → 18-min retry stall). Both have known shapes now; the no-verdict repair discipline is
  in PLAN.md step 5, and the retry stall argues for the per-chunk review→validate pipelining idea (POTENTIAL_EXPERIMENTS
  item 7 territory) — one slow unit currently gates the whole run.

## Cost totals (this round)

~115M input / ~1.1M output tokens across 4 runs + 4 judge agents (~0.3M). Naive ≈ $410; true cost materially lower
(cache reads dominate input). Wall-clock ≈ 1.9 h of run time + orchestration.
