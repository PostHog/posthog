import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createApp } from '@/server/app'
import { Metrics } from '@/server/metrics'
import type { McpService } from '@/server/services/mcp'
import { createMockRedis } from './fixtures'

describe('createApp', () => {
    let metrics: Metrics
    let mockMcpService: McpService

    beforeEach(() => {
        metrics = new Metrics()
        mockMcpService = {
            createHandler: vi.fn().mockResolvedValue(vi.fn()),
        } as unknown as McpService
    })

    it('creates an Express app', () => {
        const app = createApp({ metrics, mcpService: mockMcpService, redis: undefined })

        expect(app).toBeDefined()
        expect(typeof app.listen).toBe('function')
    })

    it('registers all expected routes', () => {
        const app = createApp({ metrics, mcpService: mockMcpService, redis: undefined })

        const routes = app._router.stack
            .filter((layer: { route?: { path: string } }) => layer.route)
            .map((layer: { route: { path: string; methods: Record<string, boolean> } }) => ({
                path: layer.route.path,
                methods: Object.keys(layer.route.methods),
            }))

        expect(routes).toContainEqual({ path: '/health', methods: ['get'] })
        expect(routes).toContainEqual({ path: '/ready', methods: ['get'] })
        expect(routes).toContainEqual({ path: '/_metrics', methods: ['get'] })
        expect(routes).toContainEqual({ path: '/', methods: ['get'] })
    })

    it('uses JSON middleware', () => {
        const app = createApp({ metrics, mcpService: mockMcpService, redis: undefined })

        const hasJsonMiddleware = app._router.stack.some(
            (layer: { name?: string }) => layer.name === 'jsonParser'
        )
        expect(hasJsonMiddleware).toBe(true)
    })

    it('works with redis configured', () => {
        const redis = createMockRedis()
        const app = createApp({ metrics, mcpService: mockMcpService, redis })

        expect(app).toBeDefined()
    })

    it('works without redis', () => {
        const app = createApp({ metrics, mcpService: mockMcpService, redis: undefined })

        expect(app).toBeDefined()
    })
})
