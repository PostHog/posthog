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
    FsBundleStore,
    PgRevisionStore,
    PgSessionQueue,
    SCHEMA_SQL,
    SecretBroker,
    selectSandboxPool,
} from '@posthog/agent-shared-v2'

import { posthogLlmGatewayModel } from './llm-gateway-model'
import { PiAiClient, resolveModelCached } from './pi-client'
import { Worker } from './worker'

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

    const worker = new Worker({
        queue: new PgSessionQueue(pool),
        revisions: new PgRevisionStore(pool),
        bundle: new FsBundleStore(bundleRoot),
        sandboxes: selectSandboxPool(),
        pi: new PiAiClient(defaultApiKey),
        broker: new SecretBroker(),
        resolveIntegrations: async () => ({}),
        resolveSecrets: async () => ({}),
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
        // eslint-disable-next-line no-console
        console.log(`[agent-runner-v2] ${sig} received — suspending in-flight sessions`)
        void worker.stop()
    }
    process.on('SIGTERM', () => shutdown('SIGTERM'))
    process.on('SIGINT', () => shutdown('SIGINT'))

    // eslint-disable-next-line no-console
    console.log(
        `[agent-runner-v2] starting worker loop (db=${dbUrl}, concurrency=${maxConcurrency}, gateway=${useGateway})`
    )
    await worker.loop()
    await pool.end()
    // eslint-disable-next-line no-console
    console.log('[agent-runner-v2] stopped cleanly')
}

// Silence unused-import warning while keeping resolveModelCached importable.
void resolveModelCached

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        // eslint-disable-next-line no-console
        console.error('[agent-runner-v2] fatal', err)
        process.exit(1)
    })
}
