# Customer analytics tasks

`system.customer_tasks` contains customer follow-up tasks, with task and linked-account access controls applied.
These are separate from AI coding tasks.

Columns: `id` (UUID), `team_id`, `account_id` (nullable UUID), `name`, `description`, `status`,
`assigned_to_id`, `due_at`, `completed_at`, `completed_by_id`, `created_by_id`, `archived_at`, `created_at`, `updated_at`.
User IDs are PostHog project members. Status is `open`, `in_progress`, `completed`, or `canceled`.

```sql
SELECT id, name, assigned_to_id, due_at
FROM system.customer_tasks
WHERE archived_at IS NULL AND status IN ('open', 'in_progress')
ORDER BY due_at ASC
LIMIT 100
```

Use `posthog:customer-tasks-create` to create a task, `posthog:customer-tasks-partial-update` to edit it,
and `posthog:customer-tasks-archive-create` or `posthog:customer-tasks-restore-create` to archive or restore it.
Use `posthog:customer-tasks-list` and `posthog:customer-tasks-retrieve` for API reads with nested account and user details.
Use `posthog:customer-tasks-activities-list` for the change history, including redacted historical account details.
