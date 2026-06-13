import { SELF } from 'cloudflare:test'
import { describe, expect, it } from 'vitest'

// HTTP-layer integration tests for the Cloudflare Workers entry point.
//
// The Worker is a stateless edge router: it terminates OAuth, validates tokens,
// and proxies `/mcp` to the Hono runtime. This suite covers that entry-point
// HTTP behavior (OAuth metadata, auth challenges, redirects) — the full MCP
// protocol loop is exercised against the Hono runtime in
// `tests/hono/mcp-protocol.test.ts`.
describe('MCP HTTP entry point (Cloudflare Workers)', () => {
    describe('OAuth Protected Resource Metadata (RFC 9728)', () => {
        it('returns metadata advertising scopes_supported for /mcp', async () => {
            const response = await SELF.fetch('https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp')

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
            const response = await SELF.fetch('https://mcp.posthog.com/.well-known/oauth-protected-resource/sse')

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

        it('returns 401 for JWTs without typ: at+jwt (not an ID-JAG token)', async () => {
            const headerB64 = btoa('{"typ":"JWT","alg":"HS256"}')
                .replace(/=+$/, '')
                .replace(/\+/g, '-')
                .replace(/\//g, '_')
            const response = await SELF.fetch('https://mcp.posthog.com/mcp', {
                method: 'POST',
                headers: { Authorization: `Bearer ${headerB64}.eyJzdWIiOiJ4In0.sig` },
            })

            expect(response.status).toBe(401)
            expect(await response.text()).toContain('Invalid token')
        })

        it('passes the gate for ID-JAG access tokens (typ: at+jwt)', async () => {
            // The MCP gate only checks the header. Signature verification happens
            // downstream against the PostHog API (`IDJagAccessTokenAuthentication`).
            // Here we assert the response is NOT the gate's "Invalid token" 401 —
            // anything else (init failure against a missing PostHog API, etc.) is
            // acceptable since this test exercises only the gate.
            const headerB64 = btoa('{"typ":"at+jwt","alg":"RS256"}')
                .replace(/=+$/, '')
                .replace(/\+/g, '-')
                .replace(/\//g, '_')
            const payloadB64 = btoa('{"sub":"example.com:user@example.com"}')
                .replace(/=+$/, '')
                .replace(/\+/g, '-')
                .replace(/\//g, '_')
            const response = await SELF.fetch('https://mcp.posthog.com/mcp', {
                method: 'POST',
                headers: { Authorization: `Bearer ${headerB64}.${payloadB64}.sig` },
            })

            expect(await response.text()).not.toContain('Invalid token')
        })
    })

    describe('Authorization server redirects', () => {
        it('redirects /.well-known/oauth-authorization-server to the auth server', async () => {
            const response = await SELF.fetch('https://mcp.posthog.com/.well-known/oauth-authorization-server', {
                redirect: 'manual',
            })

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
