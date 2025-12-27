import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createMcpHandler } from '@/server/handlers/mcp'
import { Metrics } from '@/server/metrics'
import type { McpService } from '@/server/services/mcp'
import { createMockRequest, createMockResponse, createMockNext } from '../fixtures'

describe('mcp handler', () => {
    let mockMcpService: McpService
    let metrics: Metrics
    let mockHandler: ReturnType<typeof vi.fn>

    beforeEach(() => {
        vi.clearAllMocks()
        metrics = new Metrics()
        vi.spyOn(metrics, 'incRequest')
        vi.spyOn(metrics, 'observeDuration')

        mockHandler = vi.fn().mockResolvedValue(undefined)
        mockMcpService = {
            createHandler: vi.fn().mockResolvedValue(mockHandler),
        } as unknown as McpService
    })

    describe('authentication', () => {
        it('returns 401 when no token provided', async () => {
            const handler = createMcpHandler(mockMcpService, metrics)
            const req = createMockRequest({ headers: {} })
            const res = createMockResponse()

            await handler(req, res, createMockNext())

            expect(res._status).toBe(401)
            expect(res._body).toEqual(expect.objectContaining({
                error: expect.stringContaining('No token provided'),
            }))
            expect(metrics.incRequest).toHaveBeenCalledWith('GET', '401')
        })

        it('returns 401 for invalid token format', async () => {
            const handler = createMcpHandler(mockMcpService, metrics)
            const req = createMockRequest({
                headers: { authorization: 'Bearer invalid_token' },
            })
            const res = createMockResponse()

            await handler(req, res, createMockNext())

            expect(res._status).toBe(401)
            expect(res._body).toEqual(expect.objectContaining({
                error: expect.stringContaining('Invalid token format'),
            }))
        })

        it.each([
            ['phx_test_token', 'personal API key'],
            ['pha_test_token', 'project API key'],
        ])('accepts %s (%s)', async (token) => {
            const handler = createMcpHandler(mockMcpService, metrics)
            const req = createMockRequest({
                method: 'POST',
                url: '/mcp',
                headers: { authorization: `Bearer ${token}`, host: 'localhost:8080' },
            })
            const res = createMockResponse()

            await handler(req, res, createMockNext())

            expect(mockMcpService.createHandler).toHaveBeenCalledWith(
                expect.objectContaining({ apiToken: token })
            )
        })
    })

    describe('request handling', () => {
        it('extracts sessionId from query params', async () => {
            const handler = createMcpHandler(mockMcpService, metrics)
            const req = createMockRequest({
                method: 'POST',
                url: '/mcp?sessionId=test-session',
                headers: { authorization: 'Bearer phx_test', host: 'localhost' },
            })
            const res = createMockResponse()

            await handler(req, res, createMockNext())

            expect(mockMcpService.createHandler).toHaveBeenCalledWith(
                expect.objectContaining({ sessionId: 'test-session' })
            )
        })

        it('extracts features from query params', async () => {
            const handler = createMcpHandler(mockMcpService, metrics)
            const req = createMockRequest({
                method: 'POST',
                url: '/mcp?features=feature1,feature2',
                headers: { authorization: 'Bearer phx_test', host: 'localhost' },
            })
            const res = createMockResponse()

            await handler(req, res, createMockNext())

            expect(mockMcpService.createHandler).toHaveBeenCalledWith(
                expect.objectContaining({ features: ['feature1', 'feature2'] })
            )
        })

        it('calls MCP handler with request and response', async () => {
            const handler = createMcpHandler(mockMcpService, metrics)
            const req = createMockRequest({
                method: 'POST',
                url: '/mcp',
                headers: { authorization: 'Bearer phx_test', host: 'localhost' },
            })
            const res = createMockResponse()

            await handler(req, res, createMockNext())

            expect(mockHandler).toHaveBeenCalledWith(req, res)
        })

        it('records metrics after successful handling', async () => {
            const handler = createMcpHandler(mockMcpService, metrics)
            const req = createMockRequest({
                method: 'POST',
                url: '/mcp',
                headers: { authorization: 'Bearer phx_test', host: 'localhost' },
            })
            const res = createMockResponse()

            await handler(req, res, createMockNext())

            expect(metrics.observeDuration).toHaveBeenCalledWith('POST', expect.any(Number))
            expect(metrics.incRequest).toHaveBeenCalledWith('POST', '200')
        })
    })

    describe('error handling', () => {
        it('passes errors to next middleware', async () => {
            const error = new Error('Test error')
            mockMcpService.createHandler = vi.fn().mockRejectedValue(error)

            const handler = createMcpHandler(mockMcpService, metrics)
            const req = createMockRequest({
                method: 'POST',
                url: '/mcp',
                headers: { authorization: 'Bearer phx_test', host: 'localhost' },
            })
            const res = createMockResponse()
            const next = createMockNext()

            await handler(req, res, next)

            expect(next).toHaveBeenCalledWith(error)
        })
    })
})
