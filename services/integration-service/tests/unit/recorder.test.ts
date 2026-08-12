import type { Pool } from 'pg'
import { describe, expect, it, vi } from 'vitest'

import { UsageRecorder } from '@/usage/recorder'

interface Call {
    sql: string
    params: unknown[]
}

/** A Pool stand-in that records the SQL it is given and answers from canned rows. */
function fakePool(rows: (sql: string) => unknown[] = () => []): { pool: Pool; calls: Call[] } {
    const calls: Call[] = []
    const pool = {
        query: (sql: string, params: unknown[] = []) => {
            calls.push({ sql, params })
            return Promise.resolve({ rows: rows(sql) })
        },
    }
    return { pool: pool as unknown as Pool, calls }
}

const KEY = 'HUBSPOT_APP_CLIENT_SECRET'
const WORKER = 'temporal-worker-data-warehouse'

describe('usage recorder', () => {
    it('writes nothing until it is flushed', async () => {
        const { pool, calls } = fakePool()
        const recorder = new UsageRecorder({ pool })

        recorder.record(WORKER, [KEY])
        expect(calls).toHaveLength(0)

        await recorder.flush()
        expect(calls.length).toBeGreaterThan(0)
    })

    it('collapses repeated reads of one key into a single counted row', async () => {
        const { pool, calls } = fakePool()
        const recorder = new UsageRecorder({ pool, now: () => 1_700_000_000_000 })

        for (let i = 0; i < 5; i++) {
            recorder.record(WORKER, [KEY])
        }
        await recorder.flush()

        const counts = calls.find((c) => c.sql.includes('integration_secret_usage'))
        expect(counts?.params[0]).toEqual([KEY])
        expect(counts?.params[3]).toEqual([5])
    })

    // Guards the typed pending entries: key and deployment reach the write as the exact
    // strings recorded, not whatever a string parse of a composite id yields.
    it('flushes the exact key and deployment even when a name contains the separator', async () => {
        const { pool, calls } = fakePool()
        const recorder = new UsageRecorder({ pool })

        recorder.record('oddly|named-deployment', [KEY])
        await recorder.flush()

        const counts = calls.find((c) => c.sql.includes('integration_secret_usage'))
        expect(counts?.params[0]).toEqual([KEY])
        expect(counts?.params[1]).toEqual(['oddly|named-deployment'])
    })

    it('records last-seen separately from the bucketed counts', async () => {
        const { pool, calls } = fakePool()
        const recorder = new UsageRecorder({ pool })

        recorder.record(WORKER, [KEY])
        await recorder.flush()

        expect(calls.some((c) => c.sql.includes('integration_secret_last_seen'))).toBe(true)
    })

    it('does not re-queue a failed batch, so a broken database cannot grow the buffer', async () => {
        const pool = { query: vi.fn().mockRejectedValue(new Error('down')) } as unknown as Pool
        const recorder = new UsageRecorder({ pool })

        recorder.record(WORKER, [KEY])
        await recorder.flush()
        await recorder.flush()

        // Two calls for the first flush's two statements, none for the second.
        expect((pool.query as ReturnType<typeof vi.fn>).mock.calls.length).toBeLessThanOrEqual(2)
    })

    // A dormant deployment has to keep holding the retirement decision back however long it
    // has been quiet, so retention must not reach its last-seen row.
    it('prunes only the bucketed counts, never last-seen', async () => {
        const { pool, calls } = fakePool()
        await new UsageRecorder({ pool }).prune(9)

        expect(calls).toHaveLength(1)
        expect(calls[0]?.sql).toContain('DELETE FROM integration_secret_usage')
        expect(calls[0]?.sql).not.toContain('integration_secret_last_seen')
    })

    it('does nothing at all without a database', async () => {
        const recorder = new UsageRecorder({})
        recorder.record(WORKER, [KEY])

        await expect(recorder.flush()).resolves.toBeUndefined()
        await expect(recorder.prune(9)).resolves.toBeUndefined()
    })
})
