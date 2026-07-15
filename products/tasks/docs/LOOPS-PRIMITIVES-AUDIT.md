# Loops primitives audit

Adversarial multi-agent audit of the loops backend on `feat/loops`, judged as a platform primitive that internal products (facade), external callers (REST/PSAK), and MCP agents will build on.
Nine finders (six review dimensions plus three builder personas) produced 49 raw findings, deduped to 30, then each was run past a refute-by-default verifier: 26 confirmed, 4 refuted.
The scariest confirmed findings were re-checked by hand against the code.

Verdict: the happy path is solid, but the primitives are not yet safe to build on.
The recurring root cause is that the Temporal Schedule is a second source of truth that drifts from the DB, and several fire/lifecycle paths mutate a row without driving the workflow that owns the real work.
There is also a genuine cross-tenant write.

## Blockers

### 1. Cross-tenant loop corruption via forged `TaskRun.state.loop_id`

`facade/api.py:1828` merges arbitrary `state` keys (no blocklist) on the ordinary run-update endpoint, then `api.py:1854` unconditionally calls `handle_loop_run_terminal`, which does `Loop.objects.unscoped().select_for_update().get(id=loop_id)` at `loop_runs.py:470` with no team check.
An attacker with `task:write` in team B PATCHes their own run with `{"state": {"loop_id": "<team-A-loop>"}, "status": "failed", "error_message": "..."}` and corrupts a victim loop in team A: overwrites `last_error`, increments `consecutive_failures`, and after five hits auto-disables the loop, pauses its Temporal schedules, and fires notifications to the victim's team.
Verified end to end through the public endpoint.
Fix (S): treat `loop_id` as a protected state key in `update_task_run`, and team-scope the lookup in `handle_loop_run_terminal` (pass the run's `team_id`, use `for_team`).

### 2. Personal loop config leaks to any teammate via the activity log API

`GET /api/projects/:team/activity_log/?scope=Loop` returns full loop config and instructions to any member of a team with the audit-logs feature, because `apply_activity_visibility_restrictions` (`activity_log.py:375`) has no `Loop` entry and the viewset filters only by team.
Personal loops are supposed to be owner-only.
Fix (S): add per-request owner scoping for the `Loop` scope in the activity-log visibility table.

### 3. Changing a trigger's type via PATCH orphans its Temporal Schedule

`_sync_triggers` (`facade/loops.py:596`) mutates an existing trigger's `type`/`config` in place, then calls `sync_loop_trigger_schedule`, which no-ops unless `type == SCHEDULE`.
Flip a schedule trigger to `github` or `api` and the old cron schedule stays live forever, firing `run-loop` against a repurposed row.
Worse, later deletion also gates on the current type, so the zombie schedule is unreachable through the API, MCP, or a full loop delete; only a manual Temporal admin action stops it.
Fix (S): in `_sync_triggers`, tear down the old schedule (using the pre-mutation type) before applying a type change, and make `delete_loop_trigger_schedule` idempotent on `schedule_id` rather than trusting the row's current type.

### 4. `overlap_policy=cancel_previous` and lifecycle pause only flip the DB row

The `CANCEL_PREVIOUS` branch and `_pause_loop_and_cancel_runs` do a raw `TaskRun.objects.filter(...).update(status=CANCELLED)` (`loop_runs.py:180`, `loop_lifecycle.py`) without signaling the running `ProcessTaskWorkflow`, unlike the real `cancel_task_run` facade.
The displaced sandbox keeps executing, and `update_task_run_status` has no terminal-state guard, so the abandoned run later overwrites `CANCELLED` back to `COMPLETED`.
Net: two sandboxes run the same loop against the same repo at once (both can open PRs), and the audit trail lies.
The deactivated-user path has the same shape, so an in-flight run keeps executing under a deactivated user's credentials.
Fix (M): route cancellation through the workflow signal, and guard `update_task_run_status` against overwriting a terminal status.

### 5. `LoopFire` dedup is committed before the run is created, so retries swallow fires

`fire_loop` commits the `LoopFire` dedup row (`loop_runs.py:132`) before `_create_loop_task_and_run` runs and before the result is known.
If task creation then hits a transient error, the Temporal activity retries with the same `fire_key`, hits the unique constraint, returns `reason='deduped'` with null ids, and the activity completes "successfully": that scheduled tick silently produces no run, no error logged.
An API caller retrying an `Idempotency-Key` after a `gate_blocked`/`rate_capped` response also can't recover the original outcome.
Fix (M): persist the fire outcome (task/run ids, terminal reason) on `LoopFire` so a dedup hit returns the original result instead of an empty success.

### 6. Resuming a loop via `enabled: true` never resumes its Temporal Schedule

`resume_loop_schedules` (`loop_service.py:169`) has exactly one occurrence in the codebase: its own definition.
`update_loop` never calls it, so the documented recovery action (toggle `enabled` back on after an auto-pause) returns 200, sets the row, and leaves the schedule paused forever.
The loop silently never fires again.
Verified: zero call sites.
Fix (S): call `pause_loop_schedules`/`resume_loop_schedules` from `update_loop` on the `enabled` transition.

### 7. `create_prs` default flips from false to true between read and fire

The serializer and `GET /loops/{id}` present an omitted `behaviors` as report-only (`create_prs: false`, per the field's own help text), but the fire-time fallback is `bool((loop.behaviors or {}).get("create_prs", True))` at `loop_runs.py:374`.
A caller who opts out of PR creation gets an agent that can still push branches and open PRs, and can't detect it from the read path.
This silently defeats the report-only safety boundary against untrusted trigger payloads.
Fix (S): normalize `behaviors` to explicit defaults at write time and align the fire-time fallback to `False`.

## Majors (grouped by theme)

Schedule/DB divergence (the structural weak spot):

- No reconciliation sweep for `schedule_sync_status` in `FAILED`/`PENDING` (`loop_service.py:129`). A brief Temporal outage during create/edit strands a trigger or orphans a schedule with no recovery. Fix (M): add a celery-beat sweep modeled on `sweep_loop_task_retention_task`.
- `fire_loop` never re-checks `trigger.enabled`, only `loop.enabled`/`deleted` (`loop_runs.py:129`). A disabled trigger whose pause failed still fires. Fix (S): add the guard at the fire chokepoint.

Fire correctness:

- Manual "run now" passes `trigger=None`, which skips the entire dedup path, so `Idempotency-Key` is silently ignored on `POST /loops/:id/run/` (`facade/loops.py:644`). Fix (M): add a nullable `loop` FK to `LoopFire` and dedup manual fires on it.
- Per-loop and per-team rate caps use an unlocked `COUNT` (`loop_runs.py:150`), so concurrent fires burst past the cap. Fix (S): move the count inside the advisory-lock transaction.

Tenancy:

- `fire_loop_api` doesn't filter `internal=True` (`facade/loops.py:652`) while the read/write queries do, so an internal automation with an api trigger is silently externally firable. Fix (S): add `internal=False`.

Facade as a real contract for internal teams:

- `internal=True` loops are unreachable through the facade after creation (`facade/loops.py:358`): no get/list/update/delete filters on `internal`. Signals can create a one-off internal follow-up loop but can't check, cancel, or clean it up. Fix (S): add an internal-only facade CRUD surface.
- `create_loop`/`update_loop` skip the cross-field and cross-team validation the REST serializer does (`facade/loops.py:493`), so an in-code caller can reference another team's `SandboxEnvironment` or an unknown model and explode at fire time. Fix (M): move validation into a shared `validate_loop_write` the facade calls.
- `behaviors`/`connectors`/`notifications` JSON is validated only at the DRF edge (`facade/loops.py:233`). A facade-bypass or backfill write of a malformed dict crashes every subsequent list read of the team's loops. Fix (S): harden the `_*_dto` parsers to never raise.
- Owner-deactivation auto-pause records no reason, sends no notification, and has no reactivation hook (`loop_lifecycle.py:43`). Nobody can tell why a loop is paused. Fix (M): add `Loop.disabled_reason` and a real resume path.

External REST/PSAK DX:

- PSAK fire-and-forget: a service key can trigger a loop but has no PSAK-authenticated endpoint to read back run status, output, or PR URL (`facade/loops.py:119`). This breaks the primary external use case (fire from CI, then check the result). Fix (S): allow PSAK to poll `runs/` for loops it can trigger.
- `run_at` without a UTC offset raises an uncaught `TypeError` and returns 500 instead of 400 (`serializers_loops.py:122`). Fix (S): treat naive `run_at` as UTC, matching what `loop_service.py` already does.
- `LoopFireRunSerializer.reason` omits `team_rate_capped`, a value the service actually returns (`serializers_loops.py:511`), so the generated TypeScript union is wrong. Fix (S): add the value.
- `loops-partial-update`'s documented ownership-takeover behavior is not implemented (`facade/loops.py:412`). An agent following the tool's own docs to fix a teammate's team loop gets a permission error. Fix (M): add an explicit `take_ownership` flag.

MCP agent surface:

- No MCP tools to preview a loop or read back run outcomes: `loops-preview-create` and `loops-runs-retrieve` are disabled in `tools.yaml` though both are fully implemented and scope-gated server-side. An agent can create and fire but can't verify or check results. Fix (S): enable both tools and rebuild.

Scale:

- `LoopFire` has no retention and its per-fire rate-cap queries have no supporting index (`loop_runs.py:207`), on a table written on every fire. Fix (S): index `(loop_trigger__loop, created_at)` and add a bounded retention sweep.

## Minors

- The `trigger/` endpoint's rate limiting is undocumented in OpenAPI.
- The `version` key documented on JSON config fields is unimplemented (dead contract, remove or enforce).
- The overlap-policy active-run check is an unindexed JSON scan on every fire, bypassing the `Task.loop` FK the same PR added.
- GitHub trigger branch/label filters have zero test coverage, including the untested `pull_request` branch-source choice.

## Refuted (do not act on)

- "Response serializer fields have no help_text" — they do.
- "Ownerless (user=None) loops freeze for identity edits" — handled.
- "Fire-rate caps return 200 with a flag instead of 429" — intentional and consistent.
- "No cross-product signal for loop-run-finished" — out of scope, not a defect.

## Coverage note

12 lowest-severity findings were dropped before verification to fit the budget.
Two worth a second look: `create_loop` has no idempotency primitive (a retried create from a webhook handler always makes a duplicate loop + trigger + schedule), and there is no documented service/system-identity convention for loop ownership.
Both bite the signals PR-follow-up use case directly.

## Suggested sequencing

1. Security first: findings 1 and 2 (cross-tenant write, activity-log leak) before this leaves draft.
2. Schedule/DB integrity: findings 3, 6 and the reconciliation sweep, since they make loops silently stop or double-fire.
3. Fire correctness: findings 4, 5 and the two idempotency majors, before external callers depend on retries.
4. Facade contract: the internal-reachability and validation majors, before signals ships PR follow-up on top.
5. DX polish: PSAK readback, the 500, the MCP tools, the enum.
