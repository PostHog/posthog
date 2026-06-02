import { dayjs } from 'lib/dayjs'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'

// Half-width of the time window applied to the Logs view when jumping from a span, centered on the
// span's start time. Logs queries must be time-bounded, and a trace's logs cluster near its spans.
const LOGS_WINDOW_MINUTES = 5

/**
 * Build the Logs viewer filters that scope to a single trace. We hand these to the Logs viewer
 * modal (which owns turning filters into a scene URL); tracing only expresses *what* to show — a
 * `trace_id` exact match within a window around the span. The Logs backend accepts the hex
 * `trace_id` the span carries.
 */
export function buildTraceLogsFilters(traceId: string, timestamp: string): Partial<LogsViewerFilters> {
    const center = dayjs(timestamp)
    return {
        dateRange: {
            date_from: center.subtract(LOGS_WINDOW_MINUTES, 'minute').toISOString(),
            date_to: center.add(LOGS_WINDOW_MINUTES, 'minute').toISOString(),
        },
        filterGroup: {
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
        },
    }
}
