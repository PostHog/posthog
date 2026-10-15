import type { ReferenceLineProps } from '@posthog/quill-charts'

import type { TrendsQuery } from '~/queries/schema/schema-general'

import type { ReportMetricSeriesPoints } from './reportMetrics'

export interface ReportMonitoringChartWindow {
    referencePeriodMinutes: number
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

export function monitoringChartPoints(points: ReportMetricSeriesPoints, now: number): ReportMetricSeriesPoints {
    return {
        labels: points.labels,
        // Trends fills future buckets with zero; they are unobserved rather than successful checks.
        values: points.values.map((value, index) => (Date.parse(points.labels[index]) > now ? NaN : value)),
    }
}

export function monitoringChartMarkers(
    labels: string[],
    monitoring: ReportMonitoringChartWindow,
    now: number
): ReferenceLineProps[] {
    const bucketFor = (at: number): string | undefined => {
        const dates = labels.map((label) => Date.parse(label))
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
