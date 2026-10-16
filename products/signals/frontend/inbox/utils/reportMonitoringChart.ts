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

export function monitoringChartQuery(
    query: TrendsQuery,
    monitoring: ReportMonitoringChartWindow,
    now: number
): TrendsQuery {
    const startedAt = monitoring.startedAt ? Date.parse(monitoring.startedAt) : NaN
    const anchor = Number.isFinite(startedAt) ? startedAt : now
    const windowMs = monitoring.referencePeriodMinutes * 60_000
    return {
        ...query,
        dateRange: {
            date_from: new Date(anchor - windowMs).toISOString(),
            date_to: new Date(Math.max(anchor + windowMs, now)).toISOString(),
            explicitDate: true,
        },
        compareFilter: undefined,
        interval:
            monitoring.referencePeriodMinutes <= 60
                ? 'minute'
                : monitoring.referencePeriodMinutes <= 1440
                  ? 'hour'
                  : 'day',
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
    const source = asReportMetricTrendsQuery(metric.query)?.source
    if (!source || !monitoring.thresholdScaling) {
        return []
    }
    const filter = source.trendsFilter
    const hasFormula = !!(filter?.formula || filter?.formulas?.length || filter?.formulaNodes?.length)
    const onlySeries = source.series.length === 1 && !hasFormula ? source.series[0] : null
    const math = onlySeries && 'math' in onlySeries ? onlySeries.math : null
    const linear = monitoring.thresholdScaling === 'linear'
    let factor = 1
    if (linear) {
        if (!onlySeries || (math != null && math !== 'total' && math !== 'sum')) {
            return []
        }
        const minutes = uniformBucketMinutes(labels, interval, timezone)
        if (minutes == null || monitoring.referencePeriodMinutes <= 0) {
            return []
        }
        factor = minutes / monitoring.referencePeriodMinutes
    } else if (
        metric.kind !== 'conversion_rate' &&
        metric.kind !== 'error_rate' &&
        !(onlySeries && typeof math === 'string' && LEVEL_MATHS.has(math))
    ) {
        return []
    }
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
                label: `${linear ? 'Goal' : 'Target'}: ${target.sign}${formatted}${linear ? `/${interval} (avg)` : ''}`,
                labelPosition: bounds && index === 0 ? 'start' : 'end',
                showValueOnHover: false,
            },
        ]
    })
}
