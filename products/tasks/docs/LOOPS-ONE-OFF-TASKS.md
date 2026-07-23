# Scheduling tasks from a PostHog product (via loops)

"Run a task in a week, use this prompt, go."
Any PostHog product can hand an agent a job to do once in the future, or on a recurring schedule, without standing up its own infrastructure.
A delayed task is just a loop with a schedule trigger: the schedule lives in Temporal (all cloud, no sandbox TTL problems), and each firing spawns an ordinary Task + TaskRun on the standard `process-task` pipeline.

Schedule config comes in two shapes:

- one-time: `{"type": "schedule", "config": {"run_at": <ISO 8601 datetime, must be in the future>}}` becomes a one-shot Temporal Schedule (`remaining_actions=1`) that fires once.
- recurring: `{"type": "schedule", "config": {"cron_expression": "0 9 * * 1-5", "timezone": "UTC"}}` (standard 5-field cron).

Always go through the facade (`products/tasks/backend/facade/loops.py`), never the models directly.

## Internal (product-managed) loops — recommended

Pass `internal=True` and an `origin_product` so the loop is owned by your flow, not a person.
Internal loops never appear in the user-facing loop CRUD, and the facade gives you helpers to find and tear them down by product.

```python
from datetime import timedelta

from django.utils import timezone

from products.tasks.backend.facade import loops as loops_facade

loop = loops_facade.create_loop(
    team_id,
    system_user,  # execution identity for GitHub authorship, OAuth and MCP, so pass a real user
    {
        "name": f"PR follow-up: {repo}#{pr_number}",
        "instructions": f"PR {pr_url} merged for report {report_id}. Verify the underlying issue is actually fixed. ...",
        "runtime_adapter": "claude",
        "model": "claude-sonnet-5",
        "repositories": [{"github_integration_id": integration_id, "full_name": repo}],
        "triggers": [{"type": "schedule", "config": {"run_at": (timezone.now() + timedelta(days=1)).isoformat()}}],
        "internal": True,
        "origin_product": "your_product",
    },
)
```

Lifecycle, all keyed by team and (optionally) your `origin_product`:

- `loops_facade.get_internal_loop(loop_id, team_id)` reads one back.
- `loops_facade.list_internal_loops(team_id, origin_product="your_product")` lists yours.
- `loops_facade.delete_internal_loop(loop_id, team_id)` soft-deletes it and pauses its schedule when the job is done.

These skip user and visibility checks by design: there is no owning end user, and the caller is trusted server code.

## User-visible loops

If a person should see and manage the automation, omit `internal` (defaults to `False`) and pass a real owning `user`.
It then shows up in that user's loop list and is managed through the normal API (`update_loop` / `soft_delete_loop`).
The PR-follow-up example above works the same way, just drop `internal` / `origin_product` and it becomes the owner's loop.

## From anywhere else

- REST: `POST /api/projects/:team_id/loops/` with the same payload, from any key with `loop:write` scope (PSAKs included).
- MCP: the `loops-create` tool, so agents can schedule their own follow-ups.

Both of these paths are user-facing (`internal=False`); the `internal` flag is backend-only.

## Gotchas

- Clean up one-time loops. The Temporal schedule exhausts itself after the single fire, but the `Loop` row stays. Call `delete_internal_loop` (or `soft_delete_loop` for a user loop) once the follow-up lands, or reconcile with `list_internal_loops(origin_product=...)`.
- One repo per loop for now (`MAX_LOOP_REPOSITORIES = 1`).
- Per-fire context is baked into `instructions` at creation time for schedule triggers, so put the report and PR specifics in the prompt.
- If you'd rather trigger on merge directly, `github` triggers support `pull_request` with an `actions: ["closed"]` filter, but "merged vs abandoned" lives in `payload.pull_request.merged`, which filters don't inspect. Doing the check in your own webhook code is cleaner.
