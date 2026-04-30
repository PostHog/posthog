import { afterAll, beforeAll } from 'vitest'

import { startHonoHarness } from './harness/hono'
import { loadIntegrationEnv, type IntegrationEnv, type IntegrationHarness } from './harness/types'
import { defineMcpProtocolTests, defineUiAppProtocolTests } from './mcp-protocol-suite'

// End-to-end MCP protocol test against the Hono runtime.
//   - Real `@hono/node-server` listener (TCP + HTTP semantics, not `app.request`)
//   - Real PostHog stack at `TEST_POSTHOG_API_BASE_URL` (defaults to localhost:8010)
//   - Real personal API key from `TEST_POSTHOG_PERSONAL_API_KEY`
//
// Boot the local PostHog stack with `./bin/start` before running this suite.
// Ensure `.env.test` defines TEST_POSTHOG_PERSONAL_API_KEY / TEST_ORG_ID /
// TEST_PROJECT_ID — matching the existing `tests/tools/*.integration.test.ts`.

let env: IntegrationEnv
let harness: IntegrationHarness

beforeAll(async () => {
    env = loadIntegrationEnv()
    harness = await startHonoHarness(env)
})

afterAll(async () => {
    await harness?.stop()
})

const harnessFor = () => ({
    baseUrl: harness.baseUrl,
    fetch: globalThis.fetch,
    token: env.apiToken,
    token2: env.apiToken2,
})

// SSE transport intentionally not exercised here — the Hono runtime only
// supports Streamable HTTP. SSE coverage lives in the Cloudflare integration
// test (`mcp-protocol.cf.integration.test.ts`), which still serves it.
defineMcpProtocolTests('Hono (real stack)', harnessFor)
defineUiAppProtocolTests('Hono (real stack)', harnessFor)
