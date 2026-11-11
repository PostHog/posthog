import type { GoalLineConfig, ReferenceLineProps } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import type { TrendsQuery } from '~/queries/schema/schema-general'
import { PropertyMathType } from '~/types'

import type { MonitoringMetricConfigApi, ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { asReportMetricTrendsQuery, formatReportMetricParts, type ReportMetricSeriesPoints } from './reportMetrics'

export interface ReportMonitoringChartWindow {
    referencePeriodMinutes: number
    thresholdScaling?: MonitoringMetricConfigApi['threshold_scaling']
    startedAt?: string | null
}

const MINUTE_MS = 60_000
const MAX_CHART_POINTS = 1000

function monitoringChartDateRange(monitoring: ReportMonitoringChartWindow, now: number): { from: number; to: number } {
    const startedAt = monitoring.startedAt ? Date.parse(monitoring.startedAt) : NaN
    // Stable dynamic boundaries let repeated views share query-cache entries.
    const refreshedAt = Math.floor(now / MINUTE_MS) * MINUTE_MS
    const anchor = Number.isFinite(startedAt) ? startedAt : refreshedAt
    const windowMs = monitoring.referencePeriodMinutes * MINUTE_MS
    return { from: anchor - windowMs, to: Math.max(anchor + windowMs, refreshedAt) }
}

function monitoringChartInterval(from: number, to: number): NonNullable<TrendsQuery['interval']> {
    const minutes = (to - from) / MINUTE_MS
    if (minutes <= 120) {
        return 'minute'
    }
    if (minutes <= 2880) {
        return 'hour'
    }
    // Use the shortest calendar buckets, including DST, and allow for partial edge buckets.
    const intervals = [
        ['day', 23 * 60],
        ['week', (7 * 24 - 1) * 60],
        ['month', (28 * 24 - 1) * 60],
        ['year', (365 * 24 - 1) * 60],
    ] as const
    const interval = intervals.find(([, bucketMinutes]) => Math.ceil(minutes / bucketMinutes) + 2 <= MAX_CHART_POINTS)
    if (!interval) {
        throw new Error('The Monitoring chart window exceeds the chart point budget.')
    }
    return interval[0]
}

export function monitoringChartQuery(
    query: TrendsQuery,
    monitoring: ReportMonitoringChartWindow,
    now: number
): TrendsQuery {
    const { from, to } = monitoringChartDateRange(monitoring, now)
    return {
        ...query,
        dateRange: {
            ...query.dateRange,
            date_from: new Date(from).toISOString(),
            date_to: new Date(to).toISOString(),
            explicitDate: true,
        },
        compareFilter: undefined,
        interval: monitoringChartInterval(from, to),
    }
}

function bucketTimestamp(label: string, timezone: string): number {
    return /(?:Z|[+-]\d{2}:\d{2})$/i.test(label) ? dayjs(label).valueOf() : dayjs.tz(label, timezone).valueOf()
}

export function monitoringChartPoints(
    points: ReportMetricSeriesPoints,
    now: number,
    timezone: string
): ReportMetricSeriesPoints {
    return {
        labels: points.labels,
        // Trends fills future buckets with zero; they are unobserved rather than successful checks.
        values: points.values.map((value, index) =>
            bucketTimestamp(points.labels[index], timezone) > now ? NaN : value
        ),
    }
}

export function monitoringChartMarkers(
    labels: string[],
    monitoring: ReportMonitoringChartWindow,
    now: number,
    timezone: string
): ReferenceLineProps[] {
    const bucketFor = (at: number): string | undefined => {
        const dates = labels.map((label) => bucketTimestamp(label, timezone))
        if (!dates.length || at < dates[0]) {
            return undefined
        }
        return labels[dates.findLastIndex((date) => date <= at)]
    }
    const start = monitoring.startedAt ? bucketFor(Date.parse(monitoring.startedAt)) : undefined
    const current = bucketFor(now)
    if (start && start !== current) {
        return [
            {
                value: start,
                orientation: 'vertical',
                variant: 'marker',
                label: 'Monitoring start',
                labelPosition: 'start',
                style: { color: 'var(--text-secondary)' },
            },
            ...(current
                ? [
                      {
                          value: current,
                          orientation: 'vertical' as const,
                          variant: 'marker' as const,
                          label: 'Now',
                          style: { color: 'var(--text-secondary)', stroke: 'dashed' as const },
                      },
                  ]
                : []),
        ]
    }
    return current
        ? [
              {
                  value: current,
                  orientation: 'vertical',
                  variant: 'marker',
                  label: start ? 'Monitoring start / now' : 'Now',
                  labelPosition: 'start',
                  style: { color: 'var(--text-secondary)' },
              },
          ]
        : []
}

const LEVEL_MATHS: Set<string> = new Set([
    PropertyMathType.Average,
    PropertyMathType.Minimum,
    PropertyMathType.Maximum,
    PropertyMathType.Median,
    PropertyMathType.P75,
    PropertyMathType.P90,
    PropertyMathType.P95,
    PropertyMathType.P99,
])

function uniformBucketMinutes(labels: string[], interval: TrendsQuery['interval'], timezone: string): number | null {
    if (interval === 'minute') {
        return 1
    }
    if (interval === 'hour') {
        return 60
    }
    if (interval !== 'day' || !labels.length) {
        return null
    }
    const durations = labels.map((label) => {
        const start = dayjs(bucketTimestamp(label, timezone)).tz(timezone)
        const next = dayjs.tz(start.add(1, 'day').format('YYYY-MM-DD'), timezone)
        return (next.valueOf() - start.valueOf()) / 60_000
    })
    // One horizontal reference cannot represent unequal bucket durations around daylight-saving changes.
    return durations[0] > 0 && durations.every((minutes) => minutes === durations[0]) ? durations[0] : null
}

function singleMetricSeries(source: TrendsQuery): TrendsQuery['series'][number] | null {
    const filter = source.trendsFilter
    const hasFormula = !!(filter?.formula || filter?.formulas?.length || filter?.formulaNodes?.length)
    return source.series.length === 1 && !hasFormula ? source.series[0] : null
}

function isAdditiveMetricSeries(series: TrendsQuery['series'][number]): boolean {
    const math = 'math' in series ? series.math : null
    if (math == null || math === 'total') {
        return true
    }
    // A session can contribute once to each bucket, but only once to the full window.
    return (
        math === 'sum' &&
        !('math_property' in series && series.math_property === '$session_duration') &&
        !('math_property_type' in series && series.math_property_type === 'session_properties')
    )
}

function monitoringTargetFactor(
    metric: ReportMetricApi,
    monitoring: ReportMonitoringChartWindow,
    interval: TrendsQuery['interval'],
    labels: string[],
    timezone: string
): number | null {
    const source = asReportMetricTrendsQuery(metric.query)?.source
    if (!source || !monitoring.thresholdScaling) {
        return null
    }
    const onlySeries = singleMetricSeries(source)
    const math = onlySeries && 'math' in onlySeries ? onlySeries.math : null
    if (monitoring.thresholdScaling === 'fixed') {
        return metric.kind === 'conversion_rate' ||
            metric.kind === 'error_rate' ||
            (onlySeries && typeof math === 'string' && LEVEL_MATHS.has(math))
            ? 1
            : null
    }
    if (!onlySeries || !isAdditiveMetricSeries(onlySeries)) {
        return null
    }
    const minutes = uniformBucketMinutes(labels, interval, timezone)
    return minutes != null && monitoring.referencePeriodMinutes > 0 ? minutes / monitoring.referencePeriodMinutes : null
}

export function monitoringChartTargetLines({
    metric,
    monitoring,
    interval,
    labels,
    timezone,
    bounds,
}: {
    metric: ReportMetricApi
    monitoring: ReportMonitoringChartWindow
    interval: TrendsQuery['interval']
    labels: string[]
    timezone: string
    bounds?: { lower: number; upper: number } | null
}): GoalLineConfig[] {
    const factor = monitoringTargetFactor(metric, monitoring, interval, labels, timezone)
    if (factor == null) {
        return []
    }
    const linear = monitoring.thresholdScaling === 'linear'
    const targets = bounds
        ? [
              { value: bounds.lower, sign: '≥' },
              { value: bounds.upper, sign: '≤' },
          ]
        : metric.goal_value != null
          ? [{ value: metric.goal_value, sign: metric.goal_direction === 'at_most' ? '≤' : '≥' }]
          : []
    return targets.flatMap((target, index) => {
        const value = target.value * factor
        const formatted = formatReportMetricParts(
            { ...metric, value_format: metric.value_format === 'count' ? 'number' : metric.value_format },
            value
        )?.value
        if (!formatted) {
            return []
        }
        return [
            {
                value,
                label: `${linear ? 'Goal' : 'Target'}: ${target.sign}${formatted}${linear ? `/${interval}` : ''}`,
                labelPosition: bounds && index === 0 ? 'start' : 'end',
                showValueOnHover: false,
            },
        ]
    })
}
