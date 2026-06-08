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

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1', ''])

function isLocalHost(connectionString: string): boolean {
    try {
        return LOCAL_HOSTS.has(new URL(connectionString).hostname)
    } catch {
        return false
    }
}

/**
 * Aurora's pg_hba requires SSL (`hostssl all all 0.0.0.0/0 md5`) and the
 * chart helper builds DSNs without `?sslmode=require`, so we opt in
 * client-side — same pattern as `createAgentPool` in `@posthog/agent-shared`.
 * `rejectUnauthorized: false` matches the in-cluster pgbouncer behavior
 * (Aurora uses the AWS RDS CA which Node doesn't trust out of the box).
 */
function dbClientOpts(connectionString: string): pg.ClientConfig {
    return {
        connectionString,
        // nosemgrep: problem-based-packs.insecure-transport.js-node.bypass-tls-verification.bypass-tls-verification
        ssl: isLocalHost(connectionString) ? false : { rejectUnauthorized: false },
    }
}

export interface MigrateOpts {
    /** Postgres connection string. Falls back to AGENT_DB_URL env. */
    databaseUrl?: string
    /** Direction. Defaults to 'up'. */
    direction?: 'up' | 'down'
    /** Limit how many migrations to apply. 0 = unlimited. */
    count?: number
}

// 32-bit signed int identifying the agent-platform migrate lock — `pg_advisory_lock`
// takes int4 or int8. Process-scoped: held for the duration of one migrate() call.
const MIGRATE_ADVISORY_LOCK = 0x41474e54 // ASCII "AGNT"

// 42P07 = duplicate_table. Bundled node-pg-migrate's ensureMigrationsTable
// uses plain `CREATE TABLE` rather than `CREATE TABLE IF NOT EXISTS`, so
// any concurrent migrate() racing past the existence check trips this.
const PG_DUPLICATE_TABLE_CODE = '42P07'

export async function migrate(opts: MigrateOpts = {}): Promise<void> {
    const databaseUrl = opts.databaseUrl ?? process.env.AGENT_DB_URL
    if (!databaseUrl) {
        throw new Error('agent-migrations: databaseUrl or AGENT_DB_URL is required')
    }

    // Serialize migrate() across processes via an advisory lock + pre-create
    // the migrations table idempotently. Without these two, two pods racing
    // through agent-runner / agent-janitor startup both call into the bundled
    // node-pg-migrate, both see "pgmigrations doesn't exist", both issue
    // `CREATE TABLE pgmigrations (...)` (no IF NOT EXISTS), and the loser
    // crashes with `relation "pgmigrations" already exists`.
    const pool = new Pool({ ...dbClientOpts(databaseUrl), max: 1 })
    try {
        const client = await pool.connect()
        try {
            await client.query('SELECT pg_advisory_lock($1)', [MIGRATE_ADVISORY_LOCK])
            await client.query(
                'CREATE TABLE IF NOT EXISTS public.pgmigrations (id SERIAL PRIMARY KEY, name varchar(255) NOT NULL, run_on timestamp NOT NULL)'
            )
            try {
                await runner({
                    databaseUrl: dbClientOpts(databaseUrl),
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
            } catch (err) {
                // Belt-and-braces: even with the advisory lock + pre-create,
                // swallow the duplicate-table error in case the bundled
                // ensureMigrationsTable still trips on its own existence check.
                if (!isDuplicateTableError(err)) {
                    throw err
                }
            }
        } finally {
            await client.query('SELECT pg_advisory_unlock($1)', [MIGRATE_ADVISORY_LOCK])
            client.release()
        }
    } finally {
        await pool.end()
    }
}

function isDuplicateTableError(err: unknown): boolean {
    if (!(err instanceof Error)) {
        return false
    }
    // node-pg-migrate wraps the original pg error; check both shapes.
    const code = (err as Error & { code?: string }).code
    if (code === PG_DUPLICATE_TABLE_CODE) {
        return true
    }
    return err.message.includes('pgmigrations') && err.message.includes('already exists')
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
    const pool = new Pool({ ...dbClientOpts(databaseUrl), max: 1 })
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
