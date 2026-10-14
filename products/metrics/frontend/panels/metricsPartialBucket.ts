import { dayjs } from 'lib/dayjs'

import type { MetricsAggregation, MetricsQuery } from '~/queries/schema/schema-general'

import type { MetricsChartSeries } from '../components/metricsSeries'

export type MetricsPartialBucketQuery = Pick<MetricsQuery, 'clauses' | 'formula' | 'language'>

/** Below this share of the bucket, scaling up a few samples is mostly noise, so the real value stays. */
export const MIN_EXTRAPOLATION_FRACTION = 0.1

const COUNTER_FUNCTIONS: ReadonlySet<MetricsAggregation> = new Set(['rate', 'increase'])
const ADDITIVE_FORMULA = /^[\w\s.+\-()]*$/

/** How much of the last bucket has elapsed, when that bucket is still in progress. The backend
 * reads data up to "now", so the last bucket of a range ending now holds only part of its window.
 * The bucket length comes from the spacing of the last two buckets: the response does not carry
 * the resolved interval. */
export function partialBucketFraction(times: string[], now: dayjs.Dayjs = dayjs()): number | null {
    if (times.length < 2) {
        return null
    }
    const last = dayjs(times[times.length - 1])
    const length = last.diff(dayjs(times[times.length - 2]))
    const elapsed = now.diff(last)
    if (length <= 0 || elapsed <= 0 || elapsed >= length) {
        return null
    }
    return elapsed / length
}

/** Whether a series' partial bucket grows with elapsed time, so scaling it to the full bucket is
 * correct. True for counter clauses (`rate`, `increase`); `rate` divides by the full bucket length,
 * so it is understated by the same fraction. Point-in-time values (gauges, avg, quantiles) and
 * PromQL/SQL results, whose semantics are unknown here, are not. */
export function isExtrapolatable(series: MetricsChartSeries, query: MetricsPartialBucketQuery | undefined): boolean {
    if (!query || (query.language && query.language !== 'builder')) {
        return false
    }
    const isCounter = (clause: MetricsPartialBucketQuery['clauses'][number]): boolean =>
        (!!clause.rangeFunction && COUNTER_FUNCTIONS.has(clause.rangeFunction)) ||
        (!!clause.aggregation && COUNTER_FUNCTIONS.has(clause.aggregation))
    if (series.clause === 'formula') {
        // Only a sum or difference of counters scales linearly; a ratio of two partial counters does not.
        return (
            !!query.formula &&
            ADDITIVE_FORMULA.test(query.formula) &&
            query.clauses.length > 0 &&
            query.clauses.every(isCounter)
        )
    }
    const clause = query.clauses.find((c) => c.name === series.clause)
    return !!clause && isCounter(clause)
}

export function extrapolatePartialValue(value: number, fraction: number): number {
    return fraction >= MIN_EXTRAPOLATION_FRACTION ? value / fraction : value
}
