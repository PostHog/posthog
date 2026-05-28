/**
 * Ingress entrypoint. Production wires the real RevisionStore + SessionQueue;
 * this skeleton uses in-memory impls so it can boot in dev.
 */

import {
    createLogger,
    MemoryRevisionStore,
    MemorySessionEventBus,
    MemorySessionQueue,
    RedisSessionEventBus,
    SessionEventBus,
} from '@posthog/agent-shared-v2'

import { buildApp } from './server'

const log = createLogger('agent-ingress-v2')

async function main(): Promise<void> {
    const port = parseInt(process.env.PORT ?? '8080', 10)

    // SSE /listen is the consumer side of the same bus the runner publishes
    // to. With REDIS_URL set, multi-host fan-out works; without it /listen
    // only sees events from a runner inside the same process (dev).
    let bus: SessionEventBus = new MemorySessionEventBus()
    if (process.env.REDIS_URL) {
        const redis = new RedisSessionEventBus({ url: process.env.REDIS_URL })
        await redis.connect()
        bus = redis
    }

    const app = buildApp({
        revisions: new MemoryRevisionStore(),
        queue: new MemorySessionQueue(),
        bus,
        teamId: parseInt(process.env.TEAM_ID ?? '1', 10),
        routingMode: (process.env.ROUTING_MODE as 'path' | 'domain') ?? 'path',
        domainSuffix: process.env.DOMAIN_SUFFIX,
        pathPrefix: process.env.PATH_PREFIX ?? '/agents',
        slackSigningSecret: process.env.SLACK_SIGNING_SECRET,
    })
    app.listen(port, () => {
        log.info({ port, bus: bus.constructor.name }, 'listening')
    })
}

if (require.main === module) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
