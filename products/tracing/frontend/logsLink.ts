import { combineUrl } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

// Half-width of the time window applied to the Logs view when jumping from a span, centered on the
// span's start time. Logs queries must be time-bounded, and a trace's logs cluster near its spans.
const LOGS_WINDOW_MINUTES = 5

/**
 * Build a Logs scene URL filtered to a single trace. The Logs scene reads `filterGroup` and
 * `dateRange` from search params; we keep the filter shape local here rather than importing Logs
 * internals (product isolation). The Logs backend accepts the hex `trace_id` the span carries.
 */
export function buildTraceLogsUrl(traceId: string, timestamp: string): string {
    const center = dayjs(timestamp)
    const dateRange = {
        date_from: center.subtract(LOGS_WINDOW_MINUTES, 'minute').toISOString(),
        date_to: center.add(LOGS_WINDOW_MINUTES, 'minute').toISOString(),
    }
    const filterGroup = {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        key: 'trace_id',
                        value: [traceId],
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Log,
                    },
                ],
            },
        ],
    }
    return combineUrl(urls.logs(), { filterGroup, dateRange }).url
}
