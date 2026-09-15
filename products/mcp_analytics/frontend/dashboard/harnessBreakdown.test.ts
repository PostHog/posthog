import { type HarnessRow } from '../mcpDashboardOverviewLogic'
import { summarizeHarnessBreakdown } from './harnessBreakdown'

function row(category: string, total_calls: number, errors = 0): HarnessRow {
    return {
        category,
        total_calls,
        errors,
        error_rate_pct: total_calls ? (errors / total_calls) * 100 : 0,
        sessions: 1,
    }
}

describe('harness breakdown', () => {
    it('keeps the top six named harnesses and combines the tail with unrecognized clients without losing calls', () => {
        const rows = [
            row('Other', 100, 20),
            ...Array.from({ length: 8 }, (_, i) => row(`Example ${i}`, 80 - i * 10, 1)),
        ]
        const summary = summarizeHarnessBreakdown(rows)
        expect(summary.totalCalls).toBe(460)
        expect(summary.chartRows.map((r) => r.category)).toEqual([
            'Example 0',
            'Example 1',
            'Example 2',
            'Example 3',
            'Example 4',
            'Example 5',
            'Other',
        ])
        expect(summary.chartRows.at(-1)).toMatchObject({ total_calls: 130, errors: 22, sessions: null })
        expect(summary.chartRows.at(-1)?.error_rate_pct).toBeCloseTo((22 / 130) * 100)
        expect(summary.chartRows.reduce((sum, r) => sum + r.total_calls, 0)).toBe(460)
        expect(summary.allRows).toHaveLength(9)
        expect(rows[0].category).toBe('Other')
    })

    it.each([
        { rows: [], categories: [], total: 0 },
        { rows: [row('Example', 10)], categories: ['Example'], total: 10 },
        { rows: [row('Other', 15)], categories: ['Other'], total: 15 },
        { rows: [row('Example', 0), row('Other', 0)], categories: ['Example', 'Other'], total: 0 },
    ])('preserves small and empty breakdowns: $categories', ({ rows, categories, total }) => {
        const summary = summarizeHarnessBreakdown(rows)
        expect(summary.chartRows.map((r) => r.category)).toEqual(categories)
        expect(summary.totalCalls).toBe(total)
        expect(summary.chartRows.every((r) => Number.isFinite(r.error_rate_pct))).toBe(true)
    })
})
