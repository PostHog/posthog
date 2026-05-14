import { InMemorySessionBus, InternalApiClient, RedisSessionBus, SessionBus, logger } from '@posthog/agent-core'

import { loadConfig } from './config'
import { NotImplementedExecutor } from './executor-stub'
import { RunnerWorker } from './worker'

async function main(): Promise<void> {
    const config = loadConfig()

    const apiClient = new InternalApiClient({
        baseUrl: config.internalApiBaseUrl,
        sharedKey: config.internalApiSharedKey,
    })

    const bus: SessionBus = config.redisUrl ? new RedisSessionBus({ url: config.redisUrl }) : new InMemorySessionBus()

    if (!config.redisUrl) {
        logger.warn('REDIS_URL not set; using in-memory bus (single-process only — not safe for production)')
    }

    const worker = new RunnerWorker({
        pool: { dbUrl: config.queueDbUrl },
        queueName: config.queueName,
        executor: new NotImplementedExecutor(),
        bus,
        loadSecrets: async (applicationId) => {
            if (!applicationId) {
                return {}
            }
            // Real wiring: ask Django for the secrets declared on the manifest. For now,
            // the placeholder executor never reaches the tool dispatch path, so an empty
            // map is fine.
            const { secrets } = await apiClient.decryptSecrets(applicationId, [])
            return secrets
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
