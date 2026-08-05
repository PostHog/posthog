import type { Redis } from 'ioredis'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { Config } from '@/lib/config.js'
import { logger } from '@/lib/logging.js'

vi.mock('@/lib/jwt.js', () => ({
    validateSandboxEventIngestToken: vi.fn(),
    validateStreamReadToken: vi.fn(),
    loadPublicKeys: vi.fn(),
}))

import { createApp } from '@/hono/app.js'
import { validateSandboxEventIngestToken } from '@/lib/jwt.js'

const mockValidate = vi.mocked(validateSandboxEventIngestToken)

function makeConfig(): Config {
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
    }
}

describe('app onError', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        mockValidate.mockResolvedValue({ runId: 'run-123', taskId: 'task-abc', teamId: 42 })
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
})
