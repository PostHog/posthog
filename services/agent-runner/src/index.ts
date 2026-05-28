/**
 * Worker entrypoint. Two Postgres pools:
 *
 *   - posthogDb (POSTHOG_DB_URL): the main Django/PostHog database, owns
 *     the *authoring* tables (agent_application, agent_revision). The
 *     runner reads from these via `PgRevisionStore`; never writes.
 *
 *   - agentDb (AGENT_DB_URL): the queue / runtime database, owns
 *     agent_session, agent_user, agent_sandbox_instance. The worker owns
 *     this schema and bootstraps it via SCHEMA_SQL on boot.
 *
 * In dev / CI both env vars can point at the same Postgres; production
 * deploys them separately so high-churn runtime writes don't pressure the
 * main product DB.
 *
 * Run with `tsx src/index.ts` (no build step). `pnpm start` wraps that.
 */

import { mkdir } from 'node:fs/promises'
import pg from 'pg'
const { Pool } = pg

import {
    AnalyticsSink,
    CaptureAnalyticsSink,
    createLogger,
    EncryptedFields,
    FsBundleStore,
    installProcessHandlers,
    NoopAnalyticsSink,
    NoopSessionEventBus,
    PgRevisionStore,
    PgSandboxInstanceStore,
    PgSessionQueue,
    RedisSessionEventBus,
    SCHEMA_SQL,
    SecretBroker,
    selectSandboxPool,
    SessionEventBus,
} from '@posthog/agent-shared'

import { defaultApiKeyFromConfig, loadAgentRunnerConfig } from './config'
import { posthogLlmGatewayModel } from './models/llm-gateway-model'
import { PiAiClient, resolveModelCached } from './models/pi-client'
import { makeEncryptedEnvResolver } from './resolvers/encrypted-env-resolver'
import { Worker } from './workers/worker'

const log = createLogger('agent-runner')

async function main(): Promise<void> {
    installProcessHandlers(log)
    const config = loadAgentRunnerConfig()
    // Default to a user-writable dir so dev / local CI work without root.
    // Production sets AGENT_BUNDLE_ROOT to a mounted volume shared with the
    // janitor (same path on both deployments).
    await mkdir(config.bundleRoot, { recursive: true })

    const posthogDb = new Pool({ connectionString: config.posthogDbUrl })
    const agentDb = new Pool({ connectionString: config.agentDbUrl })
    // Only the queue DB schema is the runner's responsibility — Django owns
    // the authoring tables (agent_application, agent_revision) in posthogDb.
    await agentDb.query(SCHEMA_SQL)

    const defaultApiKey = defaultApiKeyFromConfig(config)
    const revisions = new PgRevisionStore(posthogDb)

    // Build the resolveSecrets path. If ENCRYPTION_SALT_KEYS is set, decrypt
    // AgentApplication.encrypted_env via Fernet (matches Django). Otherwise
    // start with no secrets — dev / CI is happy without encryption configured.
    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const resolveSecrets = encryption.isConfigured
        ? makeEncryptedEnvResolver({ revisions, encryption })
        : async () => ({})

    // Cross-process event bus. With REDIS_URL set, ingress /listen on host A
    // sees events published by a runner on host B. Without it the runner
    // still works — events just go nowhere (no SSE consumers can connect).
    let bus: SessionEventBus = new NoopSessionEventBus()
    if (config.redisUrl) {
        const redis = new RedisSessionEventBus({ url: config.redisUrl })
        await redis.connect()
        bus = redis
    }

    // LLM analytics sink. Captures `$ai_generation` per pi-ai call and
    // `$ai_span` per tool dispatch via PostHog's standard ingestion path
    // (posthog-node /capture) — events land directly in `ai_events` with
    // no new infra. Every event carries `$ai_origin: 'agent_platform_runner'`
    // as the marker the future signed-origin billing filter will key on.
    // See docs/agent-platform/plans/platform-llm-analytics.md.
    let analytics: AnalyticsSink = new NoopAnalyticsSink()
    if (config.posthogAnalyticsApiKey) {
        const capture = new CaptureAnalyticsSink({
            apiKey: config.posthogAnalyticsApiKey,
            host: config.posthogAnalyticsHost,
        })
        await capture.connect()
        analytics = capture
    }

    const worker = new Worker({
        queue: new PgSessionQueue(agentDb),
        revisions,
        bundle: new FsBundleStore(config.bundleRoot),
        sandboxes: selectSandboxPool(),
        sandboxInstances: new PgSandboxInstanceStore(agentDb),
        pi: new PiAiClient(defaultApiKey),
        broker: new SecretBroker(),
        bus,
        resolveIntegrations: async () => ({}),
        resolveSecrets,
        resolveModel: config.useLlmGateway
            ? // Route every model through PostHog's llm-gateway, keeping spec.model
              // as the model id but ignoring the provider prefix.
              (specModel) =>
                  posthogLlmGatewayModel({
                      modelId: specModel.includes('/') ? specModel.split('/').pop()! : specModel,
                      baseUrl: config.llmGatewayUrl,
                  })
            : undefined,
        // On the gateway path pi-ai's cost numbers are client-side estimates;
        // the gateway itself owns billing. We keep token counts.
        useGatewayCost: config.useLlmGateway,
        analytics,
        maxConcurrency: config.maxConcurrency,
    })

    const shutdown = (sig: string): void => {
        log.info({ sig }, 'shutdown signal received — suspending in-flight sessions')
        void worker.stop()
    }
    process.on('SIGTERM', () => shutdown('SIGTERM'))
    process.on('SIGINT', () => shutdown('SIGINT'))

    log.info(
        {
            posthogDb: config.posthogDbUrl,
            agentDb: config.agentDbUrl,
            concurrency: config.maxConcurrency,
            gateway: config.useLlmGateway,
        },
        'starting worker loop'
    )
    await worker.loop()
    // Drain the analytics buffer BEFORE closing pools so the final batch of
    // `$ai_*` events lands in PostHog even on a rolling deploy.
    if (analytics instanceof CaptureAnalyticsSink) {
        await analytics.shutdown()
    }
    await Promise.all([posthogDb.end(), agentDb.end()])
    log.info({}, 'stopped cleanly')
}

// Silence unused-import warning while keeping resolveModelCached importable.
void resolveModelCached

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
