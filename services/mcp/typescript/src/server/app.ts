import express, { type Express } from 'express'
import type { Redis } from 'ioredis'

import { createHealthHandler, createReadyHandler } from './handlers/health'
import { createMcpHandler } from './handlers/mcp'
import { createWelcomeHandler } from './handlers/welcome'
import { createErrorMiddleware } from './middleware/error'
import type { Metrics } from './metrics'
import type { McpService } from './services/mcp'

export interface AppDependencies {
    metrics: Metrics
    mcpService: McpService
    redis: Redis | undefined
}

export function createApp(deps: AppDependencies): Express {
    const { metrics, mcpService, redis } = deps

    const app = express()
    app.use(express.json())

    app.get('/health', createHealthHandler())
    app.get('/ready', createReadyHandler(redis))
    app.get('/_metrics', async (_req, res) => {
        res.set('Content-Type', metrics.registry.contentType)
        res.end(await metrics.registry.metrics())
    })
    app.get('/', createWelcomeHandler())
    app.all('/mcp', createMcpHandler(mcpService, metrics))

    app.use(createErrorMiddleware(metrics))

    return app
}
