import { SessionQuery, SessionQueueJanitor, loadDevEnv, logger } from '@posthog/agent-core'

import { loadConfig } from './config'
import { buildServer } from './server'

loadDevEnv()

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

    const app = buildServer({ query, internalApiSharedKey: config.internalApiSharedKey })

    const server = app.listen(config.port, () => {
        logger.info('agent-janitor listening', { port: config.port })
    })

    const shutdown = async (signal: string): Promise<void> => {
        logger.info('agent-janitor shutting down', { signal })
        server.close()
        await janitor.stop()
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
