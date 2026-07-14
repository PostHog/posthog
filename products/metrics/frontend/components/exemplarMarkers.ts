import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'

// One clickable dot on the chart: a trace-linked emission positioned in its time bucket.
export interface ExemplarMarker {
    /** Chart bucket index the sample falls into. */
    index: number
    /** The sample's recorded value — where the dot sits on the y-axis. */
    value: number
    traceId: string
    spanId: string | null
    /** ISO timestamp of the emission, used to bound the trace lookup. */
    timestamp: string
}

/**
 * Positions trace-linked samples on the chart's bucket grid: nearest bucket by
 * timestamp, newest sample wins per bucket (the endpoint returns newest-first)
 * so a busy bucket renders one dot instead of a smear.
 */
export function exemplarMarkersFromSamples(samples: _MetricEventSampleApi[], bucketTimes: string[]): ExemplarMarker[] {
    if (!samples.length || !bucketTimes.length) {
        return []
    }
    const bucketMs = bucketTimes.map((time) => new Date(time).getTime())
    const byBucket = new Map<number, ExemplarMarker>()
    for (const sample of samples) {
        if (!sample.trace_id) {
            continue
        }
        const sampleMs = new Date(sample.timestamp).getTime()
        if (!Number.isFinite(sampleMs)) {
            continue
        }
        let nearest = 0
        let nearestDistance = Infinity
        for (let i = 0; i < bucketMs.length; i++) {
            const distance = Math.abs(sampleMs - bucketMs[i])
            if (distance < nearestDistance) {
                nearest = i
                nearestDistance = distance
            }
        }
        if (!byBucket.has(nearest)) {
            byBucket.set(nearest, {
                index: nearest,
                value: sample.value,
                traceId: sample.trace_id,
                spanId: sample.span_id || null,
                timestamp: sample.timestamp,
            })
        }
    }
    return Array.from(byBucket.values()).sort((a, b) => a.index - b.index)
}
