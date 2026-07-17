# Prompt caching: cross-sandbox cache reuse — mechanics and program state

**Status (2026-07-06 EOD): investigation complete, measurement instrument shipped, and the warm-up+fork build is the active next experiment** (locked constraints and candidate #8 in `CANDIDATES.md`; practical how-to in `HARNESS.md`).
This doc is the consolidated reference for the caching mechanics, what is measured as true, and what must be fixed for forking to work.
Originally written 2026-07-03 as an investigation report; consolidated 2026-07-06 (the layered update history lives in git and in `PLAN.md`'s run log).

## The idea

ReviewHog's review units each re-learn the same PR: every unit (N perspectives + blind-spot per chunk, validation) is a fresh Task → fresh Modal/Docker sandbox → fresh agent-server → fresh Claude Code conversation (see `ARCHITECTURE.md`).
The fix (locked 2026-07-06): after chunking, ONE neutral warm-up agent per chunk reads and understands the chunk and its related codespace (no judgments, no code).
Its session transcript is persisted, and every perspective forks from it, inheriting the investigation from Anthropic's server-side cache at 0.1× — so perspectives should not need to re-investigate, while keeping full tools and freedom (quality is the moat).
Value scales with perspective count, which is user-extensible and unbounded (could be 20), so nothing gates the build on measured overlap; measurement happens post-build (follower turns/cost vs control + quality parity).

## How Anthropic caching works (documented facts that matter here)

- **Prefix match:** cache key = exact bytes of `tools` → `system` → `messages` up to a `cache_control` breakpoint. "Cache hits require 100% identical prompt segments." Model is part of the key.
- **Scope:** caches are isolated per organization and (since Feb 2026) per workspace. All ReviewHog sandboxes route through the PostHog LLM gateway into ONE Anthropic workspace, so they already share a namespace: "N sandboxes from one cache" just means byte-identical prefixes within TTL. Confirmed live twice (smoke run 2 and the PR #68749 publish run: 2 of 3 wave units read the leader's identical 27,618-token [tools+preset] segment at turn 1).
- **TTL:** 5 min default, refreshed free on every read (sliding); 1h costs 2× on writes. **Our sandbox path runs on 5m** (proven by billing, by observed >5m expiries, and by the CLI's auth-gated TTL logic); `ENABLE_PROMPT_CACHING_1H=1` in a sandbox's env enforces 1h unconditionally — full detail in `HARNESS.md` "1h cache TTL". Writes 1.25× (5m), reads 0.1×.
- **Concurrency:** an entry becomes readable only after the writer's response begins — the warm-up must complete before fan-out (a stage boundary satisfies this; followers then read in parallel, and their reads keep the entry alive continuously while any of them is active).
- **Placement:** breakpoints are set by whoever builds the request — here the Claude Code CLI (spawned by the agent SDK inside agent-server), not ReviewHog. It auto-places breakpoints (system, recent messages).

## What is measured as true (sonnet-5 era, cache-aware)

Instrument: `eval/scripts/dump_result.py` (cache-aware split, validated Δ +0.0% against the gateway's LiteLLM costs on every bucket and side — `runs/gate0-run1-pr68749-publish.md`).

- **Naive token math overstates true cost ~4.8×** (PR #68749 run: naive $47.52 vs true $9.90) — never gate a decision on undifferentiated `$ai_input_tokens`.
- **Bucket split of a real run:** ~43% cache reads / 33% cache writes / 19% output / 5% fresh input. Cache reads are the largest true-cost bucket.
- **Cost is turn-dominated, not payload-dominated** (median ~15 turns/unit; each turn re-reads the whole growing prefix and emits output). The fork's saving mechanism is turn elimination: followers skip the investigation turns.
- **Cross-sandbox sharing is partially live already:** the [tools+preset] prefix (27.6K tokens) shares across units when timing allows; the per-task `Task-Id` append poisons everything after it (V1 below), so the share is worth cents until T2 lands.
- **TTL busts are real:** wave→blind-spot gaps of 5m52s–12.5min caused full prefix rewrites in both observed runs. Fresh sandbox setup alone (provision+boot+clone+checkout) measured ~4–6 min, so follower scheduling must overlap provisioning with the warm-up run, or selectively use the 1h TTL.
- Historical (opus-era, provenance only): ~$24–28/run with review+blind-spot ≈ 80% of it; the archived per-arm events died in the 2026-07-06 DB nuke, so sonnet-era baselines accumulate from fresh runs.

## What must be fixed for forking — the violations

| #   | Violation                                                                                                                                                                                                                                                                                      | Where                                                                                     | Fix                                                                                                                                                                            |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| V1  | `Task-Id: ${taskId}` interpolated into the system-prompt append of every task → prefixes diverge before messages start.                                                                                                                                                                        | code repo, `packages/agent/src/server/agent-server.ts:2638` (`buildCloudSystemPrompt`)    | De-interpolate — safe: the git tool injects the trailer deterministically from config (`packages/git/src/trailers.ts`), the prompt line is informational. See `HARNESS.md` T2. |
| V2  | Claude Code preset injects dynamic sections (cwd, git status, date) into the system prompt; the SDK's `excludeDynamicSections: true` fix is unused.                                                                                                                                            | code repo, `packages/agent/src/adapters/claude/session/options.ts:93–123`; SDK `sdk.d.ts` | One option flag; must also cover the cloud `params.systemPrompt` shape. See `HARNESS.md` T2.                                                                                   |
| V3  | The raw session JSONL (`~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl`) is never uploaded; the existing ACP-log reconstruction is lossy at every step (fresh UUIDs, flattened tool results, truncation, turn-dropping) → replayed bytes ≠ original → guaranteed miss. Never seed from it. | code repo, `packages/agent/src/adapters/claude/session/jsonl-hydration.ts`                | Upload raw JSONL at task end; followers download to the identical deterministic cwd path and fork (`resumeSession({resume, forkSession: true})`). See `HARNESS.md` T3.         |
| V0  | No warm-up stage exists in ReviewHog's workflow — nothing runs before the per-chunk fan-out.                                                                                                                                                                                                   | this repo, `products/review_hog/backend/temporal/workflow.py`                             | The build itself.                                                                                                                                                              |

**Already satisfied:** one cache namespace via the gateway; model pinning (`REVIEW_MODEL`); fork/resume/replay primitives; deterministic sandbox cwd.

**Design caveats:** a follower's appended user message strips prior thinking blocks server-side, so the warm-up must end with a settling user turn that writes the stripped-form cache once (fidelity checks must compare against the stripped form — `CANDIDATES.md` #8); the gateway silently maps non-allowlisted models to a default; the unconditional Bedrock-fallback header can reroute individual requests to Bedrock's separate cache namespace on Anthropic 5xx (occasional miss, gate it off for experiment runs); the sandbox checkout uses the PR branch ref, not the pinned `head_sha` — SHA-pinning is a correctness fix the fork also wants (byte-identical git state across warm-up and followers).

## Precedents and risks

- **C5 warm per-perspective sessions (built, rejected):** sequential chunks in one session anchored later turns near-silent — half the "saving" was suppressed findings. The fork differs: the shared prefix contains no findings or judgments, only neutral reads, and each perspective branches into its own isolated session. The residual risk is curation bias (the warm-up's reading choices framing all followers), so the per-perspective finding-count distribution + yardstick parity on frozen PR #62096 is the standing quality gate.
- **TTL expiry** on stragglers (semaphore batching at N>10, retries, the post-wave blind-spot): design fan-out for the 5m sliding window (immediate scheduling, overlapped provisioning), with per-unit `ENABLE_PROMPT_CACHING_1H` as cheap insurance (~+$0.2/chunk on the warm-up unit).
- **Validators keep fresh sessions** — never seeded from review or warm-up transcripts.

## Program state (2026-07-06 EOD)

- **Shipped:** the cache-aware metrology (`dump_result.py`), validated live; the probe-era "+28% gateway-vs-list discrepancy" resolved as a measurement artifact.
- **Dropped/demoted:** the pre-build overlap gate (Spike 3) and the standalone gateway probe (Spike 1) — the fork build's own mechanics gate (follower turn-1 cache reads ≈ warm-up transcript size) subsumes the substrate check. The T1 rewrite-bug ticket is pending re-quantification on fresh runs (expected: demote; crude post-flip probe found ~$0.005/run).
- **Next experiment:** the warm-up+fork build — T2+T3 patched locally in the PostHog Code checkout (approved working mode, `HARNESS.md`), Spike 2 (stripped-form fork fidelity) as first milestone, then the ReviewHog warm-up stage behind an on/off constant, then 2 arm vs 2 control runs on frozen PR #62096. Harness fixes ship upstream only after the experiment proves value.

## Key files

- this repo: `products/review_hog/backend/temporal/workflow.py` (fan-out; where the warm-up slots in), `backend/reviewer/sandbox/executor.py` (prompt→description; `MultiTurnSession`), `backend/reviewer/constants.py` (`REVIEW_MODEL`, on/off knobs), `products/tasks/backend/temporal/process_task/activities/provision_sandbox.py` (sandbox env injection, incl. `ENABLE_PROMPT_CACHING_1H`), `get_sandbox_for_repository.py` (branch-ref checkout to SHA-pin), `eval/scripts/dump_result.py` (validated cost instrument)
- code repo (PostHog Code): `packages/agent/src/server/agent-server.ts` (`buildCloudSystemPrompt`, Task-Id append), `packages/agent/src/adapters/claude/session/options.ts` (systemPrompt build; Bedrock header), `packages/agent/src/adapters/claude/session/jsonl-hydration.ts` (raw JSONL path; lossy hydration to avoid)

Line references drift; function names are the stable anchors. Exact patch surfaces with line numbers: `HARNESS.md`.
