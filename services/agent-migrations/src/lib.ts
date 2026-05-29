/**
 * Library surface for the agent-platform migration runner. Thin wrapper
 * around node-pg-migrate so callers (boot path, harness reset, CLI) speak
 * a single API.
 *
 *   - migrate({ databaseUrl })   — applies any pending migrations.
 *   - reset({ databaseUrl })     — drops the public schema and reapplies
 *                                  every migration. For the test harness.
 *
 * The schema migration history table is the node-pg-migrate default,
 * `pgmigrations`. New SQL files go in ./migrations/ — see CLAUDE.md for
 * conventions.
 */

import runner from 'node-pg-migrate'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import pg from 'pg'
const { Pool } = pg

const HERE = dirname(fileURLToPath(import.meta.url))
const MIGRATIONS_DIR = resolve(HERE, '../migrations')

export interface MigrateOpts {
    /** Postgres connection string. Falls back to AGENT_DB_URL env. */
    databaseUrl?: string
    /** Direction. Defaults to 'up'. */
    direction?: 'up' | 'down'
    /** Limit how many migrations to apply. 0 = unlimited. */
    count?: number
}

export async function migrate(opts: MigrateOpts = {}): Promise<void> {
    const databaseUrl = opts.databaseUrl ?? process.env.AGENT_DB_URL
    if (!databaseUrl) {
        throw new Error('agent-migrations: databaseUrl or AGENT_DB_URL is required')
    }
    await runner({
        databaseUrl,
        dir: MIGRATIONS_DIR,
        direction: opts.direction ?? 'up',
        count: opts.count ?? Infinity,
        // SQL files only — no JS templates.
        // node-pg-migrate keys off the file extension automatically.
        migrationsTable: 'pgmigrations',
        // No transactions across migrations — each migration runs in its
        // own implicit txn (node-pg-migrate's default for SQL files).
        singleTransaction: false,
        // Don't try to mutate the search_path; we depend on `public`.
        schema: 'public',
        // Silent in tests. CLI re-enables via env.
        verbose: process.env.AGENT_MIGRATE_VERBOSE === '1',
        logger: process.env.AGENT_MIGRATE_VERBOSE === '1' ? console : NULL_LOGGER,
    })
}

/**
 * Test-harness helper: drop the `public` schema and reapply every
 * migration. Cheaper and less error-prone than a hand-maintained
 * `DROP TABLE` list — anything not in migrations vanishes.
 */
export async function reset(opts: MigrateOpts = {}): Promise<void> {
    const databaseUrl = opts.databaseUrl ?? process.env.AGENT_DB_URL
    if (!databaseUrl) {
        throw new Error('agent-migrations.reset: databaseUrl or AGENT_DB_URL is required')
    }
    const pool = new Pool({ connectionString: databaseUrl, max: 1 })
    try {
        await pool.query('DROP SCHEMA IF EXISTS public CASCADE')
        await pool.query('CREATE SCHEMA public')
    } finally {
        await pool.end()
    }
    await migrate({ databaseUrl })
}

const NULL_LOGGER = {
    debug: () => undefined,
    info: () => undefined,
    warn: () => undefined,
    error: (msg: string) => console.error(msg),
}
