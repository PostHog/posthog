import { reapOrphanedSandboxes } from '@repo/ass-sandbox'

import {
    ApplicationsRepository,
    BundleStore,
    EncryptedFields,
    InMemorySessionBus,
    KafkaLogProducer,
    PosthogDbClient,
    RedisSessionBus,
    SandboxInstancesRepository,
    SessionBus,
    bundleStoreConfigFromEnv,
    loadDevEnv,
    logger,
} from '@posthog/agent-core'

import { AssServerExecutor } from './ass-server-executor'
import { loadConfig } from './config'
import { selectToolSandboxKind } from './tool-sandbox'
import { RunnerWorker } from './worker'

loadDevEnv()

async function main(): Promise<void> {
    logger.info('agent-runner booting', { node: process.version, pid: process.pid })
    const config = loadConfig()
    logger.info('agent-runner config loaded', {
        queueName: config.queueName,
        kafkaTopic: config.kafkaLogEntriesTopic,
        hasRedis: Boolean(config.redisUrl),
    })

    // Sweep tool-sandbox containers orphaned by a previous crashed run.
    try {
        if (selectToolSandboxKind() === 'docker') {
            const reaped = await reapOrphanedSandboxes({ log: (line) => logger.info(line) })
            if (reaped > 0) {
                logger.info('reaped orphaned tool-sandbox containers', { count: reaped })
            }
        }
    } catch (err) {
        logger.warn({ err }, 'orphaned-sandbox reap skipped')
    }

    const posthogDb = new PosthogDbClient({ dbUrl: config.posthogDbUrl })
    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const repository = new ApplicationsRepository({ db: posthogDb, encryption })
    // Durable lifecycle log for tool sandboxes — the janitor reaps sandboxes
    // whose worker died mid-session by walking these rows.
    const sandboxInstances = new SandboxInstancesRepository({ db: posthogDb })

    const bus: SessionBus = config.redisUrl ? new RedisSessionBus({ url: config.redisUrl }) : new InMemorySessionBus()

    if (!config.redisUrl) {
        logger.warn('REDIS_URL not set; using in-memory bus (single-process only — not safe for production)')
    }

    logger.info('connecting log producer', { brokers: config.kafkaBrokers, topic: config.kafkaLogEntriesTopic })
    const logProducer = new KafkaLogProducer({
        brokers: config.kafkaBrokers,
        topic: config.kafkaLogEntriesTopic,
        name: 'agent-runner-logs',
    })
    await logProducer.connect()
    logger.info('log producer connected')

    const bundleStore = new BundleStore(bundleStoreConfigFromEnv())

    const executor = new AssServerExecutor({ bundleStore, repository, sandboxInstances, bus, logProducer })

    const worker = new RunnerWorker({
        pool: { dbUrl: config.queueDbUrl },
        queueName: config.queueName,
        concurrency: config.concurrency,
        executor,
        bus,
        logProducer,
        loadSecrets: async (applicationId) => {
            if (!applicationId) {
                return {}
            }
            // Pulls the application's encrypted `.env` blob from the main posthog DB and
            // decrypts it locally via fernet. Tools see secrets through ToolContext.secrets.
            return await repository.decryptEnv(applicationId)
        },
    })

    await worker.start()
    logger.info('agent-runner started', { queueName: config.queueName, kafkaTopic: config.kafkaLogEntriesTopic })

    const shutdown = async (signal: string): Promise<void> => {
        logger.info('agent-runner shutting down', { signal })
        await worker.stop()
        await bus.disconnect()
        await logProducer.disconnect()
        await posthogDb.disconnect()
        bundleStore.destroy()
        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

main().catch((err: unknown) => {
    // Pass the Error instance under `err` (or `error`) so pino's serializer
    // expands message + stack + nested causes — `String(err)` loses all of it.
    logger.error({ err }, 'agent-runner fatal')
    process.exit(1)
})
