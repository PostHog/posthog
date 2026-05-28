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
    createLogger,
    EncryptedFields,
    FsBundleStore,
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

import { posthogLlmGatewayModel } from './models/llm-gateway-model'
import { PiAiClient, resolveModelCached } from './models/pi-client'
import { makeEncryptedEnvResolver } from './resolvers/encrypted-env-resolver'
import { Worker } from './workers/worker'

const log = createLogger('agent-runner')

async function main(): Promise<void> {
    const posthogDbUrl = process.env.POSTHOG_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/posthog'
    const agentDbUrl = process.env.AGENT_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue'
    // Default to a user-writable dir so dev / local CI work without root.
    // Production sets AGENT_BUNDLE_ROOT to a mounted volume shared with the
    // janitor (same path on both deployments).
    const bundleRoot = process.env.AGENT_BUNDLE_ROOT ?? `${process.env.HOME ?? '/tmp'}/.posthog/agent-bundles`
    await mkdir(bundleRoot, { recursive: true })
    const useGateway = process.env.AGENT_USE_LLM_GATEWAY === '1'

    const posthogDb = new Pool({ connectionString: posthogDbUrl })
    const agentDb = new Pool({ connectionString: agentDbUrl })
    // Only the queue DB schema is the runner's responsibility — Django owns
    // the authoring tables (agent_application, agent_revision) in posthogDb.
    await agentDb.query(SCHEMA_SQL)

    const defaultApiKey =
        process.env.POSTHOG_LLM_GATEWAY_KEY ??
        process.env.ANTHROPIC_API_KEY ??
        process.env.OPENAI_API_KEY ??
        process.env.MODEL_API_KEY

    const maxConcurrency = parseInt(process.env.AGENT_MAX_CONCURRENCY ?? '8', 10)

    const revisions = new PgRevisionStore(posthogDb)

    // Build the resolveSecrets path. If ENCRYPTION_SALT_KEYS is set, decrypt
    // AgentApplication.encrypted_env via Fernet (matches Django). Otherwise
    // start with no secrets — dev / CI is happy without encryption configured.
    const encryptionSaltKeys = process.env.ENCRYPTION_SALT_KEYS ?? ''
    const encryption = new EncryptedFields(encryptionSaltKeys)
    const resolveSecrets = encryption.isConfigured
        ? makeEncryptedEnvResolver({ revisions, encryption })
        : async () => ({})

    // Cross-process event bus. With REDIS_URL set, ingress /listen on host A
    // sees events published by a runner on host B. Without it the runner
    // still works — events just go nowhere (no SSE consumers can connect).
    let bus: SessionEventBus = new NoopSessionEventBus()
    if (process.env.REDIS_URL) {
        const redis = new RedisSessionEventBus({ url: process.env.REDIS_URL })
        await redis.connect()
        bus = redis
    }

    const worker = new Worker({
        queue: new PgSessionQueue(agentDb),
        revisions,
        bundle: new FsBundleStore(bundleRoot),
        sandboxes: selectSandboxPool(),
        sandboxInstances: new PgSandboxInstanceStore(agentDb),
        pi: new PiAiClient(defaultApiKey),
        broker: new SecretBroker(),
        bus,
        resolveIntegrations: async () => ({}),
        resolveSecrets,
        resolveModel: useGateway
            ? // Route every model through PostHog's llm-gateway, keeping spec.model
              // as the model id but ignoring the provider prefix.
              (specModel) =>
                  posthogLlmGatewayModel({
                      modelId: specModel.includes('/') ? specModel.split('/').pop()! : specModel,
                  })
            : undefined,
        maxConcurrency,
    })

    const shutdown = (sig: string): void => {
        log.info({ sig }, 'shutdown signal received — suspending in-flight sessions')
        void worker.stop()
    }
    process.on('SIGTERM', () => shutdown('SIGTERM'))
    process.on('SIGINT', () => shutdown('SIGINT'))

    log.info(
        { posthogDb: posthogDbUrl, agentDb: agentDbUrl, concurrency: maxConcurrency, gateway: useGateway },
        'starting worker loop'
    )
    await worker.loop()
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
