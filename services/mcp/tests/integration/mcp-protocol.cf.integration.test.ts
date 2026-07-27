import { afterAll, beforeAll } from 'vitest'

import { startCfHarness } from './harness/cf'
import { loadIntegrationEnv, type IntegrationEnv, type IntegrationHarness } from './harness/types'
import { defineAuthTests, type ProtocolTestHarness } from './mcp-protocol-suite'

// Auth-boundary test against the Cloudflare Workers entry point.
//   - Real workerd via `wrangler unstable_dev`
//   - Real PostHog stack at `TEST_POSTHOG_API_BASE_URL` (defaults to localhost:8010)
//   - Real personal API key from `TEST_POSTHOG_PERSONAL_API_KEY`
//
// Boot the local PostHog stack with `./bin/start` before running this suite.
//
// The worker proxies all `/mcp` traffic to the Hono runtime — protocol,
// resilience, resource-catalog and tool-behavior suites run against the runtime
// that actually serves them in `mcp-protocol.hono.integration.test.ts`. Only the
// bearer-token gate still lives in the worker, so that's all this file asserts
// (every `defineAuthTests` case is a 401 that fires before any proxying).

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

defineAuthTests('Cloudflare Workers (real stack)', harnessFor)
