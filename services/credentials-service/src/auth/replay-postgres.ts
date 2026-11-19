// Postgres shares token ids across pods and restarts, so each token verifies only once.

import type { Queryable } from '../db/integrations'
import { query } from '../db/integrations'
import { logger } from '../lib/logging'
import type { ReplayStore } from './replay'

// Every Nth claim also deletes expired rows, so no separate cleanup job is needed.
const CLEANUP_EVERY = 100
const CLEANUP_BATCH = 1000

export class PostgresReplayStore implements ReplayStore {
    private claims = 0

    constructor(private readonly db: Queryable) {}

    /** Records the token id. Returns false when this deployment already used it. */
    async claim(deployment: string, jti: string, expiresAtMs: number): Promise<boolean> {
        const result = await query(
            this.db,
            `INSERT INTO auth_jti (deployment, jti, expires_at)
             VALUES ($1, $2, to_timestamp($3::double precision / 1000))
             ON CONFLICT (deployment, jti) DO NOTHING
             RETURNING jti`,
            [deployment, jti, expiresAtMs]
        )
        this.claims += 1
        if (this.claims % CLEANUP_EVERY === 0) {
            void this.deleteExpired()
        }
        return result.rows.length > 0
    }

    async deleteExpired(): Promise<void> {
        try {
            await query(
                this.db,
                `DELETE FROM auth_jti WHERE (deployment, jti) IN (
                    SELECT deployment, jti FROM auth_jti WHERE expires_at <= now() LIMIT $1)`,
                [CLEANUP_BATCH]
            )
        } catch (err) {
            logger.warn('auth:jti_cleanup_failed', { error: err instanceof Error ? err.message : String(err) })
        }
    }
}
