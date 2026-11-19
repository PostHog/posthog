import type { AppMetricsCommonParams } from 'lib/components/AppMetrics/appMetricsLogic'
import { urls } from 'scenes/urls'

type MetricsRange = Pick<AppMetricsCommonParams, 'dateFrom' | 'dateTo' | 'interval'>

const INTERVALS: NonNullable<AppMetricsCommonParams['interval']>[] = ['day', 'hour', 'minute']

export function metricsRangeSearchParams(range: MetricsRange): Record<string, string> {
    const search: Record<string, string> = {}
    if (range.dateFrom) {
        search.date_from = range.dateFrom
    }
    if (range.dateTo) {
        search.date_to = range.dateTo
    }
    if (range.interval) {
        search.interval = range.interval
    }
    return search
}

/** Links to one step on the Metrics tab, keeping the date range and the batch run the link was clicked from. */
export function metricsStepUrl(id: string, actionId: string, range: MetricsRange, runId?: string): string {
    const search = new URLSearchParams({ action: actionId, ...metricsRangeSearchParams(range) })
    if (runId) {
        search.set('run', runId)
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
    } else if (range.dateFrom) {
        // A rolling range has no end date, so a stale one from an earlier URL must not survive the merge.
        range.dateTo = undefined
    }
    const interval = INTERVALS.find((value) => value === searchParams.interval)
    if (interval) {
        range.interval = interval
    }
    return range
}
