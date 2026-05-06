import { afterAll, beforeAll } from 'vitest'

import { startCfHarness } from './harness/cf'
import { loadIntegrationEnv, type IntegrationEnv, type IntegrationHarness } from './harness/types'
import { defineMcpProtocolTests, defineUiAppProtocolTests } from './mcp-protocol-suite'

// End-to-end MCP protocol test against the Cloudflare Workers runtime.
//   - Real workerd via `wrangler unstable_dev` (DurableObjects, agents SDK,
//     blockConcurrencyWhile, partyserver — all live)
//   - Real PostHog stack at `TEST_POSTHOG_API_BASE_URL` (defaults to localhost:8010)
//   - Real personal API key from `TEST_POSTHOG_PERSONAL_API_KEY`
//
// Boot the local PostHog stack with `./bin/start` before running this suite.

let env: IntegrationEnv
let harness: IntegrationHarness

beforeAll(async () => {
    env = loadIntegrationEnv()
    harness = await startCfHarness(env)
}, 60_000)

afterAll(async () => {
    await harness?.stop()
})

const harnessFor = () => ({
    baseUrl: harness.baseUrl,
    fetch: globalThis.fetch,
    token: env.apiToken,
    token2: env.apiToken2,
})

defineMcpProtocolTests('Cloudflare Workers (real stack)', harnessFor)
defineUiAppProtocolTests('Cloudflare Workers (real stack)', harnessFor)
