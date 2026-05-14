# @posthog/agent-runner

Session executor process for the PostHog agent platform.

- Dequeues session jobs from the `@posthog/agent-core` queue.
- Restores Claude Agent SDK state from the job's `state` payload.
- Runs one "turn" — until the next tool boundary or completion.
- Two outcomes per turn:
  - **Completion** — ack the job, publish completion to the bus.
  - **Suspension** — `reschedule({ scheduledAt, state })`. Heartbeats keep the lock alive while a turn is in flight.

## Tool execution (v1, native only)

v1 executes every tool in-process. There is no Modal sandbox, no remote dispatch. The tool registry combines:

- **Meta tools** — `complete`, `wait_for_input` (defined in `src/tools/meta.ts`).
- **Built-in tools** — backed by `@posthog/agent-core`'s `builtins` registry.

Custom tools defined inside an agent bundle are out of scope for v1 and will require the sandbox manager when they land. Until then, only built-in ids declared in agent-core are runnable.

See [`docs/internal/agent-platform.md`](../../docs/internal/agent-platform.md) for the full architecture.

## Hard rule

- **No imports from `nodejs/`.** Cherry-pick by copy if you ever need something from it.
