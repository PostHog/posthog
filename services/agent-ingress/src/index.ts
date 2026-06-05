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
    AgentApplication,
    createAgentPool,
    createLogger,
    EncryptedFields,
    HttpClient,
    installProcessHandlers,
    isDev,
    PgCredentialBroker,
    PgIdentityStore,
    PgIntegrationStore,
    PgRevisionStore,
    PgSessionQueue,
    RedisSessionEventBus,
} from '@posthog/agent-shared'

import { loadAgentIngressConfig } from './config'
import { buildDefaultVerifiers, defaultPosthogIntrospector } from './enqueue/verifiers'
import { buildApp } from './routing/server'
import type { SlackSigningSecretResolver } from './triggers/slack'

const log = createLogger('agent-ingress')

async function main(): Promise<void> {
    installProcessHandlers(log)
    const config = loadAgentIngressConfig()

    const posthogDb = createAgentPool(config.posthogDbUrl)
    const agentDb = createAgentPool(config.agentDbUrl)

    // SSE /listen is the consumer side of the same bus the runner publishes
    // to. REDIS_URL is required — without cross-host fan-out, /listen on
    // ingress pod A would silently miss events from runner pod B. Fail
    // closed at boot rather than serving a /listen that returns nothing.
    if (!config.redisUrl) {
        throw new Error(
            'REDIS_URL must be set — ingress /listen SSE needs the SessionEventBus subscribe side. Wire valkey-agent-platform via the chart.'
        )
    }
    const bus = new RedisSessionEventBus({ url: config.redisUrl })
    await bus.connect()

    // Outbound HTTP — Slack identity bridge + PostHog API introspect both
    // dispatch through here. In prod `config.httpsProxy` points at
    // smokescreen so outbound calls match the runner's posture. Fail-fast
    // in non-dev when unset rather than silently bypassing the proxy.
    if (!config.httpsProxy && !isDev()) {
        throw new Error(
            'HTTPS_PROXY must be set — outbound fetches must route through smokescreen in prod. Wire `httpProxy.enabled: true` in the chart.'
        )
    }
    const http = new HttpClient({ proxyUrl: config.httpsProxy })

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
    const introspector = defaultPosthogIntrospector({ baseUrl: config.posthogApiBaseUrl, http })
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

    // Per-agent Slack signing secret. Each agent's spec names which entry in
    // `encrypted_env` holds the Slack app's signing key
    // (`slack.config.signing_secret_ref`); we decrypt the env per request and
    // pluck the named entry. Mirrors `makeEncryptedEnvResolver` on the runner.
    const slackSigningSecretResolver: SlackSigningSecretResolver = {
        async resolve(secretRef: string, application: AgentApplication): Promise<string | null> {
            if (!application.encrypted_env) {
                return null
            }
            try {
                const env = encryption.decryptJsonEnv(application.encrypted_env)
                const value = env[secretRef]
                return typeof value === 'string' && value.length > 0 ? value : null
            } catch {
                return null
            }
        },
    }

    const app = buildApp({
        revisions: new PgRevisionStore(posthogDb),
        queue: new PgSessionQueue(agentDb),
        identities: new PgIdentityStore(agentDb),
        bus,
        teamId: config.teamId,
        routingMode: config.routingMode,
        domainSuffix: config.domainSuffix,
        pathPrefix: config.pathPrefix,
        slackSigningSecretResolver,
        previewSecret: config.previewSecret,
        integrations,
        posthogDb,
        authProvider,
        credentialBroker,
        http,
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
