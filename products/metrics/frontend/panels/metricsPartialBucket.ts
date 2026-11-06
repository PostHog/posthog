import { dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'

import type { MetricsAggregation, MetricsQuery, MetricsQueryClause } from '~/queries/schema/schema-general'

import { ownValue, referencedNames } from '../components/dashboardVariables/metricVariables'
import type { MetricsChartSeries } from '../components/metricsSeries'

export type MetricsPartialBucketQuery = Pick<
    MetricsQuery,
    'clauses' | 'formula' | 'language' | 'dateRange' | 'interval' | 'variables'
>

/** Below this share of the bucket, scaling up a few samples is mostly noise, so the real value stays. */
export const MIN_EXTRAPOLATION_FRACTION = 0.1

const DEFAULT_DATE_FROM = '-24h'
const MINUTE_MS = 60_000
/** Mirrors `_INTERVAL_LADDER`, `_TARGET_BUCKET_COUNT` and `_MAX_BUCKET_COUNT` in backend/metric_query_runner.py. */
const INTERVAL_LADDER: [string, number, string][] = [
    ['second_15', 15_000, '15s'],
    ['second_30', 30_000, '30s'],
    ['minute', MINUTE_MS, '1m'],
    ['minute_5', 5 * MINUTE_MS, '5m'],
    ['minute_15', 15 * MINUTE_MS, '15m'],
    ['minute_30', 30 * MINUTE_MS, '30m'],
    ['hour', 60 * MINUTE_MS, '1h'],
    ['hour_6', 360 * MINUTE_MS, '6h'],
    ['day', 1440 * MINUTE_MS, '1d'],
    ['week', 10080 * MINUTE_MS, '1w'],
]
const TARGET_BUCKET_COUNT = 60
const MAX_BUCKET_COUNT = 500

const COUNTER_FUNCTIONS: ReadonlySet<MetricsAggregation> = new Set(['rate', 'increase'])
const FORMULA_OPERATORS = /[\s()+-]+/

// The backend resolves the range with `exact_timerange`, so a relative date is a rolling window from now.
function resolveDateFrom(dateFrom: string, now: dayjs.Dayjs, timezone: string): dayjs.Dayjs | null {
    const components = dateStringToComponents(dateFrom)
    return components ? componentsToDayJs(components, now, timezone) : dateStringToDayJs(dateFrom, timezone)
}

function resolvedIntervalMs(query: MetricsPartialBucketQuery, now: dayjs.Dayjs, timezone: string): number | null {
    const [variableName] = referencedNames(query.interval)
    if (variableName) {
        const variable = ownValue(query.variables ?? {}, variableName)
        if (!variable || variable.all || variable.values.length !== 1) {
            return null
        }
        return INTERVAL_LADDER.find(([, , duration]) => duration === variable.values[0])?.[1] ?? null
    }
    const from = resolveDateFrom(query.dateRange?.date_from ?? DEFAULT_DATE_FROM, now, timezone)
    if (!from) {
        return null
    }
    const span = now.diff(from)
    let index: number
    if (query.interval) {
        index = INTERVAL_LADDER.findIndex(([name]) => name === query.interval)
        if (index === -1) {
            return null
        }
    } else {
        const pick = INTERVAL_LADDER.findIndex(([, step]) => span / step <= TARGET_BUCKET_COUNT)
        index = pick === -1 ? INTERVAL_LADDER.length - 1 : pick
    }
    while (index < INTERVAL_LADDER.length - 1 && span / INTERVAL_LADDER[index][1] > MAX_BUCKET_COUNT) {
        index++
    }
    return INTERVAL_LADDER[index][1]
}

/** How much of the last bucket has elapsed, when the range ends now and that bucket is still in progress. */
export function partialBucketFraction(
    times: string[],
    query: MetricsPartialBucketQuery | undefined,
    timezone: string = 'UTC',
    now: dayjs.Dayjs = dayjs()
): number | null {
    if (!query || query.dateRange?.date_to || times.length === 0) {
        return null
    }
    const length = resolvedIntervalMs(query, now, timezone)
    if (!length) {
        return null
    }
    const starts = times.map((time) => dayjs(time))
    // Closer buckets mean the chart's range differs from the query's, e.g. a dashboard date override.
    if (starts.some((start, i) => i > 0 && start.diff(starts[i - 1]) < length)) {
        return null
    }
    const elapsed = now.diff(starts[starts.length - 1])
    if (elapsed <= 0 || elapsed >= length) {
        return null
    }
    return elapsed / length
}

function isCounterClause(clause: MetricsQueryClause): boolean {
    if (clause.aggregation && COUNTER_FUNCTIONS.has(clause.aggregation)) {
        return true
    }
    // `count` counts reporting series, which does not grow with elapsed time.
    return !!clause.rangeFunction && COUNTER_FUNCTIONS.has(clause.rangeFunction) && clause.aggregation !== 'count'
}

/** Whether a series' partial bucket grows with elapsed time, so scaling it to the full bucket is correct. */
export function isExtrapolatable(series: MetricsChartSeries, query: MetricsPartialBucketQuery | undefined): boolean {
    if (!query || (query.language && query.language !== 'builder')) {
        return false
    }
    if (series.clause === 'formula') {
        // Only a sum or difference of counter aliases scales linearly. A constant term does not grow with elapsed time.
        const operands = (query.formula ?? '').split(FORMULA_OPERATORS).filter(Boolean)
        return (
            operands.length > 0 &&
            operands.every((alias) => {
                const clause = query.clauses.find((c) => c.name === alias)
                return !!clause && isCounterClause(clause)
            })
        )
    }
    const clause = query.clauses.find((c) => c.name === series.clause)
    return !!clause && isCounterClause(clause)
}

export function extrapolatePartialValue(value: number, fraction: number): number {
    return fraction >= MIN_EXTRAPOLATION_FRACTION ? value / fraction : value
}
