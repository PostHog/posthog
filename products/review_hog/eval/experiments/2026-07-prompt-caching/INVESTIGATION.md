# Prompt caching: cross-sandbox cache reuse — mechanics and program state

**Status (2026-07-07): the warm-up+fork build is LIVE with mechanics proven in the real pipeline** — T2/T3 patched locally, V0 built behind `WARMUP_FORK_ENABLED`, forked units read the shared warm-up prefix at 0.1× (5/6 wave followers + 1/3 blind-spots in arm smoke 2); the 2v2 eval is pending.
The experiment's own plan + run log: `../2026-07-warmup-fork/PLAN.md`.
This doc is the consolidated reference for the caching mechanics, what is measured as true, and the harness violations (now fixed locally).
Originally written 2026-07-03; consolidated 2026-07-06; mechanics facts extended 2026-07-07 from the build's measurements.

## The idea

ReviewHog's review units each re-learn the same PR: every unit (N perspectives + blind-spot per chunk, validation) is a fresh Task → fresh Modal/Docker sandbox → fresh agent-server → fresh Claude Code conversation (see `ARCHITECTURE.md`).
The fix (locked 2026-07-06): after chunking, ONE neutral warm-up agent per chunk reads and understands the chunk and its related codespace (no judgments, no code).
Its session transcript is persisted, and every perspective forks from it, inheriting the investigation from Anthropic's server-side cache at 0.1× — so perspectives should not need to re-investigate, while keeping full tools and freedom (quality is the moat).
Value scales with perspective count, which is user-extensible and unbounded (could be 20), so nothing gates the build on measured overlap; measurement happens post-build (follower turns/cost vs control + quality parity).

## How Anthropic caching works (documented facts that matter here)

- **Prefix match:** cache key = exact bytes of `tools` → `system` → `messages` up to a `cache_control` breakpoint. "Cache hits require 100% identical prompt segments." Model is part of the key.
- **Scope:** caches are isolated per organization and (since Feb 2026) per workspace. All ReviewHog sandboxes route through the PostHog LLM gateway into ONE Anthropic workspace, so they already share a namespace: "N sandboxes from one cache" just means byte-identical prefixes within TTL. Confirmed live twice (smoke run 2 and the PR #68749 publish run: 2 of 3 wave units read the leader's identical 27,618-token [tools+preset] segment at turn 1).
- **TTL:** 5 min default, refreshed free on every read (sliding); 1h costs 2× on writes. **Our sandbox path runs on 5m** (proven by billing, by observed >5m expiries, and by the CLI's auth-gated TTL logic); `ENABLE_PROMPT_CACHING_1H=1` in a sandbox's env enforces 1h unconditionally — full detail in `HARNESS.md` "1h cache TTL". Writes 1.25× (5m), reads 0.1×.
- **Concurrency:** an entry becomes readable only after the writer's response has STARTED — and TTFT on a ~100K-token write exceeds 30s, so concurrently-launched byte-identical requests collide into double-writes (harmless — each just pays the 1.25× write) unless the first one gets a head start (60s in the build, `FORK_LEADER_HEAD_START_SECONDS`). Once the leader's entry is readable, all later identical requests read it.
- **Placement / addressability:** breakpoints are set by whoever builds the request — here the Claude Code CLI, which auto-places them at message boundaries. **Entries are addressable only at message ends: a shared head inside one message shares NOTHING** (measured, arm smoke 1 — units whose first message ended with a unique perspective tail rewrote the entire shared span, 0 readers). Hence the build's two-turn fork: a byte-identical first turn establishes the shared entry; the divergent perspective prompt rides it as turn 2.
- **Storage dialect (measured, Spike 2):** the CLI saves sessions in a different byte form than it sends live (thinking blocks come back as placeholders, send-time-injected context differs) — a replayed session can never hit the live session's cache entries, but replay-vs-replay is byte-perfect to the token. Consequence: the shared cache key is the replay form; the S3 transcript artifact is the durable carrier; a TTL miss only re-pays the replay-span write (~$0.15-0.20), never breaks the fork.

## What is measured as true (sonnet-5 era, cache-aware)

Instrument: `eval/scripts/dump_result.py` (cache-aware split, validated Δ +0.0% against the gateway's LiteLLM costs on every bucket and side — `runs/gate0-run1-pr68749-publish.md`).

- **Naive token math overstates true cost ~4.8×** (PR #68749 run: naive $47.52 vs true $9.90) — never gate a decision on undifferentiated `$ai_input_tokens`.
- **Bucket split of a real run:** ~43% cache reads / 33% cache writes / 19% output / 5% fresh input. Cache reads are the largest true-cost bucket.
- **Cost is turn-dominated, not payload-dominated** (median ~15 turns/unit; each turn re-reads the whole growing prefix and emits output). The fork's saving mechanism is turn elimination: followers skip the investigation turns.
- **Cross-sandbox sharing is partially live already:** the [tools+preset] prefix (27.6K tokens) shares across units when timing allows; the per-task `Task-Id` append poisons everything after it (V1 below), so the share is worth cents until T2 lands.
- **TTL busts are real:** wave→blind-spot gaps of 5m52s–12.5min caused full prefix rewrites in both observed runs. Fresh sandbox setup alone (provision+boot+clone+checkout) measured ~4–6 min, so follower scheduling must overlap provisioning with the warm-up run, or selectively use the 1h TTL.
- Historical (opus-era, provenance only): ~$24–28/run with review+blind-spot ≈ 80% of it; the archived per-arm events died in the 2026-07-06 DB nuke, so sonnet-era baselines accumulate from fresh runs.

## The violations — ALL FIXED locally 2026-07-07 (patches in `../2026-07-warmup-fork/patches/`; upstreaming = a later decision)

| #   | Violation (historical)                                                                                                       | Fix as shipped                                                                                                                                                                                                                                                                     |
| --- | ---------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| V1  | `Task-Id: ${taskId}` interpolated into the system-prompt append → prefixes diverged before messages started.                 | De-interpolated to static text in `buildCloudSystemPrompt` (the git tool injects the real trailer from config).                                                                                                                                                                    |
| V2  | Claude Code preset injected dynamic sections (cwd, git status, date) into the system prompt.                                 | `excludeDynamicSections: true` in `buildSystemPrompt`, covering the cloud `params.systemPrompt` shape.                                                                                                                                                                             |
| V3  | The raw session JSONL was never uploaded; the ACP-log reconstruction is lossy → replayed bytes ≠ original → guaranteed miss. | Raw JSONL uploaded as a run artifact (`transcript-<sessionId>.jsonl`) at EVERY turn end (teardown never reliably reaches cleanup); hydration seeds from the newest matching artifact before falling back to ACP reconstruction; `POSTHOG_RESUME_TASK_ID` enables cross-task forks. |
| V0  | No warm-up stage in ReviewHog's workflow.                                                                                    | Built behind `WARMUP_FORK_ENABLED`: per-chunk warm-up → two-turn forked wave (leader head start) → blind-spot as 5th forker; a failed warm-up degrades its chunk to the unforked fan-out.                                                                                          |

**Already satisfied:** one cache namespace via the gateway; model pinning (`REVIEW_MODEL`); fork/resume/replay primitives; deterministic sandbox cwd.

**Remaining caveats:** the gateway silently maps non-allowlisted models to a default; the Bedrock-fallback header can reroute individual requests to Bedrock's separate cache namespace on Anthropic 5xx (a `POSTHOG_DISABLE_BEDROCK_FALLBACK` env gate now exists in the harness but is NOT set for runs — the confound is symmetric across arm and control); **the harness's overload rescue (`fallbackModel: claude-opus-4-8` on every session) silently and permanently switches a session's model on an overload — model is part of the cache key, so a rescued unit loses all sharing and breaks cost pinning (observed live: 2/9 units in arm smoke 2). Gated off via `POSTHOG_DISABLE_MODEL_FALLBACK`, injected for all DEBUG sandboxes; the dump flags ⚠️SWITCHED units**; the sandbox checkout uses the PR branch ref, not the pinned `head_sha` — SHA-pinning is a correctness fix the fork also wants. The original thinking-block-stripping caveat is superseded by the storage-dialect fact above (the replay form has placeholders for every unit; the warm-up's settle turn survives as cheap transcript-completeness insurance, not as a cache write).

## Precedents and risks

- **C5 warm per-perspective sessions (built, rejected):** sequential chunks in one session anchored later turns near-silent — half the "saving" was suppressed findings. The fork differs: the shared prefix contains no findings or judgments, only neutral reads, and each perspective branches into its own isolated session. The residual risk is curation bias (the warm-up's reading choices framing all followers), so the per-perspective finding-count distribution + yardstick parity on frozen PR #62096 is the standing quality gate.
- **TTL expiry** on stragglers (retries, the post-wave blind-spot): with the S3 transcript as the durable carrier, a miss only re-pays the replay-span write (~$0.15-0.20) — observed on 2/3 blind-spots in arm smoke 2. `ENABLE_PROMPT_CACHING_1H` is UNUSED in the build (followers never read the warm-up's live cache, so extending its TTL buys nothing).
- **Validators keep fresh sessions** — never seeded from review or warm-up transcripts.

## Program state (2026-07-07)

- **Shipped:** the cache-aware metrology (`dump_result.py`, incl. the per-chunk fork writers/readers tracker), validated live; the probe-era "+28% gateway-vs-list discrepancy" resolved as a measurement artifact.
- **Dropped/demoted:** the pre-build overlap gate (Spike 3) and the standalone gateway probe (Spike 1) — subsumed by the build's own measurements. The T1 rewrite-bug ticket is pending re-quantification on the eval's control runs (expected: demote).
- **Active experiment:** the warm-up+fork build (`../2026-07-warmup-fork/`) — M1-M4 done 2026-07-07: T2+T3 patched locally, Spike 2 passed (exact-token replay fidelity), the ReviewHog warm-up+fork stage built behind `WARMUP_FORK_ENABLED` and proven in-pipeline. M5 half done: both controls in ($15.63 @ 2 chunks / $25.60 @ 3; per-chunk review+blind-spot ≈ $5.6-5.8). Remaining: 2 arm runs on frozen PR #62096 + the judgment pass. Harness fixes ship upstream only after the experiment proves value. Hardening shipped along the way: sandbox units run read-only MCP scopes (a unit deleted team skills mid-run twice), and the harness's silent overload rescue (`fallbackModel`) is env-gated off for DEBUG sandboxes.

## Key files

- this repo: `products/review_hog/backend/temporal/workflow.py` (fan-out; where the warm-up slots in), `backend/reviewer/sandbox/executor.py` (prompt→description; `MultiTurnSession`), `backend/reviewer/constants.py` (`REVIEW_MODEL`, on/off knobs), `products/tasks/backend/temporal/process_task/activities/provision_sandbox.py` (sandbox env injection, incl. `ENABLE_PROMPT_CACHING_1H`), `get_sandbox_for_repository.py` (branch-ref checkout to SHA-pin), `eval/scripts/dump_result.py` (validated cost instrument)
- code repo (PostHog Code): `packages/agent/src/server/agent-server.ts` (`buildCloudSystemPrompt`, Task-Id append), `packages/agent/src/adapters/claude/session/options.ts` (systemPrompt build; Bedrock header), `packages/agent/src/adapters/claude/session/jsonl-hydration.ts` (raw JSONL path; lossy hydration to avoid)

Line references drift; function names are the stable anchors. Exact patch surfaces with line numbers: `HARNESS.md`.
