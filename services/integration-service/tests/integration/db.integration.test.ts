// Runs the real SQL against a real Postgres (testcontainers). The unit suite exercises the
// recorder against a fake pool, so nothing there would catch a broken upsert conflict
// clause, a window applied to the wrong query, or DDL that no longer applies.

import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql'
import { Pool } from 'pg'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { applySchema } from '@/db/client'
import type { SecretsSnapshot } from '@/types'
import { UsageRecorder } from '@/usage/recorder'
import { buildUsageMap } from '@/usage/verdict'

const KEY = 'HUBSPOT_APP_CLIENT_SECRET'
const WORKER = 'temporal-worker-data-warehouse'
const DJANGO = 'posthog-django'

const CHANGED_AT = '2026-08-01T00:00:00.000Z'
const BEFORE = Date.parse('2026-07-30T00:00:00.000Z')
const AFTER = Date.parse('2026-08-02T00:00:00.000Z')

const ROTATING: SecretsSnapshot = {
    fetchedAt: '2026-08-06T00:00:00.000Z',
    versionId: 'v-new',
    changedAt: CHANGED_AT,
    secrets: {
        [KEY]: {
            state: 'rotating',
            value: 'new-value',
            previous: 'old-value',
            versionId: 'v-new',
            fetchedAt: '2026-08-06T00:00:00.000Z',
        },
    },
}

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

async function verdict(recorder: UsageRecorder): Promise<boolean | undefined> {
    const { reads, lastSeen } = await recorder.summarize(24)
    const usage = buildUsageMap({
        env: 'test',
        generatedAt: new Date().toISOString(),
        quietWindowHours: 24,
        snapshot: ROTATING,
        reads,
        lastSeen,
    })
    return usage.keys[KEY]?.safeToRetirePrevious
}

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

    it('summarize windows the counts but returns last-seen from all time', async () => {
        // A dormant deployment: rows written well outside the 24h window.
        await pool.query(
            `INSERT INTO integration_secret_usage (secret_key, deployment, bucket, reads, last_seen)
             VALUES ($1, $2, now() - interval '10 days', 7, now() - interval '10 days')`,
            [KEY, DJANGO]
        )
        const oldSeen = new Date('2026-07-01T00:00:00.000Z')
        await pool.query(
            `INSERT INTO integration_secret_last_seen (secret_key, deployment, last_seen) VALUES ($1, $2, $3)`,
            [KEY, DJANGO, oldSeen]
        )

        const recorder = new UsageRecorder({ pool })
        recorder.record(WORKER, [KEY])
        await recorder.flush()

        const { reads, lastSeen } = await recorder.summarize(24)
        expect(reads.get(`${KEY}|${WORKER}`)).toBe(1)
        expect(reads.has(`${KEY}|${DJANGO}`)).toBe(false)
        // The dormant deployment still appears: this is what holds the retirement verdict back.
        expect(lastSeen.get(`${KEY}|${DJANGO}`)).toBe(oldSeen.getTime())
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

    describe('retirement verdict from real rows', () => {
        it('is false when nothing reads the key', async () => {
            expect(await verdict(new UsageRecorder({ pool }))).toBe(false)
        })

        it('is false while a known reader has not read since the secret changed', async () => {
            const active = new UsageRecorder({ pool, now: () => AFTER })
            active.record(WORKER, [KEY])
            await active.flush()

            const stale = new UsageRecorder({ pool, now: () => BEFORE })
            stale.record(DJANGO, [KEY])
            await stale.flush()

            expect(await verdict(active)).toBe(false)
        })

        it('is true once every known reader has read since the secret changed', async () => {
            const recorder = new UsageRecorder({ pool, now: () => AFTER })
            recorder.record(WORKER, [KEY])
            recorder.record(DJANGO, [KEY])
            await recorder.flush()

            expect(await verdict(recorder)).toBe(true)
        })
    })
})
