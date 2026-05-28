/**
 * Janitor entrypoint. Single-process: HTTP server + periodic sweep timer.
 *
 * Wires the real PG queue so the sweep's `reapStuckRunning` SQL runs against
 * production data. Run via `tsx src/index.ts` (no precompile).
 */

import { Pool } from 'pg'

import { createLogger, PgSessionQueue, SCHEMA_SQL } from '@posthog/agent-shared'

import { buildJanitorApp } from './server'
import { sweepOnce } from './sweep'

const log = createLogger('agent-janitor')

async function main(): Promise<void> {
    const port = parseInt(process.env.PORT ?? '8082', 10)
    const dbUrl = process.env.AGENT_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue'
    const pool = new Pool({ connectionString: dbUrl })
    await pool.query(SCHEMA_SQL)
    const queue = new PgSessionQueue(pool)

    const sweep = {
        queue,
        stuckRunningThresholdMs: parseInt(process.env.STUCK_RUNNING_MS ?? `${5 * 60_000}`, 10),
        stuckWaitingThresholdMs: parseInt(process.env.STUCK_WAITING_MS ?? `${24 * 60 * 60_000}`, 10),
        maxRetries: parseInt(process.env.MAX_RETRIES ?? '3', 10),
    }
    const app = buildJanitorApp({ queue, sweep, internalSecret: process.env.INTERNAL_SECRET })
    app.listen(port, () => {
        log.info({ port }, 'listening')
    })

    setInterval(
        async () => {
            try {
                const result = await sweepOnce(sweep)
                log.debug({ ...result }, 'sweep.done')
            } catch (err) {
                log.error({ err: (err as Error).message, stack: (err as Error).stack }, 'sweep.failed')
            }
        },
        parseInt(process.env.SWEEP_INTERVAL_MS ?? `${30 * 1000}`, 10)
    )
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
