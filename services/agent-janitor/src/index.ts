import {
    NullSessionLogStore,
    RedisSessionLogStore,
    SessionLogStore,
    SessionQuery,
    SessionQueueJanitor,
    logger,
} from '@posthog/agent-core'

import { loadConfig } from './config'
import { buildServer } from './server'

async function main(): Promise<void> {
    const config = loadConfig()

    if (!config.internalApiSharedKey) {
        logger.warn(
            'agent-janitor starting without AGENT_INTERNAL_API_SHARED_KEY — /internal routes will refuse traffic'
        )
    }

    const query = new SessionQuery({ pool: { dbUrl: config.queueDbUrl } })
    await query.connect()

    const janitor = new SessionQueueJanitor({
        pool: { dbUrl: config.queueDbUrl },
        cleanupIntervalMs: config.janitorIntervalMs,
        stallTimeoutMs: config.janitorStallTimeoutMs,
        maxTouchCount: config.janitorMaxTouchCount,
        cleanupGraceMs: config.janitorCleanupGraceMs,
    })
    await janitor.start()

    // HACK: per-session log buffer for the UI. See agent-core/src/session-logs/.
    const logStore: SessionLogStore = config.redisUrl
        ? new RedisSessionLogStore({ url: config.redisUrl })
        : new NullSessionLogStore()
    if (config.redisUrl) {
        logger.info('agent-janitor session log buffer wired (Redis)', { redisUrl: config.redisUrl })
    } else {
        logger.warn('agent-janitor session log buffer DISABLED (no REDIS_URL — /logs route will always be empty)')
    }

    const app = buildServer({ query, logStore, internalApiSharedKey: config.internalApiSharedKey })

    const server = app.listen(config.port, () => {
        logger.info('agent-janitor listening', { port: config.port })
    })

    const shutdown = async (signal: string): Promise<void> => {
        logger.info('agent-janitor shutting down', { signal })
        server.close()
        await janitor.stop()
        await logStore.disconnect()
        await query.disconnect()
        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

main().catch((err) => {
    logger.error('agent-janitor fatal', { error: String(err) })
    process.exit(1)
})
