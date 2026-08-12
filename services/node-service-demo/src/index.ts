import { createLogger, serializeError, startNodeService } from '@posthog/node-service'

import { createApp } from './app.js'
import { loadConfig } from './config.js'
import { CounterStore } from './features/counters/counter-store.js'
import { createPostgresPool, isPostgresReady } from './infrastructure/postgres/pool.js'

const bootstrapLogger = createLogger({ serviceName: 'node-service-demo' })

async function main(): Promise<void> {
    const config = loadConfig()
    const pool = createPostgresPool(config.DATABASE_URL)

    try {
        const service = createApp({
            store: new CounterStore(pool),
            postgresReadiness: async () => ((await isPostgresReady(pool)) ? { status: 'ok' } : { status: 'error' }),
            logLevel: config.LOG_LEVEL,
        })
        const startedService = await startNodeService({
            service,
            hostname: config.HOST,
            port: config.PORT,
            shutdownGraceMs: config.SHUTDOWN_GRACE_MS,
        })
        startedService.addShutdownHook('postgres', () => pool.end())
    } catch (error) {
        await pool.end()
        throw error
    }
}

main().catch((error: unknown) => {
    bootstrapLogger.fatal({ event: 'service.start_failed', error: serializeError(error) }, 'Service failed to start')
    process.exitCode = 1
})
