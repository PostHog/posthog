# Experiment: GLM 5.2 vs Sonnet 5 as the perspective-review model

> **ROUND 3 (planned 2026-07-24, not started — Alex present for these).** Two follow-up arms, prompted
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
