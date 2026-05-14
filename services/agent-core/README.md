# @posthog/agent-core

Shared library for the PostHog agent platform runtime. Imported by `@posthog/agent-ingress` and `@posthog/agent-runner` — never imports from them, and never imports from `nodejs/`.

See [`docs/internal/agent-platform.md`](../../docs/internal/agent-platform.md) for the full architecture.

## What lives here

- **Queue primitives** (`src/queue/`) — cyclotron-v2-shaped session queue, reimplemented from scratch. Single `agent_sessions` table backed by its own Postgres DB. Provides `SessionQueueManager` (enqueue), `SessionQueueWorker` (dequeue + lock + heartbeat), `SessionQueueJanitor` (stall recovery + poison-pill detection).
- **Types** (`src/types/`) — the session model, manifest, tool protocol, secrets.
- **Logger** (`src/logger.ts`) — pino-based structured logger.
- **Metrics** (`src/metrics.ts`) — Prom registry helpers.
- **Pub-sub** (`src/pubsub/`) — Redis pub-sub helper for session streaming; in-memory adapter for tests.
- **PostHog DB reader** (`src/posthog-db/`) — pg pool + `ApplicationsRepository` for reading `agent_stack_agentapplication` / `*revision` rows directly from the main posthog Postgres. Replaces the old HTTP InternalApiClient.
- **Encryption helper** (`src/encryption/`) — Fernet decrypt for fields written by Django's `EncryptedTextField` (e.g. `agent_stack_agentapplication.encrypted_env`). Copy of `nodejs/src/cdp/utils/encryption-utils.ts`.
- **Built-ins registry** (`src/builtins/`) — hardcoded map of agent-stack built-in tool ids. Imported by both runner and future validator so unknown ids fail in both places.
- **Manifest reader** (`src/manifest/`) — parse + validate top-level config.

## Database

The queue owns a dedicated Postgres DB (`agent_runtime_queue`). Schema lives in [`rust/agent_runtime_queue_migrations/`](../../rust/agent_runtime_queue_migrations/) and is applied with sqlx via the shared rust migrations image — same pattern as cyclotron.

```bash
# locally via the top-level migrate script (preferred — also creates the DB)
bin/migrate --scope=agent_runtime

# or directly
rust/bin/migrate-agent-runtime-queue
```

## Hard rules

- **No imports from `nodejs/`.** Cherry-pick by copy.
- Process-less. Importing this package never starts a server, opens a pool, or schedules a timer.
