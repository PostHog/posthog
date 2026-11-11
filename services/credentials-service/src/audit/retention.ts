// Deletes audit rows older than the retention window, in small batches so no statement holds
// locks for long. Only the maintenance command runs it, as the migrate role: the runtime role
// cannot delete audit rows. Once infra runs pg_partman retention on `audit_log`, dropping a
// whole partition replaces this.

import type { Pool } from 'pg'

import { logger } from '../lib/logging'
import { RETENTION_LOCK_KEY } from './exporter'

const DAY_MS = 86_400_000

export interface RetentionOptions {
    retentionDays: number
    /** Also delete rows with no `exported_at`. Without it, only exported rows go. */
    deleteUnexported?: boolean
    batchSize?: number
    now?: () => Date
}

/** Returns the number of rows deleted, or null when another pod holds the lock. */
export async function pruneAuditLog(pool: Pool, opts: RetentionOptions): Promise<number | null> {
    const batchSize = opts.batchSize ?? 5_000
    const cutoff = new Date((opts.now?.() ?? new Date()).getTime() - opts.retentionDays * DAY_MS)
    const client = await pool.connect()
    let locked = false
    try {
        const lock = await client.query('SELECT pg_try_advisory_lock($1) AS locked', [RETENTION_LOCK_KEY])
        locked = lock.rows[0].locked === true
        if (!locked) {
            return null
        }
        let total = 0
        for (;;) {
            const result = await client.query(
                `DELETE FROM audit_log
                 WHERE (occurred_at, id) IN (
                    SELECT occurred_at, id FROM audit_log
                    WHERE occurred_at < $1 AND ($3::boolean OR exported_at IS NOT NULL) LIMIT $2)`,
                [cutoff, batchSize, opts.deleteUnexported === true]
            )
            const deleted = result.rowCount ?? 0
            total += deleted
            if (deleted < batchSize) {
                break
            }
        }
        if (total > 0) {
            logger.info('audit:retention_deleted', { rows: total, cutoff: cutoff.toISOString() })
        }
        return total
    } finally {
        if (locked) {
            await client.query('SELECT pg_advisory_unlock($1)', [RETENTION_LOCK_KEY]).catch(() => undefined)
        }
        client.release()
    }
}
