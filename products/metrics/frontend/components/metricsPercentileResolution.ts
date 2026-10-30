/** A histogram percentile is interpolated inside the bucket that holds it, so it can only be as sharp as
 * that bucket. A bucket whose upper edge is this many times its lower edge makes the line look precise
 * while it only says "somewhere between these two edges". Exponential histograms stay far below it. */
const COARSE_BUCKET_RATIO = 2
/** Suggested custom edges grow by this factor, so the true value is at most about 25% from the estimate. */
const SUGGESTED_EDGE_STEP = 1.5
const MAX_SUGGESTED_EDGES = 12

export interface PercentileResolution {
    /** Every bucket upper edge the percentiles were estimated from. */
    edges: number[]
    /** The bucket that holds the most plotted points. `upper` is Infinity for the overflow bucket. */
    lower: number
    upper: number
    /** Fraction of the plotted points in that bucket. */
    share: number
}

interface PercentileSeries {
    histogram_bounds?: number[] | null
    points: { value: number | null }[]
}

/** The index of the first edge >= `value` in an ascending array, or -1 past the last edge. Mirrors
 * `bounds.findIndex((bound) => value <= bound)`, but in O(log n): a histogram can carry tens of
 * thousands of edges, and this runs per plotted point. */
function upperEdgeIndex(bounds: number[], value: number): number {
    let low = 0
    let high = bounds.length
    while (low < high) {
        const mid = (low + high) >>> 1
        if (bounds[mid] >= value) {
            high = mid
        } else {
            low = mid + 1
        }
    }
    return low === bounds.length ? -1 : low
}

/** The bucket that limits the percentile lines on a chart, or null when the buckets are fine enough. */
export function coarsePercentileResolution(series: PercentileSeries[]): PercentileResolution | null {
    const edges = new Set<number>()
    const bucketCounts = new Map<string, { lower: number; upper: number; count: number }>()
    let total = 0
    for (const { histogram_bounds: bounds, points } of series) {
        if (!bounds?.length) {
            continue
        }
        bounds.forEach((bound) => edges.add(bound))
        for (const { value } of points) {
            if (value === null || !Number.isFinite(value)) {
                continue
            }
            const index = upperEdgeIndex(bounds, value)
            const lower =
                index === -1 ? bounds[bounds.length - 1] : index > 0 ? bounds[index - 1] : Math.min(0, bounds[0])
            const upper = index === -1 ? Infinity : bounds[index]
            const key = `${lower}:${upper}`
            const bucket = bucketCounts.get(key) ?? { lower, upper, count: 0 }
            bucket.count += 1
            bucketCounts.set(key, bucket)
            total += 1
        }
    }
    if (!total) {
        return null
    }
    const busiest = [...bucketCounts.values()].reduce((best, bucket) => (bucket.count > best.count ? bucket : best))
    if (busiest.lower > 0 && busiest.upper / busiest.lower < COARSE_BUCKET_RATIO) {
        return null
    }
    return {
        edges: [...edges].sort((a, b) => a - b),
        lower: busiest.lower,
        upper: busiest.upper,
        share: busiest.count / total,
    }
}

const floorToTwoSignificant = (value: number): number => {
    const magnitude = 10 ** (Math.floor(Math.log10(value)) - 1)
    return Number((Math.floor(value / magnitude) * magnitude).toPrecision(2))
}

/** Custom bucket edges that cover the plotted values with room on both sides. */
export function suggestedBucketEdges(values: number[]): number[] {
    // A loop, not Math.min(...values): a long chart exceeds the engine's argument limit.
    let min = Infinity
    let max = -Infinity
    for (const value of values) {
        if (Number.isFinite(value) && value > 0) {
            min = Math.min(min, value)
            max = Math.max(max, value)
        }
    }
    if (min === Infinity) {
        return []
    }
    const from = min / 2
    const to = max * 2
    const step = Math.max(SUGGESTED_EDGE_STEP, (to / from) ** (1 / (MAX_SUGGESTED_EDGES - 1)))
    const edges: number[] = []
    for (let edge = from; edges.length < MAX_SUGGESTED_EDGES; edge *= step) {
        edges.push(floorToTwoSignificant(edge))
        if (edges[edges.length - 1] >= to) {
            break
        }
    }
    return [...new Set(edges)]
}

/** Copy-paste examples that set custom buckets. Ingested names go in as escaped string literals, so a
 * crafted metric name or unit cannot add code to the snippet. */
export function customBucketSnippet(metric: string, unit: string, edges: number[]): string {
    const list = edges.join(', ')
    return [
        '# OpenTelemetry',
        'meter.create_histogram(',
        `    ${JSON.stringify(metric)},`,
        `    unit=${JSON.stringify(unit)},`,
        `    explicit_bucket_boundaries_advisory=[${list}],`,
        ')',
        '',
        '# Prometheus client',
        'Histogram(',
        `    ${JSON.stringify(metric)},`,
        '    "...",',
        `    buckets=[${list}, float("inf")],`,
        ')',
    ].join('\n')
}
