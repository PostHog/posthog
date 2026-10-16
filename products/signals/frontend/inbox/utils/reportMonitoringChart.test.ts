import { NodeKind, type TrendsQuery } from '~/queries/schema/schema-general'

import { reportMetricsFixture } from '../__mocks__/reportMetricMocks'
import {
    monitoringChartMarkers,
    monitoringChartPoints,
    monitoringChartQuery,
    monitoringChartTargetLines,
} from './reportMonitoringChart'

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
    const targetMetric = {
        ...reportMetricsFixture[1],
        goal_value: 70,
        goal_direction: 'at_most' as const,
        query: {
            kind: NodeKind.InsightVizNode,
            source: { ...query, series: [{ kind: NodeKind.EventsNode, event: 'checkout_failed', math: 'total' }] },
        },
    }
    const targetOptions = {
        metric: targetMetric,
        monitoring: { referencePeriodMinutes: 10080, thresholdScaling: 'linear' as const },
        interval: 'day' as const,
        labels: ['2026-08-27', '2026-08-28', '2026-08-29'],
        timezone: 'UTC',
    }

    it.each([
        [10080, 'day', 70, 10, 'Goal: ≤10/day'],
        [1440, 'hour', 24, 1, 'Goal: ≤1/hour'],
        [60, 'minute', 30, 0.5, 'Goal: ≤0.5/minute'],
    ] as const)('normalizes a %s minute additive target to full %s buckets', (period, interval, goal, value, label) => {
        expect(
            monitoringChartTargetLines({
                ...targetOptions,
                metric: { ...targetMetric, goal_value: goal },
                monitoring: { ...targetOptions.monitoring, referencePeriodMinutes: period },
                interval,
            })
        ).toEqual([expect.objectContaining({ value, label })])
    })

    it('draws both inclusive bounds in the chart bucket units', () => {
        expect(monitoringChartTargetLines({ ...targetOptions, bounds: { lower: 70, upper: 140 } })).toEqual([
            expect.objectContaining({ value: 10, label: 'Goal: ≥10/day' }),
            expect.objectContaining({ value: 20, label: 'Goal: ≤20/day' }),
        ])
    })

    it.each([
        ['avg', 'fixed', true],
        ['p95', 'fixed', true],
        ['total', 'fixed', false],
        ['sum', 'fixed', false],
        ['dau', 'fixed', false],
        ['hogql', 'fixed', false],
        ['avg', 'linear', false],
        [null, 'linear', true],
    ] as const)('matches %s aggregation to a %s reference', (math, thresholdScaling, visible) => {
        const result = monitoringChartTargetLines({
            ...targetOptions,
            monitoring: { ...targetOptions.monitoring, thresholdScaling },
            metric: {
                ...targetMetric,
                kind: 'custom',
                value_format: 'number',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: { ...query, series: [{ kind: NodeKind.EventsNode, event: 'checkout_failed', math }] },
                },
            },
        })
        expect(result).toHaveLength(visible ? 1 : 0)
        if (visible) {
            expect(result[0].value).toBe(thresholdScaling === 'linear' ? 10 : 70)
        }
    })

    it('keeps a fixed percentage target on the rate scale without inferring it from formatting', () => {
        const metric = { ...reportMetricsFixture[2], goal_value: 0.4, goal_direction: 'at_least' as const }
        const options = {
            ...targetOptions,
            metric,
            monitoring: { ...targetOptions.monitoring, thresholdScaling: 'fixed' as const },
        }
        expect(monitoringChartTargetLines(options)).toEqual([
            expect.objectContaining({ value: 0.4, label: 'Target: ≥40%' }),
        ])
        expect(monitoringChartTargetLines({ ...options, metric: { ...metric, kind: 'custom' } })).toEqual([])
    })

    it('omits a horizontal count reference when daylight-saving days have unequal durations', () => {
        const options = { ...targetOptions, labels: ['2026-11-01', '2026-11-02'] }
        expect(monitoringChartTargetLines({ ...options, timezone: 'America/Los_Angeles' })).toEqual([])
        expect(monitoringChartTargetLines(options)[0].value).toBe(10)
    })

    it('does not present a formula count or a missing definition as a bucket target', () => {
        expect(monitoringChartTargetLines({ ...targetOptions, monitoring: { referencePeriodMinutes: 10080 } })).toEqual(
            []
        )
        expect(
            monitoringChartTargetLines({
                ...targetOptions,
                metric: {
                    ...targetMetric,
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: { ...query, trendsFilter: { formula: 'A * 2' } },
                    },
                },
            })
        ).toEqual([])
    })
})
