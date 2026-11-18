import { OtelMetricTypeEnumApi } from '../generated/api.schemas'
import { coarsePercentileResolution, customBucketSnippet, suggestedBucketEdges } from './metricsPercentileResolution'
import { supportsHistogramQuantile } from './metricsViewerLogic'

const DJANGO_BUCKETS = [0.1, 0.3, 0.9, 2.7, 8.1]

const series = (
    values: (number | null)[],
    bounds: number[] | null = DJANGO_BUCKETS
): { histogram_bounds: number[] | null; points: { time: string; value: number | null }[] } => ({
    histogram_bounds: bounds,
    points: values.map((value, index) => ({ time: `2026-10-23T10:0${index}:00Z`, value })),
})

describe('coarsePercentileResolution', () => {
    it('names the bucket most points fall in when its edges are far apart', () => {
        const resolution = coarsePercentileResolution([series([0.45, 0.5, 0.62, 1.2])])

        expect(resolution).toEqual({ edges: DJANGO_BUCKETS, lower: 0.3, upper: 0.9, share: 0.75 })
    })

    it('counts a point below the first edge as the bucket from zero', () => {
        expect(coarsePercentileResolution([series([0.05, 0.06])])).toMatchObject({ lower: 0, upper: 0.1 })
    })

    it('counts a point above the last edge as the open overflow bucket', () => {
        expect(coarsePercentileResolution([series([9, 9.5])])).toMatchObject({ lower: 8.1, upper: Infinity })
    })

    it('stays quiet for fine buckets such as an exponential histogram', () => {
        const fine = Array.from({ length: 40 }, (_, index) => 0.1 * 1.09 ** index)

        expect(coarsePercentileResolution([series([0.45, 0.5, 0.62], fine)])).toBeNull()
    })

    it('stays quiet without histogram bounds or values', () => {
        expect(coarsePercentileResolution([series([0.5], null)])).toBeNull()
        expect(coarsePercentileResolution([series([null, null])])).toBeNull()
        expect(coarsePercentileResolution([])).toBeNull()
    })

    it('finds the right bucket by binary search when there are many edges', () => {
        // A handful of edges can't exercise a binary search's midpoint handling; this puts the
        // target bucket in the middle of 1000 edges, where an off-by-one would show up.
        const edges = [
            ...Array.from({ length: 500 }, (_, index) => index + 1), // 1..500
            2000, // the busiest bucket, (500, 2000]
            ...Array.from({ length: 499 }, (_, index) => index + 2001), // 2001..2499
        ]

        expect(coarsePercentileResolution([series([1000, 1000, 1000], edges)])).toMatchObject({
            lower: 500,
            upper: 2000,
            share: 1,
        })
    })
})

describe('suggestedBucketEdges', () => {
    it('spans the plotted values with edges that grow by a fixed step', () => {
        const edges = suggestedBucketEdges([0.45, 1.2])

        expect(edges[0]).toBeLessThanOrEqual(0.45 / 2)
        expect(edges[edges.length - 1]).toBeGreaterThanOrEqual(1.2 * 2)
        expect(edges.length).toBeLessThanOrEqual(12)
        edges.slice(1).forEach((edge, index) => expect(edge / edges[index]).toBeLessThanOrEqual(1.6))
    })

    it('handles more values than a function call can take as arguments', () => {
        const values = Array.from({ length: 1_000_000 }, (_, index) => 0.1 + (index % 100) / 100)

        expect(() => suggestedBucketEdges(values)).not.toThrow()
    })

    it('returns no edges without positive values', () => {
        expect(suggestedBucketEdges([])).toEqual([])
        expect(suggestedBucketEdges([0])).toEqual([])
    })
})

describe('customBucketSnippet', () => {
    it('writes ingested names as string literals that cannot break out of the snippet', () => {
        const unit = 's", description=__import__("os").system("id"), x="'

        const snippet = customBucketSnippet('http.duration', unit, [0.1, 0.2])

        expect(snippet).toContain(`unit=${JSON.stringify(unit)},`)
        expect(snippet).not.toContain('description=__import__("os")')
        expect(snippet).toContain('explicit_bucket_boundaries_advisory=[0.1, 0.2]')
        expect(snippet).toContain('buckets=[0.1, 0.2, float("inf")]')
    })
})

describe('supportsHistogramQuantile', () => {
    it('offers percentiles for explicit and exponential histograms', () => {
        expect(supportsHistogramQuantile(OtelMetricTypeEnumApi.Histogram)).toBe(true)
        expect(supportsHistogramQuantile(OtelMetricTypeEnumApi.ExponentialHistogram)).toBe(true)
        expect(supportsHistogramQuantile(OtelMetricTypeEnumApi.Gauge)).toBe(false)
    })
})
