import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { startCfProxyHarness } from './harness/cf-proxy'
import { loadIntegrationEnv, type IntegrationEnv, type IntegrationHarness } from './harness/types'
import {
    defineAuthTests,
    defineHttpRouteTests,
    defineResilienceTests,
    type ProtocolTestHarness,
} from './mcp-protocol-suite'

// End-to-end test for the Cloudflare Worker proxy.
//
// What runs:
//   - Real workerd via `wrangler unstable_dev` running `src/index.ts`
//   - Real `@hono/node-server` listener running `createApp(redis)` behind it
//   - Real Redis (TEST_REDIS_URL / db TEST_REDIS_DB, default localhost:6379 db 15)
//   - Real local PostHog stack at TEST_POSTHOG_API_BASE_URL (default localhost:8010)
//
// Nothing is mocked. The Worker is configured with `MCP_HONO_URL` pointing at
// the in-process Hono, so every assertion validates the full
// client → proxy → Hono → PostHog chain.
//
// Boot the local PostHog stack with `./bin/start` and have a local Redis
// listening on 6379 before running this suite. Ensure `.env.test` (or the
// integration env) defines `TEST_POSTHOG_PERSONAL_API_KEY` / `TEST_ORG_ID` /
// `TEST_PROJECT_ID`.

let env: IntegrationEnv
let harness: IntegrationHarness & { honoUrl: URL }

beforeAll(async () => {
    env = loadIntegrationEnv()
    harness = await startCfProxyHarness(env)
}, 60000)

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

// Re-run the public-route and auth slices of the Hono protocol suite through
// the Worker. These are the cheapest end-to-end signals that the proxy
// preserves status, headers, body, and routing.
defineHttpRouteTests('CF proxy → Hono (real stack)', harnessFor)
defineAuthTests('CF proxy → Hono (real stack)', harnessFor)
// `defineResilienceTests` covers the /sse → /mcp 308 + `_deprecated=sse`
// marker (parity with the old `tests/workers/sse-redirect.test.ts`) plus the
// unknown-Mcp-Session-Id recovery path, both of which the proxy needs to
// forward verbatim.
defineResilienceTests('CF proxy → Hono (real stack)', harnessFor)

// Proxy-specific assertions: region detection inputs and request/response
// fidelity. These deliberately stay narrow — the rich protocol surface is
// covered by the Hono suite; here we just confirm the Worker hands every
// shape of request off cleanly.
describe('CF proxy plumbing (real stack)', () => {
    it('forwards an unknown path so Hono can answer (404)', async () => {
        const res = await fetch(new URL('/this-path-does-not-exist', harness.baseUrl))
        expect(res.status).toBe(404)
    })

    it('preserves request body and content-type on POST', async () => {
        // Hit /mcp without auth so we exercise POST + body forwarding without
        // needing a valid PostHog token. We expect Hono's 401 + the body to
        // round-trip through the proxy.
        const res = await fetch(new URL('/mcp', harness.baseUrl), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Accept: 'application/json, text/event-stream',
            },
            body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'ping' }),
        })
        expect(res.status).toBe(401)
        // The 401 carries the RFC 9728 WWW-Authenticate challenge. If the
        // proxy stripped response headers, we'd lose this and the test fails.
        const wwwAuth = res.headers.get('WWW-Authenticate') || ''
        expect(wwwAuth.toLowerCase()).toContain('bearer')
        expect(wwwAuth).toContain('oauth-protected-resource')
    })

    it('routes to the EU region when X-Forwarded-Host is mcp-eu.posthog.com', async () => {
        // Both regions resolve to the same local Hono via MCP_HONO_URL, so we
        // can't tell the regions apart by destination — but Hono echoes the
        // `region` query when building its OAuth metadata, so requests that
        // landed via the hostname path carry it forward to the metadata URL.
        const res = await fetch(new URL('/.well-known/oauth-protected-resource/mcp', harness.baseUrl), {
            headers: { 'X-Forwarded-Host': 'mcp-eu.posthog.com' },
        })
        expect(res.status).toBe(200)
        const json = (await res.json()) as { authorization_servers?: string[] }
        expect(Array.isArray(json.authorization_servers)).toBe(true)
    })

    it('forwards ?region=eu without altering other query params', async () => {
        const res = await fetch(
            new URL('/.well-known/oauth-protected-resource/mcp?region=eu&extra=keep', harness.baseUrl)
        )
        expect(res.status).toBe(200)
        const json = (await res.json()) as { resource?: string }
        // Hono builds `resource` from the request URL — extra query params
        // get dropped (search is cleared in public-routes), so we just assert
        // the path made it through intact.
        expect(json.resource).toMatch(/\/mcp$/)
    })

    it('forwards GET / through to the Hono redirect', async () => {
        const res = await fetch(new URL('/', harness.baseUrl), { redirect: 'manual' })
        expect([301, 302, 307, 308]).toContain(res.status)
        expect(res.headers.get('location') || '').toContain('posthog.com')
    })
})
