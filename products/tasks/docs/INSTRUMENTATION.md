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

| Property      | Type   | Description                                |
| ------------- | ------ | ------------------------------------------ |
| `task_id`     | `str`  | UUID of the task                           |
| `run_id`      | `str`  | UUID of the run                            |
| `team_id`     | `int`  | Team ID                                    |
| `repository`  | `str?` | Repository in `org/repo` format (nullable) |
| `environment` | `str`  | `cloud` or `local` (defaults to `cloud`)   |
| `mode`        | `str`  | Execution mode (e.g. `background`)         |

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

Tracked when `TaskRun.mark_failed()` is called. Additional properties:

| Property           | Type    | Description                            |
| ------------------ | ------- | -------------------------------------- |
| `error_type`       | `str`   | Exception class name                   |
| `error_message`    | `str`   | Error message (truncated to 500 chars) |
| `duration_seconds` | `float` | Time from creation to failure          |

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

### `task_run_cancelled`

Tracked when the workflow is cancelled via `CancelledError`.

| Property     | Type  | Description                     |
| ------------ | ----- | ------------------------------- |
| `run_id`     | `str` | UUID of the run                 |
| `task_id`    | `str` | UUID of the task                |
| `repository` | `str` | Repository in `org/repo` format |
| `team_id`    | `int` | Team ID                         |

### `task_run_failed` (workflow)

Tracked when the workflow fails with an exception.

| Property        | Type  | Description                            |
| --------------- | ----- | -------------------------------------- |
| `run_id`        | `str` | UUID of the run                        |
| `task_id`       | `str` | UUID of the task                       |
| `error_type`    | `str` | Exception class name                   |
| `error_message` | `str` | Error message (truncated to 500 chars) |
| `sandbox_id`    | `str` | Sandbox identifier (if available)      |

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

Tracked when a user redeems a Code invite. Includes `organization` group analytics. No additional properties.

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
