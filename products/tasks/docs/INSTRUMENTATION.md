# Tasks Backend Instrumentation

All analytics events tracked from the tasks backend via `posthoganalytics.capture()`.

All events include group analytics via `groups()` from `posthog.event_usage`, which sets `instance`, `organization`, `customer`, and `project` groups where available.

## Standard Properties

### Task events

All events captured via `Task.capture_event()` automatically include:

| Property         | Type   | Description                                |
| ---------------- | ------ | ------------------------------------------ |
| `task_id`        | `str`  | UUID of the task                           |
| `team_id`        | `int`  | Team ID                                    |
| `title`          | `str`  | Task title                                 |
| `description`    | `str`  | Task description (truncated to 500 chars)  |
| `origin_product` | `str`  | Origin product enum value                  |
| `repository`     | `str?` | Repository in `org/repo` format (nullable) |

### TaskRun events

All events captured via `TaskRun.capture_event()` automatically include:

| Property          | Type   | Description                                                             |
| ----------------- | ------ | ----------------------------------------------------------------------- |
| `task_id`         | `str`  | UUID of the task                                                        |
| `run_id`          | `str`  | UUID of the run                                                         |
| `team_id`         | `int`  | Team ID                                                                 |
| `repository`      | `str?` | Repository in `org/repo` format (nullable)                              |
| `loop_id`         | `str?` | UUID of the loop that spawned this run, from run state (nullable)       |
| `loop_trigger_id` | `str?` | UUID of the loop trigger that fired this run, from run state (nullable) |
| `environment`     | `str`  | `cloud` or `local` (defaults to `cloud`)                                |
| `mode`            | `str`  | Execution mode (e.g. `background`)                                      |

## Task Model Events

Source: `products/tasks/backend/models.py`

### `task_created`

Tracked when a new Task is saved. Additional properties:

| Property          | Type   | Description                       |
| ----------------- | ------ | --------------------------------- |
| `has_json_schema` | `bool` | Whether a JSON schema is attached |

### `task_run_created`

Tracked when `Task.create_run()` is called. Additional properties:

| Property              | Type   | Description                         |
| --------------------- | ------ | ----------------------------------- |
| `run_id`              | `str`  | UUID of the created run             |
| `mode`                | `str`  | Execution mode                      |
| `environment`         | `str`  | `cloud` or `local`                  |
| `is_resume`           | `bool` | Whether this resumes a previous run |
| `has_pending_message` | `bool` | Whether there's a pending message   |

### `task_deleted`

Tracked when `Task.soft_delete()` is called. Additional properties:

| Property           | Type    | Description                 |
| ------------------ | ------- | --------------------------- |
| `duration_seconds` | `float` | Seconds since task creation |

## TaskRun Model Events

Source: `products/tasks/backend/models.py`

### `task_run_completed`

Tracked when `TaskRun.mark_completed()` is called. Additional properties:

| Property           | Type    | Description                      |
| ------------------ | ------- | -------------------------------- |
| `duration_seconds` | `float` | Time from creation to completion |

### `task_run_failed`

Captured once per DB transition to `FAILED`, by whichever component performs it:
`TaskRun.mark_failed()` (janitor sweeps via the facade), the `update_task_run_status` Temporal activity (workflow failures), the facade run PATCH path (agent-reported failures), or `_terminalize_unstarted_task_run` (workflow dispatch failures).
Known gap: the zombie-run reap in `loop_runs.py::fire_loop` bulk-updates stale runs to `FAILED` without capturing, so the documented `stale_run_reaped` value below never actually appears.
Additional properties:

| Property           | Type    | Description                                                                                                                                                                                                    |
| ------------------ | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `error_type`       | `str`   | Stable failure source: exception class name (workflow failures), `agent_reported`, `stale_queued_cleanup`, `workflow_start_failed`, `followup_delivery_failed`, `stale_run_reaped`; `unspecified` when unknown |
| `error_message`    | `str`   | Error message (truncated to the **last** 500 chars — the root cause sits at the tail)                                                                                                                          |
| `duration_seconds` | `float` | Time from creation to failure                                                                                                                                                                                  |

### `task_run_cancelled_terminal`

Captured once per DB transition to `CANCELLED`, by whichever component performs that transition. Every writer of the status is covered:

| Writer                                                      | Cancellations it owns                                              | `cancel_source`                                     |
| ----------------------------------------------------------- | ------------------------------------------------------------------ | --------------------------------------------------- |
| `update_task_run_status` Temporal activity                  | Workflow-driven cancellations                                      | Read off `TaskRun.state`, `unspecified` when absent |
| Facade run PATCH (`facade/api.py::update_task_run`)         | API, webhook and workflow-gone fallback cancellations              | Read off `TaskRun.state`, `unspecified` when absent |
| `loop_runs.py::fire_loop` (`CANCEL_PREVIOUS` overlap)       | A run displaced by a newer fire of the same loop                   | `loop_overlap_cancel_previous`                      |
| `loop_lifecycle.py` (loop pause, runs authored by the user) | In-flight loop runs cancelled on owner deactivation or org removal | `owner_deactivated` / `owner_removed_from_org`      |

The loop paths bulk-update the rows and then signal `complete_task`, so the status activity that follows finds no transition left and skips its capture. They call `loop_service.capture_loop_runs_cancelled_terminal` instead, which is also why their property values are per-site literals rather than reads off `TaskRun.state`.

Not to be confused with [`task_run_cancelled`](#task_run_cancelled-no-longer-emitted-by-the-process_task-workflow), a different event with a different shape: the `execute_sandbox` workflow emits it (for any origin product) when the workflow itself is cancelled, and `capture_relay_command_telemetry` emits it for PostHog AI relay turn-cancels, meaning "the agent's current turn was cancelled". Neither is keyed on the run reaching a terminal state. Additional properties:

| Property           | Type    | Description                                                                                                                                                           |
| ------------------ | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cancel_reason`    | `str`   | Cancellation message. The activity and PATCH paths pass the run's message through (truncated to the **last** 500 chars), the loop paths use a fixed per-site sentence |
| `cancel_source`    | `str`   | Cancellation origin, per the table above                                                                                                                              |
| `duration_seconds` | `float` | Time from creation to cancellation                                                                                                                                    |

## Loop Fire Metrics

Source: `products/tasks/backend/metrics.py`, emitted from `products/tasks/backend/logic/services/loop_runs.py::fire_loop`.

Prometheus counters (not `posthoganalytics.capture()` events):

| Metric                                 | Labels   | Description                                                                                                                                                                 |
| -------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `posthog_tasks_loop_fire_total`        | `reason` | One increment per `fire_loop()` call, labeled with the `LoopFireResult.reason` outcome (`created`, `deduped`, `overlap_skipped`, `rate_capped`, `disabled`, `gate_blocked`) |
| `posthog_tasks_loop_auto_paused_total` | (none)   | One increment each time a loop is auto-paused after `consecutive_failures` reaches the threshold                                                                            |

`fire_loop()` also logs `loop_fire_created` (standard Python logger, not analytics) with `loop_id`, `loop_trigger_id`, `task_id`, `task_run_id` and `actor_id` on every successful fire.

## Workflow Events

Source: `products/tasks/backend/temporal/process_task/workflow.py`

These events are tracked via `_track_workflow_event()` which calls the `track_workflow_event` Temporal activity. All workflow events include `organization` and `project` group analytics and are enriched with Temporal context properties (see [Temporal Context](#temporal-context-enrichment)).

### `task_run_started`

Tracked when the workflow begins execution.

| Property     | Type  | Description                     |
| ------------ | ----- | ------------------------------- |
| `run_id`     | `str` | UUID of the run                 |
| `task_id`    | `str` | UUID of the task                |
| `repository` | `str` | Repository in `org/repo` format |
| `team_id`    | `int` | Team ID                         |

### `sandbox_started`

Tracked after sandbox and agent server are provisioned.

| Property        | Type   | Description                     |
| --------------- | ------ | ------------------------------- |
| `run_id`        | `str`  | UUID of the run                 |
| `task_id`       | `str`  | UUID of the task                |
| `sandbox_id`    | `str`  | Sandbox identifier              |
| `sandbox_url`   | `str`  | URL of the sandbox              |
| `used_snapshot` | `bool` | Whether a snapshot was used     |
| `repository`    | `str`  | Repository in `org/repo` format |

### `task_run_cancelled` (no longer emitted by the `process_task` workflow)

`process_task/workflow.py` records **nothing** on `CancelledError`: the `update_task_run_status` activity owns the terminal capture on the DB transition and emits [`task_run_cancelled_terminal`](#task_run_cancelled_terminal). Unlike `task_run_failed`, a `track_workflow_event` call with the capture suppressed records no metrics and no logs either, so the call is gated out behind the `tasks-drop-cancelled-workflow-event` patch and only replays of pre-rollout histories still schedule it.
The event name is still emitted by the `execute_sandbox` workflow (properties below) and by `capture_relay_command_telemetry` for PostHog AI relay turn-cancels.

| Property     | Type  | Description                     |
| ------------ | ----- | ------------------------------- |
| `run_id`     | `str` | UUID of the run                 |
| `task_id`    | `str` | UUID of the task                |
| `repository` | `str` | Repository in `org/repo` format |
| `team_id`    | `int` | Team ID                         |

### `task_run_failed` (workflow, metrics only)

Recorded when the workflow fails with an exception — **not captured as an analytics event** (the `update_task_run_status` activity owns the analytics capture on the DB transition, see above).
The workflow emission feeds the `posthog_tasks_task_run_failed_total` Prometheus counter and structured logging with these properties:

| Property        | Type  | Description                                 |
| --------------- | ----- | ------------------------------------------- |
| `run_id`        | `str` | UUID of the run                             |
| `task_id`       | `str` | UUID of the task                            |
| `error_type`    | `str` | Exception class name                        |
| `error_message` | `str` | Error message (truncated to last 500 chars) |
| `sandbox_id`    | `str` | Sandbox identifier (if available)           |

## Webhook Events

Source: `products/tasks/backend/webhooks.py`

These events use `TaskRun.capture_event()` so include all [TaskRun standard properties](#taskrun-events).

### `pr_created`

Tracked when a GitHub `pull_request.opened` webhook is received. Additional properties:

| Property | Type  | Description   |
| -------- | ----- | ------------- |
| `pr_url` | `str` | GitHub PR URL |

### `pr_merged`

Tracked when a GitHub `pull_request.closed` webhook is received with `merged=true`. Same additional properties as `pr_created`.

### `pr_closed`

Tracked when a GitHub `pull_request.closed` webhook is received with `merged=false`. Same additional properties as `pr_created`.

## API Events

Source: `products/tasks/backend/api.py`

### `code_invite_redeemed`

Tracked when a user redeems a Desktop invite. Includes `organization` group analytics. No additional properties.

## Activity Observability Events

Source: `products/tasks/backend/temporal/observability.py`

These events are tracked via `log_activity_execution()` context manager and are enriched with Temporal context properties. Groups can be passed through to `track_event()`.

### `process_task_activity_started`

| Property        | Type  | Description                                                    |
| --------------- | ----- | -------------------------------------------------------------- |
| `activity_name` | `str` | Name of the activity                                           |
| `...context`    | `Any` | Additional context kwargs passed to `log_activity_execution()` |

### `process_task_activity_completed`

Same properties as `process_task_activity_started`.

### `process_task_activity_failed`

| Property        | Type  | Description                                                    |
| --------------- | ----- | -------------------------------------------------------------- |
| `activity_name` | `str` | Name of the activity                                           |
| `error_type`    | `str` | Exception class name                                           |
| `error_message` | `str` | Error message (truncated to 500 chars)                         |
| `...context`    | `Any` | Additional context kwargs passed to `log_activity_execution()` |

## Temporal Context Enrichment

Events tracked from Temporal activities or workflows are automatically enriched with context properties by `track_event()` in `observability.py`:

**When in an activity:**

| Property                   | Type  |
| -------------------------- | ----- |
| `temporal_activity_id`     | `str` |
| `temporal_activity_type`   | `str` |
| `temporal_workflow_id`     | `str` |
| `temporal_workflow_run_id` | `str` |
| `temporal_attempt`         | `int` |

**When in a workflow (non-replay):**

| Property                   | Type  |
| -------------------------- | ----- |
| `temporal_workflow_id`     | `str` |
| `temporal_workflow_run_id` | `str` |
| `temporal_workflow_type`   | `str` |
