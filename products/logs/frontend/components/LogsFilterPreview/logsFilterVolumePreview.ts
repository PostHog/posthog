import type { Series } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import { OTHER_BREAKDOWN_LABEL, OTHER_BREAKDOWN_VALUE } from 'products/logs/frontend/sparklineOtherBreakdown'

/** Must match `SPARKLINE_TOP_BREAKDOWN_VALUES` in `products/logs/backend/sparkline_query_runner.py`. */
export const TOP_SERVICES_LIMIT = 10

/**
 * Mirrors the `LIMIT 1000` in `products/logs/backend/sparkline_query_runner.py`. Rows are
 * (bucket × breakdown value), and the query orders by time ascending — so if the cap were ever hit
 * it would be the *newest* buckets that got dropped, making any total an undercount. The backend
 * now folds the tail into one bucket, which bounds the response at roughly 50 × 11 rows, so this
 * should be unreachable; it stays as a backstop in case the top-N there is ever raised.
 */
export const SPARKLINE_ROW_LIMIT = 1000

export type LogsFilterPreviewMetric = 'count' | 'bytes'

/** How far back the preview query looks. Doubles as the `-{lookback}` relative date_from. */
export type LogsFilterPreviewLookback = '1h' | '24h'

export const DEFAULT_PREVIEW_LOOKBACK: LogsFilterPreviewLookback = '24h'

export interface LogsFilterPreviewPoint {
    time: string
    service: string
    count: number
    bytes_uncompressed?: number
}

/** The collapsed "Others" row reads as an aggregate rather than as another service. Resolved to a
 *  canvas-usable color by the chart — a bar fill can't take `var(--…)`. */
export const OTHER_BREAKDOWN_COLOR = 'var(--muted)'

export interface LogsFilterPreviewSeriesData {
    /** Raw bucket timestamps, one per bar. The chart's time axis formats them for display. */
    labels: string[]
    series: Series[]
    total: number
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
    // Sorted by volume so colours track the biggest talkers, but deliberately not sliced: the
    // backend already folded everything past the top N into one bucket, ranked by this same metric.
    // Slicing again here would re-collapse the collapsed row and label it as a single service.
    const ranked = Array.from(serviceTotals.entries()).sort(([, a], [, b]) => b - a)
    const valuesFor = (service: string): number[] => timeOrder.map((t) => byService.get(service)?.get(t) ?? 0)
    // No explicit colour: the chart assigns the data palette by series index, which is what the
    // volume ranking above is for.
    const series: Series[] = ranked
        .filter(([service]) => service !== OTHER_BREAKDOWN_VALUE)
        .map(([service]) => ({
            key: service,
            label: service,
            data: valuesFor(service),
        }))
    if (serviceTotals.has(OTHER_BREAKDOWN_VALUE)) {
        series.push({
            key: OTHER_BREAKDOWN_VALUE,
            label: OTHER_BREAKDOWN_LABEL,
            color: OTHER_BREAKDOWN_COLOR,
            data: valuesFor(OTHER_BREAKDOWN_VALUE),
        })
    }
    const bucketSeconds = timeOrder.length >= 2 ? dayjs(timeOrder[1]).diff(dayjs(timeOrder[0]), 'second') : 0
    const chartMax = Math.max(0, ...Array.from(bucketTotals.values()))
    return {
        labels: timeOrder,
        series,
        total,
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
