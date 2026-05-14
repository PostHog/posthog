#!/usr/bin/env tsx
/**
 * Apply pending migrations to the agent-runtime queue DB.
 *
 * Reads SQL files from services/agent-core/migrations/, applies them in lexicographic
 * order, records each applied id in agent_runtime_migrations.
 *
 * Usage:
 *   AGENT_RUNTIME_QUEUE_DATABASE_URL=postgres://... pnpm migrate
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { Pool } from 'pg'

async function main(): Promise<void> {
    const url = process.env.AGENT_RUNTIME_QUEUE_DATABASE_URL
    if (!url) {
        console.error('AGENT_RUNTIME_QUEUE_DATABASE_URL is required')
        process.exit(1)
    }

    const migrationsDir = join(__dirname, '..', 'migrations')
    const files = readdirSync(migrationsDir)
        .filter((f) => f.endsWith('.sql'))
        .sort()

    const pool = new Pool({ connectionString: url })
    try {
        await pool.query(
            `CREATE TABLE IF NOT EXISTS agent_runtime_migrations (
                id TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )`
        )

        for (const file of files) {
            const id = file.replace(/\.sql$/, '')
            const { rowCount } = await pool.query('SELECT 1 FROM agent_runtime_migrations WHERE id = $1', [id])
            if (rowCount && rowCount > 0) {
                console.info(`[migrate] skip ${id}`)
                continue
            }
            const sql = readFileSync(join(migrationsDir, file), 'utf8')
            console.info(`[migrate] apply ${id}`)
            await pool.query('BEGIN')
            try {
                await pool.query(sql)
                await pool.query('INSERT INTO agent_runtime_migrations (id) VALUES ($1)', [id])
                await pool.query('COMMIT')
            } catch (err) {
                await pool.query('ROLLBACK')
                throw err
            }
        }
    } finally {
        await pool.end()
    }
}

main().catch((err) => {
    console.error(err)
    process.exit(1)
})
