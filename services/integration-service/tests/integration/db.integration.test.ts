// Runs the real SQL against a real Postgres (testcontainers). The unit suite exercises the
// recorder against a fake pool, so nothing there would catch a broken upsert conflict
// clause, a window applied to the wrong query, or DDL that no longer applies.

import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql'
import { Pool } from 'pg'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { applySchema } from '@/db/client'
import { UsageRecorder } from '@/usage/recorder'

const KEY = 'HUBSPOT_APP_CLIENT_SECRET'
const WORKER = 'temporal-worker-data-warehouse'
const DJANGO = 'posthog-django'

let container: StartedPostgreSqlContainer
let pool: Pool

beforeAll(async () => {
    container = await new PostgreSqlContainer('postgres:16-alpine').start()
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 10 })
    await applySchema(pool)
}, 120_000)

afterAll(async () => {
    await pool?.end()
    await container?.stop()
})

beforeEach(async () => {
    await pool.query('TRUNCATE integration_secret_usage, integration_secret_last_seen, integration_secret_version')
})

describe('usage tables on a real Postgres', () => {
    it('applies the boot DDL, and concurrent replicas applying it together do not fail', async () => {
        await pool.query('CREATE DATABASE ddl_race')
        const uri = container.getConnectionUri().replace(/\/[^/?]+(\?|$)/, '/ddl_race$1')
        const pools = Array.from({ length: 4 }, () => new Pool({ connectionString: uri, max: 1 }))
        try {
            await Promise.all(pools.map((p) => applySchema(p)))
            const { rows } = await pools[0]!.query<{ table_name: string }>(
                `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name`
            )
            expect(rows.map((r) => r.table_name)).toEqual([
                'integration_secret_last_seen',
                'integration_secret_usage',
                'integration_secret_version',
            ])
        } finally {
            await Promise.all(pools.map((p) => p.end()))
        }
    }, 60_000)

    it('round-trips reads: repeated reads collapse into counted rows and last-seen upserts forward', async () => {
        const t0 = Date.parse('2026-08-01T10:15:00.000Z')
        let now = t0
        const recorder = new UsageRecorder({ pool, now: () => now })

        recorder.record(WORKER, [KEY])
        recorder.record(WORKER, [KEY])
        recorder.record(DJANGO, [KEY])
        await recorder.flush()

        // A second flush in the same hour bucket must accumulate, not duplicate or reset.
        now = t0 + 5 * 60 * 1000
        recorder.record(WORKER, [KEY])
        await recorder.flush()

        const counts = await pool.query<{ deployment: string; reads: number }>(
            `SELECT deployment, reads::int AS reads FROM integration_secret_usage
             WHERE secret_key = $1 ORDER BY deployment`,
            [KEY]
        )
        expect(counts.rows).toEqual([
            { deployment: DJANGO, reads: 1 },
            { deployment: WORKER, reads: 3 },
        ])

        const seen = await pool.query<{ deployment: string; last_seen: Date }>(
            `SELECT deployment, last_seen FROM integration_secret_last_seen
             WHERE secret_key = $1 ORDER BY deployment`,
            [KEY]
        )
        expect(seen.rows.map((r) => ({ deployment: r.deployment, at: r.last_seen.getTime() }))).toEqual([
            { deployment: DJANGO, at: t0 },
            { deployment: WORKER, at: t0 + 5 * 60 * 1000 },
        ])
    })

    // Two replicas flush the same (key, deployment, bucket) row at the same moment. If the
    // upsert ever stops summing, a rotation looks quieter than it is.
    it('sums concurrent flushes of the same key and deployment', async () => {
        const at = Date.parse('2026-08-01T10:15:00.000Z')
        const recorders = Array.from({ length: 4 }, () => new UsageRecorder({ pool, now: () => at }))
        for (const recorder of recorders) {
            recorder.record(WORKER, [KEY])
            recorder.record(WORKER, [KEY])
        }

        await Promise.all(recorders.map((recorder) => recorder.flush()))

        const { rows } = await pool.query<{ reads: number }>(
            `SELECT reads::int AS reads FROM integration_secret_usage WHERE secret_key = $1`,
            [KEY]
        )
        expect(rows).toEqual([{ reads: 8 }])
    })

    // Durability is the reason these counters live in Postgres rather than a cache: a lost
    // last-seen row would make a rotation look quieter than it is. A new pool stands in for
    // the pod that wrote them having gone away.
    it('keeps last-seen readable after the writing pool is gone', async () => {
        const at = Date.parse('2026-08-01T10:15:00.000Z')
        const writer = new Pool({ connectionString: container.getConnectionUri(), max: 1 })
        try {
            const recorder = new UsageRecorder({ pool: writer, now: () => at })
            recorder.record(DJANGO, [KEY])
            await recorder.flush()
        } finally {
            await writer.end()
        }

        const { rows } = await pool.query<{ last_seen: Date }>(
            `SELECT last_seen FROM integration_secret_last_seen WHERE secret_key = $1 AND deployment = $2`,
            [KEY, DJANGO]
        )
        expect(rows.map((r) => r.last_seen.getTime())).toEqual([at])
    })

    it('prune deletes count rows past retention and never touches last-seen', async () => {
        await pool.query(
            `INSERT INTO integration_secret_usage (secret_key, deployment, bucket, reads, last_seen) VALUES
             ($1, $2, now() - interval '10 days', 5, now() - interval '10 days'),
             ($1, $2, now() - interval '1 hour', 3, now() - interval '1 hour')`,
            [KEY, WORKER]
        )
        await pool.query(
            `INSERT INTO integration_secret_last_seen (secret_key, deployment, last_seen)
             VALUES ($1, $2, now() - interval '10 days')`,
            [KEY, WORKER]
        )

        await new UsageRecorder({ pool }).prune(9)

        const counts = await pool.query<{ reads: number }>(
            `SELECT reads::int AS reads FROM integration_secret_usage WHERE secret_key = $1`,
            [KEY]
        )
        expect(counts.rows).toEqual([{ reads: 3 }])
        const seen = await pool.query(`SELECT 1 FROM integration_secret_last_seen WHERE secret_key = $1`, [KEY])
        expect(seen.rowCount).toBe(1)
    })
})
