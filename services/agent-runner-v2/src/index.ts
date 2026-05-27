/**
 * Worker entrypoint. Wires real impls (Postgres queue, S3 bundle store, pi.dev
 * HTTP client, sandbox pool from env) and runs the claim loop forever.
 *
 * Wiring is intentionally thin — each impl is replaceable. For tests, use
 * lib.ts directly with in-memory impls.
 */

import {
    MemoryBundleStore,
    MemoryRevisionStore,
    MemorySessionQueue,
    SecretBroker,
    selectSandboxPool,
} from '@posthog/agent-shared-v2'

import { HttpPiClient } from './pi-client'
import { Worker } from './worker'

async function main(): Promise<void> {
    // Production wiring would replace these in-memory stores with the actual
    // Postgres/S3-backed impls. For now, this is a runnable skeleton — the
    // shape is fixed, the backing services are env-configurable.
    const apiKey = process.env.PI_DEV_API_KEY
    if (!apiKey) {
        // eslint-disable-next-line no-console
        console.error('PI_DEV_API_KEY not set — refusing to start without a model backend')
        process.exit(1)
    }

    const worker = new Worker({
        queue: new MemorySessionQueue(),
        revisions: new MemoryRevisionStore(),
        bundle: new MemoryBundleStore(),
        sandboxes: selectSandboxPool(),
        pi: new HttpPiClient({ apiKey, baseUrl: process.env.PI_DEV_BASE_URL }),
        broker: new SecretBroker(),
        resolveIntegrations: async () => ({}),
        resolveSecrets: async () => ({}),
    })

    // eslint-disable-next-line no-console
    console.log('[agent-runner-v2] starting worker loop')
    await worker.loop()
}

if (require.main === module) {
    main().catch((err) => {
        // eslint-disable-next-line no-console
        console.error('[agent-runner-v2] fatal', err)
        process.exit(1)
    })
}
