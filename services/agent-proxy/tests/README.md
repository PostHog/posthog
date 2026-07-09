# Tests

Unit tests for the agent-proxy service. The tree mirrors `src/` so a test sits at
the same relative path as the module it covers:

- `tests/hono/` — HTTP layer: app routes, middleware, SSE and ingest handlers, metrics
- `tests/lib/` — domain utilities: Redis stream, JWT validation, constants

Production code imports use the `@/` path alias (e.g. `@/lib/redis-stream.js`), so test
files never reach back into `src/` with relative paths.

## Setup

`tests/setup.ts` is the global setup (wired via `vitest.config.mts`). It mocks
`@/hono/metrics.js` so prom-client never registers duplicate metrics across suites.
A test that needs the real implementation (see `tests/hono/metrics.test.ts`) pulls it
in with `vi.importActual`.

## Running

```bash
pnpm --filter @posthog/agent-proxy test          # watch mode
pnpm --filter @posthog/agent-proxy exec vitest run  # single run
```
