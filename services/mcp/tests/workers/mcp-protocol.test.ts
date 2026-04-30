import { SELF } from 'cloudflare:test'
import { describe, expect, it } from 'vitest'

// HTTP-layer integration tests for the Cloudflare Workers entry point.
//
// Why this suite is narrower than the Hono one (`tests/hono/mcp-protocol.test.ts`):
// the McpAgent framework wraps session init in `blockConcurrencyWhile()` on a
// Durable Object. The workerd test runtime imposes a ~30s ceiling on that
// primitive, and the full init flow (tool registration, region detect,
// dual-region API fan-out) trips it under workerd's higher per-call overhead.
// The Hono harness exercises the full SDK-client → MCP-server protocol loop
// over the same shared suite, and the existing `tests/workers/*.test.ts` files
// cover the DO internals via `runInDurableObject`. That leaves the entry-point
// HTTP behavior as the gap this file fills.
describe('MCP HTTP entry point (Cloudflare Workers)', () => {
    describe('OAuth Protected Resource Metadata (RFC 9728)', () => {
        it('returns metadata advertising scopes_supported for /mcp', async () => {
            const response = await SELF.fetch(
                'https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp'
            )

            expect(response.status).toBe(200)
            expect(response.headers.get('content-type')).toContain('application/json')
            const body = (await response.json()) as Record<string, unknown>
            expect(body.resource).toBe('https://mcp.posthog.com/mcp')
            expect(Array.isArray(body.authorization_servers)).toBe(true)
            expect(Array.isArray(body.scopes_supported)).toBe(true)
            expect((body.scopes_supported as string[]).length).toBeGreaterThan(0)
            expect(body.bearer_methods_supported).toEqual(['header'])
        })

        it('returns metadata for /sse with the same shape', async () => {
            const response = await SELF.fetch(
                'https://mcp.posthog.com/.well-known/oauth-protected-resource/sse'
            )

            expect(response.status).toBe(200)
            const body = (await response.json()) as Record<string, unknown>
            expect(body.resource).toBe('https://mcp.posthog.com/sse')
        })
    })

    describe('Authentication challenges', () => {
        it('returns 401 with WWW-Authenticate Bearer + resource_metadata when no token', async () => {
            const response = await SELF.fetch('https://mcp.posthog.com/mcp', { method: 'POST' })

            expect(response.status).toBe(401)
            const challenge = response.headers.get('WWW-Authenticate') || ''
            expect(challenge).toContain('Bearer')
            expect(challenge).toContain('resource_metadata=')
            expect(challenge).toContain('/.well-known/oauth-protected-resource/mcp')
        })

        it('returns 401 for malformed bearer tokens (wrong prefix)', async () => {
            const response = await SELF.fetch('https://mcp.posthog.com/mcp', {
                method: 'POST',
                headers: { Authorization: 'Bearer not_a_posthog_token' },
            })

            expect(response.status).toBe(401)
            expect(await response.text()).toContain('Invalid token')
        })
    })

    describe('Authorization server redirects', () => {
        it('redirects /.well-known/oauth-authorization-server to the auth server', async () => {
            const response = await SELF.fetch(
                'https://mcp.posthog.com/.well-known/oauth-authorization-server',
                { redirect: 'manual' }
            )

            expect(response.status).toBe(302)
            const location = response.headers.get('location') || ''
            expect(location).toContain('/.well-known/oauth-authorization-server')
        })

        it('rewrites /register to /oauth/register with a 307 (preserves POST)', async () => {
            const response = await SELF.fetch('https://mcp.posthog.com/register', {
                method: 'POST',
                redirect: 'manual',
            })

            expect(response.status).toBe(307)
            const location = response.headers.get('location') || ''
            expect(location).toContain('/oauth/register')
        })
    })
})
