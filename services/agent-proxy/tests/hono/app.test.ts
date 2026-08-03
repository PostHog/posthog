import type { Redis } from 'ioredis'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { Config } from '@/lib/config.js'
import { logger } from '@/lib/logging.js'

vi.mock('@/lib/jwt.js', () => ({
    validateSandboxEventIngestToken: vi.fn(),
    validateStreamReadToken: vi.fn(),
    validateTaskPortForwardToken: vi.fn(),
    loadPublicKeys: vi.fn(),
}))

import { createApp } from '@/hono/app.js'
import { validateSandboxEventIngestToken, validateTaskPortForwardToken } from '@/lib/jwt.js'

const mockValidate = vi.mocked(validateSandboxEventIngestToken)
const mockValidatePortForward = vi.mocked(validateTaskPortForwardToken)

function makeConfig(overrides?: Partial<Config>): Config {
    return {
        redisUrl: 'redis://localhost:6379',
        sandboxJwtPublicKeysPem: [],
        corsOrigins: new Set(),
        djangoCallbackBaseUrl: '',
        agentProxyCallbackSecret: '',
        maxConcurrentStreams: 1000,
        maxStreamsPerRun: 25,
        metricsToken: '',
        port: 8003,
        host: '0.0.0.0',
        shutdownGraceMs: 300_000,
        shutdownPrestopDelayMs: 0,
        ...overrides,
    }
}

describe('app onError', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        mockValidate.mockResolvedValue({ runId: 'run-123', taskId: 'task-abc', teamId: 42 })
        mockValidatePortForward.mockResolvedValue({
            runId: 'run-123',
            taskId: 'task-abc',
            teamId: 42,
            forwardId: 'forward-123',
            port: 8000,
            userId: 7,
        })
    })

    it('logs unexpected route errors with request context and returns JSON 500', async () => {
        const errorSpy = vi.spyOn(logger, 'error')
        const failingRedis = { get: vi.fn().mockRejectedValue(new Error('redis exploded')) } as unknown as Redis
        const { app } = createApp(failingRedis, makeConfig(), [])

        const res = await app.request('/v1/runs/run-123/ingest', {
            method: 'POST',
            headers: { Authorization: 'Bearer tok' },
            body: JSON.stringify({ seq: 1, event: {} }) + '\n',
        })

        expect(res.status).toBe(500)
        expect(await res.json()).toEqual({ error: 'Internal server error' })

        const logged = errorSpy.mock.calls.find((c) => c[0] === 'http.unhandled_error')?.[1] as Record<string, unknown>
        expect(logged).toMatchObject({ error: 'redis exploded', path: '/v1/runs/run-123/ingest', method: 'POST' })
        expect(logged.requestId).toBeTruthy()
    })

    it('sets an HttpOnly cookie for a valid port-forward auth URL', async () => {
        const redis = {} as unknown as Redis
        const { app } = createApp(
            redis,
            makeConfig({ djangoCallbackBaseUrl: 'http://django', agentProxyCallbackSecret: 'secret' }),
            []
        )
        const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(Response.json({ token: 'tok' }))

        const res = await app.request('/v1/ports/forward-123/auth/?ticket=ticket-123')

        expect(res.status).toBe(302)
        expect(res.headers.get('Location')).toBe('/v1/ports/forward-123/')
        expect(res.headers.get('Set-Cookie')).toContain('ph_task_port_forward=tok')
        expect(res.headers.get('Set-Cookie')).toContain('HttpOnly')
        expect(fetchMock).toHaveBeenCalledWith(
            'http://django/internal/tasks/port-forward/exchange-ticket/',
            expect.objectContaining({
                body: JSON.stringify({ ticket: 'ticket-123' }),
                headers: {
                    'Content-Type': 'application/json',
                    'X-Agent-Proxy-Secret': 'secret',
                },
            })
        )
        fetchMock.mockRestore()
    })

    it('resolves and proxies an authenticated port-forward request to the sandbox agent server', async () => {
        const redis = {} as unknown as Redis
        const { app } = createApp(
            redis,
            makeConfig({ djangoCallbackBaseUrl: 'http://django', agentProxyCallbackSecret: 'secret' }),
            []
        )
        const fetchMock = vi
            .spyOn(globalThis, 'fetch')
            .mockResolvedValueOnce(
                Response.json({
                    run_id: 'run-123',
                    task_id: 'task-abc',
                    team_id: 42,
                    forward_id: 'forward-123',
                    port: 8000,
                    sandbox_url: 'https://sandbox.modal.run',
                    connection_token: 'sandbox-jwt',
                    sandbox_connect_token: 'connect-token',
                })
            )
            .mockImplementationOnce(async (url, init) => {
                expect(String(url)).toBe(
                    'https://sandbox.modal.run/ports/8000/some/path?x=1&_modal_connect_token=connect-token'
                )
                expect(init).not.toBeUndefined()
                expect(((init as RequestInit).headers as Headers).get('Authorization')).toBe('Bearer sandbox-jwt')
                return new Response('ok', {
                    status: 201,
                    headers: {
                        Location: '/login',
                        'Service-Worker-Allowed': '/',
                        'X-Test': 'yes',
                    },
                })
            })

        const res = await app.request('/v1/ports/forward-123/some/path?x=1', {
            headers: { Authorization: 'Bearer tok' },
        })

        expect(res.status).toBe(201)
        expect(await res.text()).toBe('ok')
        expect(res.headers.get('Location')).toBe('/v1/ports/forward-123/login')
        expect(res.headers.get('Service-Worker-Allowed')).toBeNull()
        expect(res.headers.get('X-Test')).toBe('yes')
        expect(fetchMock).toHaveBeenNthCalledWith(
            1,
            'http://django/internal/tasks/port-forward/resolve/',
            expect.objectContaining({
                headers: {
                    'Content-Type': 'application/json',
                    'X-Agent-Proxy-Secret': 'secret',
                },
            })
        )
        expect(fetchMock).toHaveBeenCalledTimes(2)
        fetchMock.mockRestore()
    })

    it('rejects resolved port-forward targets outside allowed sandbox hosts', async () => {
        const redis = {} as unknown as Redis
        const { app } = createApp(
            redis,
            makeConfig({ djangoCallbackBaseUrl: 'http://django', agentProxyCallbackSecret: 'secret' }),
            []
        )
        const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
            Response.json({
                run_id: 'run-123',
                task_id: 'task-abc',
                team_id: 42,
                forward_id: 'forward-123',
                port: 8000,
                sandbox_url: 'http://169.254.169.254',
                connection_token: 'sandbox-jwt',
            })
        )

        const res = await app.request('/v1/ports/forward-123/', {
            headers: { Authorization: 'Bearer tok' },
        })

        expect(res.status).toBe(502)
        expect(await res.json()).toEqual({ error: 'Port forward target is not available' })
        expect(fetchMock).toHaveBeenCalledTimes(1)
        fetchMock.mockRestore()
    })
})
