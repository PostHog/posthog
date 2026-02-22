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
    })

    describe('MCP endpoint authentication', () => {
        it('should return 401 when no token is provided', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/mcp', { method: 'POST' })
            expect(res.status).toBe(401)
            const text = await res.text()
            expect(text).toContain('No token provided')
            expect(res.headers.get('WWW-Authenticate')).toContain('Bearer')
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

        it('should redirect /register', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/register', { method: 'POST', redirect: 'manual' })
            expect(res.status).toBe(307)
        })

        it('should redirect /token', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/token', { method: 'POST', redirect: 'manual' })
            expect(res.status).toBe(307)
        })
    })

    describe('404 handling', () => {
        it('should return 404 for unknown routes', async () => {
            const app = createApp(mockRedis as any)
            const res = await app.request('/unknown-path')
            expect(res.status).toBe(404)
        })
    })

    describe('DELETE /mcp (session not found)', () => {
        it('should return 404 for non-existent session with valid token', async () => {
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
})
