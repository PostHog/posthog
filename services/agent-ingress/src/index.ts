import {
    ApplicationsRepository,
    EncryptedFields,
    IdentitiesRepository,
    InMemorySessionBus,
    PosthogDbClient,
    RedisSessionBus,
    SessionBus,
    SessionQueueManager,
    loadDevEnv,
    logger,
} from '@posthog/agent-core'

import { loadConfig } from './config'
import { RevisionResolver } from './resolver'
import { buildServer } from './server'

loadDevEnv()

async function main(): Promise<void> {
    const config = loadConfig()

    const queue = new SessionQueueManager({ pool: { dbUrl: config.queueDbUrl } })
    await queue.connect()

    const posthogDb = new PosthogDbClient({ dbUrl: config.posthogDbUrl })
    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const repository = new ApplicationsRepository({ db: posthogDb, encryption })
    const identities = new IdentitiesRepository({ db: posthogDb })

    const resolver = new RevisionResolver({
        repository,
        ttlMs: config.resolverTtlMs,
        domainSuffix: config.domainSuffix,
    })

    const bus: SessionBus = config.redisUrl ? new RedisSessionBus({ url: config.redisUrl }) : new InMemorySessionBus()

    if (!config.redisUrl) {
        logger.warn('REDIS_URL not set; using in-memory bus (single-process only — not safe for production)')
    }

    const app = buildServer({
        queue,
        bus,
        resolver,
        repository,
        identities,
        domainSuffix: config.domainSuffix,
        routingMode: config.routingMode,
    })

    const server = app.listen(config.port, () => {
        logger.info('agent-ingress listening', {
            port: config.port,
            routingMode: config.routingMode,
            domainSuffix: config.routingMode === 'domain' ? config.domainSuffix : undefined,
        })
    })

    const shutdown = async (signal: string): Promise<void> => {
        logger.info('agent-ingress shutting down', { signal })
        server.close()
        await bus.disconnect()
        await queue.disconnect()
        await posthogDb.disconnect()
        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

main().catch((err: unknown) => {
    logger.error({ err }, 'agent-ingress fatal')
    process.exit(1)
})
