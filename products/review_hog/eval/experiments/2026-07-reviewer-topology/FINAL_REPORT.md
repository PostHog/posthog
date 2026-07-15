# Reviewer-topology quality experiment — final report

> 15 runs · 7 configs · frozen PR #62096 · model constant (claude-opus-4-8 @ xhigh) · validator constant (strict)
> Yardstick: old ReviewHog's 10 findings (archived copy: `fixtures/old_reviewhog_report.md`)
> Judged by one LLM judge per dump (root-cause matching), raw output in `judge_results.json`. Runs 2026-07-01/02.
> **Judge calls are unreviewed by a human — spot-check the per-run `notes` in `judge_results.json` before acting on close calls.**

## TL;DR

1. **Topology moved old-coverage from 1/10 to 3/10 valid — but five of the old ten findings were never surfaced by ANY of the 15 runs across ANY topology.** The binding constraint is not chunking or pass structure; it's what the perspective skills look for, plus validator strictness. Topology tuning alone cannot close the gap to the old system.
2. **Best topology per token: C4-completeness** (small chunks × parallel perspectives + one "what did everyone miss?" gap pass per chunk). Its best run leads every quality metric (3/10 old-coverage, 8 total judge-plausible valid findings). The gap pass demonstrably adds breadth (4–6 of its raw findings per run).
3. **The new reviewer is not strictly worse than the old — it's differently focused.** Every run produced 1–3 judge-validated findings the old tool never found, including two judged stronger than anything in the old report (match-all element-step actions; root-team scoping must_fix).
4. **Validator strictness (held constant, out of scope) costs ~1–2 old-coverage points by itself:** old #6 was surfaced by 8 runs and killed by the validator in 7; old #2's catches were dismissed 4 of 9 times. The old (lenient) validator upheld both.

## Config glossary — what each C-N actually tested

All configs share: PR #62096, 3 perspective skills (logic-correctness, contracts-security, performance-reliability), Claude Opus 4.8 @ xhigh, the same strict validator. Only the review _topology_ changes.

| config              | exact setup                                                                                                                                                                                                                          | the question it answered                                                                                   |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| **C0-baseline**     | Today's prod behavior: PR is under the 1000-added-lines gate → reviewed as **one chunk**; the 3 perspectives run **in parallel**, each in its own fresh sandbox (3 review units).                                                    | Control.                                                                                                   |
| **C1-smallchunks**  | Semantic LLM chunker forced on with small targets (250/400 added lines) → PR splits into 2–3 concern chunks; 3 perspectives **× each chunk**, all parallel, fresh sandbox per unit (6–9 units).                                      | Does chunk granularity alone improve coverage?                                                             |
| **C2-sequential**   | One chunk (as C0), but perspectives run **one after another**; each later one sees the earlier ones' findings and is told "find what they missed, don't re-report" (old ReviewHog's cumulative-pass style).                          | Does "dig deeper" pressure alone improve coverage?                                                         |
| **C3-both**         | C1 + C2 combined: small chunks AND sequential perspectives within each chunk (chunks still parallel to each other).                                                                                                                  | Do the two levers compound?                                                                                |
| **C4-completeness** | Small chunks + parallel perspectives + **one extra "completeness" agent per chunk** that runs after the wave, sees all its findings, and hunts for what everyone missed (the "gap pass").                                            | Can one gap sweep buy sequential's breadth without its latency?                                            |
| **C5-warmsession**  | Small chunks, but instead of a fresh sandbox per (perspective × chunk), **one long-lived sandbox session per perspective**; that session reviews the chunks as successive turns, reusing its context (3 sandbox boots instead of 9). | Does context reuse cut cost without hurting quality? (Cost: yes. Quality: no — anchoring.)                 |
| **C6-pinnedchunks** | Chunk structure **hardcoded** to the best-performing 3-way split seen in earlier runs (core.py / tool+toolkit / frontend); parallel perspectives; no chunking LLM call.                                                              | Was the "good" 3-chunk structure causal for the best runs, or luck? (De-confounder — answer: partly luck.) |
| **C7-gappinned**    | **C4's gap pass + C6's pinned split** (hence the name: gap + pinned). Run after the main report.                                                                                                                                     | Does the winning topology hold once chunker randomness is removed? (Yes: 6 valid findings, both runs.)     |

## The coverage matrix (the experiment's central result)

`V` = caught + validator-valid · `i` = caught but validator-dismissed · `.` = missed. One column per run.

```text
old# | C0₁ C0₂ C1₁ C1₂ C1₃ C2₁ C2₂ C3₁ C3₂ C4₁ C4₂ C5₁ C5₂ C6₁ C6₂ |
  1  |  .   .   .   .   .   .   .   .   .   .   .   .   .   .   .  | never surfaced
  2  |  i   i   V   V   .   i   .   V   .   i   V   .   .   .   V  | 9 catches, 4 killed by validator
  3  |  V   V   V   V   V   V   V   V   V   V   V   V   V   V   V  | caught by every run
  4  |  .   .   .   .   .   .   .   .   .   .   .   .   .   .   .  | never surfaced
  5  |  .   .   .   .   .   .   .   .   .   .   V   .   .   .   .  | once (C4-2)
  6  |  .   .   i   .   .   i   .   V   .   i   i   i   i   .   i  | 8 surfaced, 7 killed by validator
  7  |  .   .   .   .   .   .   .   .   .   .   .   .   .   .   .  | never surfaced
  8  |  .   .   .   .   .   .   .   .   .   .   .   .   .   .   .  | never surfaced (must_fix)
  9  |  .   .   .   .   i   .   .   .   .   .   .   .   .   .   .  | once, invalidated
 10  |  .   .   .   .   .   .   .   .   .   .   .   .   .   .   .  | never surfaced (must_fix)
```

**The five never-surfaced findings (#1 attribution, #4 object-access ordering, #7 unbounded payloads, #8 subagent toolkits, #10 markdown interpolation) include both of the old report's must_fix security findings.** They span toolkit-wiring and frontend concerns and were missed even when their files sat inside the reviewed chunk. This is a _skill-content_ blind spot, not a topology one — no arrangement of chunks, passes, or sessions surfaced them.

Suppression check: the judge found **no** old finding genuinely pre-covered by the PR's 16 prior bot comments (root causes differ), so no coverage excuses apply.

## Config ranking (quality → tokens → wall-clock; better-of-two, variance noted)

| rank | config              | old-coverage valid (runs) | best total valid (old+new) | junk/run | in-tokens/run | wall-clock/run | verdict                                                                                                                                                                                         |
| ---- | ------------------- | ------------------------- | -------------------------- | -------- | ------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | **C4-completeness** | **3** (1, 3)              | **8**                      | 2–3      | 16.2–18.6M    | 22–24 min      | Best quality; gap pass adds real breadth (4–6 raw/run). High variance (chunker drew 2 chunks in run 1, 3 in run 2).                                                                             |
| 2    | C3-both             | **3** (3, 1)              | 6                          | 0–2      | 10.6–14.6M    | ~25 min        | Ties C4's best coverage on its lucky run; sequential's high precision, but 2× wall-clock and same variance problem.                                                                             |
| 3    | C1-smallchunks      | 2 (2, 2, 1)               | 5                          | 0–5      | 11.2–15.0M    | 14–17 min      | Chunking lever alone: modest, consistent gain over baseline.                                                                                                                                    |
| 4    | C6-pinnedchunks     | 2 (1, 2)                  | 4                          | 2–3      | 15.9–18.7M    | 14–16 min      | **The de-confounder: pinned "good" 3-chunk structure lands mid-pack (3–4 dump-valid), NOT the lucky draws' 5–6 — structure helps but review-pass variance co-drove the top runs.**              |
| 5    | C0-baseline         | 1 (1, 1)                  | 4                          | 1        | 10.2–12.0M    | 13–15 min      | Cheapest; reproduces the production coverage gap cleanly (raw=7 both runs).                                                                                                                     |
| 6    | C2-sequential       | 1 (1, 1)                  | 4                          | 0–1      | 10.5–11.3M    | ~25 min        | Zero dedup waste both runs (novel findings per pass) but volume drops; no coverage gain for 2× time.                                                                                            |
| 7    | C5-warmsession      | 1 (1, 1)                  | 3                          | 3–5      | 11.4–12.3M    | 17–20 min      | Cheapest multi-chunk mechanics (3 boots, P×C→P) work flawlessly, but **anchoring replicated in both runs**: chunk 1 rich, later session turns near-silent. Not viable for review quality as-is. |

Secondary observations:

- **Units → raw volume is roughly monotonic** (3 units ⇒ 4–7 raw; 12 units ⇒ 19 raw), but the validator compresses ~55–65% of it regardless of topology.
- **Sequential (C2/C3)** delivers what it promised — zero dedup loss, later passes genuinely dig past earlier ones — but pays for novelty with volume ("dig deeper" framing suppresses re-derivation _and_ total output).
- **Warm sessions (C5)** are the cost architecture (checkout/boot/skill paid once per perspective) but the quality anti-pattern in this shape: both runs show later chunk-turns finding ~nothing where parallel configs found plenty. If revisited, it needs an explicit anti-anchoring device (e.g. per-turn "assume prior turns missed something here").
- **Published precision is high everywhere**: essentially all judge-junk was already validator-dismissed; validator-valid findings were nearly all judged plausible. The strict validator trades recall (see #6) for precision that holds across topologies.

## What actually closes the gap to the old system (next rounds)

Ordered by expected coverage-per-effort:

1. **Perspective-skill content round** — the five never-surfaced findings map to concerns the current three skills demonstrably don't hunt (privileged-tool wiring/agent-safety, write-path authz ordering, output-channel injection, payload-size limits). This is where 5 of the missing 7 points live. (Old ReviewHog's ~24 cumulative review units brute-forced depth; skills can encode it directly.)
2. **Validator calibration round** — #6 and half of #2 died at validation in nearly every run that found them. Revisit the strict criteria on "speculative"/"reachability" dismissals (the old validator upheld both).
3. **Topology: adopt C4's gap pass** — cheapest breadth mechanism found (+1 unit per chunk, no serialization); combine with pinned/deterministic chunking only for eval reproducibility, since C6 showed structure alone isn't the driver.

## Cost totals (this experiment)

~205M input / ~1.9M output tokens across 15 runs (≈13.7M in/run avg) + judge/review workflows (~3.1M). Wall-clock ≈ 4.6 h of run time + orchestration.

## Addendum — C7-gappinned (C4 topology + pinned 3-chunk split, ×2)

Run after the report above, to remove the chunker coin-flip from the winning config.

| run            | chunks     | units | raw→dedup→valid | old-coverage (judge)                                                            | new plausible+valid | in-tokens | wall-clock |
| -------------- | ---------- | ----- | --------------- | ------------------------------------------------------------------------------- | ------------------- | --------- | ---------- |
| C7-gappinned-1 | 3 (pinned) | 12    | 16→11→6         | **2/10** (#3, #6 — the only VALID #6 outside C3-1; #5 surfaced but invalidated) | 4                   | 18.9M     | 23.3 min   |
| C7-gappinned-2 | 3 (pinned) | 12    | 18→11→6         | **1/10** (#3)                                                                   | 4                   | 21.5M     | 23.2 min   |

**What it settles:**

1. **The topology recommendation stands, sharpened.** Gap pass + pinned structure is the most _consistent_ and highest-_output_ config of the experiment (11 dedup / 6 valid in both runs — no other config replicated its own result). If you want a dependable, breadth-maximizing reviewer per token, this is the shape.
2. **But old-yardstick recall did NOT rise with consistency (2/10, 1/10 vs C4's lucky 3/10).** C7's valid findings are dominated by high-quality _new_ issues (RootTeamManager team-scoping divergence, list access-control bypass, pagination non-determinism, cohort-filter crash) — several judged deep and real. This closes the case on headline #1: **no topology in this space recovers the old findings; recall is bound by perspective-skill content and validator strictness.** C4-2's 3/10 was itself part variance.
3. Minor pipeline note: at higher finding volume the dedup let 3 duplicate pairs through across the two runs (e.g. old #3 counted twice as VALID in run 2) — worth a look if the gap pass ships, since gap-pass output overlaps the wave's more than perspectives overlap each other.

**Final recommendation (unchanged in direction, firmer in evidence):** adopt the C4/C7 gap pass for breadth and consistency; pin or determinize chunking only for eval reproducibility; spend the next two rounds on perspective-skill content (the five never-surfaced findings) and validator calibration (#6, #2) — that's where the remaining seven yardstick points live.
