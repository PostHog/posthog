import { serve } from '@hono/node-server'
import Redis from 'ioredis'

import { getCustomApiBaseUrl, isLocalApi } from '@/lib/constants'

import { createApp } from './app'
import { redisOperationsTotal } from './metrics'
import { registerShutdownHandlers } from './shutdown'

const PORT = parseInt(process.env.PORT || '3001', 10)
const HOST = process.env.HOST || '0.0.0.0'

function resolveRedisUrl(): string {
    const url = process.env.REDIS_URL
    if (url) {
        return url
    }
    if (process.env.NODE_ENV === 'production') {
        console.error('[MCP] REDIS_URL is required in production')
        process.exit(1)
    }
    // Local dev fallback only — production refuses to start without REDIS_URL above.
    // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
    return 'redis://localhost:6379'
}

const redis = new Redis(resolveRedisUrl(), {
    lazyConnect: true,
    maxRetriesPerRequest: 3,
    enableOfflineQueue: false,
    connectTimeout: 5000,
    commandTimeout: 2000,
    keepAlive: 30000,
    retryStrategy: (times: number) => Math.min(times * 200, 2000),
})

redis.on('error', (err: Error) => {
    console.error('[MCP] Redis connection error:', err.message)
    redisOperationsTotal.inc({ operation: 'connect', status: 'error' })
})

redis.on('connect', () => {
    console.info('[MCP] Redis connected')
    redisOperationsTotal.inc({ operation: 'connect', status: 'success' })
})

async function main(): Promise<void> {
    try {
        await redis.connect()
    } catch (err) {
        console.error('[MCP] Failed to connect to Redis:', err)
        process.exit(1)
    }

    const { app, lifecycle, warmup } = createApp(redis as unknown as Parameters<typeof createApp>[0])

    await warmup()

    const server = serve({ fetch: app.fetch, port: PORT, hostname: HOST }, (info) => {
        console.info(`[MCP] Server started on ${HOST}:${info.port}`)
        if (isLocalApi()) {
            console.info(
                `[MCP] local API (${getCustomApiBaseUrl()}) — all feature-flag-gated tools force-enabled for local dev`
            )
        }
    })

    registerShutdownHandlers({ server, lifecycle, redis })
}

main().catch((err) => {
    console.error('[MCP] Fatal error:', err)
    process.exit(1)
})
