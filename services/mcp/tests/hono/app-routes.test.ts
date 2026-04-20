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
        it('should return landing page HTML with 200', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/')
            expect(res.status).toBe(200)
            const text = await res.text()
            expect(text).toContain('html')
        })
    })

    describe('health checks', () => {
        it('should return 200 with JSON on /healthz', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/healthz')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, unknown>
            expect(body).toEqual({ status: 'ok' })
        })

        it('should return 200 on /readyz when Redis is healthy', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/readyz')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, unknown>
            expect(body).toEqual({ status: 'ok', redis: 'healthy' })
        })

        it('should return 503 on /readyz when Redis ping fails', async () => {
            mockRedis.ping.mockRejectedValue(new Error('Connection refused'))
            const app = createApp(mockRedis)
            const res = await app.request('/readyz')
            expect(res.status).toBe(503)
            const body = (await res.json()) as Record<string, unknown>
            expect(body.status).toBe('error')
        })

        it('should return 503 on /readyz when Redis returns unexpected value', async () => {
            mockRedis.ping.mockResolvedValue('NOT_PONG')
            const app = createApp(mockRedis)
            const res = await app.request('/readyz')
            expect(res.status).toBe(503)
        })
    })

    describe('security headers', () => {
        it('should include X-Content-Type-Options: nosniff', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/healthz')
            expect(res.headers.get('X-Content-Type-Options')).toBe('nosniff')
        })

        it('should include X-Frame-Options: DENY', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/healthz')
            expect(res.headers.get('X-Frame-Options')).toBe('DENY')
        })
    })

    describe('CORS', () => {
        it('should respond to OPTIONS preflight', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'OPTIONS',
                headers: {
                    Origin: 'https://example.com',
                    'Access-Control-Request-Method': 'POST',
                },
            })
            expect(res.status).toBe(204)
            expect(res.headers.get('Access-Control-Allow-Methods')).toContain('POST')
        })

        it('should expose mcp-session-id header', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'OPTIONS',
                headers: {
                    Origin: 'https://example.com',
                    'Access-Control-Request-Method': 'POST',
                },
            })
            expect(res.headers.get('Access-Control-Expose-Headers')).toContain('mcp-session-id')
        })
    })

    describe('OAuth Protected Resource Metadata', () => {
        it('should return metadata for bare /.well-known/oauth-protected-resource', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers).toBeTruthy()
            expect(body.bearer_methods_supported).toEqual(['header'])
            expect(body.scopes_supported).toBeTruthy()
        })

        it('should return metadata for /mcp path', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource/mcp')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.resource).toContain('/mcp')
        })

        it('should return metadata for /sse path', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource/sse')
            expect(res.status).toBe(200)
            const body = (await res.json()) as Record<string, any>
            expect(body.resource).toContain('/sse')
        })

        it('should use oauth.posthog.com as authorization server', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource/mcp')
            const body = (await res.json()) as Record<string, any>
            expect(body.authorization_servers[0]).toBe('https://oauth.posthog.com')
        })

        it('should set Cache-Control header', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-protected-resource/mcp')
            expect(res.headers.get('Cache-Control')).toBe('public, max-age=3600')
        })
    })

    describe('hostname-based region detection', () => {
        it('should detect EU from mcp.eu.posthog.com via X-Forwarded-Host', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: { 'X-Forwarded-Host': 'mcp.eu.posthog.com' },
            })
            expect(res.status).toBe(401)
            const wwwAuth = res.headers.get('WWW-Authenticate') || ''
            expect(wwwAuth).toContain('mcp.eu.posthog.com')
        })

        it('should detect US from mcp.us.posthog.com', async () => {
            const app = createApp(mockRedis)
            const res = await app.request(
                new Request('http://mcp.us.posthog.com/.well-known/oauth-protected-resource/mcp')
            )
            expect(res.status).toBe(200)
        })

        it('should detect EU from legacy mcp-eu.posthog.com', async () => {
            const app = createApp(mockRedis)
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
            const app = createApp(mockRedis)
            const res = await app.request('/mcp', { method: 'POST' })
            expect(res.status).toBe(401)
            const text = await res.text()
            expect(text).toContain('No token provided')
            expect(res.headers.get('WWW-Authenticate')).toContain('Bearer')
            expect(res.headers.get('WWW-Authenticate')).toContain('oauth-protected-resource/mcp')
        })

        it('should return 401 for invalid token prefix', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'POST',
                headers: { Authorization: 'Bearer bad_token' },
            })
            expect(res.status).toBe(401)
            expect(await res.text()).toContain('Invalid token')
        })

        it('should accept phx_ tokens (not 401)', async () => {
            const app = createApp(mockRedis)
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

        it('should accept pha_ tokens (not 401)', async () => {
            const app = createApp(mockRedis)
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

    describe('MCP auth on /sse', () => {
        it('should return 401 with WWW-Authenticate when no token', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/sse', { method: 'GET' })
            expect(res.status).toBe(401)
            expect(res.headers.get('WWW-Authenticate')).toContain('oauth-protected-resource/sse')
        })

        it('should return 401 for invalid token prefix on SSE', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/sse', {
                method: 'GET',
                headers: { Authorization: 'Bearer invalid' },
            })
            expect(res.status).toBe(401)
        })
    })

    describe('OAuth redirect routes', () => {
        it('should redirect /.well-known/oauth-authorization-server', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/.well-known/oauth-authorization-server', { redirect: 'manual' })
            expect([301, 302]).toContain(res.status)
            expect(res.headers.get('Location')).toContain('oauth.posthog.com')
        })

        it('should redirect /.well-known/jwks.json with 301', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/.well-known/jwks.json', { redirect: 'manual' })
            expect(res.status).toBe(301)
        })

        it('should redirect /oauth/* routes with 301', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/oauth/authorize', { redirect: 'manual' })
            expect(res.status).toBe(301)
        })

        it('should redirect /register with 307 (preserves POST)', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/register', { method: 'POST', redirect: 'manual' })
            expect(res.status).toBe(307)
            expect(res.headers.get('Location')).toContain('/oauth/register')
        })

        it('should redirect /authorize with 302', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/authorize', { redirect: 'manual' })
            expect(res.status).toBe(302)
            expect(res.headers.get('Location')).toContain('/oauth/authorize')
        })

        it('should redirect /token with 307 (preserves POST)', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/token', { method: 'POST', redirect: 'manual' })
            expect(res.status).toBe(307)
            expect(res.headers.get('Location')).toContain('/oauth/token')
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

        it('should return 405 for unsupported method (DELETE)', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/sse', {
                method: 'DELETE',
                headers: { Authorization: 'Bearer phx_test' },
            })
            expect(res.status).toBe(405)
        })
    })

    describe('Streamable HTTP endpoint', () => {
        it('should return 405 for unsupported method (PUT)', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'PUT',
                headers: { Authorization: 'Bearer phx_test' },
            })
            expect(res.status).toBe(405)
        })

        it('should return 404 for DELETE with non-existent session', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/mcp', {
                method: 'DELETE',
                headers: {
                    Authorization: 'Bearer phx_test',
                    'mcp-session-id': 'non-existent',
                },
            })
            expect(res.status).toBe(404)
        })
    })

    describe('404 handling', () => {
        it('should return 404 for unknown routes', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/unknown-path')
            expect(res.status).toBe(404)
        })

        it('should return 404 for /api paths', async () => {
            const app = createApp(mockRedis)
            const res = await app.request('/api/anything')
            expect(res.status).toBe(404)
        })
    })

    describe('session isolation', () => {
        it('should create independent app instances with separate session maps', async () => {
            const redis1 = createMockRedis()
            const redis2 = createMockRedis()
            const app1 = createApp(redis1)
            const app2 = createApp(redis2)

            const res1 = await app1.request('/healthz')
            const res2 = await app2.request('/healthz')
            expect(res1.status).toBe(200)
            expect(res2.status).toBe(200)
        })
    })
})
