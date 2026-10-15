import { NodeKind, type TrendsQuery } from '~/queries/schema/schema-general'

import { monitoringChartMarkers, monitoringChartPoints, monitoringChartQuery } from './reportMonitoringChart'

const now = Date.parse('2026-08-29T12:00:00Z')
const query: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
    dateRange: { date_from: '-7d' },
    series: [{ kind: NodeKind.EventsNode, event: 'checkout_failed', properties: [] }],
}

describe('Monitoring chart context', () => {
    it.each([
        [undefined, '2026-08-22T12:00:00.000Z', '2026-09-05T12:00:00.000Z'],
        ['2026-08-27T12:00:00Z', '2026-08-20T12:00:00.000Z', '2026-09-03T12:00:00.000Z'],
        ['2026-08-01T12:00:00Z', '2026-07-25T12:00:00.000Z', '2026-08-29T12:00:00.000Z'],
    ])('shows surrounding activity from %s through now or the future window', (startedAt, from, to) => {
        const result = monitoringChartQuery(query, { referencePeriodMinutes: 10080, startedAt }, now)
        expect(result.dateRange).toEqual({ date_from: from, date_to: to, explicitDate: true })
        expect(result.series).toEqual(query.series)
        expect(query.dateRange).toEqual({ date_from: '-7d' })
    })

    it.each([
        [30, 'minute'],
        [1440, 'hour'],
        [10080, 'day'],
    ] as const)('uses visible buckets for a %s minute reference period', (minutes, interval) => {
        expect(monitoringChartQuery(query, { referencePeriodMinutes: minutes }, now).interval).toBe(interval)
    })

    it('keeps observed zeros and masks future buckets instead of implying success', () => {
        const points = { labels: ['2026-08-28', '2026-08-29', '2026-08-30'], values: [0, 3, 0] }
        expect(monitoringChartPoints(points, now, 'UTC')).toEqual({ labels: points.labels, values: [0, 3, NaN] })
        expect(points.values).toEqual([0, 3, 0])
    })

    it.each([
        ['America/Los_Angeles', ['2026-08-28', '2026-08-29'], '2026-08-29T06:30:00Z'],
        ['America/Los_Angeles', ['2026-08-28 23:00:00', '2026-08-29 00:00:00'], '2026-08-29T06:30:00Z'],
        ['Asia/Tokyo', ['2026-08-29', '2026-08-30'], '2026-08-29T14:30:00Z'],
        ['America/Los_Angeles', ['2026-08-29T06:00:00Z', '2026-08-29T07:00:00Z'], '2026-08-29T06:30:00Z'],
    ])('interprets buckets in %s when hiding future activity and marking now', (timezone, labels, observedAt) => {
        const at = Date.parse(observedAt)
        expect(monitoringChartPoints({ labels, values: [0, 0] }, at, timezone).values).toEqual([0, NaN])
        expect(monitoringChartMarkers(labels, { referencePeriodMinutes: 1440 }, at, timezone)[0].value).toBe(labels[0])
    })

    it.each([
        [undefined, ['Now']],
        ['2026-08-27T12:00:00Z', ['Monitoring start', 'Now']],
        ['2026-08-29T10:00:00Z', ['Monitoring start / now']],
    ])('marks the observation boundaries for %s', (startedAt, labels) => {
        const buckets = ['2026-08-27', '2026-08-28', '2026-08-29', '2026-08-30']
        const markers = monitoringChartMarkers(buckets, { referencePeriodMinutes: 10080, startedAt }, now, 'UTC')
        expect(markers.map((marker) => marker.label)).toEqual(labels)
        expect(markers.at(-1)?.value).toBe('2026-08-29')
        if (markers.length === 2) {
            expect(markers[0].value).toBe('2026-08-27')
        }
    })
})
