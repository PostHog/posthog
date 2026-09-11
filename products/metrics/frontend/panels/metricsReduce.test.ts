import type { MetricsQueryPoint, MetricsQuerySeries } from '~/queries/schema/schema-general'

import { flattenSeriesRows, reduceSeries } from './metricsReduce'

// The schema types `value` as `number`, but the backend sends `null` for a
// non-representable bucket (the facade's `MetricPoint.value` is `float | None`).
// PR for null gaps widens the schema type; until then the tests cast to the
// declared shape while exercising the null path the runtime actually produces.
const points = (values: (number | null)[]): MetricsQueryPoint[] =>
    values.map((value, i) => ({ time: `2026-09-10T00:0${i}:00Z`, value }) as MetricsQueryPoint)

describe('reduceSeries', () => {
    it('returns null for an empty series', () => {
        expect(reduceSeries([], 'last')).toBeNull()
        expect(reduceSeries([], 'mean')).toBeNull()
    })

    it('returns null when every point is null', () => {
        expect(reduceSeries(points([null, null, null]), 'last')).toBeNull()
        expect(reduceSeries(points([null, null]), 'sum')).toBeNull()
    })

    it('last ignores trailing nulls', () => {
        expect(reduceSeries(points([1, 2, null]), 'last')).toBe(2)
    })

    it('mean skips nulls rather than counting them as zero', () => {
        expect(reduceSeries(points([1, null, 3]), 'mean')).toBe(2)
    })

    it('min and max ignore nulls', () => {
        expect(reduceSeries(points([5, null, 2, 8]), 'min')).toBe(2)
        expect(reduceSeries(points([5, null, 2, 8]), 'max')).toBe(8)
    })

    it('sum ignores nulls', () => {
        expect(reduceSeries(points([1, null, 2, 3]), 'sum')).toBe(6)
    })

    it('delta is last non-null minus first non-null', () => {
        expect(reduceSeries(points([null, 2, 5, 9, null]), 'delta')).toBe(7)
    })

    it('delta of a single point is zero', () => {
        expect(reduceSeries(points([null, 4, null]), 'delta')).toBe(0)
    })
})

describe('flattenSeriesRows', () => {
    const series = (
        labels: Record<string, string>,
        values: (number | null)[],
        metricName?: string
    ): MetricsQuerySeries => ({
        labels,
        points: points(values),
        metricName,
    })

    it('flattens labels into the row and computes each reducer', () => {
        const rows = flattenSeriesRows([series({ service: 'api' }, [1, 2, 3], 'cpu')], ['last', 'max', 'sum'])
        expect(rows).toHaveLength(1)
        expect(rows[0].labels).toEqual({ service: 'api' })
        expect(rows[0].metricName).toBe('cpu')
        expect(rows[0].values).toEqual({ last: 3, max: 3, sum: 6 })
    })

    it('keeps a null value for a reducer with no data', () => {
        const rows = flattenSeriesRows([series({}, [null])], ['last'])
        expect(rows[0].values.last).toBeNull()
    })

    it('handles zero label keys (ungrouped)', () => {
        const rows = flattenSeriesRows([series({}, [7])], ['last'])
        expect(rows[0].labels).toEqual({})
    })

    it('preserves the source series for drill-down', () => {
        const s = series({ pod: 'p1' }, [1, 2])
        expect(flattenSeriesRows([s], ['last'])[0].series).toBe(s)
    })

    it('produces one row per series', () => {
        const rows = flattenSeriesRows([series({ a: '1' }, [1]), series({ a: '2' }, [2])], ['last'])
        expect(rows).toHaveLength(2)
    })
})
