import { dataColorVars } from 'lib/colors'
import { SparklineTimeSeries } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'

export const TOP_SERVICES_LIMIT = 10

/**
 * Mirrors the `LIMIT 1000` in `products/logs/backend/sparkline_query_runner.py`. Rows are
 * (bucket × service), and the query orders by time ascending — so once the cap is hit it's the
 * *newest* buckets that get dropped, and any total derived from the response is an undercount.
 */
export const SPARKLINE_ROW_LIMIT = 1000

export type LogsFilterPreviewMetric = 'count' | 'bytes'

export interface LogsFilterPreviewPoint {
    time: string
    service: string
    count: number
    bytes_uncompressed?: number
}

export interface LogsFilterPreviewSeriesData {
    labels: string[]
    series: SparklineTimeSeries[]
    total: number
    truncatedServiceCount: number
    /** Width of one bar/bucket in seconds; needed to translate a per-second rate limit into per-bucket units. */
    bucketSeconds: number
    /** Tallest stacked total across buckets; used to position the rate-limit reference line. */
    chartMax: number
    bucketCount: number
    firstBucketTime: string | null
}

export function buildSparklineSeries(
    points: LogsFilterPreviewPoint[] | null,
    metric: LogsFilterPreviewMetric
): LogsFilterPreviewSeriesData {
    const timeOrder: string[] = []
    const seenTimes = new Set<string>()
    // A Map, not a plain object: service names come from ingested logs, so a log claiming
    // `service.name: "__proto__"` would otherwise resolve to an inherited value instead of a
    // bucket and throw on `.set`, taking the whole editor down.
    const byService = new Map<string, Map<string, number>>()
    const serviceTotals = new Map<string, number>()
    const bucketTotals = new Map<string, number>()
    let total = 0
    // No early return for the empty case — the accumulators below already yield the zeroed shape,
    // so a separate literal would just be a second copy of it to keep in sync.
    for (const point of points ?? []) {
        if (!seenTimes.has(point.time)) {
            seenTimes.add(point.time)
            timeOrder.push(point.time)
        }
        const svc = point.service || 'unknown'
        const value = metric === 'bytes' ? (point.bytes_uncompressed ?? 0) : point.count
        let bucket = byService.get(svc)
        if (!bucket) {
            bucket = new Map()
            byService.set(svc, bucket)
        }
        bucket.set(point.time, (bucket.get(point.time) ?? 0) + value)
        serviceTotals.set(svc, (serviceTotals.get(svc) ?? 0) + value)
        bucketTotals.set(point.time, (bucketTotals.get(point.time) ?? 0) + value)
        total += value
    }
    const labels = timeOrder.map((t) => dayjs(t).format('D MMM HH:mm'))
    const rankedServices = Array.from(serviceTotals.entries()).sort(([, a], [, b]) => b - a)
    const topServices = rankedServices.slice(0, TOP_SERVICES_LIMIT)
    const otherServices = rankedServices.slice(TOP_SERVICES_LIMIT)
    const truncatedServiceCount = otherServices.length
    const series: SparklineTimeSeries[] = topServices.map(([service], index) => ({
        name: service,
        color: dataColorVars[index % dataColorVars.length],
        values: timeOrder.map((t) => byService.get(service)?.get(t) ?? 0),
    }))
    if (otherServices.length > 0) {
        // Roll up the long tail into a single "Others" series so the chart still adds up to total volume,
        // and the rate-limit reference line lines up against an honest stacked max.
        const othersValues = timeOrder.map((t) =>
            otherServices.reduce((sum, [service]) => sum + (byService.get(service)?.get(t) ?? 0), 0)
        )
        series.push({
            name: `Others (${otherServices.length} services)`,
            color: 'muted',
            values: othersValues,
        })
    }
    const bucketSeconds = timeOrder.length >= 2 ? dayjs(timeOrder[1]).diff(dayjs(timeOrder[0]), 'second') : 0
    const chartMax = Math.max(0, ...Array.from(bucketTotals.values()))
    return {
        labels,
        series,
        total,
        truncatedServiceCount,
        bucketSeconds,
        chartMax,
        bucketCount: timeOrder.length,
        firstBucketTime: timeOrder[0] ?? null,
    }
}

/**
 * Decimal (1000-based) units, matching how logs usage is billed in `posthog/tasks/usage_report.py`.
 * Goes up to PB because a multi-week retained total is routinely several TB.
 */
export function formatBytes(bytes: number): string {
    if (bytes < 1000) {
        return `${bytes.toLocaleString()} B`
    }
    if (bytes < 1_000_000) {
        return `${(bytes / 1000).toFixed(1)} KB`
    }
    if (bytes < 1_000_000_000) {
        return `${(bytes / 1_000_000).toFixed(1)} MB`
    }
    if (bytes < 1_000_000_000_000) {
        return `${(bytes / 1_000_000_000).toFixed(2)} GB`
    }
    if (bytes < 1_000_000_000_000_000) {
        return `${(bytes / 1_000_000_000_000).toFixed(2)} TB`
    }
    return `${(bytes / 1_000_000_000_000_000).toFixed(2)} PB`
}
