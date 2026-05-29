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
    EncryptedFields,
    installProcessHandlers,
    MemorySessionEventBus,
    PgIdentityStore,
    PgIntegrationStore,
    PgRevisionStore,
    PgSessionQueue,
    RedisSessionEventBus,
    SessionEventBus,
} from '@posthog/agent-shared'

import { loadAgentIngressConfig } from './config'
import { buildApp } from './routing/server'

const log = createLogger('agent-ingress')

async function main(): Promise<void> {
    installProcessHandlers(log)
    const config = loadAgentIngressConfig()

    const posthogDb = new Pool({ connectionString: config.posthogDbUrl })
    const agentDb = new Pool({ connectionString: config.agentDbUrl })

    // SSE /listen is the consumer side of the same bus the runner publishes
    // to. With REDIS_URL set, multi-host fan-out works; without it /listen
    // only sees events from a runner inside the same process (dev).
    let bus: SessionEventBus = new MemorySessionEventBus()
    if (config.redisUrl) {
        const redis = new RedisSessionEventBus({ url: config.redisUrl })
        await redis.connect()
        bus = redis
    }

    // Slack → PostHog user bridge needs the integration store to fetch the
    // workspace bot token for `users.info`. Encryption is required to decrypt
    // sensitive_config; when it's not configured (dev / CI) the bridge is
    // simply absent and AgentUser.posthog_user_id stays null.
    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const integrations = encryption.isConfigured ? new PgIntegrationStore(posthogDb, encryption) : null

    const app = buildApp({
        revisions: new PgRevisionStore(posthogDb),
        queue: new PgSessionQueue(agentDb),
        identities: new PgIdentityStore(agentDb),
        bus,
        teamId: config.teamId,
        routingMode: config.routingMode,
        domainSuffix: config.domainSuffix,
        pathPrefix: config.pathPrefix,
        slackSigningSecret: config.slackSigningSecret,
        previewSecret: config.previewSecret,
        integrations,
        posthogDb,
    })
    app.listen(config.port, () => {
        log.info({ port: config.port, bus: bus.constructor.name }, 'listening')
    })
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
