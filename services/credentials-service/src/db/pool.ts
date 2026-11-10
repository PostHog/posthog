import { Pool } from 'pg'

import type { DatabaseConfig } from '../lib/config'
import { logger } from '../lib/logging'

const CONNECTION_TIMEOUT_MS = 5_000
const STATEMENT_TIMEOUT_MS = 10_000
const IDLE_TIMEOUT_MS = 30_000
// Client-side, so a connection that stops responding fails the query and is discarded.
const QUERY_TIMEOUT_MS = STATEMENT_TIMEOUT_MS + 5_000

export function createPool(config: DatabaseConfig): Pool {
    const pool = new Pool({
        connectionString: config.url,
        max: config.poolSize,
        connectionTimeoutMillis: CONNECTION_TIMEOUT_MS,
        idleTimeoutMillis: IDLE_TIMEOUT_MS,
        statement_timeout: STATEMENT_TIMEOUT_MS,
        query_timeout: QUERY_TIMEOUT_MS,
        application_name: 'credentials-service',
    })
    // An idle client that loses its connection emits 'error' on the pool. With no listener,
    // Node throws it as an uncaught exception, and the process stops.
    pool.on('error', (err) => {
        logger.error('db:idle_client_error', { error: err.message })
    })
    return pool
}

/** True when the database answers a trivial query. Never throws. */
export async function pingDatabase(pool: Pool): Promise<boolean> {
    try {
        await pool.query('SELECT 1')
        return true
    } catch (err) {
        logger.warn('db:ping_failed', { error: err instanceof Error ? err.message : String(err) })
        return false
    }
}
