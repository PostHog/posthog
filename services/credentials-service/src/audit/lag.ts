import type { Pool } from 'pg'

import { logger } from '../lib/logging'
import { auditExportLagSeconds } from './metrics'

export async function measureAuditExportLag(pool: Pool): Promise<void> {
    try {
        const result = await pool.query<{ lag: string }>(
            `SELECT COALESCE(EXTRACT(EPOCH FROM now() - min(occurred_at)), 0) AS lag
             FROM audit_log WHERE exported_at IS NULL`
        )
        const row = result.rows[0]
        if (!row) {
            throw new Error('audit lag query returned no rows')
        }
        auditExportLagSeconds.set(Number(row.lag))
    } catch (err) {
        logger.warn('audit:lag_query_failed', { error: err instanceof Error ? err.message : String(err) })
    }
}
