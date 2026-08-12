// Postgres holds the usage counters and the version-observation log, never a credential.
// Losing a stale reader's row makes a rotation look quieter than it is, so durability is
// the point.
//
// The DSN goes through PgBouncer in transaction mode: no LISTEN/NOTIFY, no session-scoped
// settings, no server-side named prepared statements.

import { Pool } from 'pg'

import { logger } from '../lib/logging'

// Idempotent DDL, applied at boot. Three small tables do not justify a migration runner.
const SCHEMA = `
CREATE TABLE IF NOT EXISTS integration_secret_usage (
    secret_key  text        NOT NULL,
    deployment  text        NOT NULL,
    bucket      timestamptz NOT NULL,
    reads       bigint      NOT NULL DEFAULT 0,
    last_seen   timestamptz NOT NULL,
    PRIMARY KEY (secret_key, deployment, bucket)
);

CREATE INDEX IF NOT EXISTS integration_secret_usage_bucket_idx
    ON integration_secret_usage (bucket);

-- Last-seen, separate from the bucketed counts and never pruned: safeToRetirePrevious has
-- to consider every deployment known to read a key, however rarely it reads, and keeping
-- this out of the bucketed table is what makes "known to read" mean all time.
CREATE TABLE IF NOT EXISTS integration_secret_last_seen (
    secret_key text        NOT NULL,
    deployment text        NOT NULL,
    last_seen  timestamptz NOT NULL,
    PRIMARY KEY (secret_key, deployment)
);

-- When this content first appeared, agreed across replicas and surviving a restart. A
-- mounted secret carries no AWS version, so first-observation is what "the value changed
-- at" means.
CREATE TABLE IF NOT EXISTS integration_secret_version (
    content_hash      text        PRIMARY KEY,
    first_observed_at timestamptz NOT NULL DEFAULT now()
);
`

/**
 * Apply the schema, retrying once. `CREATE TABLE IF NOT EXISTS` from replicas booting
 * together can still race Postgres's catalog inserts and fail; by the second attempt the
 * winner's tables exist and the statements no-op.
 */
export async function applySchema(pool: Pool): Promise<void> {
    try {
        await pool.query(SCHEMA)
    } catch (err) {
        logger.warn('db:schema_apply_retry', { error: err instanceof Error ? err.message : String(err) })
        await pool.query(SCHEMA)
    }
}

export async function createPool(dsn: string): Promise<Pool> {
    const pool = new Pool({
        connectionString: dsn,
        max: 8,
        idleTimeoutMillis: 30_000,
        connectionTimeoutMillis: 5_000,
    })
    pool.on('error', (err: Error) => logger.error('db:pool_error', { error: err.message }))
    await applySchema(pool)
    return pool
}

/**
 * Record that this content hash exists and return when it was first seen anywhere. The
 * insert and the read are separate statements because ON CONFLICT DO NOTHING with
 * RETURNING answers null for a hash we already know.
 */
export async function observeVersion(pool: Pool, contentHash: string): Promise<string | null> {
    await pool.query(`INSERT INTO integration_secret_version (content_hash) VALUES ($1) ON CONFLICT DO NOTHING`, [
        contentHash,
    ])
    const { rows } = await pool.query<{ first_observed_at: Date }>(
        `SELECT first_observed_at FROM integration_secret_version WHERE content_hash = $1`,
        [contentHash]
    )
    return rows[0] ? rows[0].first_observed_at.toISOString() : null
}
