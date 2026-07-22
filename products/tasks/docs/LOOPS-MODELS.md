# Loop data model

Concise reference for the three loop tables and the deltas they add to `Task` / `TaskRun`.
Source of truth: `products/tasks/backend/models.py`.
Design rationale and the wider feature live in [LOOPS.md](./LOOPS.md).

Three tables carry the feature:

- `Loop` is the automation a user (or a backend flow) defines.
- `LoopTrigger` is a firing condition attached to a loop.
- `LoopFire` is a per-fire dedup record.

Each firing spawns an ordinary `Task` + `TaskRun` on the standard `process-task` pipeline, so nothing here is a new execution engine.
All three are team-scoped through `TeamScopedRootMixin` (the fail-closed manager), and each carries its own `team` column because that manager filters on a local field, not through an FK.

## Loop

`posthog_task_loop`. The top-level object: instructions plus model config, soft-deletable, owned by a user.

| Field                                                                  | Notes                                                                                                                                                                  |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `team`                                                                 | FK to Team, `db_constraint=False` (hot table), app-level `CASCADE`.                                                                                                    |
| `created_by`                                                           | FK to User, the loop's **execution identity** for GitHub authorship, OAuth minting and MCP resolution. `SET_NULL`, `db_constraint=False`.                              |
| `name`, `description`                                                  | Display.                                                                                                                                                               |
| `visibility`                                                           | `personal` (default) or `team`. Controls who can see and edit the loop (see LOOPS.md "Access control").                                                                |
| `instructions`                                                         | The prompt delivered to the agent on every run.                                                                                                                        |
| `runtime_adapter`, `model`, `reasoning_effort`                         | Agent selection, validated against the catalog at fire time.                                                                                                           |
| `repositories`                                                         | JSON list of `{github_integration_id, full_name}`, ordered. Capped at `MAX_LOOP_REPOSITORIES` (1 today); may be empty for report-only loops.                           |
| `sandbox_environment`                                                  | Optional FK to `SandboxEnvironment` (encrypted env vars + network allowlist). `SET_NULL`.                                                                              |
| `enabled`                                                              | Pausing disables every trigger.                                                                                                                                        |
| `overlap_policy`                                                       | `skip` (default), `allow` or `cancel_previous`. Applies when a trigger fires while a run is active.                                                                    |
| `behaviors`                                                            | JSON, validated: `{create_prs, watch_ci, fix_review_comments, max_fix_iterations}`.                                                                                    |
| `connectors`                                                           | JSON: MCP Store installation ids + `posthog_mcp_scopes` (`read_only` default).                                                                                         |
| `notifications`                                                        | JSON: per channel (`push`, `email`, `slack`) an enabled flag, an event filter and channel params.                                                                      |
| `context_target`                                                       | JSON context attachment `{folder_id, name, outputs}`, or `{}` when unattached.                                                                                         |
| `internal`                                                             | `True` for loops a backend flow owns; excluded from the user-facing CRUD.                                                                                              |
| `origin_product`                                                       | Attribution for what created the loop (mirrors `Task.origin_product`).                                                                                                 |
| `last_run_at`, `last_run_status`, `last_error`, `consecutive_failures` | Bookkeeping, updated per run.                                                                                                                                          |
| `disabled_reason`                                                      | Why a non-owner pause happened (integration disconnected, owner deactivated), so the UI can explain it and a reactivation can clear it. Null for a normal owner pause. |
| `deleted`                                                              | Soft delete.                                                                                                                                                           |

Inherits `ModelActivityMixin`, so config edits land in the activity log with before/after diffs.
`_get_before_update` routes the prior-state lookup through `.unscoped()` because loop saves happen from webhook handlers and Temporal activities with no ambient team scope.

## LoopTrigger

`posthog_task_loop_trigger`. A loop has many triggers, each independently enable/disable-able.

| Field                                                | Notes                                                                                                                                                          |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `team`                                               | Own FK (denormalized off `loop.team`), `db_constraint=False`, `CASCADE`.                                                                                       |
| `loop`                                               | FK to Loop, `CASCADE`.                                                                                                                                         |
| `type`                                               | `schedule`, `github` or `api`.                                                                                                                                 |
| `enabled`                                            | Per-trigger toggle.                                                                                                                                            |
| `config`                                             | JSON, validated per type (see below).                                                                                                                          |
| `github_integration_id`, `repository`, `event_types` | Denormalized off `config` for `type=github` rows in `save()`, so webhook fan-out matches an indexed column instead of scanning the JSON. Null for other types. |
| `schedule_sync_status`                               | `pending`, `synced` or `failed`: whether the row's Temporal Schedule is in sync.                                                                               |
| `last_fired_at`                                      | Bookkeeping.                                                                                                                                                   |

`config` shapes by type:

- `schedule`: `{cron_expression, timezone}` for a recurring run, or `{run_at}` (ISO 8601, future) for a one-time run.
- `github`: `{github_integration_id, repository, events, filters}`.
- `api`: no config; fires on `POST /api/projects/:team_id/loops/:loop_id/trigger/`.

Schedule triggers are backed by a Temporal Schedule whose identity is the `schedule_id` property (`loop-trigger-{id}`).
Because that identity hangs off the row PK, trigger rows are **updated in place, never delete-and-recreated** (nested writes match by `id`).
Indexed on `(github_integration_id, repository)` for webhook routing.

## LoopFire

`posthog_task_loop_fire`. A per-fire dedup record, so schedule replays, webhook redeliveries, API retries and double-clicked manual runs never double-spawn a run.

| Field                                                      | Notes                                                                                                                                                                                    |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `team`                                                     | Own FK, `db_constraint=False`, `CASCADE`.                                                                                                                                                |
| `loop`                                                     | FK to Loop, nullable, `db_constraint=False`, `CASCADE`. Always set in practice; direct (not via trigger) so manual fires have a dedup scope and rate-cap/retention queries hit an index. |
| `loop_trigger`                                             | FK to LoopTrigger, nullable (`CASCADE`). Null for manual "run now" fires, which have no trigger.                                                                                         |
| `fire_key`                                                 | The dedup key: the Temporal workflow id (schedule), the `X-GitHub-Delivery` GUID (webhook) or the client `Idempotency-Key` (API/manual).                                                 |
| `outcome_reason`, `outcome_task_id`, `outcome_task_run_id` | The created run's ids and terminal reason, so a dedup hit (a retry) returns the original outcome instead of a bare "deduped".                                                            |

Two partial unique constraints enforce dedup:

- `(loop_trigger, fire_key)` when a trigger is present.
- `(loop, fire_key)` when there is no trigger (manual fires), so manual fires don't all collide on a shared `NULL` trigger.

## Task / TaskRun deltas

Loop-spawned tasks are system artifacts, not personal tasks:

- `Task.loop`: nullable, indexed FK back to the loop (the loop detail UI lists runs through it).
- `Task.origin_product`: gains a `loop` value; loop-spawned rows are also `internal=True`, so they never surface in a user's inbox or sidebar.
- `Task.created_by` is the loop owner, because sandbox OAuth minting reads it. Attribution, not ownership.
- `TaskRun` carries the babysitting chain (`origin_run_id`, `fix_iteration`) used to bound follow-up runs across workflow boundaries.

Everything a run uses is snapshotted into `TaskRun` state at fire time (repositories, model config, behaviors, resolved connectors, `loop_id`, `loop_trigger_id`, `trigger_context`), so editing a loop never affects in-flight or queued runs and every run stays self-describing for audit.
