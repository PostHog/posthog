/**
 * Ingress entrypoint. Two Postgres pools (matching the runner):
 *
 *   - posthogDb (POSTHOG_DB_URL): Django-owned authoring tables. The ingress
 *     reads `agent_application` + `agent_revision` to resolve a request's
 *     slug/domain to a live revision.
 *
 *   - agentDb (AGENT_DB_URL): runtime queue. The ingress writes new
 *     `agent_session` rows when a trigger fires and reads / writes
 *     `agent_user` for identity resolution.
 *
 * Single-pool default (both env vars unset → same Postgres) is fine for dev.
 */

import pg from 'pg'
const { Pool } = pg

import {
    createLogger,
    installProcessHandlers,
    MemorySessionEventBus,
    PgIdentityStore,
    PgRevisionStore,
    PgSessionQueue,
    RedisSessionEventBus,
    SessionEventBus,
} from '@posthog/agent-shared'

import { buildApp } from './routing/server'

const log = createLogger('agent-ingress')

async function main(): Promise<void> {
    installProcessHandlers(log)
    const port = parseInt(process.env.PORT ?? '8080', 10)
    const posthogDbUrl = process.env.POSTHOG_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/posthog'
    const agentDbUrl = process.env.AGENT_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue'

    const posthogDb = new Pool({ connectionString: posthogDbUrl })
    const agentDb = new Pool({ connectionString: agentDbUrl })

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
        revisions: new PgRevisionStore(posthogDb),
        queue: new PgSessionQueue(agentDb),
        identities: new PgIdentityStore(agentDb),
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

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
