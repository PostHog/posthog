/**
 * Worker entrypoint. Wires real Postgres queue + revision store + FS bundle
 * store, picks a pi-ai model from env, runs the claim loop until SIGTERM.
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
import { PiAiClient, resolveModel } from './pi-client'
import { Worker } from './worker'

async function main(): Promise<void> {
    const dbUrl = process.env.AGENT_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue'
    const bundleRoot = process.env.AGENT_BUNDLE_ROOT ?? '/var/lib/agent-bundles'
    const defaultModelSpec = process.env.AGENT_DEFAULT_MODEL ?? 'anthropic/claude-sonnet-4-7'

    const pool = new Pool({ connectionString: dbUrl })
    await pool.query(SCHEMA_SQL)

    // Model selection: routed via PostHog llm-gateway if a gateway key is set,
    // otherwise a direct pi-ai provider call.
    const model = process.env.POSTHOG_LLM_GATEWAY_KEY
        ? posthogLlmGatewayModel({ modelId: defaultModelSpec.split('/').pop() ?? 'gpt-4.1-mini' })
        : resolveModel(defaultModelSpec)
    const apiKey =
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
        pi: new PiAiClient(model, apiKey),
        broker: new SecretBroker(),
        resolveIntegrations: async () => ({}),
        resolveSecrets: async () => ({}),
        maxConcurrency,
    })

    const shutdown = (sig: string): void => {
        // eslint-disable-next-line no-console
        console.log(`[agent-runner-v2] ${sig} received — suspending in-flight session`)
        void worker.stop()
    }
    process.on('SIGTERM', () => shutdown('SIGTERM'))
    process.on('SIGINT', () => shutdown('SIGINT'))

    // eslint-disable-next-line no-console
    console.log(`[agent-runner-v2] starting worker loop (db=${dbUrl}, concurrency=${maxConcurrency})`)
    await worker.loop()
    await pool.end()
    // eslint-disable-next-line no-console
    console.log('[agent-runner-v2] stopped cleanly')
}

// ESM entry-point check — replaces the CJS `require.main === module` idiom.
if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        // eslint-disable-next-line no-console
        console.error('[agent-runner-v2] fatal', err)
        process.exit(1)
    })
}
