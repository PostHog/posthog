/**
 * Pure unit tests for the resilient row parsing that keeps one drifted live
 * spec from poisoning a whole bulk read (the regression that silently stopped
 * the cron sweep fleet-wide). No Postgres — `safeRowToRev` is a pure function.
 */

import { safeRowToRev } from './pg-revision-store'

const baseRow = {
    id: '019e8990-0000-7000-8000-000000000001',
    application_id: '019e8990-0000-7000-8000-0000000000aa',
    parent_revision_id: null,
    created_by_id: null,
    created_at: new Date('2026-06-02T00:00:00.000Z'),
    state: 'live',
    bundle_uri: 's3://x/',
    bundle_sha256: null,
}

describe('safeRowToRev', () => {
    it('parses a valid spec row into a revision', () => {
        const rev = safeRowToRev({ ...baseRow, spec: { model: 'claude-sonnet-4-6' } })
        expect(rev).not.toBeNull()
        expect(rev!.id).toBe(baseRow.id)
        expect(rev!.spec.model).toBe('claude-sonnet-4-6')
    })

    it('returns null (does not throw) for a drifted spec — cron trigger missing the now-required prompt', () => {
        // The exact shape that poisoned the fleet: a cron trigger frozen before
        // `prompt` was required, so the current schema rejects it.
        const rev = safeRowToRev({
            ...baseRow,
            spec: { triggers: [{ type: 'cron', config: { name: 'sweep', schedule: '0 9 * * *', timezone: 'UTC' } }] },
        })
        expect(rev).toBeNull()
    })

    it('a mixed batch keeps the good rows and drops the bad ones', () => {
        const rows = [
            { ...baseRow, id: 'a', spec: { model: 'x' } },
            {
                ...baseRow,
                id: 'b',
                spec: { triggers: [{ type: 'cron', config: { name: 'n', schedule: '* * * * *' } }] },
            },
            { ...baseRow, id: 'c', spec: { model: 'y' } },
        ]
        const kept = rows.map(safeRowToRev).filter((r): r is NonNullable<typeof r> => r !== null)
        expect(kept.map((r) => r.id)).toEqual(['a', 'c'])
    })
})
