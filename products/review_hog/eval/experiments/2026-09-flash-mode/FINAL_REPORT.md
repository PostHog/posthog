# FINAL REPORT — which model should ReviewHog Flash use

**Date:** 2026-09-17 (runs 2026-09-16 21:44 UTC – 2026-09-17 04:00 UTC, judging until ~07:00 UTC).
**Question:** which model, used as both reviewer and validator, gives Flash mode the cheapest and fastest review with good-enough quality?
**Arms:** GLM 5.3 Flash @ high, GPT 5.6 Luna @ low, GPT 5.6 Sol @ low. Two runs each.

## TL;DR

**Pick GPT 5.6 Luna @ low.**
It costs $0.30 per review and takes 15 minutes.
That is 8 times cheaper and 5 times faster than GLM, and 23 times cheaper than Sol.
It posted the most important issue on this PR in both runs.

The price is noise.
60% of the comments Luna posts are not real, and its validator drops almost nothing (1 of 10 not-real findings).
It also finds fewer serious issues per run than Sol (1.5 against 3.5).

- **Drop GLM 5.3 Flash.** It is the slowest arm by far (about 70–80 minutes). It costs 8 times more than Luna. It posts more comments, but most extra ones are minor or not real, and its serious-issue yield swings from 1 to 4 between runs.
- **Keep Sol @ low as the quality fallback.** It posts about twice the serious issues of Luna with less noise (36%), at $7 per review.

## Setup

Same clean room as the August experiments:
frozen PR 75215 at `a7fb363b`, 4 pinned chunks, PR comments mocked to none, `MAX_CONCURRENT_SANDBOXES = 4`, DB-only (no publish), local stack with Modal sandboxes.
Flash mode as committed in `810ab275ccb`: the same model in both sandbox seats, skill bodies inlined into the prompts, Sonnet one-shots for selection and dedup.
Costs are the gateway's own `$ai_generation` figures, read from the local Kafka AI topic per run (`runs/<run>.usage.md`).

## Results

Numbers use the adjudicated truth (see [How "real" was decided](#how-real-was-decided)).
"Serious" means `should_fix` or worse; no finding in this experiment ended up `must_fix`.
Issue counts are distinct issues, so a run that posts the same issue three times counts it once.

### Per model (mean of two runs)

| Model | Cost | Minutes | Comments posted | Serious issues posted | Minor issues posted | Posted but not real | Share not real | Cost per serious issue posted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GLM 5.3 Flash @ high | $2.49 | ~77 | 13.5 | 2.5 | 4.5 | 6.5 | 48% | $0.99 |
| GPT 5.6 Luna @ low | $0.30 | 15 | 7.5 | 1.5 | 0.5 | 4.5 | 60% | $0.20 |
| GPT 5.6 Sol @ low | $7.01 | 21 | 7 | 3.5 | 1 | 2.5 | 36% | $2.00 |

### Per run

| Run | Model | Minutes | Cost | Raw → deduped → posted | Serious posted | Minor posted | Duplicates posted | Not real posted | Validator kept real | Validator dropped not-real |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- |
| `glm-high-1bc` ¹ | GLM @ high | 83 | $2.56 | 46 → 36 → 13 | 1 | 4 | 0 | 8 | 5/9 | 18/27 ³ |
| `glm-high-2` ² | GLM @ high | 71 | $2.41 | 55 → 35 → 14 | 4 | 5 | 0 | 5 | 9/10 | 20/25 |
| `luna-low-1` | Luna @ low | 14 | $0.30 | 9 → 9 → 8 | 2 | 1 | 0 | 5 | 3/4 | 0/5 |
| `luna-low-2` | Luna @ low | 16 | $0.31 | 8 → 8 → 7 | 1 | 0 | 2 | 4 | 3/3 | 1/5 |
| `sol-low-1` | Sol @ low | 20 | $6.59 | 11 → 9 → 7 | 3 | 2 | 0 | 2 | 5/5 | 2/4 |
| `sol-low-2` | Sol @ low | 22 | $7.43 | 14 → 10 → 7 | 4 | 0 | 0 | 3 | 4/5 | 2/5 |

¹ Composite. The first attempt died at dedup (local gateway auth bug). The re-run's reviewer side finished, but its validation sandboxes failed to build (see [Incidents](#incidents)). A validation-only re-run on the same report reused the cached GLM reviews, produced the identical 36 deduped findings, and validated them. Minutes = re-run review stage + validation-only run.
² Includes about 14 minutes of dedup retries caused by the same local auth bug, so the clean time is nearer 57 minutes.
³ One more not-real finding (GC19) got no verdict at all; it was not posted, but it is not counted as dropped.

Validator totals across both runs:

| Model | Real findings kept | Not-real findings dropped | Findings with no verdict |
| --- | --- | --- | ---: |
| GLM @ high | 14/19 (74%) | 38/52 (73%) | 1 |
| Luna @ low | 6/7 (86%) | 1/10 (10%) | 0 |
| Sol @ low | 9/10 (90%) | 4/9 (44%) | 0 |

### Where the money and time go

| Run | Review | Blind-spot | Validation | Selection + dedup (Sonnet) | Review + blind-spot min | Validation min |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `glm-high-1bc` | $0.69 (223 calls) | $0.46 (130) | $1.26 (433) | $0.15 | 45.5 | 34.6 |
| `glm-high-2` | $0.78 (289) | $0.34 (96) | $0.99 (459) | $0.30 | 36.9 | 18.9 |
| `luna-low-1` | $0.14 (42) | $0.06 (18) | $0.06 (28) | $0.04 | 8.7 | 3.8 |
| `luna-low-2` | $0.15 (43) | $0.06 (17) | $0.06 (23) | $0.04 | 10.7 | 3.7 |
| `sol-low-1` | $3.31 (44) | $1.47 (19) | $1.70 (31) | $0.11 | 11.3 | 5.6 |
| `sol-low-2` | $3.98 (57) | $1.68 (25) | $1.68 (33) | $0.09 | 13.7 | 5.5 |

GLM makes 4–7 times more review calls and 13–20 times more validation calls than the GPT models.
The calls are cheap because almost all input is a cache read, but each one adds latency, so GLM is slow in both seats.
For Luna, the Sonnet one-shots are 13% of the bill.

### Which issues each model found

Every serious issue any arm found, plus how often it reached the posted review.

| Issue | GLM @ high | Luna @ low | Sol @ low |
| --- | --- | --- | --- |
| Receiver leg stamps self-driving provenance with no PR-to-run, bot or fork check (cluster 2) | 2/2 posted | 2/2 posted | 2/2 posted |
| Stamphog gate reads only one acting reviewer's toggle (cluster 57) | found 2/2, posted 1/2 | – | found 2/2, posted 1/2 |
| `find_task_run` queries task runs unscoped and checks the team afterwards (cluster 39) | – | found 1/2, posted 1/2 | 2/2 posted |
| Draft and bot gate relaxations keyed only on the self-driving flag (cluster 6) | – | found 1/2, posted 0/2 | 1/2 posted |
| Branch fallback can bind an unrelated or stale run (cluster 73) | – | – | 2/2 posted (judged serious in 1) |
| Carve-out retry path can block the stale-approval dismissal (cluster 29) | 1/2 posted | – | – |
| Toggle looks healthy while Stamphog is disconnected (new) | 1/2 posted | – | – |

Distinct serious issues posted across both runs: GLM 4, Luna 2, Sol 5.
GLM also posted 9 distinct minor issues (mostly doc and comment accuracy, 4 of them not in the August registry). Luna posted 1 (a retry-exhaustion variant of cluster 58). Sol posted 2 (another cluster 58 variant, and cluster 73 in the run where it was judged minor).
Full table: `findings/COMPARE.adjudicated.md`; per-run scorecards: `findings/<SET>.score.adjudicated.md`.

## How "real" was decided

1. **Parse.** Each run's dump became a findings set (`findings/<SET>.json`): GC and GB for GLM, UA and UB for Luna, SA and SB for Sol.
2. **Match.** Two independent matchers per set mapped every finding to the 76-issue registry from July and August, with a tiebreak agent on disagreement (`findings/<SET>.match.json`).
3. **Verify.** Every finding got three refutation-first verifiers against the frozen worktree, with the severity bar of the August protocol. That is 107 findings and 320 verdicts (one verifier of one finding died) (`findings/judge_result_*.json`, `findings/verify_result_*.json`).
4. **Adjudicate.** The fresh verdicts disagreed with August, and with each other, on 14 issues. Those issues decided the ranking, so each got a panel of three adjudicators with different starting angles (form your own view, steelman real, steelman not real). Each adjudicator read the July, August and current evidence and re-checked the code. 40 of the 44 affected findings got a unanimous verdict, and 21 verdicts changed (`findings/adjudication_result.json`, dossiers in `findings/adjudicate/`).

What the panel decided on the big ones:

- **Cluster 2 (receiver provenance hole):** real, `should_fix` for all 8 findings. Earlier verdicts ranged from not real to `must_fix`.
- **Cluster 57 (single acting reviewer):** real, `should_fix` for all 4. August had it 2 real of 11.
- **Cluster 39 (unscoped task-run lookup):** real, `should_fix` for all 3. August had it 1 of 6.
- **Cluster 31 (toggle trusted from queue time):** not real for all 4, agreeing with August's 0 of 6. The fresh panels had called 3 of them real.
- **Cluster 58 (initial review lost on broker failure):** not real for the 8 findings making the fire-and-forget broker claim, and for 1 rate-limit retry variant. Real but minor for 3 findings, each at 2 of 3 votes: two say exhausting the task's retries silently drops the review, and one says exhausted Temporal start retries leave runs queued forever.

### Sensitivity: does the answer depend on the truth rule?

Posted real findings / posted not-real findings per run (per finding, duplicates counted):

| Truth rule | GLM @ high | Luna @ low | Sol @ low |
| --- | --- | --- | --- |
| Fresh 3-skeptic verdicts only | 7.5 / 6.0 | 3.0 / 4.5 | 6.5 / 0.5 |
| August registry verdicts where August had ≥2 | 6.5 / 7.0 | 2.0 / 5.5 | 2.0 / 5.0 |
| **Adjudicated (used above)** | **7.0 / 6.5** | **3.0 / 4.5** | **4.5 / 2.5** |

Cost and speed do not depend on the rule, and GLM is the slowest arm under every rule.
Sol's quality lead does depend on it: large with fresh verdicts, moderate when adjudicated, and gone under August's verdicts.
Luna is the cheapest under every rule. It posts the fewest real findings under the fresh and adjudicated rules, and ties Sol under August's.
All six rules are in `findings/SENSITIVITY.md`.

## Compared with the August experiments

The truth rules differ (August judged clusters 39 and 57 mostly not real), so read these side by side loosely.

| | August | Now |
| --- | --- | --- |
| GLM 5.3 Flash as reviewer | @ max: 7–33% of findings real, none survived the Opus validator, $1.64–1.82 review | @ high: 25–29% real, $1.12–1.15 review + blind-spot. Same band. |
| GLM 5.3 Flash as validator | @ max: 12 of 22 findings got no verdict in one run | @ high: 1 of 71 findings got no verdict. Its own validator drops 73% of its noise but also 26% of its real findings. |
| Sol as reviewer | @ xhigh (prod pin): 19–23 findings, 50–65% real, ~$26 review. @ medium: 14–15 findings, 47–50% real, ~$10.50 | @ low: 9–10 findings, 50–56% real, $4.78–5.66 review + blind-spot |
| Full prod review of this PR | Sol @ xhigh + Opus 5 @ xhigh ≈ $50 per run | Luna Flash ≈ $0.30 per run |

## Incidents

1. **Local gateway rejected the dev API key.** Its scopes were `['*']`, and the gateway does not accept the wildcard for `llm_gateway:read`, so every direct one-shot call returned 401. The first GLM run died at dedup, and the second waited about 14 minutes for the negative auth cache to expire. Fixed by adding `llm_gateway:read` to the key.
2. **No cost data at first.** The slim dev stack had no `capture-ai` service, so gateway `$ai_generation` events went nowhere. Fixed by adding it to the slim stack before any counted run.
3. **Validation sandboxes failed to build.** At 01:35 UTC something deleted the Go sources from `products/desktop/packages/agent-shadow/` in every local Modal build context under the system temp folder. The worker's 300-second image cache then re-hashed the damaged context, and the Dockerfile's `go build` failed with "no Go files". The process that deleted the files was not identified. A worker restart creates fresh contexts. The run was recovered by re-running dedup and validation on the same report, where the model-stamped reviewer cache is reused.
4. **Usage credits ran out mid-judging.** 89 verifier agents in one workflow failed while it still reported completion, and they were re-run. One more verifier failed in another workflow and was not re-run, so finding GB31 rests on two votes (both not real).
5. **One GLM review unit needed a retry** in `glm-high-2`. The Luna and Sol runs had no retries.

## Caveats

- **One PR, two runs per model.** Run-to-run swings are large (GLM posted 1 serious issue in one run and 4 in the other). The planned 100-PR manual test is what confirms the pick.
- **Local timings are inflated.** Concurrency 4 and a local Modal image make all runs slower than prod. The ordering should hold, since GLM is 3–9 times slower per stage.
- **Truth comes from agents.** Contested issues were settled by a three-agent panel, and severities on uncontested issues can still differ between findings of the same issue (cluster 73 is `consider` in one Sol run and `should_fix` in the other).
- **Luna's validator is almost a pass-through.** A stricter validator on Luna's findings is the obvious variant this experiment did not test.

## What switching Flash to Luna takes

`FLASH_ARM` in `products/review_hog/backend/reviewer/constants.py` becomes Codex, `gpt-5.6-luna`, `ReasoningEffort.LOW`, `initial_permission_mode="full-access"`, and its tests follow.
`gpt-5.6-luna` is already allowed in the `review_hog` gateway token pin (`products/tasks/backend/temporal/process_task/ai_gateway_token.py`) and in the Python gateway's `background_agents` allowlist.
The GLM entries added for Flash could then be removed.
Nothing was changed; that decision is open.

## Files

- Runs: `runs/<run>.{md,usage.md,ai_usage.json,log,summary.txt}`; composite GLM run 1: `runs/glm-high-1bc.{md,usage.md}`.
- Findings and truth: `findings/<SET>.{json,match.json,truth.json,truth.adjudicated.json}`.
- Scores: `findings/<SET>.score.md` (fresh), `findings/<SET>.score.adjudicated.md`, `findings/COMPARE.md`, `findings/COMPARE.adjudicated.md`, `findings/SENSITIVITY.md`.
- Scripts: `scripts/{parse_dump,assemble_truth,apply_adjudication,scorecard,compare,sensitivity}.py`.
- Plan, decisions and run log: `PLAN.md`.
