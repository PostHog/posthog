# Node service demo development guide

This service is the temporary end-to-end validation target for `@posthog/node-service`. Keep it small and remove it after a permanent service adopts the runtime.

## Commands

Run these commands from the repository root:

- `pnpm --filter=@posthog/node-service-demo migrate`
- `pnpm --filter=@posthog/node-service-demo test:unit`
- `pnpm --filter=@posthog/node-service-demo test:integration`
- `pnpm --filter=@posthog/node-service-demo test:e2e`
- `pnpm --filter=@posthog/node-service-demo test:ci`
- `pnpm --filter=@posthog/node-service-demo typecheck`
- `pnpm --filter=@posthog/node-service-demo fix`
- `pnpm --filter=@posthog/node-service-demo build`
- `pnpm --filter=@posthog/node-service-demo docker:build`

## Test contract

- Unit tests live beside source files as `*.test.ts` and do not use infrastructure.
- Integration tests live in `tests/integration/` and use the repository-wide development stack.
- Tests apply the versioned migrations from `migrations/`. Do not create tables from test helpers or application startup.
- End-to-end tests live in `tests/e2e/`, launch `dist/server.mjs`, and use real Postgres.
- Tests must refuse destructive database setup unless the database name contains `test`.
- Use isolated table names so parallel runs cannot affect each other.
- Do not use arbitrary sleeps. Wait for readiness, process output, or another observable condition with a deadline.
- Run `test:ci` and review the slowest-test report after changing integration or end-to-end coverage.

Before adding a test, name the realistic regression it catches and confirm that no cheaper existing test catches it.

## Source structure

- Keep configuration, dependency construction, startup, and shutdown in `src/index.ts`.
- Compose feature routes in `src/app.ts`.
- Group behavior under `src/features/<feature>/` with colocated unit tests.
- Put Postgres and other external adapters under `src/infrastructure/`.
- Do not create empty controller, service, or repository layers. Split a feature only when its behavior needs those boundaries.

## Runtime contract

- Build the application with Hono and `@posthog/node-service`.
- Keep database code in the service rather than the shared runtime package.
- Store database changes as ordered files under `migrations/` and run them with `@posthog/node-migrations`.
- Use the shared build and test-report commands from `@posthog/node-service`. Do not add service-specific scripts for those jobs.
- Run migrations explicitly before deploying the service. Application processes must not execute schema changes during startup.
- Keep advisory locking and migration history enabled.
- Register every opened resource with a shutdown hook.
- Use route templates for metric labels. Never use counter names or other request values as labels.
- Do not log request bodies, credentials, cookies, tokens, or arbitrary headers.
