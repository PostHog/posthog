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

import { S3Client } from '@aws-sdk/client-s3'

import { migrate } from '@posthog/agent-migrations'
import {
    AnalyticsSink,
    analyticsDistinctId,
    CaptureAnalyticsSink,
    createLogger,
    EncryptedFields,
    FsBundleStore,
    HttpGatewayClient,
    installProcessHandlers,
    KafkaLogSink,
    MemoryStore,
    NoopAnalyticsSink,
    NoopSessionEventBus,
    PgCredentialBroker,
    PgIdentityStore,
    PgIntegrationStore,
    PgRevisionStore,
    PgSandboxInstanceStore,
    PgSessionQueue,
    PgTeamApiKeyResolver,
    RedisSessionEventBus,
    S3MemoryStore,
    SecretBroker,
    selectSandboxPool,
    SessionEventBus,
} from '@posthog/agent-shared'

import { defaultApiKeyFromConfig, loadAgentRunnerConfig } from './config'
import { makePerAskerAuth } from './loop/per-asker-auth'
import { posthogLlmGatewayModel } from './models/llm-gateway-model'
import { resolveModelCached } from './models/pi-client'
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

    const defaultApiKey = defaultApiKeyFromConfig(config)
    const revisions = new PgRevisionStore(posthogDb)

    // Encryption is required at boot now — constructor throws on empty
    // keys. Dev gets a deterministic default via `isDev()` in platform
    // config; prod must set ENCRYPTION_SALT_KEYS explicitly.
    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const resolveSecrets = makeEncryptedEnvResolver({ revisions, encryption })

    // Integration credentials live in PostHog's existing `posthog_integration`
    // table (the same one Settings → Integrations writes to and HogFunctions
    // read from). Unconditionally wired now that encryption is required.
    const integrations = new PgIntegrationStore(posthogDb, encryption)
    const resolveIntegrations = async (session: {
        team_id: number
        revision_id: string
    }): Promise<Awaited<ReturnType<typeof integrations.resolveForSpec>>> => {
        const rev = await revisions.getRevision(session.revision_id)
        const kinds = rev?.spec?.integrations ?? []
        return integrations.resolveForSpec(session.team_id, kinds)
    }

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
    // Reuses the same identity table the ingress writes through. Threaded
    // into `WorkerDeps.isAskerInApproverScope` → driver → gated tool's
    // pre-queue check in build-agent-tools.
    const identities = new PgIdentityStore(agentDb)
    const isAskerInApproverScope = makePerAskerAuth({ identities, posthogDb })

    // On the gateway path the bearer is the owning team's phc_ project key.
    // The resolver caches per team so the hot path is a hash lookup.
    // See docs/agent-platform/plans/ai-gateway-integration.md §3 (W1).
    const teamApiKeys = config.useLlmGateway ? new PgTeamApiKeyResolver(posthogDb) : null
    // Gateway read client for /v1/usage + /v1/wallet/balance lookups.
    const gatewayClient = config.useLlmGateway ? new HttpGatewayClient({ baseUrl: config.llmGatewayUrl }) : null

    // Agent memory: S3-backed file store. Disabled (memory tools surface
    // `memory_store_unavailable` to the model) when the bucket isn't
    // configured — dev/CI without object storage still boots cleanly.
    let memoryStore: MemoryStore | undefined
    if (config.memoryS3Bucket && config.memoryS3Endpoint) {
        const s3 = new S3Client({
            endpoint: config.memoryS3Endpoint,
            region: config.memoryS3Region,
            forcePathStyle: config.memoryS3ForcePathStyle,
            credentials:
                config.memoryS3AccessKeyId && config.memoryS3SecretAccessKey
                    ? {
                          accessKeyId: config.memoryS3AccessKeyId,
                          secretAccessKey: config.memoryS3SecretAccessKey,
                      }
                    : undefined,
        })
        memoryStore = new S3MemoryStore({
            client: s3,
            bucket: config.memoryS3Bucket,
            bucketPrefix: config.memoryS3Prefix,
        })
        log.info(
            { bucket: config.memoryS3Bucket, endpoint: config.memoryS3Endpoint, prefix: config.memoryS3Prefix },
            'memory.s3.enabled'
        )
    } else {
        log.warn({}, 'memory.s3.disabled — set AGENT_MEMORY_S3_BUCKET + AGENT_MEMORY_S3_ENDPOINT to enable')
    }

    // Per-session credential broker — same shape ingress writes to.
    // Required for any non-public auth mode (e.g. the concierge's
    // oauth/pat). Construction throws if encryption isn't configured —
    // fail-fast at boot.
    const credentialBroker = new PgCredentialBroker(agentDb, {
        encryptionSaltKeys: config.encryptionSaltKeys,
    })

    const worker = new Worker({
        queue: new PgSessionQueue(agentDb),
        revisions,
        bundle: new FsBundleStore(config.bundleRoot),
        sandboxes: selectSandboxPool(),
        sandboxInstances: new PgSandboxInstanceStore(agentDb),
        broker: new SecretBroker(),
        credentialBroker,
        bus,
        logs: logSink,
        resolveIntegrations,
        resolveSecrets,
        resolveModel: config.useLlmGateway
            ? // Route every model through PostHog's llm-gateway. The gateway's
              // router admits on the canonical "<provider>/<model>" form; its
              // dispatcher strips the prefix before forwarding so the upstream
              // provider sees the bare id (see llm-gateway PR #57). Pass
              // spec.model verbatim.
              (specModel) =>
                  posthogLlmGatewayModel({
                      modelId: specModel,
                      baseUrl: config.llmGatewayUrl,
                  })
            : undefined,
        // The driver streams through pi-ai's `streamSimple`; the per-session
        // API key flows in here (no more client-level default). Gateway path
        // → resolve the owning team's `phc_`; direct path → fall back to the
        // boot-time default (ANTHROPIC_API_KEY / OPENAI_API_KEY / etc).
        resolveApiKey: teamApiKeys ? (session) => teamApiKeys.resolve(session.team_id) : () => defaultApiKey,
        resolveGatewayHeaders: config.useLlmGateway
            ? (session) => ({
                  'X-PostHog-Distinct-Id': analyticsDistinctId(session),
                  'X-PostHog-Trace-Id': session.id,
              })
            : undefined,
        resolveGatewayUsage:
            gatewayClient && teamApiKeys
                ? async (session) => ({ client: gatewayClient, phc: await teamApiKeys.resolve(session.team_id) })
                : undefined,
        // On the gateway path pi-ai's cost numbers are client-side estimates;
        // the gateway itself owns billing. We keep token counts. Cost is
        // recovered post-turn via /v1/usage/{request_id} (see resolveGatewayUsage).
        useGatewayCost: config.useLlmGateway,
        analytics,
        maxConcurrency: config.maxConcurrency,
        memoryStore,
        isAskerInApproverScope,
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
