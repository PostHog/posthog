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
    it('returns empty series for no rows, so the empty state shows', () => {
        expect(buildDailyChartData([], ['2026-06-01 00:00:00'], 'UTC')).toEqual({
            labels: [],
            calls: [],
            errors: [],
            p50: [],
            p95: [],
            users: [],
            sessions: [],
        })
    })

    // Guards the "sparklines lose their line" regression: with one active day, projecting onto the
    // full window's day keys pads the axis out (counts→0, latency→NaN) so the line still renders.
    it('projects rows onto day bucket keys, padding empty days', () => {
        const rows = [stat({ day: '2026-06-03', calls: 5, errors: 0, p50: 50, p95: 150, users: 1, sessions: 1 })]
        const keys = ['2026-06-01 00:00:00', '2026-06-02 00:00:00', '2026-06-03 00:00:00', '2026-06-04 00:00:00']
        expect(buildDailyChartData(rows, keys, 'UTC')).toEqual({
            labels: keys,
            calls: [0, 0, 5, 0],
            errors: [0, 0, 0, 0],
            p50: [NaN, NaN, 50, NaN],
            p95: [NaN, NaN, 150, NaN],
            users: [0, 0, 1, 0],
            sessions: [0, 0, 1, 0],
        })
    })

    // Sub-day windows bucket by hour: hourly rows must line up with hourly keys, so "12 hours
    // collapses to a single point" can't come back.
    it('lines up hourly rows with hourly bucket keys', () => {
        const rows = [
            stat({ day: '2026-06-03 10:00:00', calls: 12, errors: 2, p50: 80, p95: 200, users: 4, sessions: 5 }),
        ]
        const keys = ['2026-06-03 09:00:00', '2026-06-03 10:00:00', '2026-06-03 11:00:00']
        const data = buildDailyChartData(rows, keys, 'UTC')
        expect(data.calls).toEqual([0, 12, 0])
        expect(data.p95).toEqual([NaN, 200, NaN])
        expect(data.sessions).toEqual([0, 5, 0])
    })
})
