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

import { loadAgentJanitorConfig } from './config'
import { buildJanitorApp } from './server'
import { sweepOnce } from './sweep'

const log = createLogger('agent-janitor')

async function main(): Promise<void> {
    const config = loadAgentJanitorConfig()
    await mkdir(config.bundleRoot, { recursive: true })

    const posthogDb = new Pool({ connectionString: config.posthogDbUrl })
    const agentDb = new Pool({ connectionString: config.agentDbUrl })
    await agentDb.query(SCHEMA_SQL)

    const queue = new PgSessionQueue(agentDb)
    const revisions = new PgRevisionStore(posthogDb)
    const bundles = new FsBundleStore(config.bundleRoot)

    const sweep = {
        queue,
        stuckRunningThresholdMs: config.stuckRunningMs,
        stuckWaitingThresholdMs: config.stuckWaitingMs,
        maxRetries: config.maxRetries,
    }
    const app = buildJanitorApp({
        queue,
        sweep,
        revisions,
        bundles,
        internalSecret: config.internalSecret,
    })
    app.listen(config.port, () => {
        log.info({ port: config.port }, 'listening')
    })

    setInterval(async () => {
        try {
            const result = await sweepOnce(sweep)
            log.debug({ ...result }, 'sweep.done')
        } catch (err) {
            log.error({ err: (err as Error).message, stack: (err as Error).stack }, 'sweep.failed')
        }
    }, config.sweepIntervalMs)
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
