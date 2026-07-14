# One-off scheduled tasks via loops

"Run a task in a week, use this prompt, go."
Loops support one-time triggers, so a delayed task is just a loop with a `run_at` trigger.
All cloud, no sandbox TTL problems: the schedule lives in Temporal, not inside a running task.

## From backend code (self-driving PR follow-up)

You already sit in the PR-merge webhook path (`handle_pull_request_event` is what resolves linked SignalReports).
Do the "is this associated with a report" check there, then schedule the follow-up:

```python
from products.tasks.backend.facade import loops as loops_facade

loops_facade.create_loop(
    team_id,
    system_user,  # runs execute as this user (GitHub authorship, OAuth, MCP), so pass a real one
    {
        "name": f"PR follow-up: {repo}#{pr_number}",
        "instructions": f"PR {pr_url} merged for report {report_id}. Verify the underlying issue is actually fixed. ...",
        "runtime_adapter": "claude",
        "model": "claude-sonnet-5",
        "repositories": [{"github_integration_id": integration_id, "full_name": repo}],
        "triggers": [{"type": "schedule", "config": {"run_at": (timezone.now() + timedelta(days=1)).isoformat()}}],
    },
)
```

`run_at` must be an ISO 8601 datetime in the future.
The trigger becomes a one-time Temporal Schedule (`remaining_actions=1`), fires once and creates an internal Task + TaskRun on the normal `process-task` pipeline.
Only import via the facade (`products/tasks/backend/facade/loops.py`), never the models.

## From anywhere else

- REST: `POST /api/projects/:team_id/loops/` with the same payload, any key with `loop:write` scope (PSAKs included).
- MCP: the `loops-create` tool, so agents can schedule their own follow-ups.

## Gotchas

- One-time loops don't clean themselves up yet. The Temporal schedule exhausts itself but the Loop row stays. At loop-per-PR volume, call `loops_facade.soft_delete_loop(loop_id, team_id, user)` once the follow-up lands, or ping #team-tasks for auto-archival.
- One repo per loop for now (`MAX_LOOP_REPOSITORIES = 1`).
- Per-fire context is baked into `instructions` at creation time for schedule triggers, so put the report and PR specifics in the prompt.
- If you'd rather trigger on merge directly, `github` triggers support `pull_request` with an `actions: ["closed"]` filter, but "merged vs abandoned" lives in `payload.pull_request.merged` which filters don't inspect. Doing the check in your own webhook code is cleaner.
