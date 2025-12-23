import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createHealthHandler, createReadyHandler } from '@/server/handlers/health'
import { createMockRequest, createMockResponse, createMockRedis } from '../fixtures'

describe('health handlers', () => {
    describe('createHealthHandler', () => {
        it('returns OK', () => {
            const handler = createHealthHandler()
            const req = createMockRequest()
            const res = createMockResponse()

            handler(req, res, vi.fn())

            expect(res._body).toBe('OK')
        })
    })

    describe('createReadyHandler', () => {
        it('returns OK when no redis configured', async () => {
            const handler = createReadyHandler(undefined)
            const req = createMockRequest()
            const res = createMockResponse()

            await handler(req, res, vi.fn())

            expect(res._body).toBe('OK')
        })

        it('returns OK when redis ping succeeds', async () => {
            const redis = createMockRedis()
            const handler = createReadyHandler(redis)
            const req = createMockRequest()
            const res = createMockResponse()

            await handler(req, res, vi.fn())

            expect(redis.ping).toHaveBeenCalled()
            expect(res._body).toBe('OK')
        })

        it('returns 503 when redis ping fails', async () => {
            const redis = createMockRedis()
            vi.mocked(redis.ping).mockRejectedValue(new Error('Connection refused'))

            const handler = createReadyHandler(redis)
            const req = createMockRequest()
            const res = createMockResponse()

            await handler(req, res, vi.fn())

            expect(res._status).toBe(503)
            expect(res._body).toBe('Redis not ready')
        })
    })
})
