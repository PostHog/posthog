import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

// Tests that go through createApp need a signing key — the typed-confirm
// runtime install throws without one. We stub a fixed value rather than
// depend on the surrounding environment.
const TEST_SIGNING_KEY = 'a'.repeat(32)
beforeAll(() => {
    process.env.MCP_SIGNED_STATE_KEY = TEST_SIGNING_KEY
})

interface MockRedis extends RedisLike {
    ping: Mock<() => Promise<string>>
    _store: Map<string, string>
}

function createMockRedis(): MockRedis {
    const store = new Map<string, string>()
    return {
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string) => {
            store.set(key, value)
            return 'OK'
        }),
        del: vi.fn(async (...keys: string[]) => keys.length),
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
        ...makeRedisRateLimitStubs(),
        ping: vi.fn(async () => 'PONG'),
        _store: store,
    }
}

describe('Hono App Routes', () => {
    let mockRedis: MockRedis

    beforeEach(() => {
        mockRedis = createMockRedis()
    })

    describe('GET /', () => {
        it('should redirect to the docs', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/')
            expect(res.status).toBe(302)
            expect(res.headers.get('location')).toBe('https://posthog.com/docs/model-context-protocol')
        })
    })

    describe('health checks', () => {
        it('should return 200 with JSON on /healthz', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/healthz')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, unknown>
            expect(body).toEqual({ status: 'ok' })
        })

        it('should return 200 with JSON on /health', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/health')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, unknown>
            expect(body).toEqual({ status: 'ok' })
        })

        it('should return Cache-Control: no-store on /health', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/health')
            expect(res.headers.get('Cache-Control')).toBe('no-store')
        })

        it('should return 200 on /readyz when Redis is healthy', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/readyz')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, unknown>
            expect(body).toEqual({ status: 'ok', redis: 'healthy' })
        })

        it('should return 503 on /readyz when Redis ping fails', async () => {
            mockRedis.ping.mockRejectedValue(new Error('Connection refused'))
            const { app } = createApp(mockRedis)
            const res = await app.request('/readyz')
            expect(res.status).toBe(503)
            const body = (await res.json()) as Record<string, unknown>
            expect(body.status).toBe('error')
        })

        it('should return 503 on /readyz when Redis returns unexpected value', async () => {
            mockRedis.ping.mockResolvedValue('NOT_PONG')
            const { app } = createApp(mockRedis)
            const res = await app.request('/readyz')
            expect(res.status).toBe(503)
        })
    })

    describe('GET /.well-known/openai-apps-challenge', () => {
        it('should return the challenge token', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/.well-known/openai-apps-challenge')
            expect(res.status).toBe(200)
            const body = await res.text()
            expect(body).toBe('pRLV9JYbPOF5Dy039v3Rn3-qrMuKqZ2_4SsX9GoL9aU')
        })
    })

    describe('security headers', () => {
        it('should include X-Content-Type-Options: nosniff', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/healthz')
            expect(res.headers.get('X-Content-Type-Options')).toBe('nosniff')
        })

        it('should include X-Frame-Options: DENY', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/healthz')
            expect(res.headers.get('X-Frame-Options')).toBe('DENY')
        })
    })

    describe('OAuth Protected Resource Metadata', () => {
        it('should return metadata for bare /.well-known/oauth-protected-resource', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers).toBeTruthy()
            expect(body.bearer_methods_supported).toEqual(['header'])
            expect(body.scopes_supported).toBeTruthy()
        })

        it('should return metadata for /mcp path', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource/mcp')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.resource).toContain('/mcp')
        })

        it('should use oauth.posthog.com as authorization server', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource/mcp')
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers[0]).toBe('https://oauth.posthog.com')
        })

        it('should set Cache-Control header', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource/mcp')
            expect(res.headers.get('Cache-Control')).toBe('public, max-age=3600')
        })
    })

    describe('hostname-based region detection', () => {
        it('should detect EU from mcp.eu.posthog.com via X-Forwarded-Host', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: { 'X-Forwarded-Host': 'mcp.eu.posthog.com' },
            })
            expect(res.status).toBe(401)
            const wwwAuth = res.headers.get('WWW-Authenticate') || ''
            expect(wwwAuth).toContain('mcp.eu.posthog.com')
        })

        it('should detect US from mcp.us.posthog.com', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request(
                new Request('http://mcp.us.posthog.com/.well-known/oauth-protected-resource/mcp')
            )
            expect(res.status).toBe(200)
        })

        it('should detect EU from legacy mcp-eu.posthog.com', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: { 'X-Forwarded-Host': 'mcp-eu.posthog.com' },
            })
            expect(res.status).toBe(401)
            const wwwAuth = res.headers.get('WWW-Authenticate') || ''
            expect(wwwAuth).toContain('region=eu')
        })
    })

    describe('MCP auth on /mcp', () => {
        it('should return 401 with WWW-Authenticate when no token', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/mcp', { method: 'POST' })
            expect(res.status).toBe(401)
            const text = await res.text()
            expect(text).toContain('No token provided')
            expect(res.headers.get('WWW-Authenticate')).toContain('Bearer')
            expect(res.headers.get('WWW-Authenticate')).toContain('oauth-protected-resource/mcp')
        })

        it('should return 401 for invalid token prefix', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: { Authorization: 'Bearer bad_token' },
            })
            expect(res.status).toBe(401)
            expect(await res.text()).toContain('Invalid token')
        })

        it('should pass auth check for phx_ tokens (may fail later at init)', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: {
                    Authorization: 'Bearer phx_test_token',
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'initialize',
                    params: {
                        protocolVersion: '2024-11-05',
                        capabilities: {},
                        clientInfo: { name: 'test', version: '1.0' },
                    },
                    id: 1,
                }),
            })
            // Token format check passes — response is NOT "Invalid token"
            const body = await res.text()
            expect(body).not.toContain('Invalid token')
        })

        it('should pass auth check for pha_ tokens (may fail later at init)', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: {
                    Authorization: 'Bearer pha_test_token',
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'initialize',
                    params: {
                        protocolVersion: '2024-11-05',
                        capabilities: {},
                        clientInfo: { name: 'test', version: '1.0' },
                    },
                    id: 1,
                }),
            })
            // Token format check passes — response is NOT "Invalid token"
            const body = await res.text()
            expect(body).not.toContain('Invalid token')
        })

        it('should pass auth check for ID-JAG access tokens (typ: at+jwt)', async () => {
            // Synthesize a JWT-shaped token: header `{"typ":"at+jwt","alg":"RS256"}`,
            // a stub payload, and a placeholder signature. The MCP gate only inspects
            // the header — the PostHog API verifies the signature downstream.
            const headerB64 = btoa('{"typ":"at+jwt","alg":"RS256"}')
                .replace(/=+$/, '')
                .replace(/\+/g, '-')
                .replace(/\//g, '_')
            const payloadB64 = btoa('{"sub":"example.com:user@example.com","aud":"https://posthog.test"}')
                .replace(/=+$/, '')
                .replace(/\+/g, '-')
                .replace(/\//g, '_')
            const idJagToken = `${headerB64}.${payloadB64}.signature`

            const { app } = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${idJagToken}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'initialize',
                    params: {
                        protocolVersion: '2024-11-05',
                        capabilities: {},
                        clientInfo: { name: 'test', version: '1.0' },
                    },
                    id: 1,
                }),
            })
            const body = await res.text()
            expect(body).not.toContain('Invalid token')
        })

        it('should reject non-id-jag JWTs (e.g. typ: JWT)', async () => {
            // A JWT without `typ: at+jwt` is not an ID-JAG access token — e.g.
            // a sharing JWT — and must be rejected here so the right backend
            // takes over (or fails with the documented invalid-token response).
            const headerB64 = btoa('{"typ":"JWT","alg":"HS256"}')
                .replace(/=+$/, '')
                .replace(/\+/g, '-')
                .replace(/\//g, '_')
            const wrongJwt = `${headerB64}.eyJzdWIiOiJ4In0.sig`

            const { app } = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: { Authorization: `Bearer ${wrongJwt}` },
            })
            expect(res.status).toBe(401)
            expect(await res.text()).toContain('Invalid token')
        })
    })

    describe('OAuth redirect routes', () => {
        it('should redirect /.well-known/oauth-authorization-server', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-authorization-server', { redirect: 'manual' })
            expect([301, 302]).toContain(res.status)
            expect(res.headers.get('Location')).toContain('oauth.posthog.com')
        })

        it('should redirect /.well-known/jwks.json with 301', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/.well-known/jwks.json', { redirect: 'manual' })
            expect(res.status).toBe(301)
        })

        it('should redirect /oauth/* routes with 301', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/oauth/authorize', { redirect: 'manual' })
            expect(res.status).toBe(301)
        })

        it('should redirect /register with 307 (preserves POST)', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/register', { method: 'POST', redirect: 'manual' })
            expect(res.status).toBe(307)
            expect(res.headers.get('Location')).toContain('/oauth/register')
        })

        it('should redirect /authorize with 302', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/authorize', { redirect: 'manual' })
            expect(res.status).toBe(302)
            expect(res.headers.get('Location')).toContain('/oauth/authorize')
        })

        it('should redirect /token with 307 (preserves POST)', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/token', { method: 'POST', redirect: 'manual' })
            expect(res.status).toBe(307)
            expect(res.headers.get('Location')).toContain('/oauth/token')
        })
    })

    describe('Streamable HTTP endpoint', () => {
        it('should return 405 for unsupported method (PUT)', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'PUT',
                headers: { Authorization: 'Bearer phx_test' },
            })
            expect(res.status).toBe(405)
        })

        it('should return 405 for DELETE (stateless, no session management)', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'DELETE',
                headers: {
                    Authorization: 'Bearer phx_test',
                    'mcp-session-id': 'non-existent',
                },
            })
            expect(res.status).toBe(405)
        })
    })

    describe('404 handling', () => {
        it('should return 404 for unknown routes', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/unknown-path')
            expect(res.status).toBe(404)
        })

        it('should return 404 for /api paths', async () => {
            const { app } = createApp(mockRedis)
            const res = await app.request('/api/anything')
            expect(res.status).toBe(404)
        })
    })

    describe('session isolation', () => {
        it('should create independent app instances with separate session maps', async () => {
            const redis1 = createMockRedis()
            const redis2 = createMockRedis()
            const { app: app1 } = createApp(redis1)
            const { app: app2 } = createApp(redis2)

            const res1 = await app1.request('/healthz')
            const res2 = await app2.request('/healthz')
            expect(res1.status).toBe(200)
            expect(res2.status).toBe(200)
        })
    })

    describe('confirmed-action runtime', () => {
        afterEach(() => {
            // Restore the signing key after the "missing key" test below
            // unsets it, so following tests don't bleed into each other.
            process.env.MCP_SIGNED_STATE_KEY = TEST_SIGNING_KEY
        })

        it('installs the runtime so generated -prepare/-execute handlers can resolve it', async () => {
            // createApp wires setConfirmedActionRuntime at boot. Without
            // that wiring, getConfirmedActionRuntime() throws — so the
            // mere fact that we can resolve a non-undefined runtime after
            // createApp ran proves the boot path is in place.
            createApp(mockRedis)
            const { getConfirmedActionRuntime } = await import('@/tools/confirmed-action-registry')
            const runtime = getConfirmedActionRuntime()
            expect(runtime.codec).toBeInstanceOf(Object)
            expect(runtime.ledger).toBeInstanceOf(Object)
        })

        it('overwrites the singleton on each createApp call (latest wins)', async () => {
            // app.ts deliberately re-installs the runtime on every
            // createApp. Lock that behavior down so a future "guard
            // against re-install" change doesn't silently make the second
            // app instance share the first app's Redis-bound ledger.
            const { getConfirmedActionRuntime } = await import('@/tools/confirmed-action-registry')
            const redis1 = createMockRedis()
            createApp(redis1)
            const first = getConfirmedActionRuntime()
            const redis2 = createMockRedis()
            createApp(redis2)
            const second = getConfirmedActionRuntime()
            expect(second).not.toBe(first)
            expect(second.ledger).not.toBe(first.ledger)
        })

        it('boots without a signing key — confirmed_action paradigm is disabled but the app still serves', async () => {
            // Option B: missing key disables the paradigm but does NOT
            // crash the app. Other tools keep working; only confirmed_action
            // tools fail at request time. Assert: app responds normally
            // AND getConfirmedActionRuntime() throws with a message that
            // points at the env var.
            delete process.env.MCP_SIGNED_STATE_KEY
            const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
            try {
                const { app } = createApp(mockRedis)
                const res = await app.request('/healthz')
                expect(res.status).toBe(200)
                expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining('confirmed-action paradigm disabled'))

                const { getConfirmedActionRuntime } = await import('@/tools/confirmed-action-registry')
                expect(() => getConfirmedActionRuntime()).toThrow(/MCP_SIGNED_STATE_KEY/)
            } finally {
                errorSpy.mockRestore()
            }
        })
    })
})
