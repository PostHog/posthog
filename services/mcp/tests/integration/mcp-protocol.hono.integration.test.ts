import { afterAll, beforeAll } from 'vitest'

import { startHonoHarness } from './harness/hono'
import { loadIntegrationEnv, type IntegrationEnv, type IntegrationHarness } from './harness/types'
import {
    defineAuthTests,
    defineCatalogFilterTests,
    defineHttpRouteTests,
    defineJsonRpcEdgeCaseTests,
    defineMcpProtocolTests,
    defineResilienceTests,
    defineResourceCatalogTests,
    defineSessionLifecycleTests,
    defineToolBehaviorTests,
    defineUiAppProtocolTests,
    type ProtocolTestHarness,
} from './mcp-protocol-suite'

// End-to-end MCP protocol test against the Hono runtime.
//   - Real `@hono/node-server` listener (TCP + HTTP semantics, not `app.request`)
//   - Real PostHog stack at `TEST_POSTHOG_API_BASE_URL` (defaults to localhost:8010)
//   - Real personal API key from `TEST_POSTHOG_PERSONAL_API_KEY`
//
// Boot the local PostHog stack with `./bin/start` before running this suite.
// Ensure `.env.test` defines TEST_POSTHOG_PERSONAL_API_KEY / TEST_ORG_ID /
// TEST_PROJECT_ID — matching the existing `tests/tools/*.integration.test.ts`.
//
// Suites wired here, each focused on a slice of MCP server behavior:
//   - `defineMcpProtocolTests`        — SDK-level initialize / list / call / read
//   - `defineResilienceTests`         — /sse redirects, unknown Mcp-Session-Id behavior
//   - `defineUiAppProtocolTests`      — ext-app metadata, HTML stub, static asset serving
//   - `defineHttpRouteTests`          — public routes (health, oauth, openai challenge, 405s)
//   - `defineAuthTests`               — bearer enforcement at the /mcp boundary
//   - `defineJsonRpcEdgeCaseTests`    — raw JSON-RPC (parse errors, batches, notifications, ping)
//   - `defineSessionLifecycleTests`   — initialize negotiation + repeated init
//   - `defineResourceCatalogTests`    — both UI and context-mill resources present and readable
//   - `defineToolBehaviorTests`       — real PostHog tool calls and multi-step interactions
//   - `defineCatalogFilterTests`      — ?features= and ?tools= query-param filtering

let env: IntegrationEnv
let harness: IntegrationHarness

beforeAll(async () => {
    env = loadIntegrationEnv()
    harness = await startHonoHarness(env)
})

afterAll(async () => {
    await harness?.stop()
})

const harnessFor = (): ProtocolTestHarness => ({
    baseUrl: harness.baseUrl,
    fetch: globalThis.fetch,
    token: env.apiToken,
    token2: env.apiToken2,
    stateless: true,
    gracefulUnknown: true,
    orgId: env.orgId,
    projectId: env.projectId,
    publicRoutes: true,
})

defineMcpProtocolTests('Hono (real stack)', harnessFor)
defineResilienceTests('Hono (real stack)', harnessFor)
defineUiAppProtocolTests('Hono (real stack)', harnessFor)
defineHttpRouteTests('Hono (real stack)', harnessFor)
defineAuthTests('Hono (real stack)', harnessFor)
defineJsonRpcEdgeCaseTests('Hono (real stack)', harnessFor)
defineSessionLifecycleTests('Hono (real stack)', harnessFor)
defineResourceCatalogTests('Hono (real stack)', harnessFor)
defineToolBehaviorTests('Hono (real stack)', harnessFor)
defineCatalogFilterTests('Hono (real stack)', harnessFor)
