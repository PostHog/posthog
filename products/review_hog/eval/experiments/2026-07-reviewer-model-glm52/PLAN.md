# Experiment: GLM 5.2 vs Sonnet 5 as the perspective-review model

> **ROUND 6 — EXECUTED 2026-07-31, verdict: PASS — injected memory makes Sol turns additive.**
> J2 (turn 2, native `<already_covered_findings_for_chunk>` injection verified in all 9 unit
> prompts): 3/4 verified real (75%), 2 must_fix, ZERO re-reports of J1 — incl. **E1, a brand-new
> must_fix cluster (any-GitHub-bot author floor) no prior set across 7 models found**, and E2
> re-catching the migration blocker J1's blind pass missed (no anchoring). Pair: 6 distinct real
> clusters / 3 must_fix at $15.66 true (~48m); marginal turn = $6.10 → 3 reals, best
> reals-per-dollar of the experiment. The round-5 "5.6 reach limit" was per-RUN, not per-model.
> Caveats: J1 = weakest blind Sol single (3/10); pair recall 6 < one Sonnet run's 7. Empty commit
> `a7fb363` (signed — unsigned commit-tree pushes bounce off the repo ruleset) moved the head;
> clusters 74 → 76; data in FINAL_REPORT § Round 6 + judge-round6.json. Original spec below.
>
> **ROUND 6 spec (2026-07-31): sequential Sol with prior-findings injection.**
> Question: round 5 showed a blind second Sol run wastes budget re-finding run 1's issues (S2→W4
> dup, ~3 new distinct reals). Does a second Sol run that KNOWS run 1's findings push into new
> territory instead — and does 2×Sol-with-memory then rival one Sonnet run (7 reals, ~$40) at ~$25?
>
> **Arm J** = `CODEX`/`gpt-5.6-sol`/`XHIGH`/`"full-access"`, same frozen PR #75215 @ `1341596e`,
> same chunk pin + Opus validator. Labels `J-gpt56sol-seq-{1,2}`, blind sets Z (J1) and E (J2).
> Protocol: wipe → J1 (blind, identical to round-5 arm I) → dump → **NO wipe** → push an **empty
> commit** to the frozen branch (new head SHA, diff byte-identical — the production "new commits →
> new turn" trigger shape, with zero review-content change) → J2 (sees J1's findings) → dump →
> revert + wipe.
>
> **Context injection is NATIVE — no harness changes beyond round 5's.** The pipeline already
> injects prior turns' findings from the ReviewHog DB into every review unit's prompt as
> `<already_covered_findings_for_chunk>` (`load_prior_findings_with_verdicts` keyed by
> `before_run_index`, publication-independent — "some … were never posted as inline comments"),
> and the same set joins the dedup gate as an enforcement backstop. The round-3
> `fetch_pr_comments` clean-room mock (`return []`) stays exactly as-is: it only suppresses the
> real GitHub comments (the frozen PR carries other bots' noise), which is still wanted.
>
> **Mechanics (verified against the code 2026-07-31):**
>
> - The empty-commit head bump makes the whole turn-2 path production-shaped: `run_index =
report.run_count + 1` (run_count bumped at J1's finalize) gives turn 2 naturally, and unit
>   resume is head_sha-scoped (`load_perspective_results` keys `(report, head_sha) → (pass,
chunk)`), so the new head misses turn-1 artefacts organically — no scrubbing, no same-SHA
>   special-casing. An earlier draft of this spec scrubbed working-state artefacts to force a
>   same-SHA re-review; dropped as unrealistic — prod re-reviews only ever happen on a moved head.
> - The chunk pin and the verification worktree stay valid because the empty commit leaves the
>   diff byte-identical; dumps will just record the new head_sha.
> - The pushed empty commit needs Alex's go (or Alex pushes it) — experiment sessions never push.
> - Verify J2's kickoff prompt actually contains the injected findings (spot-check one unit's
>   rendered context) before letting the wave spend money.
>
> **Measurement:** adversarially verify J1 and J2 (same refutation-first protocol, worktree @
> `1341596e`); extend clusters. Read out: (1) duplicate rate J2-vs-J1 — injection efficacy,
> expect ≈0 vs the blind pair's re-finds; (2) NEW distinct verified reals J2 adds beyond J1;
> (3) union(J1, J2) vs one Sonnet run (7 reals) and vs the blind Sol pair (8 reals / 7 distinct);
> (4) anchoring check — does J2 merely extend/validate run-1 areas. Verdict rule: J2 adds ≥3 new
> distinct verified reals with ≈0 dups → sequential-Sol-with-memory is a real config, promote the
> DB-backed injection idea; J2 rehashes despite injection → the 5.6 reach limit is confirmed and
> the Sonnet-wave + single-Sol-lens combo stands as the endgame.
>
> **ROUND 5 — EXECUTED overnight 2026-07-30 → 31, all 4 runs + judging completed.** Two arms:
> Sonnet stability (A3/A4, sets N/O — verified + clustered, excluded from the panel) and
> **GPT 5.6 Sol** (arm I = `CODEX`/`gpt-5.6-sol`/`XHIGH`/`"full-access"`, sets S/W, full protocol,
> panel re-ranked with Sol as M7). Verdict: **Sonnet's numbers were not luck** — four runs across
> two rounds each produced exactly 7 verified reals (7/20, 7/24, 7/23, 7/26); default unchanged.
> **Sol displaces Terra as the Codex champion**: 8/24 real (33.3%), 3 must_fix, 16 clusters,
> panel #1 on impact (only model touching all three heavy clusters), #2 on recall AND precision,
> ~$11 true and ~8m clean review in both runs. Round-4 correction: the migration-0019 CI blocker
> was target drift, not a Sonnet blind spot — both stability runs catch it as must_fix on the
> frozen PR. Full data: FINAL_REPORT § Round 5 + judge-round5.json (clusters 62 → 74).
> Ops: A3 survived a ~6.5h host sleep mid-run (Temporal recovered on wake; timings excluded,
> findings/cost valid). Preflight lesson applied: product-path probe for `gpt-5.6-sol` 200'd
> before launch (allowlist extended in gateway config.py — kept, like the round-4 additions).
> Sol's fake-refusal boot storms (17 and 16 first-attempt failures) fully absorbed by the
> fail-fast retries; zero stragglers, zero rescue. Harness reverted to the master baseline
> (byte-identical via merge-base checkout) and staged the same night.
>
> **ROUND 4 — EXECUTED 2026-07-30, all 4 runs completed same day.** Verdict: **Terra** wins
> precision (6/16 real) and impact (4 must_fix, densest ever) at ~$10/run with an 8-minute clean
> review; **Luna** not competitive (4/28 real); **Sonnet keeps the default** on recall. Full data:
> FINAL_REPORT § Round 4 + judge-round4.json. Harness reverted to baseline the same day.
>
> **ROUND 4 (2026-07-30) — GPT 5.6 (Luna, Terra), supersedes round 3.** Round 3's arms are dropped:
> arm E (gpt-5.5 retest) is superseded by the 5.6 family (faster, and Luna far cheaper); arm F
> (GLM via Modal) is shelved — the Modal deployment 503'd under the 9-session fan-out on 2026-07-24,
> and GLM is slow regardless. Of the arm-E prerequisites, #2 landed this round as a real product fix:
> `_check_logs`/`poll_for_turn` now treat `stopReason:"refusal"` as terminal (fail fast → in-session
> nudge retry → activity retry), so a refusal costs seconds, not 30 minutes.
>
> **Target: PR #75215** — a frozen copy of #72680 at `1341596e` (same branch content, opened as its
> own draft PR because #72680's head moved on to the fixes). Diff content is byte-identical to what
> rounds 1–3 reviewed, so the pinned chunks and zero-comment mock carry over unchanged; run dumps
> carry the new PR number.
>
> | Arm | Adapter | REVIEW_MODEL    | Effort  | Permission mode | Runs | Labels                     |
> | --- | ------- | --------------- | ------- | --------------- | ---- | -------------------------- |
> | G   | `CODEX` | `gpt-5.6-luna`  | `XHIGH` | `"full-access"` | ≤2   | `G-gpt56luna-xhigh-{1,2}`  |
> | H   | `CODEX` | `gpt-5.6-terra` | `XHIGH` | `"full-access"` | ≤2   | `H-gpt56terra-xhigh-{1,2}` |
>
> Effort: `xhigh`, matching Sonnet/Opus/gpt-5.5 (GLM-at-MAX stays the outlier); 5.6 also supports a
> new `max` tier — a later curiosity repeat, not part of this round. Order interleaved
> G1 → H1 → G2 → H2, wipe DB + verify PR head before each run. Repeat gate per arm: a run that
> DNFs after the retry ladder or needs heavy operational rescue = technical shitshow → skip the
> repeat, record "no verdict — infra" (not a model judgment); completes with 0 validated findings =
> model shitshow → skip the repeat, it IS the data point; weak-but-complete → repeat happens.
> Judging: incremental, same machinery as the 4-way — blind the new sets, one adversarial verifier
> per finding against the worktree @ `1341596e`, extend the existing cluster set, fresh 3-lens
> panel over all six anonymized models reusing the old sets' verdicts.
> Preflight 2026-07-30: gateway probes `gpt-5.6-luna` + `gpt-5.6-terra` → 200/completed; django
> tunnel probed from Modal's network → 200; fresh local DB (user 1 / team 1 / GitHub integration
> installed). End state unchanged: revert mock + pin + constants to the Sonnet baseline.
>
> **G1 attempt 1 (2026-07-30 ~12:00) failed on a gateway allowlist gap, not the model.** All 8
> units died in ~30 min with `stopReason:"refusal"` at 0 tokens. ngrok's request inspector showed
> every sandbox call as `POST /review_hog/v1/responses → 403`: the gateway's `review_hog` product
> allowlist lacked the 5.6 family (only glm-5.2 / sonnet-5 / opus-4-8 / gpt-5.5). Fixed by adding
> `gpt-5.6-luna` + `gpt-5.6-terra` to `services/llm-gateway/.../products/config.py`; uvicorn
> `--reload` picked it up; product-path probes then 200'd. Two durable lessons: (1) preflight must
> probe the **product-scoped** path (`/review_hog/v1/responses`), not the generic `/v1/responses` —
> the generic path runs under the allow-everything `llm_gateway` product; (2) codex-app-server maps
> codex `TurnStatus:"failed"` → ACP `"refusal"` (`mapTurnStopReason`), so "refusal" in our logs
> means "turn failed", not necessarily a safety refusal — which casts doubt on whether round-3's
> gpt-5.5 "refusal storm" was ever a content refusal (its refusals arrived ~90s in with the model
> allowlisted, so that one did reach the API; mechanism still unconfirmed).
>
> **CONFIRMED during G1/H1 (2026-07-30): Codex first attempts fail systematically, and it is not
> the model.** In both G1 (Luna) and H1 (Terra), **all 9 first-attempt review units failed within
> seconds of each other**, ~90s after session start, labeled `stopReason:"refusal"`, with **zero
> tokens billed** — the requests never reached OpenAI, so this is not a content/safety refusal and
> not chunk-specific. Staggered retries then succeed (G1: 24 failed attempts hidden inside a
> "clean" run; H1: 8/9 attempt-2s recovered immediately). Blind-spot and validation stages (4
> concurrent, later boot) never hit it. Working theory: the codex-app-server MCP-connect race at
> sandbox boot, amplified by 9 simultaneous first-boots — the same mechanism as round 3's C1
> "17/17 refusal storm", now effectively proven. The refusal pre-fix is what makes this survivable:
> each failed attempt costs ~90s instead of a 30-min poll timeout. Residual cost: units whose retry
> goes gen-silent still ride the 30-min poll budget (G1's p2-c1, H1's p3-c1) — that is the real
> wall-clock tax on Codex arms. Adapter-level fix (await MCP ready before the first prompt, or
> fail-fast + instant retry) belongs in posthog/code, not this experiment.
>
> **G1 attempt 2 (healthy, ~40 min in) was terminated by Alex's call: it ran with zero cost/token
> telemetry**, and cost/token is a hard requirement. The fresh stack loses every local
> `$ai_generation` in two stacked ways: the gateway process never received the
> `LLM_GATEWAY_POSTHOG_*` env from `bin/mprocs.yaml` (capture disabled entirely — fixed via repo
> `.env` + gateway restart), and once enabled, the SDK's AI lane (`/i/v0/ai/batch/`) 200-ACKs
> events that `ingestion-ai` then drops (its forwarder 401s on `localhost:8010/batch/` and shuts
> down). Local bypass in the gateway callback: `_use_ai_lane=False` **and**
> `_enable_multimodal_capture=False` (multimodal implies the lane) — marked EXPERIMENT, revert
> both. E2E verified: gateway probe → luna gen with cost in local ClickHouse. Cleanup: 15 orphan
> Modal sandboxes terminated, DB wiped. G1 attempt 3 is the first run with full telemetry.

> **ROUND 3 (planned 2026-07-24, not started — Alex present for these; SUPERSEDED by round 4).** Two follow-up arms, prompted
> by the round-2 findings and Alessandro's Slack comment that GLM was supposed to run on **Modal
> inference** (which supports caching and reportedly runs faster than Opus), not Cloudflare:
>
> | Arm | What                            | Config                                                                                 | Runs | Labels                   |
> | --- | ------------------------------- | -------------------------------------------------------------------------------------- | ---- | ------------------------ |
> | E   | gpt-5.5 retest, done properly   | `CODEX`/`gpt-5.5`/`XHIGH`/`"full-access"` — after the fixes below                      | 2    | `E-gpt55-xhigh-{1,2}`    |
> | F   | GLM 5.2 via **Modal inference** | `CLAUDE`/`@cf/zai-org/glm-5.2`/`MAX` + gateway routed to Modal (`zai-org/GLM-5.2-FP8`) | 2    | `F-glm52modal-max-{1,2}` |
>
> **Why round 2's arm C was not a fair gpt-5.5 test:** 17/17 first-attempt provider refusals
> (`stopReason:"refusal"` ~90s in), each amplified into a 30-min hang by the `poll_for_turn` bug;
> ~43% of Codex sandboxes silently got no MCP tools and reviewed without their perspective skill.
> C1 hard-failed; C2 recovered only via a 3rd-attempt ladder. Details: FINAL_REPORT § 4-way extension.
>
> **Arm E prerequisites (fix/diagnose first, with Alex present):**
>
> 1. Reproduce the refusal cheaply outside the pipeline: replay a failed unit's exact `session/prompt`
>    text (saved in the S3 turn logs) against gpt-5.5 directly through the gateway — distinguishes
>    model-refuses-content from a Codex-adapter/harness artifact. Iterate on whatever it shows.
> 2. Make `poll_for_turn` treat a refusal-completed turn as terminal (products/tasks
>    `custom_prompt_internals.py`) — otherwise every experiment iteration costs 30 min per refusal.
>    Real product bug; worth landing regardless.
> 3. Diagnose Codex MCP flakiness (9/21 sessions in C1 had no `posthog/exec`) — likely a connect race
>    at session start; a turn without MCP tools should fail fast, not improvise skill-less.
>    **Arm F prerequisites:**
> 4. Local gateway needs the Modal inference creds: `LLM_GATEWAY_MODAL_API_BASE`,
>    `LLM_GATEWAY_MODAL_KEY`, `LLM_GATEWAY_MODAL_SECRET` (Alex fetches, same place as the CF keys).
> 5. Force the Modal route with `LLM_GATEWAY_GLM_MODAL_TRAFFIC_FRACTION=1.0` (routing precondition:
>    all three Modal creds set, else `_route_to_modal` short-circuits to Cloudflare). Verify with a
>    probe request + gateway logs BEFORE run 1; also verify the cache signature — Modal/vLLM prefix
>    caching should show as non-zero cached tokens, which the CF path never had.
> 6. Cost accounting decision: Modal is self-hosted (no per-token list price; gateway will price
>    $0.00) — report raw token flow + wall-clock, and compare CF-list-priced tokens as an upper bound.
>    **Shared harness (re-apply for the runs, revert after — all three were reverted post-round-2):**
>    comment mock (`fetch_pr_comments → []`), chunk pin (constants loader + `split_chunks_activity`
>    hook, `pinned_chunks.json` still in this folder), arm constants. PR 72680 must still be at
>    `1341596e` — verify before each run; if the head moved, stop and re-plan (results would not be
>    comparable with rounds 1–2).
>    **Carry-over caveat for arm F conclusions:** round-2's GLM cost (+50–100%) and speed (slower)
>    findings are Cloudflare-path artifacts (zero caching); only the quality numbers (7/36 verified
>    real, must_fix ownership, ~30% Sonnet overlap) are expected to carry over.

> **EXTENDED 2026-07-23 night → 4-way model comparison.** After the A/B verdict (see FINAL_REPORT.md),
> two more arms run overnight on the identical setup (same PR @ `1341596e`, same pinned chunks, same
> zero-comment clean room, same validator):
>
> | Arm | Adapter  | REVIEW_MODEL      | Effort  | Permission mode                                           | Runs | Labels                 |
> | --- | -------- | ----------------- | ------- | --------------------------------------------------------- | ---- | ---------------------- |
> | C   | `CODEX`  | `gpt-5.5`         | `XHIGH` | `"full-access"` (headless Codex stalls on MCP without it) | 2    | `C-gpt55-xhigh-{1,2}`  |
> | D   | `CLAUDE` | `claude-opus-4-8` | `XHIGH` | `None`                                                    | 2    | `D-opus48-xhigh-{1,2}` |
>
> Order C1 → C2 → D1 → D2 (one constants flip between arms), dump → wipe after every run.
> Arm-C failure policy: if a C run hard-fails, retry once; if the arm fails twice, skip to D and
> report — don't burn the night. Note for D: Opus 4.8 IS the SDK fallbackModel, so fallback
> contamination is undetectable-by-construction for that arm (note it, don't chase it).
> Judging: blind sets R (C1), T (C2), U (D1), V (D2) via `blind_prep.py`; verify every finding
> against the PR worktree; cluster across all 8 sets; 3-lens panel over four anonymous models.
> End state: revert mock + pin + constants to the Sonnet baseline; extend FINAL_REPORT.md to the
> 4-way verdict; RUN_LOG + memory + Slack summary (/tmp).

**Question:** is `@cf/zai-org/glm-5.2` better than `claude-sonnet-5` at applying ReviewHog's review perspectives?
Everything else in the pipeline is held constant.

Follows the shared on-pipeline protocol (`../2026-07-reviewer-topology/PLAN.md` §"The dump/reset harness",
`../../POTENTIAL_EXPERIMENTS.md` §"Shared protocol for all on-pipeline runs"), with a fresh target PR.

## Arms

| Arm                                    | REVIEW_MODEL          | REVIEW_REASONING_EFFORT | Runs              | Labels                  |
| -------------------------------------- | --------------------- | ----------------------- | ----------------- | ----------------------- |
| A (baseline = prod config, zero edits) | `claude-sonnet-5`     | `XHIGH`                 | 1 (+1 if unclear) | `A-sonnet5-xhigh-{1,2}` |
| B                                      | `@cf/zai-org/glm-5.2` | `MAX`                   | 1 (+1 if unclear) | `B-glm52-max-{1,2}`     |

**Adaptive pairs** (decision 9): run A1 → B1, judge head-to-head; only if the verdict is unclear run
A2 → B2 and re-judge over all four. "Clear" = one arm wins on validated-finding quality with no red
flags (schema/parse failures, model fallback, lost wave units); thin or mixed margins → second pair.

Effort note: GLM 5.2 registers only `HIGH`/`MAX` (no `XHIGH`), so effort parity with the baseline is
impossible. Decision: each model at its strongest registered setting — the question is "would GLM beat
what we run in prod today", not a same-label comparison. Caveat recorded below (drop_params).

## What changes vs prod (all in the working tree, per-arm)

1. **Gateway allowlist** (`services/llm-gateway/src/llm_gateway/products/config.py`, `review_hog` entry):
   `allowed_models=None` → `frozenset({"@cf/zai-org/glm-5.2", "claude-sonnet-5", "claude-opus-4-8", "gpt-5.5"})`.
   Deliberately the _simple_ shape — no `allowed_application_ids`/`requires_server_credential` hardening
   (stamphog-style) yet; the one-shot direct calls authenticate through this product and must keep working.
2. **Agent-side routing** (code repo, `packages/agent/src/utils/gateway.ts`): add `"review_hog"` to the
   `GatewayProduct` union + an `originProduct === "review_hog"` case in `resolveGatewayProduct`, before the
   `isInternal` catch-all. Without this, sandbox reviews route to `background_agents`, whose allowlist lacks
   GLM → 403 → the Claude-SDK `fallbackModel` silently reruns on `claude-opus-4-8` (see the documented
   incident in `../2026-07-pipeline-models/FINAL_REPORT.md`). First sandbox after the edit pays a
   MODAL_DOCKER image rebuild (image bakes from `LOCAL_POSTHOG_CODE_MONOREPO_ROOT`).
3. **Comment mock** (`backend/reviewer/tools/github_meta.py`): `return []` at the top of
   `PRFetcher.fetch_pr_comments`. The target PR already carries bot/human/prod-ReviewHog comments; this is
   the single choke point where comments enter the pipeline. Active for ALL 4 runs → both arms see zero
   comments. Experiment-only hack.
4. **Chunk pin** (`backend/reviewer/`): re-add a minimal `EXPERIMENT_PINNED_CHUNKS` (the mechanism was
   deliberately deleted from the tree after the topology round — see `../../POTENTIAL_EXPERIMENTS.md` header).
   Run A1 chunks naturally (one-shot, Sonnet 5); its split becomes the pin for A2/B1/B2, so all four runs
   review identical chunks. Experiment-only hack.
5. **Arm B constants** (`backend/reviewer/constants.py:6-7`): `REVIEW_MODEL = "@cf/zai-org/glm-5.2"`,
   `REVIEW_REASONING_EFFORT = ReasoningEffort.MAX`. Adapter stays `CLAUDE` (GLM is driven through the
   claude adapter; the gateway translates the `@cf/` id upstream). This flips the blind-spot sweep too —
   decision: the blind-spot check is a perspective, same approach applies; whole finder wave = one model
   per arm.

Held constant in both arms: validation (`claude-opus-4-8` @ xhigh — same judge for both arms), one-shot
calls (chunking / perspective selection / dedup, `claude-sonnet-5` @ xhigh), all prompts and skills
(re-seeded defaults after each wipe).

## Target PR

`https://github.com/PostHog/posthog/pull/72680` (own PR — open, non-draft, non-fork,
head `posthog-code/stamphog-reviews-inbox-prs`). ~742 reviewable additions after filters → one-shot
chunking path. **Frozen for the duration: no pushes to the branch until the experiment is done.**
Runs never use `--publish`; with a fresh `ReviewReport` row each run, zero GitHub writes (the mid-run
status-comment refresh is a no-op when `status_comment_id` is NULL).

## Per-run loop (serial, adaptive: A1 → B1 → judge → [A2 → B2])

1. Set constants for the arm; confirm the temporal-worker hot-reloaded (never flip mid-flight).
2. `date +%s` → RUN_START_EPOCH.
3. `flox activate -- bash -c "SANDBOX_PROVIDER=MODAL_DOCKER DJANGO_SETTINGS_MODULE=posthog.settings \
python manage.py run_review --pr-url https://github.com/PostHog/posthog/pull/72680 --team-id 1 --user-id 1"`
4. Dump: `LABEL=<label> RUN_SECONDS=<s> RUN_START_EPOCH=<epoch> \
OUT_DIR=products/review_hog/eval/experiments/2026-07-reviewer-model-glm52/runs \
python manage.py shell -c "exec(open('products/review_hog/eval/scripts/dump_result.py').read())"`
5. **Model-integrity check (mandatory, per run):** the dump's spend table must show the arm's model on
   every `issues-review-*` / `blind-spots-*` gen — `$ai_model` is the only trustworthy signal; a 403'd or
   unlisted model silently falls back to Opus with no warning. For B1, additionally probe `$ai_generation`
   in ClickHouse mid-run as soon as the first review units start and abort early if Opus appears.
6. Wipe: `DEBUG=1 python manage.py reset_review_hog --yes` (dump ALWAYS before reset). Wipes all four
   review_hog tables across all teams; skill configs re-seed to defaults → identical roster every run.
7. Next run.

Initial state: run the wipe once before A1 (clean slate).

## Preflight (before A1)

- **Local telemetry prerequisite (required for ANY experiment run on a local stack):**
  the local ingestion-ai forwarder 401s on `/batch/` and silently drops every AI-lane `$ai_generation` event.
  Add `LLM_GATEWAY_POSTHOG_AI_LANE_CAPTURE=false` to the repo `.env` (gitignored) and restart the local gateway,
  or none of the run's generations get tracked and every cost/token number is unrecoverable.
- temporal-worker + backend running (phrocs); worker start-time > last constants edit.
- ngrok tunnels up: `django` → :8010, `gateway` → :3308, `mcp` → :8787.
- Local gateway restarted after the allowlist edit (verify it serves the edited config).
- GLM servable: gateway `/review_hog/v1/models` lists `@cf/zai-org/glm-5.2` (requires Cloudflare or Modal
  creds on the local gateway — `_glm_backend_configured`) + a tiny direct Messages probe returns from GLM.
- Code-repo routing edit in place (`resolveGatewayProduct`).
- No `ReviewReport` row for PR 72680 / team 1.
- DEBUG=1.

## Scoring (after all 4 dumps)

- **Primary:** blind head-to-head LLM-judge over the four dumps' post-dedup validated findings — which arm
  surfaces more real, higher-impact issues on identical chunks; contested findings adversarially verified
  against the repo by hand.
- **Secondary:** funnel stats (raw → post-dedup → validator pass-rate), true-$ spend per arm,
  schema/parse-failure count, run-to-run stability within each arm, and **per-stage wall-clock** from
  the dump's "Stage timing" section — the **review-stage duration** (selection → last finder unit,
  wave + blind-spot) is the headline Sonnet-vs-GLM speed metric.
- Verdict + caveats → `FINAL_REPORT.md` in this folder.

## Known caveats (record in FINAL_REPORT)

- **Effort pin may be cosmetic for GLM:** both the Cloudflare and Modal gateway translations set
  `drop_params=True`, which strips Anthropic-style effort/thinking params — `MAX` vs `HIGH` may not reach
  the backend. Check gateway logs during the B1 smoke; report either way.
- The `background_agents` allowlist also lacks `gpt-5.5` (the old Codex review pin) — prod Codex reviews
  would hit the same silent-fallback path today. Follow-up regardless of this experiment's outcome.
- ARCHITECTURE.md §Sandbox execution layer still says the perspective review runs on Codex `gpt-5.5` —
  stale; current master pins `claude-sonnet-5` @ xhigh. Fix with the routing change when it lands.
- Generated type files (`api.schemas.ts`, `api.zod.ts`, MCP `generated.ts`, ~27 adds) survive the
  reviewable-file filters by design gap and will consume review attention in both arms equally.

## Decisions log

1. GLM @ MAX vs Sonnet @ XHIGH — each model at its strongest registered setting (no XHIGH for GLM).
2. Unblock GLM via a dedicated `review_hog` gateway product route (two-sided: gateway allowlist +
   agent-side `resolveGatewayProduct` case) — not by widening `background_agents`.
3. Gateway entry keeps the simple shape (allowlist only); stamphog-style hardening is a separate follow-up.
4. Blind-spot sweep switches with the arm (it's a perspective).
5. Comments mocked to `[]` for all runs (clean-room; PR was already reviewed by other bots + prod ReviewHog).
6. Chunks pinned from A1's natural split for all subsequent runs.
7. Serial runs; wipe after every dump; PR frozen; no publish; team 1 / user 1.
8. End state: the infra edits (gateway allowlist, agent-side routing) STAY in the working tree — they're
   the durable enablement, committed if GLM wins. The experiment hacks (comment mock, chunk pin, arm-B
   constants flip) are reverted; `REVIEW_*` returns to the Sonnet baseline pending the verdict.
9. Adaptive pairs instead of fixed 2+2: A1 → B1 → judge; second pair only when the 1v1 verdict is
   unclear (cheaper in expectation, same worst case; a 1v1 gap must be large to count as clear since
   single runs carry unmeasured variance).
