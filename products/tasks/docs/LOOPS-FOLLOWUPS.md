# Loops: deferred hardening and next steps

Backlog left over from a loop-primitive hardening pass that closed the schedule-teardown gaps and the critical write, run and audit-log bugs.
Everything below is a known, accepted gap, not a surprise.
The "Landed" section is here for context; the rest of the doc is the actionable backlog.
File paths are relative to `products/tasks/backend/` unless noted.

## Landed

- Schedule teardown (no more zombie Temporal schedules): every path that removes a loop or trigger now tears down its Temporal Schedule, team/org/project deletion, Django admin hard-delete, soft-delete, reconciliation, trigger type-change and the one-time (`run_at`) fire.
- Critical bugs: org activity-log crash, loop hijack via ownership takeover, partial-PATCH config corruption, terminal-run resurrection, owner-deactivation not stopping the sandbox, `LoopFire` `CASCADE` wiping rate-cap history and dead run notifications.
- Hardening: retention-sweep failure isolation, reconciliation no longer swallowing the Celery soft time limit and a locked create-cap check.

## Deferred

### Needs a product or contract decision

- **Server-side confirmation for externally-triggered write-capable loops.**
  `LOOPS.md` documents a save-time confirmation for `github`/`api`-triggered loops that carry full MCP scope or `create_prs`, but nothing enforces it and the `loops-review` MCP tool is a pure echo.
  Decide the gate (an `acknowledged_external_write_risk` flag?), then enforce it in the write serializer and facade validator.
  Files: `presentation/serializers_loops.py`, `facade/loops.py` (`validate_loop_write`), `services/mcp/src/tools/loops/loopsReview.ts`.
- **Manual and API fire idempotency default.**
  When no `Idempotency-Key` header is sent, `fire_key` falls back to a fresh UUID, so a double-click or an HTTP retry under `overlap_policy=allow` spawns a duplicate paid run.
  Decide: require the header, or derive a stable default from request attributes.
  Files: `facade/loops.py` (`fire_loop_manual` / `fire_loop_api`), `presentation/views/loops.py`.

### Needs cross-repo (agent-prompt) work

- **Server-assigned run branch.**
  The self-trigger exclusion assumes a `loop/`-prefixed branch, but nothing pins the agent to one, so a `create_prs` + `watch_ci` loop's own commits can re-fire its push trigger, and two concurrent runs of one loop can pick colliding branch names.
  Generate a unique `loop/{slug}/{run-shortid}` per fire (mirror `generate_wizard_head_branch` in `prompts.py`) and thread it into the run prompt.
  Files: `logic/services/loop_runs.py`, `loop_github_events.py`, plus the agent prompt.

### Lower-priority hardening

- **Auto-pause on repeated zombie crashes.**
  The zombie-run reap in `fire_loop` uses a bulk `update()` that bypasses `handle_loop_run_terminal`, so a loop that systematically zombie-crashes never trips `consecutive_failures` or auto-pause.
  This is a judgment call: a zombie is an infrastructure failure, so auto-pausing on it may be too aggressive.
  If we want it, invoke the terminal bookkeeping per reaped run.
  File: `logic/services/loop_runs.py`.
- **Rate-cap accounting.**
  `LoopFire` rows are written before the rate checks run, so a trigger already past its own daily cap keeps writing counted rows that can exhaust the shared per-team pool, and GitHub-webhook fires have no request-level throttle.
  Exclude non-`created` outcomes from the cap counts (or check caps before writing the row), and add a per-installation or per-repository throttle ahead of webhook-sourced fires.
  Files: `logic/services/loop_runs.py`, `loop_github_events.py`.
- **Re-check enabled/deleted under the advisory lock.**
  `fire_loop` checks `enabled`/`deleted` on in-memory objects before taking the per-team advisory lock, so a pause that lands mid-flight can still race a fire through.
  Re-read and re-check inside the locked section before creating the run.
  File: `logic/services/loop_runs.py`.
- **Retention batch cap.**
  The task-retention sweep ranks with a window function but has no per-run cap or saturation log, unlike the reconciliation sweep.
  Cap it per run and log when the cap is hit.
  File: `loop_retention.py`.
- **Retention horizon vs dedup window.**
  The 200-task-per-loop retention can soft-delete a task still inside `LoopFire`'s 7-day dedup window, so a delayed retry against an old idempotency key can return a soft-deleted `task_id`.
  Skip tasks still referenced by a live `LoopFire.outcome_task_id`, or align the two horizons.
  File: `loop_retention.py`.

### Observability and docs

- **`LoopFire` read surface.**
  No admin, API or MCP surface exposes `LoopFire`, and the `disabled` and `overlap_skipped` outcomes are not always recorded, so "why didn't my loop fire" needs a raw DB query.
  Add a read-only `LoopFireAdmin` and/or a `loops/:id/fires/` action, and record every outcome.
  Files: `admin.py`, `logic/services/loop_runs.py`.
- **`LoopTrigger` activity logging.**
  Only `Loop` emits activity-log entries; trigger edits (repository, schedule, filters) are invisible, contrary to LOOPS.md's audit-trail claim.
  Add `ModelActivityMixin` plus a `sender=LoopTrigger` receiver, or log explicitly in `_sync_triggers`.
  Deprioritized.
  Files: `activity_logging.py`, `models.py`, `facade/loops.py`.
- **Reconciliation live-diff.**
  LOOPS.md claims reconciliation diffs against live Temporal state in both directions, but it only re-syncs rows already flagged `pending`/`failed`.
  Either implement the live diff (list Temporal schedules, recreate or delete to match) or narrow the doc.
  Files: `loop_reconciliation.py`, `docs/LOOPS.md`.

## Pre-existing branch drift (not from the hardening pass)

A master merge landed on the branch mid-pass. Two unrelated things to clear before the PR is fully green:

- OpenAPI generated types are stale: run `hogli build:openapi` after merging master.
- An unused `# type: ignore` in `posthog/personhog_client/converters.py` that repo-wide mypy may flag.
