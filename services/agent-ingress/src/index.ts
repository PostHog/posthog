import { readFileSync } from 'node:fs'

import {
    InMemorySessionBus,
    InternalApiClient,
    RedisSessionBus,
    ResolvedRevision,
    ResolvedRevisionSchema,
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

    const apiClient = new InternalApiClient({
        baseUrl: config.internalApiBaseUrl,
        sharedKey: config.internalApiSharedKey,
    })

    const localRevisions = loadLocalRevisions(process.env.AGENT_DEV_REVISIONS_PATH, config.domainSuffix)
    const resolver = new RevisionResolver({
        client: apiClient,
        ttlMs: config.resolverTtlMs,
        localRevisions,
    })

    const bus: SessionBus = config.redisUrl ? new RedisSessionBus({ url: config.redisUrl }) : new InMemorySessionBus()

    if (!config.redisUrl) {
        logger.warn('REDIS_URL not set; using in-memory bus (single-process only — not safe for production)')
    }

    const app = buildServer({ queue, bus, resolver, domainSuffix: config.domainSuffix })

    const server = app.listen(config.port, () => {
        logger.info('agent-ingress listening', { port: config.port })
    })

    const shutdown = async (signal: string): Promise<void> => {
        logger.info('agent-ingress shutting down', { signal })
        server.close()
        await bus.disconnect()
        await queue.disconnect()
        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

/**
 * Dev-only fixture loader. Reads a JSON file shaped as `ResolvedRevision[]` and
 * returns a Map keyed by `app:<applicationId>` and `domain:<applicationSlug><suffix>`.
 * Lets the local stack run without a wired Django `resolve` endpoint.
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
        const revision = ResolvedRevisionSchema.parse(entry)
        map.set(`app:${revision.applicationId}`, revision)
        map.set(`domain:${revision.applicationSlug}${domainSuffix}`, revision)
    }
    logger.warn('agent-ingress using AGENT_DEV_REVISIONS_PATH fixture — dev only', { path, count: map.size / 2 })
    return map
}

main().catch((err) => {
    logger.error('agent-ingress fatal', { error: String(err) })
    process.exit(1)
})
