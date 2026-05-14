# @posthog/agent-core

Shared library for the PostHog agent platform runtime. Imported by `@posthog/agent-ingress` and `@posthog/agent-runner` — never imports from them, and never imports from `nodejs/`.

See [`docs/internal/agent-platform.md`](../../docs/internal/agent-platform.md) for the full architecture.

## What lives here

- **Queue primitives** (`src/queue/`) — cyclotron-v2-shaped session queue, reimplemented from scratch. Single `agent_sessions` table backed by its own Postgres DB. Provides `SessionQueueManager` (enqueue), `SessionQueueWorker` (dequeue + lock + heartbeat), `SessionQueueJanitor` (stall recovery + poison-pill detection).
- **Types** (`src/types/`) — the session model, manifest, tool protocol, secrets.
- **Logger** (`src/logger.ts`) — pino-based structured logger.
- **Metrics** (`src/metrics.ts`) — Prom registry helpers.
- **Pub-sub** (`src/pubsub/`) — Redis pub-sub helper for session streaming; in-memory adapter for tests.
- **Internal-API client** (`src/internal-api/`) — calls Django for resolve + decrypt.
- **Built-ins registry** (`src/builtins/`) — hardcoded map of agent-stack built-in tool ids. Imported by both runner and future validator so unknown ids fail in both places.
- **Manifest reader** (`src/manifest/`) — parse + validate top-level config.

## Database

The queue owns a dedicated Postgres DB (`agent_runtime_queue`). Migrations live in `migrations/` and are applied via `bin/migrate.ts`.

```bash
AGENT_RUNTIME_QUEUE_DATABASE_URL=postgres://... pnpm migrate
```

## Hard rules

- **No imports from `nodejs/`.** Cherry-pick by copy.
- Process-less. Importing this package never starts a server, opens a pool, or schedules a timer.
