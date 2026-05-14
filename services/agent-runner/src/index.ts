import { InMemorySessionBus, RedisSessionBus, SessionBus, logger } from '@posthog/agent-core'

import { loadConfig } from './config'
import { NotImplementedExecutor } from './executor-stub'
import { RunnerWorker } from './worker'

async function main(): Promise<void> {
    const config = loadConfig()

    const bus: SessionBus = config.redisUrl ? new RedisSessionBus({ url: config.redisUrl }) : new InMemorySessionBus()

    if (!config.redisUrl) {
        logger.warn('REDIS_URL not set; using in-memory bus (single-process only — not safe for production)')
    }

    const worker = new RunnerWorker({
        pool: { dbUrl: config.queueDbUrl },
        queueName: config.queueName,
        executor: new NotImplementedExecutor(),
        bus,
        loadSecrets: () => {
            // EchoExecutor (v1) never reaches tool dispatch, so we skip the Django
            // decrypt call. When the real Claude Agent SDK executor lands we'll wire
            // `InternalApiClient.decryptSecrets(applicationId, names)` here, scoped
            // to the names declared on the manifest the turn is about to invoke.
            return Promise.resolve({})
        },
    })

    await worker.start()
    logger.info('agent-runner started', { queueName: config.queueName })

    const shutdown = async (signal: string): Promise<void> => {
        logger.info('agent-runner shutting down', { signal })
        await worker.stop()
        await bus.disconnect()
        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

main().catch((err) => {
    logger.error('agent-runner fatal', { error: String(err) })
    process.exit(1)
})
