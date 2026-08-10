import type { Pool } from 'pg'
import { describe, expect, it, vi } from 'vitest'

import { UsageRecorder } from '@/usage/recorder.js'

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

    describe('summarize', () => {
        // The property behind safeToRetirePrevious. A deployment reading a key less often
        // than the rolling window must still appear, or one read from an active caller
        // could declare the previous value retirable while that consumer is still on it.
        it('returns last-seen for a deployment with no reads inside the window', async () => {
            const seenAt = new Date('2026-01-01T00:00:00Z')
            const { pool } = fakePool((sql) =>
                sql.includes('integration_secret_last_seen')
                    ? [{ secret_key: KEY, deployment: WORKER, last_seen: seenAt }]
                    : []
            )

            const { reads, lastSeen } = await new UsageRecorder({ pool }).summarize(24)

            expect(reads.size).toBe(0)
            expect(lastSeen.get(`${KEY}|${WORKER}`)).toBe(seenAt.getTime())
        })

        it('window-filters the counts but never the last-seen lookup', async () => {
            const { pool, calls } = fakePool()
            await new UsageRecorder({ pool }).summarize(24)

            const counts = calls.find((c) => c.sql.includes('integration_secret_usage'))
            const seen = calls.find((c) => c.sql.includes('integration_secret_last_seen'))

            expect(counts?.sql).toContain('make_interval')
            expect(seen?.sql).not.toContain('make_interval')
        })
    })

    // A dormant deployment has to keep holding the verdict back however long it has been
    // quiet, so retention must not reach its last-seen row.
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
        expect((await recorder.summarize(24)).reads.size).toBe(0)
    })
})
