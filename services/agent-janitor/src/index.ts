/**
 * Janitor entrypoint. Single-process: HTTP server + periodic sweep timer.
 *
 * Two Postgres pools (matches runner + ingress):
 *   - posthogDb (POSTHOG_DB_URL): Django-owned agent_application + agent_revision.
 *     The revision store reads from here so /revisions/* HTTP endpoints
 *     can resolve revisions.
 *   - agentDb (AGENT_DB_URL): queue + sandbox-instances; janitor sweep
 *     reaps stuck rows here.
 *
 * Bundle storage: filesystem at AGENT_BUNDLE_ROOT in dev, swappable to S3
 * in prod once the S3 BundleStore impl is wired.
 *
 * Run via `tsx src/index.ts` (no precompile).
 */

import { mkdir } from 'node:fs/promises'
import pg from 'pg'
const { Pool } = pg

import { createLogger, FsBundleStore, PgRevisionStore, PgSessionQueue, SCHEMA_SQL } from '@posthog/agent-shared'

import { buildJanitorApp } from './server'
import { sweepOnce } from './sweep'

const log = createLogger('agent-janitor')

async function main(): Promise<void> {
    const port = parseInt(process.env.PORT ?? '8082', 10)
    const posthogDbUrl = process.env.POSTHOG_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/posthog'
    const agentDbUrl = process.env.AGENT_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue'
    // Default to a user-writable dir so dev / local CI work without root.
    // Production sets AGENT_BUNDLE_ROOT to a mounted volume (or S3 bucket
    // for the future S3BundleStore impl).
    const bundleRoot = process.env.AGENT_BUNDLE_ROOT ?? `${process.env.HOME ?? '/tmp'}/.posthog/agent-bundles`
    await mkdir(bundleRoot, { recursive: true })

    const posthogDb = new Pool({ connectionString: posthogDbUrl })
    const agentDb = new Pool({ connectionString: agentDbUrl })
    await agentDb.query(SCHEMA_SQL)

    const queue = new PgSessionQueue(agentDb)
    const revisions = new PgRevisionStore(posthogDb)
    const bundles = new FsBundleStore(bundleRoot)

    const sweep = {
        queue,
        stuckRunningThresholdMs: parseInt(process.env.STUCK_RUNNING_MS ?? `${5 * 60_000}`, 10),
        stuckWaitingThresholdMs: parseInt(process.env.STUCK_WAITING_MS ?? `${24 * 60 * 60_000}`, 10),
        maxRetries: parseInt(process.env.MAX_RETRIES ?? '3', 10),
    }
    const app = buildJanitorApp({
        queue,
        sweep,
        revisions,
        bundles,
        internalSecret: process.env.INTERNAL_SECRET,
    })
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
