/**
 * Worker entrypoint. Two Postgres pools:
 *
 *   - posthogDb (POSTHOG_DB_URL): the main Django/PostHog database, owns
 *     the *authoring* tables (agent_application, agent_revision). The
 *     runner reads from these via `PgRevisionStore`; never writes.
 *
 *   - agentDb (AGENT_DB_URL): the queue / runtime database, owns
 *     agent_session, agent_user, agent_sandbox_instance. Schema is
 *     managed by @posthog/agent-migrations; this entry applies any
 *     pending migrations on boot (idempotent).
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

import { migrate } from '@posthog/agent-migrations'
import {
    AnalyticsSink,
    applySchema as applyMemorySchema,
    CaptureAnalyticsSink,
    createLogger,
    EncryptedFields,
    FsBundleStore,
    FullTextRecaller,
    installProcessHandlers,
    KafkaLogSink,
    Memory,
    NoopAnalyticsSink,
    NoopSessionEventBus,
    PgIdentityStore,
    PgIntegrationStore,
    PgRevisionStore,
    PgSandboxInstanceStore,
    PgSessionQueue,
    RedisSessionEventBus,
    SecretBroker,
    selectSandboxPool,
    SessionEventBus,
} from '@posthog/agent-shared'
import { setMemory } from '@posthog/agent-tools'

import { defaultApiKeyFromConfig, loadAgentRunnerConfig } from './config'
import { makePerAskerAuth } from './loop/per-asker-auth'
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
    // Belt-and-braces in dev; prod also runs `bin/migrate --scope=agent_runtime`
    // as a one-shot job before the service starts. Idempotent.
    await migrate({ databaseUrl: config.agentDbUrl })

    // Agent memory (slice): the agent_memory_* tables aren't in
    // @posthog/agent-migrations yet, so apply the slice schema here
    // (idempotent). Graduation folds this into a migration + swaps the
    // FTS recaller for embeddings. See docs/agent-platform/plans/agent-memory-mnemion-slice.md.
    await applyMemorySchema(agentDb)
    setMemory(new Memory(agentDb, new FullTextRecaller()))

    const defaultApiKey = defaultApiKeyFromConfig(config)
    const revisions = new PgRevisionStore(posthogDb)

    // Build the resolveSecrets path. If ENCRYPTION_SALT_KEYS is set, decrypt
    // AgentApplication.encrypted_env via Fernet (matches Django). Otherwise
    // start with no secrets — dev / CI is happy without encryption configured.
    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const resolveSecrets = encryption.isConfigured
        ? makeEncryptedEnvResolver({ revisions, encryption })
        : async () => ({})

    // Integration credentials live in PostHog's existing `posthog_integration`
    // table (the same one Settings → Integrations writes to and HogFunctions
    // read from). When encryption isn't configured the store can't decrypt
    // sensitive_config — the resolver falls back to an empty map so dev
    // without integrations keeps working. See
    // services/agent-shared/src/persistence/integration-store.ts.
    const integrations = encryption.isConfigured ? new PgIntegrationStore(posthogDb, encryption) : null
    const resolveIntegrations = integrations
        ? async (session: { team_id: number; revision_id: string }) => {
              const rev = await revisions.getRevision(session.revision_id)
              const kinds = rev?.spec?.integrations ?? []
              return integrations.resolveForSpec(session.team_id, kinds)
          }
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

    // Structured per-turn log sink. Every session lifecycle event the
    // runner emits is also shipped to the shared `log_entries` CH table
    // via Kafka, so the console's session-detail page can render them.
    // Connect at boot — failing here is louder than silently dropping
    // logs into a NoopLogSink in prod. Local dev: PostHog's flox env
    // brings up Kafka on `localhost:9092` by default.
    const logSink = new KafkaLogSink({
        brokers: config.kafkaHosts,
        logger: {
            info: (m, x) => log.info(x ?? {}, m),
            warn: (m, x) => log.warn(x ?? {}, m),
            error: (m, x) => log.error(x ?? {}, m),
        },
    })
    await logSink.connect()

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

    // Per-asker authorisation shortcut for approval-gated tools (#23 step 3).
    // Lets a Slack user who's already a team admin drive a gated tool
    // directly via chat instead of going through the queued-approval UI.
    // Reuses the same identity table the ingress writes through.
    const identities = new PgIdentityStore(agentDb)
    const isAskerInApproverScope = makePerAskerAuth({ identities, posthogDb })

    const worker = new Worker({
        queue: new PgSessionQueue(agentDb),
        revisions,
        bundle: new FsBundleStore(config.bundleRoot),
        sandboxes: selectSandboxPool(),
        sandboxInstances: new PgSandboxInstanceStore(agentDb),
        pi: new PiAiClient(defaultApiKey),
        broker: new SecretBroker(),
        bus,
        logs: logSink,
        resolveIntegrations,
        resolveSecrets,
        isAskerInApproverScope,
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
    await logSink.disconnect()
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
