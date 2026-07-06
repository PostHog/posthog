# Gate 0 — cache-aware metrology + gateway cache probe + fork sizing (run-ready plan, 2026-07-06)

> This is the FIRST round of the prompt-caching program and the only round greenlit so far (decision locked with the user 2026-07-06).
> It is prepared for a fresh agent to execute in isolation: read `INVESTIGATION.md`, `CANDIDATES.md`, and `HARNESS.md`
> (same folder, in that order) first — this plan assumes their context and does not repeat it. HARNESS.md carries the
> PROVEN two-repo loop (local agent build -> sandbox overlay -> agentVersion fingerprint) and the 2026-07-06 smoke-run
> findings that revise this plan's baselines. Candidates referenced as #N below are CANDIDATES.md numbering
> (#1 `cache-aware-metrology`, #2 `gateway-cache-probe`, #3 `fork-sizing-spikes`).
> **User veto 2026-07-06 (see CANDIDATES.md locked constraints): one-shot LLM calls for code investigation are out of scope;
> every review unit stays a full sandbox agent. The warm-up+fork family (#8) is the flagship, which promotes #3 into this round.**
> Later rounds (skill splice, pre-pack, the warm-up+fork ladder) get their own PLAN when greenlit — do NOT start them from here.

## Status after session 1 (2026-07-06 — user scope-narrowed it to "one PR review + fix the spend calculation"; START HERE next session)

Branch `signals/reviewhog-exp-caching-gate0`, commits `1ed24313ca0` + doc sync; details in the run log at the bottom.

- **Part 1 instrument: DONE, validated live.** `dump_result.py` emits the cache-aware split, `true_usd`/`gw_usd`, the per-side cost cross-check, `>200K` count, and the per-unit turn-1 cache-read distribution. Validation anchor (task 1) passed beyond spec: **every priced bucket and every side matches LiteLLM to the cent (Δ +0.0%)**, opus and sonnet both.
- **Task 2 (+28% sonnet discrepancy): RESOLVED — it never existed.** Per-gen LiteLLM costs match the list back-calc exactly; the July probe's own back-calc was at fault (hypothesis (e): per-path token-accounting — it summed `$ai_input_tokens`, which is the WHOLE prompt, as if fresh). Trap recorded for future readers: LiteLLM's `input_cost` breakdown field is the whole input side (fresh + cache read + cache write), not fresh-only.
- **Task 3 (archived-arm recompute): DEAD — the urgency note fired.** The local DB was nuked 2026-07-06; the 07-03 arm events are gone. The corrected sonnet-era baseline accumulates from fresh runs instead. First data point (`runs/gate0-run1-pr68749-publish.md`, single-chunk publish run on PR #68749): true $9.90 vs naive $47.52 (4.8×, matching the probe-era ratio), bucket split 43% cache reads / 33% writes / 19% output / 5% fresh.
- **Task 4 (T1 detector): NOT RUN** — no archived data; run it over fresh runs as they accumulate. **Task 5 (re-anchor CANDIDATES.md $): NOT RUN** — needs the fresh-run baseline.
- **Part 2 (gateway probe): NOT STARTED.**
- **Part 3 (fork-sizing): NOT STARTED**, and its data source changed: archived ACP logs died with the DB, so `s`/warmth compute from fresh runs' events + ACP logs. The PR #68749 run is single-chunk (usable for one chunk's 3-wave-unit overlap, useless for cross-chunk warmth); the large multi-chunk runs the locked priority demands still need to be generated.
- Bonus live evidence from a real publish run (not a smoke): 2/3 wave units read the leader's identical 27,618-token [tools+preset] prefix at turn 1; the blind-spot fired 12.5 min after the wave and rewrote everything — third independent confirmation of the TTL/per-chunk-sequencing requirement.
- Ops lessons for anyone running this locally are in `HARNESS.md` → "Smoke-run lessons" (mid-run `products/**/*.py` edits kill the run via nodemon; DB-nuke integration restore; buffered CLI stdout).

~~**Next experiment session = the Gate-0 remainder: Part 2 (gateway cache probe) + Part 3 (fork-sizing spikes), which now starts by generating fresh run data on large multi-chunk PRs (2 runs double as the corrected-baseline controls and the T1-detector corpus for tasks 3-5).**~~

**SUPERSEDED — ROUND CLOSED 2026-07-06 late session (user decisions, recorded as locked constraints 6-9 in `CANDIDATES.md`).** The user reframed the flagship: the warm-up is designed as THE per-chunk investigation stage, value scales with unbounded perspective count, so **the s-measurement no longer gates the build** — Part 3 as specified is demoted to an optional post-build diagnostic, and Part 2 is optional (the fork's own mechanics gate subsumes the substrate check). The 1h-TTL question is resolved (default 5m on our path, enforceable per sandbox via `ENABLE_PROMPT_CACHING_1H=1` — see `HARNESS.md` "1h cache TTL"). **The next experiment is the warm-up+fork build (#8) on frozen PR #62096, with its own plan in a new experiment folder; T1 detector and the corrected-baseline accumulation ride along on its control runs.** This Gate-0 plan stays as the record of Part 1 (shipped) and the superseded Parts 2-3 specs.

## Goal

Three deliverables, in priority order:

1. **Make every future cost gate computable and honest.** Extend the dump harness with a cache-aware split, publish the corrected
   sonnet-era baseline next to the naive numbers, and re-anchor the $ estimates of candidates #4-#10.
   Sub-decision: settle the T1 rewrite-bug ticket (press with fresh sonnet-era evidence, or demote and record).
2. **Verify the cache-sharing substrate through the LLM gateway.** Do two distinct clients share one cache? A necessary
   (not sufficient) condition for any cross-sandbox sharing — arm 5 (sandbox-origin) is the load-bearing arm now that the fork
   family is the flagship; the direct-path breakpoint result only matters for the one-shot chunking/dedup calls.
3. **Size the fork flagship.** #3's two offline analyses over existing run data: the perspective-invariant exploration-overlap
   share _s_ (the fork build's go/no-go, threshold ~0.55 strict) and the prefix-warmth TTL timeline (does the fork build need
   chunk-local rescheduling; can the blind-spot be a 5th forker). Compute on the largest available multi-chunk runs as well as
   frozen #62096 — large PRs are the program's priority (locked 2026-07-06).

Non-goals: NO pipeline changes, NO eval runs, NO harness (PostHog Code repo) changes, NO builds of #4/#8/#10. Zero prod risk by construction.

## Working mode (locked with the user 2026-07-06)

- Experiments run **iteratively and in isolation, one after another** — this round runs alone on its own branch off `signals/reviewhog`
  (suggested: `signals/reviewhog-exp-caching-gate0`).
- If a later experiment's changes contradict earlier ones, stash the work after the experiment concludes, or better, keep each
  experiment on its own branch. Only decided winners merge back.
- Only durable artifact expected to merge from THIS round: the `dump_result.py` extension (it is eval tooling, not pipeline code)
  plus the result docs in this folder.

## Urgency note

Part 1 recomputes the archived 07-03 eval arms from local ClickHouse `$ai_generation` events.
**First action of the round: confirm those events still exist** (retention makes this fragile — the 10-day probe window barely covered
them on 2026-07-06). If they have aged out, the corrected baseline must come from the next round's 2 control runs instead; record that
in the run log and proceed with the rest.

## Part 1 — cache-aware metrology (#1, offline, $0 LLM, ~1 day)

Instrument: `products/review_hog/eval/scripts/dump_result.py` (currently sums `$ai_input_tokens`/`$ai_output_tokens` with no cache
split, lines ~50-61; OUT_DIR-overridable; queries local ClickHouse over `$ai_generation`).

Extend with per `(model x stage)` columns (stage = the `ai_stage` / `task_title` attribution already used):

- `gens`, `fresh_in_tokens`, `cache_write_tokens` (`$ai_cache_creation_input_tokens`), `cache_read_tokens`
  (`$ai_cache_read_input_tokens`), `long_ctx_gens` (prompt > 200K — the premium-tier boundary), `output_tokens`
- `true_usd`: list-price back-calc — opus-4-8 $5/$25 per M, sonnet-5 $2/$10 per M (per `../2026-07-reviewer-model-sonnet5/FINAL_REPORT.md`),
  writes 1.25x, reads 0.1x, long-context gens priced at the premium tier
- `gw_usd`: summed gateway `$ai_total_cost_usd`, kept as a standing cross-check column, not a one-off
- per-unit turn-1 cache_read as a DISTRIBUTION (per-unit values + hit count), the cross-sandbox-sharing tripwire.
  **2026-07-06 update: the baseline is NOT uniformly 0 anymore** — the harness smoke observed 2/3 wave units reading an
  identical 27.6K [tools+preset] segment via natural jitter (see `HARNESS.md`); medians mislead, report distributions.

Tasks:

1. **Validation anchor:** opus-4-8 `true_usd` must match `gw_usd` within 1% (the 2026-07-06 probe matched to <0.1%). If it does not,
   stop and debug the pricing table before anything else is trusted.
2. **The +28% sonnet discrepancy:** the probe found sonnet-5 `gw_usd` ~28% above list-price back-calc (implied blended ~$2.55/M).
   Test an enumerated hypothesis list and publish which one closes the gap: (a) >200K long-context tier split; (b) requested-vs-served
   model mapping (allowlist — check `$ai_model`); (c) Bedrock-reroute pricing on Anthropic 5xx; (d) gateway price-table error for the
recently enabled sonnet-5 row; (e) per-path token-accounting convention differences. Decision rule if none closes it: trust
`gw_usd`as ground truth for scoring, keep`true_usd` as the decomposition lens, and note the residual.
3. **Corrected Economics table:** recompute the archived sonnet-5 arms (B1/B2 of the model round; pipeline-models arms C/F/G if events
   survive) as an ADDED true-cost column next to the naive $ (never replacing it — cross-round continuity), scoped by task
   identity (`task_title`/run ids) rather than raw time windows where possible (overlapping local LLM activity contaminates windows).
   Publish into `FINAL_REPORT.md` of this round and update the reframing numbers in `CANDIDATES.md` if they moved.
4. **T1 rewrite detector:** over post-flip runs (local team-1 + prod cloud since 2026-07-03): consecutive gens within one
   `task_run_id`, time-ordered (subagent interleave breaks naive adjacency), flag `cache_read < 0.05x prev(cr+cw+fresh)` AND
   `cache_creation >= 0.8x prev` AND `gap <= 120s`; sweep the creation threshold 0.8 -> 0.5 for partial rewrites; classify
   rewrite-after-write vs session-restart/compaction shapes; separate Bedrock-fallback reroutes (identical signature — segment by
   routing telemetry if the gateway records it, else correlate detections with Anthropic 5xx in the window and state the confound as
   bounded). Output: rewrites/run, rewritten tokens/run, $/run at sonnet write price ($2.50/M), turn-position histogram.
   **Decision: >= $0.5/run -> press the Tasks-team ticket with this evidence; < $0.3/run -> demote the ticket, record in
   INVESTIGATION.md.** (Crude 2026-07-06 probe: ~$0.005/run post-flip; demotion is the expected outcome.)
5. **Re-anchor CANDIDATES.md:** restate #4-#10's $ estimates against the corrected sonnet-era buckets (esp. #4's fetch-choreography
   $/unit and #9/#10's $/turn, both opus-era today).

## Part 2 — gateway cache probe (#2, throwaway script, ~$0.25-0.60 LLM, ~1-3h)

> **2026-07-06 update:** the existential cross-client question already has a live production PASS — the harness smoke
> observed two fresh sandboxes reading a third's 27.6K cache write through the full stack (Modal -> ngrok -> local
> gateway); see `HARNESS.md`. Run the probe anyway for the controlled arms (share RATE, allowlist mapping, TTL sanity),
> but treat arm-2 failure as an anomaly to investigate, not a program-killer.

Script (scratch, not committed to the pipeline): raw `client.messages.create` — NOT `.parse` (structured outputs inject schema bytes
into the request), thinking OFF (adaptive thinking is incompatible with `max_tokens=64` and thinking config invalidates message-span
breakpoints) — through `get_async_anthropic_gateway_client(product="review_hog", team_id=...)` (same path as
`reviewer/sandbox/direct_llm.py`; Bedrock fallback already off there). Payload: ~10K-token document block ending in an explicit
`cache_control: {type: "ephemeral"}` breakpoint, `max_tokens=64`. **Every arm AND every trial salts the document with a unique nonce**
so arms can never read each other's warm entries (reads refresh the sliding TTL free, silently contaminating creation baselines).
Hold metadata/user_id/extra headers constant across processes. Record `response.usage` (`cache_creation_input_tokens`,
`cache_read_input_tokens`) and cross-check the `$ai_generation` cache fields.

| arm                                                                | shape                                                                                                                 | gate                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 (positive control)                                               | same process, identical request 2 min apart                                                                           | trial 2 `cache_read >= 0.95x` trial 1 `cache_creation`. FAIL -> the gateway strips/ignores `cache_control` on the direct path: file a gateway ticket (affects only one-shot chunking/dedup breakpoint optimization now) and re-probe the cross-sandbox question via a CLI-driven sandbox session pair once T2 lands — intra-session caching demonstrably works through the gateway, so a strip would be direct-path-specific |
| 2 (the claim)                                                      | two separate OS processes, 2 min apart, **replicated >= 3x with fresh nonces**                                        | report a share RATE, not a binary (a gateway pooling several upstream keys/workspaces shares probabilistically); gate: process-B `cache_read >= 0.95x` process-A `cache_creation`, same trial                                                                                                                                                                                                                                |
| 3 (allowlist confound)                                             | `REVIEW_MODEL` vs a non-allowlisted model name                                                                        | confirm `$ai_model` on BOTH sides; if the name silently maps to the SAME served model, a HIT is the expected outcome — model identity, not hit/miss, is the finding                                                                                                                                                                                                                                                          |
| 4 (negative control)                                               | 6-min gap, fresh nonce, guaranteed zero intermediate reads                                                            | must MISS (sliding TTL)                                                                                                                                                                                                                                                                                                                                                                                                      |
| 5 (sandbox origin — MANDATORY before any cross-sandbox greenlight) | one byte-identical pair issued as raw gateway calls from INSIDE a sandbox (network-origin/credential/workspace check) | same as arm 2. NOT a Claude Code CLI-driven pair — CLI requests cannot be byte-identical today (V1/V2) and would miss by construction                                                                                                                                                                                                                                                                                        |

Interpretation discipline (write this into the report verbatim-honest):

- Arms 1+2+5 PASS -> the workspace substrate for cross-sandbox sharing is verified (and explicit breakpoints work on the
  direct path, useful for one-shot chunking/dedup).
- A PASS does **not** "de-risk" the cross-sandbox program: T2/T3 byte fixes and CLI breakpoint placement remain unproven; arm 5 covers
  origin only.
- Arm 1 passes, arm 2 fails persistently -> the gateway partitions clients (bytes or credentials): escalate to the gateway/Tasks team
  (the probe can demonstrate THAT divergence exists, not produce the exact wire diff) and stop all cross-request candidates.

## Part 3 — fork-sizing spikes (#3, offline, $0-5 LLM, ~1-2 days)

Full spec in CANDIDATES.md #3 — execute as written there, with the critics' mods (wave-only s, strict 3-of-3 / loose 2-of-3,
blind-spot marginal overlap reported separately, early-window reconciliation, the raised-threshold rule if the TTL gate fails).
Execution notes:

- Join `$ai_generation` (timestamps, `cache_creation`) to the tasks' ACP logs for tool-call ARGUMENTS — `$ai_tools_called`
  carries names only. If archived ACP logs are gone, capture from the next round's control runs and record the gap.
- **Include large multi-chunk runs** (e.g. the live PR #67419 run: 3217 additions, one-shot chunking, 61 raw findings), not
  just frozen #62096 data. Report s per chunk-count bucket — large PRs are the priority, and s may differ there (chunks of a
  big PR touching shared modules plausibly overlap more, which would RAISE the fork's value exactly where it matters).
- Gates: wave-fork GO at s_p50 >= ~0.55 strict; wave-internal max-gap p95 < 4 min -> no rescheduling build needed;
  wave->blind-spot gap p95 < 4 min -> blind-spot qualifies as 5th forker (+$0.8-1.1/run).

## Pre-flight

- flox env; local ClickHouse reachable and holding `$ai_generation` for the archived eval windows (check FIRST — see urgency note).
- Part 3 needs the tasks' ACP logs (S3/object storage) for tool-call arguments — check access and retention alongside the
  ClickHouse check.
- Gateway client credentials work from the worker env (`get_async_anthropic_gateway_client`).
- No dev stack needed beyond ClickHouse; no sandboxes except arm 5 (one throwaway task or a shell into an existing sandbox image).
- Nothing in this round touches `reviewer/` pipeline code or prompts.

## Scoring & decision

Round output = `FINAL_REPORT.md` in this folder (convention: TL;DR, setup, results incl. the corrected Economics table, probe arm
table with rates, recommendations, cost totals) plus:

1. corrected baseline published; naive-vs-true kept side by side
2. T1 ticket: pressed or demoted (recorded in INVESTIGATION.md either way)
3. cross-sandbox substrate verdict (arm 2 + arm 5 share rates) and the fork go/no-go inputs published (s per chunk-count
   bucket, TTL warmth timeline, blind-spot 5th-forker verdict)
4. CANDIDATES.md re-anchored (its $ figures and the measured-facts section updated with sonnet-era cache-aware numbers)
5. recommendation for the next rounds, for the user to greenlight: Round 1 default per CANDIDATES.md = #4 skill-body splice +
   #10 pre-pack (after its pre-gate); flagship verdict = fork ladder GO/STOP from s + substrate. Harness path is resolved
   (2026-07-06): experiments run on a locally patched PostHog Code checkout (`/Users/woutut/Documents/Code/code`);
   upstreaming is decided after the experiment proves value

## Run log

(append entries as work happens: date, what ran, headline numbers, surprises, files touched)

- **2026-07-06 (scope-narrowed session: single PR review + spend-calc fix only, per user).** DB had just been nuked: `$ai_generation` archive = 0 (archived-arm recompute impossible; corrected baselines must come from fresh runs), team 1/user 1 survived re-seed, GitHub integration row was gone — restored via `GitHubIntegration.integration_from_installation_id("143741024", team_id=1)`. Ran `run_review` on live PR #68749 with `--publish` (single chunk: 461 raw additions but reviewable lines under the 400 gate). **Lesson burned: editing `products/**/\*.py` mid-run respawns the temporal worker (nodemon) and killed the first attempt's wave;** Temporal retried the workflow, which resumed from persisted (pass, chunk) results at the same head — wave was not re-paid, blind-spot re-ran. Run finished, review published (`posthog-local-dev`, 20:45 UTC), funnel 1 chunk / 4 units / 8 raw / 8 dedup / 4 valid.
- **2026-07-06 late — TTL investigated, program reframed, round closed.** Proved the sandbox path runs on the 5m cache TTL (billing at exactly 1.25×, >5m gaps rewrite in full, and the CLI's `CCH()` gate requires first-party auth before its allowlist — decompiled from the CLI bundle) and that `ENABLE_PROMPT_CACHING_1H=1` in the sandbox env enforces 1h unconditionally (injection point: `provision_sandbox.py`; per-unit; 2× writes; `FORCE_PROMPT_CACHING_5M` is the kill switch) — full detail in `HARNESS.md` "1h cache TTL". User locked the reframe (CANDIDATES.md constraints 6-9): warm-up = designed investigation stage, N unbounded, s-gate dropped, fixture #62096. Gate 0 closed; next experiment = the #8 fork build. Doc updates left uncommitted (user commits).
- **2026-07-06 — Part-1 instrument shipped and validated live.** `eval/scripts/dump_result.py` extended: per (model × stage) split into fresh (1×) / cache write (1.25×) / cache read (0.1×) / output, `true_usd` (list, mirrors LiteLLM's map incl. haiku; 1h-TTL writes bill 2× and are visible only in the write-side cost field), `gw_usd` (`$ai_total_cost_usd`), per-side `$ai_*_cost_usd` cross-check (NB: LiteLLM's `input_cost` = whole input side, cache included), `>200K` diagnostic count, and the per-unit turn-1 cache-read distribution. Validation on the PR #68749 window (`runs/gate0-run1-pr68749-publish.md`): **true $9.90 vs gw $9.90, Δ +0.0% on every bucket and every side** — the old probe's +28% sonnet discrepancy did NOT reproduce against per-gen LiteLLM costs (its back-calc, not the gateway table, was at fault). Naive method = $47.52 = **4.8× true** (matches CANDIDATES.md's measured fact). Bucket split this run: 43% cache reads / 33% writes / 19% output / 5% fresh. Tripwire reproduced the smoke-run finding: 2/5 units read the leader's identical 27,618-token [tools+preset] prefix at turn 1; blind-spot started 12.5 min after the wave (TTL busted, full rewrite).
