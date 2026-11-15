import { dayjs } from 'lib/dayjs'

import type { MetricsQueryClause } from '~/queries/schema/schema-general'

import type { MetricsChartSeries } from '../components/metricsSeries'
import {
    extrapolatePartialValue,
    isExtrapolatable,
    type MetricsPartialBucketQuery,
    partialBucketFraction,
} from './metricsPartialBucket'

const BUCKETS = ['2026-08-01T10:00:00Z', '2026-08-01T11:00:00Z', '2026-08-01T12:00:00Z']

const series = (clause: string): MetricsChartSeries => ({ labels: {}, points: [], clause })
const clause = (name: string, extra: Partial<MetricsQueryClause> = {}): MetricsQueryClause => ({
    name,
    metricName: 'http.requests',
    ...extra,
})
const query = (
    clauses: MetricsQueryClause[],
    extra: Partial<MetricsPartialBucketQuery> = {}
): MetricsPartialBucketQuery => ({
    clauses,
    ...extra,
})

describe('partialBucketFraction', () => {
    const hourly = query([], { interval: 'hour' })

    it.each([
        ['quarter into the last bucket', 'hour', '1h', '2026-08-01T12:15:00Z', 0.25],
        ['last bucket complete', 'hour', '1h', '2026-08-01T13:00:00Z', null],
        ['now before the last bucket', 'hour', '1h', '2026-08-01T11:30:00Z', null],
        ['hourly variable', '$window', '1h', '2026-08-01T12:15:00Z', 0.25],
        ['braced variable', '${window}', '15m', '2026-08-01T12:05:00Z', 1 / 3],
        ['formatted variable', '[[window:raw]]', '1m', '2026-08-01T12:00:15Z', 0.25],
        ['variable bucket complete', '$window', '1h', '2026-08-01T13:00:00Z', null],
    ])('%s', (_, interval, duration, now, expected) => {
        const q = query([], { interval, variables: { window: { values: [duration] } } })
        expect(partialBucketFraction(BUCKETS, q, 'UTC', dayjs(now))).toBe(expected)
    })

    it('uses the query interval, not the spacing of sparse buckets', () => {
        const sparse = ['2026-08-01T10:00:00Z', '2026-08-01T12:00:00Z']
        expect(partialBucketFraction(sparse, hourly, 'UTC', dayjs('2026-08-01T13:00:00Z'))).toBeNull()
        expect(partialBucketFraction(sparse, hourly, 'UTC', dayjs('2026-08-01T12:30:00Z'))).toBe(0.5)
    })

    it('picks the interval from the range when the query does not set one', () => {
        const fifteenMinutes = ['2026-08-01T11:45:00Z', '2026-08-01T12:00:00Z']
        const auto = query([], { dateRange: { date_from: '2026-08-01T00:00:00Z' } })
        expect(partialBucketFraction(fifteenMinutes, auto, 'UTC', dayjs('2026-08-01T12:05:00Z'))).toBeCloseTo(1 / 3)
    })

    it('treats a relative range start as a rolling window, like the backend', () => {
        const halfHours = ['2026-08-01T11:30:00Z', '2026-08-01T12:00:00Z']
        const lastDay = query([], { dateRange: { date_from: '-1d' } })
        expect(partialBucketFraction(halfHours, lastDay, 'UTC', dayjs('2026-08-01T12:05:00Z'))).toBeCloseTo(1 / 6)
    })

    it.each([
        ['a fixed range end', query([], { interval: 'hour', dateRange: { date_to: '2026-08-01T12:15:00Z' } })],
        ['buckets closer than the query interval', query([], { interval: 'day' })],
        ['missing interval variable', query([], { interval: '$window' })],
        ['empty interval selection', query([], { interval: '$window', variables: { window: { values: [] } } })],
        [
            'multiple interval selections',
            query([], { interval: '$window', variables: { window: { values: ['1h', '6h'] } } }),
        ],
        [
            'All interval selection',
            query([], { interval: '$window', variables: { window: { values: ['1h'], all: true } } }),
        ],
        [
            'invalid interval duration',
            query([], { interval: '$window', variables: { window: { values: ['invalid'] } } }),
        ],
        ['no query', undefined],
    ])('stays solid for %s', (_, q) => {
        expect(partialBucketFraction(BUCKETS, q, 'UTC', dayjs('2026-08-01T12:15:00Z'))).toBeNull()
    })
})

describe('isExtrapolatable', () => {
    it.each([
        ['rate range function', clause('a', { rangeFunction: 'rate', aggregation: 'sum' }), true],
        ['increase aggregation', clause('a', { aggregation: 'increase' }), true],
        ['gauge average', clause('a', { aggregation: 'avg' }), false],
        ['sum of latest values', clause('a', { aggregation: 'sum' }), false],
        ['count of series reporting a rate', clause('a', { rangeFunction: 'rate', aggregation: 'count' }), false],
    ])('%s', (_, c, expected) => {
        expect(isExtrapolatable(series('a'), query([c]))).toBe(expected)
    })

    it.each([
        ['a + b', true],
        ['(a - b) + a', true],
        ['a / b', false],
        ['a * 100', false],
        ['a + 100', false],
    ])('formula %s', (formula, expected) => {
        const counters = [clause('a', { rangeFunction: 'increase' }), clause('b', { rangeFunction: 'increase' })]
        expect(isExtrapolatable(series('formula'), query(counters, { formula }))).toBe(expected)
    })

    it('ignores clauses the formula does not use', () => {
        const clauses = [
            clause('a', { rangeFunction: 'increase' }),
            clause('b', { rangeFunction: 'increase' }),
            clause('c', { aggregation: 'avg' }),
        ]
        expect(isExtrapolatable(series('formula'), query(clauses, { formula: 'a + b' }))).toBe(true)
    })

    it('does not extrapolate a formula over a gauge', () => {
        const clauses = [clause('a', { rangeFunction: 'increase' }), clause('b', { aggregation: 'avg' })]
        expect(isExtrapolatable(series('formula'), query(clauses, { formula: 'a + b' }))).toBe(false)
    })

    it.each(['promql', 'sql'] as const)('does not extrapolate %s queries', (language) => {
        expect(isExtrapolatable(series('a'), query([clause('a', { rangeFunction: 'rate' })], { language }))).toBe(false)
    })

    it('does not extrapolate without a query', () => {
        expect(isExtrapolatable(series('a'), undefined)).toBe(false)
    })
})

describe('extrapolatePartialValue', () => {
    it('scales the value to the full bucket', () => {
        expect(extrapolatePartialValue(25, 0.25)).toBe(100)
    })

    it('keeps the real value early in the bucket', () => {
        expect(extrapolatePartialValue(2, 0.05)).toBe(2)
    })
})
