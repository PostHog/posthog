import { buildDailyChartData, type DailyToolStat } from './mcpAnalyticsToolDetailLogic'

function stat(overrides: Partial<DailyToolStat> & { day: string }): DailyToolStat {
    return {
        calls: 0,
        errors: 0,
        p50: 0,
        p95: 0,
        users: 0,
        sessions: 0,
        ...overrides,
    }
}

describe('buildDailyChartData', () => {
    it('returns empty series for no rows', () => {
        expect(buildDailyChartData([])).toEqual({
            labels: [],
            calls: [],
            errors: [],
            p50: [],
            p95: [],
            users: [],
            sessions: [],
        })
    })

    it('passes a single day through unchanged', () => {
        const rows = [stat({ day: '2026-06-01', calls: 10, errors: 2, p50: 100, p95: 300, users: 3, sessions: 4 })]
        expect(buildDailyChartData(rows)).toEqual({
            labels: ['2026-06-01'],
            calls: [10],
            errors: [2],
            p50: [100],
            p95: [300],
            users: [3],
            sessions: [4],
        })
    })

    it('gap-fills interior missing days (counts→0, latency→NaN) with a contiguous day axis', () => {
        const rows = [
            stat({ day: '2026-06-01', calls: 10, errors: 1, p50: 100, p95: 200, users: 2, sessions: 3 }),
            stat({ day: '2026-06-03', calls: 5, errors: 0, p50: 50, p95: 150, users: 1, sessions: 1 }),
        ]
        expect(buildDailyChartData(rows)).toEqual({
            labels: ['2026-06-01', '2026-06-02', '2026-06-03'],
            calls: [10, 0, 5],
            errors: [1, 0, 0],
            p50: [100, NaN, 50],
            p95: [200, NaN, 150],
            users: [2, 0, 1],
            sessions: [3, 0, 1],
        })
    })

    // Guards the "sparklines lose their line" regression: with only one active day, an axis that spans
    // just the data would be a single point (no line). A window range pads it out so the line renders.
    it('spans the full window when given a range, padding days without data', () => {
        const rows = [stat({ day: '2026-06-03', calls: 5, errors: 0, p50: 50, p95: 150, users: 1, sessions: 1 })]
        expect(buildDailyChartData(rows, { start: '2026-06-01', end: '2026-06-05' })).toEqual({
            labels: ['2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04', '2026-06-05'],
            calls: [0, 0, 5, 0, 0],
            errors: [0, 0, 0, 0, 0],
            p50: [NaN, NaN, 50, NaN, NaN],
            p95: [NaN, NaN, 150, NaN, NaN],
            users: [0, 0, 1, 0, 0],
            sessions: [0, 0, 1, 0, 0],
        })
    })
})
