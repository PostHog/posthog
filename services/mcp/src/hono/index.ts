import { serve } from '@hono/node-server'
import { Redis } from 'ioredis'

import { createApp } from './app'

const PORT = parseInt(process.env.PORT || '3001', 10)
const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379'

const redis = new Redis(REDIS_URL, {
    maxRetriesPerRequest: 3,
    retryStrategy(times) {
        const delay = Math.min(times * 200, 2000)
        return delay
    },
    lazyConnect: true,
})

redis.on('error', (err) => {
    console.error('[MCP] Redis connection error:', err.message)
})

redis.on('connect', () => {
    console.info('[MCP] Redis connected')
})

async function main(): Promise<void> {
    try {
        await redis.connect()
    } catch (err) {
        console.error('[MCP] Failed to connect to Redis:', err)
        process.exit(1)
    }

    const app = createApp(redis)

    const server = serve({ fetch: app.fetch, port: PORT }, (info) => {
        console.info(`[MCP] Server started on port ${info.port}`)
    })

    const shutdown = async (): Promise<void> => {
        console.info('[MCP] Shutting down...')
        server.close()
        await redis.quit()
        process.exit(0)
    }

    process.on('SIGTERM', shutdown)
    process.on('SIGINT', shutdown)
}

main().catch((err) => {
    console.error('[MCP] Fatal error:', err)
    process.exit(1)
})
