# Pipeline-models experiment — validator swap (C) and Fable-5-low pipeline (D) vs the Sonnet-review control (B)

> **Working scratchpad. Survives compaction — update the Run log + Decisions as we go.**
> Follow-up to `../2026-07-reviewer-model-sonnet5/` (read its FINAL_REPORT.md first). That round flipped the
> REVIEW stage to `claude-sonnet-5 @ xhigh` (now prod). This round tests two follow-on configurations against
> that round's B runs as control (`B-sonnet5-xhigh-{1,2}` = Sonnet review → Opus-default validation, reused —
> identical tree, prompts, review config, pinned chunks):
>
> - **Arm C ×1** (scoped down from 2, user 2026-07-03): Sonnet 5 review → **Sonnet 5 @ xhigh validation** —
>   does the validator also move to Sonnet?
> - **Arm D ×2** (added 2026-07-03): **Fable 5 @ LOW as BOTH reviewer and validator** — the premium-model,
>   minimal-thinking tier. Fable 5 = $10/$50 per M (2× Opus, 5× Sonnet 5 per token), so D bets on token-volume
>   collapse at low effort; the risk is depth (review) and verdict quality (validation) at minimal reasoning.

## What C changes vs B (exactly one stage)

The per-chunk warm validation sessions. New permanent plumbing (keepable regardless of outcome):
`start_sandbox_session` gained the same optional `runtime_adapter/model/reasoning_effort/initial_permission_mode`
kwargs `run_sandbox_review` has (all-None = agent default = pre-knob behavior), and `validate_chunk_activity`
passes new `VALIDATION_*` constants (`reviewer/constants.py`). For the round they're set to
`claude`/`claude-sonnet-5`/`xhigh`. Dedup and chunking stay on the agent default (Opus) in both arms.
**Note the arm C pin changes model AND effort vs the control (opus@high → sonnet-5@xhigh) — user's explicit
choice (2026-07-03): test the intended end-state config, not the single-variable version.**

Chunk structure re-pinned to the same 3-chunk split as the B runs (`EXPERIMENT_PINNED_CHUNKS` re-added,
temporary, DELETE after the round). 12 review units/run as before.

## Config matrix

| label                  | review model      | validation model                | runs | source                                                                                                                                                                                                                                                                |
| ---------------------- | ----------------- | ------------------------------- | ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `B-sonnet5-xhigh-N`    | sonnet-5 @ xhigh  | agent default (opus-4-8 @ high) | 2    | REUSED from ../2026-07-reviewer-model-sonnet5/runs/                                                                                                                                                                                                                   |
| `C-sonnet5val-xhigh-1` | sonnet-5 @ xhigh  | **sonnet-5 @ xhigh (pinned)**   | 1    | this round (scoped 2→1, user)                                                                                                                                                                                                                                         |
| `F-fable5-low-N`       | **fable-5 @ low** | **fable-5 @ low**               | 2    | this round — **relabeled from D (user, 2026-07-03): the D1 attempt silently ran on Opus via SDK fallback (local key lacked fable access) and is VOID; post-key-fix runs are F1/F2.** Fable access smoke-tested end-to-end before F1 (1 gen, real tokens, 0 fallback). |

Same PR `https://github.com/PostHog/posthog/pull/62096` at frozen head `ba725a89` (re-verify pre-flight).
**Known limitation:** e2e runs — each validator judges a different review draw; C at n=1 reads direction
only. D deliberately changes BOTH stages at once — it tests a pipeline tier, not a stage isolation.

### Arm D enablement (the gateway gap)

`claude-fable-5` was already in the tasks registry (low–max) and the agent package, **but absent from BOTH
local llm-gateway allowlists** — sandbox agents authenticate as product `posthog_code` (verified in the
gateway's cost logs), and neither `_POSTHOG_CODE_AGENT_MODELS` nor `background_agents` listed fable-5.
Without the gateway entry the agent's `sanitizedModel` silently falls back to Opus — a fallback run looks
normal. Fix: add `"claude-fable-5"` to both sets in
`services/llm-gateway/src/llm_gateway/products/config.py` (commit-worthy parity — PostHog Code's composer
already offers Fable 5). **The local gateway runs `uvicorn --reload`, so this edit must wait until no run
is in flight** — the reload severs live sandbox streams (A1's validator died exactly that way).
Arm D constants: `REVIEW_MODEL`/`VALIDATION_MODEL = "claude-fable-5"`,
`REVIEW_REASONING_EFFORT`/`VALIDATION_REASONING_EFFORT = LOW`.
**D verification per run:** `$ai_model == claude-fable-5` on review AND validation generations
(opus ≈ dedup-only), naive $ at $10/$50.

## What to measure

**Arm D additionally** gets the full previous-round protocol (funnel, old-10 coverage, new-finding
plausibility, review-stage tokens/turns/wall-clock) — it changes the review stage too, so it reads as a
pipeline tier against BOTH the B control and `../2026-07-reviewer-model-sonnet5/`'s A runs (Opus review).

Validator-focused (C vs B; D's validator observed with the same lens):

1. **Survival rate** dedup→valid (B: 6/11, 6/14) and per-verdict CORRECTNESS — the judge assesses whether
   dismissals/validations were right (B judges already did: e.g. the sound viewer-floor refutation in B1 vs
   the same finding VALIDATED in B2's opus validator — calibration probe cases).
2. **Yardstick kill pattern:** does the sonnet validator uphold #3 (every run ever)? #6/#9-style calls
   (B1 upheld #6, killed #9; B2 killed #2/#7)?
3. **Junk leakage:** validated-junk rate (B: ~0 — all judge-junk was validator-dismissed). A sonnet validator
   that passes junk = published-noise regression, the validator's whole job.
4. **Priority overrides** (downgrades happened in B: #2, #6, 2 status-label findings should_fix→consider).
5. **Cost/time of the validation stage.** In C the per-model token table can't split review vs validation
   (both sonnet-5) — instead compare: opus gens should collapse to dedup-only (B: 44/52 opus gens = dedup +
   validate; C expect ~≤15), and C's sonnet totals grow by the validation share. Validation wall-clock ≈
   time from dedup end to finalize; sessions visible as `[sandbox_prompt:validation-c*]` tasks.

## The run loop (per run) — inherited verbatim from ../2026-07-reviewer-model-sonnet5/PLAN.md

Pre-flight (worker hot-reloaded, ngrok, MODAL_DOCKER, PR head check) → `run_review` (no publish) → dump
(`LABEL=<label> ... OUT_DIR=products/review_hog/eval/experiments/2026-07-pipeline-models/runs`)
→ **no-verdict check before reset** (validator-session deaths; repair = re-run `run_review`, skip-resume
re-attempts only missing verdicts) → model verification (opus-gen collapse + sonnet validation sessions) →
`reset_review_hog --yes`.

## Scoring

Judge each C dump per the established protocol (root-cause vs old-10 + new-finding plausibility,
`judge_results.json` here), PLUS a validator head-to-head vs the B runs on the five metrics above.
Report → `FINAL_REPORT.md` here. **User reviews judge calls at the end.**
Decision rule: sonnet validator adoptable if junk leakage stays ~0, verdict-correctness (judge-assessed) is
not worse, and survival behavior is in the B band (no mass-kill, no rubber-stamp). Cost is secondary (the
validation stage is ~15–20% of run cost).

## Decisions (locked)

- **2026-07-03 (post-report): validator ADOPTED — `VALIDATION_*` flipped to `claude-sonnet-5 @ xhigh`** (user;
  flip-and-watch). Prod pipeline is now all-Sonnet-xhigh for perspectives, blind spots, AND validation; only
  dedup/chunking remain on the agent default.

- Arm C = sonnet-5 @ **xhigh** validation (user, 2026-07-03) — end-state config over single-variable purity.
- **Arm C scoped to 1 run; arm D (fable-5 @ low, both stages) ×2 added (user, 2026-07-03).** D runs after C1
  completes; the gateway allowlist edit + constants flip happen only in the gap (no in-flight runs).
- **Arm D BLOCKED, arm C restored to 2 runs (user, 2026-07-03 ~16:30):** fable-5 is unreachable from the local
  gateway key's Anthropic workspace (data-retention requirement — see the void D row in the run log). User
  chose one more clean C run (C2) over unblocking D; D stays on the books as blocked-environmental.
- **C2 cancelled (user, 2026-07-03 ~17:15) — arm C stays at 1 run.** Two C2 launches were stopped/wiped;
  no C2 dump exists.
- **Fable UNBLOCKED + arm relabeled D→F (user, 2026-07-03 ~17:25):** local gateway key swapped to a
  data-retention-enabled workspace; end-to-end smoke test on the real sandbox path passed (single
  `claude-fable-5` gen, 47.8k in / 20 out, 0 errors, 0 fallback). New runs = `F-fable5-low-{1,2}`.
- Control = reused B runs (no new opus-validator runs).
- Pinned chunks re-added for C, deleted after; `VALIDATION_*` constants + `start_sandbox_session` kwargs are
  permanent plumbing (all-None default = no behavior change) — end-state values decided by this round's outcome.
- The user commits; the agent only edits/stages.
- NO publish on any run.

## Run log

| label               | run | date       | chunks       | units                     | raw→dedup→valid           | validator model verified                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | total tok (in/out)                 | wall-clock                                                                                                                                                      | dump file                 | notes                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------- | --- | ---------- | ------------ | ------------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C-sonnet5val-xhigh  | 1   | 2026-07-03 | 3 (pinned ✓) | 12                        | 18→11→**7**               | ✓ time-window proof: opus (30 gens, 2.96M) confined to the dedup window 15:15–15:25 and stops before the first verdict; validation phase 15:25–15:40 all-sonnet (sonnet total 508 gens, 49.9M/352k)                                                                                                                                                                                                                                                                                           | 49.9M/352k sonnet + 2.96M/27k opus | 2580s (43 min; stages ≈ review 17 / dedup 10 / validation 15 — slow run overall, other workflows shared the worker; tokens are the cost signal, not wall-clock) | `C-sonnet5val-xhigh-1.md` | 0 no-verdict. **7 valid = highest of any run in either round** (B: 6/11, 6/14 → survival 55%/43%; C1: 7/11 = 64%). Sonnet validator slightly more permissive on its face — judge must rule on verdict correctness + junk leakage before reading this as a win.                                                                                                                                                                                 |
| F-fable5-low        | 1   | 2026-07-03 | 3 (pinned ✓) | 12                        | 25→17→7                   | ✓ all-fable: 176 fable gens 15.8M/78k, real tokens, 0 errors; opus = 5 gens (dedup only)                                                                                                                                                                                                                                                                                                                                                                                                      | 15.8M/78k fable + 0.46M/4k opus    | 954s (**15.9 min — fastest full run of both rounds**)                                                                                                           | `F-fable5-low-1.md`       | 0 no-verdict. **Highest raw volume ever (25; prior max 19) and most dedup survivors (17)** in the least time. 7 valid ties C1. Token volume collapsed (~16M vs 20–53M) but fable's $10/M in makes naive $ ≈ $164 — highest of all arms naive; true cost depends on the cache split the local tally can't see. Validator survival 7/17 = 41% (sonnet C1 64%, opus B 55/43%) — volume up, strictness apparently up too; judge must rule on junk. |
| F-fable5-low        | 2   | 2026-07-03 | 3 (pinned ✓) | 12                        | 24→13→**8**               | ✓ all-fable: 170 gens 15.0M/79k real tokens; opus = 1 gen (dedup)                                                                                                                                                                                                                                                                                                                                                                                                                             | 15.0M/79k fable + 0.1M/4k opus     | 903s (15.1 min)                                                                                                                                                 | `F-fable5-low-2.md`       | 0 no-verdict. **8 valid = new all-time high across both rounds; arm F replicates itself** (raw 25/24, valid 7/8, ~15–16 min both runs). Validator survival 8/13 = 62% (vs F1's 41%) — dedup cut more this time.                                                                                                                                                                                                                                |
| D-fable5-low (VOID) | —   | 2026-07-03 | 3 (pinned)   | 12 (all on FALLBACK opus) | n/a — terminated at dedup | **✗ FAILED: every fable-5 call 400'd upstream** — Anthropic `model_not_available`: "your organization or workspace must have data retention enabled" (the LOCAL gateway's ANTHROPIC_API_KEY workspace lacks data retention; prod's has it). The Claude SDK's per-turn `fallbackModel` silently reran every turn on opus-4-8 (25 zero-token fable gens vs 63 real opus gens) — **the funnel looked completely normal; only the mandated `$ai_model` check caught it.** Run terminated + wiped. | —                                  | —                                                                                                                                                               | —                         | Blocker is environmental (Anthropic workspace setting / key), not code. The gateway allowlist fix (fable-5 in `posthog_code` + `background_agents`) was still necessary and stays.                                                                                                                                                                                                                                                             |
