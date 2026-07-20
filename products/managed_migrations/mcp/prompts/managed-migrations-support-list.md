List batch import (managed migration) jobs across ALL PostHog teams, for troubleshooting customer migrations. PostHog staff only: the backend requires a staff user AND a personal API key explicitly carrying the `batch_import_support:read` scope. A full-access (`*`) key is rejected; OAuth sign-in can never grant this scope.

Filter with `team_id` (the customer's project id) or `status` (`running`, `paused`, `failed`, `completed`), or `search` (matches the developer status message and team name). Results are newest-first.

How to read a job's state:

- `display_status: waiting_to_start` means the job is `running` but no worker has claimed it yet (`lease_id` is null) - it is queued, not stuck.
- Workers hold a lease per job: 30 minutes on initial claim, renewed for 5 minutes on each heartbeat. `lease_expired: true` on a `running` job means the worker died or the row is about to be re-claimed by the next worker poll.
- A `paused` job KEEPS its worker lease; resuming requires clearing the lease (a Django admin action today - this API is read-only).
- `paused` with a `status_message` mentioning invalid JSON syntax at the resume point usually means a poisoned byte offset: the source bytes changed under the committed offset (re-downloaded nondeterministic export or replaced source file). The fix is Django admin's "Resume + re-import in-flight part", which resets the in-flight part to offset 0 (safe for Mixpanel/Amplitude, which dedupe by deterministic event UUID).
- `backoff_until` in the future means the job is in a transient-failure retry loop (`backoff_attempt` counts consecutive retries), not stuck.
- `parts_progress` summarizes the worker's units of work: a part is done when its committed byte offset reaches its total size; parts are processed in order, so the in-flight part is the first unfinished one.
- `status_message` is the developer-facing debugging signal; `display_status_message` is what the customer sees in the PostHog UI.

Use `managed-migrations-support-get` with a job id for the raw worker `state` and `import_config` blobs. Credentials (`secrets`) are never returned.
