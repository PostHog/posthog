# One-shot chunking + dedup experiment — sandbox-free stages on Sonnet 5 @ xhigh

> **Working scratchpad. Survives compaction — update the Run log + Decisions as we go.**
> Implements `../../POTENTIAL_EXPERIMENTS.md` **item 7 ("Sandbox-free dedup and chunking")** with the
> user's refinements: the one-shot path runs **claude-sonnet-5 @ xhigh** (not agent-default opus) and is
> **size-gated** with the previous sandbox path kept above the gates. Companions: the model rounds at
> `../2026-07-reviewer-model-sonnet5/` and `../2026-07-pipeline-models/` (read their FINAL_REPORTs for the
> yardstick, judge protocol, and the run-loop discipline this round inherits).

## Goal

Chunking and dedup are the only pipeline stages still running as agentic sandboxes on the agent default
(opus-4-8 @ high) — yet both are pure text tasks (dedup renders `CLAUDE_CODE_CONTEXT=""`; chunking's
prompt embeds metadata + comments + patches inline; 14/20 archived dedup calls used zero tools). Each
sandbox pays ~55s provisioning on the serial critical path plus two failure classes (Modal provisioning
flakes; the 29% chunking schema-failure class — bare array instead of the `chunks` object).

Answer: **do one-shot gateway calls (Sonnet 5 @ xhigh, schema-guaranteed via structured outputs) hold
chunk-plan and dedup quality while collapsing stage wall-clock and killing those failure classes?**

## The test PR — #62096 (FROZEN, comparable)

**Review URL (exact, every run): `https://github.com/PostHog/posthog/pull/62096`**
head `ba725a897db35053525e5bdfac2c64a8b007fcb4` (re-verify pre-flight: unchanged, OPEN, 674 add / 1 del /
10 files). 674 adds sits above the 400-add single-chunk gate and under both one-shot gates, so both new
paths exercise live. Yardstick = the old ReviewHog 10 findings
(`../2026-07-reviewer-topology/fixtures/old_reviewhog_report.md`).

## Instruments (all permanent, default-ON in this branch — user commits)

1. **Gates + model pin** (`reviewer/constants.py`): `CHUNKING_ONESHOT_MAX_ADDITIONS = 5000` (additions-only,
   consistent with every other chunking gate), `DEDUP_ONESHOT_MAX_FINDINGS = 50` (issues entering dedup,
   inclusive), `ONESHOT_MODEL = "claude-sonnet-5"`, `ONESHOT_REASONING_EFFORT = "xhigh"`. A gate set to 0
   disables its one-shot path entirely.
2. **`reviewer/sandbox/direct_llm.py` → `run_oneshot_review(...)`**: one Messages call through the LLM
   gateway (`get_async_anthropic_gateway_client(product="review_hog")`), adaptive thinking +
   `output_config.effort=xhigh` (the API-native expression of the sandbox pins), **structured outputs**
   from the stage's pydantic model (schema-guaranteed JSON — the chunking schema-failure class cannot
   occur), `ai_stage` header stamped for dump/cost attribution, Anthropic errors re-raised as compact
   `ApplicationError`s (4xx non-retryable except 408/409/429). Bedrock fallback deliberately off (that
   path strips `output_config`).
3. **Branches**: `split_chunks_activity` (additions ≤ gate → one-shot, else sandbox unchanged) and
   `deduplicate_issues` (issue count ≤ gate → one-shot, else sandbox unchanged). Prompts identical on
   both paths.
4. **Gateway product registration** (permanent parity plumbing): `review_hog` added to
   `posthog/llm/gateway_client.py`'s `Product` literal and
   `services/llm-gateway/src/llm_gateway/products/config.py` (any model, API keys, not billable).
5. **NO chunk pin** — unpinned by design (user, 2026-07-03): the chunk plan is itself a measured output,
   and a pin would short-circuit the one-shot chunking path entirely.

**Deliberate confound (end-state-config style, per prior rounds):** the one-shot arm changes the model
(opus-4-8 @ high agent default → sonnet-5 @ xhigh) AND the execution mode (sandbox → direct call) for
these two stages together. It tests the intended end state, not the single-variable version.

## Config matrix

| label          | what                                                                                             | runs    |
| -------------- | ------------------------------------------------------------------------------------------------ | ------- |
| `ONESHOT-N`    | full e2e run, one-shot chunking + dedup live, unpinned chunks                                    | 2       |
| offline sample | `sample_oneshot_chunker.py` ×5 direct chunker calls on the frozen snapshot (no pipeline, ~cents) | 1 batch |

Baselines (all REUSED, none re-run): `../2026-07-pipeline-models/` **C1** (sonnet review+validation,
dedup/chunking sandbox on opus default, **pinned** 3-chunk split, 18→11→7) is the closest config to
today's prod; `../2026-07-reviewer-model-sonnet5/` **B1/B2** (sonnet review, opus-default validation,
pinned, 17→11→6 / 18→14→6). **Caveat both ways:** baselines were pinned; these runs are unpinned, so the
2-vs-3-chunk coin flip re-enters the funnel. Chunk-plan quality and dedup decisions are the primary
reads; the funnel/valid count is secondary with the structure caveat attached.

## What to measure

1. **Mechanics:** run timeline shows NO `sandbox_prompt:chunking` / `sandbox_prompt:dedup` tasks; the
   chunking/dedup generations appear in the dump's per-model tally as `claude-sonnet-5` with
   `ai_product=review_hog` + `ai_stage` stamps (silent-fallback guard now applies to one-shot calls too).
2. **Chunk-plan quality (primary):** split count + seams vs the archive's distribution (coin flip
   between the 2-chunk backend/frontend split and the good 3-chunk core.py / tool+toolkit / frontend
   split; 17 archived draws) — from the 2 e2e runs plus the 5-sample offline batch; full-coverage
   check (every reviewable file exactly once).
3. **Dedup decisions (primary):** raw→dedup survivor sets vs archived behavior — obvious duplicate
   collapse still happens, no new false merges (spot-check survivors against the raw findings list).
4. **Funnel** raw→dedup→valid vs the C1/B band (secondary, structure caveat).
5. **Stage cost/time:** chunking + dedup stage wall-clock (C1 measured its dedup stage ≈ 10 min incl.
   sandbox provisioning; expect well under 1 min) and per-stage tokens via the `ai_stage` split.
6. **Schema failures:** expect 0 by construction (vs 4/14 archived chunking tasks).
7. **Judge vs old-10** per the established protocol → `judge_results.json`, report → `FINAL_REPORT.md`.

## The run loop (per run) — inherited from ../2026-07-pipeline-models/PLAN.md

1. Pre-flight (below). 2. `RUN_START_EPOCH=$(date +%s)` then
   `flox activate -- bash -c "SANDBOX_PROVIDER=MODAL_DOCKER DJANGO_SETTINGS_MODULE=posthog.settings python manage.py run_review --pr-url https://github.com/PostHog/posthog/pull/62096 --team-id 1 --user-id 1"`
   (NO `--publish`).
2. Dump: `LABEL=ONESHOT-<n> RUN_SECONDS=<s> RUN_START_EPOCH=<epoch> OUT_DIR=products/review_hog/eval/experiments/2026-07-oneshot-chunking-dedup/runs flox activate -- bash -c "DJANGO_SETTINGS_MODULE=posthog.settings python manage.py shell -c \"exec(open('products/review_hog/eval/scripts/dump_result.py').read())\""`
3. **No-verdict check** (BEFORE reset): `grep -c "no-verdict" <dump>`; if any, re-run `run_review`
   (skip-resume re-attempts only missing verdicts), re-dump over the same label.
4. **Model + mechanics verification (MANDATORY):** per-model tally shows review/validation on sonnet-5
   as before AND the chunking/dedup gens NOT on the sandbox path — verify via the `ai_stage`/`ai_product`
   properties (query local `$ai_generation` events) and the absence of chunking/dedup sandbox tasks.
5. After run 1's dump (before reset): run the **offline chunker sample** (`sample_oneshot_chunker.py`,
   usage in its docstring) → `runs/chunker-offline-sample.md`.
6. `flox activate -- bash -c "DJANGO_SETTINGS_MODULE=posthog.settings python manage.py reset_review_hog --yes"` (dump BEFORE reset).

## Pre-flight (every run)

- Worker up + hot-reloaded current code (nodemon watches `products/`; start-time > edit mtime); never
  edit workflow-read constants while a `review-pr` workflow is active.
- ngrok up; `SANDBOX_PROVIDER=MODAL_DOCKER`; flox `DEBUG=True`; PR head re-verified == `ba725a89`.
- **LLM gateway up on :3308 with the `review_hog` product loaded** (uvicorn --reload picks up config
  edits — but a reload severs live streams, so gateway config edits only between runs). Smoke-verified
  2026-07-03: one-shot dedup call end-to-end → `$ai_generation` with model=claude-sonnet-5,
  ai_product=review_hog, ai_stage stamped (593 in / 20 out).
- **Env gotcha (agent-driven shells only):** the PostHog Code desktop harness overrides
  `LLM_GATEWAY_URL` to its own local proxy — prefix manual shell invocations with
  `LLM_GATEWAY_URL=http://localhost:3308`. The Temporal worker (started from a normal terminal) gets
  the correct debug default and is unaffected.
- DB reset from the prior run already done (dump-before-reset discipline).

## Scoring & decision

Judge each dump vs the old-10 (same protocol/prompt as the prior rounds; raw → `judge_results.json`;
user reviews judge calls at the end), plus the stage-focused reads above. **Kill criteria (item 7,
adapted):** dedup survivor sets diverge from archived dedup behavior (false merges or missed obvious
dupes) across the runs; or chunk plans degrade vs the archive's splits (broken coverage, incoherent
seams, systematic single-file shatter). Win ⇒ the default-ON code stands (user commits); kill ⇒ revert =
set the two gates to 0 (sandbox behavior returns byte-identical).

## Decisions (locked)

- **Unpinned e2e ×2 + offline 5-sample chunker batch** (user, 2026-07-03) — chunk-plan quality judged
  directly; funnel read carries the structure caveat.
- **Gate metric = additions only** (user, 2026-07-03) — consistent with `SINGLE_CHUNK_GATE_ADDITIONS` /
  `CHUNK_TARGET_ADDITIONS` convention.
- **`review_hog` registered as a gateway product** (user, 2026-07-03) — permanent parity plumbing.
- **Permanent code, default ON at 5000/50** (user, 2026-07-03) — flip-and-watch style; revert = two
  constants.
- **The user commits everything; the agent only edits files** (standing since the sonnet-5 round).
- NO publish on any run. Results dir: `runs/` next to this file.
- **Chunker-shatter fix = prompt adjustment, DEFERRED (user, 2026-07-03 — "not now").** Not applied in this
  round; the round reports the untuned behavior. When picked up: an explicit size floor + a chunk-count
  sanity formula (sonnet-5 weights concern-separation over the "fewest chunks / ~300-add aim" vibes), shared
  prompt so both paths stay in parity, validated cheaply with `sample_oneshot_chunker.py` before any run.
- **2026-07-04 (post-round): prompt fix APPLIED** (user go-ahead after the live-PR run) — ~100-add floor +
  count-formula ceiling added to `prompts/chunking/prompt.jinja` sizing rules. **VALIDATED 2026-07-06:**
  5/5 draws vs the #62096 fixtures (`sample_oneshot_chunker_fixture.py`, fully local) = 2 chunks each,
  full coverage, zero sub-100-add fragments — the untuned 4,4,4,3,3 shatter is gone. Chunking half now
  clear to adopt alongside dedup.
- **2026-07-04 (post-round, separate prod change on this branch):** `VALIDATION_MODEL` reverted
  `claude-sonnet-5` → `claude-opus-4-8` (effort stays XHIGH) per the user's watch of the sonnet validator's
  volume-permissiveness (constants test green). Unrelated to the one-shot change; recorded here because it
  shares the branch.
- **JUDGING DONE 2026-07-04 → `judge_results.json` + `FINAL_REPORT.md`.** Headlines: old-coverage 4 valid
  (O1, incl. #5 third-ever surface + #6 third-ever VALID) / 2 valid (O2) vs the B pair's 3/1; validated-junk
  0 in both runs; dedup decisions in-band; recommendation = adopt dedup now, chunking after the tuned-prompt
  batch (or gate 0 meanwhile). Two judge-agent attempts died to harness infra (an interrupt cascade, then
  gateway 502s) before the third succeeded.

## Run log

| label           | run | date       | chunks            | units | raw→dedup→valid | one-shot verified (chunking/dedup)                                                                                                                                                                            | chunking+dedup stage time                                                                                                                                                        | total tok (in/out)                                                           | wall-clock                                                                             | dump file                   | notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| --------------- | --- | ---------- | ----------------- | ----- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ONESHOT         | 1   | 2026-07-03 | 2 (unpinned draw) | 8     | 13→11→**10**    | ✓ chunking: 2 `review_hog/chunking` sonnet-5 gens (attempt 1 discarded by a mid-flight worker restart, retry landed 21:10:22) · ✓ dedup: 1 `review_hog/dedup` gen 21:31:36 · no chunking/dedup sandbox tasks  | chunking 47s/attempt (+5.5 min heartbeat-timeout stall from the user's worker restart — infra, not the path) · combine→clean→dedup→persist ≈ **38s** (C1's dedup stage ≈ 10 min) | 33.9M/230k sonnet-5 + 2.9M/23k opus (opus = local cron noise, no `ai_stage`) | 2374s incl. the restart stall (effective ≈ 34 min; validation of 11 findings ≈ 11 min) | `ONESHOT-1.md`              | 0 no-verdict. **valid 10 = highest of any run in any round; validator survival 10/11 = 91% (band was 43–64%) — judge must rule on junk before reading as a win.** 2-chunk draw = archive's modal split, full coverage.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ONESHOT         | 2   | 2026-07-03 | 3 (unpinned draw) | 12    | 18→14→**9**     | ✓ chunking: 1 `review_hog/chunking` gen 21:49:31 (52.4k in / 3.7k out) · ✓ dedup: 1 `review_hog/dedup` gen 22:04:50 (50.2k in / 4.7k out) · no chunking/dedup sandbox tasks; **zero opus gens in the window** | fetch→chunk_set **36s** · one-shot stages combined ≈ $0.29 naive                                                                                                                 | 53.1M/352k sonnet-5 (all-sonnet run)                                         | 1626s (27.1 min, clean — no restarts)                                                  | `ONESHOT-2.md`              | 0 no-verdict. 3-chunk draw — in-pipeline draws (2, 3) both inside the sandbox archive's range; the 4-draws stayed offline-only. Survival 9/14 = 64% (back in the C1 band after run 1's 91%).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| chunker-offline | —   | 2026-07-03 | 4,4,4,3,3         | —     | —               | ✓ 5× `chunking-offline-sample` one-shot calls, ~47–90s each                                                                                                                                                   | —                                                                                                                                                                                | ~5 gens, pennies                                                             | —                                                                                      | `chunker-offline-sample.md` | **One-shot chunker skews to MORE, smaller chunks than the sandbox archive** (draws 4/4/4/3/3 vs sandbox 2–3; fragments down to 16 adds vs the no-fragments prompt rule). Coverage complete in all 5. In-run draw was 2 — n=6 total spread 2,3,3,4,4,4. **User verdict (2026-07-03): 4 chunks is unambiguously too many for ~497 reviewable adds at the ~300-add target — this hits the "chunk plans degrade" kill criterion for the CHUNKING half** (units = chunks × 4, so a 4-draw doubles review-stage cost vs a 2-draw). Post-round options if the read holds: (a) deterministic plan guard in the one-shot path (reject plans with chunks ≪ target or count > ceil(adds/target)+1, retry once / fall back to sandbox), (b) prompt nudge, (c) adopt one-shot DEDUP only and set `CHUNKING_ONESHOT_MAX_ADDITIONS = 0` (sandbox chunking returns byte-identically). |
