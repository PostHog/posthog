# Prompt caching investigation: cross-sandbox cache reuse

**Status: investigation only (2026-07-03) — nothing here is built, and nothing should be built without the spikes and gates below.**
Decisions locked with the user 2026-07-03: report-only deliverable (spikes specified, not run); cost-first framing (a wall-clock regression of a few minutes is acceptable if $/run drops meaningfully, quality still gated by the yardstick eval); ReviewHog-scope — the three harness changes ship as well-specified Tasks-team tickets, not as work in this product.

> **Update 2026-07-06 — moved + candidate roster added.** This doc moved from `products/review_hog/PROMPT_CACHING_INVESTIGATION.md` to this experiment folder. Three facts changed since it was written:
>
> 1. **The model gate cleared.** `REVIEW_MODEL` flipped to `claude-sonnet-5 @ xhigh` on 2026-07-03 (see `../2026-07-reviewer-model-sonnet5/FINAL_REPORT.md`), so "sequence caching work after the model decision" is satisfied. All caching baselines now key on sonnet-5; the opus-era $ figures below stand as the historical record but must not gate new arms. T1's magnitude likely collapsed with the flip (writes are ~5x cheaper; a crude post-flip probe found ~$0.005/run vs the $0.75 opus-era figure): re-quantify before pressing that ticket.
> 2. **One-shot chunking + dedup shipped (2026-07-03)**, proving the size-gated one-shot pattern AND giving ReviewHog a request-bytes-owning path (`reviewer/sandbox/direct_llm.py`) where IT places `cache_control`. That path is exempt from V1/V2, which reorders this doc's priorities: cross-CALL context sharing on the direct path works today with zero harness dependency, and the strongest new candidates exploit exactly that.
> 3. **A candidates round ran 2026-07-06** (18 raw ideas from 4 lenses -> 13 merged -> 2 adversarial audits each): see **`CANDIDATES.md`** (same folder) for the survivors, the graveyard, corrected economics (naive sonnet $/run overstates true cost ~4.8x; cache reads are now the largest true-cost bucket), and the sequencing (measurement Gate 0 first).
> 4. **User veto, 2026-07-06 (locked):** one-shot LLM calls for code investigation are permanently out of scope — a single call cannot do detective work, and quality is the moat. Only chunking + dedup stay one-shot; every review unit remains a full sandbox agent. The roster's direct-call candidates are recorded as killed in `CANDIDATES.md`; **this doc's Phase 3 warm-up+fork is the program flagship**, spike-gated exactly as specified below (Spike 3 threshold raised to s >= ~0.55), with T2/T3 on the critical path. Large PRs (1000+ additions) are the explicit priority — per-chunk savings scale with chunk count, so the fork benefits large PRs most.
> 5. **2026-07-06 smoke run (see `HARNESS.md`) — two claims below are now stale.** (a) "Cross-sandbox sharing is exactly zero — measured (turn-1 `cache_read` median = 0)": on the current agent/SDK, PARTIAL sharing is live — 2 of 3 fresh wave sandboxes read the jitter-elected leader's identical 27.6K [tools + system-preset] segment; V1's `Task-Id` poisons only the append onward (T2 remains the fork's hard prerequisite; the preset share is worth cents). (b) Spike 1's existential cross-client question has a production PASS (two sandboxes shared one cache through Modal -> ngrok -> local gateway); the probe is confirmatory now. Also observed live: a 10-min wave->blind-spot gap on a single-chunk PR busted the 5-min TTL, so the fork needs per-chunk sequencing (exactly Spike 3's gate (b)). The two-repo local harness loop (patch `packages/agent` locally, overlay into sandboxes, verify via `agentVersion`) is PROVEN and documented in `HARNESS.md`.

## The idea under investigation

ReviewHog's pipeline stages each re-learn the same PR: every LLM unit (chunking, 3 perspectives + blind-spot per chunk, dedup, validation) is a fresh Task → fresh Modal/Docker sandbox → fresh agent-server → fresh Claude Code conversation (see `ARCHITECTURE.md`).
The idea: one "read and understand this PR" warm-up step whose processed context lands in Anthropic's server-side prompt cache, with the parallel review units starting from that cached state instead of re-exploring — saving tokens and money.
Investigated across `products/review_hog` + `products/tasks` (this repo), `packages/agent` in the PostHog Code repo (the agent harness), and Anthropic's prompt-caching documentation.

## Verdict (TL;DR)

**The idea is technically sound and every primitive it needs already exists in the stack — but it fails today for three specific, fixable reasons, and the honest economics are smaller than the 11–21M-input-tokens headline suggests.**

1. **Mental-model correction:** there is no per-sandbox cache and no "cache duplication" API.
   Anthropic's cache is server-side, scoped per **workspace** (docs, Feb 2026), keyed by a cumulative hash of the exact request bytes (`tools` → `system` → `messages`) + model.
   All ReviewHog sandboxes already share ONE cache namespace (everything routes through the PostHog LLM gateway → one Anthropic workspace).
   "N sandboxes from the same cache" = N sandboxes sending byte-identical prompt prefixes within TTL. That's the only mechanism — and it's sufficient.
2. **Caching already works heavily _within_ each sandbox conversation.**
   Measured (`eval/POTENTIAL_EXPERIMENTS.md`): the 11–21M input tokens/run are ~90% cache reads at 0.1×; the real cost split is 42% cache writes / 36% cache reads / 18% output / 4% fresh input; ~$24–28/run, review + blind-spot ≈ 80% of it.
3. **Cross-sandbox sharing is exactly zero today — measured** (turn-1 `cache_read` median = 0) — and fully explained: the harness embeds a unique `Task-Id` into every unit's system prompt, so prefixes diverge before the messages even start.
4. **Guaranteed wins come first:** a known agent-server cache bug (~$0.75/run) + a cache-stable system prompt (~$1.5–2.5/run for ReviewHog, plus **every** PostHog Code cloud task fleet-wide).
   The full warm-up/fork topology adds an estimated **$2–5/run optimistic, ~$0 pessimistic** — the deciding unknown (how much exploration the 4 units per chunk actually duplicate) is measurable from existing telemetry before anyone builds anything.

## How Anthropic caching works (documented facts that matter here)

- **Prefix match:** cache key = exact bytes of `tools` → `system` → `messages` up to a `cache_control` breakpoint. "Cache hits require 100% identical prompt segments." Model is part of the key.
- **Scope:** "Caches are isolated between organizations… As of February 5, 2026, caches are also isolated per workspace within an organization on the Claude API." Within one workspace, all requests share — sandboxes are irrelevant to scoping.
- **TTL:** 5 min default, **refreshed free on every read** (sliding window); optional 1h TTL at 2× write cost. Writes 1.25× (5m), reads 0.1× of input price. Cache hits don't count against rate limits.
- **Concurrency:** an entry becomes readable only after the first response _begins_ — a warm-up must complete before fan-out (a pipeline stage boundary satisfies this; followers can then fire in parallel, all reading).
- **Placement:** breakpoints are set by whoever builds the request — here that's the Claude Code CLI (spawned by the agent SDK inside agent-server), not ReviewHog. It auto-places breakpoints (system, recent messages).

## Today's reality (measured, from the eval work)

Per-stage cost (17-run topology experiment, `eval/POTENTIAL_EXPERIMENTS.md`):

| stage                                                    | share of ~$24–28/run |
| -------------------------------------------------------- | -------------------- |
| review wave (3 perspectives, isolated sandboxes)         | ~$14.3               |
| blind-spot check                                         | ~$5.3                |
| validation (already a warm multi-turn session per chunk) | ~$2.8                |
| chunking + dedup                                         | ~$1.5                |

Cost is **turn-dominated** (median 15 turns/unit, ~$0.10/turn flat from turn 4), not payload-dominated: fresh input is ~16K tokens at turn 1, ~0 after.
Intra-session caching demonstrably works through the gateway.
Two prior experiments are directly relevant precedent:

- **C5 warm per-perspective sessions** (chunks as sequential turns): built, evaluated, **rejected** — anchoring made later turns near-silent; ~half the "saving" was the anchoring itself; wall-clock +3–4 min.
- **"Shared repo-orientation pre-pass artefact"**: **rejected** — measured turn-1 `cache_read` = 0 meant no cross-sandbox cache existed, so a shared pre-pass was pure added payload per unit, plus an anchoring device.
  _The fork idea investigated here is that idea with the cache economics actually attached — which is why it deserves the re-look, gated on eval._

## Why cross-sandbox sharing fails today — three violations

| #   | Violation                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Where                                                                                          | Fixable                                                                                                                                                                                                        |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| V1  | `Task-Id: ${taskId}` interpolated into the system-prompt append of **every** task (signed-commit attribution). Each ReviewHog unit is its own Task → unique system segment → cache diverges before messages.                                                                                                                                                                                                                                                       | code repo, `packages/agent/src/server/agent-server.ts:2638` (`buildCloudSystemPrompt`)         | Yes — de-interpolate. Verify first whether the signed-commit tool injects the trailer server-side from config (then the prompt line can be static text); otherwise move the ID into the first user message.    |
| V2  | Claude Code preset injects dynamic sections (cwd, git status, date, auto-memory) into the system prompt. The SDK ships the exact fix — `systemPrompt: {preset: "claude_code", excludeDynamicSections: true}` (strips them and re-injects as first user message) and `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` — **the harness uses neither**.                                                                                                                               | code repo, `packages/agent/src/adapters/claude/session/options.ts:93–123`; SDK `sdk.d.ts:1934` | Yes — one option flag, but fleet-wide behavioral blast radius → flagged rollout.                                                                                                                               |
| V3  | Transcript seeding exists (`hydrateSessionJsonl()` + `resumeSession`/`forkSession:true` + `--replay-user-messages`) but reconstruction from the S3 ACP log is **lossy** (fresh random UUIDs, `JSON.stringify`-flattened tool results, 10K-char truncation, zeroed usage, turn-dropping over ~150K est. tokens) → replayed bytes ≠ original → guaranteed miss. The **raw** JSONL (`~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl`) is never uploaded anywhere. | code repo, `packages/agent/src/adapters/claude/session/jsonl-hydration.ts:54,243,589`          | Yes — upload the raw JSONL at task end; seed followers by downloading it to the identical path (cwd is deterministic: `/tmp/workspace/repos/{org}/{repo}`) and forking. Must NOT use the lossy hydration path. |

Plus V0 (trivial, ReviewHog-side): no warm-up stage exists in `backend/temporal/workflow.py` — nothing runs before the 4-unit fan-out.

**Conditions already satisfied:** one cache namespace via the gateway (`ANTHROPIC_BASE_URL` → `gateway.{us|eu}.posthog.com/background_agents`); model pinning exists (`REVIEW_MODEL`, `backend/reviewer/constants.py:5-7`); fork/resume/replay primitives exist; deterministic sandbox cwd; same base repo snapshot per run.

**Caveats to design around:** the gateway silently maps non-allowlisted models to a default; an unconditional Bedrock-fallback header (`options.ts:161`) can reroute individual requests to Bedrock's separate cache namespace on Anthropic 5xx (occasional miss, not fatal); the sandbox checkout uses the PR **branch ref, not the pinned `head_sha`** — a latent mixed-version race across today's parallel units regardless of caching.

## What it would actually save (cost-first)

ReviewHog's prompt layout is already accidentally cache-friendly: the composed prompt goes into `Task.description` → the **first user message** (not the Anthropic system prompt), and the 4 units of a chunk differ only in the last ~10 lines (perspective skill name/version).
But without V1/V2 fixed, none of that shares; and even with them fixed, only the tools+system segment shares — the exploration (each unit re-reading the same chunk files via tools) is what the warm-up/fork targets.

- **Fix known bug (T1):** ~$0.75/run, zero risk.
- **Cache-stable system prompt (T2):** converts each unit's turn-1 system+tools cache write (~10–20K tokens at 1.25×) into a 0.1× read → ~$1.5–2.5/run across ~16–20 sandbox requests, **plus the same effect on every PostHog Code cloud task fleet-wide**. Prerequisite for everything below.
- **Warm-up + fork (the idea, T3 + ReviewHog work):** addressable pool = the perspective-invariant share _s_ of early exploration duplicated across 4 units/chunk.
  At *s*≈0.6: ~$2–2.5/chunk (turn elimination + write→read conversion) → **~$2–5/run net optimistic on a 3-chunk run (8–20%), ~$0 pessimistic**; wall-clock +2–4 min (serial warm-up + 55s sandbox provisioning) unless follower provisioning overlaps warm-up execution — acceptable under the cost-first framing.
  _s_ is unmeasured; Spike 3 settles it from existing data.
- **Reference point:** the in-flight Sonnet-5 model round (`eval/experiments/2026-07-reviewer-model-sonnet5/`, arm B pending) would cut ~40% of review-stage cost on its own if it hits parity — and model is part of the cache key, so it resets all caching baselines. **Sequence caching work after the model decision.** _(Resolved 2026-07-06: the round completed and prod flipped to sonnet-5 @ xhigh on 2026-07-03 — the gate is cleared and sonnet-5 is the baseline model for all caching arms.)_

## Recommended path

### Phase 0 — Tasks-team tickets (harness/code repo; can be written now, no ReviewHog dependency)

1. **T1 — mid-task full-prefix cache-rewrite bug** (already flagged in `eval/POTENTIAL_EXPERIMENTS.md`: 24 gens, ~2.2M tokens rewritten with cache_read=0 seconds after a write, ~$0.75/run). Pure waste; no eval gate.
2. **T2 — cache-stable system prompt for sandbox tasks:** de-interpolate `Task-Id` from `buildCloudSystemPrompt` (verify the signed-commit tool injects the trailer itself from server config; else move to first user message) + enable `excludeDynamicSections: true` for cloud sessions.
   Roll out behind a flag per gateway product, `background_agents` first; gate on the harness smoke suite + ReviewHog yardstick + turn-1 cache_read median > 0.
3. **T3 — raw-JSONL session persistence + seed-on-start:** upload the raw `~/.claude/projects/<cwd>/<sessionId>.jsonl` at task end (same storage/ACL class as the existing ACP log); on task start with a seed reference, download to the identical path and `resumeSession({resume: sessionId, forkSession: true})`, delivering the task description as the new turn.
   Explicitly not the lossy `hydrateSessionJsonl` path.

### Phase 1 — ReviewHog-side, independent of the tickets

- **SHA-pin the sandbox checkout** via the existing `head_sha` (correctness fix regardless of caching; also required for byte-identical git state across warm-up/followers).
- **Spike 3 (offline, zero risk):** from existing runs' logs/`$ai_generation` events, compute per-chunk token-weighted overlap of pre-first-finding tool activity across the 4 units.
  **Go/no-go for the fork topology: ≥40% overlap** (below that, expected net < $2/run — stop after T2).

### Phase 2 — decisive spikes (cheap, before any build; after the Sonnet-5 round fixes `REVIEW_MODEL`)

- **Spike 1 — gateway cache probe:** two hand-built byte-identical `/v1/messages` requests (≥8K-token cached block) from two sandboxes through the gateway, 2 min apart.
  Success: second request's `cache_read_input_tokens ≥ 0.95×` the first's `cache_creation_input_tokens` (cross-check in `$ai_generation`).
  Variants: `REVIEW_MODEL` vs default (allowlist mapping), >6 min apart (TTL sanity).
  Failure = escalate to the Tasks team ("workspace cache not shared through gateway") and stop.
- **Spike 2 — raw-JSONL fork fidelity:** 5-turn session in sandbox A (tools + thinking + file reads); copy the raw JSONL to sandbox B at the identical encoded-cwd path (same checkout SHA, same CLI version); fork + one new turn.
  Success: the fork's first request reads ≥90% of A's final prompt size from cache, no 400s (thinking-block signatures accepted).
  This one experiment retires the replay-fidelity, thinking-block, session-id, and version-skew unknowns.

### Phase 3 — build only if the gates pass

Per-chunk **warm-up + fork** behind a constant: a neutral warm-up unit ("read the diff and touched files; do not analyze or judge") → raw JSONL persisted → 4 followers fork it → perspective/blind-spot ask as the new turn.
Chunk-local scheduling (warm-up + its followers as one unit, follower provisioning overlapped with warm-up execution) to stay inside the 5-min sliding TTL under `Semaphore(10)` saturation.
**Eval gate per team culture:** 2 arm runs vs 2 fresh controls on frozen PR #62096 — valid-count and old-coverage parity, per-perspective finding-count distribution (anchoring shows up as depressed follower counts), measured net saving ≥ $2/run, wall ≤ +3–4 min.
Validators keep their own fresh sessions — never seeded from review/warm-up transcripts.

## Risks

- **Anchoring (the big one):** the C5 precedent is real, but the fork differs — the shared prefix contains _no findings, no judgments_, only neutral reads of the same chunk; each perspective branches fresh.
  Residual risk is curation bias (the warm-up's choice of what to read frames follower attention) — exactly why the eval gate includes per-perspective count distributions.
- **TTL expiry** on slow multi-chunk runs → chunk-local scheduling; monitor the follower turn-1 cache_read distribution.
- **Bedrock fallback variance** (per-request cache misses on Anthropic 5xx) → accept; alert if the run-level cache-read share drops.
- **Model-round interference:** model is part of the cache key; run all caching work on the post-round pinned model.
- **Org:** T1–T3 are Tasks-team owned; T2 is fleet-wide → flagged, product-by-product rollout.

## Key files

- this repo: `products/review_hog/backend/temporal/workflow.py` (fan-out; where the warm-up would slot in), `backend/reviewer/sandbox/executor.py:82` (prompt→description; `MultiTurnSession` start/continue/end), `backend/reviewer/constants.py` (`REVIEW_MODEL`), `products/tasks/backend/temporal/process_task/activities/get_sandbox_for_repository.py:295` (branch-ref checkout to SHA-pin), `products/review_hog/eval/POTENTIAL_EXPERIMENTS.md` (all economics)
- code repo (PostHog Code): `packages/agent/src/server/agent-server.ts:2638` (Task-Id append), `:2457` (`buildSessionSystemPrompt`), `packages/agent/src/adapters/claude/session/options.ts:93–123` (systemPrompt build; `:161` Bedrock header; `:439` replay-user-messages), `packages/agent/src/adapters/claude/session/jsonl-hydration.ts` (lossy hydration; JSONL path)

Line references are as of 2026-07-03 and will drift; the function names are the stable anchors.

## Verification (when work starts — nothing runs now)

Spikes 1–3 with the success metrics above; T2 gated on the yardstick eval + turn-1 cache_read > 0; Phase 3 gated on the #62096 eval.
Ongoing telemetry: the per-unit turn-1 `cache_read_input_tokens` distribution and the `$ai_cache_read_input_tokens` share per run from `$ai_generation` events (the gateway already records both).
