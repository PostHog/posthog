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
    DirectHttpClient,
    EncryptedEnvSecretResolver,
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
    // The internal signing key backs both the preview-token gate and the
    // `posthog_internal` auth verifier — required in prod, fail-fast rather than
    // booting with that mode silently disabled.
    if (!config.internalSigningKey && !isDev()) {
        throw new Error(
            'AGENT_INTERNAL_SIGNING_KEY must be set — it backs the preview-token gate and the posthog_internal auth mode.'
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
    // PostHog's `/api/users/@me/` is cluster-internal — use the direct client
    // so the introspect doesn't hit smokescreen (which would refuse RFC1918).
    // The proxy-bound `http` stays reserved for everything an agent author can
    // influence the URL of (Slack identity bridge → slack.com).
    const introspector = defaultPosthogIntrospector({
        baseUrl: config.posthogApiBaseUrl,
        http: new DirectHttpClient(),
    })
    // Per-agent secret resolver. Decrypts the agent's `encrypted_env` and plucks
    // a named entry — backs the Slack signing-secret/bot-token lookups and the
    // shared_secret auth verifier (which reads `mode.secret_ref`).
    const secretResolver = new EncryptedEnvSecretResolver(encryption)
    const authProvider = {
        verifiers: buildDefaultVerifiers({
            introspector,
            jwtSecretResolver: secretResolver,
            sharedSecretResolver: secretResolver,
            internalSecret: config.internalSigningKey ?? '',
        }),
    }
    // Encrypted-at-rest credential broker (separate row per session,
    // Fernet-encrypted by the same EncryptedFields helper as
    // `AgentApplication.encrypted_env`). Required for any non-public
    // auth mode — construction throws if encryption isn't configured.
    const credentialBroker = new PgCredentialBroker(agentDb, {
        encryptionSaltKeys: config.encryptionSaltKeys,
    })

    const app = buildApp({
        revisions: new PgRevisionStore(agentDb),
        queue: new PgSessionQueue(agentDb),
        identities: new PgIdentityStore(agentDb),
        bus,
        routingMode: config.routingMode,
        domainSuffix: config.domainSuffix,
        pathPrefix: config.pathPrefix,
        publicBaseUrl: config.publicUrl,
        slackSigningSecretResolver: secretResolver,
        internalSigningKey: config.internalSigningKey,
        integrations,
        posthogDb,
        authProvider,
        credentialBroker,
        http,
    })
    app.listen(config.port, () => {
        log.info(
            {
                port: config.port,
                bus: bus.constructor.name,
                // Only surfaced when set — an unset public URL is normal (domain-mode
                // routes by host; Django builds callback URLs from its own settings).
                ...(config.publicUrl ? { public_url: config.publicUrl } : {}),
            },
            config.publicUrl ? `listening — reachable at ${config.publicUrl}` : 'listening'
        )
    })
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
