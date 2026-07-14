import type { _MetricEventSampleApi, _MetricFilterApi } from 'products/metrics/frontend/generated/api.schemas'

// One clickable dot on the chart: a trace-linked emission positioned in its time bucket.
export interface ExemplarMarker {
    /** Chart bucket index the sample falls into. */
    index: number
    /** The matched series' value at that bucket — the dot sits on the line it annotates. */
    value: number
    traceId: string
    spanId: string | null
    /** ISO timestamp of the emission, used to bound the trace lookup. */
    timestamp: string
}

interface ExemplarSeries {
    labels: Record<string, string>
    points: { time: string; value: number | null }[]
}

interface ExemplarOptions {
    groupByKeys: string[]
    filters: _MetricFilterApi[]
}

// The samples endpoint only scopes by metric name and window, so the chart's
// attribute filters are re-applied here — a dot must belong to the plotted data.
// Negative operators match rows lacking the key, mirroring Prometheus matchers.
function matchesFilters(attributes: Record<string, string>, filters: _MetricFilterApi[]): boolean {
    return filters.every((filter) => {
        const value = attributes[filter.key]
        switch (filter.op ?? 'eq') {
            case 'eq':
                return value === filter.value
            case 'neq':
                return value === undefined || value !== filter.value
            case 'regex':
                return value !== undefined && safeRegexTest(filter.value, value)
            case 'not_regex':
                return value === undefined || !safeRegexTest(filter.value, value)
            default:
                return true
        }
    })
}

function safeRegexTest(pattern: string, value: string): boolean {
    try {
        return new RegExp(pattern).test(value)
    } catch {
        return false
    }
}

/**
 * Positions trace-linked samples on the chart: floored into the bucket they
 * aggregated into (buckets are start-timestamped), matched to their series
 * under group-by, filtered like the chart, and pinned to the series value so
 * the dot sits on the line regardless of the chart's aggregation. Newest
 * sample wins per bucket so a busy bucket renders one dot instead of a smear.
 */
export function exemplarMarkersFromSamples(
    samples: _MetricEventSampleApi[],
    series: ExemplarSeries[],
    options: ExemplarOptions
): ExemplarMarker[] {
    const bucketTimes = series[0]?.points.map((point) => point.time) ?? []
    if (!samples.length || !bucketTimes.length) {
        return []
    }
    const bucketMs = bucketTimes.map((time) => new Date(time).getTime())
    // Samples past the final bucket's span are out of window, not part of the last bucket.
    const interval = bucketMs.length > 1 ? bucketMs[1] - bucketMs[0] : Infinity
    const windowEnd = bucketMs[bucketMs.length - 1] + interval

    const byBucket = new Map<number, ExemplarMarker>()
    for (const sample of samples) {
        if (!sample.trace_id) {
            continue
        }
        const sampleMs = new Date(sample.timestamp).getTime()
        if (!Number.isFinite(sampleMs) || sampleMs < bucketMs[0] || sampleMs >= windowEnd) {
            continue
        }
        const attributes = { ...sample.resource_attributes, ...sample.attributes }
        if (!matchesFilters(attributes, options.filters)) {
            continue
        }
        const matchedSeries = options.groupByKeys.length
            ? series.find((candidate) => options.groupByKeys.every((key) => candidate.labels[key] === attributes[key]))
            : series[0]
        if (!matchedSeries) {
            continue
        }
        // Floor to the containing bucket: the last bucket starting at or before the sample.
        let bucket = bucketMs.length - 1
        while (bucket > 0 && bucketMs[bucket] > sampleMs) {
            bucket--
        }
        const seriesValue = matchedSeries.points[bucket]?.value
        if (seriesValue === null || seriesValue === undefined) {
            continue // a dot on a gap would assert data the chart doesn't show
        }
        // Newest sample wins per bucket, regardless of the order the API returned
        // them in, so a busy bucket renders its most recent trace, not a random one.
        const existing = byBucket.get(bucket)
        if (!existing || sampleMs > new Date(existing.timestamp).getTime()) {
            byBucket.set(bucket, {
                index: bucket,
                value: seriesValue,
                traceId: sample.trace_id,
                spanId: sample.span_id || null,
                timestamp: sample.timestamp,
            })
        }
    }
    return Array.from(byBucket.values()).sort((a, b) => a.index - b.index)
}
