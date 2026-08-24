import fs from 'fs'
import path from 'path'

import { OTHER_BREAKDOWN_LABEL, OTHER_BREAKDOWN_VALUE } from 'products/logs/frontend/sparklineOtherBreakdown'

import {
    LogsFilterPreviewPoint,
    OTHER_BREAKDOWN_COLOR,
    TOP_SERVICES_LIMIT,
    buildSparklineSeries,
    formatBytes,
} from './logsFilterVolumePreview'

const readSource = (relativePath: string): string =>
    fs.readFileSync(path.join(__dirname, '../../../..', relativePath), 'utf-8')

const point = (time: string, service: string, count: number, bytes?: number): LogsFilterPreviewPoint => ({
    time,
    service,
    count,
    bytes_uncompressed: bytes,
})

const T1 = '2026-08-04T11:00:00Z'
const T2 = '2026-08-04T11:30:00Z'

describe('constants shared with the backend', () => {
    it('agrees with the backend on how many breakdown values survive the rollup', () => {
        // The header text promises "top N" and the backend decides N, so drift would make the UI lie.
        const runner = readSource('logs/backend/sparkline_query_runner.py')
        const match = runner.match(/^SPARKLINE_TOP_BREAKDOWN_VALUES = (\d+)$/m)
        expect(match).not.toBeNull()
        expect(Number(match![1])).toEqual(TOP_SERVICES_LIMIT)
    })

    it('uses the same collapsed-bucket sentinel the backend emits', () => {
        // A mismatch would leave the sentinel unrecognised and drawn as a service literally named
        // "$$_posthog_breakdown_other_$$".
        const breakdowns = readSource('../posthog/hogql_queries/insights/utils/breakdowns.py')
        const match = breakdowns.match(/^BREAKDOWN_OTHER_STRING_LABEL = "(.+)"$/m)
        expect(match).not.toBeNull()
        expect(match![1]).toEqual(OTHER_BREAKDOWN_VALUE)
    })
})

describe('buildSparklineSeries', () => {
    it('stacks one series per service in bucket order', () => {
        const data = buildSparklineSeries([point(T1, 'api', 3), point(T1, 'worker', 1), point(T2, 'api', 5)], 'count')

        expect(data.series).toEqual([
            expect.objectContaining({ label: 'api', data: [3, 5] }),
            expect.objectContaining({ label: 'worker', data: [1, 0] }),
        ])
        // Raw bucket times, not display strings: the chart's time axis needs unique ISO labels to
        // format ticks and the tooltip header itself.
        expect(data.labels).toEqual([T1, T2])
        expect(data.total).toEqual(9)
        expect(data.chartMax).toEqual(5)
        expect(data.bucketSeconds).toEqual(1800)
        expect(data.bucketCount).toEqual(2)
        expect(data.firstBucketTime).toEqual(T1)
    })

    it('keeps every returned series rather than slicing — the backend already folded the tail', () => {
        // Slicing here again would take the backend's collapsed row and re-collapse it, labelling an
        // aggregate of many services as though it were one more service.
        const points = Array.from({ length: 13 }, (_, i) => point(T1, `svc-${i}`, 13 - i))
        const data = buildSparklineSeries(points, 'count')

        expect(data.series).toHaveLength(13)
        expect(data.series.map((s) => s.label)).toEqual(Array.from({ length: 13 }, (_, i) => `svc-${i}`))
        expect(data.series.reduce((sum, s) => sum + s.data[0], 0)).toEqual(data.total)
    })

    it('labels the collapsed bucket and pins it last even when it outweighs every service', () => {
        const points = [
            point(T1, 'api', 5),
            point(T2, 'api', 5),
            point(T1, OTHER_BREAKDOWN_VALUE, 900),
            point(T2, OTHER_BREAKDOWN_VALUE, 900),
        ]

        const data = buildSparklineSeries(points, 'count')

        expect(data.series.map((s) => s.label)).toEqual(['api', OTHER_BREAKDOWN_LABEL])
        expect(data.series[1]).toEqual(
            expect.objectContaining({ label: OTHER_BREAKDOWN_LABEL, color: OTHER_BREAKDOWN_COLOR, data: [900, 900] })
        )
        expect(data.total).toEqual(1810)
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

            expect(data.series).toEqual([expect.objectContaining({ label: service, data: [2, 3] })])
            expect(data.total).toEqual(5)
        }
    )

    it('labels a blank service as unknown', () => {
        expect(buildSparklineSeries([point(T1, '', 1)], 'count').series[0].label).toEqual('unknown')
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
