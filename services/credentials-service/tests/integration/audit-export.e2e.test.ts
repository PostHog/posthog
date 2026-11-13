// The audit exporter and the retention step against a real Postgres in a container.

import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql'
import { Pool } from 'pg'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import {
    AUDIT_DISTINCT_ID,
    AUDIT_EVENT,
    AuditExporter,
    type CaptureEvent,
    EXPORT_LOCK_KEY,
    captureSender,
} from '@/audit/exporter'
import { pruneAuditLog } from '@/audit/retention'
import { runMigrations } from '@/db/migrate'
import { insertAuditRows } from '@/integrations/audit'
import { register } from '@/metrics'

const FAKE_SECRET = 'fake-secret-value-z9y8x7'
const DAY_MS = 86_400_000

let container: StartedPostgreSqlContainer
let pool: Pool
let runtimePool: Pool

const RUNTIME_ROLE = 'credentials_runtime_export_test'

const entry = (operation: string) => ({
    actor: { deployment: 'cdp-api', caller: 'tests', userId: 7, jti: 'jti-fake-0001', requestId: 'req-1' },
    operation,
    outcome: 'ok',
    ownerType: 'team',
    ownerId: 101,
    integrationId: '5b1f2c52-7c0e-4c3c-9d0e-0f4c6e0b6a11',
    kind: 'hubspot',
    fields: ['access_token'],
    details: { note: FAKE_SECRET },
})

async function seed(count: number, operation = 'resolve'): Promise<void> {
    await insertAuditRows(
        pool,
        Array.from({ length: count }, () => entry(operation))
    )
}

async function exportedCount(): Promise<number> {
    const result = await pool.query('SELECT count(*)::int AS n FROM audit_log WHERE exported_at IS NOT NULL')
    return result.rows[0].n
}

function recorder(): { sent: CaptureEvent[][]; send: (events: CaptureEvent[]) => Promise<void> } {
    const sent: CaptureEvent[][] = []
    return { sent, send: async (events) => void sent.push(events) }
}

async function metricValue(name: string, labels: Record<string, string> = {}): Promise<number> {
    const metric = (await register.getMetricsAsJSON()).find((m) => m.name === name)
    const values = (metric?.values ?? []).filter((v) =>
        Object.entries(labels).every(([key, value]) => (v.labels as Record<string, string>)[key] === value)
    )
    return values.reduce((sum, v) => sum + v.value, 0)
}

beforeAll(async () => {
    container = await new PostgreSqlContainer('postgres:17-alpine').start()
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 8 })
    await pool.query(`CREATE ROLE ${RUNTIME_ROLE} LOGIN PASSWORD 'not-a-real-password'`)
    await runMigrations({
        databaseUrl: container.getConnectionUri(),
        direction: 'up',
        runtimeRole: RUNTIME_ROLE,
    })
    const runtimeUrl = new URL(container.getConnectionUri())
    runtimeUrl.username = RUNTIME_ROLE
    runtimeUrl.password = 'not-a-real-password'
    runtimePool = new Pool({ connectionString: runtimeUrl.toString(), max: 4 })
}, 120_000)

beforeEach(async () => {
    await pool.query('TRUNCATE audit_log')
})

afterAll(async () => {
    await runtimePool?.end()
    await pool?.end()
    await container?.stop()
})

describe('AuditExporter', () => {
    it('exports each row once, in batches, and never again', async () => {
        await seed(5)
        const { sent, send } = recorder()
        const exporter = new AuditExporter(pool, send, 2)

        expect(await exporter.tick()).toBe('exported')
        expect(sent.map((batch) => batch.length)).toEqual([2, 2, 1])
        expect(await exportedCount()).toBe(5)

        expect(await exporter.tick()).toBe('idle')
        expect(sent).toHaveLength(3)
    })

    // The service connects as the runtime role. It may set exported_at, and nothing else on audit_log.
    it('exports as the runtime role, which can mark rows but not change or delete them', async () => {
        await seed(3)
        const { sent, send } = recorder()

        expect(await new AuditExporter(runtimePool, send, 10).tick()).toBe('exported')
        expect(await exportedCount()).toBe(3)
        expect(sent.flat()).toHaveLength(3)

        await expect(runtimePool.query(`UPDATE audit_log SET outcome = 'forged'`)).rejects.toThrow(/permission denied/)
        await expect(runtimePool.query(`UPDATE audit_log SET exported_at = NULL, outcome = 'x'`)).rejects.toThrow(
            /permission denied/
        )
        await expect(runtimePool.query('DELETE FROM audit_log')).rejects.toThrow(/permission denied/)
        await expect(pruneAuditLog(runtimePool, { retentionDays: 0 })).rejects.toThrow(/permission denied/)
    })

    it('marks rows by key when their timestamps differ only in microseconds', async () => {
        await pool.query(
            `INSERT INTO audit_log (id, occurred_at, deployment, operation, outcome)
             SELECT gen_random_uuid(), timestamptz '2026-11-10 12:00:00.123456+00' + n * interval '1 microsecond',
                    'cdp-api', 'resolve', 'ok'
             FROM generate_series(0, 4) AS n`
        )
        const { sent, send } = recorder()

        expect(await new AuditExporter(pool, send, 10).tick()).toBe('exported')
        expect(sent.flat()).toHaveLength(5)
        expect(await exportedCount()).toBe(5)
        expect(await new AuditExporter(pool, send, 10).tick()).toBe('idle')
    })

    it('sends the documented event shape', async () => {
        await seed(1, 'resolve')
        const { sent, send } = recorder()
        await new AuditExporter(pool, send, 10).tick()

        const [event] = sent[0]!
        expect(event).toMatchObject({ event: AUDIT_EVENT, distinct_id: AUDIT_DISTINCT_ID })
        expect(event!.uuid).toMatch(/^[0-9a-f-]{36}$/)
        expect(event!.properties).toEqual({
            $process_person_profile: false,
            deployment: 'cdp-api',
            caller: 'tests',
            user_id: 7,
            owner_type: 'team',
            owner_id: 101,
            integration_id: '5b1f2c52-7c0e-4c3c-9d0e-0f4c6e0b6a11',
            kind: 'hubspot',
            operation: 'resolve',
            fields: ['access_token'],
            outcome: 'ok',
            request_id: 'req-1',
        })
    })

    it('retries the same rows after a failed send', async () => {
        await seed(3)
        const failedBefore = await metricValue('credentials_service_audit_exported_total', { outcome: 'failed' })
        let calls = 0
        const sent: CaptureEvent[][] = []
        const exporter = new AuditExporter(
            pool,
            async (events) => {
                calls += 1
                if (calls === 1) {
                    throw new Error('capture answered 503')
                }
                sent.push(events)
            },
            10
        )

        expect(await exporter.tick()).toBe('failed')
        expect(await exportedCount()).toBe(0)
        expect(
            (await metricValue('credentials_service_audit_exported_total', { outcome: 'failed' })) - failedBefore
        ).toBe(3)

        expect(await exporter.tick()).toBe('exported')
        expect(sent[0]).toHaveLength(3)
        expect(await exportedCount()).toBe(3)
    })

    it('lets only one pod export at a time', async () => {
        await seed(2)
        const holder = await pool.connect()
        try {
            await holder.query('SELECT pg_advisory_lock($1)', [EXPORT_LOCK_KEY])
            const { sent, send } = recorder()
            expect(await new AuditExporter(pool, send, 10).tick()).toBe('not_leader')
            expect(sent).toHaveLength(0)
            expect(await exportedCount()).toBe(0)
        } finally {
            await holder.query('SELECT pg_advisory_unlock($1)', [EXPORT_LOCK_KEY])
            holder.release()
        }
        const { sent, send } = recorder()
        expect(await new AuditExporter(pool, send, 10).tick()).toBe('exported')
        expect(sent.flat()).toHaveLength(2)
    })

    it('exports every row once when two pods tick together', async () => {
        await seed(6)
        const { sent, send } = recorder()
        const results = await Promise.all([
            new AuditExporter(pool, send, 2).tick(),
            new AuditExporter(pool, send, 2).tick(),
        ])
        expect(results).toContain('exported')
        const uuids = sent.flat().map((event) => event.uuid)
        expect(new Set(uuids).size).toBe(6)
        expect(uuids).toHaveLength(6)
    })

    it('reports the age of the oldest unexported row as lag', async () => {
        await seed(1)
        await pool.query("UPDATE audit_log SET occurred_at = now() - interval '2 minutes'")
        const { send } = recorder()
        const failing = new AuditExporter(
            pool,
            async () => {
                throw new Error('down')
            },
            10
        )
        await failing.tick()
        expect(await metricValue('credentials_service_audit_export_lag_seconds')).toBeGreaterThanOrEqual(119)

        await new AuditExporter(pool, send, 10).tick()
        await new AuditExporter(pool, send, 10).tick()
        expect(await metricValue('credentials_service_audit_export_lag_seconds')).toBe(0)
    })

    it('puts no secret value in the request body', async () => {
        await seed(2)
        const bodies: string[] = []
        const fakeFetch = (async (_url: URL, init: RequestInit) => {
            bodies.push(String(init.body))
            return new Response(null, { status: 200 })
        }) as unknown as typeof fetch
        const send = captureSender(
            {
                host: 'http://capture.example.com',
                apiKey: 'phc_fake',
                batchSize: 10,
                intervalSeconds: 10,
                timeoutMs: 1000,
            },
            fakeFetch
        )
        await new AuditExporter(pool, send, 10).tick()

        expect(bodies).toHaveLength(1)
        expect(bodies[0]).not.toContain(FAKE_SECRET)
        expect(bodies[0]).not.toContain('jti-fake-0001')
        expect(JSON.parse(bodies[0]!).api_key).toBe('phc_fake')
    })

    it('treats a non-2xx answer as a failed send', async () => {
        await seed(1)
        const fakeFetch = (async () => new Response('nope', { status: 500 })) as unknown as typeof fetch
        const send = captureSender(
            {
                host: 'http://capture.example.com',
                apiKey: 'phc_fake',
                batchSize: 10,
                intervalSeconds: 10,
                timeoutMs: 1000,
            },
            fakeFetch
        )
        expect(await new AuditExporter(pool, send, 10).tick()).toBe('failed')
        expect(await exportedCount()).toBe(0)
    })
})

describe('pruneAuditLog', () => {
    const ageRows = async (days: number, operation: string): Promise<void> => {
        await pool.query(`UPDATE audit_log SET occurred_at = now() - $1::int * interval '1 day' WHERE operation = $2`, [
            days,
            operation,
        ])
    }

    it('deletes only rows older than the window, in several batches', async () => {
        await seed(5, 'old')
        await seed(2, 'recent')
        await ageRows(31, 'old')
        await ageRows(29, 'recent')

        expect(await pruneAuditLog(pool, { retentionDays: 30, batchSize: 2, deleteUnexported: true })).toBe(5)
        const left = await pool.query('SELECT operation FROM audit_log')
        expect(left.rows.map((row) => row.operation)).toEqual(['recent', 'recent'])
    })

    it('keeps old rows that were never exported, and deletes old rows that were', async () => {
        await seed(3, 'old')
        await ageRows(40, 'old')
        await pool.query(
            `UPDATE audit_log SET exported_at = now()
             WHERE id = (SELECT id FROM audit_log ORDER BY id LIMIT 1)`
        )

        expect(await pruneAuditLog(pool, { retentionDays: 30 })).toBe(1)
        expect((await pool.query('SELECT 1 FROM audit_log')).rowCount).toBe(2)
    })

    it('keeps everything when nothing is old enough', async () => {
        await seed(3)
        expect(await pruneAuditLog(pool, { retentionDays: 30 })).toBe(0)
        expect((await pool.query('SELECT 1 FROM audit_log')).rowCount).toBe(3)
    })

    it('skips when another pod holds the lock', async () => {
        await seed(1)
        await ageRows(40, 'resolve')
        const holder = await pool.connect()
        try {
            await holder.query('SELECT pg_advisory_lock($1)', [7_201_002])
            expect(await pruneAuditLog(pool, { retentionDays: 30, deleteUnexported: true })).toBeNull()
            expect((await pool.query('SELECT 1 FROM audit_log')).rowCount).toBe(1)
        } finally {
            await holder.query('SELECT pg_advisory_unlock($1)', [7_201_002])
            holder.release()
        }
    })
})

void DAY_MS
