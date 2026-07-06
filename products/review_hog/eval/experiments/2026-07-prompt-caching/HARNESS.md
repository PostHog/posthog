# Harness (PostHog Code repo) — local patch, build, and verify loop (recon 2026-07-06)

> Companion to `CANDIDATES.md` #8 (warm-up+fork flagship) and `PLAN.md`. The user approved local two-repo
> experimentation 2026-07-06: T2/T3-class harness changes are patched in the local PostHog Code checkout at
> `/Users/woutut/Documents/Code/code` for experiments; upstreaming is a later, separate decision.
> All file:line anchors below are as of 2026-07-06 and will drift; function names are the stable anchors.

## How the agent reaches sandboxes (no Docker image in the code repo)

The artifact is the npm package `@posthog/agent` (bin `agent-server`, `packages/agent/package.json:92-94`),
built by tsup (bundles `@posthog/shared`, `@posthog/git`, `@posthog/enricher`; also vendors the Claude CLI binary
into `dist/claude-cli/`). CI auto-tags `agent-v*` on main pushes and publishes to npm; the sandbox base image in
THIS repo (`products/tasks/backend/sandbox/images/Dockerfile.sandbox-base:109-115`) does
`npm install @posthog/agent@latest` at image build, and the workflow starts `./node_modules/.bin/agent-server --port 47821`.

## The local dev loop for a PATCHED agent (documented, already half-configured on this machine)

Source of truth: `docs/internal/sandboxes-setup-guide.md:190-256`.

1. `.env` already has `SANDBOX_PROVIDER=MODAL_DOCKER` (DEBUG-only Modal subclass, app names `posthog-sandbox-modal-docker-*`)
   and `SANDBOX_LLM_GATEWAY_URL=https://alexl-llmg.ngrok.dev` (ngrok tunnel to the local llm-gateway on :3308).
   **Missing piece: `LOCAL_POSTHOG_CODE_MONOREPO_ROOT=/Users/woutut/Documents/Code/code`** (documented in `.env.example:11-12`).
   With it set, sandboxes get the LOCAL agent build overlaid instead of the published package
   (Modal path: runtime overlay via `products/tasks/backend/logic/services/local_packages.py:42-77`, DEBUG-only,
   requires built `dist/` dirs; plain-Docker path: `Dockerfile.sandbox-local` builds `posthog-sandbox-base-local`
   by pnpm-packing the local packages, rebuilt every provision).
2. After editing agent code: `cd /Users/woutut/Documents/Code/code/packages/agent && pnpm build`,
   then **restart the temporal worker** — the build context is `lru_cache`d for the worker's lifetime
   (guide :255-256). The worker runs under nodemon watching `products/**/*.py`, so touching any watched .py file
   respawns it (never boot a second worker — port 8001 collision; see the e2e memory).
3. Run the standard e2e (`run_review --pr-url ... --team-id 1 --user-id 1`, no `--publish`), ngrok up.
4. Verify with the tripwire SQL below.

Housekeeping: while `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` is set, EVERY local sandbox run uses the local build
(which drifts from npm `@latest`) — set it for experiment sessions, remove it after, per the isolation working mode.

## T2 patch surface (cache-stable system prompt) — small, both sites verified

- **V1 — Task-Id de-interpolation is SAFE.** The `Task-Id: ${taskId}` line sits in the `signedCommitInstructions`
  template (`packages/agent/src/server/agent-server.ts:2655-2660`, `buildCloudSystemPrompt` at `:2587`).
  Decisive finding: **the trailer is injected deterministically by the git tool from config**, not by the model —
  `packages/git/src/trailers.ts:4-8` (`buildPostHogTrailers(taskId)`) applied in `signed-commit.ts:885,:1177` from
  `ctx.taskId`. The prompt line is purely informational, so it can become static text
  ("the tool appends Generated-By and Task-Id trailers automatically") with zero functional loss.
  Tests that will fail and must be updated with the patch: `agent-server.test.ts:1891-1892,:1901-1902,:1928-1929,:1967-1968`
  (assert `toContain("Task-Id: test-task-id")`).
  (Separate, unaffected: signal-report artefact attribution uses the `X-PostHog-Task-Id` HTTP header, and an older
  workspace-server copy at `packages/workspace-server/src/services/agent/agent.ts:589-601` instructs the model to
  hand-write trailers — desktop path, out of scope.)
- **V2 — one-flag change, currently untested territory.** `buildSystemPrompt` (`packages/agent/src/adapters/claude/session/options.ts:94-124`)
  builds `{type: "preset", preset: "claude_code", append: ...}`; the pinned SDK (`@anthropic-ai/claude-agent-sdk` 0.3.170)
  supports `excludeDynamicSections?: boolean` (`sdk.d.ts:1985`) and the repo never sets it. Cloud sessions pass the
  agent-server's merged prompt via `params.systemPrompt` (`options.ts:433`), so the patch must cover that shape too,
  not just the default. NO existing test inspects `options.systemPrompt` — add one with the patch.
- **Bedrock fallback header** (`options.ts:161-162`): unconditional `x-posthog-use-bedrock-fallback: true` on every
  session. On Anthropic 5xx a request reroutes to Bedrock's separate cache namespace (occasional miss, plus a
  detector confound for the T1 rewrite signature). For experiment runs, consider gating it off; `options.test.ts:196`
  asserts the exact header string and will need updating if touched.

## T3 patch surface (raw-JSONL persistence + fork-seed)

- Raw transcript path in sandbox: `${CLAUDE_CONFIG_DIR || ~/.claude}/projects/${encodeCwdToProjectKey(cwd)}/${sessionId}.jsonl`
  (`jsonl-hydration.ts:90-107`); cwd = `repositoryPath ?? "/tmp/workspace"` (`agent-server.ts:1281`) — deterministic
  across sandboxes of the same repo, exactly what fork-seeding needs.
- **Nothing uploads it today.** `cleanupSession` (`agent-server.ts:3350-3400`) persists only the git checkpoint and the
  ACP log flush. The ACP log is uploaded server-side via `TaskRun.append_log`
  (posthog repo `products/tasks/backend/models.py:1178-1212`, key `tasks/logs/team_{}/task_{}/run_{}.jsonl`,
  `OBJECT_STORAGE_*` bucket, ttl 30d) — and it is lossy at every step (fresh UUIDs `jsonl-hydration.ts:449,:513,:552`,
  fabricated msg ids/timestamps/zeroed usage `:344-352,:425-429,:534-539`, `JSON.stringify` tool results `:553-556`,
  10K-char truncation `:55-68`, turn-dropping `:272-301`) — confirming the investigation's V3: never seed from it.
- Persist: read the raw JSONL in `cleanupSession` (+ crash path near `:756`) and upload — simplest via the existing
  artifact uploader (`posthog-api.ts:231 uploadTaskArtifacts`, reserved name like `transcript/<sessionId>.jsonl`);
  posthog side may need nothing (artifact endpoint exists) or a `transcript_url` sibling to `log_url`.
- Seed: new step 0 in `hydrateSessionJsonl` (`:654`, between the file-exists check `:668-684` and ACP reconstruction
  `:689`): download the referenced run's raw JSONL to `getSessionJsonlPath`, sanitize, done. Resume trigger already
  flows (`POSTHOG_RESUME_RUN_ID`, `provision_sandbox.py:253-256` -> `autoInitializeSession` `agent-server.ts:2442-2450`).
- Fork wiring already exists end to end: capabilities advertise fork/resume (`claude-agent.ts:295-305`),
  `unstable_forkSession` -> `createSession({resume, forkSession: true})` (`:347-359`, new uuidv7 on fork `:1654-1663`),
  `--replay-user-messages` always passed (`options.ts:443-446`). A seeded raw JSONL under the prior sessionId is
  exactly what this path consumes.
- Remember from CANDIDATES #8: the warm-up needs a final settling user turn (thinking-block stripping), and Spike 2's
  gate is against the stripped-form prefix.

## Verification — the tripwire

- The gateway captures `$ai_generation` with `$ai_cache_read_input_tokens` / `$ai_cache_creation_input_tokens`
  (emitted only when present -> treat missing as 0; capture site `services/llm-gateway/src/llm_gateway/callbacks/posthog.py:232-237`).
  Local e2e demonstrably lands these in local ClickHouse (all prior eval rounds' dumps).
- Unit attribution: sandbox units carry `task_title` = `[sandbox_prompt:issues-review-p{pass}-c{chunk}] ...` /
  `[sandbox_prompt:blind-spots-c{chunk}] ...` plus a unique `task_run_id` (one TaskRun = one sandbox = one conversation).
  Turn 1 = first `$ai_generation` per `task_run_id` by timestamp. Turn-1 `cache_read > 0` on a fresh sandbox can only
  come from ANOTHER process's write: that is the cross-sandbox signal.
- The query (run via `sync_execute` in `manage.py shell`, dump_result.py pattern):

```sql
WITH unit_turn1 AS (
    SELECT
        JSONExtractString(properties, 'task_run_id') AS task_run_id,
        extract(any(JSONExtractString(properties, 'task_title')), '\\[sandbox_prompt:([a-z0-9_-]+)\\]') AS step_name,
        count() AS gens,
        argMin(toFloat64OrZero(JSONExtractString(properties, '$ai_cache_read_input_tokens')), timestamp) AS turn1_cache_read,
        argMin(toFloat64OrZero(JSONExtractString(properties, '$ai_cache_creation_input_tokens')), timestamp) AS turn1_cache_creation
    FROM events
    WHERE event = '$ai_generation'
      AND timestamp >= %(run_start)s AND timestamp < %(run_end)s
      AND (JSONExtractString(properties, 'task_title') LIKE '[sandbox_prompt:issues-review-%'
           OR JSONExtractString(properties, 'task_title') LIKE '[sandbox_prompt:blind-spots-%')
      AND JSONExtractString(properties, 'task_run_id') != ''
    GROUP BY task_run_id
)
SELECT
    multiIf(step_name LIKE 'blind-spots%', 'blind-spot', 'perspective') AS unit_kind,
    count() AS units,
    medianExact(turn1_cache_read) AS turn1_cache_read_median,
    countIf(turn1_cache_read > 0) AS units_with_turn1_hit,
    medianExact(turn1_cache_creation) AS turn1_cache_creation_median
FROM unit_turn1
GROUP BY unit_kind WITH TOTALS ORDER BY unit_kind
```

- Note: sandbox units go through the harness's gateway product (`background_agents`) — do NOT filter on
  `ai_product = 'review_hog'` for sandbox units (that only tags the one-shot chunking/dedup calls).
- **Report the DISTRIBUTION (units_with_turn1_hit + per-unit values), never just the median** — see below.

## Smoke run 2 result (2026-07-06, live PR #68735, UNPATCHED local main) — the baseline is NOT zero anymore

| unit                         | first gen | t1 cache_read | t1 cache_write |
| ---------------------------- | --------- | ------------- | -------------- |
| issues-review-p2-c1 (leader) | 18:34:54  | 0             | 59,423         |
| issues-review-p3-c1          | +4s       | **27,618**    | 31,801         |
| issues-review-p1-c1          | +50s      | **27,618**    | 31,806         |
| blind-spots-c1               | +10min    | 0             | 62,473         |

Reading of the evidence:

1. **Cross-sandbox cache sharing is partially LIVE on the current agent/SDK.** Two fresh sandboxes read an identical
   27,618-token segment written by the leader: the [tools + system-preset-block] prefix, shared because natural
   provisioning jitter (4s, 50s) made p2 a de-facto leader. The `Task-Id` append (V1) poisons only the bytes AFTER it —
   the preset block ahead of it shares fine. The 2026-07-03 investigation's "turn-1 cache_read median = 0" is **stale**
   on the current build (and note: today's median would be 27,618 — hence distributions, not medians).
2. **This is production-grade evidence for Spike 1's cross-client question**: two distinct sandbox processes shared one
   Anthropic cache through the full stack (Modal sandbox -> ngrok -> local llm-gateway). The controlled probe (#2)
   remains useful for the allowlist/TTL/rate arms but its existential question has a live PASS.
3. **The wave->blind-spot TTL gap is real and observed**: 10 minutes on a SINGLE-CHUNK PR (sandbox provision + boot +
   clone + checkout eat the 5-min sliding TTL), so the blind-spot rewrote everything. Any fork design must sequence
   per-chunk and re-check warmth (exactly fork-sizing spike gate (b)).
4. **What this does NOT change: T2 is still the fork's hard prerequisite.** A follower forking the warm-up's transcript
   needs byte-identity through the ENTIRE prefix (system append included); per-task `Task-Id` still breaks that at the
   append. The ~27.6K preset share is worth only cents per unit ($/follower ≈ 27.6K x ~$2.3/M delta ≈ $0.06) — the fork's
   value is the ~70K transcript read, which stays blocked on T2+T3.
5. Post-T2 expectation: turn-1 reads extend to [tools + preset + append]; post-T3 fork: turn-1 reads ~= the warm-up's
   stripped-form transcript size.

## Environment checklist (state on 2026-07-06)

- Dev stack: UP (llm-gateway :3308, temporal-worker under nodemon, backend). Ngrok: UP (`https://alexl-llmg.ngrok.dev` -> 200).
- `.env`: `SANDBOX_PROVIDER=MODAL_DOCKER` + `SANDBOX_LLM_GATEWAY_URL` set; `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` added 2026-07-06
  (line 212) and picked up after a full stack restart — the flox hook sources `.env` at ACTIVATION, so a nodemon respawn or
  phrocs process toggle does NOT re-read it; only a stack restart (or an export in the launching shell) does.
- Code repo: clean on `main`, agent built via `pnpm turbo build --filter=@posthog/agent...` (~10s), SDK 0.3.170 pinned.

## Smoke-run lessons (2026-07-06)

- **The version fingerprint is trustworthy and in-band.** `agentVersion` is broadcast in the `run_started` notification
  (`agent-server.ts:1387`) and lands in the TaskRun log (object storage, readable mid-run). Local build reports `0.0.0-dev`
  (INLINED into `dist/server/bin.cjs` at build time — verified, no runtime package.json read); published npm reports its
  real version (2.3.1272 on 2026-07-06). Check this on EVERY patched run; the Modal overlay
  (`modal_sandbox.py: image.add_local_dir(dist -> /scripts/node_modules/@posthog/<pkg>/dist)`) is silent on success and
  only warns on missing `dist/` dirs, so worker logs alone prove nothing. The overlay swaps `dist/` of agent+shared+git
  over the published install; transitive deps resolve from the baked node_modules tree (watch for runtime-dep drift
  between local main and the published package.json when they diverge for long).
- **Setup progress notifications (clone/checkout) precede agent-server boot** — a unit that dies in `step: checkout`
  never ran the agent at all; do not read setup failures as build failures.
- **Smoke run 1 failed for an environmental reason**: sample PR #63625 merged 2026-07-03 and its branch was deleted;
  branch-ref checkout (the known unpinned-SHA issue) fails on merged-and-deleted PRs. RUN_LOG.md updated; use a live
  non-fork PR (or the still-open frozen eval PR #62096) for smokes.
- **Never edit `products/**/\*.py`while a run is in flight** (learned 2026-07-06 the expensive way): nodemon respawns
the temporal worker on any watched-file change, killing in-flight sandbox activities; repeated edits exhaust the
2-attempt retries and fail the whole`review-pr`workflow. Temporal then retries the workflow, and it RESUMES from
persisted (pass, chunk) results at the same head — the killed wave was not re-paid, only the unfinished blind-spot
re-ran. Sequence watched-file edits strictly before/after runs; check state with`temporal workflow list --address localhost:7233 -q "ExecutionStatus='Running'"`.
- **DB-nuke recovery for `run_review`**: team 1 / user 1 re-seed automatically, the GitHub integration row does NOT —
  the workflow fails fast on it. Restore in `manage.py shell`:
  `GitHubIntegration.integration_from_installation_id("143741024", team_id=1, created_by=User.objects.get(pk=1))`
  (the "posthog-local-dev" app installation persists on GitHub's side). A nuke also deletes archived `$ai_generation`
  events and ACP logs — plan measurement windows accordingly.
- **`run_review` stdout is block-buffered when piped** — the `ReviewHog ▶ starting` banner and the result line flush
  only at process exit. Watch live progress in the temporal-worker log (stage banners) or via `temporal workflow list`.
- **Tripwire reproduced on a full publish run** (PR #68749, 2026-07-06, single chunk): leader wrote 73.2K at turn 1;
  two followers read the identical 27,618-token [tools+preset] segment at +1s/+19s; the blind-spot fired +12.5 min
  after the wave and rewrote everything (TTL bust). Full table: `runs/gate0-run1-pr68749-publish.md` — the turn-1
  distribution is now a standing section of every `dump_result.py` dump.
