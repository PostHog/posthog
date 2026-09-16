# PLAN — Flash mode (GLM 5.3 Flash in the reviewer and validator seats)

**Question:** is a cheap "Flash" review, the existing pipeline with `zai-org/glm-5.3-flash` @ `high` in both
sandbox seats, worth running on every PR the way Greptile and CodeRabbit are, with the full Sol/Opus review kept
for the PRs that matter? The 2026-08 experiment (`../2026-08-model-glm53-flash/`) measured GLM against the prod
pins on one frozen PR; this one ships Flash as a run mode and measures it on ~100 real PRs by hand.

## Decisions (grilled 2026-09-16)

1. **Shape:** the existing pipeline, unchanged. Only the reviewer arm (perspectives + blind-spot sweep) and the
   validator run on GLM. Chunking, perspective selection, and dedup stay on the Sonnet one-shots. No sandbox-free
   one-shot review (rejected: it is a different product, not a cheaper version of this one).
2. **Model:** `zai-org/glm-5.3-flash` @ `high` in both seats (the GLM family only exposes `high` and `max`; the
   August runs used `max`). One shared arm constant, `FLASH_ARM` in `reviewer/constants.py`.
3. **Skill delivery: the pinned skill body is pasted into the prompt for Flash turns** (`skill_body` on
   `build_review_prompt` / `build_validation_prompt`, loaded by `load_skill_body`; the templates branch on it).
   The first plan kept the MCP pull and checked it in the local run; the August finding held (L3 below: every GLM
   sandbox searched for `skill-get`, found only `exec`, and reviewed blind), so the agreed fallback is built. Full
   turns still pull over MCP, unchanged.
4. **A per-run switch, not a tier.** The UI trigger sends `run_mode=flash`; the workflow input carries
   `review_mode`; the review and validation activities pick their arm by it. The PR's stored tier and arm are
   untouched, so a later normal trigger runs a normal review.
5. **One review per commit, whichever came first.** The existing join-on-running and already-reviewed rules cover
   Flash in both directions. The per-commit reviewer-result cache is stamped with the model that wrote it and only
   reused by the same model, so a full review after an empty Flash run at the same commit cannot silently reuse
   GLM's results and skip Sol.
6. **Trigger:** the "Review in Flash mode" item in the Code review scene's split button only. No label, inbox, or
   CLI variant (the MCP trigger tool shares the endpoint and inherits the choice).
7. **Prefix:** every GitHub message a Flash run writes starts with `FLASH MODE` + newline: the status comment
   (all edits), the one-time promo comment, the review body, and every inline finding comment.
8. **Never writes code:** the resolution stage is off for Flash, whatever the user's `resolve_comments` setting
   says. The trigger pins it off and the workflow refuses the dispatch for a flash turn.
9. **Telemetry:** `review_mode` on the started / completed / failed events; the reviewer and validator model
   properties come from the same mode-aware helpers the pipeline uses. Nothing stored on the report row. The
   per-finding outcome event (classified hours later, without the turn's mode) is left alone.
10. **Prod plumbing:** GLM 5.3 Flash added to the worker's `review_hog` scoped-token allowlist
    (`products/tasks/backend/temporal/process_task/ai_gateway_token.py`) AND to the Python gateway's
    `background_agents` allowlist (the mint-failure fallback path; a frozen service, justified as an active-caller
    fallback).

## Checks before the 100 PRs

1. **Local run (DB-only):** start the flash workflow with publishing off against the frozen PR 75215 and confirm in
   the agent log (`task_run.log_url`) that every GLM unit fetched its skill (`skill-get` / `exec skill get` call
   before analysis). If it did not, switch to inline skill delivery before any prod run. **Outcome: it did not
   (L3), inline delivery built; L4 re-checks that the inline body is in the prompt and the run completes.**
2. **First prod Flash run:** confirm the Go ai-gateway actually serves `zai-org/glm-5.3-flash` in prod (Baseten
   host wired) — a served-but-unpinned model is denied with no fallback, and an unserved entry is dropped from
   the token pin by a current gateway binary or fails the whole mint on an older one (which then falls back to
   the Python gateway, where the patched `background_agents` allowlist takes over). Watch `AI_GATEWAY_TOKEN_MINTS`
   and the first unit's `$ai_model`.

## Run log

### L1 — local DB-only flash run (2026-09-16, started 18:16:38 UTC)

- Started from a Django shell (`execute_review_pr_workflow(..., publish=False, review_mode="flash")`, team 1 / user 1 /
  acting user 1) against PR 75215 at `a7fb363bef69` (the PR is closed since August; its branch still exists and the
  direct workflow path has no open-state gate). Report `01a0ab6f-6f76-7f26-9e76-2c4397788d61`. Stored arm untouched
  (`review_tier=human`, `review_model=gpt-5.6-sol`) — the per-run switch leaves the row alone as designed.
- Chunking: 2 chunks (unpinned, unlike the August clean room), selection persisted, 6 review units
  (3 perspectives × 2 chunks) started 18:19:29 — every `TaskRun.state` reads `claude / zai-org/glm-5.3-flash / high`.
- Ops: the worker in this stack does not hot-reload `.py` edits (restart via phrocs before a run); the local
  llm-gateway needed a restart to pick up the `background_agents` allowlist; `create_sandbox_for_repository` ran with
  `image_source=modal_local_build`, i.e. a cold local image build (~20 min) before the agents started.
- **FAILED at agent start, both parent attempts (30 sandboxes, zero LLM calls):** every sandbox died with
  `POSTHOG_CODE_REASONING_EFFORT 'high' is not supported for claude model 'zai-org/glm-5.3-flash'`. Cause: the local
  image was built from `LOCAL_POSTHOG_CODE_MONOREPO_ROOT=~/Documents/Code/code`, the pre-migration agent checkout
  (last commit 2026-08-01), whose registry predates GLM 5.3 Flash. Not a prod problem: the published
  `@posthog/agent@2.4.187` (2026-09-16) lists `["high", "max"]` for the model, and so does this repo's generated
  catalog. Fix for the local run: the `.env` line is commented out (published agent in the local image), the
  workflow was terminated, the worker restarted, and the run relaunched as L2.

### L2 — same failure (started 18:53:57 UTC): the stack's worker keeps its environment

- Identical `'high' is not supported` on every sandbox, 6/6 units failed → failure floor → run failed. `hogli start`
  loads `.env` once into the phrocs daemon and every process restart inherits that snapshot, so commenting the line
  out and toggling the worker changed nothing. (The stale checkout has built `dist/` dirs, so the local packages
  really were baked.)

### L3 — own worker without the variable (started ~19:35 UTC)

- The phrocs `temporal-worker` is stopped for the duration and an identical worker (the `bin/mprocs.yaml` command,
  `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` unset) runs from the session scratchpad (`run3_chain.sh`, log
  `own_worker.log`); the phrocs worker goes back on afterwards. The image now installs the published agent.
- **Started 19:22:27 UTC; agents ran.** 2 live chunks, 6 wave units done in 7–13 min each (all on
  `claude / zai-org/glm-5.3-flash / high`), 2 blind-spot units 12–15 min, dedup → 23 findings, GLM validation from
  19:54.
- **Skill fetch: NO.** Every GLM unit ran `ToolSearch("select:mcp__posthog__skill-get")`, got no match (the
  `posthog` MCP is exec-only for non-allowlisted clients; a `posthog-local` MCP entry from
  `POSTHOG_DESKTOP_SKILLS=local` was unreachable from Modal), never called `exec`, and reviewed blind — the August
  finding holds. Tools it did use: `Execute command`, `Read File`, `ToolSearch`. → inline skill delivery built
  (decision 3), exercised by the next run.
- **GLM validator warm-session death (the August V2 signature, now explained):** `validation-c1` failed on a
  follow-up turn with a gateway 400, `messages.17: role 'system' must precede an 'assistant' message or end the
array` — the claude adapter's follow-up turn puts a system-role message mid-array, which the GLM (Baseten)
  Messages surface rejects. The chunk retried with skip-resume (`VALIDATION_MAX_ATTEMPTS = 2`); a repeat on the
  final attempt skips the issue, i.e. a coverage hole. Open question for the 100-PR test: how often it recurs, and
  whether the flash validator should run one session per issue instead of a warm session.
- **Done 20:57:09 UTC, wall 5682 s (95 min), DB-only, no cost figures** (the local gateway had
  `LLM_GATEWAY_POSTHOG_AI_LANE_CAPTURE=false`, so no `$ai_generation` events landed anywhere). Funnel: raw 25
  (wave 21 + blind-spot 4) → dedup 23 → **valid 0**; both validation chunks died once on the 400 above, retried, and
  every finding got a verdict (23/23, no hole). Unit times on GLM @ high: wave 6.6–13.1 min, blind-spot 11.6–14.9,
  validation-c1 retry 8.5 min for its share, validation-c2 retry **51 min** (one warm session grinding through 14
  findings; the validator is the slow seat). Both seats ran blind (no skill), so this is a mechanics run, not a
  quality number.
