# Warm-up + fork experiment (candidate #8, the flagship) — plan

**Status 2026-07-07 ~11:20 UTC: M1-M4 DONE, M5 half done — both CONTROLS are in (run log #10, #12: $15.63 @ 2 chunks / $25.60 @ 3 chunks, per-chunk review+blind-spot ≈ $5.6-5.8); NEXT: arm run 1 → arm run 2 → judgment.**
Arm 1's first attempt (10:52 UTC) was cancelled ~5 min in for priority production reviews (control path, published): PR #68791 (11:01 UTC) and PR #67451 (11:31 UTC) — wait for both to finish before touching the worker, then restart arm 1 from scratch: flip `WARMUP_FORK_ENABLED=True`, restart the worker (phrocs toggle ×2), wipe the #62096 report, `run_review` (no publish), dump as `m5-arm-1`, repeat for `m5-arm-2`, then the judgment pass (gates in this doc; yardstick = `../2026-07-reviewer-topology/fixtures/`; compare per-chunk-normalized review+blind-spot cost, follower gens/unit vs control's ~20-33, and the fork tracker's writers/readers lines).
Source of truth for mechanics and constraints: `../2026-07-prompt-caching/` — `INVESTIGATION.md` (violations V0-V3, caching facts), `CANDIDATES.md` (locked constraints 1-9, #8's audited spec), `HARNESS.md` (exact patch surfaces, 1h TTL, smoke-run lessons). This plan does not restate what they settle.
The design section below is the original spec; **the run log is the truth for what the build actually became** — the biggest deltas: forked units run TWO turns (byte-identical settle turn first, perspective prompt second — cache entries are only addressable at message ends), the leader gets a `FORK_LEADER_HEAD_START_SECONDS` head start, and the 1h TTL is not used (the S3 transcript is the durable carrier; followers never read the warm-up's live cache).

## What we're testing

After chunking, one neutral warm-up agent per chunk reads and understands the chunk and its related codespace (no judgments, no code). Its raw session transcript is persisted, and every perspective reviewer forks from it, inheriting the investigation from Anthropic's server-side cache at 0.1× — so reviewers skip the investigation turns entirely while keeping full tools and freedom.
The saving mechanism is turn elimination (cost is turn-dominated: median ~15 turns/unit, each re-reading the growing prefix). Value scales with perspective count, which is user-extensible and unbounded — the warm-up amortizes over N.
No pre-build overlap measurement gates this (locked constraint 7); measurement is post-build: follower turns and per-turn cost vs control + quality parity.

## The arm (design at a glance)

- **Warm-up unit** = a real Claude Code sandbox session (same `CustomPromptSandboxContext` shape, same repository/branch, same model pins as the wave — the model is part of the cache key and tools+system must match followers byte-for-byte). Prompt: read the chunk diff, touched files, immediate callers; explicitly no analysis, no judgments, no code; transcript capped ~70K tokens.
- **Settling turn**: the warm-up ends with one trivial follow-up user turn (multi-turn primitives exist in `executor.py`). Original rationale (stripped-form cache write) turned out moot — followers never read the warm-up's live cache (see run log #5) — but the turn stays: it is cheap (measured: read ~75K cached / wrote ~400) and guarantees a final turn-end transcript upload after the investigation completes.
- **Fork (as built)**: the harness uploads the raw session JSONL at every turn end (T3); each follower downloads it to the identical deterministic cwd and forks (`resumeSession({resume, forkSession: true})`). The forked unit then runs **two turns**: turn 1 is `FORKED_UNIT_FIRST_TURN_PROMPT`, byte-identical across all siblings of a chunk — cache entries are addressable only at message ends, so siblings share the big replayed span only when their entire first request matches (run log #7); turn 2 carries the perspective-specific review prompt, riding the now-cached prefix. The chunk's first wave unit (leader) launches `FORK_LEADER_HEAD_START_SECONDS` ahead of its siblings, because an entry is readable only once the writer's response has _started_ and TTFT on a ~100K write exceeds 30s (run log #8).
- **Per-chunk sequencing**: warm-up(chunk) → forked wave(chunk) → blind-spot(chunk) as 5th forker right after its chunk's wave (replaces today's global wave barrier). A failed warm-up degrades its chunk to the unforked fan-out.
- **TTL policy (superseded)**: the 1h TTL is NOT used. The S3 transcript artifact is the durable carrier — a TTL miss only means the next unit re-pays the ~1.25× replay-span write (~$0.15-0.20), never a broken fork. Observed leak: the wave→blind-spot gap sometimes outlives the 5m window (1 of 3 chunks' blind-spots read in smoke 2); priced honestly by the eval, with the Bedrock-fallback header as a possible confound (present equally in arm and control).
- **Everything behind one constant** in `reviewer/constants.py` (`WARMUP_FORK_ENABLED`, default off). Constant off = byte-for-byte today's pipeline (the control).

Anchoring posture (the C5 lesson): the shared prefix contains no findings or judgments, only neutral raw tool results; each perspective branches into its own isolated forked session. The residual risk is curation bias (the warm-up's reading choices framing all followers) — the per-perspective finding-count distribution + yardstick are the standing guard. Validators stay fresh, never seeded.

**Recorded alternative (2026-07-07, user): the paste variant.** Instead of replaying the transcript via T3, extract the warm-up's file reads and paste them into the forked units' identical first turn as plain content. Same cache mechanics required (two-turn + leader head start — a shared head inside one message shares nothing, proven by arm smoke 1), so it simplifies only the harness side: no T3 upload/hydration/resume plumbing. Costs: second-hand content instead of first-person memory (likely strengthens the re-read instinct; the mild form of the killed dossier shape) and a curation surface the replay doesn't have. Not for this experiment — it is the production simplification candidate if the arm wins quality but we don't want T2/T3 shipped upstream.

Skill delivery note: the skill-get choreography stays as-is in the fork arm (perspective-specific = divergent turn 2 anyway, no cache to win); queued candidate #4 (skill-body-splice) removes it at build time and composes cleanly with the fork.

## Milestones

### M0 — pre-flight (~15 min, $0)

Stack + ngrok up; `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` active in the worker env (needs a full stack restart if not — flox sources `.env` at activation only); code repo clean on `main`, base commit recorded here; GitHub integration row present (DB-nuke restore one-liner in `HARNESS.md`); no running `review-pr` workflows before any watched-file edit.

### M1 — T2: cache-stable prefix (code repo, ~half day, 1 smoke run)

Per `HARNESS.md` T2 surface:

- De-interpolate `Task-Id: ${taskId}` in `buildCloudSystemPrompt` (`agent-server.ts`, `signedCommitInstructions`) to static text — safe, the git tool injects the trailer deterministically from config. Update the 4 `agent-server.test.ts` assertions.
- Set `excludeDynamicSections: true` in `buildSystemPrompt` (`options.ts`), covering the cloud `params.systemPrompt` shape too; add the missing test.
- Gate the unconditional `x-posthog-use-bedrock-fallback` header off for experiment runs (env-gated; update `options.test.ts:196`) — it reroutes to Bedrock's separate cache namespace on Anthropic 5xx and confounds every cache measurement.

`pnpm build`, restart worker, record the diff in `patches/t2.diff`. Smoke: one ordinary no-publish run on PR #62096, `agentVersion 0.0.0-dev` confirmed in the TaskRun log.
**Exit:** non-leader wave units' turn-1 `cache_read` spans grow past the pre-T2 preset-only boundary (27,618 on the measured run shape) to cover tools+system+append, identical across followers. If ambiguous, diff raw request bytes at the local llm-gateway.

### M2 — T3: raw-JSONL persistence + fork-seed (code repo, ~1 day, 1 smoke run)

Per `HARNESS.md` T3 surface:

- Upload the raw session JSONL in `cleanupSession` (+ crash path) via the existing artifact uploader (`uploadTaskArtifacts`, reserved name like `transcript/<sessionId>.jsonl`). Never the lossy ACP reconstruction (V3).
- Fork-seed: new step 0 in `hydrateSessionJsonl` — when the resume-referenced run has a raw transcript artifact, download it to `getSessionJsonlPath` and hydrate from it. The resume trigger already flows (`POSTHOG_RESUME_RUN_ID` → `autoInitializeSession`).

Record `patches/t3.diff`.
**Exit:** after an ordinary run, every unit's raw transcript artifact exists in object storage; a manual resume against a finished run logs raw-JSONL hydration (not ACP reconstruction).

### M3 — Spike 2: stripped-form fork fidelity (the go/no-go, ~half day, ~$5-10)

Minimal throwaway driver (script in this folder, run via `manage.py shell` or an eval script — added strictly between runs, it's a watched path): task A = warm-up-style neutral read of a #62096 chunk with the settling turn; tasks B and C fork from A's run concurrently with follower-style appended messages. This is where the one missing plumbing bit gets built minimally: a way to set `resume_from_run_id` on a facade-created task (today `CustomPromptSandboxContext` has no passthrough; `provision_sandbox.py` already reads it from run state).
Measure:

1. **Fidelity:** B/C turn-1 `cache_read` ≈ A's stripped-form transcript size (gate stated against the stripped form, or it false-kills a correct implementation).
2. **Latency:** A-settling-turn → B-first-request wall clock vs the 5m TTL; confirms or retires the 1h-on-warm-up decision (if enabled: A's write-side cost ~+60% and a >5m gap survives — the empirical 1h confirmation `HARNESS.md` asks for).
3. **No re-write race:** two concurrent followers both read (neither re-writes) — the settling write is the fix, stagger is the fallback.

**Exit:** fork read ≈ stripped-form prefix on both followers. **A miss here stops the experiment before M4** — record, diagnose (byte-diff at the gateway), and only then decide.

Driver: `spike2_driver.py` (this folder). Post-run analysis — one per-gen table over the spike's units, everything else is arithmetic on it (run via `sync_execute` in `manage.py shell`):

```sql
SELECT
    JSONExtractString(properties, 'task_run_id') AS run_id,
    extract(JSONExtractString(properties, 'task_title'), '\\[sandbox_prompt:([a-z0-9_-]+)\\]') AS step,
    timestamp,
    toInt64OrZero(JSONExtractString(properties, '$ai_input_tokens')) AS input_total,
    toInt64OrZero(JSONExtractString(properties, '$ai_cache_read_input_tokens')) AS cache_read,
    toInt64OrZero(JSONExtractString(properties, '$ai_cache_creation_input_tokens')) AS cache_write,
    toInt64OrZero(JSONExtractString(properties, '$ai_output_tokens')) AS output,
    toFloat64OrZero(JSONExtractString(properties, '$ai_cache_creation_cost_usd')) AS write_usd
FROM events
WHERE event = '$ai_generation'
  AND JSONExtractString(properties, 'task_title') LIKE '[sandbox_prompt:spike2-%'
ORDER BY run_id, timestamp
```

Checks: (1) fidelity — B/C turn-1 `cache_read` ≈ A's settle-gen `input_total` (the stripped-form prefix); (2) latency — A's settle-gen timestamp → B/C first-gen timestamps vs the TTL; (3) no re-write race — both followers read, neither re-writes the prefix span; (4) 1h billing — A's `write_usd` at the 2× rate (vs 1.25× list) confirms the env var took effect, and a >5m A→follower gap surviving confirms the TTL.

### M4 — ReviewHog warm-up stage + fork wiring behind the constant (this repo, ~1 day, 2 smoke runs)

- `reviewer/constants.py`: `WARMUP_FORK_ENABLED = False` + the warm-up knobs (transcript cap, 1h-TTL toggle per M3's decision).
- Warm-up activity + prompt template (neutral read, no judgments, cap, settling turn), pinned to the REVIEW model/effort/adapter.
- `ReviewPerspectivesWorkflow`: per-chunk sequencing (warm-up → forked wave → blind-spot as 5th forker), keeping the semaphore, failure floor, and persisted-resume semantics. **Fallback:** a failed warm-up degrades that chunk to today's unforked fan-out — never fails the chunk.
- Facade passthrough (products/tasks): `resume_from_run_id` (+ per-task env for the TTL toggle) on `CustomPromptSandboxContext` → task run state → existing `POSTHOG_RESUME_RUN_ID` env injection.
- Never edit `products/**/*.py` while a run is in flight (nodemon respawns the worker and kills the run).

**Exit:** arm smoke on #62096 (constant on): all followers' turn-1 reads ≈ their chunk's warm-up transcript, review completes, findings persist. Control smoke (constant off): pipeline byte-identical to today (no behavior drift).

### M5 — the 2v2 eval (~$60-100, the decision)

2 control runs (constant off) + 2 arm runs (constant on), frozen PR #62096, no publish. Each run dumped with the validated cache-aware `dump_result.py` (turn-1 distribution is a standing section). LLM-judged vs the old-10 yardstick (`../2026-07-reviewer-topology/fixtures/`). The control runs double as the fresh sonnet-era baseline (and carry candidate #1's leftover T1 detector + re-anchor work, run offline afterwards).

## Gates (all cache-aware, relative to the measured control)

| gate      | pass                                                                                                                                                                                             | kill                                                                                                                                                               |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Mechanics | every follower turn-1 `cache_read` ≈ its warm-up's stripped-form transcript size                                                                                                                 | any follower at ~0 on a healthy warm-up = silent regression; fix or stop (this gate also becomes the production kill-switch metric if #8 ships)                    |
| Cost      | review-stage (wave + blind-spot + warm-up) true $/run **down vs control, net of warm-up cost**; follower median turns down; follower per-turn cost **not above** control (the re-read-tax guard) | arm ≥ control $, or turns drop but per-turn cost balloons (warm-up under-covered, followers re-read anyway)                                                        |
| Quality   | valid findings ≥ control − 1; yardstick finding-ID overlap not degraded; per-perspective finding-count distribution intact                                                                       | a perspective near-silent in both arm runs (the C5 signature) = kill even at equal totals; a systematic yardstick loss (same finding lost in both arm runs) = kill |

## Rollback

Losing arm: revert this repo's experiment commits (constant + wiring), `git checkout .` in the code repo (patches preserved in `patches/`), experiment folder keeps the record. The T2/T3 harness fixes are independently upstreamable regardless of the arm's fate — that decision is the user's, after.

## Working mode (locked)

Everything on `signals/reviewhog`, no new branches; experiment code behind `WARMUP_FORK_ENABLED`; I never `git commit` (the user commits); code-repo changes stay as local uncommitted patches on `main`, snapshotted into `patches/` after each milestone; `agentVersion` recorded on every patched run; runs and dumps land in `runs/`.

## Run log

| #   | date       | what                                                       | result                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| --- | ---------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | 2026-07-06 | M1 smoke on #62096 (22:48 UTC)                             | INVALID for T2: units ran npm agent 2.3.1272 — `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` never reached the worker (stale flox activation at stack start; the silent `return None` in `local_packages.py:52`). Killed at validation.                                                                                                                                                                                                                           |
| 2   | 2026-07-06 | M1 smoke rerun (23:14 UTC), env fixed via explicit exports | INVALID for T2 but proved `agentVersion 0.0.0-dev` (overlay works): spawned only ONE unit — unit results persist per head (report artefacts), so it reused run 1's wave. Lesson: **wipe the #62096 `ReviewReport` before every fresh-measurement run.**                                                                                                                                                                                                |
| 3   | 2026-07-06 | M1 smoke, fully fresh (23:27 UTC), report wiped            | **M1 PASS.** Turn-1 shared span grew 27,618 → **37,120**, identical on 5/10 units incl. both blind-spots **7.7 min after the wave** (the wave's ongoing reads kept the shared head alive — sliding-TTL refresh works cross-unit). 3 same-second starters missed (writer-response race; the settling turn is the fork's fix). 2 chunks this time (LLM chunker nondeterminism). True $15.67 / naive $80.17 / 308 gens. Dump: `runs/m1-t2-smoke-run3.md`. |

| 4 | 2026-07-07 | Spike 2 attempt 1 (00:00 UTC, ~$0.3) | FAIL at the artifact gate — but A's cache mechanics were textbook (settle turn: read 75,025 / wrote 385 — the stripped-form prefix costs almost nothing extra in-session). Three T3 bugs found: (1) sandbox teardown on task completion never reaches `cleanupSession`, so an upload there never runs — moved to turn-end (`broadcastTurnComplete`, fire-and-forget); (2) the backend keeps only the basename of an artifact name — `transcript/x.jsonl` became `x.jsonl` and the seed's exact match could never hit — renamed to `transcript-<sessionId>.jsonl`; (3) the manifest APPENDS per upload — the seed now takes the last matching entry. Also: A provisioned in ~80s (repo-snapshot restore), and snapshot restores demonstrably DO get the local dist overlay. |
| 5 | 2026-07-07 | Spike 2 attempt 2 (00:15 UTC), fixed build | **Mechanics half-PASS, design pivot.** Turn-end upload works (artifact visible the second A ended). Both followers hydrated A's raw JSONL (T3 seed works). Fidelity split: **replay-vs-replay is byte-perfect** — C's turn-1 read 76,551 = exactly B's 37,120 read + 39,431 write, wrote 0 — but **live-vs-replay diverges at message 1** (B matched only the tools+system span; the CLI stores/loads sessions in a different dialect than it sends live — e.g. thinking blocks come back as `{"text": " "}` placeholders, and the live first message carries ~8K of send-time-injected context). Pivot: stop chasing live-form fidelity — **all followers replay the same artifact; the first to fire writes the replay-form cache (~$0.19), the rest read at 0.1×**. The S3 artifact is the durable carrier, so TTL pressure mostly vanishes (concurrent followers self-refresh; the 1h env is likely unnecessary). Bonus: attempt-2's warm-up read 45,470 tokens of attempt-1's warm-up cache from 13 min earlier — behavioral 1h-TTL confirmation. Defect 2: followers got the generic "continue" instead of their prompt — fixed via `pending_user_message` on the fork path (the resume continuation prefers it; the workflow forwarder skips resumes, so no double delivery). |
| 6 | 2026-07-07 | Spike 2 attempt 3 (00:26 UTC), follower prompts wired | **M3 PASS — the fork works end to end, with exact-token fidelity.** A: 5 gens, settle prefix ~74.8K, transcript artifact visible the second A ended; A's turn-1 also read 45,470 of attempt-2's warm-up cache (1h TTL live). Followers both ran an identical 77,484-token replayed prompt. C fired first: read 37,120 (shared tools+system), **wrote 38,885** (the replay-form message span). B fired second: **read 76,005 = 37,120 + 38,885 EXACTLY, wrote 0** — 98.1% of its prompt at 0.1× (~$0.018 vs $0.155 naive). Both answered the blast-radius question (2,042 / 1,814 output tokens — the `pending_user_message` fix delivered the prompts). Driver was killed mid-poll so parsed answers weren't captured and sessions idled out ("Sandbox stopped" error is teardown noise, both runs completed). The replay-form write is the fork's real cache key: first follower pays the ~1.25× write once, every later follower reads. |

| 7 | 2026-07-07 | M4 arm smoke 1 (07:29 UTC, $20.89) | **Pipeline PASS, cache MISS — found the real fork constraint.** Warm-ups ran per chunk (~3 min each, parallel), all 8 units forked (hydration + `pending_user_message` worked end to end, review completed, 9 raw → 8 dedup → 3 valid). But every forked unit turn-1 read only the 37,120 tools+system span and REWROTE the ~60-100K replay span — 0 cross-unit sharing. Two causes vs the spike: (1) each unit's first request ended with its own perspective-specific review prompt, and a cache entry is only addressable at its END — divergent tails make the shared middle unreadable (the spike's followers shared because their prompts were byte-identical); (2) snapshot-restore provisioning is too uniform (~±10s) for natural jitter to serialize the writers anyway. Dump: `runs/m4-arm-smoke-run1.md`. |
| 8 | 2026-07-07 | M4 arm smoke 2 (08:17 UTC), two-turn fork + leader head start | **M4 PASS — the fork shares in the real pipeline.** 3 chunks; per chunk: c2 perfect (1 writer, 3 readers incl. blind-spot — 85,858 read exact, wrote 0), c3 wave perfect (1 writer, 2 readers at 115,879 exact; blind-spot TTL-missed and re-paid the write), c1 one collision (sibling's request landed inside the leader's TTFT — 30s head start marginally short, bumped to 60s). Wave followers: **5/6 read the full shared prefix at 0.1×**; blind-spots 1/3. Review completed: 20 raw → 17 dedup → 3 valid, $29.43 true (incl. $1.57 warm-ups). **Second finding: 2 units silently switched sonnet→opus mid-session** — the harness's own overload rescue (`options.ts` sets `fallbackModel: claude-opus-4-8`; an overload during the 08:23 burst of concurrent ~100K prompts flips the session permanently). Model is part of the cache key, so a rescued unit loses all sharing AND pays opus prices (~$3+ of this run's cost). Fixed for measurement: `POSTHOG_DISABLE_MODEL_FALLBACK` env gate in the harness, injected for all DEBUG sandboxes; the dump now prints per-unit models with a ⚠️SWITCHED flag and a `model_switches=` headline count. Dump: `runs/m4-arm-smoke-run2.md` (predates the model column). |

| 9 | 2026-07-07 | M5 control 1, attempt 1 (09:12 UTC, ~$10 burned) | FAILED at the blind-spot skill load: `review-hog-blind-spots-general` was **soft-deleted at 08:33:25 — mid arm-smoke-2** (between blind-spot-c3's failed attempt and its Temporal retry). Prime suspect: a sandbox unit with FULL posthog-MCP scopes calling a skills-store write tool instead of `skill-get`. The delete also clears `is_latest`, and the canonical sync does not resurrect soft-deleted rows — so every later run fails until manually fixed (`deleted=False, is_latest=True`). Report wiped, control relaunched clean (attempt 1b, 09:26 UTC). **Product flag for later: review units should get read-only MCP scopes** — an agent can corrupt team skill state mid-run. |

| 10 | 2026-07-07 | M5 control 1 = attempt 1b (09:25 UTC, $15.63) | **CONTROL 1 DONE.** 2 chunks, 8 units, 11 raw → 9 dedup → 5 valid, true $15.63 (≈ yesterday's unforked smoke $15.67 — stable baseline). Turn-1 cross-unit sharing near-zero as expected for the control (2/10 units; all 6 wave units fired within 8s of each other). New tripwire caught 1 mid-session model-pin loss (validation-c1, opus→sonnet-4-6 — the pre-existing session-restart class, NOT the fallback rescue; hits arm and control alike). sonnet-4-6 added to the dump's price map. Dump: `runs/m5-control-1.md`. |
| 11 | 2026-07-07 | Skill deletion #2 (found 10:06; deleted 09:37 mid-control-1) | `review-hog-perspective-contracts-security` tombstoned by a review agent — control 2 attempt 1 failed instantly on it. Twice in 2 runs → applied the least-privilege fix NOW rather than after the eval: all ReviewHog sandbox contexts (review / forked / multi-turn) run with `posthog_mcp_scopes="read_only"` — the MCP server strips write tools entirely, so skill corruption becomes impossible; units only ever `skill-get` (a read). Applies identically to arm and control. Both skill rows restored; control 2 relaunched 10:16 UTC. |

| 12 | 2026-07-07 | M5 control 2 = attempt 2b (10:13 UTC, $25.60) | **CONTROL 2 DONE, no incidents** (read-only scopes held — no skill corruption). 3 chunks this time (chunker nondeterminism), 12 units, 17 raw → 15 dedup → 6 valid, true $25.60. 1 model-pin loss flagged. With control 1 ($15.63, 2 chunks): control per-chunk review+blind-spot ≈ $5.6-5.8 — stable. Dump: `runs/m5-control-2.md`. |

| 13 | 2026-07-07 | Arm 1 attempt 1 (10:52 UTC, ~$1-2 burned) | Cancelled ~5 min in (warm-up stage) for the priority production review of PR #68791 (published, control path, constant flipped off for it). Arm 1 restarts from scratch after. |

Operational lessons (2026-07-06 night):

- The worker env comes ONLY from the phrocs supervisor's env at stack start; `.env` edits after the launching shell's flox activation are silently ignored. Remedy: explicit `export` in the stack-launching shell (now includes `TEMPORAL_DISABLE_HOT_RELOAD=1`, which removes the nodemon mid-run-edit hazard entirely).
- `run_review` reuses persisted (pass, chunk) unit results at the same head **across invocations** (keyed on the per-PR report, not per run) — a partially-complete prior run makes the next one skip its wave. Delete the PR's `ReviewReport` (cascades artefacts) for a fresh run.
- Cross-task artifact reads need no posthog-side changes: `artifacts_download` / `retrieve` are read-only actions gated on task visibility, and all ReviewHog units share one creating user.
