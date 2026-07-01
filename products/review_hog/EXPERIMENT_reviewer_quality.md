# Reviewer-quality experiment — finding the best reviewer topology

> **Working scratchpad. Survives compaction — update the Run Log + Decisions as we go.**
> Companion to `ARCHITECTURE.md`. Scope = the **reviewer stage only** (chunking + perspective topology).
> The **validator is held constant** (current strict validator) — out of scope this round.
> Model held constant: **GPT-5.5 Codex @ xhigh** for reviewers (matches the old ReviewHog). Reviewer-Claude-vs-GPT is a later round.

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

| label             | chunking                | topology              | purpose                                                                                                          |
| ----------------- | ----------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `C0-baseline`     | current gate (→1 chunk) | parallel              | control = today's behavior                                                                                       |
| `C1-smallchunks`  | forced, target ~250     | parallel              | isolate the chunking lever                                                                                       |
| `C2-sequential`   | current gate (→1 chunk) | sequential            | isolate the topology lever                                                                                       |
| `C3-both`         | forced, target ~250     | sequential            | the combination (closest to old)                                                                                 |
| `C4-completeness` | forced small            | parallel + 1 gap pass | cheaper breadth: after parallel perspectives, ONE extra pass shown all findings, asked "what did everyone miss?" |

**5 configs × 2 runs each = 10 runs** (add a 3rd run for any config whose two runs diverge a lot). `C4` targets the
coverage gap (breadth) without paying full sequential latency — a single "loop-until-dry-lite" completeness pass; it may
be the best quality/cost point.

## What each run captures (the dump)

One `.md` per run in `playground/reviewhog-quality-iterations/<label>[-<n>].md`, same format for all, containing:

- **Config snapshot** (chunking constants, topology flag, model/effort) + PR head + timestamp.
- **Funnel:** raw issues found (pre-dedup, summed over perspective results) → after dedup → passed validator.
- **Cost/time:** total GPT-5.5 tokens (in+out, from local `$ai_generation`) + Claude tokens (dedup/validate) + wall-clock;
  chunk count; review-unit count (chunks × perspectives [× passes]).
- **Findings list:** every finding (file:lines, priority, category, title, body) + validator verdict — the raw material
  for coverage-vs-old mapping.

The old report stays in its own format (it's the reference, not a run).

## The dump/reset harness

A single self-contained script `playground/reviewhog-quality-iterations/dump_result.py`, run via
`manage.py shell -c "exec(open(...).read())"` with a `LABEL` env var (mirrors the verify scripts already used). It
consolidates the 3 scratch scripts (verify pins / findings / show body). Loop per config:

1. Edit the experiment constants for the config; confirm the **worker hot-reloaded** (start-time > edit mtime).
2. `run_review --pr-url …/pull/62096 --team-id 1 --user-id 1` (NO `--publish`), blocks ~10–15 min.
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
- ngrok up (Modal sandbox needs it); `SANDBOX_PROVIDER=modal`.
- DB reset from the prior run (dump BEFORE reset).
- Flox `DEBUG=True` → queues collapse to `development-task-queue`; DB `db`=localhost:5432.

## Cost/time expectations (rough)

Review sandboxes per run at gpt-5.5 xhigh: C0/C2 = 3 (1 chunk × 3); C1/C3 = ~9 (≈3 chunks × 3). Sequential (C2/C3)
same sandbox count but serialized → longer wall-clock. So C3 is the most expensive/slowest; C0 the cheapest. × runs-per-config.

## Scoring & final analysis (#6)

After all dumps land, an **LLM judge** (one agent) reads each run's dump + the old report and maps every run finding to
the old 10 → **caught / missed / new-but-valid**, yielding **coverage% + precision** per run. I spot-check borderline
calls; the **user reviews the judge output at the very end**. Final report ranks configs strictly by the priority order
(quality first, then tokens, then wall-clock) and recommends the topology to adopt. With 2 runs/config, report the
better-of-two and note variance.

## Decisions (locked)

- Test PR = **#62096** (frozen, best discriminator). Validator = current (unchanged). Model = gpt-5.5 xhigh.
- **2 runs per config** (5 configs → 10 runs; add a 3rd if a config's two runs diverge). Control `C0` = current settings.
- **Quality scored by an LLM judge vs the old 10 findings**; user reviews at the end.
- **C4-completeness is IN** (5 configs total).
- Small-chunk start = **~250 add target / ~400 soft-max**, tune during C1 to land ≈3 chunks.
- Results dir = `playground/reviewhog-quality-iterations/`. **No publish** on any run.
- Execution: the user will drive the loop unattended (allow-all permissions), so runs proceed without approval stops.

## Run log

| label                     | run | date | chunks | raw→dedup→valid | gpt5.5 tok | claude tok | wall-clock | dump file | notes |
| ------------------------- | --- | ---- | ------ | --------------- | ---------- | ---------- | ---------- | --------- | ----- |
| _(fill as runs complete)_ |     |      |        |                 |            |            |            |           |       |
