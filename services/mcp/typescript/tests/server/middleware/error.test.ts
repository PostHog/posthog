import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createErrorMiddleware } from '@/server/middleware/error'
import { Metrics } from '@/server/metrics'
import { createMockRequest, createMockResponse, createMockNext } from '../fixtures'

describe('error middleware', () => {
    let metrics: Metrics

    beforeEach(() => {
        metrics = new Metrics()
        vi.spyOn(metrics, 'incRequest')
        vi.spyOn(console, 'error').mockImplementation(() => {})
    })

    describe('createErrorMiddleware', () => {
        it('returns 500 status', () => {
            const middleware = createErrorMiddleware(metrics)
            const error = new Error('Test error')
            const req = createMockRequest({ method: 'POST' })
            const res = createMockResponse()

            middleware(error, req, res, createMockNext())

            expect(res._status).toBe(500)
        })

        it('returns generic error message', () => {
            const middleware = createErrorMiddleware(metrics)
            const error = new Error('Sensitive internal error details')
            const req = createMockRequest()
            const res = createMockResponse()

            middleware(error, req, res, createMockNext())

            expect(res._body).toEqual({ error: 'Internal server error' })
        })

        it('logs the error', () => {
            const middleware = createErrorMiddleware(metrics)
            const error = new Error('Test error')
            const req = createMockRequest()
            const res = createMockResponse()

            middleware(error, req, res, createMockNext())

            expect(console.error).toHaveBeenCalledWith('Server error:', error)
        })

        it('records 500 metric', () => {
            const middleware = createErrorMiddleware(metrics)
            const error = new Error('Test error')
            const req = createMockRequest({ method: 'POST' })
            const res = createMockResponse()

            middleware(error, req, res, createMockNext())

            expect(metrics.incRequest).toHaveBeenCalledWith('POST', '500')
        })
    })
})
