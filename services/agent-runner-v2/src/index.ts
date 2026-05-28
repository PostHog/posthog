/**
 * Worker entrypoint. Wires real Postgres queue + revision store + FS bundle
 * store, runs the claim loop until SIGTERM. Each session's model is resolved
 * from `rev.spec.model` (e.g. "anthropic/claude-sonnet-4-7"), with optional
 * routing through PostHog's llm-gateway when AGENT_USE_LLM_GATEWAY=1.
 *
 * Run with `tsx src/index.ts` (no build step). pnpm start wraps that.
 */

import { Pool } from 'pg'

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
} from '@posthog/agent-shared-v2'

import { makeEncryptedEnvResolver } from './encrypted-env-resolver'
import { posthogLlmGatewayModel } from './llm-gateway-model'
import { PiAiClient, resolveModelCached } from './pi-client'
import { Worker } from './worker'

const log = createLogger('agent-runner-v2')

async function main(): Promise<void> {
    const dbUrl = process.env.AGENT_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue'
    const bundleRoot = process.env.AGENT_BUNDLE_ROOT ?? '/var/lib/agent-bundles'
    const useGateway = process.env.AGENT_USE_LLM_GATEWAY === '1'

    const pool = new Pool({ connectionString: dbUrl })
    await pool.query(SCHEMA_SQL)

    const defaultApiKey =
        process.env.POSTHOG_LLM_GATEWAY_KEY ??
        process.env.ANTHROPIC_API_KEY ??
        process.env.OPENAI_API_KEY ??
        process.env.MODEL_API_KEY

    const maxConcurrency = parseInt(process.env.AGENT_MAX_CONCURRENCY ?? '8', 10)

    const revisions = new PgRevisionStore(pool)

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
        queue: new PgSessionQueue(pool),
        revisions,
        bundle: new FsBundleStore(bundleRoot),
        sandboxes: selectSandboxPool(),
        sandboxInstances: new PgSandboxInstanceStore(pool),
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

    log.info({ db: dbUrl, concurrency: maxConcurrency, gateway: useGateway }, 'starting worker loop')
    await worker.loop()
    await pool.end()
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
