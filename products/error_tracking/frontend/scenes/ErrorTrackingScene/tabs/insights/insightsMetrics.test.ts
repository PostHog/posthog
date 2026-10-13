import { buildMetrics, crashFreeRate, parseComparisonTotals, parseSummaryBuckets } from './insightsMetrics'

describe('insightsMetrics', () => {
    describe('parseComparisonTotals', () => {
        // The query interleaves each measure with its previous-period twin. Reordering the SELECT
        // without reordering this would silently show one metric's value against another's baseline.
        it('reads the interleaved current and previous columns', () => {
            const totals = parseComparisonTotals([[100, 50, 9, 4, 80, 70, 20, 10, 3, 2]])

            expect(totals.current).toEqual({
                exceptions: 100,
                affectedUsers: 9,
                sessions: 80,
                crashSessions: 20,
                releases: 3,
            })
            expect(totals.previous).toEqual({
                exceptions: 50,
                affectedUsers: 4,
                sessions: 70,
                crashSessions: 10,
                releases: 2,
            })
        })

        it('reads an empty response as a period with no activity', () => {
            expect(parseComparisonTotals([]).current.exceptions).toBe(0)
        })
    })

    describe('crashFreeRate', () => {
        it.each([
            [100, 20, 80],
            [100, 0, 100],
        ])('%s sessions with %s crashing is %s%% crash-free', (sessions, crashSessions, expected) => {
            expect(crashFreeRate({ sessions, crashSessions })).toBe(expected)
        })

        // Reporting 100% for a period with no traffic claims a clean period on no evidence, and hands
        // the comparison a baseline that makes every delta read as no change.
        it('has no rate for a period with no sessions', () => {
            expect(crashFreeRate({ sessions: 0, crashSessions: 0 })).toBeNull()
        })
    })

    describe('buildMetrics', () => {
        const bucketKeys = ['2026-06-01 00:00:00', '2026-06-02 00:00:00', '2026-06-03 00:00:00']
        const totals = parseComparisonTotals([[30, 15, 6, 4, 100, 100, 12, 8, 2, 1]])

        // A quiet bucket returns no row at all. Falling back to the returned rows would draw a
        // sparkline shorter than the chart beside it, with the gap closed up rather than shown.
        it('zero-fills the buckets the query returned no row for', () => {
            const buckets = parseSummaryBuckets([['2026-06-03 00:00:00', 20, 5, 60, 8, 2]])

            const metrics = buildMetrics(totals, buckets, bucketKeys, 'day')

            expect(metrics.exceptions.sparkline).toEqual([0, 0, 20])
            expect(metrics.exceptions.sparklineLabels).toEqual(['Jun 1', 'Jun 2', 'Jun 3'])
            expect(metrics.crashFreeRate.sparkline).toEqual([100, 100, (52 / 60) * 100])
        })

        it('compares each headline against the previous period', () => {
            const metrics = buildMetrics(totals, [], bucketKeys, 'day')

            expect(metrics.exceptions).toMatchObject({ value: 30, previousValue: 15, deltaPct: 100 })
            expect(metrics.releases).toMatchObject({ value: 2, previousValue: 1, deltaPct: 100 })
            expect(metrics.crashFreeRate).toMatchObject({ value: 88, previousValue: 92 })
        })

        // Without a baseline the tile has to show no pill: a jump from nothing is not a percentage.
        it('reports no change when the previous period was empty', () => {
            const fromNothing = parseComparisonTotals([[30, 0, 0, 0, 0, 0, 0, 0, 0, 0]])

            expect(buildMetrics(fromNothing, [], bucketKeys, 'day').exceptions.deltaPct).toBeNull()
        })
    })
})
