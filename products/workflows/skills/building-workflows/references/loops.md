# Loops: the workflow shape PostHog Desktop reads back

A Loop in PostHog Desktop is a workflow tagged `origin_product: "loops"` with exactly this graph: one trigger, one "Create AI task" step, one exit. The Loops screens parse this shape. A workflow that has anything else still saves and runs, but Desktop shows it as "changed in the workflow editor" and makes it read-only.

Use this reference when a user asks for a loop, or when a workflow must stay editable in Desktop Loops.

## The graph

Replace only the values in angle brackets. Add nothing else.

```json
{
  "name": "<short name>",
  "description": "",
  "status": "draft",
  "origin_product": "loops",
  "exit_condition": "exit_only_at_end",
  "actions": [
    { "id": "trigger", "name": "Trigger", "type": "trigger", "config": <trigger config> },
    {
      "id": "create_task",
      "name": "Create AI task",
      "type": "function",
      "config": {
        "template_id": "template-posthog-create-task",
        "inputs": {
          "prompt": { "value": "<task prompt>" },
          "repository": { "value": "<owner/name>" },
          "skills": { "value": ["<skill name>"] }
        }
      }
    },
    { "id": "exit", "name": "Exit", "type": "exit", "config": { "reason": "Task created" } }
  ],
  "edges": [
    { "from": "trigger", "to": "create_task", "type": "continue" },
    { "from": "create_task", "to": "exit", "type": "continue" }
  ]
}
```

Task step inputs: `prompt` is required. Include `repository` only when the task works in a repository. Include `skills` only when attaching team skills, by exact name from `skill-list`, at most 10. Leave other keys out.

## Trigger config

Schedule:

```json
{ "type": "schedule" }
```

The cadence lives on a schedule row (below), not in the trigger.

GitHub event, one repository, one event type:

```json
{
  "type": "internal-event",
  "filters": {
    "source": "internal-events",
    "events": [{ "id": "$github_event_received", "type": "events" }],
    "properties": [
      { "key": "repository", "value": ["<owner/name>"], "operator": "exact", "type": "event" },
      {
        "key": "event_type",
        "value": ["<issues | issue_comment | pull_request | push>"],
        "operator": "exact",
        "type": "event"
      },
      { "key": "actor_access", "value": ["write"], "operator": "exact", "type": "event" }
    ]
  }
}
```

Keep the `actor_access` filter. It stops people without write access to the repository from starting a task.

## Schedule row

Create it with `workflows-schedule-create` after the workflow exists. `rrule` is one of these, exactly. No `BYHOUR` or `BYMINUTE`.

| Cadence        | rrule                                         |
| -------------- | --------------------------------------------- |
| Every hour     | `FREQ=HOURLY;INTERVAL=1`                      |
| Every day      | `FREQ=DAILY;INTERVAL=1`                       |
| Weekdays       | `FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,TU,WE,TH,FR` |
| One day a week | `FREQ=WEEKLY;INTERVAL=1;BYDAY=<MO..SU>`       |
| Once           | `FREQ=DAILY;COUNT=1`                          |

`starts_at` is the first run, as ISO 8601 with a UTC offset. The clock time comes from it, so pick the next occurrence at the time the user wants. `timezone` is the user's IANA timezone. Hourly schedules start on the hour.

## Test run

Test the draft before you schedule or enable it. `workflows-test-run` runs one step at a time and mocks the task creation, so nothing real is created.

1. Run with no `current_action_id` and `globals` `{ "event": { "event": "$scheduled", "properties": {} } }` for a schedule loop. A schedule trigger accepts any event in a test run. For a GitHub loop, send an `$github_event_received` event whose properties match the trigger filters, and no person.
2. Expect `nextActionId` = `create_task`. Run again with `current_action_id: "create_task"`.
3. Expect the step to complete with the mocked task call and `nextActionId` = `exit`.

A `status=skipped` on step 1 means the sample event does not match the trigger filters. Fix the sample, not the trigger.

## Not available in Loops

Notifications, auto-fix behaviors, contexts, API or manual triggers, more than one repository, more than one GitHub event type, and any other workflow step. If the user asks for one of these, say Loops does not support it yet and offer the closest loop that fits. Do not add actions, edges, or inputs to work around it.
