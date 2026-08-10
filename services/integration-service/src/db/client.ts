// Postgres — the service's durable state.
//
// This holds usage counters and the version-observation log. It deliberately does NOT hold
// credentials: those arrive on the mounted secret and never leave process memory.
//
// Durability is the point, not tidiness. The counters decide whether an old credential is
// safe to retire, and losing a row changes that answer in the UNSAFE direction: drop a
// stale reader's record while keeping a fresh one, and the stale reader disappears, so the
// verdict flips to "safe" while that reader is still on the old value. A cache with an
// eviction policy cannot be trusted with an input to that decision.
//
// The DSN comes from the `psql:` harness in the posthog-app chart, which also stands up
// PgBouncer. That means transaction pooling, so nothing here may rely on session state:
// no LISTEN/NOTIFY, no session-scoped settings, no server-side named prepared statements.
// Plain parameterised queries are what node-postgres sends by default.

import { Pool } from 'pg'

import { logger } from '../lib/logging.js'

// Idempotent DDL, applied at boot. Two tables with no foreign keys and no history to
// migrate does not justify a migration runner yet; revisit if the schema grows a third.
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

-- When this content first appeared, agreed across replicas and surviving a restart. A
-- mounted secret carries no AWS version, so first-observation is what "the value changed
-- at" means now.
CREATE TABLE IF NOT EXISTS integration_secret_version (
    content_hash      text        PRIMARY KEY,
    first_observed_at timestamptz NOT NULL DEFAULT now()
);
`

export async function createPool(dsn: string): Promise<Pool> {
    const pool = new Pool({
        connectionString: dsn,
        max: 8,
        idleTimeoutMillis: 30_000,
        connectionTimeoutMillis: 5_000,
    })
    pool.on('error', (err: Error) => logger.error('db:pool_error', { error: err.message }))
    await pool.query(SCHEMA)
    return pool
}

/**
 * Record that this content hash exists and return when it was first seen anywhere.
 *
 * ON CONFLICT DO NOTHING then RETURNING would give null for a hash we already know, so the
 * insert and the read are separate statements. Both are trivial against a table with one
 * row per rotation.
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
