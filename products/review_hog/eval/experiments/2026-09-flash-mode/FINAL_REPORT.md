# FINAL REPORT — which model should ReviewHog Flash use

**Date:** 2026-09-17. Original six runs ended at 04:00 UTC; four Luna effort follow-up runs ran from 18:47 to 20:29 UTC.
**Question:** which model, used as both reviewer and validator, gives Flash mode the cheapest and fastest review with good-enough quality?
**Arms:** GLM 5.3 Flash @ high, GPT 5.6 Luna @ low / medium / xhigh, GPT 5.6 Sol @ low. Two runs each.

## TL;DR

**Use GPT 5.6 Luna @ medium as the budget Flash choice; use xhigh when coverage justifies a slower, more expensive review.**
Medium posts three distinct serious issues per run for $0.59, compared with 1.5 for $0.30 at low.
That extra $0.29 buys twice the serious-issue coverage at roughly the same $0.20 per serious issue.
Its false-comment share falls only from 60% to 53%, and it posts five false comments instead of 4.5.
Medium does not solve permissive validation.

Xhigh posts eight distinct serious issues per run with 33% false comments for $3.32 and about 36 minutes.
It offers much stronger coverage and a lower noise share, but costs 11.1 times as much as low and posts more false comments in absolute terms: 6.5 per review.
Under the adjudicated truth, it is a better coverage fallback than Sol low ($7.01, 3.5 serious issues, 36% false), with more comments and longer waits.
Sol remains quieter under the fresh verifier truth, so this is not a quality ranking that holds under every judging rule.

These are two runs per arm on one PR.
The follow-up ran on a different local stack, so its 10.5-minute medium mean does not establish that extra reasoning makes reviews faster.
The original six-run recommendation was Luna low; the completed [effort follow-up](#luna-reasoning-effort-follow-up) changes the budget recommendation to medium.

## Setup

Same clean room as the August experiments:
frozen PR 75215 at `a7fb363b`, 4 pinned chunks, PR comments mocked to none, `MAX_CONCURRENT_SANDBOXES = 4`, DB-only (no publish), local stack with Modal sandboxes.
Flash mode as committed in `810ab275ccb`: the same model in both sandbox seats, skill bodies inlined into the prompts, Sonnet one-shots for selection and dedup.
Costs are the gateway's own `$ai_generation` figures, read from the local Kafka AI topic per run (`runs/<run>.usage.md`).

## Original six-run results

Numbers use the adjudicated truth (see [How "real" was decided](#how-real-was-decided)).
"Serious" means `should_fix` or worse; no finding in the original six runs ended up `must_fix` under adjudicated truth.
Issue counts are distinct issues, so a run that posts the same issue three times counts it once.

### Per model (mean of two runs)

| Model                |  Cost | Minutes | Comments posted | Serious issues posted | Minor issues posted | Posted but not real | Share not real | Cost per serious issue posted |
| -------------------- | ----: | ------: | --------------: | --------------------: | ------------------: | ------------------: | -------------: | ----------------------------: |
| GLM 5.3 Flash @ high | $2.49 |     ~77 |            13.5 |                   2.5 |                 4.5 |                 6.5 |            48% |                         $0.99 |
| GPT 5.6 Luna @ low   | $0.30 |      15 |             7.5 |                   1.5 |                 0.5 |                 4.5 |            60% |                         $0.20 |
| GPT 5.6 Sol @ low    | $7.01 |      21 |               7 |                   3.5 |                   1 |                 2.5 |            36% |                         $2.00 |

### Per run

| Run              | Model      | Minutes |  Cost | Raw → deduped → posted | Serious posted | Minor posted | Duplicates posted | Not real posted | Validator kept real | Validator dropped not-real |
| ---------------- | ---------- | ------: | ----: | ---------------------- | -------------: | -----------: | ----------------: | --------------: | ------------------- | -------------------------- |
| `glm-high-1bc` ¹ | GLM @ high |      83 | $2.56 | 46 → 36 → 13           |              1 |            4 |                 0 |               8 | 5/9                 | 18/27 ³                    |
| `glm-high-2` ²   | GLM @ high |      71 | $2.41 | 55 → 35 → 14           |              4 |            5 |                 0 |               5 | 9/10                | 20/25                      |
| `luna-low-1`     | Luna @ low |      14 | $0.30 | 9 → 9 → 8              |              2 |            1 |                 0 |               5 | 3/4                 | 0/5                        |
| `luna-low-2`     | Luna @ low |      16 | $0.30 | 8 → 8 → 7              |              1 |            0 |                 2 |               4 | 3/3                 | 1/5                        |
| `sol-low-1`      | Sol @ low  |      20 | $6.58 | 11 → 9 → 7             |              3 |            2 |                 0 |               2 | 5/5                 | 2/4                        |
| `sol-low-2`      | Sol @ low  |      22 | $7.43 | 14 → 10 → 7            |              4 |            0 |                 0 |               3 | 4/5                 | 2/5                        |

¹ Composite. The first attempt died at dedup (local gateway auth bug). The re-run's reviewer side finished, but its validation sandboxes failed to build (see [Incidents](#incidents)). A validation-only re-run on the same report reused the cached GLM reviews, produced the identical 36 deduped findings, and validated them. Minutes = re-run review stage + validation-only run.
² Includes about 14 minutes of dedup retries caused by the same local auth bug, so the clean time is nearer 57 minutes.
³ One more not-real finding (GC19) got no verdict at all; it was not posted, but it is not counted as dropped.

Validator totals across both runs:

| Model      | Real findings kept | Not-real findings dropped | Findings with no verdict |
| ---------- | ------------------ | ------------------------- | -----------------------: |
| GLM @ high | 14/19 (74%)        | 38/52 (73%)               |                        1 |
| Luna @ low | 6/7 (86%)          | 1/10 (10%)                |                        0 |
| Sol @ low  | 9/10 (90%)         | 4/9 (44%)                 |                        0 |

### Where the money and time go

| Run            |            Review |  Blind-spot |  Validation | Selection + dedup (Sonnet) | Review + blind-spot min | Validation min |
| -------------- | ----------------: | ----------: | ----------: | -------------------------: | ----------------------: | -------------: |
| `glm-high-1bc` | $0.69 (223 calls) | $0.46 (130) | $1.26 (433) |                      $0.15 |                    45.5 |           34.6 |
| `glm-high-2`   |       $0.78 (289) |  $0.34 (96) | $0.99 (459) |                      $0.30 |                    36.9 |           18.9 |
| `luna-low-1`   |        $0.14 (42) |  $0.06 (18) |  $0.06 (28) |                      $0.04 |                     8.7 |            3.8 |
| `luna-low-2`   |        $0.15 (43) |  $0.06 (17) |  $0.06 (23) |                      $0.03 |                    10.7 |            3.7 |
| `sol-low-1`    |        $3.31 (44) |  $1.47 (19) |  $1.70 (31) |                      $0.11 |                    11.3 |            5.6 |
| `sol-low-2`    |        $3.98 (57) |  $1.68 (25) |  $1.68 (33) |                      $0.09 |                    13.7 |            5.5 |

Costs sum raw gateway events before rounding; displayed stage amounts can differ from the rounded total when added.

In the original six runs, GLM makes 4–7 times more review calls and 13–20 times more validation calls than the GPT models.
The calls are cheap because almost all input is a cache read, but each one adds latency, so GLM is slow in both seats.
For Luna low, the Sonnet one-shots are 12% of the bill.

### Which issues each model found

Every serious issue the original six runs found, plus how often it reached the posted review.

| Issue                                                                                        | GLM @ high            | Luna @ low            | Sol @ low                        |
| -------------------------------------------------------------------------------------------- | --------------------- | --------------------- | -------------------------------- |
| Receiver leg stamps self-driving provenance with no PR-to-run, bot or fork check (cluster 2) | 2/2 posted            | 2/2 posted            | 2/2 posted                       |
| Stamphog gate reads only one acting reviewer's toggle (cluster 57)                           | found 2/2, posted 1/2 | –                     | found 2/2, posted 1/2            |
| `find_task_run` queries task runs unscoped and checks the team afterwards (cluster 39)       | –                     | found 1/2, posted 1/2 | 2/2 posted                       |
| Draft and bot gate relaxations keyed only on the self-driving flag (cluster 6)               | –                     | found 1/2, posted 0/2 | 1/2 posted                       |
| Branch fallback can bind an unrelated or stale run (cluster 73)                              | –                     | –                     | 2/2 posted (judged serious in 1) |
| Carve-out retry path can block the stale-approval dismissal (cluster 29)                     | 1/2 posted            | –                     | –                                |
| Toggle looks healthy while Stamphog is disconnected (new)                                    | 1/2 posted            | –                     | –                                |

Distinct serious issues posted across both runs: GLM 4, Luna 2, Sol 5.
GLM also posted 9 distinct minor issues (mostly doc and comment accuracy, 4 of them not in the August registry). Luna posted 1 (a retry-exhaustion variant of cluster 58). Sol posted 2 (another cluster 58 variant, and cluster 73 in the run where it was judged minor).
Full table: `findings/COMPARE.adjudicated.md`; per-run scorecards: `findings/<SET>.score.adjudicated.md`.

## How "real" was decided

The original six runs used this process; the follow-up below extends it with the same truth rules.

1. **Parse.** Each run's dump became a findings set (`findings/<SET>.json`): GC and GB for GLM, UA and UB for Luna low, SA and SB for Sol.
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

For the original six runs, posted real findings / posted not-real findings per run (per finding, duplicates counted):

| Truth rule                                   | GLM @ high    | Luna @ low    | Sol @ low     |
| -------------------------------------------- | ------------- | ------------- | ------------- |
| Fresh 3-skeptic verdicts only                | 7.5 / 6.0     | 3.0 / 4.5     | 6.5 / 0.5     |
| August registry verdicts where August had ≥2 | 6.5 / 7.0     | 2.0 / 5.5     | 2.0 / 5.0     |
| **Adjudicated (used above)**                 | **7.0 / 6.5** | **3.0 / 4.5** | **4.5 / 2.5** |

Cost and speed do not depend on the rule, and GLM is the slowest arm under every rule.
Sol's quality lead does depend on it: large with fresh verdicts, moderate when adjudicated, and gone under August's verdicts.
Luna is the cheapest under every rule. It posts the fewest real findings under the fresh and adjudicated rules, and ties Sol under August's.
All six rules are in `findings/SENSITIVITY.md`.

## Luna reasoning-effort follow-up

The four additional runs use Luna at `medium` or `xhigh` in review, blind-spot sweep, and validation.
All four completed on the frozen head `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82`, with four pinned chunks covering 22 files, empty PR comments, sandbox concurrency four, Flash prompts, and Sonnet selection/dedup.
Publishing remained disabled.
The usage artifacts confirm the actual model and effort in every stage; the dump's stored configuration snapshot does not identify the runtime arm.

### Mean of two runs per arm

| Arm           |  Cost | Minutes | Comments posted | Distinct serious issues posted | Minor issues posted | Posted but not real | Share not real | Validator precision | Validator recall |
| ------------- | ----: | ------: | --------------: | -----------------------------: | ------------------: | ------------------: | -------------: | ------------------: | ---------------: |
| GLM @ high    | $2.49 |    77.2 |            13.5 |                            2.5 |                 4.5 |                 6.5 |            48% |         14/27 (52%) |      14/19 (74%) |
| Luna @ low    | $0.30 |    15.0 |             7.5 |                            1.5 |                 0.5 |                 4.5 |            60% |          6/15 (40%) |        6/7 (86%) |
| Luna @ medium | $0.59 |    10.5 |             9.5 |                              3 |                 0.5 |                   5 |            53% |          9/19 (47%) |       9/9 (100%) |
| Luna @ xhigh  | $3.32 |    36.2 |            19.5 |                              8 |                 1.5 |                 6.5 |            33% |         26/39 (67%) |      26/27 (96%) |
| Sol @ low     | $7.01 |    20.8 |               7 |                            3.5 |                   1 |                 2.5 |            36% |          9/14 (64%) |       9/10 (90%) |

Rates pool both runs' counts; costs, times, and issue counts are arithmetic means.
Precision is real kept findings divided by all kept findings; recall is real kept findings divided by all real candidates after deduplication.
Real duplicate comments count in those rates, but only once in distinct serious/minor issue counts.
Medium posts one extra real duplicate per run; xhigh posts 3.5.
Together, distinct serious issues, distinct minor issues, extra real duplicates, and false comments sum to total comments.
Costs are captured generation costs, with the rejected-request accounting described below; they exclude sandbox infrastructure, judging, smoke checks, and aborted attempts.

### Per-run results

| Run                  |  Cost | Minutes | Raw → deduped → posted | Distinct serious posted | Minor posted | Extra real duplicates | Not-real posted | Validator precision | Validator recall |
| -------------------- | ----: | ------: | ---------------------- | ----------------------: | -----------: | --------------------: | --------------: | ------------------: | ---------------: |
| `luna-medium-1` (MA) | $0.54 |     9.2 | 14 → 11 → 9            |                       3 |            0 |                     1 |               5 |           4/9 (44%) |       4/4 (100%) |
| `luna-medium-2` (MB) | $0.64 |    11.8 | 15 → 11 → 10           |                       3 |            1 |                     1 |               5 |          5/10 (50%) |       5/5 (100%) |
| `luna-xhigh-1` (XA)  | $3.49 |    36.0 | 32 → 22 → 20           |                       8 |            2 |                     3 |               7 |         13/20 (65%) |     13/13 (100%) |
| `luna-xhigh-2` (XB)  | $3.15 |    36.4 | 27 → 22 → 19           |                       8 |            1 |                     4 |               6 |         13/19 (68%) |      13/14 (93%) |

### Reviewer coverage improves more than validator strictness

Medium posts the receiver-provenance defect (cluster 2) and the bot/draft gate defect (cluster 6) in both runs.
MA also posts the unscoped task-run lookup (cluster 39); MB posts the single-reviewer toggle defect (cluster 57).
Each run therefore posts three serious issues, with four distinct serious issues across the two runs.
The cost rises by $0.29 per review, or 1.98 times low, while cost per serious issue remains about $0.20.

Xhigh posts eight distinct serious issues in each run, 5.33 times low's yield.
Its findings include additional claims about bypassing a repository's disabled setting and the initial receiver's internal-task guard, both repeated across the two runs.
Its noise share falls by 27 percentage points relative to low, but the larger review still contains 6.5 false comments on average.
At $0.42 per serious issue, xhigh costs about twice as much per serious issue as low or medium.

| Reviewer/validator measure               |   Luna low | Luna medium |  Luna xhigh |
| ---------------------------------------- | ---------: | ----------: | ----------: |
| Real candidates after deduplication      | 7/17 (41%) |  9/22 (41%) | 27/44 (61%) |
| Distinct serious issues proposed per run |          2 |           3 |         8.5 |
| Not-real candidates rejected             | 1/10 (10%) |  3/13 (23%) |  4/17 (24%) |
| Real candidates retained                 |  6/7 (86%) |  9/9 (100%) | 26/27 (96%) |

Medium's reviewer produces more serious issues without improving its real-finding share.
Xhigh improves both coverage and the share of real candidates.
Both higher efforts reject roughly a quarter of false candidates, so neither becomes a strict validator.
Because both seats change together and see different candidate sets, this experiment does not isolate validator effort as the cause of those differences.

### Cost and latency

| Mean cost per stage      | Luna medium |  Luna xhigh |
| ------------------------ | ----------: | ----------: |
| Review                   | $0.27077512 | $1.48508901 |
| Blind-spot sweep         | $0.10041563 | $0.50602124 |
| Validation               | $0.12742532 | $1.09115328 |
| Sonnet selection + dedup | $0.09201200 | $0.23790900 |
| Total                    | $0.59062807 | $3.32017253 |

Xhigh costs 11.1 times low and 5.6 times medium.
Its 36.2-minute mean is 3.4 times medium on the same follow-up stack.
Against Sol low, xhigh costs less than half as much and posts more serious issues under adjudicated truth, but takes longer and posts 19.5 comments instead of seven.
Sol's 2.5 false comments per review are also fewer than xhigh's 6.5.

A token-price audit fits every priced Luna event across low, medium, and xhigh to the same observed base rates: $0.20 per million uncached input tokens, $0.02 cached input, and $1.20 output including reasoning.
Forty-nine xhigh calls use a higher context tier with observed rates of $0.40, $0.04, and $1.80 respectively.
That tier adds $0.32536628 to the mean xhigh review, about 9.8% of its cost.
Even pricing those calls at the base rates would leave xhigh at $2.99, about ten times low.
This is an inference from captured tokens and costs, not a claim about current public model prices or an exact context threshold.

### Cost capture and rejected requests

The four measured runs contain 1,381 captured requests: 1,372 priced generations and nine rejected requests, all in XB validation.
The priced generations total $7.82160120.
Independent Kafka reads match the saved run events, with no unpriced successful generation.

XB contains 546 captured requests: 537 priced generations totaling $3.15126478 and nine error events with no captured usage or cost fields and the captured `litellm.NotFoundError` prefix.
The usage collector preserves their costs as null and represents the omitted token counters as zero.
The original driver's strict cost check rejected the run because it rejected every null cost.
The installed LiteLLM 1.92.0 HTTP and exception paths classify these as HTTP 404 failures before the response stream starts; the gateway failure callback emits no usage or cost for that path.
This source-based classification is recorded per event in [the request-error ledger](runs/luna-xhigh-2.request_errors.json).
Request-level HTTP logs were unavailable, and no provider invoice was checked.

The raw null costs remain intact.
They are not converted to zero-dollar generations, and the reported dollar total is the sum of priced generations, not an independently verified provider bill.
All 546 requests and the full elapsed time remain in the run, including the rejected attempts.
The scorer accepts only these hash-bound, explicitly audited error records and still rejects unknown missing prices.
The failed driver check remains in the local log; acceptance follows the separate accounting audit.

### Judging, carryovers, and duplicate accounting

MA/MB/XA/XB contain 66 deduplicated findings, each with three independent refutation-first votes against the frozen worktree: 198 votes, with no gaps.
All 66 also have a validator verdict.
Two matchers per set and a third matcher for disagreements establish registry identity.
XA and XB judging began from claims-only snapshots during validation; every claim field was checked for exact equality with the final parsed dumps before scoring.

The original panel's verdict transfers through 31 explicit, independently checked sub-claim matches: five MA, seven MB, eight XA, and eleven XB.
Fresh/panel disagreements remain visible in the truth artifacts:

- The fresh judges accept the broker-publication claims MA8, MB4, MB9, XA5, and XB5, and the queue-time-toggle claims XA10, XB2, and XB13; the original panel rejects those claims.
- The fresh judges reject MB2 and XB19's single-reviewer-toggle claim; the panel retains it. XB's validator also rejects XB19, producing its one real-finding miss under adjudicated truth.
- Several fresh `must_fix` verdicts become the panel's `should_fix` for receiver provenance and bot/draft gating. MB10's retry-exhaustion claim and XA18's stranded-QUEUED claim take the panel's `consider` verdict.
- XB7 contains both the rejected broker-publication claim and a separate process-exit window after the task-run commit but before callback publication. All three fresh votes retain the process-exit claim. Its adjudicated record preserves the panel's false broker verdict and separately retains that uncovered `should_fix` sub-claim; it does not extend the panel to a claim it did not judge.

XA3 and XA15 retain the same minor replica-lag readiness defect in all six fresh votes.
An explicit finding-specific group counts one minor issue and one extra real duplicate, while preserving both original matches and truth records.
The comparable XB6 finding occurs only once in XB, so it needs no within-run override.
The initial receiver guard is kept distinct from cluster 1's webhook lookup path.
Uncontested severity can still vary: XA17's cluster-36 claim is `should_fix`, while the earlier GC12 finding was `consider`.

### Sensitivity to the truth rule

These cells are mean posted real findings / posted false findings, including real duplicates; they are not distinct serious-issue counts.

| Truth rule                                                | Luna low | Luna medium | Luna xhigh |   Sol low |
| --------------------------------------------------------- | -------: | ----------: | ---------: | --------: |
| Fresh votes per finding                                   |  3 / 4.5 |     5.5 / 4 |   15.5 / 4 | 6.5 / 0.5 |
| Pooled fresh votes per registry cluster                   |  4.5 / 3 |     5.5 / 4 |   15 / 4.5 | 6.5 / 0.5 |
| August verdicts where at least two votes settle the issue |  2 / 5.5 |     2 / 7.5 |   9.5 / 10 |     2 / 5 |
| Adjudicated, used for the recommendation                  |  3 / 4.5 |     4.5 / 5 |   13 / 6.5 | 4.5 / 2.5 |

Medium's real-finding advantage over low disappears under the August rule, and it then posts more false comments.
Xhigh posts more real findings under all four rules, but Sol is quieter under fresh verdicts: 7% false comments against xhigh's 21%.
The pooled rule includes the new runs' votes, so it can change the baseline arms' scores too.
The serious-only modes in [SENSITIVITY.md](findings/SENSITIVITY.md) treat minor findings as outside their target; their non-serious share must not be read as a false-comment share.

### Comparability and recommendation

The handoff names runtime commit `4cf3e5471286cbac0a0960b9966aa0c55e92b7f5`; the available follow-up stack ran `c0e58940541edeb01ec55e410338750a6368308c` after a master merge.
The `products/review_hog` tree is identical between those commits before the temporary harness edits.
Shared runtime code differs, including the Temporal executor and task-status path; the gateway's analytics dependency changes from 7.54.0 to 7.54.1, while both commits pin LiteLLM 1.92.0.
Observed base token prices match, but the baseline installed environment and live price map were not archived.
The reviewed source and review configuration are frozen; machine and shared-runtime differences limit causal claims, especially about elapsed time.

An earlier medium attempt was aborted after backend autoreload interrupted sandbox callbacks.
Its 68 captured generations cost $0.26832528 and are retained as `luna-medium-1-aborted` cost artifacts, excluded from all arm means.
Backend reload was disabled for the four measured runs.
The large xhigh payloads also exceeded the live monitor's initial read deadline; a longer read and an independent full-window Kafka audit recovered all events.

**Medium is worth the extra $0.29 for this budget Flash use case:** twice the serious issues, similar cost per serious issue, and a modestly lower noise share.
It is a coverage upgrade, with a validator that still passes most junk.
**Xhigh is worth considering when eight serious issues rather than 1.5 justifies $3.32 and 36 minutes:** it is the strongest coverage option here, but its cost no longer stays near Luna low.
Use medium as the budget default and xhigh as the coverage option, then check both on the planned broader PR sample before treating this one-PR result as general.

## Original six runs compared with August

The truth rules differ (August judged clusters 39 and 57 mostly not real), so read these side by side loosely.

|                             | August                                                                                                       | Now                                                                                                                  |
| --------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| GLM 5.3 Flash as reviewer   | @ max: 7–33% of findings real, none survived the Opus validator, $1.64–1.82 review                           | @ high: 25–29% real, $1.12–1.15 review + blind-spot. Same band.                                                      |
| GLM 5.3 Flash as validator  | @ max: 12 of 22 findings got no verdict in one run                                                           | @ high: 1 of 71 findings got no verdict. Its own validator drops 73% of its noise but also 26% of its real findings. |
| Sol as reviewer             | @ xhigh (prod pin): 19–23 findings, 50–65% real, ~$26 review. @ medium: 14–15 findings, 47–50% real, ~$10.50 | @ low: 9–10 findings, 50–56% real, $4.78–5.67 review + blind-spot                                                    |
| Full prod review of this PR | Sol @ xhigh + Opus 5 @ xhigh ≈ $50 per run                                                                   | Luna Flash ≈ $0.30 per run                                                                                           |

## Incidents

1. **Local gateway rejected the dev API key.** Its scopes were `['*']`, and the gateway does not accept the wildcard for `llm_gateway:read`, so every direct one-shot call returned 401. The first GLM run died at dedup, and the second waited about 14 minutes for the negative auth cache to expire. Fixed by adding `llm_gateway:read` to the key.
2. **No cost data at first.** The slim dev stack had no `capture-ai` service, so gateway `$ai_generation` events went nowhere. Fixed by adding it to the slim stack before any counted run.
3. **Validation sandboxes failed to build.** At 01:35 UTC something deleted the Go sources from `products/desktop/packages/agent-shadow/` in every local Modal build context under the system temp folder. The worker's 300-second image cache then re-hashed the damaged context, and the Dockerfile's `go build` failed with "no Go files". The process that deleted the files was not identified. A worker restart creates fresh contexts. The run was recovered by re-running dedup and validation on the same report, where the model-stamped reviewer cache is reused.
4. **Usage credits ran out mid-judging.** 89 verifier agents in one workflow failed while it still reported completion, and they were re-run. One more verifier failed in another workflow and was not re-run, so finding GB31 rests on two votes (both not real).
5. **One GLM review unit needed a retry** in `glm-high-2`. The original Luna low and Sol runs had no retries.

## Caveats

- **One PR, two runs per model.** Run-to-run swings are large (GLM posted 1 serious issue in one run and 4 in the other). The planned 100-PR manual test is what confirms the pick.
- **Local timings are inflated.** Concurrency 4 and a local Modal image make these measurements unsuitable as production latency estimates. The follow-up also ran on a different machine and shared runtime; compare its timings with the original six cautiously.
- **Truth comes from agents.** Contested issues were settled by a three-agent panel, and severities on uncontested issues can still differ between findings of the same issue (cluster 73 is `consider` in one Sol run and `should_fix` in the other).
- **Luna's validator is almost a pass-through.** A stricter validator on Luna's findings is the obvious variant this experiment did not test.

## What switching Flash to Luna takes

For the updated budget recommendation, `FLASH_ARM` in `products/review_hog/backend/reviewer/constants.py` becomes Codex, `gpt-5.6-luna`, `ReasoningEffort.MEDIUM`, `initial_permission_mode="full-access"`, and its tests follow.
`gpt-5.6-luna` is already allowed in the `review_hog` gateway token pin (`products/tasks/backend/temporal/process_task/ai_gateway_token.py`) and in the Python gateway's `background_agents` allowlist.
The GLM entries added for Flash could then be removed.
The experiment does not change the production arm; applying the recommendation is a separate change.

## Files

- Runs: `runs/<run>.{md,usage.md,ai_usage.json}` and start/end epochs; composite GLM run 1: `runs/glm-high-1bc.{md,usage.md}`. Follow-up operational logs remain local.
- Findings and truth: `findings/<SET>.{json,match.json,truth.json,truth.adjudicated.json}`.
- Scores: `findings/<SET>.score.md` (fresh), `findings/<SET>.score.adjudicated.md`, `findings/COMPARE.md`, `findings/COMPARE.adjudicated.md`, `findings/SENSITIVITY.md`.
- Scripts: `scripts/{parse_dump,assemble_truth,apply_adjudication,scorecard,compare,sensitivity,usage_costs}.py`.
- Follow-up audit inputs: `findings/luna_effort_adjudication_carryovers.json`, `findings/duplicate_groups.json`, and `runs/luna-xhigh-2.request_errors.json`.
- Plan, decisions and run log: `PLAN.md`.
