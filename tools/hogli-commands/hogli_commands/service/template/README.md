# **SERVICE_NAME**

Node.js service built with `@posthog/node-service` and Hono.

Feature code lives under `src/features/`. Add external adapters under `src/infrastructure/` only when the service needs them. Keep unit tests beside their source files.

## Development

Run commands from the repository root:

```bash
pnpm --filter=@posthog/__SERVICE_NAME__ dev
pnpm --filter=@posthog/__SERVICE_NAME__ typecheck
pnpm --filter=@posthog/__SERVICE_NAME__ test
```

## Tests

Unit tests live beside source files. Integration and end-to-end tests live under `tests/`.

```bash
pnpm --filter=@posthog/__SERVICE_NAME__ test:unit
pnpm --filter=@posthog/__SERVICE_NAME__ test:integration
pnpm --filter=@posthog/__SERVICE_NAME__ test:e2e
pnpm --filter=@posthog/__SERVICE_NAME__ test:ci
```

Integration tests may use the repository-wide development stack. Keep test data isolated and use databases with `test` in their names. If the service owns database tables, apply its versioned migrations before integration and end-to-end tests instead of creating tables from test setup.

## Docker

```bash
pnpm --filter=@posthog/__SERVICE_NAME__ docker:build
```

The image runs as a non-root user and exposes port 3000 by default.

## Runtime endpoints

- `GET /_health` provides liveness.
- `GET /_ready` provides readiness.
- `GET /_metrics` provides Prometheus metrics.
