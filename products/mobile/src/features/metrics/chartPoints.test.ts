import { seriesChartPoints, snapshotChartPoints } from './chartPoints'

describe('chart points', () => {
    test('reads trends bucket labels as local wall-clock time', () => {
        const points = seriesChartPoints({
            interval: 'day',
            points: [
                { at: '2026-10-13', value: 1 },
                { at: '2026-10-13 14:00:00', value: 2 },
                { at: 'not a date', value: 3 },
            ],
        })
        expect(points).toEqual([
            { at: new Date(2026, 9, 13).getTime(), value: 1 },
            { at: new Date(2026, 9, 13, 14).getTime(), value: 2 },
        ])
    })

    test('places the undated snapshot buckets one interval apart, ending when it was measured', () => {
        const measured = new Date(2026, 9, 13, 9, 30)
        const points = snapshotChartPoints(
            { value: 6, at: measured.toISOString(), series: [1, 2, 3] },
            'day',
            new Date(2026, 0, 1)
        )
        expect(points).toEqual([
            { at: new Date(2026, 9, 11, 9, 30).getTime(), value: 1 },
            { at: new Date(2026, 9, 12, 9, 30).getTime(), value: 2 },
            { at: measured.getTime(), value: 3 },
        ])
    })
})
