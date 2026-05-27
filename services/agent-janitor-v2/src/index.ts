/**
 * Janitor entrypoint. Single-process: HTTP server + periodic sweep timer.
 */

import { MemorySessionQueue } from '@posthog/agent-shared-v2'

import { buildJanitorApp } from './server'
import { sweepOnce } from './sweep'

async function main(): Promise<void> {
    const port = parseInt(process.env.PORT ?? '8082', 10)
    const queue = new MemorySessionQueue()
    const sweep = {
        queue,
        stuckThresholdMs: parseInt(process.env.STUCK_THRESHOLD_MS ?? `${15 * 60_000}`, 10),
        listCandidates: async () => [],
    }
    const app = buildJanitorApp({ queue, sweep, internalSecret: process.env.INTERNAL_SECRET })
    app.listen(port, () => {
        // eslint-disable-next-line no-console
        console.log(`[agent-janitor-v2] listening on ${port}`)
    })

    setInterval(
        async () => {
            try {
                await sweepOnce(sweep)
            } catch (err) {
                // eslint-disable-next-line no-console
                console.error('[agent-janitor-v2] sweep failed', err)
            }
        },
        parseInt(process.env.SWEEP_INTERVAL_MS ?? `${30 * 1000}`, 10)
    )
}

if (require.main === module) {
    main().catch((err) => {
        // eslint-disable-next-line no-console
        console.error('[agent-janitor-v2] fatal', err)
        process.exit(1)
    })
}
