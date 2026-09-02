# FINDINGS — ops traps and environment facts (Kimi K3 experiment, 2026-09-01)

Reliable notes for future experiments. Read this BEFORE re-running anything on this machine.
Run-by-run results stay in [PLAN.md](./PLAN.md); this file carries the traps. Where a trap also held
for GLM 5.3 Flash, the shared traps live in `../2026-08-model-glm53-flash/FINDINGS.md` too.

## The big one for a new-model experiment on the claude adapter

1. **A local agent-model registry change needs a monorepo `pnpm build` — editing `src` is NOT
   enough, and the sandbox otherwise fails with "Agent-server failed to start."** In DEBUG the Modal
   sandbox build (`products/tasks/backend/logic/services/local_packages.py`) overlays the local
   monorepo's **pre-built `packages/{agent,shared,git}/dist/`** onto the sandbox agent — it reads the
   compiled `dist/`, never `src/`. So adding a model to `MODEL_EFFORT_LEVELS` in
   `packages/agent/src/adapters/claude/session/models.ts` does nothing until you rebuild `dist/`.
   With a stale `dist/`, the agent-server runs old code, `isSupportedReasoningEffort` returns false
   for the new model+effort, and `bin.ts` **hard-errors at startup** → the TaskRun ends
   `status=failed, error_message="Agent-server failed to start"` (seen here: 780 s, 33 agent-log
   lines, no turn produced). Fix, in the monorepo (`$LOCAL_POSTHOG_CODE_MONOREPO_ROOT`):
   `pnpm --filter @posthog/agent build`, then confirm `grep moonshotai/kimi-k3
packages/agent/dist/server/agent-server.js` hits. The overlay covers **agent, shared, git** — all
   three need a `dist/`.
2. **The monorepo needs `pnpm install` first, and the agent build `rimraf`s `dist` before it runs —
   so a FAILED build leaves NO `dist/` at all.** After a `posthog` master pull the monorepo's
   `node_modules` were stale: `pnpm --filter @posthog/agent build` died on
   `Could not resolve "@opentelemetry/exporter-trace-otlp-http"` (and `packages/harness` warned
   "node_modules missing"). Because the build script is `rimraf dist && tsup && …`, that failure
   deleted the previously-working `dist/`, which makes `get_local_posthog_code_packages` return
   `None` and silently fall back to the **npm-published** agent (which also lacks the new model).
   Always `pnpm install --prefer-offline` in the monorepo first, then build. Do **not** build with
   the recursive `@posthog/agent...` filter — it drags in `packages/harness`, whose own deps
   (`@earendil-works/pi-*`) may be missing and fail the whole run; the overlay only needs `agent`
   (its workspace deps `shared`/`git` already have a `dist/`).

## Kimi-K3-specific environment

3. **Kimi K3 is Modal-served, not Baseten (the GLM difference).** `services/llm-gateway/.../modal.py`
   pins `moonshotai/kimi-k3` to the `modal_kimi_api_base` setting (env
   `LLM_GATEWAY_MODAL_KIMI_API_BASE`); no Cloudflare/Baseten fallback. The endpoint URL + Modal
   proxy-auth come from the gateway's production secret store. Two gotchas cost a round-trip here:
   - **Use the Modal PROXY-AUTH token (`wk-…`/`ws-…`), not the Modal API token (`ak-…`/`as-…`).**
     Passing the API token id as `Modal-Key` returns HTTP 401 `{"error":"Webhook token not found:
ak-…"}`. The GLM-era `LLM_GATEWAY_MODAL_KEY`/`SECRET` (the `wk-`/`ws-` pair) authorize Kimi too —
     proxy-auth is workspace-scoped and Kimi is in the same `posthog--` workspace.
   - **The base URL must end in `/v1`.** The gateway hands `api_base` straight to litellm as the
     OpenAI `base_url` and calls `{base}/chat/completions`; vLLM serves under `/v1` (`/models` 404s,
     `/v1/models` 200s). A `.../modal.direct` base (no `/v1`) silently mis-routes.
   - Verified: `POST /v1/chat/completions` with `moonshotai/kimi-k3` → 200 in ~1.2 s, reasoning model
     (`reasoning_content`), prompt caching live, model id case-insensitive.
4. **`utils.py` shipped `moonshotai/kimi-k3` with an EMPTY efforts tuple `()`** — so `max` (and every
   effort) is rejected until you set it. Local edit: `(ReasoningEffort.HIGH, ReasoningEffort.MAX)` to
   match the endpoint's advertised effort set {low, high, max}.
5. **Gateway allowlists:** add `moonshotai/kimi-k3` to `background_agents.allowed_models` (the product
   ReviewHog sandboxes route through — probe `localhost:3308/background_agents/v1/models`) and, for a
   direct-call smoke, `review_hog.allowed_models`. Kimi is **not** in `RESTRICTED_MODEL_PRODUCTS`
   (unlike GLM's flash), so no restricted-products edit is needed. The `tasks-kimi-k3` access flag is
   bypassed locally by the gateway's DEBUG mode (`dependencies.py`), so no flag flip is needed for a
   local run.
6. **Kimi K3 is priced Sonnet/Opus-class** ($3/M in, $15/M out, $0.30/M cache read — gateway cost
   bridge), ~20-30× GLM 5.3 Flash. It is a premium model, not a flash model; read its results against
   the premium pins (Sol reviewer / Opus validator), and budget the runs accordingly (~$250-350 for 4).

## V-arm reviewer effort (comparability caveat — bit us here)

7. **A codex reviewer built through the local overlay runs at `low`, NOT the pinned `xhigh` — but this
   is LOCAL-ONLY (a stale monorepo), NOT a prod bug.** Because kimi-k3 is not in the published npm
   `@posthog/agent`, the V arm must build the agent from the local monorepo overlay (FINDINGS 1). That
   local checkout is **stale**: HEAD is `a4c32dfdc` dated **2026-08-01**, predating the codex-effort fix
   (#88893) that landed ~**2026-08-26**. So the locally-built agent lacks the fix and its Sol reviewer
   runs at codex's default (`low`). GLM (08-31) used the _released_ npm agent, which already had the fix,
   so its Sol ran at `xhigh`.
   **Prod is healthy — verified, not assumed.** Prod ReviewHog Sol reviewer `$ai_effort` (project 2,
   last 21 days): `xhigh` 118,870 calls latest 2026-09-01 (ongoing) vs `low` 60,279 calls that stopped
   2026-08-26 — i.e. prod ran low until the fix landed, then flipped to xhigh and stayed there. So **no
   `FIX_XHIGH.md` is warranted**; the fix is already in prod.
   Confirmed real locally, not a telemetry mislabel: Kafka `$ai_effort=low` **and** Sol review
   cost/volume collapsed ($3.33 / 8 findings vs the released agent's Sol@xhigh ~$27 / ~22). Consequence
   for this experiment: the V-arm finding set is smaller/weaker than the 08-26 Sol@xhigh controls, so
   Kimi-validator precision/recall are not directly comparable to them (coverage + keep/drop behavior
   still are). The claude adapter is unaffected — the Kimi validator ran at `max` correctly (V1), as did
   the Kimi reviewer in R1/R2/R3.
   **How to make Sol run at `xhigh` locally (the tested fix).** Root cause (full write-up in
   `../2026-08-validator-model-sol/FINAL_REPORT.md` "The effort pin never reached Codex"): the Codex
   adapter sends a per-turn `collaborationMode` whose `settings` carry only `{ model }`, and Codex applies
   the separate `effort` param only when no collaboration mode is sent — so every turn falls back to the
   model's catalog default (`low` for `gpt-5.6-sol`, `medium` for terra/luna). The claude adapter passes
   effort through session meta and is unaffected (so Kimi@max is fine). #88893 fixes it upstream with one
   line: put `reasoning_effort` into that settings object.
   The `Dockerfile.sandbox-base` sed the sol experiment used patches the installed npm agent, which the
   overlay REPLACES, so it does nothing for a Kimi run. Patch the overlay source instead, at
   `packages/agent/src/adapters/codex-app-server/session-config.ts` under the monorepo root (verified
   here at `session-config.ts:371`). In `collaborationModeForTurn()`, add the effort to the settings:

   ```ts
   // was:  settings: { model: this._model }
   settings: { model: this._model, reasoning_effort: this._effort }
   ```

   Then rebuild with `pnpm --filter @posthog/agent build` (the same build the overlay needs for kimi,
   FINDINGS 1). Verify on the first Codex call via `kafka_ai_usage.py`: the effort must read `xhigh`,
   and Sol's review plus blind-spot cost and volume should jump to ~$26 / ~22 findings (vs low's
   ~$3-6 / 8-11). The clean alternative is to update the monorepo past 2026-08-26 for #88893 itself
   (git pull, pnpm install, rebuild), preserving the local gateway edit and re-adding the kimi models
   entry. Either touches the Desktop monorepo, so it is a deliberate operator step, not an experiment
   default.

## Worker-churn discipline (cost us a smoke here)

8. **A `.py` write under `products/` restarts the temporal worker (nodemon), and the Modal image
   build rewrites `products/posthog_ai/dist/skills/*.py`, so a cold build churns the worker
   repeatedly** (GLM's FINDINGS trap 7 — up to ~27 restarts, wedging the workflow poller). The first
   smoke here was launched right after editing `utils.py` + writing the smoke script, and the churn
   during its cold build left the workflow signalling `workflow execution already completed`.
   Remedies: make all harness `.py` edits **between runs, never mid-flight**, batch them, and after a
   cold build restart the worker once (phrocs `toggle temporal-worker` twice, or the user does it) to
   get a clean poller. In-flight `MultiTurnSession.start` polls ride through a restart.

## Validator session reliability

9. **A Kimi validator's per-chunk session can die and fall back to `claude-opus-4-8`, silently
   contaminating the verdict.** In V2, chunk c4's Kimi validation session made 4 no-op calls ($0.00),
   then the agent-server fell back to its default model (`claude-opus-4-8`, 9 real calls, $1.79) to
   finish the chunk — so c4's 1 finding got an **Opus** verdict, not Kimi. This mirrors GLM V2's c2
   session death, except the fallback here produced a real (Opus) verdict instead of a no-verdict
   hole. Consequence: a "Kimi validator" run can carry non-Kimi verdicts on the chunks where Kimi's
   session failed, and a "no verdict hole" can be the fallback rescuing it rather than Kimi's own
   coverage. Always break the validation effort/model guard down **per chunk** (`validation-cN`) and
   check for `claude-opus-4-8` rows — not just the stage-family total. V1 was all-Kimi (clean); V2 was
   10/11 Kimi + 1 Opus.

## Standing rules carried over (still true)

- NEVER write a `.py` under `products/` while a run is in flight.
- ngrok can only be (re)started by the user; three tunnels needed (django/gateway/mcp).
- `MAX_CONCURRENT_SANDBOXES = 4` for comparability; Codex retry patch for the Sol reviewer arm.
- Between runs delete ONLY the PR 75215 report row, never a global wipe.
- No publish, ever, on experiment runs (`run_review` without `--publish`).
- Local `$ai_generation` ingestion is down; cost/effort ground truth = the sibling experiment's
  `scripts/kafka_ai_usage.py` (Kafka topic `events_plugin_ingestion_ai`).
