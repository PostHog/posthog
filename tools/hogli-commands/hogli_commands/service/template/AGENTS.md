# Node.js service development guide

## Architecture

- Build HTTP services with Hono and the primitives from `@posthog/node-service`.
- Keep the entrypoint in `src/index.ts` limited to configuration, dependency construction, startup, and shutdown registration.
- Keep domain logic independent from Hono where practical.
- Inject infrastructure dependencies. Do not create database, Redis, or Kafka clients at module import time.
- Register resource cleanup with the service shutdown lifecycle.
- Validate environment variables at startup.
- Use structured logger fields. Do not log credentials, cookies, tokens, request bodies, or arbitrary request headers.
- Use route templates for metric labels. Never place identifiers, URLs, team IDs, or user-controlled values in metric labels.
- Keep shared runtime code and standard build/report commands in `@posthog/node-service`.
- Use `@posthog/node-migrations` for service-owned PostgreSQL migrations.
- Do not add service-specific build, migration-runner, or test-report scripts when the shared package commands cover the service.
- Keep database clients, authentication, retries, and domain metrics in this service.

## Source structure

- Keep process wiring in `src/index.ts` and HTTP composition in `src/app.ts`.
- Group behavior under `src/features/<feature>/` with colocated unit tests.
- Put database, cache, queue, and third-party adapters under `src/infrastructure/` when they are needed.
- Prefer vertical feature slices over top-level `controllers/`, `services/`, and `repositories/` directories.
- Do not create empty architectural layers. A small feature can keep its route and logic together.

## Commands

Run these commands from the repository root:

- `pnpm --filter=@posthog/__SERVICE_NAME__ test:unit`
- `pnpm --filter=@posthog/__SERVICE_NAME__ test:integration`
- `pnpm --filter=@posthog/__SERVICE_NAME__ test:e2e`
- `pnpm --filter=@posthog/__SERVICE_NAME__ test:ci`
- `pnpm --filter=@posthog/__SERVICE_NAME__ typecheck`
- `pnpm --filter=@posthog/__SERVICE_NAME__ fix`
- `pnpm --filter=@posthog/__SERVICE_NAME__ build`
- `pnpm --filter=@posthog/__SERVICE_NAME__ docker:build`

## Tests

Before adding a test, state the realistic regression it catches and confirm no existing test catches it.

### Unit tests

- Place unit tests beside source files as `*.test.ts`.
- Keep them free of databases, networks, subprocesses, and real timers.
- Test public behavior instead of private method calls.
- Use `it.each` for variations of the same behavior.

### Integration tests

- Place integration tests in `tests/integration/` as `*.integration.test.ts`.
- Use real Postgres, Redis, Kafka, ClickHouse, or object storage when the feature depends on them.
- Use the repository-wide development stack.
- Use dedicated test databases, schemas, tables, topics, buckets, and key prefixes.
- Refuse to run destructive setup against a database whose name does not contain `test`.
- Run the same schema setup or migrations used by the service.
- Mock only third-party systems at their network boundary.

### Database migrations

- Decide whether Django or the service owns each table before writing database code.
- Keep Django migrations as the source of truth for tables owned by Django.
- Keep service-owned migrations as ordered files under the service root.
- Run service-owned migrations explicitly before application deployment and before infrastructure-backed tests.
- Do not execute schema changes during application startup.
- Keep migration history and advisory locking enabled.
- Use the same migration files in development, CI, and production.

### End-to-end tests

- Place end-to-end tests in `tests/e2e/` as `*.e2e.test.ts`.
- Launch the built `dist/server.mjs` artifact as a subprocess or container.
- Exercise the public network interface and real infrastructure dependencies.
- Cover startup, readiness, the primary feature flow, persistence where applicable, and graceful shutdown.
- Wait for observable conditions with deadlines. Do not use arbitrary sleeps.

### Test performance

- Run `test:ci` after changing integration or end-to-end coverage.
- Review the slowest-test report and the category budgets.
- Update a budget only when the service contract requires more work, not to hide a regression.
- Keep generated JUnit output under `test-results/` and do not commit it.

## Runtime contract

- `/_health` is liveness and must not call external dependencies.
- `/_ready` is readiness and may check required dependencies with bounded work.
- `/_metrics` exposes Prometheus metrics and must not be included in request metrics.
- Readiness must close before shutdown starts.
- OpenTelemetry spans are created through the API package. They remain no-ops unless an SDK is configured before service startup.
