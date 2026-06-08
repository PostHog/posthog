import { afterAll, beforeAll, describe } from 'vitest'

import { startCfHarness } from './harness/cf'
import { loadIntegrationEnv, type IntegrationEnv, type IntegrationHarness } from './harness/types'
import {
    defineAuthTests,
    defineCatalogFilterTests,
    defineMcpProtocolTests,
    defineResilienceTests,
    defineResourceCatalogTests,
    defineToolBehaviorTests,
    defineUiAppProtocolTests,
    type ProtocolTestHarness,
} from './mcp-protocol-suite'

// End-to-end MCP protocol test against the Cloudflare Workers runtime.
//   - Real workerd via `wrangler unstable_dev` (DurableObjects, agents SDK,
//     blockConcurrencyWhile, partyserver — all live)
//   - Real PostHog stack at `TEST_POSTHOG_API_BASE_URL` (defaults to localhost:8010)
//   - Real personal API key from `TEST_POSTHOG_PERSONAL_API_KEY`
//
// Boot the local PostHog stack with `./bin/start` before running this suite.
//
// What runs here vs Hono-only:
//   - SDK-based suites work on both runtimes because the SDK client handles
//     CF's SSE-streaming responses and Durable Object session lifecycle.
//   - Raw-fetch JSON-asserting suites (defineHttpRouteTests,
//     defineJsonRpcEdgeCaseTests, defineSessionLifecycleTests) are Hono-only:
//     CF returns SSE bodies and requires an initialized DO session before
//     it'll dispatch arbitrary JSON-RPC methods, which the raw assertions
//     don't account for. These behaviors are still covered against the Hono
//     runtime — both runtimes share the same dispatcher / catalog code.
//   - defineAuthTests is shared because every test in it asserts on a 401
//     rejection that fires before the dispatcher / session layer.

let env: IntegrationEnv
let harness: IntegrationHarness

beforeAll(async () => {
    env = loadIntegrationEnv()
    harness = await startCfHarness(env)
}, 60_000)

afterAll(async () => {
    await harness?.stop()
})

const harnessFor = (): ProtocolTestHarness => ({
    baseUrl: harness.baseUrl,
    fetch: globalThis.fetch,
    token: env.apiToken,
    token2: env.apiToken2,
    orgId: env.orgId,
    projectId: env.projectId,
    publicRoutes: false,
})

// The worker now proxies all `/mcp` traffic to the Hono runtime instead of
// serving it locally via the durable object, so these serving suites no longer
// exercise the worker. The same protocol behavior is covered against the
// runtime that actually serves it in `mcp-protocol.hono.integration.test.ts`.
// Skipped (not removed) until the durable object itself is retired.
describe.skip('Cloudflare Workers serving (now proxied to Hono)', () => {
    defineMcpProtocolTests('Cloudflare Workers (real stack)', harnessFor)
    defineResilienceTests('Cloudflare Workers (real stack)', harnessFor)
    defineUiAppProtocolTests('Cloudflare Workers (real stack)', harnessFor)
    defineResourceCatalogTests('Cloudflare Workers (real stack)', harnessFor)
    defineToolBehaviorTests('Cloudflare Workers (real stack)', harnessFor)
    defineCatalogFilterTests('Cloudflare Workers (real stack)', harnessFor)
})

// The worker still enforces the bearer-token boundary before any proxying, so
// these 401 assertions remain valid against the real worker.
defineAuthTests('Cloudflare Workers (real stack)', harnessFor)
