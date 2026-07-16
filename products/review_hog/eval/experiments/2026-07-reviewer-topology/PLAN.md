# Reviewer-quality experiment — finding the best reviewer topology

> **ARCHIVED 2026-07-02 — experiment complete.** This was the live working scratchpad; it moved here from
> `products/review_hog/EXPERIMENT_reviewer_quality.md` after the runs finished, and its `playground/reviewhog-quality-iterations/`
> paths are historical — the artifacts now live next to this file: `FINAL_REPORT.md` (read this first), `judge_results.json`,
> `runs/` (17 per-run dumps), `fixtures/` (PR diff, prior bot comments, copy of the old report), and the harness at
> `../../scripts/dump_result.py`.

> **Working scratchpad. Survives compaction — update the Run Log + Decisions as we go.**
> Companion to `ARCHITECTURE.md`. Scope = the **reviewer stage only** (chunking + perspective topology).
> The **validator is held constant** (current strict validator) — out of scope this round.
> Model held constant: **Claude Opus 4.8 @ xhigh** for reviewers (switched back from GPT-5.5 Codex, which was unreliable). Reviewer-model comparison is a later round; the old ReviewHog yardstick below was produced with GPT-5.5, so coverage differences may partly reflect the model, not just topology.

## Goal & priority order

Find the reviewer topology that gets **closest to (or beats) the old ReviewHog's coverage** on the same PR.
Priorities, in order (quality dominates):

1. **Quality** (largest weight) — coverage vs the old report (issues found that the old found) + not adding junk.
2. **Tokens spent** (second).
3. **Wall-clock time** (third).

If tokens/time were free we'd replicate the old structure 1:1 (8 chunks × 3 cumulative passes). The point is to find how
much of that quality we can keep at a fraction of the cost.

## Why we're here (root cause, from the #67371 analysis)

On PR #67371 the cloud reviewer found **4** issues vs the old's **11** (all 4 a subset). Cause is **structural, not the
prompt** (the two review prompts are near-identical):

- Old = **8 chunks × 3 cumulative passes = ~24 focused review units**; each pass sees the prior passes' findings and is
  pushed to find _more_.
- Cloud = **1 chunk × 3 parallel perspectives = 3 broad sweeps**; one-shot per lens, deduped after, no "dig deeper".
- The **single-chunk size gate** (`CHUNK_TARGET_ADDITIONS=1000`, additions-only) collapsed a 495-add/36-file refactor
  into 1 chunk. (Validator strictness explains the further 4→2, and that's accepted.)

So the two levers to test are **(1) chunk granularity** and **(2) perspective topology (parallel vs sequential)**.

## The test PR — #62096 (FROZEN, comparable)

**Review URL (use this exact one for every run): `https://github.com/PostHog/posthog/pull/62096`**

`feat(ph AI): add action CRUD tools to ph AI` · head `ba725a897db35053525e5bdfac2c64a8b007fcb4` ·
**674 add / 1 del / 10 files** (current head stats == old report stats → PR unchanged since the old run).
Old report: `/Users/woutut/Documents/Code/pr_reviewer/reviews/62096/review_report.md`.

**Why this PR over 52901 / 62116:** best discriminator. Findings spread across **3 genuinely distinct concerns**, mixed
severity/category, and several need real depth (subagent toolkits, markdown render path). 52901 = 5 files/1 chunk (no
chunking signal). 62116 = findings clump (6 of 11 in one chunk).

### The yardstick — old ReviewHog's 10 findings (all validated Valid by the old lenient validator)

| #   | old id | chunk | pri          | cat         | finding                                                                   |
| --- | ------ | ----- | ------------ | ----------- | ------------------------------------------------------------------------- |
| 1   | 1-1-1  | 1     | should_fix   | bug         | Action activity attribution still uses the creator on updates/deletes     |
| 2   | 1-1-2  | 1     | should_fix   | bug         | Action names not normalized/length-validated before direct model saves    |
| 3   | 1-1-3  | 1     | should_fix   | bug         | Negative list pagination args can break the action listing query          |
| 4   | 2-1-1  | 1     | should_fix   | bug         | Object-specific editor grants blocked before object access is checked     |
| 5   | 2-1-2  | 1     | should_fix   | security    | Replacing action steps is an unapproved destructive agent operation       |
| 6   | 3-1-1  | 1     | should_fix   | performance | List output not actually bounded by the action limit                      |
| 7   | 3-1-2  | 1     | should_fix   | performance | Create/update accept unbounded step payloads before sync bytecode compile |
| 8   | 2-2-1  | 2     | **must_fix** | security    | Mutating action tools reach subagents despite read-only subagent toolkits |
| 9   | 1-3-1  | 3     | should_fix   | bug         | Action tools missing from the default tool list                           |
| 10  | 2-3-1  | 3     | **must_fix** | security    | Action names interpolated into Markdown-rendered tool status              |

Spread 7/1/2 across 3 chunks · 2 must_fix (both security) · 8 should_fix · cats: 5 bug / 3 security / 2 perf.

## Variables & configs

Two independent levers, toggled by **conditional constants** (edited between runs; worker hot-reloads via nodemon):

- **Chunking:** `EXPERIMENT_FORCE_CHUNKING` (bypass the ≤1000 single-chunk gate + run the semantic chunker) +
  `CHUNK_TARGET_ADDITIONS` / `CHUNK_SOFT_MAX_ADDITIONS` lowered. Proposed small values: **target ~250, soft-max ~400**,
  by-concern, **min ~2 files/chunk** (no single-file chunks). Aim ≈ old's 3 chunks on this PR. _(tunable — see Q)_.
- **Perspective topology:** `EXPERIMENT_SEQUENTIAL_PERSPECTIVES` (bool). Parallel (current) vs sequential per chunk
  (p1 → p2 → p3), each perspective fed the prior perspectives' findings with a "dig deeper / find what they missed"
  framing (the old cumulative-pass behavior). Chunks may still run in parallel; only perspectives-within-a-chunk serialize.

### Config matrix (each = one dump)

| label             | chunking                | topology                 | purpose                                                                                                          |
| ----------------- | ----------------------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| `C0-baseline`     | current gate (→1 chunk) | parallel                 | control = today's behavior                                                                                       |
| `C1-smallchunks`  | forced, target ~250     | parallel                 | isolate the chunking lever                                                                                       |
| `C2-sequential`   | current gate (→1 chunk) | sequential               | isolate the topology lever                                                                                       |
| `C3-both`         | forced, target ~250     | sequential               | the combination (closest to old)                                                                                 |
| `C4-completeness` | forced small            | parallel + 1 gap pass    | cheaper breadth: after parallel perspectives, ONE extra pass shown all findings, asked "what did everyone miss?" |
| `C5-warmsession`  | forced small            | warm session/perspective | chunk-per-turn inside one session per perspective — context reuse + cross-chunk carryover (see below)            |
| `C6-pinnedchunks` | pinned 3-chunk split    | parallel                 | de-confound C1: is chunk STRUCTURE causal, or was the 3-chunk run's review pass lucky? (see below)               |

**7 configs × 2 runs each = 14 runs** (add a 3rd run for any config whose two runs diverge a lot). `C4` targets the
coverage gap (breadth) without paying full sequential latency — a single "loop-until-dry-lite" completeness pass; it may
be the best quality/cost point. **`C5` and `C6` run LAST (after C4, order C5 → C6)** — both need new code, implemented
together in the single gap after C4's runs so worker hot-reloads never kill an in-flight run.

### `C5-warmsession` (IN — final stage, implemented after C4's runs)

C1's chunking, but instead of `P × C` isolated single-turn sandboxes, **one warm multi-turn session per perspective**
walking the chunks as sequential turns (turn 1 = chunk 1, turn 2 = chunk 2, …). Each turn still emits its own
per-chunk `IssuesReview` artefact — chunks remain separate review units ("isolation-ish"), only the session context is
shared. Collapses `P × C` sandboxes → `P` sessions: checkout/boot/skill-pull paid once per perspective, and the session **context is reusable** — at chunk N the
agent has already internalized chunks 1..N-1 (shared types, cross-chunk contracts, PR shape), so later turns
re-establish less and can catch cross-chunk issues that isolated chunk sandboxes structurally can't. Risks to measure:
anchoring/context bloat across turns; failure floor becomes per-perspective (coarser); sequential-within-perspective
wall-clock (cross-perspective stays parallel, like C2's shape but serialized over chunks instead of perspectives).

Not new plumbing: reuses the warm-session executor helpers (`start/continue/end_sandbox_session`, same as the validate
stage) and the existing `(pass_number, chunk_id)` skip-resume via `load_perspective_results`. **Full design already in
`ARCHITECTURE.md` → "NEXT candidate — per-PERSPECTIVE warm review session" — read that first.**

Experiment wiring: `EXPERIMENT_WARM_REVIEW_SESSION` constant (default False) + `EXPERIMENT_FORCE_CHUNKING=True`
(C1 chunking). When on, `ReviewPerspectivesWorkflow` routes to a per-perspective session activity (chunks as turns,
stable chunk-id order, skip-resume splits done/pending chunks like the validate session splits issues) instead of the
`P × C` fan-out. Turn 1 = full `build_review_prompt` for the first pending chunk; later turns = lean follow-up (next
chunk's change-set + "same perspective/skill, fresh chunk — do not re-report prior chunks' findings"). Mirrors the
validate-session activity shape (one persisted `IssuesReview` per turn).

Implementation map (validated against the code 2026-07-02, mirror `validate_chunk_activity` at `activities.py:683`):

1. `constants.py` — `EXPERIMENT_WARM_REVIEW_SESSION = False`.
2. `sandbox/executor.py` — `start_sandbox_session` gains optional `runtime_adapter/model/reasoning_effort/
initial_permission_mode` kwargs (defaults None; validate callers unchanged) passed into
   `CustomPromptSandboxContext`, mirroring `run_sandbox_review` — else the session opener loses the
   REVIEW_MODEL/xhigh pins that `review_chunk_activity` applies.
3. `tools/issues_review.py` — `build_review_followup_prompt(...)`: mirror of `build_validation_followup_prompt`;
   carries the NEXT chunk's `build_chunk_prompt_context` blocks (code context / chunk json / chunk comments / file
   changes) + this chunk's covered-findings block + "same perspective skill you already loaded (do NOT re-fetch),
   fresh chunk; do not re-report problems you already reported on earlier chunks" + the `IssuesReview` schema.
4. `temporal/activities.py` — `ReviewPerspectiveSessionInput` (adds `chunk_ids: list[int]`, drops `chunk_id`) +
   `review_perspective_session_activity`: pending = chunk_ids (ascending) minus `load_perspective_results` keys for
   this pass; open session on first pending chunk (full `build_review_prompt` + model pins,
   `step_name=f"issues-review-session-p{pass}"`), follow-up per later chunk (`label=f"c{chunk_id}"`); per turn stamp
   `source_perspective` + `persist_perspective_results` for `(pass, chunk)`; error shape copied from validate:
   session-never-opened → raise (Temporal retries, failure floor sees a real outage), turn-failed-on-live-session →
   log + continue (chunk gets no result; a re-run re-attempts just that chunk); `Heartbeater` around the loop;
   `end_sandbox_session` in `finally`.
5. `temporal/workflow.py` — third branch in `ReviewPerspectivesWorkflow.run`: gather over perspectives only
   (`total = len(perspectives)` for the failure floor — coarser by design), semaphore reused; activity
   `start_to_close_timeout` must cover C chunk-turns, not one (validate's per-session timeout is the precedent —
   reuse whatever it uses, likely `_SANDBOX_TIMEOUT`-per-session; verify when implementing).
6. Tests: follow-up-prompt content test (chunk blocks present, no `skill-get`, schema present, covered-findings
   filtered to the chunk); pending-chunk skip-resume test; workflow routing-contract test for the new branch
   (mirror the existing sequential-branch tests).

**✅ BUILT 2026-07-02 (uncommitted):** all 6 map items above + C6's `plan_pinned_chunks` landed exactly as mapped;
`review_perspective_session_activity` registered in `temporal/__init__.py`; 297 review_hog tests + ruff green
(4 new tests: session skip-resume/model-pin/per-chunk-persist, warm-branch workflow routing, follow-up prompt
content, pinned-plan builder). 4-lens adversarial review workflow run before first C5 launch (results in Run log
notes).

### `C6-pinnedchunks` (IN — runs after C5; added 2026-07-02)

Motivated by C1's runs: the 3-chunk split (run 2, near-identical to old ReviewHog's) gave the best funnel (13→10→5),
but the chunker finds it stochastically — the mode is the flatter 2-chunk split (runs 1+3), which barely beats
baseline. C1's "small chunks help" conclusion is therefore **confounded** (structure vs review-pass luck, n=1 for the
3-chunk split). C6 de-confounds: **pin the exact C1-run-2 3-chunk split** (hardcoded `ChunksList` behind
`EXPERIMENT_PINNED_CHUNKS`, short-circuiting the chunker LLM like the deterministic gate does) × parallel
perspectives × 2 runs. Cheapest config there is (no chunking turn, ~9 units, ~20 lines of code).
Interpretation: pinned-3-chunks reproducing the strong funnel ⇒ structure is causal ⇒ prod lesson =
deterministic/target-seeking chunking (best-of-N chunker samples or explicit chunk-count guidance), far cheaper than
sequential's 2× wall-clock. Not reproducing ⇒ the C1-run-2 outlier was review-pass luck ⇒ stop chasing chunk
granularity. Pinned split (from `C1-smallchunks-2.md`): chunk 1 = `ee/hogai/tools/actions/core.py`; chunk 2 =
`ee/hogai/tools/actions/tool.py`, `ee/hogai/tools/actions/__init__.py`, `ee/hogai/tools/__init__.py`,
`ee/hogai/chat_agent/toolkit.py`; chunk 3 = `frontend/src/scenes/max/max-constants.tsx`,
`frontend/src/queries/schema/schema-assistant-messages.ts`, `frontend/src/queries/schema.json`,
`posthog/schema_enums.py`. Deliberately NOT adding: more topology permutations (sequential+gap etc.) or model/effort
sweeps — later rounds.

## What each run captures (the dump)

One `.md` per run in `playground/reviewhog-quality-iterations/<label>[-<n>].md`, same format for all, containing:

- **Config snapshot** (chunking constants, topology flag, model/effort) + PR head + timestamp.
- **Funnel:** raw issues found (pre-dedup, summed over perspective results) → after dedup → passed validator.
- **Cost/time:** total `$ai_generation` tokens (in+out, from local events, broken down per model) + wall-clock;
  chunk count; review-unit count (chunks × perspectives [× passes]). Reviewer and dedup/validate now both run
  on Claude, so tokens no longer split cleanly by role — the review-unit count is the reliable reviewer-cost proxy.
- **Findings list:** every finding (file:lines, priority, category, title, body) + validator verdict — the raw material
  for coverage-vs-old mapping.

The old report stays in its own format (it's the reference, not a run).

## The dump/reset harness

A single self-contained script `playground/reviewhog-quality-iterations/dump_result.py`, run via
`manage.py shell -c "exec(open(...).read())"` with a `LABEL` env var (mirrors the verify scripts already used). It
consolidates the 3 scratch scripts (verify pins / findings / show body). Loop per config:

1. Edit the experiment constants for the config; confirm the **worker hot-reloaded** (start-time > edit mtime).
2. `run_review --pr-url https://github.com/PostHog/posthog/pull/62096 --team-id 1 --user-id 1` (NO `--publish`),
   blocks ~10–15 min. (Full invocation: `flox activate -- bash -c "SANDBOX_PROVIDER=MODAL_DOCKER DJANGO_SETTINGS_MODULE=posthog.settings python manage.py run_review --pr-url https://github.com/PostHog/posthog/pull/62096 --team-id 1 --user-id 1"`.)
3. `LABEL=<config> manage.py shell -c "exec(dump_result.py)"` → writes the `.md` + metrics.
4. `manage.py reset_review_hog --yes` (DEBUG-only wipe) so the next run doesn't resume from DB.
5. Next config.

## Implementation touch-points (conditional constants branch here)

- `reviewer/constants.py` — add the `EXPERIMENT_*` constants (default = current behavior, so prod is untouched).
- Chunking: `temporal/activities.py` `split_chunks_activity` (the ≤1000 single-chunk gate at ~L455) +
  `tools/split_pr_into_chunks.py` (`plan_deterministic_chunks` / the chunking prompt soft-max). Branch on
  `EXPERIMENT_FORCE_CHUNKING` + the lowered targets.
- Topology: `temporal/workflow.py` `ReviewPerspectivesWorkflow.run` (~L117-142) — the `gather` over `(perspective,
chunk)` units becomes a per-chunk sequential loop when `EXPERIMENT_SEQUENTIAL_PERSPECTIVES`. Feed prior-perspective
  findings via a new same-run loader (perspective results already persist per `(pass,chunk)`; `load_prior_findings` is
  the cross-_turn_ analog to adapt) + a "dig deeper" prompt block in `prompts/issues_review/prompt.jinja` (the existing
  `COVERED_FINDINGS` block is close but its framing is "don't repeat"; sequential wants "find MORE beyond these").

All behind flags defaulting to current behavior → **no prod migration, no prod behavior change**.

## Pre-flight (every run)

- Worker up + hot-reloaded the new constants (nodemon watches `products`; verify start-time > edit mtime).
- **Never flip `EXPERIMENT_WARM_REVIEW_SESSION` (a workflow-read constant) while a `review-pr` workflow is active/wedged** — the reloaded worker replays open histories against the new branch → Temporal nondeterminism wedge. If a run hangs, terminate the workflow (`tctl workflow terminate`) before editing constants. (Adversarial-review finding, refuted for the happy path but real if a run is abandoned mid-flight.)
- After each C5 dump, verify units == chunks × perspectives — a systematically failing follow-up turn is skipped best-effort in-session and would otherwise look like a clean low-volume run.
- ngrok up (Modal sandbox needs it); `SANDBOX_PROVIDER=MODAL_DOCKER`.
- **Modal build-context poisoning (hit during C5 run 2, 2026-07-02 ~01:38 UTC):** in DEBUG, sandbox images build from a temp-dir context staged once per worker process (`_prepare_local_modal_build_context` is `@lru_cache`d, `products/tasks/backend/logic/services/modal_sandbox.py:304`). If macOS purges that `/var/folders/...posthog-modal-build-*` dir mid-process, EVERY later sandbox create fails with `SandboxProvisionError` ← `FileNotFoundError: .../Dockerfile.sandbox-base`, and the poisoned cache survives until the worker restarts. Symptom: run fails at a sandbox stage after earlier stages worked. Fix: restart the worker (touch any watched `.py`), then re-run `run_review` — DB skip-resume reuses all persisted results. Candidate real fix (post-experiment, tasks-owned): re-stage when the cached path no longer exists.
- DB reset from the prior run (dump BEFORE reset).
- Flox `DEBUG=True` → queues collapse to `development-task-queue`; DB `db`=localhost:5432.

## Cost/time expectations (rough)

Review sandboxes per run at Claude Opus 4.8 xhigh: C0/C2 = 3 (1 chunk × 3); C1/C3 = ~9 (≈3 chunks × 3). Sequential (C2/C3)
same sandbox count but serialized → longer wall-clock. So C3 is the most expensive/slowest; C0 the cheapest. × runs-per-config.

## Scoring & final analysis (#6)

After all dumps land, an **LLM judge** (one agent) reads each run's dump + the old report and maps every run finding to
the old 10 → **caught / missed / new-but-valid**, yielding **coverage% + precision** per run. I spot-check borderline
calls; the **user reviews the judge output at the very end**. Final report ranks configs strictly by the priority order
(quality first, then tokens, then wall-clock) and recommends the topology to adopt. With 2 runs/config, report the
better-of-two and note variance.

## Decisions (locked)

- Test PR = **#62096** (frozen, best discriminator). Validator = current (unchanged). Model = Claude Opus 4.8 xhigh (Codex was unreliable).
- **2 runs per config** (5 configs → 10 runs; add a 3rd if a config's two runs diverge). Control `C0` = current settings.
- **Quality scored by an LLM judge vs the old 10 findings**; user reviews at the end.
- **C4-completeness is IN** (5 configs total).
- **C5-warmsession is IN as a final stage (added 2026-07-02, was "future session")** — implemented after C4's runs complete (no `.py` edits while a run is in flight: nodemon restarts the worker and kills in-flight sandbox activities), then run ×2 like the others.
- **C6-pinnedchunks is IN, runs after C5 (added 2026-07-02, user approved the token cost)** — pinned C1-run-2 3-chunk split × parallel; code implemented together with C5 in the same post-C4 gap. Full rationale + the pinned file split in its section above.
- **Post-report follow-ups authorized (2026-07-02):** after the judge report, if the results raise a question one more config (C7+) would settle AND it could change the final recommendation, design + run it unattended (~2 runs, same append-only dump discipline). If the picture is conclusive, stop — no obligation to invent configs.
- **JUDGING DONE 2026-07-02 → `playground/reviewhog-quality-iterations/FINAL_REPORT.md`** (+ raw `judge_results.json`). Headlines: best topology = C4 (3/10 old-coverage, best breadth/token via the gap pass); **5 of the old 10 never surfaced in ANY of 15 runs (#1,4,7,8,10 — incl. both must_fix)** → skill-content blind spot, not topology; validator strictness costs ~1–2 more (#6 killed 7/8 times it was found); every run also found 1–3 judge-valid NEW findings the old missed. Suppression map EMPTY (no old finding pre-covered by prior bot comments — root causes differ).
- **C7-gappinned running (added post-report per the authorization):** C4 topology + pinned 3-chunk split ×2, to de-noise the C4 recommendation (its pair straddled the chunker coin-flip). Addendum lands in FINAL_REPORT.md.
- Small-chunk start = **~250 add target / ~400 soft-max**, tune during C1 to land ≈3 chunks.
  - **Tuned outcome (C1 run 1): accepted 2 chunks at 250/400.** The chunker keeps the backend concern whole (424 adds, one real seam vs frontend) per its "split only at real seams" rule — lowering the target further fights the prompt, not the numbers. 2 chunks = the lever engaged (1→2); C3/C4 reuse 250/400.
  - ~~Chunker robustness finding~~ **Retracted:** `test_action_tools.py` is excluded deterministically at fetch by `PRFilter.is_test_file` (`github_meta.py:299`) — the chunker assigned all 9 reviewable files it was given. Uniform across all configs; not a chunker gap. (A completeness guard on chunker output would still be cheap insurance, but nothing misbehaved here.)
- Results dir = `playground/reviewhog-quality-iterations/`. **No publish** on any run.
- Execution: the user will drive the loop unattended (allow-all permissions), so runs proceed without approval stops.

## Run log

| label                   | run | date       | chunks | raw→dedup→valid | total tok                      | wall-clock                                                               | dump file              | notes                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------- | --- | ---------- | ------ | --------------- | ------------------------------ | ------------------------------------------------------------------------ | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C0-baseline             | 1   | 2026-07-01 | 1      | 7→5→3           | 12.0M in / 69k out (93 gens)   | 758s (12.6 min)                                                          | `C0-baseline-1.md`     | 3 units (1×3), single-chunk gate hit as expected                                                                                                                                                                                                                                                                                                                      |
| C0-baseline             | 2   | 2026-07-01 | 1      | 7→6→4           | 10.2M in / 70k out (83 gens)   | 878s (14.6 min)                                                          | `C0-baseline-2.md`     | 3 units (1×3), consistent with run 1                                                                                                                                                                                                                                                                                                                                  |
| C1-smallchunks          | 1   | 2026-07-01 | 2      | 9→7→4           | 14.7M in / 112k out (141 gens) | 1013s (16.9 min)                                                         | `C1-smallchunks-1.md`  | 6 units (2×3). Chunker chose 2 chunks not 3 (backend 424 adds — over soft-max, kept whole at a real seam; frontend 73). `test_action_tools.py` (177 adds) absent by design — `PRFilter.is_test_file` drops test files at fetch (`github_meta.py:299`), uniformly in every config; the chunker assigned all 9 reviewable files (424+73 = 497 = full reviewable total). |
| C1-smallchunks          | 2   | 2026-07-01 | 3      | 13→10→5         | 15.0M in / 165k out (161 gens) | 968s (16.1 min)                                                          | `C1-smallchunks-2.md`  | 9 units (3×3). Chunker nondeterminism: this run split core.py / tool+toolkit / frontend — near-identical to the old ReviewHog's 3 chunks. Best funnel so far. **2-vs-3-chunk divergence → 3rd C1 run queued per plan.**                                                                                                                                               |
| C1-smallchunks          | 3   | 2026-07-01 | 2      | 6→4→3           | 11.2M in / 105k out (111 gens) | 813s (13.6 min)                                                          | `C1-smallchunks-3.md`  | 6 units (2×3), same backend/frontend split as run 1 → **2 chunks is the mode (2/3 runs); run 2's 3-chunk split is the outlier and the best funnel** — chunk granularity, not luck, looks causal for coverage. Note also big same-split variance (run 1: 9 raw vs run 3: 6 raw).                                                                                       |
| C2-sequential           | 1   | 2026-07-01 | 1      | 6→6→4           | 11.3M in / 80k out (90 gens)   | 1574s (26.2 min, DB-derived — CLI watcher reaped)                        | `C2-sequential-1.md`   | 3 serial units (3+2+1 raw per pass). **Zero dedup loss — passes didn't overlap** (vs C0 losing 1–2); same tokens as C0, 4 valid, but ~2× wall-clock.                                                                                                                                                                                                                  |
| C2-sequential           | 2   | 2026-07-02 | 1      | 4→4→3           | 10.5M in / 72k out (81 gens)   | 1488s (24.8 min)                                                         | `C2-sequential-2.md`   | 3 serial units (1+2+1 raw per pass). Again zero dedup loss, but lower raw than run 1 — sequential "dig deeper" framing may suppress volume; valid 3 ≈ C0.                                                                                                                                                                                                             |
| C3-both                 | 1   | 2026-07-02 | 3      | 11→8→6          | 14.6M in / 159k out (156 gens) | 1454s (24.2 min)                                                         | `C3-both-1.md`         | **Best valid count so far (6).** Chunker drew the GOOD 3-way split (same as C1-run-2) — forced-chunking split is now 2-vs-2 across runs (2,3,2,3): coin-flip nondeterminism. 9 serial units; modest dedup loss (3).                                                                                                                                                   |
| C3-both                 | 2   | 2026-07-02 | 2      | 5→4→4           | 10.6M in / 106k out (101 gens) | 1503s (25.1 min)                                                         | `C3-both-2.md`         | 2-chunk split again (coin-flip now 2,3,2,3,2). The 3-vs-2-chunk quality gap repeats WITHIN C3 (6 vs 4 valid) — more evidence structure drives coverage. High precision (4/5 raw validated).                                                                                                                                                                           |
| C4-completeness         | 1   | 2026-07-02 | 2      | 11→8→4          | 16.2M in / 143k out (158 gens) | 1409s (23.5 min)                                                         | `C4-completeness-1.md` | 8 units (2×3 wave + 2 gap). **Gap pass mechanically ✅** (`review-hog-completeness-gap` stamped): gap units found 4 of 11 raw (3+1) beyond the wave's 7 — real breadth add, but validator cut to 4. Most tokens of any config yet.                                                                                                                                    |
| C4-completeness         | 2   | 2026-07-02 | 3      | 19→12→8         | 18.6M in / 223k out (198 gens) | 1309s (21.8 min)                                                         | `C4-completeness-2.md` | **NEW OVERALL BEST (8 valid).** 12 units (3×3 wave + 3 gap); good 3-chunk draw (coin-flip now 2,3,2,3,2,3 — exactly 50/50); gap units added 6 of 19 raw. Structure effect now repeats within C1 (5v4), C3 (6v4), C4 (8v4). Priciest run (18.6M in).                                                                                                                   |
| C5-warmsession          | 1   | 2026-07-02 | 3      | 7→6→2           | 11.4M in / 107k out (99 gens)  | 1013s (16.9 min)                                                         | `C5-warmsession-1.md`  | **Mechanics ✅: 9/9 units persisted** (3 sessions × 3 chunk-turns, follow-up prompt + skip-resume worked; units == chunks×perspectives check passes). Cheap+fast (3 boots). BUT lowest valid yet (2); later turns found little (chunk 2: 1 raw vs C3-1's 5) — anchoring risk looks real. Good 3-chunk draw.                                                           |
| C5-warmsession          | 2   | 2026-07-02 | 3      | 10→9→3          | 12.3M in / 128k out (112 gens) | ~1208s active (20 min; 2 infra failures mid-run — see pre-flight gotcha) | `C5-warmsession-2.md`  | 9/9 units. **Anchoring pattern REPLICATES**: chunk 1 = 8 raw, chunks 2–3 ≈ silent (0–2), while parallel configs found plenty on chunk 2. Run survived a Modal build-context poisoning (dedup failed ×2) via worker restart + DB skip-resume — all 9 reviews reused, only dedup→validate re-ran.                                                                       |
| C6-pinnedchunks         | 1   | 2026-07-02 | 3      | 9→5→3           | 18.7M in / 161k out (192 gens) | 839s (14.0 min)                                                          | `C6-pinnedchunks-1.md` | **Pinned split applied ✓** (no chunking turn). 9 parallel units on the "good" structure yet well below C1-2/C3-1's funnels — first evidence review-pass variance, not just structure, drove the top runs.                                                                                                                                                             |
| C6-pinnedchunks         | 2   | 2026-07-02 | 3      | 12→8→4          | 15.9M in / 171k out (176 gens) | 965s (16.1 min)                                                          | `C6-pinnedchunks-2.md` | Pinned split ✓. **C6 verdict: pinned good-structure ⇒ 3–4 valid (mid-pack), NOT the 5–6 of the lucky draws — structure helps but review-pass variance was a co-driver of the top funnels.** ALL 15 RUNS DONE.                                                                                                                                                         |
| C7-gappinned (addendum) | 1   | 2026-07-02 | 3      | 16→11→6         | 18.9M in / 224k out (214 gens) | 1398s (23.3 min)                                                         | `C7-gappinned-1.md`    | Post-report addendum: C4 topology (gap pass) + pinned split. 12 units (9 wave + 3 gap).                                                                                                                                                                                                                                                                               |
| C7-gappinned (addendum) | 2   | 2026-07-02 | 3      | 18→11→6         | 21.5M in / 239k out (233 gens) | 1395s (23.2 min)                                                         | `C7-gappinned-2.md`    | **Replicates run 1 exactly (11 dedup / 6 valid both runs) — most consistent AND highest pair of the experiment. Gap-pass topology confirmed as the winner once structure variance is removed.**                                                                                                                                                                       |
