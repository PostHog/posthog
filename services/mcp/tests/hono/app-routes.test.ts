import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createApp } from '@/hono/app'

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
function createMockRedis() {
    const store = new Map<string, string>()
    return {
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string) => {
            store.set(key, value)
            return 'OK'
        }),
        del: vi.fn(async (...keys: string[]) => keys.length),
        scan: vi.fn(async () => ['0', []]),
        ping: vi.fn(async () => 'PONG'),
        _store: store,
    }
}

describe('Hono App Routes', () => {
    let mockRedis: ReturnType<typeof createMockRedis>

    beforeEach(() => {
        mockRedis = createMockRedis()
    })

    describe('GET /', () => {
        it('should return landing page HTML', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/')
            expect(res.status).toBe(200)
            const text = await res.text()
            expect(text).toContain('html')
        })
    })

    describe('GET /healthz', () => {
        it('should return 200 with ok status', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/healthz')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, unknown>
            expect(body).toEqual({ status: 'ok' })
        })
    })

    describe('GET /readyz', () => {
        it('should return 200 when Redis is healthy', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/readyz')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, unknown>
            expect(body).toEqual({ status: 'ok', redis: 'healthy' })
        })

        it('should return 503 when Redis ping fails', async () => {
            mockRedis.ping.mockRejectedValue(new Error('Connection refused'))
            const app = createApp(mockRedis as any)
            const res = await app.request('/readyz')
            expect(res.status).toBe(503)
            const body = (await res.json()) as Record<string, unknown>
            expect(body.status).toBe('error')
        })

        it('should return 503 when Redis ping returns unexpected value', async () => {
            mockRedis.ping.mockResolvedValue('NOT_PONG')
            const app = createApp(mockRedis as any)
            const res = await app.request('/readyz')
            expect(res.status).toBe(503)
        })
    })

    describe('OAuth Protected Resource Metadata', () => {
        it('should return metadata for /.well-known/oauth-protected-resource/mcp', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/.well-known/oauth-protected-resource/mcp')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.resource).toContain('/mcp')
            expect(body.authorization_servers).toBeTruthy()
            expect(body.scopes_supported).toBeTruthy()
            expect(body.bearer_methods_supported).toEqual(['header'])
        })

        it('should respect region query param for authorization server', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/.well-known/oauth-protected-resource/mcp?region=eu')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers[0]).toContain('eu.posthog.com')
        })

        it('should default to US authorization server', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/.well-known/oauth-protected-resource/mcp')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers[0]).toContain('us.posthog.com')
        })

        it('should return metadata for /sse path', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/.well-known/oauth-protected-resource/sse')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.resource).toContain('/sse')
        })
    })

    describe('hostname-based region detection', () => {
        it('should detect EU region from mcp.eu.posthog.com', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request(
                new Request('http://mcp.eu.posthog.com/.well-known/oauth-protected-resource/mcp')
            )
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers[0]).toContain('eu.posthog.com')
        })

        it('should detect US region from mcp.us.posthog.com', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request(
                new Request('http://mcp.us.posthog.com/.well-known/oauth-protected-resource/mcp')
            )
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers[0]).toContain('us.posthog.com')
        })

        it('should detect EU region from legacy mcp-eu.posthog.com', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request(
                new Request('http://mcp-eu.posthog.com/.well-known/oauth-protected-resource/mcp')
            )
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers[0]).toContain('eu.posthog.com')
        })

        it('should prioritize hostname over query param', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request(
                new Request('http://mcp.eu.posthog.com/.well-known/oauth-protected-resource/mcp?region=us')
            )
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers[0]).toContain('eu.posthog.com')
        })
    })

    describe('MCP endpoint authentication', () => {
        it('should return 401 when no token is provided on /mcp', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/mcp', { method: 'POST' })
            expect(res.status).toBe(401)
            const text = await res.text()
            expect(text).toContain('No token provided')
            expect(res.headers.get('WWW-Authenticate')).toContain('Bearer')
            expect(res.headers.get('WWW-Authenticate')).toContain('oauth-protected-resource/mcp')
        })

        it('should return 401 when no token is provided on /sse', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/sse', { method: 'GET' })
            expect(res.status).toBe(401)
            const text = await res.text()
            expect(text).toContain('No token provided')
            expect(res.headers.get('WWW-Authenticate')).toContain('oauth-protected-resource/sse')
        })

        it('should return 401 for invalid token format', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: { Authorization: 'Bearer invalid_token' },
            })
            expect(res.status).toBe(401)
            const text = await res.text()
            expect(text).toContain('Invalid token')
        })

        it('should accept phx_ prefixed tokens', async () => {
            const app = createApp(mockRedis as any)
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
            expect(res.status).not.toBe(401)
        })

        it('should accept pha_ prefixed tokens', async () => {
            const app = createApp(mockRedis as any)
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
            expect(res.status).not.toBe(401)
        })
    })

    describe('OAuth redirect routes', () => {
        it('should redirect /.well-known/oauth-authorization-server', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/.well-known/oauth-authorization-server', { redirect: 'manual' })
            expect([301, 302]).toContain(res.status)
        })

        it('should redirect /oauth/ routes', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/oauth/authorize', { redirect: 'manual' })
            expect([301, 302]).toContain(res.status)
        })

        it('should redirect /register with 307 (preserves POST)', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/register', { method: 'POST', redirect: 'manual' })
            expect(res.status).toBe(307)
        })

        it('should redirect /token with 307 (preserves POST)', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/token', { method: 'POST', redirect: 'manual' })
            expect(res.status).toBe(307)
        })

        it('should redirect /authorize with 302', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/authorize', { redirect: 'manual' })
            expect(res.status).toBe(302)
        })

        it('should include region in redirect for EU hostname', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request(
                new Request('http://mcp.eu.posthog.com/.well-known/oauth-authorization-server'),
                { redirect: 'manual' }
            )
            expect([301, 302]).toContain(res.status)
            const location = res.headers.get('Location') || ''
            expect(location).toContain('eu.posthog.com')
        })
    })

    describe('SSE endpoint', () => {
        it('should return 401 when no token is provided', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/sse', { method: 'GET' })
            expect(res.status).toBe(401)
        })

        it('should return 400 for POST without sessionId', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/sse', {
                method: 'POST',
                headers: {
                    Authorization: 'Bearer phx_test_token',
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ jsonrpc: '2.0', method: 'ping', id: 1 }),
            })
            expect(res.status).toBe(400)
        })

        it('should return 404 for POST with non-existent session', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/sse?sessionId=non-existent', {
                method: 'POST',
                headers: {
                    Authorization: 'Bearer phx_test_token',
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ jsonrpc: '2.0', method: 'ping', id: 1 }),
            })
            expect(res.status).toBe(404)
        })

        it('should return 405 for unsupported methods', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/sse', {
                method: 'DELETE',
                headers: { Authorization: 'Bearer phx_test_token' },
            })
            expect(res.status).toBe(405)
        })
    })

    describe('Streamable HTTP endpoint', () => {
        it('should return 405 for unsupported methods', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/mcp', {
                method: 'PUT',
                headers: { Authorization: 'Bearer phx_test_token' },
            })
            expect(res.status).toBe(405)
        })

        it('should return 404 for DELETE with non-existent session', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/mcp', {
                method: 'DELETE',
                headers: {
                    Authorization: 'Bearer phx_test_token',
                    'mcp-session-id': 'non-existent-session',
                },
            })
            expect(res.status).toBe(404)
        })
    })

    describe('404 handling', () => {
        it('should return 404 for unknown routes', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/unknown-path')
            expect(res.status).toBe(404)
        })
    })
})
