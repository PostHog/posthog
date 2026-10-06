import { formatBucketLabel, normalizeBucket } from 'lib/utils/timeBuckets'

import { IntervalType } from '~/types'

export interface InsightMetric {
    /** Null when the period holds nothing the metric can be computed from. */
    value: number | null
    previousValue: number | null
    /** Null when the previous period had nothing to compare against, so the tile shows no change pill. */
    deltaPct: number | null
    sparkline: number[]
    sparklineLabels: string[]
    goodDirection: 'up' | 'down'
}

export interface InsightsMetrics {
    exceptions: InsightMetric
    affectedUsers: InsightMetric
    sessions: InsightMetric
    crashSessions: InsightMetric
    crashFreeRate: InsightMetric
    releases: InsightMetric
}

/** The five aggregates the summary query returns for one period. */
export interface PeriodTotals {
    exceptions: number
    affectedUsers: number
    sessions: number
    crashSessions: number
    releases: number
}

export interface ComparisonTotals {
    current: PeriodTotals
    previous: PeriodTotals
}

/** One bucket of the summary series, already normalized to a bucket key the zero-fill can join on. */
export interface SummaryBucket extends PeriodTotals {
    bucket: string
}

const EMPTY_TOTALS: PeriodTotals = {
    exceptions: 0,
    affectedUsers: 0,
    sessions: 0,
    crashSessions: 0,
    releases: 0,
}

export const EMPTY_COMPARISON_TOTALS: ComparisonTotals = { current: EMPTY_TOTALS, previous: EMPTY_TOTALS }

/**
 * Percentage of sessions that reported no exception, or null when there were no sessions at all.
 * A period with no traffic has no rate: reporting 100% there would claim a clean period on the
 * strength of no evidence, and it would give the comparison a baseline to divide by.
 */
export function crashFreeRate({
    sessions,
    crashSessions,
}: Pick<PeriodTotals, 'sessions' | 'crashSessions'>): number | null {
    return sessions > 0 ? ((sessions - crashSessions) / sessions) * 100 : null
}

/** Per-bucket rate for the sparkline, where a bucket with no sessions draws flat rather than absent. */
function bucketCrashFreeRate(totals: PeriodTotals): number {
    return crashFreeRate(totals) ?? 100
}

function changePct(current: number | null, previous: number | null): number | null {
    if (current === null || previous === null || previous === 0) {
        return current === 0 && previous === 0 ? 0 : null
    }
    return ((current - previous) / previous) * 100
}

export function parseComparisonTotals(rawRows: unknown[][]): ComparisonTotals {
    const row = rawRows[0]
    if (!row) {
        return { current: EMPTY_TOTALS, previous: EMPTY_TOTALS }
    }
    return {
        current: {
            exceptions: Number(row[0] ?? 0),
            affectedUsers: Number(row[2] ?? 0),
            sessions: Number(row[4] ?? 0),
            crashSessions: Number(row[6] ?? 0),
            releases: Number(row[8] ?? 0),
        },
        previous: {
            exceptions: Number(row[1] ?? 0),
            affectedUsers: Number(row[3] ?? 0),
            sessions: Number(row[5] ?? 0),
            crashSessions: Number(row[7] ?? 0),
            releases: Number(row[9] ?? 0),
        },
    }
}

export function parseSummaryBuckets(rawRows: unknown[][]): SummaryBucket[] {
    return rawRows.map((row) => ({
        bucket: normalizeBucket(row[0]),
        exceptions: Number(row[1] ?? 0),
        affectedUsers: Number(row[2] ?? 0),
        sessions: Number(row[3] ?? 0),
        crashSessions: Number(row[4] ?? 0),
        releases: Number(row[5] ?? 0),
    }))
}

/**
 * Headline numbers from the comparison query and sparklines from the per-bucket series.
 *
 * The two come from separate queries because the headline distinct counts (users, sessions, releases)
 * cannot be recovered by summing per-bucket distinct counts: anything active in more than one bucket
 * would be counted once per bucket.
 */
export function buildMetrics(
    totals: ComparisonTotals,
    buckets: SummaryBucket[],
    bucketKeys: string[],
    interval: IntervalType
): InsightsMetrics {
    const byBucket = new Map(buckets.map((bucket) => [bucket.bucket, bucket]))
    const series = bucketKeys.map((key) => byBucket.get(key) ?? EMPTY_TOTALS)
    const sparklineLabels = bucketKeys.map((key) => formatBucketLabel(key, interval))

    const metric = (
        value: number | null,
        previousValue: number | null,
        sparkline: number[],
        goodDirection: 'up' | 'down'
    ): InsightMetric => ({
        value,
        previousValue,
        deltaPct: changePct(value, previousValue),
        sparkline,
        sparklineLabels,
        goodDirection,
    })

    return {
        exceptions: metric(
            totals.current.exceptions,
            totals.previous.exceptions,
            series.map((bucket) => bucket.exceptions),
            'down'
        ),
        affectedUsers: metric(
            totals.current.affectedUsers,
            totals.previous.affectedUsers,
            series.map((bucket) => bucket.affectedUsers),
            'down'
        ),
        sessions: metric(
            totals.current.sessions,
            totals.previous.sessions,
            series.map((bucket) => bucket.sessions),
            'up'
        ),
        crashSessions: metric(
            totals.current.crashSessions,
            totals.previous.crashSessions,
            series.map((bucket) => bucket.crashSessions),
            'down'
        ),
        crashFreeRate: metric(
            crashFreeRate(totals.current),
            crashFreeRate(totals.previous),
            series.map(bucketCrashFreeRate),
            'up'
        ),
        releases: metric(
            totals.current.releases,
            totals.previous.releases,
            series.map((bucket) => bucket.releases),
            'up'
        ),
    }
}
