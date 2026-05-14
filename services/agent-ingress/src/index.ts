import { readFileSync } from 'node:fs'

import {
    ApplicationsRepository,
    EncryptedFields,
    InMemorySessionBus,
    PosthogDbClient,
    RedisSessionBus,
    ResolvedRevision,
    SessionBus,
    SessionQueueManager,
    logger,
} from '@posthog/agent-core'

import { loadConfig } from './config'
import { RevisionResolver } from './resolver'
import { buildServer } from './server'

async function main(): Promise<void> {
    const config = loadConfig()

    const queue = new SessionQueueManager({ pool: { dbUrl: config.queueDbUrl } })
    await queue.connect()

    const posthogDb = new PosthogDbClient({ dbUrl: config.posthogDbUrl })
    // Ingress needs the decryptor too — slack_event triggers fetch their
    // signing secret (and the ack_reaction's bot token) from the app's
    // encrypted_env at request time via `repository.decryptEnv`.
    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const repository = new ApplicationsRepository({ db: posthogDb, encryption })

    const localRevisions = loadLocalRevisions(process.env.AGENT_DEV_REVISIONS_PATH, config.domainSuffix)
    const resolver = new RevisionResolver({
        repository,
        ttlMs: config.resolverTtlMs,
        domainSuffix: config.domainSuffix,
        localRevisions,
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
        domainSuffix: config.domainSuffix,
        routingMode: config.routingMode,
    })

    const server = app.listen(config.port, () => {
        logger.info('agent-ingress listening with', {
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

/**
 * Dev-only fixture loader. Reads a JSON file shaped as `ResolvedRevision[]` and
 * returns a Map keyed by `app:<applicationId>` and `domain:<applicationSlug><suffix>`.
 * Lets the local stack run against canned revisions without inserting Django rows.
 */
function loadLocalRevisions(path: string | undefined, domainSuffix: string): Map<string, ResolvedRevision> | undefined {
    if (!path) {
        return undefined
    }
    const raw = JSON.parse(readFileSync(path, 'utf8')) as unknown
    if (!Array.isArray(raw)) {
        throw new Error(`AGENT_DEV_REVISIONS_PATH=${path} must contain a JSON array of ResolvedRevision`)
    }
    const map = new Map<string, ResolvedRevision>()
    for (const entry of raw) {
        const revision = entry as ResolvedRevision
        map.set(`app:${revision.applicationId}`, revision)
        map.set(`domain:${revision.applicationSlug}${domainSuffix}`, revision)
        // Also key by bare slug so path-mode resolves against the same fixture.
        map.set(`slug:${revision.applicationSlug}`, revision)
    }
    logger.warn('agent-ingress using AGENT_DEV_REVISIONS_PATH fixture — dev only', { path, count: map.size / 2 })
    return map
}

main().catch((err) => {
    logger.error('agent-ingress fatal', { error: String(err) })
    process.exit(1)
})
