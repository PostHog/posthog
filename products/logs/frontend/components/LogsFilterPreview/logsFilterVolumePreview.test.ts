import { LogsFilterPreviewPoint, buildSparklineSeries, formatBytes } from './logsFilterVolumePreview'

const point = (time: string, service: string, count: number, bytes?: number): LogsFilterPreviewPoint => ({
    time,
    service,
    count,
    bytes_uncompressed: bytes,
})

const T1 = '2026-08-04T11:00:00Z'
const T2 = '2026-08-04T11:30:00Z'

describe('buildSparklineSeries', () => {
    it('stacks one series per service in bucket order', () => {
        const data = buildSparklineSeries([point(T1, 'api', 3), point(T1, 'worker', 1), point(T2, 'api', 5)], 'count')

        expect(data.series).toEqual([
            expect.objectContaining({ name: 'api', values: [3, 5] }),
            expect.objectContaining({ name: 'worker', values: [1, 0] }),
        ])
        expect(data.total).toEqual(9)
        expect(data.chartMax).toEqual(5)
        expect(data.bucketSeconds).toEqual(1800)
        expect(data.bucketCount).toEqual(2)
        expect(data.firstBucketTime).toEqual(T1)
    })

    it('rolls the long tail past the top 10 into one Others series, preserving the total', () => {
        const points = Array.from({ length: 13 }, (_, i) => point(T1, `svc-${i}`, 13 - i))
        const data = buildSparklineSeries(points, 'count')

        expect(data.series).toHaveLength(11)
        expect(data.series[10].name).toEqual('Others (3 services)')
        // svc-10..svc-12 rank last, contributing 3 + 2 + 1.
        expect(data.series[10].values).toEqual([6])
        expect(data.truncatedServiceCount).toEqual(3)
        expect(data.series.reduce((sum, s) => sum + s.values[0], 0)).toEqual(data.total)
    })

    it('reads bytes_uncompressed for the bytes metric and treats a missing value as zero', () => {
        const points = [point(T1, 'api', 100, 2048), point(T2, 'api', 100)]

        expect(buildSparklineSeries(points, 'bytes').total).toEqual(2048)
        expect(buildSparklineSeries(points, 'count').total).toEqual(200)
    })

    it.each(['__proto__', 'constructor', 'toString'])(
        'handles an ingested service name of %p without crashing',
        (service) => {
            // Service names come from ingested logs. With a plain-object accumulator these keys
            // resolve to inherited values instead of a bucket and throw on `.set`.
            const data = buildSparklineSeries([point(T1, service, 2), point(T2, service, 3)], 'count')

            expect(data.series).toEqual([expect.objectContaining({ name: service, values: [2, 3] })])
            expect(data.total).toEqual(5)
        }
    )

    it('labels a blank service as unknown', () => {
        expect(buildSparklineSeries([point(T1, '', 1)], 'count').series[0].name).toEqual('unknown')
    })

    it('returns an empty shape for no data', () => {
        for (const points of [null, []]) {
            const data = buildSparklineSeries(points, 'bytes')
            expect(data.series).toEqual([])
            expect(data.total).toEqual(0)
            expect(data.bucketCount).toEqual(0)
            expect(data.firstBucketTime).toBeNull()
        }
    })
})

describe('formatBytes', () => {
    it('scales through to PB so multi-week retained totals stay readable', () => {
        expect(formatBytes(512)).toEqual('512 B')
        expect(formatBytes(2048)).toEqual('2.0 KB')
        expect(formatBytes(5_500_000)).toEqual('5.5 MB')
        expect(formatBytes(15_000_000_000)).toEqual('15.00 GB')
        expect(formatBytes(450_000_000_000)).toEqual('450.00 GB')
        expect(formatBytes(13_500_000_000_000)).toEqual('13.50 TB')
        expect(formatBytes(2_500_000_000_000_000)).toEqual('2.50 PB')
    })
})
