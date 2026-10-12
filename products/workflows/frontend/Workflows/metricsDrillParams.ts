import type { AppMetricsCommonParams } from 'lib/components/AppMetrics/appMetricsLogic'
import { urls } from 'scenes/urls'

type MetricsRange = Pick<AppMetricsCommonParams, 'dateFrom' | 'dateTo' | 'interval'>

const INTERVALS: NonNullable<AppMetricsCommonParams['interval']>[] = ['day', 'hour', 'minute']

/** Links to one step on the Metrics tab, keeping the date range the link was clicked from. */
export function metricsStepUrl(id: string, actionId: string, range: MetricsRange): string {
    const search = new URLSearchParams({ action: actionId })
    if (range.dateFrom) {
        search.set('date_from', range.dateFrom)
    }
    if (range.dateTo) {
        search.set('date_to', range.dateTo)
    }
    if (range.interval) {
        search.set('interval', range.interval)
    }
    return `${urls.workflow(id, 'metrics')}?${search.toString()}`
}

/** Reads the date range a Metrics tab link carries. Values that are not strings or not known intervals are ignored. */
export function metricsRangeFromSearchParams(searchParams: Record<string, unknown>): MetricsRange {
    const range: MetricsRange = {}
    if (typeof searchParams.date_from === 'string') {
        range.dateFrom = searchParams.date_from
    }
    if (typeof searchParams.date_to === 'string') {
        range.dateTo = searchParams.date_to
    }
    const interval = INTERVALS.find((value) => value === searchParams.interval)
    if (interval) {
        range.interval = interval
    }
    return range
}
