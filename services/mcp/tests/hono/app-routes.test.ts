import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'

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
        it('should return landing page HTML', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/')
            expect(res.status).toBe(200)
        })
    })

    describe('health checks', () => {
        it('should return 200 on /healthz', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/healthz')
            expect(res.status).toBe(200)
        })

        it('should return 200 on /readyz when Redis healthy', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/readyz')
            expect(res.status).toBe(200)
        })

        it('should return 503 on /readyz when Redis fails', async () => {
            mockRedis.ping.mockRejectedValue(new Error('Connection refused'))
            const app = createApp(mockRedis)
            const res = await app.request('/readyz')
            expect(res.status).toBe(503)
        })
    })

    describe('OAuth Protected Resource Metadata', () => {
        it('should return metadata for bare path', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers).toBeTruthy()
            expect(body.bearer_methods_supported).toEqual(['header'])
        })

        it('should return metadata for /mcp path', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource/mcp')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.resource).toContain('/mcp')
        })

        it('should use oauth proxy URL for authorization server', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource/mcp')
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers[0]).toContain('oauth.posthog.com')
        })
    })

    describe('hostname-based region detection', () => {
        it('should detect EU region from mcp.eu.posthog.com', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: { 'X-Forwarded-Host': 'mcp.eu.posthog.com' },
            })
            expect(res.status).toBe(401)
            const wwwAuth = res.headers.get('WWW-Authenticate') || ''
            expect(wwwAuth).toContain('mcp.eu.posthog.com')
        })
    })

    describe('MCP auth', () => {
        it('should return 401 when no token on /mcp', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/mcp', { method: 'POST' })
            expect(res.status).toBe(401)
            expect(res.headers.get('WWW-Authenticate')).toContain('Bearer')
        })

        it('should return 401 when no token on /sse', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/sse', { method: 'GET' })
            expect(res.status).toBe(401)
        })

        it('should return 401 for invalid token format', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: { Authorization: 'Bearer bad_token' },
            })
            expect(res.status).toBe(401)
        })
    })

    describe('OAuth redirect routes', () => {
        it('should redirect /.well-known/oauth-authorization-server', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-authorization-server', { redirect: 'manual' })
            expect([301, 302]).toContain(res.status)
        })

        it('should redirect /register with 307', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/register', { method: 'POST', redirect: 'manual' })
            expect(res.status).toBe(307)
        })
    })

    describe('SSE endpoint', () => {
        it('should return 400 for POST without sessionId', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/sse', {
                method: 'POST',
                headers: { Authorization: 'Bearer phx_test', 'Content-Type': 'application/json' },
                body: '{}',
            })
            expect(res.status).toBe(400)
        })

        it('should return 404 for POST with non-existent session', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/sse?sessionId=fake', {
                method: 'POST',
                headers: { Authorization: 'Bearer phx_test', 'Content-Type': 'application/json' },
                body: '{}',
            })
            expect(res.status).toBe(404)
        })
    })

    describe('404', () => {
        it('should return 404 for unknown routes', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/unknown-path')
            expect(res.status).toBe(404)
        })
    })
})
