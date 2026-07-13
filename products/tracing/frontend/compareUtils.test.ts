import { AggregatedSpanRow } from '~/queries/schema/schema-general'

import { buildRows, changeMagnitude, classifyRow, type CompareRow, MIN_BASELINE_COUNT } from './compareUtils'

type CompareRowSides = Pick<CompareRow, 'current' | 'previous'>

const aggRow = (overrides: Partial<AggregatedSpanRow> = {}): AggregatedSpanRow =>
    ({
        service_name: 'web',
        name: 'GET /api',
        count: 100,
        p50_duration_nano: 1_000_000,
        p95_duration_nano: 10_000_000,
        p99_duration_nano: 20_000_000,
        error_count: 0,
        ...overrides,
    }) as AggregatedSpanRow

const row = (
    current: Partial<AggregatedSpanRow> | null,
    previous: Partial<AggregatedSpanRow> | null
): CompareRowSides => ({
    current: current ? aggRow(current) : null,
    previous: previous ? aggRow(previous) : null,
})

describe('compareUtils', () => {
    describe('classifyRow', () => {
        test.each([
            [
                'p95 >20% worse is regressed',
                row({ p95_duration_nano: 13_000_000 }, { p95_duration_nano: 10_000_000 }),
                'regressed',
            ],
            [
                'p95 >20% better is improved',
                row({ p95_duration_nano: 7_000_000 }, { p95_duration_nano: 10_000_000 }),
                'improved',
            ],
            [
                'within the threshold is unchanged',
                row({ p95_duration_nano: 11_000_000 }, { p95_duration_nano: 10_000_000 }),
                'unchanged',
            ],
            ['missing current is gone', row(null, {}), 'gone'],
            ['missing previous is new', row({}, null), 'new'],
            [
                'a large delta on a tiny baseline is noise, not a regression',
                row(
                    { p95_duration_nano: 50_000_000 },
                    { p95_duration_nano: 10_000_000, count: MIN_BASELINE_COUNT - 1 }
                ),
                'unchanged',
            ],
            [
                'a large delta on a tiny current window is noise too',
                row(
                    { p95_duration_nano: 50_000_000, count: MIN_BASELINE_COUNT - 1 },
                    { p95_duration_nano: 10_000_000 }
                ),
                'unchanged',
            ],
            [
                'a zero baseline p95 is unchanged',
                row({ p95_duration_nano: 5_000_000 }, { p95_duration_nano: 0 }),
                'unchanged',
            ],
        ])('%s', (_name, input, expected) => {
            expect(classifyRow(input)).toBe(expected)
        })
    })

    it('changeMagnitude orders new above big movers above small movers above gone under a descending sort', () => {
        const gone = row(null, {})
        const fresh = row({}, null)
        const bigMove = row({ p95_duration_nano: 30_000_000 }, { p95_duration_nano: 10_000_000 })
        const smallMove = row({ p95_duration_nano: 11_000_000 }, { p95_duration_nano: 10_000_000 })

        const sorted = [gone, smallMove, fresh, bigMove].sort((a, b) => changeMagnitude(b) - changeMagnitude(a))
        expect(sorted).toEqual([fresh, bigMove, smallMove, gone])
    })

    it('sparse new rows do not outrank real movers in the change sort', () => {
        const sparseFresh = row({ count: MIN_BASELINE_COUNT - 1 }, null)
        const bigMove = row({ p95_duration_nano: 30_000_000 }, { p95_duration_nano: 10_000_000 })

        expect(changeMagnitude(sparseFresh)).toBeLessThan(changeMagnitude(bigMove))
    })

    it('a null baseline dataset marks every row unchanged instead of new', () => {
        const rows = buildRows([aggRow()], null)
        expect(rows).toHaveLength(1)
        expect(rows[0].status).toBe('unchanged')
    })

    it('buildRows appends vanished rows so fully regressed call sites stay visible', () => {
        const current = [aggRow({ name: 'GET /api' })]
        const previous = [aggRow({ name: 'GET /api' }), aggRow({ name: 'GET /legacy' })]

        const rows = buildRows(current, previous)
        expect(rows).toHaveLength(2)
        expect(rows[1]).toMatchObject({ name: 'GET /legacy', current: null, status: 'gone' })
        expect(rows[0].previous).not.toBeNull()
    })
})
