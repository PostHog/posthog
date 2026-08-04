# Orchestrated tasks

Orchestrated tasks let one cloud task plan work and spawn cloud child tasks that each complete a focused part of that plan. The parent and children normally share a channel, and the channel context is their plan of record.

The `tasks-orchestration` organization feature flag controls child spawning and the `tasks-spawn` MCP tool.

## Parent and child model

Parentage is stored only in protected child-run state:

- `parent_task_id` identifies the parent task.
- `parent_run_id` records the run that spawned the child.
- `wake_on` stores optional wake sources.

There is no parent-child field on `Task`. Grouping belongs to channels, and adding a schema relationship would require every task action to define whether it affects related tasks. This keeps children independent: archive, cancel, and delete operations never propagate. This decision also incorporates the concerns raised in [#51629](https://github.com/PostHog/posthog/issues/51629).

Orchestration has a depth limit of one. A run with `parent_task_id` cannot spawn another child.

## Child capability

`tasks-spawn` accepts a server-managed `delegation_profile` for callers that want to control cost and capability without selecting a runtime-specific model combination:

- `low` uses the cheapest supported implementation configuration.
- `medium` uses a balanced implementation configuration.
- `high` uses the strongest supported planning and implementation configuration.

Callers that need an exact configuration can instead provide `runtime_adapter`, `model`, and `reasoning_effort`. Profiles and explicit runtime fields cannot be combined.

## Wake delivery

Every terminal child status wakes the parent. A child can also wake the parent when its pull request merges by including `pr_merged` in `wake_on` at spawn time.

The wake service resolves the parent task's current run when it delivers the message. It follows this delivery order:

1. Signal a live parent workflow.
2. Queue the wake in the parent run's state when the workflow is unavailable.
3. Resume a cold parent and deliver all queued wakes.

Wake messages are built from task and run records. They include the child's status, error, and pull request URL when available.

Child and CI follow-ups carry trusted source metadata through the agent protocol. Clients render them as automation messages rather than attributing them to the user.

## Running dependent child tasks

Run dependent child tasks serially through pull request merge. The CI follow-up loop can push fixes to a child's branch, which makes a stacked branch based on that child unstable. Spawn the next dependent child after the previous pull request merges.

## Headless creation gaps

Children are created in the cloud without a desktop client. They inherit the parent's skill bundles, imported public-URL MCP servers, sandbox environment, and custom image.

Desktop-relayed MCP servers do not work for child tasks. Their stdio or private-network executor exists only in the desktop process that created the parent, and a server-created child has no relay binding.

## Follow-ups

- Allow parents to steer active children through `tasks-runs-command-create`.
- Wake parents when a child pull request closes without merging.
- Add a children-list filter or tree view if the product needs hierarchy. A `Task` foreign key can be backfilled from run-state keys when that UI has a concrete consumer.
