import type {
    TransactionalEmailStatsCountsApi,
    TransactionalEmailStatsOverTimeApi,
} from 'products/messaging/frontend/generated/api.schemas'

export type MetricTileFormat = 'count' | 'rate'

export interface MetricTile {
    key: 'sent' | 'delivered' | 'bounced' | 'complained'
    title: string
    format: MetricTileFormat
    /** The period's value: a count, or a percentage from 0 to 100. Null when there is nothing to divide by. */
    value: number | null
    /** The value for each bucket, in the same unit as `value`. */
    points: number[]
    count: number
    /** What a rate divides by, for the caption. */
    baseLabel: 'sent' | 'delivered' | null
    bases: number[]
    counts: number[]
    /** Percent change for a count, percentage points for a rate. Null when there is nothing to compare with. */
    change: number | null
    goodDirection: 'up' | 'down'
}

function sum(values: number[]): number {
    return values.reduce((total, value) => total + value, 0)
}

function rate(count: number, base: number): number {
    return base > 0 ? (count / base) * 100 : 0
}

/** A rate per bucket. A bucket with nothing to divide by keeps the rate around it, since no sends is not a 0% rate. */
function ratePoints(counts: number[], bases: number[]): number[] {
    const firstKnown = bases.findIndex((base) => base > 0)
    let last = firstKnown >= 0 ? rate(counts[firstKnown], bases[firstKnown]) : 0
    return counts.map((count, index) => {
        if (bases[index] > 0) {
            last = rate(count, bases[index])
        }
        return last
    })
}

function rateTile(
    stats: TransactionalEmailStatsOverTimeApi,
    key: 'delivered' | 'bounced' | 'complained',
    title: string,
    baseKey: 'sent' | 'delivered',
    goodDirection: 'up' | 'down'
): MetricTile {
    const counts = stats.buckets.map((bucket) => bucket.counts[key])
    const bases = stats.buckets.map((bucket) => bucket.counts[baseKey])
    const count = sum(counts)
    const base = sum(bases)
    const previous: TransactionalEmailStatsCountsApi | null = stats.previous
    return {
        key,
        title,
        format: 'rate',
        value: base > 0 ? rate(count, base) : null,
        points: ratePoints(counts, bases),
        count,
        baseLabel: baseKey,
        bases,
        counts,
        change:
            base > 0 && previous && previous[baseKey] > 0
                ? rate(count, base) - rate(previous[key], previous[baseKey])
                : null,
        goodDirection,
    }
}

/** The four summary numbers for the period, with a value per bucket for each trend line. */
export function buildMetricTiles(stats: TransactionalEmailStatsOverTimeApi): MetricTile[] {
    const sent = stats.buckets.map((bucket) => bucket.counts.sent)
    const totalSent = sum(sent)
    const previousSent = stats.previous?.sent ?? 0
    return [
        {
            key: 'sent',
            title: 'Sent',
            format: 'count',
            value: totalSent,
            points: sent,
            count: totalSent,
            baseLabel: null,
            bases: [],
            counts: sent,
            change: previousSent > 0 ? ((totalSent - previousSent) / previousSent) * 100 : null,
            goodDirection: 'up',
        },
        rateTile(stats, 'delivered', 'Delivered', 'sent', 'up'),
        rateTile(stats, 'bounced', 'Bounced', 'sent', 'down'),
        rateTile(stats, 'complained', 'Marked as spam', 'delivered', 'down'),
    ]
}
