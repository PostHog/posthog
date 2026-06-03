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

import {
    createAgentPool,
    createLogger,
    EncryptedFields,
    installProcessHandlers,
    MemorySessionEventBus,
    PgCredentialBroker,
    PgIdentityStore,
    PgIntegrationStore,
    PgRevisionStore,
    PgSessionQueue,
    RedisSessionEventBus,
    SessionEventBus,
} from '@posthog/agent-shared'

import { loadAgentIngressConfig } from './config'
import { buildDefaultVerifiers, defaultPosthogIntrospector } from './enqueue/verifiers'
import { buildApp } from './routing/server'

const log = createLogger('agent-ingress')

async function main(): Promise<void> {
    installProcessHandlers(log)
    const config = loadAgentIngressConfig()

    const posthogDb = createAgentPool(config.posthogDbUrl)
    const agentDb = createAgentPool(config.agentDbUrl)

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
    // workspace bot token for `users.info`. Construction throws if
    // encryption isn't configured — fail-fast at boot rather than first
    // tool call.
    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const integrations = new PgIntegrationStore(posthogDb, encryption)

    // Per-mode auth verifiers. The introspector validates OAuth + PAT
    // bearers against PostHog's `/api/users/@me/` (covers both token
    // types). JWT verification needs an `issuer_secret_ref` resolver to
    // pull the embedding party's secret from the agent's encrypted env —
    // wired below.
    const introspector = defaultPosthogIntrospector({ baseUrl: config.posthogApiBaseUrl })
    const authProvider = {
        verifiers: buildDefaultVerifiers({ introspector }),
    }
    // Encrypted-at-rest credential broker (separate row per session,
    // Fernet-encrypted by the same EncryptedFields helper as
    // `AgentApplication.encrypted_env`). Required for any non-public
    // auth mode — construction throws if encryption isn't configured.
    const credentialBroker = new PgCredentialBroker(agentDb, {
        encryptionSaltKeys: config.encryptionSaltKeys,
    })

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
        authProvider,
        credentialBroker,
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
