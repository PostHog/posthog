import {
    ApplicationsRepository,
    BundleStore,
    EncryptedFields,
    InMemorySessionBus,
    NullSessionLogStore,
    PosthogDbClient,
    RedisSessionBus,
    RedisSessionLogStore,
    SessionBus,
    SessionLogStore,
    bundleStoreConfigFromEnv,
    logger,
} from '@posthog/agent-core'

import { AssServerExecutor } from './ass-server-executor'
import { loadConfig } from './config'
import { RunnerWorker } from './worker'

async function main(): Promise<void> {
    const config = loadConfig()

    const posthogDb = new PosthogDbClient({ dbUrl: config.posthogDbUrl })
    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const repository = new ApplicationsRepository({ db: posthogDb, encryption })

    const bus: SessionBus = config.redisUrl ? new RedisSessionBus({ url: config.redisUrl }) : new InMemorySessionBus()

    if (!config.redisUrl) {
        logger.warn('REDIS_URL not set; using in-memory bus (single-process only — not safe for production)')
    }

    // HACK: per-session log buffer for the management UI. See
    // `agent-core/src/session-logs/`. Real implementation will be loki/clickhouse.
    const logStore: SessionLogStore = config.redisUrl
        ? new RedisSessionLogStore({ url: config.redisUrl })
        : new NullSessionLogStore()
    if (config.redisUrl) {
        logger.info('agent-runner session log buffer wired (Redis)', { redisUrl: config.redisUrl })
    } else {
        logger.warn('agent-runner session log buffer DISABLED (no REDIS_URL — UI tail will be empty)')
    }

    // Reads OBJECT_STORAGE_* env vars (defaults match Django's local MinIO config),
    // so a dev stack with `bin/start` already has a usable bundle store.
    const bundleStore = new BundleStore(bundleStoreConfigFromEnv())

    const executor = new AssServerExecutor({ bundleStore, repository, bus, logStore })

    const worker = new RunnerWorker({
        pool: { dbUrl: config.queueDbUrl },
        queueName: config.queueName,
        executor,
        bus,
        logStore,
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
    logger.info('agent-runner started', { queueName: config.queueName })

    const shutdown = async (signal: string): Promise<void> => {
        logger.info('agent-runner shutting down', { signal })
        await worker.stop()
        await bus.disconnect()
        await logStore.disconnect()
        await posthogDb.disconnect()
        bundleStore.destroy()
        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

main().catch((err) => {
    logger.error('agent-runner fatal', { error: String(err) })
    process.exit(1)
})
