# Reviewer-model experiment — Opus 4.8 @ xhigh vs Sonnet 5 @ xhigh (review stage only)

> **Working scratchpad. Survives compaction — update the Run log + Decisions as we go.**
> Companion to `../../../ARCHITECTURE.md` (model-switch reference at "📍 Reference — where the sandbox model +
> reasoning-effort switch lives") and the topology round's archive at `../2026-07-reviewer-topology/`
> (read its `FINAL_REPORT.md` for the yardstick + config vocabulary). This round is a slice of
> `../../POTENTIAL_EXPERIMENTS.md` Tier-1 item 3 ("Reviewer-stage effort and model tiers"), with its
> arm C upgraded from sonnet-4-6@high to **sonnet-5@xhigh** (Sonnet 5 supports xhigh/max; 4.6 capped at high).

## Goal

Answer: **does Claude Sonnet 5 @ xhigh match Claude Opus 4.8 @ xhigh on review quality at ~2.5× lower
review-stage cost?** ($2/$10 vs $5/$25 per M in/out tokens; Sonnet is also expected faster per turn.)

Scope = the **review stage only**: the wave perspectives AND the blind-spot unit both run through
`review_chunk_activity`, the single consumer of `REVIEW_MODEL`/`REVIEW_REASONING_EFFORT`
(`reviewer/constants.py:6-7`). Chunking, dedup, and the validator sessions carry no model pin and stay on the
agent-server default (Opus) in BOTH arms — the validator is deliberately held constant, so the comparison
isolates the review model. Side benefit: the dump's per-`$ai_model` token table splits review-stage vs
support-stage cost cleanly in arm B.

## The test PR — #62096 (FROZEN, comparable)

**Review URL (exact, every run): `https://github.com/PostHog/posthog/pull/62096`**
head `ba725a897db35053525e5bdfac2c64a8b007fcb4` (re-verified 2026-07-03: unchanged, OPEN, 674 add / 1 del / 10 files).
Yardstick = the old ReviewHog's 10 findings — archived copy + coverage-matrix vocabulary in
`../2026-07-reviewer-topology/` (`fixtures/old_reviewhog_report.md`, `FINAL_REPORT.md`).

## Instruments (what changed to run this)

1. **Registry entry (permanent, prod-visible — user commits):** `"claude-sonnet-5": (low, medium, high, xhigh, max)`
   added to `CLAUDE_REASONING_EFFORTS_BY_MODEL` (`products/tasks/backend/temporal/process_task/utils.py`).
   Mirrors the agent-side `packages/agent/src/adapters/claude/session/models.ts` (sonnet-5 in
   `MODELS_WITH_EFFORT` + `MODELS_WITH_XHIGH_EFFORT`) — the agent and the LLM gateway
   (`background_agents` allowlist) already supported sonnet-5; this repo's registry was the only gap.
2. **`EXPERIMENT_PINNED_CHUNKS` (temporary — DELETE after the round):** `reviewer/constants.py` flag +
   `plan_pinned_chunks()` (`reviewer/tools/split_pr_into_chunks.py`) + a short-circuit in
   `split_chunks_activity` that wins over the persisted-chunk-set resume (the topology-round gotcha).
   Pins the C1-run-2/C6/C7 3-chunk split (core.py / tool+toolkit / frontend) for all runs → kills the
   2-vs-3-chunk coin flip that co-drove funnel variance. 3 chunks × (3 perspectives + 1 blind-spot) =
   **12 review units per run**.
3. **`REVIEW_MODEL` flip between arms (temporary):** `"claude-opus-4-8"` for arm A, `"claude-sonnet-5"` for
   arm B; `REVIEW_REASONING_EFFORT = XHIGH` in both. Reverted to Opus at the end regardless of outcome
   (a prod flip is a separate decision after live-PR confirmation).

## Config matrix (each = one dump)

| label               | REVIEW_MODEL      | effort | runs | notes                              |
| ------------------- | ----------------- | ------ | ---- | ---------------------------------- |
| `A-opus48-xhigh-N`  | `claude-opus-4-8` | xhigh  | 2    | fresh control on CURRENT prod code |
| `B-sonnet5-xhigh-N` | `claude-sonnet-5` | xhigh  | 2    | the candidate                      |

Rules: **2 runs per arm; add a 3rd if an arm's pair diverges hard** (topology-round precedent). Arm A must be
fresh — the topology archive predates productionization (prompt fixes, `WAVE_PERSPECTIVES` injection, dedup
nudge, new chunking constants), so archived C7 (18.9/21.5M in, 6 valid ×2, pinned+gap = today's shape) and the
2026-07-02 e2e run (unpinned, 2 chunks, 10→8→4, 13.1M in) are **variance priors only**, not controls.

## The run loop (per run)

1. Pre-flight (below). Confirm constants for the arm; worker hot-reloaded (start-time > constants mtime).
2. `RUN_START_EPOCH=$(date +%s)` then
   `flox activate -- bash -c "SANDBOX_PROVIDER=MODAL_DOCKER DJANGO_SETTINGS_MODULE=posthog.settings python manage.py run_review --pr-url https://github.com/PostHog/posthog/pull/62096 --team-id 1 --user-id 1"`
   (NO `--publish`; blocks ~20–25 min at 12 units).
3. Dump:
   `LABEL=<label> RUN_SECONDS=<s> RUN_START_EPOCH=<epoch> OUT_DIR=products/review_hog/eval/experiments/2026-07-reviewer-model-sonnet5/runs flox activate -- bash -c "DJANGO_SETTINGS_MODULE=posthog.settings python manage.py shell -c \"exec(open('products/review_hog/eval/scripts/dump_result.py').read())\""`
4. **Arm-B model verification (MANDATORY):** the dump's per-model token table must show the review-unit
   generations on `claude-sonnet-5`. The agent silently falls back to its default when the gateway doesn't
   serve the requested model (`sanitizedModel` — ARCHITECTURE.md:2843), so a fallback run looks normal and
   must be VOIDED, root-caused, and re-run.
5. **No-verdict check (BEFORE reset — learned from A1):** `grep -c "no-verdict" <dump>`. A validator warm
   session can die mid-run on an upstream timeout, leaving issues unruled (looks like a low valid count).
   If any: re-run `run_review` (DB skip-resume reuses every review result and re-attempts ONLY the missing
   verdicts, minutes not a full run), then re-dump over the same label. A1 skipped this (state already
   wiped when discovered; user accepted the floor) — every later run must not.
6. `flox activate -- bash -c "DJANGO_SETTINGS_MODULE=posthog.settings python manage.py reset_review_hog --yes"`
   (dump BEFORE reset).

## Pre-flight (every run — inherited from the topology round)

- Worker up + hot-reloaded current constants (nodemon watches `products/`; verify start-time > edit mtime).
- **Never edit a workflow-read constant while a `review-pr` workflow is active/wedged** — terminate first
  (`tctl workflow terminate`) or the replay wedges on nondeterminism.
- ngrok up; `SANDBOX_PROVIDER=MODAL_DOCKER`; flox `DEBUG=True` (queues collapse to `development-task-queue`).
- DB reset from the prior run already done (dump-before-reset discipline).
- Modal build-context poisoning gotcha: if a sandbox stage fails with `FileNotFoundError: .../Dockerfile.sandbox-base`,
  restart the worker (touch a watched `.py`) and re-run — DB skip-resume reuses persisted results.
- Units check on the dump: expect 12 (3 pinned chunks × (3 wave + 1 blind-spot)); pinned split applied (no
  chunking sandbox turn in the timeline).

## Scoring & final analysis

After all dumps: one **LLM judge** reads each dump + the old report (same protocol as the topology round —
root-cause matching vs the old 10 → caught/missed/new-but-valid, junk assessment), raw output to
`judge_results.json`; then a head-to-head section Opus vs Sonnet: old-coverage, total valid, junk rate,
blind-spot-unit contribution, never-surfaced-5 raw hits (observational), tokens by model, $/run
(cache-aware if derivable), wall-clock. **The user reviews judge calls at the end.** Report to `FINAL_REPORT.md`.

**Decision rule (adapted from POTENTIAL_EXPERIMENTS item 3 arm C):** parity bar = arm B's valid count ≥ arm A's
worse run, with old-coverage and junk not worse. Sonnet loses old #3 (found 17/17 archived runs) in either run
⇒ strong negative signal. A win ⇒ Sonnet 5 becomes adopt-candidate: confirm on 1–2 live PRs before any prod
flip. Either way `REVIEW_MODEL` reverts to Opus at round end.

## Decisions (locked)

- **2026-07-03 (post-report): prod FLIPPED to `claude-sonnet-5 @ xhigh`** — user chose flip-and-watch over the
  report's hold-as-candidate recommendation (quality parity + ~15–25% cost + ~15% latency won the call; dogfood
  volume makes the live-PR confirm happen in prod). Watch items on the next live reviews: `$ai_model ==
claude-sonnet-5` on review units, finding depth vs the Opus era, consider-grade noise volume. Revert = the one
  `REVIEW_MODEL` constant.

- Pinned 3-chunk split for ALL runs (user, 2026-07-03) — model comparison over prod realism; prod-realistic
  confirmation happens post-win on live PRs.
- Registry entry is a real prod change, committed (user, 2026-07-03); pin instrument + model flip stay
  uncommitted-local and are removed after the round.
- **The user commits everything themselves — the agent only edits/stages files (2026-07-03).**
- 2 runs/arm + divergence rule; xhigh both arms; validator/dedup/chunking untouched; NO publish on any run.
- Results dir: `runs/` next to this file.

## Run log

| label           | run | date       | chunks       | units | raw→dedup→valid | review-stage model verified                                                          | total tok (in/out)                                                                                      | wall-clock                                                                                                                                                                                                                                                                                                                                          | dump file              | notes                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| --------------- | --- | ---------- | ------------ | ----- | --------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A-opus48-xhigh  | 1   | 2026-07-03 | 3 (pinned ✓) | 12    | 15→11→3\*       | ✓ opus-4-8 (196 gens)                                                                | 19.3M/219k opus (+0.86M sonnet-4-6 = local background noise: summarize-team-sessions cron, not the run) | 1444s (24.1 min)                                                                                                                                                                                                                                                                                                                                    | `A-opus48-xhigh-1.md`  | Pinned split applied, no chunking turn. In-tokens ≈ C7 (18.9M). **\*valid=3 is a FLOOR: the validation-c1 warm session died mid-run on an upstream API timeout (`send_followup_task_message_failed`/`upstream_timeout`) after 3 verdicts → 4 of 11 findings no-verdict (all chunk 1; 2 of them should_fix). User decision: keep as-is, no restore (DB already reset); judge must treat no-verdict findings separately, not as dismissed.** |
| A-opus48-xhigh  | 2   | 2026-07-03 | 3 (pinned ✓) | 12    | 15→8→6          | ✓ opus-4-8 (247 gens)                                                                | 23.0M/245k opus                                                                                         | 1504s (25.1 min)                                                                                                                                                                                                                                                                                                                                    | `A-opus48-xhigh-2.md`  | Clean run, 0 no-verdict. Matches C7 exactly (raw 15 vs 16-18, 6 valid). Same raw volume as A1 (15) — A1's low valid confirmed as the validator-session death + dedup draw, not review-stage variance.                                                                                                                                                                                                                                      |
| B-sonnet5-xhigh | 1   | 2026-07-03 | 3 (pinned ✓) | 12    | 17→11→6         | ✓ **sonnet-5 (337 gens review)**, opus 44 gens = dedup+validate (support, by design) | 34.5M/240k sonnet-5 + 2.9M/37k opus                                                                     | 1253s (20.9 min)                                                                                                                                                                                                                                                                                                                                    | `B-sonnet5-xhigh-1.md` | Clean, 0 no-verdict. Valid 6 = ties A2. **More turns + tokens for the same units** (337 gens / 34.5M review-stage in vs A2's ~200 / ~20M — ~1.7×), so the 2.5× price edge nets out to ~30% cheaper naive; 4 min faster.                                                                                                                                                                                                                    |
| B-sonnet5-xhigh | 2   | 2026-07-03 | 3 (pinned ✓) | 12    | 18→14→6         | ✓ sonnet-5 (425 gens review), opus 52 gens support                                   | 37.5M/295k sonnet-5 + 4.4M/44k opus                                                                     | 2368s (39.5 min, workflow-derived — CLI watcher was stopped mid-run; workflow unaffected). **Effective ≈ 21 min:** one wave unit's first attempt failed at the sandbox layer; Temporal retry attempt 2 started 11:42:45 (21 min in) and every later stage waited on it. Model-independent infra flake (user-spotted; verified in workflow history). | `B-sonnet5-xhigh-2.md` | Clean, 0 no-verdict. 6 valid again — arm B replicates its own result (6/6) like C7 did. Corrected wall-clock story: sonnet-5 ≈ 21 min in BOTH runs vs opus 24–25.                                                                                                                                                                                                                                                                          |
