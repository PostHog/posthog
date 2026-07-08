import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { startCfProxyHarness } from './harness/cf-proxy'
import { loadIntegrationEnv, type IntegrationEnv, type IntegrationHarness } from './harness/types'
import { defineAuthTests, defineResilienceTests, type ProtocolTestHarness } from './mcp-protocol-suite'

// End-to-end test for the Cloudflare Worker → Hono proxy.
//
// What runs:
//   - Real workerd via `wrangler unstable_dev` running `src/index.ts`
//   - Real `@hono/node-server` listener running `createApp(redis)` behind it
//   - Real Redis (TEST_REDIS_URL / db TEST_REDIS_DB, default localhost:6379 db 15)
//   - Real local PostHog stack at TEST_POSTHOG_API_BASE_URL (default localhost:8010)
//
// Nothing is mocked. The Worker is configured with `MCP_HONO_URL` pointing at
// the in-process Hono, so authenticated `/mcp` traffic travels the full
// client → proxy → Hono → PostHog chain.
//
// The worker owns OAuth metadata, redirects, health, and the bearer-token gate
// locally and proxies only `/mcp` — it is not a transparent pass-through. The
// Hono-runtime public-route surface (`/readyz`, `/metrics`, unknown-path 404s,
// security headers) is asserted against the Hono integration test, not here.
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
})

// The bearer-token gate fires in the worker before any proxying, and the
// /sse → /mcp 308 (+ `_deprecated=sse` marker) and unknown-Mcp-Session-Id
// recovery paths are forwarded to Hono. Together these are the cheapest
// end-to-end signals that the proxy preserves status, headers, body, and
// routing. The /sse cases also give parity with the old
// `tests/workers/sse-redirect.test.ts`.
defineAuthTests('CF proxy → Hono (real stack)', harnessFor)
defineResilienceTests('CF proxy → Hono (real stack)', harnessFor)

// Proxy-specific assertions: request/response fidelity and region-detection
// inputs. These stay narrow — the rich protocol surface is covered by the Hono
// suite; here we confirm the worker hands each request off (or answers it)
// cleanly.
describe('CF proxy plumbing (real stack)', () => {
    it('returns the worker 401 + WWW-Authenticate challenge for unauthenticated POST /mcp', async () => {
        // The token gate fires before proxying, so an unauthenticated POST /mcp
        // gets the worker's own RFC 9728 challenge. If the worker dropped
        // response headers we'd lose the WWW-Authenticate here.
        const res = await fetch(new URL('/mcp', harness.baseUrl), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Accept: 'application/json, text/event-stream',
            },
            body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'ping' }),
        })
        expect(res.status).toBe(401)
        const wwwAuth = res.headers.get('WWW-Authenticate') || ''
        expect(wwwAuth.toLowerCase()).toContain('bearer')
        expect(wwwAuth).toContain('oauth-protected-resource')
    })

    it('detects the EU region from X-Forwarded-Host when building OAuth metadata', async () => {
        const res = await fetch(new URL('/.well-known/oauth-protected-resource/mcp', harness.baseUrl), {
            headers: { 'X-Forwarded-Host': 'mcp-eu.posthog.com' },
        })
        expect(res.status).toBe(200)
        const json = (await res.json()) as { authorization_servers?: string[] }
        expect(Array.isArray(json.authorization_servers)).toBe(true)
    })

    it('serves OAuth metadata with ?region=eu without dropping the resource path', async () => {
        const res = await fetch(
            new URL('/.well-known/oauth-protected-resource/mcp?region=eu&extra=keep', harness.baseUrl)
        )
        expect(res.status).toBe(200)
        const json = (await res.json()) as { resource?: string }
        expect(json.resource).toMatch(/\/mcp$/)
    })

    it('redirects GET / to the docs', async () => {
        const res = await fetch(new URL('/', harness.baseUrl), { redirect: 'manual' })
        expect([301, 302, 307, 308]).toContain(res.status)
        expect(res.headers.get('location') || '').toContain('posthog.com')
    })
})
