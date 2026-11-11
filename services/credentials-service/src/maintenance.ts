// Entry point for the maintenance commands: `node credentials-service-maintenance.mjs audit-retention`.
// It runs as its own process (a Kubernetes CronJob), connected as the migrate role. The runtime
// role cannot delete audit rows, so the server process cannot prune them.

import { Pool } from 'pg'

import { pruneAuditLog } from './audit/retention'
import { loadMaintenanceConfig } from './lib/config'
import { logger } from './lib/logging'

const COMMANDS = ['audit-retention'] as const

async function main(): Promise<void> {
    const [command, ...rest] = process.argv.slice(2)
    if (command !== 'audit-retention' || rest.length > 0) {
        throw new Error(`usage: credentials-service-maintenance [${COMMANDS.join(' | ')}]`)
    }
    const config = loadMaintenanceConfig()
    if (!config) {
        throw new Error('CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL is not set')
    }
    const pool = new Pool({ connectionString: config.url, max: 2, application_name: 'credentials-service-maintenance' })
    // A dropped connection emits 'error' on the pool. Without a listener it would end the run with an uncaught exception.
    pool.on('error', (err) => logger.error('maintenance:pool_error', { error: err.message }))
    try {
        const deleted = await pruneAuditLog(pool, {
            retentionDays: config.retentionDays,
            deleteUnexported: config.deleteUnexported,
        })
        logger.info('maintenance:complete', { command, deleted, skipped: deleted === null })
    } finally {
        await pool.end()
    }
}

main().catch((err: unknown) => {
    logger.error('maintenance:failed', { error: err instanceof Error ? err.message : String(err) })
    process.exit(1)
})
