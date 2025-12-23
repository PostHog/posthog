import { Redis } from 'ioredis'

import { MemoryCache } from '@/lib/utils/cache'
import { SessionManager } from '@/lib/utils/SessionManager'
import { createApp } from './app'
import { loadConfig } from './config'
import { Metrics } from './metrics'
import { AnalyticsService } from './services/analytics'
import { McpService } from './services/mcp'
import { RegionService } from './services/region'

const config = loadConfig()
const metrics = new Metrics()

let redis: Redis | undefined
if (config.redisUrl) {
    redis = new Redis(config.redisUrl, {
        maxRetriesPerRequest: 3,
        lazyConnect: true,
    })
    redis.on('error', (err) => {
        console.error('Redis connection error:', err.message)
    })
    redis.on('connect', () => {
        console.info('Connected to Redis')
    })
}

const regionService = new RegionService(config)
const dummyCache = new MemoryCache('__analytics__')
const sessionManager = new SessionManager(dummyCache)
const analyticsService = new AnalyticsService(sessionManager)

const mcpService = new McpService({
    config,
    metrics,
    regionService,
    analyticsService,
    redis,
})

const app = createApp({ metrics, mcpService, redis })

app.listen(config.port, '0.0.0.0', () => {
    console.info(`MCP server listening on port ${config.port}`)
    console.info(`Redis: ${config.redisUrl ? 'enabled' : 'disabled (using in-memory cache)'}`)
})

async function shutdown(): Promise<void> {
    console.info('Shutting down...')
    if (redis) {
        await redis.quit()
    }
    process.exit(0)
}

process.on('SIGTERM', shutdown)
process.on('SIGINT', shutdown)
